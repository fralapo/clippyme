"""Pure cut-boundary math — no cv2, no ffmpeg, host-unit-testable.

Ports two video-use Hard Rules that ClippyMe's automated clip extraction
violated:

- Rule 6 "Never cut inside a word" — snap a Gemini-picked clip [start, end]
  (raw seconds) to the nearest Scribe/Deepgram WORD boundary so a clip never
  opens or closes on half a syllable.
- Rule 7 "Pad every cut edge" — ASR timestamps drift 50-100ms; a small lead/
  tail pad absorbs the drift so the first/last word isn't clipped.

`main.py` owns the ffmpeg cut; it calls `snap_clip_to_words` with the flattened
transcript word list before seeking. Keep this file dependency-free.
"""
from __future__ import annotations

from typing import Iterable

# video-use working window for cut padding is 30-200ms. We lead a touch and
# tail a touch more (the last word's release matters more than the attack).
DEFAULT_PRE_PAD = 0.05   # 50ms before the first kept word
DEFAULT_POST_PAD = 0.08  # 80ms after the last kept word
# If the nearest word boundary is farther than this from the requested edge,
# the transcript is probably misaligned for that moment — keep the raw edge
# rather than yank the clip somewhere the LLM did not intend.
DEFAULT_MAX_SNAP = 0.6


# video-use Hard Rule 3: a 30ms audio fade at every segment boundary kills the
# audible pop a hard concat cut leaves behind.
DEFAULT_FADE = 0.03


def audio_fade_filter(duration: float, fade: float = DEFAULT_FADE) -> str:
    """ffmpeg `-af` value that fades audio in at the head and out at the tail of
    a segment of length `duration`. Returns "" when the segment is too short to
    fade safely (a fade longer than half the clip would distort it).
    """
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        return ""
    if duration <= 0 or fade <= 0 or duration < fade * 2:
        return ""
    out_start = duration - fade
    return f"afade=t=in:st=0:d={fade},afade=t=out:st={out_start:.4f}:d={fade}"


def flatten_words(transcript: dict | None) -> list[dict]:
    """Flatten a transcript dict ({'segments': [{'words': [...]}, ...]}) into a
    single time-ordered list of word dicts each carrying numeric 'start'/'end'.

    Tolerant of the two shapes the pipeline produces: word objects may use
    'start'/'end' (Whisper) and always do after the Deepgram remap. Words
    missing usable timing are dropped (they can't anchor a cut).
    """
    if not transcript:
        return []
    words: list[dict] = []
    for seg in transcript.get("segments", []) or []:
        for w in seg.get("words", []) or []:
            s = w.get("start")
            e = w.get("end")
            if s is None or e is None:
                continue
            try:
                s = float(s)
                e = float(e)
            except (TypeError, ValueError):
                continue
            if e < s:
                continue
            words.append({"start": s, "end": e, "word": w.get("word", "")})
    words.sort(key=lambda x: x["start"])
    return words


def _nearest_boundary(target: float, boundaries: Iterable[float], max_snap: float):
    """Return the boundary value nearest to `target` within `max_snap`, else None."""
    best = None
    best_dist = max_snap
    for b in boundaries:
        d = abs(b - target)
        if d <= best_dist:
            best_dist = d
            best = b
    return best


def snap_clip_to_words(
    start: float,
    end: float,
    words: list[dict],
    *,
    pre_pad: float = DEFAULT_PRE_PAD,
    post_pad: float = DEFAULT_POST_PAD,
    max_snap: float = DEFAULT_MAX_SNAP,
    source_duration: float | None = None,
) -> tuple[float, float]:
    """Snap a raw clip [start, end] to word boundaries and pad the edges.

    - `start` snaps to the nearest WORD START so the clip opens on a word
      onset, then `pre_pad` is subtracted (clamped to ≥0) for breathing room.
    - `end` snaps to the nearest WORD END, then `post_pad` is added.
    - If no boundary lies within `max_snap` of an edge, that edge is kept raw
      (only the pad is applied) — a misaligned transcript never drags the clip.

    Pure: returns the new (start, end). Never returns an inverted/zero range;
    if snapping would collapse it, the original is returned unchanged.
    """
    try:
        start = float(start)
        end = float(end)
    except (TypeError, ValueError):
        return start, end
    if end <= start:
        return start, end

    new_start, new_end = start, end
    if words:
        snap_start = _nearest_boundary(start, (w["start"] for w in words), max_snap)
        if snap_start is not None:
            new_start = snap_start
        snap_end = _nearest_boundary(end, (w["end"] for w in words), max_snap)
        if snap_end is not None:
            new_end = snap_end

    new_start = max(0.0, new_start - pre_pad)
    new_end = new_end + post_pad
    if source_duration is not None:
        new_end = min(new_end, float(source_duration))

    # Never produce an inverted or zero-length range.
    if new_end <= new_start:
        return start, end
    return new_start, new_end


