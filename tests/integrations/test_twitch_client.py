"""Tests for clippyme.integrations.twitch_client.

Pure parsers (stream_is_live / parse_vods) plus TwitchClient with requests
monkeypatched — no network, no creds.
"""
from clippyme.integrations.twitch_client import (
    TwitchClient,
    parse_vods,
    stream_is_live,
)


# --- pure parsers ----------------------------------------------------------

def test_stream_is_live():
    assert stream_is_live({"data": [{"id": "1", "started_at": "x"}]}) is True
    assert stream_is_live({"data": []}) is False
    assert stream_is_live({}) is False
    assert stream_is_live(None) is False


def test_parse_vods_extracts_fields():
    vods = parse_vods({"data": [
        {"id": "111", "url": "https://www.twitch.tv/videos/111", "created_at": "2026-01-01"},
    ]})
    assert vods == [{"id": "111", "url": "https://www.twitch.tv/videos/111",
                     "created_at": "2026-01-01"}]


def test_parse_vods_builds_url_when_missing():
    vods = parse_vods({"data": [{"id": "222", "published_at": "2026-02-02"}]})
    assert vods[0]["url"] == "https://www.twitch.tv/videos/222"
    assert vods[0]["created_at"] == "2026-02-02"


def test_parse_vods_empty():
    assert parse_vods(None) == []
    assert parse_vods({"data": []}) == []


# --- client with fake requests ---------------------------------------------

class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_client_mints_token_and_reads_stream(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "post",
                        lambda url, **kw: _Resp({"access_token": "tok", "expires_in": 1000}))
    monkeypatch.setattr(requests, "get",
                        lambda url, **kw: _Resp({"data": [{"id": "s1"}]}))
    client = TwitchClient("cid", "secret")
    assert stream_is_live(client.get_stream("someone")) is True


def test_client_get_user_id(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "post",
                        lambda url, **kw: _Resp({"access_token": "tok", "expires_in": 1000}))
    monkeypatch.setattr(requests, "get",
                        lambda url, **kw: _Resp({"data": [{"id": 42, "login": "someone"}]}))
    client = TwitchClient("cid", "secret")
    assert client.get_user_id("someone") == "42"
