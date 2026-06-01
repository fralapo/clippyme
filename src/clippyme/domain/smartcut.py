"""
Smart Cut — Remove dead silences and filler words from video clips.

Two-stage pipeline:
1. **Filler-word + transcript-gap pass** (this module)
   - Reads Whisper word-level timestamps
   - Drops filler words ("ehm", "uhm", "like", ...)  in 5 languages
   - Drops gaps > SILENCE_THRESHOLD between words
   - Renders the cuts via auto-editor's v3 JSON timeline (frame-accurate,
     single-pass) — falls back to FFmpeg concat demuxer if auto-editor
     isn't installed.
2. **Audio-loudness polish pass**
   - Runs auto-editor with `--edit audio:threshold=0.04` on the result of
     stage 1 to catch silences the transcript missed (low mumble, music
     gaps, ambient quiet). Skipped silently if auto-editor is unavailable.

Public API (unchanged): smart_cut(clip_path, transcript, clip_start, clip_end, language)
"""

import contextlib
import hashlib
import logging
import os
import re
import json
import shutil
import subprocess
import tempfile
import threading
from typing import Optional

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

# Concurrency cap for parallel auto-editor invocations. Each invocation is
# CPU-bound (libav decode + encode); spawning unlimited copies under heavy
# load can starve the box. Adjustable via env var. 0/negative = unlimited.
_AE_MAX_PARALLEL = max(0, int(os.environ.get("AE_MAX_PARALLEL", "2")))
_AE_CONCURRENCY_SEM: Optional[threading.Semaphore] = (
    threading.Semaphore(_AE_MAX_PARALLEL) if _AE_MAX_PARALLEL > 0 else None
)

DEFAULT_LANG = "en"

# Gaps longer than this between words are considered "dead silence"
SILENCE_THRESHOLD = float(os.environ.get("AE_SILENCE_THRESHOLD", "0.8"))

# Minimum silence kept around the cut (one breath, avoids whiplash edits)
SILENCE_KEEP = float(os.environ.get("AE_SILENCE_KEEP", "0.3"))

# Polish safety net: if the audio polish pass removes more than this fraction
# of the stage-1 output, the result is suspicious (likely a music clip with
# legitimate quiet sections being misidentified as silence). Revert in that
# case rather than serve a butchered video.
MAX_POLISH_CUT_RATIO = float(os.environ.get("AE_MAX_POLISH_CUT_RATIO", "0.5"))

# Per-clip mutex registry: prevents two concurrent smart_cut calls on the
# same source clip from clobbering each other's _smartcut.mp4 output.
# Lazily populated by _clip_lock(). Workers from FastAPI's executor pool
# may hit the same clip when the user spam-clicks Download.
_CLIP_LOCKS: dict[str, threading.Lock] = {}
_CLIP_LOCKS_GUARD = threading.Lock()


def _clip_lock(clip_path: str) -> threading.Lock:
    """Return a process-wide lock unique to `clip_path`. Lazy + thread-safe."""
    abs_path = os.path.abspath(clip_path)
    with _CLIP_LOCKS_GUARD:
        lock = _CLIP_LOCKS.get(abs_path)
        if lock is None:
            lock = threading.Lock()
            _CLIP_LOCKS[abs_path] = lock
            # Bound the registry. 256 in-flight clips is plenty for any
            # realistic worker count.
            if len(_CLIP_LOCKS) > 256:
                _CLIP_LOCKS.pop(next(iter(_CLIP_LOCKS)))
        return lock


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
    return hashlib.sha1(payload.encode()).hexdigest()[:10]

# Audio polish pass: amplitude threshold under which audio is considered silent.
# 0.04 ≈ -28 dB. Conservative — won't touch normal speech, only true quiet.
# Tunable via env var without rebuilding the image.
AUDIO_POLISH_THRESHOLD = os.environ.get("AE_AUDIO_THRESHOLD", "0.04")
AUDIO_POLISH_MARGIN = os.environ.get("AE_MARGIN", "0.2sec")

# Hard cap on any single auto-editor invocation. Prevents a frozen binary
# from blocking a worker forever. 5 minutes is generous for typical clips.
SUBPROCESS_TIMEOUT_SECONDS = int(os.environ.get("AE_TIMEOUT_SECONDS", "300"))

