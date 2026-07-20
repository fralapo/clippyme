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
from typing import Optional

logger = logging.getLogger("clippyme")

API_URL = "https://kick.com/api/v2/channels/{slug}"
# Rotated on repeated 403 (Cloudflare challenge). Ordered most→least common.
DEFAULT_PROFILES = ("chrome124", "chrome131", "safari17_0")


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
        cf = self._cf_requests()
        url = API_URL.format(slug=slug)
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
                logger.warning("Kick get_channel for %s → HTTP %s", slug, status)
                return None
            try:
                return resp.json()
            except Exception:
                logger.warning("Kick get_channel: response was not valid JSON")
                return None
        logger.warning("Kick get_channel: all profiles returned 403 for %s", slug)
        return None