# ---------------------------------------------------------------------------
# Sentence-boundary snapping (the truncation fix).
#
# `snap_clip_to_words` only fixes a clip opening/closing mid-WORD. Users still
# saw clips cut mid-SENTENCE because the LLM's [start,end] drifts and the 0.6s
# word-snap budget can't reach the actual sentence edge. This layer snaps the
# clip to SENTENCE boundaries using the punctuation already attached to word
# tokens (Deepgram smart_format / Whisper). It is asymmetric and guarded, per
# the design council:
#   - START moves BACKWARD (generously) to the sentence onset → include the
#     whole opening sentence. Backward moves are nearly free (don't fight the
#     60s cap or the next clip).
#   - END moves FORWARD (tightly) to the sentence-final word → finish the
#     thought. Forward moves fight the duration cap + neighbour overlap, so the
#     budget is smaller and the clamps below always win.
#   - Hard invariants (max duration, no overlap with a neighbour clip, source
#     bounds) WIN over the sentence preference. On any conflict the function
#     degrades — start-only, then end-only, then all the way back to the
#     word-snapped edges. It is NEVER worse than `snap_clip_to_words` alone.
#   - Detection is guarded against false positives (abbreviations, decimals,
#     single-letter initials, bracketed audio-event tokens) so unpunctuated /
#     multilingual transcripts no-op gracefully instead of cutting on "Dr.".
# ---------------------------------------------------------------------------

# How far START may travel backward to reach a sentence onset.
DEFAULT_SENTENCE_BACK = 2.5
# How far END may travel forward to finish a sentence (tighter — fights the cap).
DEFAULT_SENTENCE_FWD = 1.5
# Platform target ceiling. A sentence snap never pushes a clip past this.
DEFAULT_MAX_CLIP_DURATION = 60.0

# Characters that terminate a sentence across EN/IT/ES/FR/DE/PT.
_SENTENCE_FINAL_CHARS = ".!?…"  # . ! ? …

# Tokens ending in '.' that are NOT sentence ends. Lower-cased, with the dot.
_ABBREVIATIONS = frozenset({
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.",
    "no.", "vol.", "p.", "pp.", "fig.", "inc.", "ltd.", "co.",
    "e.g.", "i.e.",
    # Italian
    "sig.", "sig.ra", "dott.", "dott.ssa", "avv.", "ing.", "geom.", "rag.",
    "sec.", "art.", "n.",
    # Spanish / Portuguese / French
    "sra.", "srta.", "ud.", "uds.", "m.", "mme.", "mlle.",
})


def _is_sentence_final(word: str) -> bool:
    """True if `word` ends a sentence — guarded against the usual false friends.

    Rejects: empty, bracketed audio events ``(laughter)``, abbreviations
    (``Dr.``), single-letter initials (``U.``), and pure-number/decimal tokens
    (``3.`` / ``3.5``) which carry a trailing dot but aren't sentence ends.
    """
    w = (word or "").strip()
    if len(w) < 2:
        return False
    # Bracketed audio-event token, e.g. "(laughter)" — never a sentence end.
    if w[0] == "(" and w[-1] == ")":
        return False
    if w[-1] not in _SENTENCE_FINAL_CHARS:
        return False
    lower = w.lower()
    if lower in _ABBREVIATIONS:
        return False
    core = lower.rstrip(_SENTENCE_FINAL_CHARS)
    if len(core) <= 1:           # single letter + dot → initial ("U.")
        return False
    # Internal dot remaining after stripping the terminator → dotted acronym
    # ("U.S.", "U.S.A.", "p.m.") rather than a real sentence end.
    if "." in core:
        return False
    # Pure number / decimal / thousands ("3.", "3.5", "1,000.") → not a sentence.
    if core.replace(",", "").isdigit():
        return False
    return True


def sentence_boundaries(words: list[dict]) -> tuple[list[float], list[float]]:
    """Derive sentence ONSET starts and sentence-final ENDs from a flat word list.

    `words` is the output of :func:`flatten_words` (time-ordered dicts carrying
    ``start``/``end``/``word``). A word is an onset when it follows a
    sentence-final word (and the very first word is always an onset). Returns
    ``(onset_starts, final_ends)`` — both ascending. Empty when there is no
    usable punctuation, so callers degrade to the word-snap path.
    """
    onsets: list[float] = []
    ends: list[float] = []
    prev_final = True  # the first spoken word opens the first sentence
    for w in words:
        if prev_final:
            onsets.append(w["start"])
        if _is_sentence_final(w.get("word", "")):
            ends.append(w["end"])
            prev_final = True
        else:
            prev_final = False
    return onsets, ends