# If stage 1 already shaved off this much, skip the audio polish pass —
# the clip is probably already tight and the polish won't earn its overhead.
SKIP_POLISH_IF_SAVED_OVER = float(os.environ.get("AE_SKIP_POLISH_THRESHOLD", "8.0"))


# ---------------------------------------------------------------------------
# Subprocess + probe helpers (cached)
# ---------------------------------------------------------------------------

# In-process cache for video probe results, keyed by (path, size, mtime).
# Smartcut + audio polish pass + compose pipeline can otherwise probe the
# same source 3-4 times for a single download.
_PROBE_CACHE: dict[tuple, dict] = {}

# Same idea for plain duration probes (format=duration), which the polish
# pass + stats logging hit several times per clip on output files.
_DURATION_CACHE: dict[tuple, float] = {}

_CACHE_LIMIT = 256


def _probe_cache_key(path: str):
    """(abspath, size, mtime) key; None if the file can't be stat'd."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (os.path.abspath(path), st.st_size, st.st_mtime)


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

# Cache for `auto-editor --version` output. Refreshed when the binary
# changes (auto_editor_updater swaps a new file in).
_AE_VERSION_CACHE: dict[str, Optional[str]] = {}


def _run(cmd: list[str], *, timeout: Optional[int] = None) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr).

    Wraps subprocess.run with a uniform timeout, captured streams, and
    string decoding so callers don't repeat the boilerplate everywhere.
    """
    try:
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout if timeout is not None else SUBPROCESS_TIMEOUT_SECONDS,
        )
        return r.returncode, r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")
    except subprocess.TimeoutExpired as e:
        logger.warning("subprocess timed out: %s", " ".join(cmd[:3]))
        return -1, "", f"timeout after {e.timeout}s"
    except FileNotFoundError as e:
        return -1, "", f"command not found: {e.filename}"


# ---------------------------------------------------------------------------
# Stage 1A — analyze the transcript
# ---------------------------------------------------------------------------

def analyze_silences(transcript, clip_start, clip_end, language=None):
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

    if not words:
        # Whisper sometimes returns segment-level timestamps without per-word
        # timing (faster_whisper word_timestamps=False). Log so the operator
        # knows why smart cut is a no-op.
        if not any('words' in s for s in transcript.get('segments', [])):
            logger.info("smartcut: transcript has no word-level timestamps; nothing to cut")
        return [], {"error": "No words found in clip range"}

    clip_duration = clip_end - clip_start

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
    last_kept_end = 0.0

    for idx, word in enumerate(words):
        if word_skip[idx]:
            if current_start < word['start']:
                segments_to_keep.append((current_start, word['start']))
                last_kept_end = word['start']
            current_start = word['end']
            removed_fillers += 1
            continue

        if idx > 0:
            prev_end = words[idx - 1]['end']
            gap = word['start'] - prev_end
            if gap > SILENCE_THRESHOLD:
                segments_to_keep.append((current_start, prev_end + SILENCE_KEEP))
                last_kept_end = prev_end + SILENCE_KEEP
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

    new_duration = sum(end - start for start, end in merged)
    return merged, {
        "original_duration": round(clip_duration, 1),
        "new_duration": round(new_duration, 1),
        "time_saved": round(clip_duration - new_duration, 1),
        "silences_removed": removed_silences,
        "fillers_removed": removed_fillers,
        "segments": len(merged),
    }


# ---------------------------------------------------------------------------
# Stage 1B — auto-editor v3 JSON renderer (replaces FFmpeg concat)
# ---------------------------------------------------------------------------

def _has_auto_editor() -> bool:
    """True if the `auto-editor` binary is on PATH."""
    return shutil.which("auto-editor") is not None


def _auto_editor_version() -> Optional[str]:
    """Return the cached output of `auto-editor --version`. Cached per-binary
    path so a runtime swap by the updater is picked up next call.
    """
    binary = shutil.which("auto-editor")
    if not binary:
        return None
    cache_key = f"{binary}:{os.path.getmtime(binary) if os.path.exists(binary) else 0}"
    if cache_key in _AE_VERSION_CACHE:
        return _AE_VERSION_CACHE[cache_key]
    rc, out, _ = _run([binary, "--version"], timeout=10)
    version = out.strip().split()[-1] if (rc == 0 and out.strip()) else None
    _AE_VERSION_CACHE[cache_key] = version
    return version


