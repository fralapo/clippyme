"""YouTube uploads-feed poller (long-form only) + channel-id resolution."""
from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("clippyme")

FEED_URL = "https://www.youtube.com/feeds/videos.xml?playlist_id={playlist}"
USER_AGENT = "Mozilla/5.0 (compatible; ClippyMe-LiveMonitor/1.0)"
MAX_FEED_BYTES = 2 * 1024 * 1024

_UC_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_PLAYLIST_RE = re.compile(r"^UULF[A-Za-z0-9_-]{22}$")
_VIDEO_ID_XML_RE = re.compile(r"<yt:videoId>([^<]+)</yt:videoId>")
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_FEED_OPENER = urllib.request.build_opener(_NoRedirectHandler)


def uploads_playlist_id(channel_id: str) -> str:
    """UC… channel id -> its long-form uploads playlist id (UULF…)."""
    cid = (channel_id or "").strip()
    if not _UC_RE.fullmatch(cid):
        raise ValueError(f"expected a canonical UC channel id, got {channel_id!r}")
    return "UULF" + cid[2:]


def feed_url(playlist_id: str) -> str:
    playlist = (playlist_id or "").strip()
    if not _PLAYLIST_RE.fullmatch(playlist):
        raise ValueError(f"invalid uploads playlist id: {playlist_id!r}")
    return FEED_URL.format(playlist=playlist)


def parse_feed(xml) -> list:
    """Return ``[{id, url}]`` in feed order from a small Atom document."""
    text = xml.decode("utf-8", "replace") if isinstance(xml, (bytes, bytearray)) else (xml or "")
    out = []
    for match in _VIDEO_ID_XML_RE.finditer(text):
        video_id = match.group(1).strip()
        if _VIDEO_ID_RE.fullmatch(video_id):
            out.append({"id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"})
    return out


def _validate_feed_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "www.youtube.com":
        raise ValueError("feed URL must use https://www.youtube.com")
    if parsed.path != "/feeds/videos.xml":
        raise ValueError("unexpected YouTube feed path")
    playlist_values = parse_qs(parsed.query, strict_parsing=True).get("playlist_id", [])
    if len(playlist_values) != 1 or not _PLAYLIST_RE.fullmatch(playlist_values[0]):
        raise ValueError("invalid playlist_id in feed URL")
    return parsed.geturl()


def fetch_feed(url: str, timeout: float = 15.0) -> bytes:
    """Fetch a validated YouTube feed without redirects or unbounded reads."""
    safe_url = _validate_feed_url(url)
    req = urllib.request.Request(safe_url, headers={"User-Agent": USER_AGENT})
    try:
        with _FEED_OPENER.open(req, timeout=timeout) as response:  # nosec B310: exact HTTPS host/path validated above
            data = response.read(MAX_FEED_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"YouTube feed HTTP {exc.code}") from exc
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("YouTube feed exceeded size cap")
    return data


def resolve_channel_id(channel_input: str) -> str:
    """Resolve an @handle / channel URL / UC id to a canonical UC id."""
    channel = (channel_input or "").strip()
    if _UC_RE.fullmatch(channel):
        return channel
    lowered = channel.lower()
    if lowered.startswith("http://"):
        raise ValueError("YouTube channel URLs must use HTTPS")
    if lowered.startswith(("youtube.com/", "www.youtube.com/")):
        url = f"https://{channel}"
    elif lowered.startswith("https://"):
        url = channel
    else:
        url = f"https://www.youtube.com/{channel.lstrip('/')}"
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid YouTube channel URL port") from exc
    path = parsed.path.rstrip("/")
    allowed_path = (
        path.startswith("/@")
        or path.startswith("/channel/UC")
        or path.startswith("/c/")
        or path.startswith("/user/")
    )
    if (
        parsed.scheme != "https"
        or host not in {"youtube.com", "www.youtube.com"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not allowed_path
    ):
        raise ValueError("YouTube channel must use an official channel/handle URL")
    from yt_dlp import YoutubeDL

    with YoutubeDL({"quiet": True, "skip_download": True, "extract_flat": True}) as ydl:
        info = ydl.extract_info(url, download=False, process=False) or {}
    channel_id = info.get("channel_id") or info.get("uploader_id") or info.get("id")
    if not channel_id or not _UC_RE.fullmatch(str(channel_id)):
        raise ValueError(f"could not resolve YouTube channel id from {channel_input!r}")
    return str(channel_id)
