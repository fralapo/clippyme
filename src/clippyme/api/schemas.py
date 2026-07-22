"""Pydantic request schemas for the ClippyMe FastAPI app."""
import ipaddress
import socket
from enum import Enum
from typing import Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

# ViralClip / ViralClipsResponse moved to the neutral clippyme.schemas module so
# the pipeline no longer imports from clippyme.api. Re-exported here for
# backward compatibility (existing imports from clippyme.api.schemas keep working).
from clippyme.schemas import ViralClip, ViralClipsResponse  # noqa: F401
from clippyme.domain.job_results import MAX_INSTRUCTIONS_LEN


class ManualPublishStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    all = "all"


def _reject_internal_host(host: str) -> None:
    """Raise ValueError if a hostname resolves to a private/loopback/link-local
    address. Best-effort SSRF guard: blocks the obvious metadata-endpoint and
    LAN targets while leaving public video URLs untouched. DNS failures are
    tolerated (the downstream downloader will fail safely)."""
    if not host:
        raise ValueError("url has no host")
    candidates = set()
    try:
        candidates.add(ipaddress.ip_address(host))
    except ValueError:
        try:
            for info in socket.getaddrinfo(host, None):
                try:
                    candidates.add(ipaddress.ip_address(info[4][0]))
                except ValueError:
                    continue
        except (socket.gaierror, UnicodeError):
            return  # unresolvable — let the downloader handle it
    for ip in candidates:
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError("url points to a non-public address")


def validate_public_url(value: str) -> str:
    """Enforce http(s) scheme + non-internal host. Used by Process/Batch."""
    raw = (value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("url must use http or https")
    _reject_internal_host((parsed.hostname or "").lower())
    return raw


class ProcessRequest(BaseModel):
    url: str = Field(..., max_length=2048)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        # Allow the internal multipart-upload placeholder unchanged; every
        # real submission must be a public http(s) URL (SSRF guard).
        if v == "https://upload.invalid/local":
            return v
        return validate_public_url(v)
    # Optional per-job knobs — mirror the BatchRequest so single and batch
    # jobs expose the same surface area to the frontend. All three are
    # validated downstream (reframe_mode by argparse choices, language by
    # ALLOWED_LANGUAGES in job_results.build_main_cmd, instructions by
    # length cap).
    instructions: Optional[str] = Field(None, max_length=MAX_INSTRUCTIONS_LEN)
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled|subject|object)$")
    aspect: Optional[str] = Field(None, pattern=r"^(9:16|1:1|16:9)$")
    language: Optional[str] = Field(None, max_length=16)
    no_zoom: Optional[bool] = False
    skip_analysis: Optional[bool] = False
    # Optional per-job Gemini model override. Validated against the gemini-
    # family prefix + safe charset (build_main_cmd.GEMINI_MODEL_RE) before it's
    # appended as --model to the pipeline argv. When omitted, the pipeline uses
    # GEMINI_MODEL from env / Settings (default gemini-3.5-flash).
    model: Optional[str] = Field(None, max_length=72, pattern=r"^gemini-[A-Za-z0-9.\-]{1,64}$")
    # Publish destination for this job's finished clips: "manual_queue" (default —
    # land in the Manual Publish tab for hand-review) or "zernio" (opt out of the
    # manual queue; the user will publish via the per-clip Zernio flow instead).
    # Mirrors LiveMonitorStartRequest.publisher_mode for consistency.
    publisher_mode: str = Field("manual_queue", pattern=r"^(manual_queue|zernio)$")


class BatchRequest(BaseModel):
    urls: List[str] = Field(..., min_length=1, max_length=20)
    instructions: Optional[str] = Field(None, max_length=MAX_INSTRUCTIONS_LEN)
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled|subject|object)$")
    aspect: Optional[str] = Field(None, pattern=r"^(9:16|1:1|16:9)$")
    publisher_mode: str = Field("manual_queue", pattern=r"^(manual_queue|zernio)$")

    @field_validator("urls")
    @classmethod
    def _validate_urls(cls, v: List[str]) -> List[str]:
        # Preserve the legacy "skip blanks" behaviour, validate the rest.
        return [validate_public_url(u) for u in v if (u or "").strip()]
    # Optional per-batch ASR language override. When omitted the pipeline
    # uses its default (Deepgram `multi` for EN+IT code-switching). Setting
    # this to a single-language code ("en", "it", "es", …) improves both
    # transcription accuracy AND speaker diarization reliability on audio
    # that isn't actually multilingual.
    language: Optional[str] = Field(None, max_length=16)
    no_zoom: Optional[bool] = False
    skip_analysis: Optional[bool] = False
    # Per-batch Gemini model override (applies to every job in the batch).
    model: Optional[str] = Field(None, max_length=72, pattern=r"^gemini-[A-Za-z0-9.\-]{1,64}$")