def _ae_supports_no_cache() -> bool:
    """`--no-cache` was added in auto-editor v30.1.0. Detect support so we
    don't pass an unrecognized flag to older binaries (legacy v29 install).
    """
    version = _auto_editor_version()
    if not version:
        return False
    try:
        parts = [int(p) for p in version.split(".")[:3]]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts) >= (30, 1, 0)
    except (ValueError, AttributeError):
        return False


@contextlib.contextmanager
def _ae_concurrency_slot():
    """Acquire a slot from the global auto-editor concurrency semaphore.
    No-op if AE_MAX_PARALLEL <= 0 (unlimited).
    """
    if _AE_CONCURRENCY_SEM is None:
        yield
        return
    _AE_CONCURRENCY_SEM.acquire()
    try:
        yield
    finally:
        _AE_CONCURRENCY_SEM.release()


def _probe_video(clip_path: str) -> Optional[dict]:
    """Probe a video file for fps, resolution, and audio sample rate.
    Cached per (path, size, mtime).

    Returns a dict with keys: fps_num, fps_den, width, height, samplerate.
    Returns None on failure (caller should fall back).
    """
    cache_key = _probe_cache_key(clip_path)
    if cache_key is None:
        return None
    cached = _cache_get(_PROBE_CACHE, cache_key)
    if cached is not None:
        return cached

    rc, out, _ = _run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-of", "json",
        clip_path,
    ], timeout=15)
    if rc != 0:
        return None
    try:
        v = json.loads(out)["streams"][0]
        fps_str = v["r_frame_rate"]
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps_num, fps_den = int(num), int(den)
        else:
            fps_num, fps_den = int(float(fps_str) * 1000), 1000
        width, height = int(v["width"]), int(v["height"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None

    rc, out, _ = _run([
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate",
        "-of", "json",
        clip_path,
    ], timeout=15)
    samplerate = 48000
    if rc == 0:
        try:
            a_streams = json.loads(out).get("streams", [])
            if a_streams:
                samplerate = int(a_streams[0]["sample_rate"])
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    result = {
        "fps_num": fps_num,
        "fps_den": fps_den,
        "width": width,
        "height": height,
        "samplerate": samplerate,
    }
    _cache_put(_PROBE_CACHE, cache_key, result)
    return result


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


def _render_with_auto_editor(
    clip_path: str,
    segments: list[tuple[float, float]],
    output_path: str,
) -> bool:
    """Render the keep-segments via auto-editor v3 JSON timeline.

    Returns True on success, False on any failure (caller should fall back to
    the legacy FFmpeg concat path).
    """
    probe = _probe_video(clip_path)
    if probe is None:
        return False

    timeline = _build_v3_timeline(clip_path, segments, probe)
    if not timeline["v"][0]:
        return False

    tmp_dir = tempfile.mkdtemp(prefix="ae_v3_")
    timeline_path = os.path.join(tmp_dir, "plan.json")
    try:
        with open(timeline_path, "w") as f:
            json.dump(timeline, f)

        cmd = ["auto-editor", timeline_path, "-o", output_path, "--no-open"]
        if _ae_supports_no_cache():
            cmd.append("--no-cache")

        with _ae_concurrency_slot():
            rc, _, stderr = _run(cmd)
        ok = rc == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0
        if not ok:
            logger.warning("auto-editor render failed (rc=%s): %s", rc, stderr.strip()[:300])
        return ok
    except Exception as e:
        logger.warning("auto-editor render exception: %s", e)
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stage 1C — legacy FFmpeg concat fallback (used if auto-editor is missing)
# ---------------------------------------------------------------------------

def _render_with_ffmpeg(
    clip_path: str,
    segments: list[tuple[float, float]],
    output_path: str,
) -> bool:
    """Original FFmpeg concat-demuxer renderer. Slower (N re-encodes + concat)
    but has zero external deps beyond ffmpeg, so it's the safe fallback.
    """
    temp_dir = tempfile.mkdtemp(prefix="smartcut_")
    try:
        segment_files = []
        for i, (start, end) in enumerate(segments):
            seg_path = os.path.join(temp_dir, f"seg_{i:03d}.mp4")
            rc, _, _ = _run([
                "ffmpeg", "-y",
                "-ss", str(start), "-to", str(end),
                "-i", clip_path,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac",
                "-avoid_negative_ts", "make_zero",
                seg_path,
            ])
            if rc == 0 and os.path.exists(seg_path):
                segment_files.append(seg_path)

        if len(segment_files) < 2:
            return False

        concat_list = os.path.join(temp_dir, "concat.txt")
        with open(concat_list, "w") as f:
            for seg_path in segment_files:
                f.write(f"file '{seg_path.replace(chr(92), '/')}'\n")

        rc, _, stderr = _run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac",
            "-pix_fmt", "yuv420p",
            output_path,
        ])
        if rc != 0:
            logger.warning("ffmpeg concat fallback failed: %s", stderr.strip()[:300])
        return rc == 0 and os.path.exists(output_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stage 2 — audio-loudness polish pass via auto-editor
# ---------------------------------------------------------------------------

def _audio_polish_pass(input_path: str) -> tuple[str, float]:
    """Run auto-editor in audio-threshold mode on `input_path` to remove
    silences the transcript missed.

    Returns (output_path, seconds_saved). If the polish step is unavailable
    or doesn't reduce duration meaningfully, returns (input_path, 0.0) so the
    caller can keep the stage-1 output.
    """
    if not _has_auto_editor():
        return input_path, 0.0

    polished_path = input_path.replace(".mp4", "_polished.mp4")
    cmd = [
        "auto-editor", input_path,
        "--edit", f"audio:threshold={AUDIO_POLISH_THRESHOLD}",
        "--margin", AUDIO_POLISH_MARGIN,
        "--no-open",
        "-o", polished_path,
    ]
    if _ae_supports_no_cache():
        cmd.append("--no-cache")
    with _ae_concurrency_slot():
        rc, _, stderr = _run(cmd, timeout=min(SUBPROCESS_TIMEOUT_SECONDS, 180))

    if rc != 0 or not os.path.exists(polished_path):
        if rc != 0:
            logger.info("audio polish skipped (rc=%s): %s", rc, stderr.strip()[:200])
        return input_path, 0.0

    in_dur = _probe_duration(input_path)
    out_dur = _probe_duration(polished_path)
    saved = (in_dur - out_dur) if (in_dur and out_dur) else 0.0

    # Discard if no real benefit
    if saved < 0.5:
        try:
            os.remove(polished_path)
        except OSError:
            pass
        return input_path, 0.0

    # SAFETY: revert if polish removed an unreasonable fraction of the clip.
    # Likely a music/ambient clip where quiet sections are intentional.
    if in_dur > 0 and (saved / in_dur) > MAX_POLISH_CUT_RATIO:
        logger.warning(
            "audio polish reverted: cut %.1f%% of clip (cap %.0f%%) — likely music/ambient",
            (saved / in_dur) * 100, MAX_POLISH_CUT_RATIO * 100,
        )
        try:
            os.remove(polished_path)
        except OSError:
            pass
        return input_path, 0.0

    # Atomic-ish replace, falling back to copy+unlink for cross-FS mounts.
    try:
        os.replace(polished_path, input_path)
    except OSError as e:
        logger.debug("os.replace failed (%s), falling back to shutil.move", e)
        try:
            shutil.move(polished_path, input_path)
        except Exception as e2:
            logger.warning("polish output swap failed: %s", e2)
            try:
                os.remove(polished_path)
            except OSError:
                pass
            return input_path, 0.0
    return input_path, saved


def _probe_duration(path: str) -> float:
    # Cached per (path, size, mtime): the polish pass + stats logging probe
    # the same output files repeatedly within a single smart_cut call.
    cache_key = _probe_cache_key(path)
    if cache_key is not None:
        cached = _cache_get(_DURATION_CACHE, cache_key)
        if cached is not None:
            return cached

    rc, out, _ = _run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ], timeout=10)
    if rc != 0:
        return 0.0
    try:
        duration = float(out.strip())
    except (ValueError, AttributeError):
        return 0.0
    if cache_key is not None:
        _cache_put(_DURATION_CACHE, cache_key, duration)
    return duration


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def smart_cut(clip_path, transcript, clip_start, clip_end, language=None):
    """Generate a tighter version of `clip_path` by removing silences and fillers.

    Concurrency-safe: a per-clip threading.Lock prevents two simultaneous
    smart_cut calls on the same source from clobbering each other's output.
    If a previous run already produced the expected `_smartcut.mp4` and the
    source hasn't changed, we reuse it (cache hit).

    Pipeline:
      1. analyze_silences()  →  list of keep-segments (transcript-based)
      2. _render_with_auto_editor()  →  v3 timeline render (frame-accurate)
         · falls back to _render_with_ffmpeg() if auto-editor isn't available
      3. _audio_polish_pass()  →  optional second pass that catches silences
         the transcript missed (skipped silently if auto-editor missing)

    Returns:
        (output_path, stats)  on success
        (None, stats)         on no-op or failure
    """
    with _clip_lock(clip_path):
        return _smart_cut_inner(clip_path, transcript, clip_start, clip_end, language)


