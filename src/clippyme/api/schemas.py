"""Pydantic request schemas for the ClippyMe FastAPI app."""
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ProcessRequest(BaseModel):
    url: str = Field(..., max_length=2048)


class BatchRequest(BaseModel):
    urls: List[str] = Field(..., min_length=1, max_length=20)
    instructions: Optional[str] = Field(None, max_length=2000)
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled)$")


class ConfigUpdateRequest(BaseModel):
    keys: dict


_HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"
_FONT_NAME = r"^[A-Za-z0-9 _\-]{1,40}$"
_POSITION = r"^(top|middle|center|bottom)$"
_HOOK_SIZE = r"^[SML]$"
_FILENAME = r"^[A-Za-z0-9_\-.]{1,200}$"
_PRESET = r"^[a-z0-9_]{1,40}$"
_KARAOKE_MODE = r"^(word_group|full_line)$"


class SubtitleRequest(BaseModel):
    job_id: str = Field(..., pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
    clip_index: int = Field(..., ge=0, lt=100)
    position: str = Field("bottom", pattern=_POSITION)
    font_size: int = Field(16, ge=8, le=120)
    font_name: str = Field("Verdana", pattern=_FONT_NAME)
    font_color: str = Field("#FFFFFF", pattern=_HEX_COLOR)
    border_color: str = Field("#000000", pattern=_HEX_COLOR)
    border_width: int = Field(2, ge=0, le=10)
    bg_color: str = Field("#000000", pattern=_HEX_COLOR)
    bg_opacity: float = Field(0.0, ge=0.0, le=1.0)
    input_filename: Optional[str] = Field(None, pattern=_FILENAME)
    # Karaoke / viral subtitle options
    preset: Optional[str] = Field(None, pattern=_PRESET)
    karaoke_mode: Optional[str] = Field(None, pattern=_KARAOKE_MODE)
    words_per_group: int = Field(3, ge=1, le=10)
    uppercase: bool = True
    highlight_color: Optional[str] = Field(None, pattern=_HEX_COLOR)


class HookRequest(BaseModel):
    job_id: str = Field(..., pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
    clip_index: int = Field(..., ge=0, lt=100)
    text: str = Field(..., max_length=200)
    input_filename: Optional[str] = Field(None, pattern=_FILENAME)
    position: str = Field("top", pattern=_POSITION)
    size: str = Field("M", pattern=_HOOK_SIZE)


class ReframeRequest(BaseModel):
    """Switch a clip between reframe modes after it has been generated.

    Only valid when the per-clip 16:9 source slice was preserved on disk
    (i.e. jobs produced after the post-hoc reframe feature landed).
    """
    reframe_mode: str = "auto"  # "auto" or "disabled"


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
    viral_reason: str = Field(..., min_length=20)
    video_description_for_tiktok: str = ""
    video_description_for_instagram: str = ""
    video_title_for_youtube_short: str = Field("", max_length=120)
    viral_hook_text: str = Field("", max_length=160)

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
