"""
Smart Cut — pure logic (host-testable, no subprocess/ffmpeg/cv2).

This module holds the transcript-analysis and timeline-building half of Smart
Cut: filler-word indexing, drop-range arithmetic, silence/gap detection, the
LRU cache primitives, and the auto-editor v3 timeline builder. Everything here
is deterministic pure Python (only stdlib + os.path), so it runs in the fast
host test tier.

The impure orchestrator (ffmpeg/auto-editor rendering, probing, subprocess,
per-clip locks, the public ``smart_cut`` entrypoint) lives in ``smartcut.py``,
which re-exports every name below for backwards compatibility.
"""

import hashlib
import json
import math
import logging
import os
import re
import threading

logger = logging.getLogger(__name__)


# Filler words by language. Each entry can be a single word OR a multi-word
# phrase ("you know", "uh huh"). The matcher below builds an n-gram lookup
# so multi-word phrases actually match (the previous single-token-only set
# lookup made all multi-word entries dead config).
#
# This dict can be EXTENDED at runtime: if `data/filler_words.json` exists,
# its entries are merged into FILLER_WORDS via _load_external_filler_config()
# at first use. Operators can add domain jargon (e.g. company-specific
# verbal tics) without editing source code.
FILLER_WORDS = {
    "it": {"ehm", "uhm", "eh", "ah", "mhm", "cioe", "cioè", "tipo", "praticamente",
           "diciamo", "insomma", "ecco", "allora", "niente", "vabbè", "vabbe"},
    "en": {"um", "uh", "uh huh", "like", "you know", "basically", "actually",
           "so yeah", "i mean", "right", "well", "anyway"},
    "es": {"ehm", "pues", "bueno", "o sea", "tipo", "digamos", "este"},
    "fr": {"euh", "ben", "genre", "en fait", "du coup", "voilà", "bah"},
    "de": {"ähm", "also", "halt", "sozusagen", "quasi", "na ja"},
}

# Path to optional external filler config. JSON shape: {"<lang>": ["word1", ...]}
# Resolved relative to the current working directory (both the FastAPI
# backend and the Docker container launch from the repo root → /app).
# Using a bare relative path silently broke when the pipeline was invoked
# from a different CWD; absolutizing up-front keeps this predictable.
EXTERNAL_FILLER_CONFIG = os.environ.get(
    "AE_FILLER_CONFIG",
    os.path.abspath(os.path.join("data", "filler_words.json")),
)
_filler_external_loaded = False
_filler_external_lock = threading.Lock()

DEFAULT_LANG = "en"

# Gaps longer than this between words are considered "dead silence"
SILENCE_THRESHOLD = float(os.environ.get("AE_SILENCE_THRESHOLD", "0.8"))

# Minimum silence kept around the cut (one breath, avoids whiplash edits)
SILENCE_KEEP = float(os.environ.get("AE_SILENCE_KEEP", "0.3"))

# Regex that strips ALL non-alphanumeric chars (unicode-aware) for the
# filler-word lookup. Replaces the .strip('.,!?') hack which missed
# parentheses, brackets, quotes (straight and typographic), em-dash, etc.
_NORM_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize_token(text: str) -> str:
    """Lowercase + strip punctuation + collapse whitespace."""
    return _NORM_RE.sub("", text).strip().lower()


def _load_external_filler_config() -> None:
    """Merge entries from EXTERNAL_FILLER_CONFIG into FILLER_WORDS once.

    Idempotent + thread-safe. If the file is missing, malformed, or any I/O
    error occurs, we log a debug message and skip silently — the built-in
    FILLER_WORDS remain in effect.
    """
    global _filler_external_loaded
    if _filler_external_loaded:
        return
    with _filler_external_lock:
        if _filler_external_loaded:
            return
        _filler_external_loaded = True
        path = EXTERNAL_FILLER_CONFIG
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                external = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("smartcut: external filler config %s failed to load: %s", path, e)
            return
        if not isinstance(external, dict):
            logger.debug("smartcut: external filler config %s is not a JSON object", path)
            return
        added = 0
        for lang, entries in external.items():
            if not isinstance(entries, list):
                continue
            bucket = FILLER_WORDS.setdefault(lang, set())
            for entry in entries:
                if isinstance(entry, str) and entry.strip():
                    bucket.add(entry.strip())
                    added += 1
        if added:
            logger.info("smartcut: merged %d external filler entries from %s", added, path)


