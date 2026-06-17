"""Robust parser for Gemini viral-moment JSON responses.

Implements a 5-level fallback chain designed to make the clip-detection
pipeline resilient to the kinds of malformations Gemini occasionally
produces (stray backslashes, smart quotes, code fences, reasoning
prose mixed with the JSON body, trailing commas, etc.):

    1. strict   - json.loads on the section after the ``### JSON ###``
                  delimiter (or on the full text if absent).
    2. clean    - deterministic cleanup pass (smart quotes, trailing
                  commas, lone backslashes, control chars) then retry.
    3. json_repair - delegate to the ``json_repair`` library if
                  installed.
    4. retry    - one additional round-trip to Gemini with the decoder
                  error as context, asking it to emit JSON only.
    5. fallback - give up, return ``ParseResult.data = None`` so the
                  caller can degrade gracefully (whole-video mode).

Post-parse, ``validate_and_dedupe`` runs the result through the
``ViralClipsResponse`` Pydantic model and removes clips whose time
ranges overlap more than ``overlap_threshold`` (IoU) with a
higher-scoring neighbour.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from pydantic import ValidationError

from clippyme.schemas import ViralClipsResponse

logger = logging.getLogger(__name__)

JSON_DELIMITER = "### JSON ###"

# The delimiter in the prompt is canonical, but Gemini (especially flash)
# occasionally emits tiny variations: different spacing, lowercase, extra
# hashes, or markdown bold wrapping. Match them all with a single regex.
_DELIMITER_PATTERN = re.compile(
    r"(?:\*{0,2})#{2,4}\s*json\s*#{2,4}(?:\*{0,2})",
    re.IGNORECASE,
)

_CODE_FENCE_OPEN = re.compile(r"^\s*```(?:json)?\s*", re.IGNORECASE)
_CODE_FENCE_CLOSE = re.compile(r"\s*```\s*$")
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_LONE_BACKSLASH = re.compile(r'\\(?!["\\/bfnrtu])')
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass
class ParseResult:
    """Outcome of ``parse_gemini_response``.

    ``parse_path`` tells downstream logging which level of the chain
    succeeded (or ``"fallback"`` if every level failed).
    """
    data: Optional[Dict[str, Any]]
    parse_path: str  # strict | clean | json_repair | retry | fallback
    duration_ms: float
    error: Optional[str] = None


def _extract_json_section(text: str) -> str:
    """Isolate the JSON body from reasoning + code fences.

    If a delimiter matching ``_DELIMITER_PATTERN`` is present,
    everything before the LAST occurrence is discarded (chain-of-
    thought reasoning). The "last occurrence" rule matters because
    Gemini occasionally echoes the delimiter inside its own reasoning.

    Then any ``` ```json ... ``` ``` fence is stripped defensively so
    the rest of the pipeline sees raw JSON whatever the model emits.
    """
    matches = list(_DELIMITER_PATTERN.finditer(text))
    if matches:
        text = text[matches[-1].end():]
    text = _CODE_FENCE_OPEN.sub("", text)
    text = _CODE_FENCE_CLOSE.sub("", text)
    return text.strip()


def _clean_json(raw: str) -> str:
    """Deterministic JSON repair for the most common Gemini mistakes.

    * curly/smart quotes -> straight ASCII quotes
    * trailing comma before ``}``/``]`` -> removed
    * lone backslash not part of a valid escape -> doubled
    * ASCII control chars (except ``\\n \\r \\t``) -> stripped
    """
    raw = (
        raw.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )
    raw = _TRAILING_COMMA.sub(r"\1", raw)
    raw = _LONE_BACKSLASH.sub(r"\\\\", raw)
    raw = _CONTROL_CHARS.sub("", raw)
    return raw


def parse_gemini_response(
    text: str,
    retry_fn: Optional[Callable[[str], str]] = None,
    request_id: str = "",
) -> ParseResult:
    """Run the 5-level parsing chain on a Gemini response.

    Parameters
    ----------
    text:
        The raw text returned by ``response.text`` from the
        google-genai SDK.
    retry_fn:
        Optional callable that takes the last decoder error message
        and returns a fresh Gemini response (as text) for one retry.
        Pass ``None`` to disable level 4.
    request_id:
        Opaque ID to correlate logs across the parse chain.
    """
    t0 = time.time()
    section = _extract_json_section(text)

    # Level 1: strict ------------------------------------------------
    try:
        data = json.loads(section)
        return ParseResult(data, "strict", (time.time() - t0) * 1000)
    except json.JSONDecodeError as e1:
        strict_err = f"{e1.msg}: line {e1.lineno} col {e1.colno}"

    # Level 2: deterministic clean ----------------------------------
    cleaned = _clean_json(section)
    try:
        data = json.loads(cleaned)
        return ParseResult(data, "clean", (time.time() - t0) * 1000)
    except json.JSONDecodeError:
        pass

    # Level 3: json_repair library ----------------------------------
    try:
        from json_repair import repair_json  # type: ignore

        data = json.loads(repair_json(section))
        return ParseResult(data, "json_repair", (time.time() - t0) * 1000)
    except Exception:  # pragma: no cover - json_repair may be missing
        pass

    # Level 4: one retry with error context -------------------------
    if retry_fn is not None:
        try:
            retry_text = retry_fn(strict_err)
            retry_section = _extract_json_section(retry_text)
            data = json.loads(_clean_json(retry_section))
            return ParseResult(data, "retry", (time.time() - t0) * 1000)
        except Exception as e:
            return ParseResult(
                None,
                "fallback",
                (time.time() - t0) * 1000,
                f"retry failed: {e}; original: {strict_err}",
            )

    return ParseResult(None, "fallback", (time.time() - t0) * 1000, strict_err)


def _viral_reason_is_generic(reason: str) -> bool:
    """Heuristic: does ``viral_reason`` look like a placeholder?

    We already reject reasons shorter than 20 chars via Pydantic, but
    a 25-char generic line ("this is a cool moment in the video") can
    still slip through. Detect the most common hedging phrases and
    flag them so the caller can either drop the clip or downgrade the
    score.
    """
    lowered = reason.lower().strip()
    generic_markers = (
        "interesting point",
        "cool moment",
        "great content",
        "good clip",
        "this moment",
        "this part",
        "nice segment",
        "important point",
    )
    if any(m in lowered for m in generic_markers):
        return True
    # A reason with no digits AND no quoted fragment almost never
    # cites a specific hook or payoff — treat as weak signal.
    has_digit = any(ch.isdigit() for ch in lowered)
    has_quote = '"' in reason or "'" in reason
    return (not has_digit) and (not has_quote) and len(lowered.split()) < 8


# Timestamp coercion now lives in clippyme.api.schemas.ViralClip as a
# @field_validator('start','end', mode='before'). The legacy helpers
# _coerce_timestamp() and _normalize_clip_timestamps() that used to
# pre-walk the dict before Pydantic were removed in this commit — they
# were unused after schema validation took over. If you need to expand
# the coercion rules, add the logic inside ViralClip._coerce_timestamp
# so every downstream caller gets it automatically.


def validate_and_dedupe(
    data: Dict[str, Any],
    video_duration: Optional[float] = None,
    overlap_threshold: float = 0.7,
    drop_generic: bool = False,
) -> List[Dict[str, Any]]:
    """Pydantic-validate then remove overlapping clips.

    Clips are sorted by ``viral_score`` desc; for each candidate, if
    its intersection-over-union with any already-kept clip exceeds
    ``overlap_threshold`` it's dropped. When ``video_duration`` is
    given, clips whose ``end`` exceeds it are also dropped.

    Raises
    ------
    pydantic.ValidationError
        Only if the top-level response shape is malformed (e.g. ``shorts``
        is missing or not a list). Individual clip validation failures
        no longer nuke the whole batch — invalid clips are logged and
        silently dropped so the pipeline proceeds with whatever Gemini
        got right. This is critical because Gemini occasionally returns
        ~15 clips where 14 are valid and 1 has a duration of 2.96s; the
        old behaviour rejected all 15 and fell back to whole-video mode.
    """
    # Timestamp coercion lives entirely in ViralClip's @field_validator
    # (mode='before'). The legacy _normalize_clip_timestamps() helper was
    # removed to keep the pipeline single-source-of-truth — if you need a
    # log of coerced fields, add it inside the validator.

    # Per-clip resilience: iterate manually instead of relying on
    # ViralClipsResponse's List[ViralClip] fail-fast behaviour.
    raw_shorts = (data or {}).get("shorts") if isinstance(data, dict) else None
    if not isinstance(raw_shorts, list):
        # Top-level shape wrong — let Pydantic emit the authoritative error.
        ViralClipsResponse.model_validate(data)
        return []

    from clippyme.schemas import ViralClip  # neutral module, no api dependency

    candidates: List = []
    dropped_invalid = 0
    for i, raw in enumerate(raw_shorts):
        try:
            candidates.append(ViralClip.model_validate(raw))
        except Exception as exc:
            dropped_invalid += 1
            # Log the first validation error message verbatim so debugging
            # which field failed is one grep away.
            msg = str(exc).splitlines()[0] if str(exc) else "unknown"
            logger.warning(
                "validate_and_dedupe: dropping clip #%d — %s (input: start=%s end=%s)",
                i, msg[:200], raw.get("start") if isinstance(raw, dict) else "?",
                raw.get("end") if isinstance(raw, dict) else "?",
            )
    if dropped_invalid:
        logger.info(
            "validate_and_dedupe: %d/%d clip(s) rejected by per-clip validation, "
            "%d survived",
            dropped_invalid, len(raw_shorts), len(candidates),
        )
    if video_duration is not None:
        candidates = [c for c in candidates if c.end <= video_duration + 0.5]

    if drop_generic:
        before = len(candidates)
        candidates = [c for c in candidates if not _viral_reason_is_generic(c.viral_reason)]
        dropped = before - len(candidates)
        if dropped:
            logger.info(
                "validate_and_dedupe: dropped %d clip(s) with generic viral_reason", dropped
            )

    candidates.sort(key=lambda c: -c.viral_score)

    kept: List = []
    for clip in candidates:
        overlaps = False
        for k in kept:
            inter = max(0.0, min(clip.end, k.end) - max(clip.start, k.start))
            union = max(clip.end, k.end) - min(clip.start, k.start)
            if union > 0 and (inter / union) > overlap_threshold:
                overlaps = True
                break
        if not overlaps:
            kept.append(clip)

    return [c.model_dump() for c in kept]


def _truncate_words(text: str, n: int = 10) -> str:
    """Normalize whitespace and truncate to the first ``n`` words."""
    parts = (text or "").strip().split()
    return " ".join(parts[:n]).strip()


def backfill_hook_text(
    clips: List[Dict[str, Any]],
    words: List[Dict[str, Any]],
    fallback_title: str = "",
) -> List[Dict[str, Any]]:
    """Ensure EVERY clip has a non-empty ``viral_hook_text``.

    IMPORTANT: The hook is designed to be a SCROLL-STOPPING overlay, not
    a transcript echo. The prompt in ``main.py`` explicitly forbids quoting
    the first spoken words, so this backfill also does NOT fall back to
    transcript words — doing so would reintroduce the exact bug the new
    prompt is meant to fix.

    Strategy (first success wins):
      1. Keep Gemini's hook if non-empty (normalized + truncated to 8 words).
      2. Derive a teaser-style hook from the YouTube title if present.
      3. Use ``fallback_title`` (source title) similarly truncated.
      4. Hard-coded generic teaser so the field is never empty.

    The ``words`` parameter is kept for backward compatibility with
    callers in ``main.py`` and ``job_results.py``; it is intentionally
    unused.

    This function is idempotent and mutates each clip dict in place,
    returning the same list for convenience.
    """
    del words  # unused — see docstring

    for clip in clips:
        existing = _truncate_words(clip.get("viral_hook_text") or "", 8)
        if existing:
            clip["viral_hook_text"] = existing
            continue

        title_hook = _truncate_words(
            clip.get("video_title_for_youtube_short", "") or fallback_title,
            8,
        )
        if title_hook:
            clip["viral_hook_text"] = title_hook
            continue

        clip["viral_hook_text"] = "You need to see this"

    return clips


__all__ = [
    "JSON_DELIMITER",
    "ParseResult",
    "parse_gemini_response",
    "validate_and_dedupe",
    "backfill_hook_text",
]