class ConfigUpdateRequest(BaseModel):
    # Typed as Dict[str, str] so non-string values are rejected at the
    # boundary. save_persistent_config further filters to VALID_CONFIG_KEYS.
    keys: Dict[str, str]

    @field_validator("keys")
    @classmethod
    def _cap_values(cls, v: Dict[str, str]) -> Dict[str, str]:
        # Cap each value to defeat a memory/disk-bloat write via a giant string.
        for name, val in v.items():
            if val is not None and len(val) > 4096:
                raise ValueError(f"config value for {name!r} too long (max 4096)")
        return v


class ReframeRequest(BaseModel):
    """Switch a clip between reframe modes after it has been generated.

    Only valid when the per-clip 16:9 source slice was preserved on disk
    (i.e. jobs produced after the post-hoc reframe feature landed).
    """
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled|subject|object)$")


# Overlay params (hook_params / subtitle_params) are intentionally left as
# free-form dicts so the frontend can evolve fields without a schema bump, but
# they flow into Pillow text rendering and ffmpeg numeric filter args. Without
# bounds, a single authenticated request with a multi-megabyte ``text`` or an
# absurd ``font_size`` can pin a worker (DoS). This validator enforces flat,
# bounded values without changing the downstream ``.get()`` access pattern.
_OVERLAY_MAX_KEYS = 40
_OVERLAY_MAX_STR = 1000
_OVERLAY_MAX_ABS_NUM = 100_000


def _validate_overlay_params(v):
    if v is None:
        return v
    if not isinstance(v, dict):
        raise ValueError("must be an object")
    if len(v) > _OVERLAY_MAX_KEYS:
        raise ValueError(f"too many keys (max {_OVERLAY_MAX_KEYS})")
    for key, val in v.items():
        if isinstance(val, str):
            if len(val) > _OVERLAY_MAX_STR:
                raise ValueError(f"value for {key!r} too long (max {_OVERLAY_MAX_STR})")
        elif isinstance(val, bool):
            continue
        elif isinstance(val, (int, float)):
            if abs(val) > _OVERLAY_MAX_ABS_NUM:
                raise ValueError(f"value for {key!r} out of range")
        elif val is None:
            continue
        else:
            # Reject nested dicts/lists — overlay params are flat scalars.
            raise ValueError(f"value for {key!r} must be a scalar")
    return v


# Manual-trim drop spans. Bounds mirror the overlay validator's intent: keep an
# authenticated request from handing the worker an absurd list. The smartcut
# engine (normalize_drop_ranges) re-validates, so this is a cheap front gate.
_DROP_MAX_RANGES = 500
_DROP_MAX_SECONDS = 100_000


def _validate_drop_ranges(v):
    if v is None:
        return v
    if not isinstance(v, list):
        raise ValueError("drop_ranges must be a list")
    if len(v) > _DROP_MAX_RANGES:
        raise ValueError(f"too many drop_ranges (max {_DROP_MAX_RANGES})")
    for item in v:
        # Accept [start, end] pairs or {"start","end"} objects; the engine
        # coerces both. Just bound the numeric magnitude here.
        if isinstance(item, dict):
            nums = (item.get("start"), item.get("end"))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            nums = (item[0], item[1])
        else:
            raise ValueError("each drop range must be [start, end] or {start, end}")
        for n in nums:
            if not isinstance(n, (int, float)) or isinstance(n, bool):
                raise ValueError("drop range bounds must be numbers")
            if abs(n) > _DROP_MAX_SECONDS:
                raise ValueError("drop range bound out of range")
    return v


def validate_publish_platforms(v: List[dict]) -> List[dict]:
    """Validate a list of Zernio platform targets.

    Each entry is forwarded verbatim into Zernio's create-post payload, so it
    must be a small flat object with a known platform + an accountId (no
    smuggled control keys like publishNow / webhookUrl). Shared by
    PublishRequest and LiveMonitorStartRequest.
    """
    allowed = {"tiktok", "instagram", "youtube"}
    for item in v:
        if not isinstance(item, dict):
            raise ValueError("each platform must be an object")
        platform = item.get("platform")
        if platform not in allowed:
            raise ValueError(f"platform must be one of {sorted(allowed)}")
        acct = item.get("accountId")
        if not isinstance(acct, str) or not acct or len(acct) > 256:
            raise ValueError("accountId must be a non-empty string (max 256)")
        extra = set(item) - {"platform", "accountId", "platformSpecificData"}
        if extra:
            raise ValueError(f"unexpected platform keys: {sorted(extra)}")
        if "platformSpecificData" in item:
            _validate_overlay_params(item["platformSpecificData"])
    return v


