"""Neutral data schemas shared across layers.

``ViralClip`` / ``ViralClipsResponse`` are the contract between the Gemini
viral-detection prompt (pipeline) and the rest of the app. They live here — in
a layer that depends on neither ``api`` nor ``pipeline`` — so the pipeline no
longer has to import from ``clippyme.api`` (which inverted the intended
dependency direction). ``clippyme.api.schemas`` re-exports them for backward
compatibility.
"""
from pydantic import BaseModel, Field, field_validator


class ViralClip(BaseModel):
    """A single viral clip candidate emitted by Gemini and validated
    before it's handed to the reframing pipeline.

    Duration bounds are deliberately a bit wider than the user-facing
    15-60s target (10-75s) so we don't throw away near-misses that the
    Smart Cut post-processing can still rescue.
    """
    start: float = Field(..., ge=0)
    end: float = Field(..., gt=0)
    viral_score: int = Field(..., ge=1, le=100)

    @field_validator("start", "end", mode="before")
    @classmethod
    def _coerce_timestamp(cls, v):
        """Normalize Gemini timestamps to float seconds.

        Gemini 2.5-flash occasionally emits start/end as *dotted* or
        *colon-separated* time strings instead of float seconds. Seen:

        * ``"25.17.724"`` → 25 min 17.724 s (MM.SS.mmm)
        * ``"1.25.17.724"`` → 1 h 25 min 17.724 s (HH.MM.SS.mmm)
        * ``"25:17.724"`` / ``"1:25:17"`` → HH:MM:SS

        Normalizing here (``mode='before'``) means the model is
        self-defending wherever it's used, not only via
        ``gemini_parser.validate_and_dedupe``. Numeric values and
        single-dot float strings pass through unchanged.
        """
        if not isinstance(v, str):
            return v
        s = v.strip()
        if not s:
            return v
        # Colon-separated (HH:MM:SS or MM:SS, optional decimal seconds)
        if ":" in s:
            try:
                parts = s.split(":")
                if len(parts) == 2:
                    return float(parts[0]) * 60.0 + float(parts[1])
                if len(parts) == 3:
                    return (
                        float(parts[0]) * 3600.0
                        + float(parts[1]) * 60.0
                        + float(parts[2])
                    )
            except ValueError:
                return v
            return v
        # Dotted. One dot = ordinary float; 2+ = MM.SS[.ms] / HH.MM.SS[.ms]
        if s.count(".") <= 1:
            return v
        parts = s.split(".")
        try:
            if len(parts) == 3:
                mm, ss, ms = parts
                return float(mm) * 60.0 + float(ss) + float(f"0.{ms}")
            if len(parts) == 4:
                hh, mm, ss, ms = parts
                return (
                    float(hh) * 3600.0
                    + float(mm) * 60.0
                    + float(ss)
                    + float(f"0.{ms}")
                )
        except ValueError:
            return v
        return v
    viral_reason: str = Field(..., min_length=20)
    video_description_for_tiktok: str = ""
    video_description_for_instagram: str = ""
    # YouTube Shorts enforces 100 chars; we leave a tiny cushion (10 chars)
    # because Gemini sometimes appends a stray period or ellipsis that we
    # trim during normalization anyway.
    video_title_for_youtube_short: str = Field("", max_length=110)
    viral_hook_text: str = Field("", max_length=160)

    @field_validator(
        "viral_reason",
        "video_description_for_tiktok",
        "video_description_for_instagram",
        "video_title_for_youtube_short",
        "viral_hook_text",
    )
    @classmethod
    def _normalize_whitespace(cls, v: str) -> str:
        """Collapse whitespace runs and strip.

        Gemini occasionally emits multiline values with stray \\n or \\t
        that break downstream rendering (ASS lines, drawtext, UI cards).
        Normalize once at the edge so the rest of the pipeline sees clean
        single-line text for every string field.
        """
        if not isinstance(v, str):
            return v
        return " ".join(v.split()).strip()

    @field_validator("end")
    @classmethod
    def _duration_in_range(cls, v: float, info) -> float:
        start = info.data.get("start", 0.0) or 0.0
        if v <= start:
            raise ValueError(f"end ({v}) must be strictly greater than start ({start})")
        duration = v - start
        if duration < 10 or duration > 75:
            raise ValueError(
                f"clip duration {duration:.2f}s outside allowed range [10, 75]"
            )
        return v


class ViralClipsResponse(BaseModel):
    """Top-level response shape from the Gemini viral-moment prompt."""
    shorts: list[ViralClip] = Field(..., min_length=0, max_length=20)
