"""Pydantic request schemas for the ClippyMe FastAPI app."""
from __future__ import annotations

import ipaddress
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from clippyme.domain.job_results import ALLOWED_LANGUAGES, MAX_INSTRUCTIONS_LEN
from clippyme.netutil import resolve_host_addresses
from clippyme.schemas import ViralClip, ViralClipsResponse  # noqa: F401


def _reject_internal_host(host: str) -> None:
    """Reject literal or DNS-resolved non-public hosts without unbounded DNS I/O.

    DNS failures and timeouts remain best-effort at this early API boundary; the
    downloader performs the authoritative rebinding-aware check immediately
    before the network request.
    """
    if not host:
        raise ValueError("url has no host")
    try:
        candidates = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            candidates = set(resolve_host_addresses(host, timeout=5.0))
        except (OSError, TimeoutError, UnicodeError):
            return
    for ip in candidates:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError("url points to a non-public address")


def validate_public_url(value: str) -> str:
    """Enforce an HTTP(S) URL with a non-internal host."""
    raw = (value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("url must use http or https")
    _reject_internal_host((parsed.hostname or "").lower())
    return raw


def _validate_language(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized not in ALLOWED_LANGUAGES:
        raise ValueError(f"unsupported language: {value!r}")
    return normalized


def _validate_timezone(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError("timezone must not be blank")
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {normalized!r}") from exc
    except ImportError:  # pragma: no cover - Python 3.11 always has zoneinfo
        pass
    return normalized


class ProcessRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    instructions: Optional[str] = Field(None, max_length=MAX_INSTRUCTIONS_LEN)
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled|subject|object)$")
    aspect: Optional[str] = Field(None, pattern=r"^(9:16|1:1|16:9)$")
    language: Optional[str] = Field(None, max_length=16)
    no_zoom: Optional[bool] = False
    skip_analysis: Optional[bool] = False
    model: Optional[str] = Field(
        None, max_length=72, pattern=r"^gemini-[A-Za-z0-9.\-]{1,64}$"
    )

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        if value == "https://upload.invalid/local":
            return value
        return validate_public_url(value)

    @field_validator("language")
    @classmethod
    def _bound_language(cls, value: Optional[str]) -> Optional[str]:
        return _validate_language(value)


class BatchRequest(BaseModel):
    urls: List[str] = Field(..., min_length=1, max_length=20)
    instructions: Optional[str] = Field(None, max_length=MAX_INSTRUCTIONS_LEN)
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled|subject|object)$")
    aspect: Optional[str] = Field(None, pattern=r"^(9:16|1:1|16:9)$")
    language: Optional[str] = Field(None, max_length=16)
    no_zoom: Optional[bool] = False
    skip_analysis: Optional[bool] = False
    model: Optional[str] = Field(
        None, max_length=72, pattern=r"^gemini-[A-Za-z0-9.\-]{1,64}$"
    )

    @field_validator("urls")
    @classmethod
    def _validate_urls(cls, values: List[str]) -> List[str]:
        cleaned = [validate_public_url(url) for url in values if (url or "").strip()]
        if not cleaned:
            raise ValueError("at least one non-blank URL is required")
        return cleaned

    @field_validator("language")
    @classmethod
    def _bound_language(cls, value: Optional[str]) -> Optional[str]:
        return _validate_language(value)


class ConfigUpdateRequest(BaseModel):
    keys: Dict[str, str]

    @field_validator("keys")
    @classmethod
    def _cap_values(cls, values: Dict[str, str]) -> Dict[str, str]:
        for name, value in values.items():
            if value is not None and len(value) > 4096:
                raise ValueError(f"config value for {name!r} too long (max 4096)")
        return values


class ReframeRequest(BaseModel):
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled|subject|object)$")


_OVERLAY_MAX_KEYS = 40
_OVERLAY_MAX_STR = 1000
_OVERLAY_MAX_ABS_NUM = 100_000


