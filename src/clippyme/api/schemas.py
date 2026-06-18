"""Pydantic request schemas for the ClippyMe FastAPI app."""
import ipaddress
import socket
from typing import Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

# ViralClip / ViralClipsResponse moved to the neutral clippyme.schemas module so
# the pipeline no longer imports from clippyme.api. Re-exported here for
# backward compatibility (existing imports from clippyme.api.schemas keep working).
from clippyme.schemas import ViralClip, ViralClipsResponse  # noqa: F401


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
    instructions: Optional[str] = Field(None, max_length=2000)
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled|object)$")
    aspect: Optional[str] = Field(None, pattern=r"^(9:16|1:1|16:9)$")
    language: Optional[str] = Field(None, max_length=16)
    no_zoom: Optional[bool] = False
    skip_analysis: Optional[bool] = False
    # Optional per-job Gemini model override. Validated against the gemini-
    # family prefix + safe charset (build_main_cmd.GEMINI_MODEL_RE) before it's
    # appended as --model to the pipeline argv. When omitted, the pipeline uses
    # GEMINI_MODEL from env / Settings (default gemini-3.5-flash).
    model: Optional[str] = Field(None, max_length=72, pattern=r"^gemini-[A-Za-z0-9.\-]{1,64}$")


class BatchRequest(BaseModel):
    urls: List[str] = Field(..., min_length=1, max_length=20)
    instructions: Optional[str] = Field(None, max_length=2000)
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled|object)$")
    aspect: Optional[str] = Field(None, pattern=r"^(9:16|1:1|16:9)$")

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
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled|object)$")


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


class ComposeRequest(BaseModel):
    toggles: dict = {}
    hook_params: dict = {}
    subtitle_params: dict = {}
    logo_params: dict = {}

    @field_validator("hook_params", "subtitle_params", "logo_params")
    @classmethod
    def _bound_overlay(cls, v):
        return _validate_overlay_params(v)


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
    scheduled_for: Optional[str] = None
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

    @field_validator("hook_params", "subtitle_params", "logo_params")
    @classmethod
    def _bound_overlay(cls, v):
        return _validate_overlay_params(v)

    @field_validator("platforms")
    @classmethod
    def _validate_platforms(cls, v: List[dict]) -> List[dict]:
        # Each entry is forwarded verbatim into Zernio's create-post payload.
        # Require it to be a small, flat object with a known platform + an
        # accountId, so an attacker can't smuggle arbitrary control keys
        # (publishNow, scheduledFor, webhookUrl, …) into the upstream request.
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
            # Bound the free-form per-platform payload too — it is forwarded
            # verbatim to Zernio, so cap size/depth like the overlay params.
            if "platformSpecificData" in item:
                _validate_overlay_params(item["platformSpecificData"])
        return v

    @field_validator("tiktok_settings")
    @classmethod
    def _bound_tiktok_settings(cls, v):
        # Forwarded verbatim into Zernio's create-post body; bound it so an
        # authenticated client can't smuggle a huge/nested object through.
        return _validate_overlay_params(v)


class ZernioConfigRequest(BaseModel):
    """Persisted Zernio settings (saved to data/config.json)."""
    api_key: Optional[str] = None
    accounts: Optional[dict] = None  # {"tiktok": "...", "instagram": "...", "youtube": "..."}
    timezone: Optional[str] = None
