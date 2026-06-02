"""Pydantic request schemas for the ClippyMe FastAPI app."""
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ProcessRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    # Optional per-job knobs — mirror the BatchRequest so single and batch
    # jobs expose the same surface area to the frontend. All three are
    # validated downstream (reframe_mode by argparse choices, language by
    # ALLOWED_LANGUAGES in job_results.build_main_cmd, instructions by
    # length cap).
    instructions: Optional[str] = Field(None, max_length=2000)
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled)$")
    aspect: Optional[str] = Field(None, pattern=r"^(9:16|1:1|16:9)$")
    language: Optional[str] = Field(None, max_length=16)
    no_zoom: Optional[bool] = False
    skip_analysis: Optional[bool] = False


class BatchRequest(BaseModel):
    urls: List[str] = Field(..., min_length=1, max_length=20)
    instructions: Optional[str] = Field(None, max_length=2000)
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled)$")
    aspect: Optional[str] = Field(None, pattern=r"^(9:16|1:1|16:9)$")
    # Optional per-batch ASR language override. When omitted the pipeline
    # uses its default (Deepgram `multi` for EN+IT code-switching). Setting
    # this to a single-language code ("en", "it", "es", …) improves both
    # transcription accuracy AND speaker diarization reliability on audio
    # that isn't actually multilingual.
    language: Optional[str] = Field(None, max_length=16)
    no_zoom: Optional[bool] = False
    skip_analysis: Optional[bool] = False


class ConfigUpdateRequest(BaseModel):
    keys: dict


class ReframeRequest(BaseModel):
    """Switch a clip between reframe modes after it has been generated.

    Only valid when the per-clip 16:9 source slice was preserved on disk
    (i.e. jobs produced after the post-hoc reframe feature landed).
    """
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled)$")


class ComposeRequest(BaseModel):
    toggles: dict = {}
    hook_params: dict = {}
    subtitle_params: dict = {}


class PublishRequest(BaseModel):
    """Schedule a clip on social platforms via Zernio.

    schedule_mode:
      - "now"     → publish immediately
      - "auto"    → SmartScheduler picks the next optimal slot
      - "manual"  → caller passes scheduled_for (ISO 8601)

    platforms is a list of {platform, accountId, platformSpecificData?} dicts
    matching Zernio's create-post schema.
    """
    title: str = ""
    caption: str = ""
    platforms: List[dict] = Field(..., min_length=1, max_length=14)
    schedule_mode: str = "now"
    scheduled_for: Optional[str] = None
    # Optional YYYY-MM-DD that defines the day the SmartScheduler should
    # start picking slots from when schedule_mode="auto". Ignored by
    # "now" / "manual". Defaults to today if omitted.
    start_date: Optional[str] = None
    timezone: str = "Europe/Rome"
    tiktok_settings: Optional[dict] = None
    # If true, force a fresh compose pass before upload using the supplied
    # toggles. If omitted, the latest composed clip on disk is used.
    compose_first: bool = False
    toggles: Optional[dict] = None
    hook_params: Optional[dict] = None
    subtitle_params: Optional[dict] = None


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
    shorts: List[ViralClip] = Field(..., min_length=0, max_length=20)


class ZernioConfigRequest(BaseModel):
    """Persisted Zernio settings (saved to data/config.json)."""
    api_key: Optional[str] = None
    accounts: Optional[dict] = None  # {"tiktok": "...", "instagram": "...", "youtube": "..."}
    timezone: Optional[str] = None