def _validate_overlay_params(value):
    if value is None:
        return value
    if not isinstance(value, dict):
        raise ValueError("must be an object")
    if len(value) > _OVERLAY_MAX_KEYS:
        raise ValueError(f"too many keys (max {_OVERLAY_MAX_KEYS})")
    for key, item in value.items():
        if isinstance(item, str):
            if len(item) > _OVERLAY_MAX_STR:
                raise ValueError(f"value for {key!r} too long (max {_OVERLAY_MAX_STR})")
        elif isinstance(item, bool):
            continue
        elif isinstance(item, (int, float)):
            if abs(item) > _OVERLAY_MAX_ABS_NUM:
                raise ValueError(f"value for {key!r} out of range")
        elif item is None:
            continue
        else:
            raise ValueError(f"value for {key!r} must be a scalar")
    return value


_DROP_MAX_RANGES = 500
_DROP_MAX_SECONDS = 100_000


def _validate_drop_ranges(value):
    if value is None:
        return value
    if not isinstance(value, list):
        raise ValueError("drop_ranges must be a list")
    if len(value) > _DROP_MAX_RANGES:
        raise ValueError(f"too many drop_ranges (max {_DROP_MAX_RANGES})")
    for item in value:
        if isinstance(item, dict):
            numbers = (item.get("start"), item.get("end"))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            numbers = (item[0], item[1])
        else:
            raise ValueError("each drop range must be [start, end] or {start, end}")
        for number in numbers:
            if not isinstance(number, (int, float)) or isinstance(number, bool):
                raise ValueError("drop range bounds must be numbers")
            if abs(number) > _DROP_MAX_SECONDS:
                raise ValueError("drop range bound out of range")
    return value


def validate_publish_platforms(value: List[dict]) -> List[dict]:
    """Validate the small, flat Zernio target objects forwarded downstream."""
    allowed = {"tiktok", "instagram", "youtube"}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each platform must be an object")
        platform = item.get("platform")
        if platform not in allowed:
            raise ValueError(f"platform must be one of {sorted(allowed)}")
        account_id = item.get("accountId")
        if not isinstance(account_id, str) or not account_id or len(account_id) > 256:
            raise ValueError("accountId must be a non-empty string (max 256)")
        extra = set(item) - {"platform", "accountId", "platformSpecificData"}
        if extra:
            raise ValueError(f"unexpected platform keys: {sorted(extra)}")
        if "platformSpecificData" in item:
            _validate_overlay_params(item["platformSpecificData"])
    return value


class ComposeRequest(BaseModel):
    toggles: dict = Field(default_factory=dict)
    hook_params: dict = Field(default_factory=dict)
    subtitle_params: dict = Field(default_factory=dict)
    logo_params: dict = Field(default_factory=dict)
    grade_params: dict = Field(default_factory=dict)
    banner_params: dict = Field(default_factory=dict)
    drop_ranges: list = Field(default_factory=list)

    @field_validator(
        "hook_params", "subtitle_params", "logo_params", "grade_params", "banner_params"
    )
    @classmethod
    def _bound_overlay(cls, value):
        return _validate_overlay_params(value)

    @field_validator("drop_ranges")
    @classmethod
    def _bound_drops(cls, value):
        return _validate_drop_ranges(value)


class EditAIRequest(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=1000)
    model: Optional[str] = Field(
        None, max_length=64, pattern=r"^gemini-[A-Za-z0-9.\-]{1,64}$"
    )


