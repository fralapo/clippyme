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
