"""Twitch Helix client — live detection + VOD listing.

Uses the STABLE Helix API path (scraping GQL hashes rotates and breaks). An app
access token is minted via ``client_credentials`` (client_id + client_secret),
lasts ~60 days, and is transparently refreshed on a 401. ``requests`` is
imported lazily so the host test suite doesn't need creds or network.

``stream_is_live`` / ``parse_vods`` are pure response readers — host-unit-tested
without any HTTP.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("clippyme")

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX_URL = "https://api.twitch.tv/helix"


def stream_is_live(streams_json) -> bool:
    """True when GET /helix/streams returned a non-empty ``data`` array."""
    return bool((streams_json or {}).get("data"))


def stream_started_at(streams_json) -> Optional[datetime]:
    """Parse the live stream's ``started_at`` (ISO 8601 Z) from GET
    /helix/streams, UTC-aware. None when offline/missing/unparseable."""
    data = (streams_json or {}).get("data") or []
    if not data:
        return None
    raw = data[0].get("started_at")
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_vods(videos_json) -> list:
    """Extract ``[{id, url, created_at}]`` from GET /helix/videos."""
    out = []
    for v in (videos_json or {}).get("data") or []:
        vid = v.get("id")
        if not vid:
            continue
        out.append({
            "id": str(vid),
            "url": v.get("url") or f"https://www.twitch.tv/videos/{vid}",
            "created_at": v.get("created_at") or v.get("published_at") or "",
        })
    return out


def find_live_vod(videos_json, stream_id) -> Optional[str]:
    """Return the url of the in-progress archive VOD whose ``stream_id`` matches
    the current live stream's id (from GET /helix/streams), else None. Defensive
    dict access like :func:`parse_vods`."""
    if not stream_id:
        return None
    for v in (videos_json or {}).get("data") or []:
        if str(v.get("stream_id") or "") == str(stream_id):
            vid = v.get("id")
            return v.get("url") or (f"https://www.twitch.tv/videos/{vid}" if vid else None)
    return None


class TwitchClient:
    """Minimal Helix client — app token + streams/users/videos."""

    def __init__(self, client_id: str, client_secret: str, timeout: float = 15.0):
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret are required")
        self._cid = client_id
        self._secret = client_secret
        self._timeout = timeout
        self._token: Optional[str] = None
        self._token_exp: float = 0.0

    def _get_token(self, force: bool = False) -> str:
        import requests
        if self._token and not force and time.time() < self._token_exp - 60:
            return self._token
        resp = requests.post(TOKEN_URL, params={
            "client_id": self._cid,
            "client_secret": self._secret,
            "grant_type": "client_credentials",
        }, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 5184000))
        return self._token

    def _get(self, path: str, params: dict):
        import requests
        for attempt in range(2):  # one retry to refresh an expired/revoked token
            token = self._get_token(force=attempt > 0)
            resp = requests.get(HELIX_URL + path, params=params, headers={
                "Client-Id": self._cid,
                "Authorization": f"Bearer {token}",
            }, timeout=self._timeout)
            if resp.status_code == 401 and attempt == 0:
                continue
            resp.raise_for_status()
            return resp.json()
        return None

    def get_stream(self, login: str):
        """GET /helix/streams?user_login= — empty data means offline."""
        return self._get("/streams", {"user_login": login})

    def get_user_id(self, login: str) -> Optional[str]:
        """GET /helix/users?login= — the numeric user id (cached by caller)."""
        arr = (self._get("/users", {"login": login}) or {}).get("data") or []
        return str(arr[0]["id"]) if arr and arr[0].get("id") else None

    def get_videos(self, user_id: str):
        """GET /helix/videos?user_id=&type=archive — past-broadcast VODs."""
        return self._get("/videos", {"user_id": user_id, "type": "archive"})
