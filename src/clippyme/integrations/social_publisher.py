"""
social_publisher — publish/schedule clips to social platforms via Zernio.

Provides:
- ZernioClient: minimal REST client (no third-party SDK), uses requests
- SmartScheduler: optimal-slot picker with anti-collision (replicates the
  Italian-prime-time logic from the user-provided reference script)
- publish_clip(): high-level orchestrator used by the FastAPI endpoint

Three scheduling modes are supported:
- "now"          → publishNow=true, immediate publish
- "auto"         → SmartScheduler picks the best slot avoiding collisions
- "manual"       → caller passes an explicit ISO 8601 timestamp

Multi-platform: accepts a list of {platform, accountId, platformSpecificData?}
entries. The platformSpecificData payload is platform-specific (TikTok needs
privacy_level + consent flags, YouTube needs visibility, etc.) and is passed
through verbatim to Zernio.

This module is import-safe with no auto-editor / smartcut deps. Network calls
only happen when ZernioClient methods are invoked. SmartScheduler is pure
Python and unit-testable without any HTTP mock.
"""
from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

def _safe_zernio_base_url() -> str:
    """Resolve ZERNIO_BASE_URL with a strict allowlist on the host.

    The Zernio integration uploads clip media and exchanges a long-lived
    API key on every call. Allowing an arbitrary override via env var would
    be an SSRF-by-configuration primitive (a compromised env could redirect
    every clip + every API key to an attacker-controlled host). We therefore
    only honour overrides that are HTTPS and resolve to the official
    `zernio.com` apex (or its `*.zernio.com` subdomains).
    """
    default = "https://zernio.com/api/v1"
    raw = os.environ.get("ZERNIO_BASE_URL", default).strip()
    if not raw:
        return default
    try:
        from urllib.parse import urlparse
        parsed = urlparse(raw)
    except Exception:
        return default
    if parsed.scheme != "https":
        logger.warning("Ignoring ZERNIO_BASE_URL with non-https scheme: %r", raw)
        return default
    host = (parsed.hostname or "").lower()
    if host != "zernio.com" and not host.endswith(".zernio.com"):
        logger.warning("Ignoring ZERNIO_BASE_URL with unauthorised host: %r", raw)
        return default
    return raw


ZERNIO_BASE_URL = _safe_zernio_base_url()
DEFAULT_TIMEZONE = os.environ.get("ZERNIO_DEFAULT_TZ", "Europe/Rome")
HTTP_TIMEOUT_SECONDS = int(os.environ.get("ZERNIO_HTTP_TIMEOUT", "60"))
UPLOAD_TIMEOUT_SECONDS = int(os.environ.get("ZERNIO_UPLOAD_TIMEOUT", "600"))

# Italian-prime-time slots (CET/CEST), tuned for TikTok / Reels / Shorts.
# weekday → list of (hour_start, hour_end) windows. Same data as the user's
# reference script.
DEFAULT_SLOT_WINDOWS: dict[int, list[tuple[int, int]]] = {
    0: [(12, 14), (18, 21)],   # Monday
    1: [(9, 12), (14, 22)],    # Tuesday
    2: [(7, 11), (14, 22)],    # Wednesday
    3: [(9, 12), (15, 21)],    # Thursday
    4: [(11, 15), (16, 22)],   # Friday
    5: [(9, 13), (15, 20)],    # Saturday
    6: [(8, 17), (18, 20)],    # Sunday
}

MIN_GAP_BETWEEN_POSTS_SECONDS = int(os.environ.get("ZERNIO_MIN_GAP_SECONDS", "5400"))  # 90 min


# ---------------------------------------------------------------------------
# ZernioClient — minimal requests-based REST client
# ---------------------------------------------------------------------------