def _build_filler_index(lang: str) -> tuple[set[str], int]:
    """Compile the filler list for a language into (phrase_set, max_ngram).

    Returns the set of normalized filler phrases and the maximum number
    of words across all phrases — used to drive the n-gram window size.
    Side effect: triggers a one-time external config merge.
    """
    _load_external_filler_config()
    raw = FILLER_WORDS.get(lang, FILLER_WORDS[DEFAULT_LANG])
    phrases: set[str] = set()
    max_n = 1
    for entry in raw:
        norm = _normalize_token(entry)
        if not norm:
            continue
        phrases.add(norm)
        max_n = max(max_n, len(norm.split()))
    return phrases, max_n


def _segments_hash(segments: list[tuple[float, float]], lang: str) -> str:
    """Stable short hash for an output filename. Encodes the actual cut plan
    + language so a re-run with different params produces a different file
    (no false-positive cache hit on language change).
    """
    payload = json.dumps(
        {"lang": lang or "", "segs": [(round(s, 3), round(e, 3)) for s, e in segments]},
        separators=(",", ":"),
    )
    return hashlib.sha1(payload.encode(), usedforsecurity=False).hexdigest()[:10]


# ---------------------------------------------------------------------------
# LRU cache primitives (pure dict arithmetic; the caches themselves live in
# smartcut.py next to the probe functions that fill them).
# ---------------------------------------------------------------------------

_CACHE_LIMIT = 256


def _cache_get(cache: dict, key):
    """LRU read: return the cached value and mark `key` most-recently-used."""
    if key in cache:
        val = cache.pop(key)
        cache[key] = val  # reinsert at the end (most recently used)
        return val
    return None


def _cache_put(cache: dict, key, value, limit: int = _CACHE_LIMIT) -> None:
    """LRU write: insert and evict the least-recently-used entry past `limit`."""
    cache.pop(key, None)
    cache[key] = value
    if len(cache) > limit:
        cache.pop(next(iter(cache)))  # front == least recently used


# ---------------------------------------------------------------------------
# Manual trim — interactive transcript-driven cut (ported idea from
# x007xyz/flycut-caption, see docs/flycut-caption-analysis.md). flycut lets a
# user delete subtitle segments and cuts the matching video intervals; our
# Smart Cut was auto-only. `drop_ranges` lets a caller hand-pick spans to
# remove ON TOP OF (or instead of) the automatic filler/silence detection.
# Pure-math + host-unit-tested — no ffmpeg, no cv2.
# ---------------------------------------------------------------------------

def normalize_drop_ranges(raw, *, max_ranges: int = 500):
    """Coerce caller-supplied drop spans into a clean list of (start, end)
    float tuples in clip-relative seconds.

    Tolerant by design — the input comes straight off an HTTP body. Accepts
    `[[s, e], ...]` or `[{"start": s, "end": e}, ...]`. Silently discards
    malformed entries, non-positive spans, and anything past `max_ranges`
    (an abuse cap). Returns `[]` for falsy/garbage input so the caller can
    treat "no manual drops" uniformly.
    """
    if not raw:
        return []
    out: list[tuple[float, float]] = []
    for item in raw:
        try:
            if isinstance(item, dict):
                s, e = float(item["start"]), float(item["end"])
            else:
                s, e = float(item[0]), float(item[1])
        except (TypeError, ValueError, KeyError, IndexError):
            continue
        if math.isfinite(s) and math.isfinite(e) and e > s >= 0:
            out.append((s, e))
        if len(out) >= max_ranges:
            break
    return out