def _smart_cut_inner(clip_path, transcript, clip_start, clip_end, language=None):
    segments, stats = analyze_silences(transcript, clip_start, clip_end, language)

    if not segments or len(segments) < 2:
        stats["skipped"] = True
        return None, stats
    if stats["time_saved"] < 1.0:
        stats["skipped"] = True
        return None, stats

    # Hash the cut plan + language so a re-run with different params produces
    # a different filename — no false-positive cache hit on language change.
    plan_hash = _segments_hash(segments, language or "")
    base, _ext = os.path.splitext(clip_path)
    # Backwards-compat: also accept the legacy `_smartcut.mp4` if present.
    output_path = f"{base}_smartcut_{plan_hash}.mp4"
    legacy_path = f"{base}_smartcut.mp4"

    # Cache hit: a previous run already produced this exact plan against this
    # source mtime. Skip re-rendering — the work is identical.
    try:
        for candidate in (output_path, legacy_path):
            if (os.path.exists(candidate)
                    and os.path.exists(clip_path)
                    and os.path.getmtime(candidate) >= os.path.getmtime(clip_path)
                    and os.path.getsize(candidate) > 0):
                stats["cached"] = True
                stats["renderer"] = "cache"
                ver = _auto_editor_version()
                if ver:
                    stats["renderer_version"] = ver
                stats["new_duration"] = round(_probe_duration(candidate), 1)
                stats["time_saved"] = round(
                    stats["original_duration"] - stats["new_duration"], 1
                )
                logger.info("smartcut cache hit: reusing %s", os.path.basename(candidate))
                return candidate, stats
    except OSError:
        pass

    if os.path.exists(output_path):
        os.remove(output_path)

    use_ae = _has_auto_editor()
    stage1_ok = False
    if use_ae:
        stage1_ok = _render_with_auto_editor(clip_path, segments, output_path)
        if stage1_ok:
            stats["renderer"] = "auto-editor-v3"
            ver = _auto_editor_version()
            if ver:
                stats["renderer_version"] = ver
        else:
            logger.warning("auto-editor v3 render failed, falling back to FFmpeg concat")

    if not stage1_ok:
        stage1_ok = _render_with_ffmpeg(clip_path, segments, output_path)
        if stage1_ok:
            stats["renderer"] = "ffmpeg-concat"

    if not stage1_ok:
        stats["error"] = "render failed (both auto-editor and ffmpeg)"
        return None, stats

    # Stage 2 — audio polish pass (best effort, never fatal).
    # Skip when stage 1 already shaved off plenty: extra invocation overhead
    # rarely earns more than a second on already-tight clips.
    if stats["time_saved"] >= SKIP_POLISH_IF_SAVED_OVER:
        logger.info(
            "skipping audio polish: stage-1 already saved %.1fs (threshold %.1fs)",
            stats["time_saved"], SKIP_POLISH_IF_SAVED_OVER,
        )
        polish_saved = 0.0
    else:
        _, polish_saved = _audio_polish_pass(output_path)

    if polish_saved > 0:
        stats["audio_polish_saved"] = round(polish_saved, 1)
        stats["new_duration"] = round(_probe_duration(output_path), 1)
        stats["time_saved"] = round(stats["original_duration"] - stats["new_duration"], 1)

    msg_parts = [
        f"✂️  Smart Cut: {stats['original_duration']}s → {stats['new_duration']}s",
        f"(-{stats['time_saved']}s, {stats['silences_removed']} silences,",
        f"{stats['fillers_removed']} fillers",
    ]
    if "audio_polish_saved" in stats:
        msg_parts.append(f", audio polish -{stats['audio_polish_saved']}s")
    msg_parts.append(f", renderer={stats.get('renderer', '?')}")
    if "renderer_version" in stats:
        msg_parts.append(f" v{stats['renderer_version']}")
    msg_parts.append(")")
    logger.info(" ".join(msg_parts))

    return output_path, stats
