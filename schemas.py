"""Pydantic request schemas for the ClippyMe FastAPI app."""
from typing import List, Optional

from pydantic import BaseModel, Field


class ProcessRequest(BaseModel):
    url: str


class BatchRequest(BaseModel):
    urls: List[str] = Field(..., min_length=1, max_length=20)
    instructions: Optional[str] = None
    reframe_mode: Optional[str] = None


class ConfigUpdateRequest(BaseModel):
    keys: dict


class SubtitleRequest(BaseModel):
    job_id: str = Field(..., pattern=r"^[0-9a-fA-F-]{36}$")
    clip_index: int
    position: str = "bottom"
    font_size: int = 16
    font_name: str = "Verdana"
    font_color: str = "#FFFFFF"
    border_color: str = "#000000"
    border_width: int = 2
    bg_color: str = "#000000"
    bg_opacity: float = 0.0
    input_filename: Optional[str] = None
    # Karaoke / viral subtitle options
    preset: Optional[str] = None  # e.g. "classic_white", "hormozi_bold"
    karaoke_mode: Optional[str] = None  # "word_group" or "full_line"
    words_per_group: int = 3
    uppercase: bool = True
    highlight_color: Optional[str] = None


class HookRequest(BaseModel):
    job_id: str = Field(..., pattern=r"^[0-9a-fA-F-]{36}$")
    clip_index: int
    text: str
    input_filename: Optional[str] = None
    position: str = "top"
    size: str = "M"


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
    timezone: str = "Europe/Rome"
    tiktok_settings: Optional[dict] = None
    # If true, force a fresh compose pass before upload using the supplied
    # toggles. If omitted, the latest composed clip on disk is used.
    compose_first: bool = False
    toggles: Optional[dict] = None
    hook_params: Optional[dict] = None
    subtitle_params: Optional[dict] = None


class ZernioConfigRequest(BaseModel):
    """Persisted Zernio settings (saved to data/config.json)."""
    api_key: Optional[str] = None
    accounts: Optional[dict] = None  # {"tiktok": "...", "instagram": "...", "youtube": "..."}
    timezone: Optional[str] = None