def clip_transcript_segments(transcript, clip_start, clip_end):
    """Return the transcript broken into editable segments within a clip's
    [clip_start, clip_end] window, with times made clip-relative (seconds from
    the clip's own start). Feeds the interactive manual-trim UI.

    Each segment: {"index", "text", "start", "end"}. Prefers the transcript's
    own segment boundaries (Deepgram utterances / Whisper sentences); within a
    segment, only the words that fall inside the clip window contribute to the
    text + timing, so a segment straddling the clip edge is trimmed cleanly.
    Falls back to the segment-level text/timing when per-word timing is absent.
    """
    out = []
    for seg in transcript.get("segments", []):
        words = seg.get("words") or []
        in_words = [w for w in words
                    if w.get("end", 0) > clip_start and w.get("start", 0) < clip_end]
        if in_words:
            s = max(0.0, in_words[0]["start"] - clip_start)
            e = max(s, in_words[-1]["end"] - clip_start)
            text = " ".join(w["word"].strip() for w in in_words).strip()
        else:
            s_abs, e_abs = seg.get("start"), seg.get("end")
            if s_abs is None or e_abs is None:
                continue
            if e_abs <= clip_start or s_abs >= clip_end:
                continue
            s = max(0.0, s_abs - clip_start)
            e = max(s, min(e_abs, clip_end) - clip_start)
            text = (seg.get("text") or "").strip()
        if not text:
            continue
        out.append({"index": len(out), "text": text,
                    "start": round(s, 3), "end": round(e, 3)})
    return out


def subtract_ranges(keep_segments, drop_ranges):
    """Remove `drop_ranges` from `keep_segments`. Both are lists of (start, end)
    seconds; returns the trimmed keep list, splitting a kept span when a drop
    falls inside it. Pure interval arithmetic — the engine behind manual trim.

    Example: keep [(0, 10)] minus drop [(3, 5)] → [(0, 3), (5, 10)].
    """
    if not drop_ranges:
        return [seg for seg in keep_segments if seg[1] > seg[0]]
    drops = sorted((s, e) for s, e in drop_ranges if e > s)
    result: list[tuple[float, float]] = []
    for ks, ke in keep_segments:
        if ke <= ks:
            continue
        cursor = ks
        for ds, de in drops:
            if de <= cursor or ds >= ke:
                continue  # no overlap with the remaining kept span
            if ds > cursor:
                result.append((cursor, min(ds, ke)))
            cursor = max(cursor, de)
            if cursor >= ke:
                break
        if cursor < ke:
            result.append((cursor, ke))
    return [seg for seg in result if seg[1] > seg[0]]


# ---------------------------------------------------------------------------
# Stage 1A — analyze the transcript
# ---------------------------------------------------------------------------