def _onset_at_or_before(target: float, onsets: Iterable[float], budget: float):
    """Largest onset ``<= target`` within ``budget`` seconds, else ``None``."""
    best = None
    for o in onsets:
        if o <= target and (target - o) <= budget and (best is None or o > best):
            best = o
    return best


def _final_at_or_after(target: float, ends: Iterable[float], budget: float):
    """Smallest sentence-end ``>= target`` within ``budget`` seconds, else ``None``."""
    best = None
    for x in ends:
        if x >= target and (x - target) <= budget and (best is None or x < best):
            best = x
    return best


def snap_clip_to_sentences(
    start: float,
    end: float,
    words: list[dict],
    *,
    word_start: float,
    word_end: float,
    back_budget: float = DEFAULT_SENTENCE_BACK,
    fwd_budget: float = DEFAULT_SENTENCE_FWD,
    pre_pad: float = DEFAULT_PRE_PAD,
    post_pad: float = DEFAULT_POST_PAD,
    max_duration: float = DEFAULT_MAX_CLIP_DURATION,
    source_duration: float | None = None,
    neighbor_start: float | None = None,
    neighbor_end: float | None = None,
) -> tuple[float, float, str]:
    """Snap a clip to sentence boundaries, falling back to the word-snapped edges.

    Parameters
    ----------
    start, end:
        The RAW LLM-picked clip edges (anchors for the snap budgets).
    word_start, word_end:
        The already word-snapped + padded edges (today's behaviour). These are
        the fallback — the result is guaranteed no worse than these.
    neighbor_start:
        Start of the nearest TIME-following clip (output edge). The clip end is
        clamped below this so a forward extension never overlaps the next clip.
    neighbor_end:
        End of the nearest TIME-preceding clip. The clip start is clamped above
        this so a backward extension never overlaps the previous clip.

    Returns
    -------
    ``(new_start, new_end, path)`` where ``path`` is one of ``"sentence"``
    (both edges moved to sentence boundaries), ``"sentence_start"`` /
    ``"sentence_end"`` (one edge), or ``"word"`` (no sentence snap applied —
    identical to the word-snap input). The path is logged by the caller.
    """
    onsets, ends = sentence_boundaries(words) if words else ([], [])

    # When the transcript has NO sentence terminators at all (unpunctuated
    # Whisper, some multilingual paths), the lone "onset" is just word[0] —
    # transcript-start, not a real sentence boundary. Snapping a clip's start
    # back to it would be arbitrary, so suppress sentence snapping entirely and
    # let the word-snap edges stand (graceful no-op on the noisy sources).
    if not ends:
        onsets = []

    # Candidate sentence edges (None when nothing is in budget / no punctuation).
    onset = _onset_at_or_before(start, onsets, back_budget)
    final = _final_at_or_after(end, ends, fwd_budget)

    sent_start = max(0.0, onset - pre_pad) if onset is not None else None
    if sent_start is not None and neighbor_end is not None:
        sent_start = max(sent_start, neighbor_end)

    sent_end = (final + post_pad) if final is not None else None
    if sent_end is not None:
        if source_duration is not None:
            sent_end = min(sent_end, float(source_duration))
        if neighbor_start is not None:
            sent_end = min(sent_end, neighbor_start)

    def _valid(s: float, e: float) -> bool:
        return e > s and (e - s) <= max_duration

    # Graceful degradation: prefer both sentence edges, then the cheaper
    # start-only move, then end-only, then the plain word-snapped edges. The
    # backward start move is the safest, so it survives a duration conflict
    # before the forward end move does.
    s_candidates = [sent_start, word_start]
    e_candidates = [sent_end, word_end]
    for s in s_candidates:
        if s is None:
            continue
        for e in e_candidates:
            if e is None:
                continue
            if _valid(s, e):
                if s == sent_start and e == sent_end:
                    path = "sentence"
                elif s == sent_start:
                    path = "sentence_start"
                elif e == sent_end:
                    path = "sentence_end"
                else:
                    path = "word"
                return s, e, path

    # Last resort: the word-snapped edges (never worse than today). They are
    # already validated by snap_clip_to_words, but re-assert ordering.
    if word_end > word_start:
        return word_start, word_end, "word"
    return start, end, "word"


# ---------------------------------------------------------------------------
# Waveform silence-trough edge refinement (audio-aware final polish).
#
# The word/sentence snaps above are TRANSCRIPT-derived: they land the cut at
# `word.end + fixed pad`, but ASR word timestamps drift 50-100ms and the pad is
# a guess. The cleanest cut actually lands inside a real low-energy SILENCE
# trough (video-use: "silence gaps are the cleanest cut targets") so a word's
# attack/release is never clipped and no half-breath bleeds across the cut.
# This gently nudges each already-snapped edge (within a small window) into the
# nearest silence interval detected from the WAVEFORM
# (media_probe.detect_silences). It only ever moves toward quiet, so it is a
# strict improvement; no silence near an edge → that edge is left untouched.
# ---------------------------------------------------------------------------