class ZernioError(Exception):
    """Wraps any HTTP / API failure from Zernio."""

    def __init__(self, message: str, status_code: Optional[int] = None, body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class ZernioClient:
    def __init__(self, api_key: str, base_url: str = ZERNIO_BASE_URL):
        if not api_key or not isinstance(api_key, str):
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ClippyMe-SocialPublisher/1.0",
        })

    # -- internal --------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self._base}{path}"
        kwargs.setdefault("timeout", HTTP_TIMEOUT_SECONDS)
        try:
            r = self._session.request(method, url, **kwargs)
        except requests.RequestException as e:
            raise ZernioError(f"network error: {e}") from e
        if r.status_code >= 400:
            raise ZernioError(
                f"Zernio {method} {path} → HTTP {r.status_code}",
                status_code=r.status_code,
                body=r.text[:500],
            )
        try:
            return r.json()
        except ValueError:
            return None

    # -- public ----------------------------------------------------------

    def list_accounts(self) -> list[dict]:
        """GET /v1/accounts — discovery for the Settings UI."""
        data = self._request("GET", "/accounts")
        if isinstance(data, dict):
            return data.get("accounts", []) or []
        return data or []

    def list_scheduled_posts(self, date_from: str, date_to: str, limit: int = 100) -> list[dict]:
        """GET /v1/posts?status=scheduled&dateFrom&dateTo — for collision check."""
        data = self._request(
            "GET", "/posts",
            params={"status": "scheduled", "dateFrom": date_from, "dateTo": date_to, "limit": limit},
        )
        if isinstance(data, dict):
            return data.get("posts", []) or []
        return data or []

    def presign_upload(self, filename: str, content_type: str = "video/mp4",
                       size_bytes: Optional[int] = None) -> dict:
        """POST /v1/media/presign — returns {uploadUrl, publicUrl, key, type}."""
        body: dict[str, Any] = {"filename": filename, "contentType": content_type}
        if size_bytes is not None:
            body["size"] = int(size_bytes)
        return self._request("POST", "/media/presign", json=body)

    def upload_to_presigned(self, upload_url: str, file_path: str, content_type: str = "video/mp4") -> None:
        """PUT the file to the presigned URL. Plain HTTP, no Authorization header."""
        with open(file_path, "rb") as f:
            try:
                r = requests.put(
                    upload_url,
                    data=f,
                    headers={"Content-Type": content_type},
                    timeout=UPLOAD_TIMEOUT_SECONDS,
                )
            except requests.RequestException as e:
                raise ZernioError(f"upload network error: {e}") from e
        if r.status_code >= 400:
            raise ZernioError(
                f"upload PUT failed: HTTP {r.status_code}",
                status_code=r.status_code, body=r.text[:300],
            )

    def create_post(
        self,
        *,
        content: str,
        media_items: list[dict],
        platforms: list[dict],
        scheduled_for: Optional[str] = None,
        timezone: str = DEFAULT_TIMEZONE,
        publish_now: bool = False,
        tiktok_settings: Optional[dict] = None,
        title: Optional[str] = None,
    ) -> dict:
        """POST /v1/posts — create the post (scheduled or immediate)."""
        body: dict[str, Any] = {
            "content": content,
            "mediaItems": media_items,
            "platforms": platforms,
            "timezone": timezone,
        }
        if title:
            body["title"] = title
        if publish_now:
            body["publishNow"] = True
        elif scheduled_for:
            body["scheduledFor"] = scheduled_for
        if tiktok_settings:
            body["tiktokSettings"] = tiktok_settings
        return self._request("POST", "/posts", json=body)


# ---------------------------------------------------------------------------
# SmartScheduler — picks an optimal posting time
# ---------------------------------------------------------------------------


@dataclass
class SmartScheduler:
    """Replicates the user-provided 'trova_orario_smart' logic.

    1. Try to find a slot window with NO existing posts and place the post
       inside it (random hour/minute), respecting the minimum gap.
    2. Otherwise, scan every 15 minutes between 07:00 and 23:00 looking for
       a slot that's at least min_gap_seconds away from every existing post.
    3. Fallback: pick a random hour inside any slot window.
    """
    slot_windows: dict[int, list[tuple[int, int]]] = field(default_factory=lambda: dict(DEFAULT_SLOT_WINDOWS))
    min_gap_seconds: int = MIN_GAP_BETWEEN_POSTS_SECONDS
    rng: random.Random = field(default_factory=random.Random)

    def _windows_for(self, weekday: int) -> list[tuple[int, int]]:
        return self.slot_windows.get(weekday, self.slot_windows[0])

    def _is_window_free(self, day: date, window: tuple[int, int], occupied: list[datetime]) -> bool:
        start = datetime.combine(day, time(hour=window[0]))
        end = datetime.combine(day, time(hour=window[1]))
        return not any(start <= t < end for t in occupied)

    def _gap_ok(self, candidate: datetime, occupied: list[datetime]) -> bool:
        return all(abs((candidate - o).total_seconds()) >= self.min_gap_seconds for o in occupied)

    def find_slot(self, day: date, occupied: list[datetime], now: Optional[datetime] = None) -> datetime:
        now = now or datetime.now()
        weekday = day.weekday()
        windows = self._windows_for(weekday)

        # 1. Free window
        free_windows = [w for w in windows if self._is_window_free(day, w, occupied)]
        if free_windows:
            window = self.rng.choice(free_windows)
            for _ in range(30):
                hour = self.rng.randint(window[0], window[1] - 1)
                minute = self.rng.randint(0, 59)
                candidate = datetime.combine(day, time(hour=hour, minute=minute))
                if candidate > now and self._gap_ok(candidate, occupied):
                    return candidate

        # 2. 15-minute scan inside the safe daytime range
        candidates: list[datetime] = []
        base = datetime.combine(day, time(hour=7))
        for i in range(0, 16 * 4):
            candidate = base + timedelta(minutes=i * 15)
            if candidate > now and self._gap_ok(candidate, occupied):
                candidates.append(candidate)
        if candidates:
            return self.rng.choice(candidates)

        # 3. Last-resort random pick inside any slot window
        window = self.rng.choice(windows)
        return datetime.combine(
            day,
            time(hour=self.rng.randint(window[0], window[1] - 1), minute=self.rng.randint(0, 59)),
        )