def analyze_silences(transcript, clip_start, clip_end, language=None, drop_ranges=None):
    """Inspect word timestamps and produce a list of (start, end) segments
    to KEEP, expressed in seconds relative to `clip_start`.

    Two filter passes:
    1. **Multi-word filler matching** via n-gram lookahead. Phrases like
       "you know" or "uh huh" now actually match (the previous single-token
       set lookup made multi-word entries dead config).
    2. **Inter-word silence gaps** longer than SILENCE_THRESHOLD.

    Punctuation is normalized via _normalize_token() so "(uh,)" and "ehm;"
    are detected (the previous .strip('.,!?') hack missed brackets, quotes,
    semicolons, em-dashes, and unicode punctuation).
    """
    lang = (language or DEFAULT_LANG).lower()[:2]
    fillers, max_ngram = _build_filler_index(lang)

    words = []
    for segment in transcript.get('segments', []):
        for word_info in segment.get('words', []):
            if word_info['end'] > clip_start and word_info['start'] < clip_end:
                words.append({
                    'word': word_info['word'].strip(),
                    'norm': _normalize_token(word_info['word']),
                    'start': max(0, word_info['start'] - clip_start),
                    'end': max(0, word_info['end'] - clip_start),
                })

    clip_duration = clip_end - clip_start
    drops = normalize_drop_ranges(drop_ranges)

    if not words:
        # Whisper sometimes returns segment-level timestamps without per-word
        # timing (faster_whisper word_timestamps=False). Manual drops don't
        # need word timing — they're absolute spans — so still honour them by
        # cutting against the whole clip. Auto detection just no-ops.
        if drops:
            kept = subtract_ranges([(0.0, clip_duration)], drops)
            kept_dur = sum(e - s for s, e in kept)
            return kept, {
                "original_duration": round(clip_duration, 1),
                "new_duration": round(kept_dur, 1),
                "time_saved": round(clip_duration - kept_dur, 1),
                "silences_removed": 0,
                "fillers_removed": 0,
                "manual_drops": len(drops),
                "segments": len(kept),
            }
        if not any('words' in s for s in transcript.get('segments', [])):
            logger.info("smartcut: transcript has no word-level timestamps; nothing to cut")
        return [], {"error": "No words found in clip range"}

    # Pre-compute filler skip mask using n-gram lookahead.
    # word_skip[i] = True if `words[i]` is part of a filler phrase
    word_skip = [False] * len(words)
    i = 0
    while i < len(words):
        matched = False
        # Try the longest n-gram first so "uh huh" beats "uh"
        for n in range(min(max_ngram, len(words) - i), 0, -1):
            phrase = " ".join(words[i + k]['norm'] for k in range(n))
            if phrase in fillers:
                for k in range(n):
                    word_skip[i + k] = True
                i += n
                matched = True
                break
        if not matched:
            i += 1

    segments_to_keep: list[tuple[float, float]] = []
    removed_silences = 0
    removed_fillers = 0

    current_start = 0.0

    for idx, word in enumerate(words):
        if word_skip[idx]:
            if current_start < word['start']:
                segments_to_keep.append((current_start, word['start']))
            current_start = word['end']
            removed_fillers += 1
            continue

        if idx > 0:
            prev_end = words[idx - 1]['end']
            gap = word['start'] - prev_end
            if gap > SILENCE_THRESHOLD:
                segments_to_keep.append((current_start, prev_end + SILENCE_KEEP))
                current_start = max(0, word['start'] - 0.05)
                removed_silences += 1

    if words:
        final_end = min(clip_duration, words[-1]['end'] + 0.2)
        segments_to_keep.append((current_start, final_end))

    # Merge near-touching segments (gap < 0.1s)
    merged: list[tuple[float, float]] = []
    for seg in segments_to_keep:
        if seg[1] <= seg[0]:
            continue
        if merged and seg[0] - merged[-1][1] < 0.1:
            merged[-1] = (merged[-1][0], seg[1])
        else:
            merged.append(seg)

    # Manual trim: subtract caller-picked spans on top of the auto cut.
    if drops:
        merged = subtract_ranges(merged, drops)

    new_duration = sum(end - start for start, end in merged)
    stats = {
        "original_duration": round(clip_duration, 1),
        "new_duration": round(new_duration, 1),
        "time_saved": round(clip_duration - new_duration, 1),
        "silences_removed": removed_silences,
        "fillers_removed": removed_fillers,
        "segments": len(merged),
    }
    if drops:
        stats["manual_drops"] = len(drops)
    return merged, stats


# ---------------------------------------------------------------------------
# Stage 1B — auto-editor v3 JSON timeline builder (pure; the renderer that
# spawns auto-editor lives in smartcut.py)
# ---------------------------------------------------------------------------

def _build_v3_timeline(
    clip_path: str,
    segments: list[tuple[float, float]],
    probe: dict,
) -> dict:
    """Build an auto-editor v3 timeline JSON for the given keep-segments.

    Schema confirmed against auto-editor src/exports/json.nim and
    src/imports/json.nim. All numeric fields are in *frames* (timebase units).
    """
    fps = probe["fps_num"] / probe["fps_den"]
    abs_src = os.path.abspath(clip_path)

    video_clips: list[dict] = []
    audio_clips: list[dict] = []
    out_pos = 0  # cumulative output frame position

    for seg_start_sec, seg_end_sec in segments:
        start_f = int(round(seg_start_sec * fps))
        dur_f = int(round((seg_end_sec - seg_start_sec) * fps))
        if dur_f <= 0:
            continue
        clip_obj_v = {
            "name": "video",
            "src": abs_src,
            "start": out_pos,
            "dur": dur_f,
            "offset": start_f,
            "stream": 0,
        }
        clip_obj_a = {**clip_obj_v, "name": "audio"}
        video_clips.append(clip_obj_v)
        audio_clips.append(clip_obj_a)
        out_pos += dur_f

    return {
        "version": "3",
        "timebase": f"{probe['fps_num']}/{probe['fps_den']}",
        "background": "#000000",
        "resolution": [probe["width"], probe["height"]],
        "samplerate": probe["samplerate"],
        "layout": "stereo",
        "langs": ["und"],
        "v": [video_clips],
        "a": [audio_clips],
    }