# An edge may move at most this far to reach a silence trough — a gentle polish,
# never a re-pick of the clip.
DEFAULT_SILENCE_WINDOW = 0.35
# Start sits this far before speech resumes (inside the trailing silence).
DEFAULT_SILENCE_LEAD = 0.04
# End sits this far after speech stops (inside the leading silence).
DEFAULT_SILENCE_TAIL = 0.06


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def refine_edges_to_silence(
    start: float,
    end: float,
    silences: list[tuple[float, float]],
    *,
    window: float = DEFAULT_SILENCE_WINDOW,
    lead: float = DEFAULT_SILENCE_LEAD,
    tail: float = DEFAULT_SILENCE_TAIL,
    source_duration: float | None = None,
    neighbor_start: float | None = None,
    neighbor_end: float | None = None,
) -> tuple[float, float, str]:
    """Nudge a clip ``[start, end]`` into the nearest waveform silence trough.

    ``silences`` is the ``[(s, e), ...]`` list from
    :func:`media_probe.detect_silences`. For the START edge we snap to the END
    of the silence that immediately precedes the first word (clip opens just as
    sound begins); for the END edge we snap to the START of the silence that
    follows the last word (clip closes just as sound stops). An edge only moves
    when a silence boundary lies within ``window`` of it; otherwise it is kept.

    Returns ``(new_start, new_end, path)`` with ``path`` in ``silence`` /
    ``silence_start`` / ``silence_end`` / ``none``. Guarantees a valid,
    non-inverted range that respects the source + neighbour clamps; on any
    conflict the original edges are returned unchanged (never worse).
    """
    try:
        start = float(start)
        end = float(end)
    except (TypeError, ValueError):
        return start, end, "none"
    if end <= start or not silences:
        return start, end, "none"

    new_start, new_end = start, end
    moved_start = moved_end = False

    # START → end of the nearest preceding silence trough.
    best = None
    best_dist = window
    for s, e in silences:
        d = abs(e - start)
        if d <= best_dist:
            best_dist = d
            best = (s, e)
    if best is not None:
        s, e = best
        cand = _clamp(e - lead, s, e)
        if cand >= 0.0:
            new_start = cand
            moved_start = True

    # END → start of the nearest following silence trough.
    best = None
    best_dist = window
    for s, e in silences:
        d = abs(s - end)
        if d <= best_dist:
            best_dist = d
            best = (s, e)
    if best is not None:
        s, e = best
        new_end = _clamp(s + tail, s, e)
        moved_end = True

    # Clamps: source bounds + neighbour clips win.
    new_start = max(0.0, new_start)
    if neighbor_end is not None:
        new_start = max(new_start, neighbor_end)
    if source_duration is not None:
        new_end = min(new_end, float(source_duration))
    if neighbor_start is not None:
        new_end = min(new_end, neighbor_start)

    # Never invert / collapse the clip — fall back to the input edges.
    if new_end <= new_start:
        return start, end, "none"

    if moved_start and moved_end:
        path = "silence"
    elif moved_start:
        path = "silence_start"
    elif moved_end:
        path = "silence_end"
    else:
        path = "none"
    return new_start, new_end, path


# ---------------------------------------------------------------------------
# Smart Cut stage-2 polish pre-screen (pure prediction math)
# ---------------------------------------------------------------------------

def parse_margin_seconds(margin: str, default: float = 0.2) -> float:
    """Parse an auto-editor ``--margin`` value ('0.2sec', '0.2s', '0.2') → seconds.

    Falls back to ``default`` on anything unparsable; negative values clamp
    to 0 (a negative margin is meaningless here).
    """
    raw = str(margin or "").strip().lower()
    for suffix in ("seconds", "second", "secs", "sec", "s"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def predict_polish_saving(silences, margin_seconds: float) -> float:
    """Upper-bound estimate of how many seconds an auto-editor audio polish
    (``--edit audio:threshold`` + ``--margin M``) would remove, given the
    silence intervals ffmpeg ``silencedetect`` found.

    auto-editor keeps M seconds of padding around every loud section, so a
    silence of length L can contribute at most ``max(0, L - 2*M)``. The caller
    uses this as a PRE-SCREEN: when even this optimistic total is below the
    keep-threshold, the full decode+encode polish render would be discarded
    anyway and can be skipped outright. Pure → host-unit-tested.
    """
    m2 = 2.0 * max(0.0, float(margin_seconds))
    total = 0.0
    for start, end in silences or []:
        try:
            length = float(end) - float(start)
        except (TypeError, ValueError):
            continue
        if length > m2:
            total += length - m2
    return total
