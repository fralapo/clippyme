"""Pure lexical TextTiling — dependency-light topic segmentation of a transcript.

The boundary math (gap-score → smoothing → depth-score → boundary identification)
is ported faithfully from ``ClipsAI/clipsai`` (`clip/texttiler.py`), but the
neural sentence-embedding front-end is swapped for the **classic Hearst (1997)
lexical block comparison**: term-frequency vectors over windows of transcript
segments, compared by cosine similarity. That swap is the whole point — it needs
NO ``sentence-transformers`` / ``torch`` model download (a ~90 MB dep ClippyMe
otherwise avoids), only the transcript text the pipeline already has.

Used as a smarter **whole-video fallback**: when Gemini viral detection is
unavailable (no key) or fails (parse/network), instead of rendering the entire
source as one giant vertical clip we segment the transcript into topic-coherent
chunks and emit several reasonably-sized clips. It is *not* viral-ranked — it has
no AI judgment — but topic-coherent multi-clip output beats a single whole-video
dump for the no-API-key / API-down path.

Pure stdlib + numpy → host-importable and host-unit-tested (no cv2/torch import),
following the established ``reframe_ops.py`` / ``media_probe.py`` pattern (testable
math in its own module, thin glue in ``main.py``). See
``docs/research/clipsai.md`` for the comparison and rationale.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Sequence, Tuple

# Small multilingual stop-word set (EN + IT — ClippyMe's two primary languages).
# Dropping these sharpens lexical-cohesion signal: function words co-occur in
# every block and would otherwise wash out the topic-specific term overlap.
_STOPWORDS = frozenset(
    """
    a an the of to in is it and or but for on at by with as be this that these those
    i you he she we they me him her us them my your his our their its do does did not
    no yes so if then than too very can will just have has had was were are am been
    il lo la i gli le un uno una di a da in con su per tra fra e o ma se che non
    è sono ho hai ha abbiamo avete hanno questo questa questi queste quello quella
    mi ti ci vi si come anche più meno molto poco
    """.split()
)

_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)  # unicode letters, no digits/punct


def tokenize(text: str) -> List[str]:
    """Lower-case unicode word tokens with stop-words removed."""
    return [t for t in (m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")) if t not in _STOPWORDS]


def _cosine(a: Counter, b: Counter) -> float:
    """Cosine similarity of two term-frequency Counters (0.0 if either empty)."""
    if not a or not b:
        return 0.0
    # iterate the smaller dict
    if len(a) > len(b):
        a, b = b, a
    dot = sum(cnt * b.get(term, 0) for term, cnt in a.items())
    if dot == 0:
        return 0.0
    na = math.sqrt(sum(c * c for c in a.values()))
    nb = math.sqrt(sum(c * c for c in b.values()))
    return dot / (na * nb)


def gap_scores(block_tokens: Sequence[Sequence[str]], k: int) -> List[float]:
    """Cosine similarity across each gap between consecutive blocks.

    For gap ``i`` (between block ``i`` and ``i+1``) the left window pools the
    token counts of blocks ``[i-k+1 .. i]`` and the right window pools
    ``[i+1 .. i+k]`` (clamped to the ends), mirroring ClipsAI's ``k``-window
    pooling but with bag-of-words term frequencies instead of pooled embeddings.
    Returns ``len(block_tokens) - 1`` scores (empty if fewer than 2 blocks).
    """
    n = len(block_tokens)
    if n < 2:
        return []
    k = max(1, k)
    scores: List[float] = []
    for i in range(n - 1):
        left = Counter()
        for j in range(max(0, i - k + 1), i + 1):
            left.update(block_tokens[j])
        right = Counter()
        for j in range(i + 1, min(n, i + 1 + k)):
            right.update(block_tokens[j])
        scores.append(_cosine(left, right))
    return scores


def smooth_scores(scores: Sequence[float], width: int) -> List[float]:
    """Centered flat (moving-average) smoothing, faithful to TextTiling's smooth().

    ``width`` < 3 (or longer than the series) is a no-op. Window is normalized
    and applied with edge clamping so the series length is preserved.
    """
    n = len(scores)
    if width < 3 or n < width:
        return list(scores)
    half = width // 2
    out: List[float] = []
    for i in range(n):
        lo, hi = i - half, i + half
        acc = 0.0
        for j in range(lo, hi + 1):
            jj = 0 if j < 0 else (n - 1 if j >= n else j)  # clamp edges
            acc += scores[jj]
        out.append(acc / (2 * half + 1))
    return out


def depth_scores(gaps: Sequence[float]) -> List[float]:
    """Valley depth at each gap: ``(left_peak - gap) + (right_peak - gap)``.

    Peaks are found by walking outward while scores are non-decreasing, exactly
    as in ClipsAI's ``_calc_depth_scores``. A deep valley (low similarity flanked
    by high-similarity peaks) marks a strong topic boundary.
    """
    n = len(gaps)
    depths: List[float] = [0.0] * n
    for i in range(n):
        lpeak = gaps[i]
        j = i
        while j - 1 >= 0 and gaps[j - 1] >= lpeak:
            lpeak = gaps[j - 1]
            j -= 1
        rpeak = gaps[i]
        j = i
        while j + 1 < n and gaps[j + 1] >= rpeak:
            rpeak = gaps[j + 1]
            j += 1
        depths[i] = (lpeak - gaps[i]) + (rpeak - gaps[i])
    return depths


def _cutoff(depths: Sequence[float], policy: str) -> float:
    n = len(depths)
    if n == 0:
        return 0.0
    mean = sum(depths) / n
    var = sum((d - mean) ** 2 for d in depths) / n
    std = math.sqrt(var)
    if policy == "average":
        return mean
    if policy == "low":
        return mean - std
    return mean + std  # "high" (default)


def identify_boundaries(depths: Sequence[float], cutoff_policy: str = "high") -> List[int]:
    """Gap indices that are local depth maxima above the cutoff.

    A gap ``i`` is a boundary when ``depth > cutoff`` AND it is ``>=`` both
    neighbours AND it is not a flat plateau equal to both neighbours — the exact
    four-condition test from ClipsAI's ``_identify_boundaries``. The returned
    indices are *gap* indices, i.e. a boundary at ``i`` means "split after block i".
    """
    n = len(depths)
    if n == 0:
        return []
    cutoff = _cutoff(depths, cutoff_policy)
    out: List[int] = []
    for i in range(n):
        left = depths[i - 1] if i > 0 else float("-inf")
        right = depths[i + 1] if i < n - 1 else float("-inf")
        if (
            depths[i] > cutoff
            and depths[i] >= left
            and depths[i] >= right
            and not (depths[i] == left and depths[i] == right)
        ):
            out.append(i)
    return out


def segment_indices(
    block_tokens: Sequence[Sequence[str]],
    k: int = 7,
    smoothing_width: int = 3,
    cutoff_policy: str = "high",
) -> List[Tuple[int, int]]:
    """Group blocks into topic segments → list of inclusive ``(start, end)`` block-index spans.

    Runs the full lexical TextTiling chain (gap → smooth → depth → boundaries)
    and converts the gap boundaries into contiguous block spans covering every
    block. ``k`` is auto-shrunk when the series is short (``> n/5`` is clamped),
    mirroring ClipsAI's guard so tiny transcripts still produce a sane result.
    """
    n = len(block_tokens)
    if n <= 1:
        return [(0, n - 1)] if n == 1 else []
    if k > max(1, n // 5):
        k = max(1, n // 5)
    gaps = gap_scores(block_tokens, k)
    gaps = smooth_scores(gaps, smoothing_width)
    depths = depth_scores(gaps)
    bounds = identify_boundaries(depths, cutoff_policy)
    spans: List[Tuple[int, int]] = []
    start = 0
    for b in bounds:
        spans.append((start, b))  # gap b → split after block b
        start = b + 1
    if start <= n - 1:
        spans.append((start, n - 1))
    return spans


def find_topic_clips(
    segments: Sequence[Dict],
    min_clip_duration: float = 15.0,
    max_clip_duration: float = 90.0,
    max_clips: int = 12,
    k: int = 7,
    cutoff_policy: str = "high",
) -> List[Dict]:
    """Segment transcript ``segments`` into topic clips for the no-AI fallback.

    ``segments`` are transcript chunks shaped ``{"text": str, "start": float,
    "end": float}`` (ClippyMe's ``transcript_result['segments']``). Returns a list
    of ``{"start", "end", "text"}`` dicts, each within ``[min, max]`` duration:

    * spans longer than ``max_clip_duration`` are sliced at segment boundaries,
    * spans shorter than ``min_clip_duration`` are merged forward into the next,
    * at most ``max_clips`` clips are returned (longest-first, then re-sorted by
      start) so a long podcast doesn't explode into dozens of clips.

    Returns ``[]`` when there isn't enough usable text to segment, so the caller
    can fall back to its existing whole-video behaviour.
    """
    usable = [
        s for s in segments
        if isinstance(s, dict)
        and s.get("text")
        and s.get("start") is not None
        and s.get("end") is not None
        and float(s["end"]) > float(s["start"])
    ]
    if len(usable) < 4:
        return []

    block_tokens = [tokenize(s["text"]) for s in usable]
    spans = segment_indices(block_tokens, k=k, cutoff_policy=cutoff_policy)

    # span (block indices) → time window, then enforce min/max duration.
    clips: List[Dict] = []
    pending_start_idx = None
    for (a, b) in spans:
        s_idx = pending_start_idx if pending_start_idx is not None else a
        start_t = float(usable[s_idx]["start"])
        end_t = float(usable[b]["end"])
        dur = end_t - start_t
        if dur < min_clip_duration:
            # too short → carry the start forward and merge into the next span
            pending_start_idx = s_idx
            continue
        pending_start_idx = None
        if dur <= max_clip_duration:
            clips.append({"start": start_t, "end": end_t,
                          "text": " ".join(usable[j]["text"].strip() for j in range(s_idx, b + 1))})
            continue
        # too long → slice at segment boundaries into <= max chunks
        chunk_start = s_idx
        for j in range(s_idx, b + 1):
            if float(usable[j]["end"]) - float(usable[chunk_start]["start"]) >= max_clip_duration:
                clips.append({
                    "start": float(usable[chunk_start]["start"]),
                    "end": float(usable[j]["end"]),
                    "text": " ".join(usable[t]["text"].strip() for t in range(chunk_start, j + 1)),
                })
                chunk_start = j + 1
        if chunk_start <= b and float(usable[b]["end"]) - float(usable[chunk_start]["start"]) >= min_clip_duration:
            clips.append({
                "start": float(usable[chunk_start]["start"]),
                "end": float(usable[b]["end"]),
                "text": " ".join(usable[t]["text"].strip() for t in range(chunk_start, b + 1)),
            })

    if not clips:
        return []
    if len(clips) > max_clips:
        clips = sorted(clips, key=lambda c: c["end"] - c["start"], reverse=True)[:max_clips]
    return sorted(clips, key=lambda c: c["start"])
