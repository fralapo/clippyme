"""Kick.com channel client — live detection + HLS playback URL.

Kick's public API (``/api/v2/channels/{slug}``) is Cloudflare-gated, so a plain
``requests`` call gets a 403. We use ``curl_cffi`` with a rotating
browser-impersonation profile; on a sustained 403 we cycle the profile list
rather than treating it as fatal. ``curl_cffi`` is imported LAZILY so the host
test suite (and file-upload-only deployments) don't need the wheel.

``is_live`` / ``playback_url`` are pure dict readers — host-unit-tested without
any network or curl_cffi import.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("clippyme")

API_URL = "https://kick.com/api/v2/channels/{slug}"
VIDEOS_URL = "https://kick.com/api/v2/channels/{slug}/videos"
# Rotated on repeated 403 (Cloudflare challenge). Ordered most→least common.
DEFAULT_PROFILES = ("chrome124", "chrome131", "safari17_0")


def extract_vods(payload) -> list:
    """Best-effort VOD list from a Kick channel JSON *or* a /videos payload.

    Kick's VOD shape is UNVERIFIED and drifts across API versions, so we probe
    several known field names defensively. Returns ``[{id, url, created_at}]``
    (possibly empty). ``url`` is the yt-dlp-friendly ``kick.com/video/{uuid}``.
    """
    if not payload:
        return []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = (payload.get("previous_livestreams")
                 or payload.get("videos")
                 or payload.get("data") or [])
    else:
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        video = it.get("video") if isinstance(it.get("video"), dict) else it
        vid = video.get("uuid") or it.get("uuid") or video.get("id") or it.get("id")
        if not vid:
            continue
        created = (it.get("created_at") or it.get("start_time")
                   or video.get("created_at") or "")
        out.append({"id": str(vid), "url": f"https://kick.com/video/{vid}",
                    "created_at": created})
    return out


def is_live(channel: Optional[dict]) -> bool:
    """True when the channel JSON reports an active livestream.

    Kick sets ``livestream`` to a non-null object while live and null when
    offline; the nested ``is_live`` flag confirms it when present.
    """
    if not channel:
        return False
    livestream = channel.get("livestream")
    if not livestream:
        return False
    return bool(livestream.get("is_live", True))


def stream_started_at(channel: Optional[dict]) -> Optional[datetime]:
    """Parse the livestream's start time from Kick channel JSON, UTC-aware.

    Kick's ``livestream.created_at`` (also seen as ``start_time``) has been
    observed both as ISO 8601 ("2024-01-01T12:00:00.000000Z") and a plain
    space-separated UTC string ("2024-01-01 12:00:00") — tolerant of either.
    Returns None on a missing/unparseable value; callers fall back to the
    full prelive-skip window in that case.
    """
    if not channel:
        return None
    livestream = channel.get("livestream") or {}
    raw = livestream.get("created_at") or livestream.get("start_time")
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip().replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def playback_url(channel: Optional[dict]) -> Optional[str]:
    """Extract the HLS (.m3u8) playback URL, or None when unavailable."""
    if not channel:
        return None
    livestream = channel.get("livestream") or {}
    url = livestream.get("playback_url") or channel.get("playback_url")
    return url or None


class KickClient:
    """Fetches Kick channel JSON with Cloudflare-bypassing impersonation."""

    def __init__(self, timeout: float = 15.0, profiles=None):
        self._timeout = timeout
        self._profiles = list(profiles or DEFAULT_PROFILES)
        self._pi = 0  # rotating index into _profiles

    def _cf_requests(self):
        # Lazy import so host tests / upload-only setups don't require the wheel.
        from curl_cffi import requests as cf_requests
        return cf_requests

    def get_channel(self, slug: str) -> Optional[dict]:
        """GET the channel JSON. Returns the parsed dict, or None.

        A 404 (unknown slug) and any non-403 4xx/5xx return None. A 403 rotates
        the impersonation profile and retries; only after every profile has
        returned 403 do we give up (None) — the caller treats that as
        "try again next poll", not a hard failure.
        """
        return self._get_json(API_URL.format(slug=slug))

    def get_channel_videos(self, slug: str):
        """GET the channel's VOD list (used only when the channel JSON has none)."""
        return self._get_json(VIDEOS_URL.format(slug=slug))

    def _get_json(self, url: str):
        cf = self._cf_requests()
        for _ in range(len(self._profiles)):
            profile = self._profiles[self._pi % len(self._profiles)]
            try:
                resp = cf.get(url, impersonate=profile, timeout=self._timeout)
            except Exception as exc:  # network / curl error — rotate + retry
                logger.warning("Kick get_channel error (profile=%s): %s", profile, exc)
                self._pi += 1
                continue
            status = getattr(resp, "status_code", 0)
            if status == 403:
                logger.info("Kick 403 with profile %s — rotating impersonation", profile)
                self._pi += 1
                continue
            if status == 404:
                return None
            if status >= 400:
                logger.warning("Kick GET %s → HTTP %s", url, status)
                return None
            try:
                return resp.json()
            except Exception:
                logger.warning("Kick GET: response was not valid JSON")
                return None
        logger.warning("Kick GET: all profiles returned 403 for %s", url)
        return None
