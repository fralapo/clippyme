"""YouTube uploads-feed poller (long-form only) + channel-id resolution.

The ``UULF`` uploads playlist RSS feed returns ONLY long-form videos (Shorts are
structurally excluded), so a plain stdlib ``urllib`` GET is enough — no Cloudflare
gate, no curl_cffi. ``parse_feed`` / ``uploads_playlist_id`` are pure and
host-unit-tested; ``resolve_channel_id`` lazily imports yt_dlp (Docker-only).
"""
from __future__ import annotations

import logging
import re
from urllib.request import Request, urlopen

logger = logging.getLogger("clippyme")

FEED_URL = "https://www.youtube.com/feeds/videos.xml?playlist_id={playlist}"
# A real browser UA — YouTube throttles the default urllib agent.
USER_AGENT = "Mozilla/5.0 (compatible; ClippyMe-LiveMonitor/1.0)"

_UC_RE = re.compile(r"^UC[A-Za-z0-9_-]{20,40}$")
_VIDEO_ID_RE = re.compile(r"<yt:videoId>([^<]+)</yt:videoId>")


def uploads_playlist_id(channel_id: str) -> str:
    """UC… channel id → its long-form uploads playlist id (UULF…)."""
    cid = (channel_id or "").strip()
    if not cid.startswith("UC"):
        raise ValueError(f"expected a UC channel id, got {channel_id!r}")
    return "UULF" + cid[2:]


def feed_url(playlist_id: str) -> str:
    return FEED_URL.format(playlist=playlist_id)


def parse_feed(xml) -> list:
    """Return ``[{id, url}]`` in feed order from a uploads-feed XML document.

    Regex-parsed on purpose: the feed is a small, fixed-schema Atom document and
    ``<yt:videoId>`` lives in a namespace that makes ElementTree needlessly
    verbose. ponytail: regex parse, swap for ElementTree if the feed schema grows.
    """
    text = xml.decode("utf-8", "replace") if isinstance(xml, (bytes, bytearray)) else (xml or "")
    out = []
    for m in _VIDEO_ID_RE.finditer(text):
        vid = m.group(1).strip()
        if vid:
            out.append({"id": vid, "url": f"https://www.youtube.com/watch?v={vid}"})
    return out


def fetch_feed(url: str, timeout: float = 15.0) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed youtube.com host)
        return resp.read()


def resolve_channel_id(channel_input: str) -> str:
    """Resolve an @handle / channel URL / UC id → canonical UC channel id.

    Runs yt_dlp's flat extractor once (at monitor start); the result is cached in
    the strategy so the feed URL is built without further resolution.
    """
    ci = (channel_input or "").strip()
    if _UC_RE.match(ci):
        return ci
    url = ci if ci.startswith("http") else f"https://www.youtube.com/{ci.lstrip('/')}"
    from yt_dlp import YoutubeDL
    with YoutubeDL({"quiet": True, "skip_download": True, "extract_flat": True}) as ydl:
        info = ydl.extract_info(url, download=False, process=False) or {}
    cid = info.get("channel_id") or info.get("uploader_id") or info.get("id")
    if not cid or not str(cid).startswith("UC"):
        raise ValueError(f"could not resolve YouTube channel id from {channel_input!r}")
    return str(cid)