class PublishRequest(BaseModel):
    title: str = Field("", max_length=500)
    caption: str = Field("", max_length=2200)
    platforms: List[dict] = Field(..., min_length=1, max_length=14)
    schedule_mode: str = Field("now", pattern=r"^(now|auto|manual)$")
    scheduled_for: Optional[str] = Field(None, max_length=64)
    start_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    timezone: str = Field("Europe/Rome", max_length=64)
    tiktok_settings: Optional[dict] = None
    compose_first: bool = False
    toggles: Optional[dict] = None
    hook_params: Optional[dict] = None
    subtitle_params: Optional[dict] = None
    logo_params: Optional[dict] = None
    grade_params: Optional[dict] = None
    banner_params: Optional[dict] = None
    drop_ranges: Optional[list] = None

    @field_validator("timezone")
    @classmethod
    def _validate_tz(cls, value: str) -> str:
        return _validate_timezone(value)  # type: ignore[return-value]

    @field_validator("scheduled_for")
    @classmethod
    def _validate_scheduled_for(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as exc:
            raise ValueError("scheduled_for must be an ISO 8601 timestamp") from exc
        return value

    @field_validator(
        "hook_params", "subtitle_params", "logo_params", "grade_params", "banner_params"
    )
    @classmethod
    def _bound_overlay(cls, value):
        return _validate_overlay_params(value)

    @field_validator("drop_ranges")
    @classmethod
    def _bound_drops(cls, value):
        return None if value is None else _validate_drop_ranges(value)

    @field_validator("platforms")
    @classmethod
    def _validate_platforms(cls, value: List[dict]) -> List[dict]:
        return validate_publish_platforms(value)

    @field_validator("tiktok_settings")
    @classmethod
    def _bound_tiktok_settings(cls, value):
        return _validate_overlay_params(value)


class LiveMonitorPublishingRequest(BaseModel):
    # Strict prevents strings such as 'false' from being coerced to True.
    enabled: bool = Field(strict=True)


class LiveMonitorStartRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=256)
    platform: str = Field("kick", pattern=r"^(kick|twitch|youtube)$")
    mode: str = Field("live", pattern=r"^(live|vod)$")
    platforms: List[dict] = Field(..., min_length=1, max_length=14)
    segment_seconds: int = Field(1800, ge=60, le=3600)
    prelive_skip_seconds: int = Field(1800, ge=0, le=7200)
    min_gap_seconds: int = Field(900, ge=0, le=86400)
    poll_interval: Optional[int] = Field(None, ge=30, le=3600)
    loop: bool = False
    caption_template: str = Field("", max_length=2200)
    title_template: str = Field("", max_length=500)
    instructions: Optional[str] = Field(None, max_length=MAX_INSTRUCTIONS_LEN)
    timezone: Optional[str] = Field(None, max_length=64)
    banner: Optional[dict] = None
    compose: Optional[dict] = None
    catchup: str = Field("backfill", pattern=r"^(backfill|live_only)$")
    delete_after_publish: bool = True
    max_clips: int = Field(5, ge=1, le=50)

    @field_validator("timezone")
    @classmethod
    def _validate_tz(cls, value: Optional[str]) -> Optional[str]:
        return _validate_timezone(value)

    @field_validator("banner")
    @classmethod
    def _bound_banner(cls, value):
        return _validate_overlay_params(value)

    @field_validator("compose")
    @classmethod
    def _bound_compose(cls, value):
        if value is None:
            return value
        if not isinstance(value, dict):
            raise ValueError("compose must be an object")
        if len(value) > 8:
            raise ValueError("compose has too many keys")
        for key, item in value.items():
            if isinstance(item, dict):
                _validate_overlay_params(item)
            elif not isinstance(item, (str, int, float, bool)) and item is not None:
                raise ValueError(f"compose[{key!r}] must be a scalar or object")
        return value

    @field_validator("slug")
    @classmethod
    def _clean_slug(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError("channel must not be blank or contain whitespace")
        return normalized

    @field_validator("platforms")
    @classmethod
    def _validate_platforms(cls, value: List[dict]) -> List[dict]:
        return validate_publish_platforms(value)


class ZernioConfigRequest(BaseModel):
    api_key: Optional[str] = Field(None, max_length=512)
    accounts: Optional[dict] = None
    timezone: Optional[str] = Field(None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def _validate_tz(cls, value: Optional[str]) -> Optional[str]:
        return _validate_timezone(value)

    @field_validator("accounts")
    @classmethod
    def _validate_accounts(cls, value):
        if value is None:
            return value
        if not isinstance(value, dict):
            raise ValueError("accounts must be an object")
        if len(value) > 16:
            raise ValueError("too many account entries")
        allowed = {"tiktok", "instagram", "youtube"}
        for platform, account_id in value.items():
            if platform not in allowed:
                raise ValueError(f"unknown account platform: {platform!r}")
            if account_id is not None and (
                not isinstance(account_id, str) or len(account_id) > 256
            ):
                raise ValueError(
                    f"account id for {platform!r} must be a string <= 256 chars"
                )
        return value