# ---------------------------------------------------------------------------
# publish_clip — high-level orchestrator used by the FastAPI endpoint
# ---------------------------------------------------------------------------


def _validate_platform_targets(platform_targets: list[dict]) -> None:
    if not platform_targets:
        raise ValueError("at least one platform target is required")
    for entry in platform_targets:
        if not isinstance(entry, dict):
            raise ValueError("each platform target must be a dict")
        if not entry.get("platform"):
            raise ValueError("platform target missing 'platform' field")
        if not entry.get("accountId"):
            raise ValueError(f"platform target {entry.get('platform')} missing 'accountId'")


def publish_clip(
    *,
    api_key: str,
    clip_path: str,
    title: str,
    caption: str,
    platform_targets: list[dict],
    schedule_mode: str = "now",
    scheduled_for: Optional[str] = None,
    timezone: str = DEFAULT_TIMEZONE,
    tiktok_settings: Optional[dict] = None,
    scheduler: Optional[SmartScheduler] = None,
    start_date: Optional[str] = None,
) -> dict:
    """Publish a single clip via Zernio.

    Args:
        api_key: Zernio API key (sk_...). Never logged.
        clip_path: absolute path to the .mp4 to upload.
        title: post title (used by YouTube etc.)
        caption: post text/content
        platform_targets: list of {platform, accountId, platformSpecificData?}
        schedule_mode: "now" | "auto" | "manual"
        scheduled_for: ISO 8601 timestamp (required when schedule_mode="manual")
        timezone: IANA tz string passed to Zernio
        tiktok_settings: optional root-level TikTok settings (consent, privacy)
        scheduler: optional injected SmartScheduler (testing)

    Returns:
        {
            "post_id": str | None,
            "status": str,
            "scheduled_for": str | None,
            "schedule_mode": str,
            "platforms": [...],
        }

    Raises:
        ValueError on invalid input, ZernioError on API failures.
    """
    if not os.path.isfile(clip_path):
        raise ValueError(f"clip not found: {clip_path}")
    _validate_platform_targets(platform_targets)
    if schedule_mode not in ("now", "auto", "manual"):
        raise ValueError(f"unknown schedule_mode: {schedule_mode}")
    if schedule_mode == "manual":
        if not scheduled_for:
            raise ValueError("schedule_mode='manual' requires scheduled_for")
        try:
            # Accept a trailing 'Z' (UTC) by normalising to +00:00, which
            # datetime.fromisoformat understands on all supported Pythons.
            datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                f"scheduled_for must be an ISO 8601 timestamp: {scheduled_for!r}"
            ) from exc

    # Caption fallback: TikTok and Instagram have no concept of a separate
    # "title" field — the text shown under the video is whatever we pass as
    # `content`. If the user typed a title but left the caption blank, we
    # want TikTok/IG to show the title instead of being empty. YouTube uses
    # the separate `title` field at the Zernio root, so it's unaffected.
    effective_content = (caption or "").strip() or (title or "").strip()
    logger.info(
        "publish_clip: platforms=%s content_len=%d title_len=%d mode=%s",
        [p.get("platform") for p in platform_targets],
        len(effective_content), len(title or ""), schedule_mode,
    )

    client = ZernioClient(api_key)

    # 1. Resolve scheduled_for based on mode
    publish_now = schedule_mode == "now"
    final_scheduled_for: Optional[str] = None
    if schedule_mode == "auto":
        # Pick a slot today (or tomorrow if it's late), or honour an
        # explicit start_date from the caller (batch publish UI lets the
        # user pick the day the schedule should begin).
        sched = scheduler or SmartScheduler()
        now = datetime.now()
        if start_date:
            try:
                requested = datetime.strptime(start_date, "%Y-%m-%d").date()
            except ValueError as exc:
                raise ValueError(f"invalid start_date, expected YYYY-MM-DD: {start_date}") from exc
            # Never schedule in the past — bump to today if the user picked
            # a day that has already passed.
            target_day = max(requested, now.date())
        else:
            target_day = now.date() + timedelta(days=1) if now.hour >= 22 else now.date()
        date_iso = target_day.strftime("%Y-%m-%d")
        try:
            posts = client.list_scheduled_posts(date_iso, date_iso)
            occupied: list[datetime] = []
            for post in posts:
                ts = (post.get("scheduledFor") or "").replace("Z", "+00:00")
                if not ts:
                    continue
                try:
                    occupied.append(datetime.fromisoformat(ts).replace(tzinfo=None))
                except ValueError:
                    continue
        except ZernioError as e:
            logger.warning("list_scheduled_posts failed, falling back to empty occupancy: %s", e)
            occupied = []

        # Verbose scheduling trace — lets the operator see exactly which
        # slots were considered occupied and which slot was picked.
        weekday_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][target_day.weekday()]
        windows = sched._windows_for(target_day.weekday())
        windows_str = ", ".join(f"{s:02d}-{e:02d}" for s, e in windows)
        occupied_str = ", ".join(o.strftime("%H:%M") for o in sorted(occupied)) or "none"
        logger.info(
            "SmartScheduler: day=%s (%s), prime-time windows=[%s], already occupied: [%s], min_gap=%ds",
            date_iso, weekday_name, windows_str, occupied_str, sched.min_gap_seconds,
        )
        slot = sched.find_slot(target_day, occupied, now=now)
        # Describe why this slot was chosen
        in_window = next(
            (w for w in windows if w[0] <= slot.hour < w[1]),
            None,
        )
        reason = (
            f"free prime-time window {in_window[0]:02d}-{in_window[1]:02d}"
            if in_window else "fallback (all prime-time windows busy)"
        )
        logger.info(
            "SmartScheduler: → picked %s (%s), reason: %s",
            slot.strftime("%Y-%m-%d %H:%M"), weekday_name, reason,
        )
        final_scheduled_for = slot.isoformat()
    elif schedule_mode == "manual":
        final_scheduled_for = scheduled_for

    # 2. Presign + upload
    filename = os.path.basename(clip_path)
    try:
        size_bytes = os.path.getsize(clip_path)
    except OSError:
        size_bytes = None
    presign = client.presign_upload(filename, content_type="video/mp4", size_bytes=size_bytes)
    upload_url = presign["uploadUrl"]
    public_url = presign["publicUrl"]
    client.upload_to_presigned(upload_url, clip_path, content_type="video/mp4")

    # 3. Create post
    media_items = [{"type": "video", "url": public_url}]
    response = client.create_post(
        content=effective_content,
        title=title,
        media_items=media_items,
        platforms=platform_targets,
        scheduled_for=final_scheduled_for,
        timezone=timezone,
        publish_now=publish_now,
        tiktok_settings=tiktok_settings,
    )

    # 4. Extract post id (response shape varies)
    post_obj = response.get("post") if isinstance(response, dict) else None
    if isinstance(post_obj, dict):
        post_id = post_obj.get("_id") or post_obj.get("id")
        status = post_obj.get("status", "scheduled")
        platforms_resp = post_obj.get("platforms", [])
    else:
        post_id = response.get("_id") if isinstance(response, dict) else None
        status = response.get("status", "scheduled") if isinstance(response, dict) else "unknown"
        platforms_resp = []

    return {
        "post_id": post_id,
        "status": status,
        "scheduled_for": final_scheduled_for,
        "schedule_mode": schedule_mode,
        "platforms": platforms_resp,
    }