class ComposeRequest(BaseModel):
    toggles: dict = {}
    hook_params: dict = {}
    subtitle_params: dict = {}
    logo_params: dict = {}
    grade_params: dict = {}
    # Attribution banner: {enabled, platform, handle, y_pct?, mode?}. Flat scalar
    # dict like the other overlay params (bounded below). `enabled` acts as the
    # banner's own active flag (no separate toggles entry required).
    banner_params: dict = {}
    # Manual Smart Cut trim: hand-picked [[start, end], …] spans (clip-relative
    # seconds) removed on top of the automatic filler/silence pass.
    drop_ranges: list = []

    @field_validator("hook_params", "subtitle_params", "logo_params", "grade_params",
                     "banner_params")
    @classmethod
    def _bound_overlay(cls, v):
        return _validate_overlay_params(v)

    @field_validator("drop_ranges")
    @classmethod
    def _bound_drops(cls, v):
        return _validate_drop_ranges(v)


class EditAIRequest(BaseModel):
    """Natural-language clip-trim request — Gemini returns spans to cut."""
    instruction: str = Field(..., min_length=1, max_length=1000)
    model: Optional[str] = Field(
        None, max_length=64, pattern=r"^gemini-[A-Za-z0-9.\-]{1,64}$"
    )


class PublishRequest(BaseModel):
    """Schedule a clip on social platforms via Zernio.

    schedule_mode:
      - "now"     → publish immediately
      - "auto"    → SmartScheduler picks the next optimal slot
      - "manual"  → caller passes scheduled_for (ISO 8601)

    platforms is a list of {platform, accountId, platformSpecificData?} dicts
    matching Zernio's create-post schema.
    """
    title: str = Field("", max_length=500)
    caption: str = Field("", max_length=2200)
    platforms: List[dict] = Field(..., min_length=1, max_length=14)
    schedule_mode: str = Field("now", pattern=r"^(now|auto|manual)$")
    scheduled_for: Optional[str] = Field(None, max_length=64)
    # Optional YYYY-MM-DD that defines the day the SmartScheduler should
    # start picking slots from when schedule_mode="auto". Ignored by
    # "now" / "manual". Defaults to today if omitted.
    start_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    timezone: str = Field("Europe/Rome", max_length=64)
    tiktok_settings: Optional[dict] = None

    @field_validator("timezone")
    @classmethod
    def _validate_tz(cls, v: str) -> str:
        # Reject unknown IANA zones at the boundary (defends SmartScheduler /
        # Zernio from a crafted tz string). Falls back to allowing the value
        # if the tz database isn't available on the host.
        try:
            from zoneinfo import available_timezones
            if v not in available_timezones():
                raise ValueError(f"unknown timezone: {v!r}")
        except ImportError:
            pass
        return v

    @field_validator("scheduled_for")
    @classmethod
    def _validate_scheduled_for(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        from datetime import datetime
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as exc:
            raise ValueError("scheduled_for must be an ISO 8601 timestamp") from exc
        return v
    # If true, force a fresh compose pass before upload using the supplied
    # toggles. If omitted, the latest composed clip on disk is used.
    compose_first: bool = False
    toggles: Optional[dict] = None
    hook_params: Optional[dict] = None
    subtitle_params: Optional[dict] = None
    logo_params: Optional[dict] = None
    grade_params: Optional[dict] = None
    banner_params: Optional[dict] = None
    drop_ranges: Optional[list] = None

    @field_validator("hook_params", "subtitle_params", "logo_params", "grade_params",
                     "banner_params")
    @classmethod
    def _bound_overlay(cls, v):
        return _validate_overlay_params(v)

    @field_validator("drop_ranges")
    @classmethod
    def _bound_drops(cls, v):
        return None if v is None else _validate_drop_ranges(v)

    @field_validator("platforms")
    @classmethod
    def _validate_platforms(cls, v: List[dict]) -> List[dict]:
        return validate_publish_platforms(v)

    @field_validator("tiktok_settings")
    @classmethod
    def _bound_tiktok_settings(cls, v):
        # Forwarded verbatim into Zernio's create-post body; bound it so an
        # authenticated client can't smuggle a huge/nested object through.
        return _validate_overlay_params(v)


class LiveMonitorStartRequest(BaseModel):
    """Start a content monitor for one channel on one platform.

    All runtime config is body-supplied (no env). ``platforms`` reuses the same
    Zernio target validation as PublishRequest; every produced clip is published
    with schedule_mode='auto' and a shared >=min_gap_seconds spacing that is
    GLOBAL across all running monitors.

    ``platform`` (default 'kick' for back-compat) and ``mode`` (default 'live')
    select the source. ``slug`` is the channel: a kick/twitch login, or for
    youtube an @handle / UC… id / channel URL. Per-platform channel validation
    (and the youtube-can't-do-live rule) is enforced in the domain layer, which
    raises a clean 400, so the schema keeps ``slug`` permissive.
    """
    slug: str = Field(..., min_length=1, max_length=256)
    platform: str = Field("kick", pattern=r"^(kick|twitch|youtube)$")
    mode: str = Field("live", pattern=r"^(live|vod)$")
    # Manual delivery is the safe default and needs no Zernio targets. The
    # domain layer requires targets when publisher_mode='zernio'.
    publisher_mode: str = Field("manual_queue", pattern=r"^(manual_queue|zernio)$")
    platforms: Optional[List[dict]] = Field(None, max_length=14)
    segment_seconds: int = Field(1800, ge=60, le=3600)
    prelive_skip_seconds: int = Field(1800, ge=0, le=7200)
    min_gap_seconds: int = Field(900, ge=0, le=86400)
    # Optional: domain picks a mode-appropriate default (60s live / 600s vod).
    poll_interval: Optional[int] = Field(None, ge=30, le=3600)
    loop: bool = False
    caption_template: str = Field("", max_length=2200)
    title_template: str = Field("", max_length=500)
    # AI instructions steering Gemini viral-clip selection — mirrors
    # ProcessRequest.instructions (same cap; domain layer trims/re-caps).
    instructions: Optional[str] = Field(None, max_length=MAX_INSTRUCTIONS_LEN)
    timezone: Optional[str] = Field(None, max_length=64)
    # Attribution-banner override for auto-published clips. None → auto from the
    # monitor's own platform + channel; {"enabled": false} disables it; a dict
    # overrides {platform, handle, y_pct}. Flat scalar dict (bounded).
    banner: Optional[dict] = None
    # Optional compose-recipe overrides for the monitor's auto-publish flow:
    # {toggles?, hook_params?, subtitle_params?, banner?}. Defaults (hook top,
    # banner attached under the letterbox band, subtitles bottom-left) apply
    # when omitted. Shallow-merged over the defaults in build_monitor_compose.
    compose: Optional[dict] = None

    @field_validator("banner")
    @classmethod
    def _bound_banner(cls, v):
        return _validate_overlay_params(v)

    @field_validator("compose")
    @classmethod
    def _bound_compose(cls, v):
        # Nested overlay dicts are allowed here (hook_params/subtitle_params/
        # banner), so bound each nested value individually but keep the shape.
        if v is None:
            return v
        if not isinstance(v, dict):
            raise ValueError("compose must be an object")
        if len(v) > 8:
            raise ValueError("compose has too many keys")
        for key, val in v.items():
            if isinstance(val, dict):
                _validate_overlay_params(val)
            elif not isinstance(val, (str, int, float, bool)) and val is not None:
                raise ValueError(f"compose[{key!r}] must be a scalar or object")
        return v

    @field_validator("slug")
    @classmethod
    def _clean_slug(cls, v: str) -> str:
        v = v.strip()
        if not v or any(c.isspace() for c in v):
            raise ValueError("channel must not be blank or contain whitespace")
        return v

    @field_validator("platforms")
    @classmethod
    def _validate_platforms(cls, v: Optional[List[dict]]) -> Optional[List[dict]]:
        return None if v is None else validate_publish_platforms(v)

    @model_validator(mode="after")
    def _zernio_requires_platforms(self):
        if self.publisher_mode == "zernio" and not self.platforms:
            raise ValueError("at least one platform target is required for zernio")
        return self


class ZernioConfigRequest(BaseModel):
    """Persisted Zernio settings (saved to data/config.json)."""
    api_key: Optional[str] = Field(None, max_length=512)
    accounts: Optional[dict] = None  # {"tiktok": "...", "instagram": "...", "youtube": "..."}
    timezone: Optional[str] = Field(None, max_length=64)

    @field_validator("accounts")
    @classmethod
    def _validate_accounts(cls, v):
        if v is None:
            return v
        if len(v) > 16:
            raise ValueError("too many account entries")
        allowed = {"tiktok", "instagram", "youtube"}
        for k, val in v.items():
            if k not in allowed:
                raise ValueError(f"unknown account platform: {k!r}")
            if val is not None and (not isinstance(val, str) or len(val) > 256):
                raise ValueError(f"account id for {k!r} must be a string <= 256 chars")
        return v
