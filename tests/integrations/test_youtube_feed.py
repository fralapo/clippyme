"""Tests for clippyme.integrations.youtube_feed pure helpers (no network)."""
import pytest

from clippyme.integrations import youtube_feed as yf
from clippyme.integrations.youtube_feed import (
    feed_url,
    parse_feed,
    uploads_playlist_id,
)

SAMPLE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>abc123XYZ_1</yt:videoId>
    <title>First long-form upload</title>
  </entry>
  <entry>
    <yt:videoId>def456UVW_2</yt:videoId>
    <title>Second</title>
  </entry>
</feed>"""


def test_uploads_playlist_id():
    assert uploads_playlist_id("UCabcdefghijklmnopqrstuv") == "UULFabcdefghijklmnopqrstuv"


def test_uploads_playlist_id_rejects_non_uc():
    with pytest.raises(ValueError):
        uploads_playlist_id("PLxxxx")


def test_feed_url():
    assert "playlist_id=UULFabcdefghijklmnopqrstuv" in feed_url("UULFabcdefghijklmnopqrstuv")


def test_parse_feed_order_and_urls():
    items = parse_feed(SAMPLE_FEED)
    assert [i["id"] for i in items] == ["abc123XYZ_1", "def456UVW_2"]
    assert items[0]["url"] == "https://www.youtube.com/watch?v=abc123XYZ_1"


def test_parse_feed_empty():
    assert parse_feed(b"<feed></feed>") == []
    assert parse_feed("") == []


def test_feed_url_rejects_malformed_playlist_id():
    with pytest.raises(ValueError):
        feed_url("UULF../etc/passwd")


def test_fetch_feed_rejects_non_youtube_url_before_network(monkeypatch):
    monkeypatch.setattr(
        yf._FEED_OPENER,
        "open",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network must not run")),
    )
    with pytest.raises(ValueError):
        yf.fetch_feed("file:///etc/passwd")
    with pytest.raises(ValueError):
        yf.fetch_feed("https://evil.example/feeds/videos.xml?playlist_id=UULFabcdefghijklmnopqrstuv")


def test_fetch_feed_enforces_size_cap(monkeypatch):
    import io

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(yf, "MAX_FEED_BYTES", 4)
    monkeypatch.setattr(yf._FEED_OPENER, "open", lambda *a, **k: Response(b"12345"))
    with pytest.raises(ValueError, match="size cap"):
        yf.fetch_feed(feed_url("UULFabcdefghijklmnopqrstuv"))


def test_resolve_channel_id_normalizes_bare_official_host(monkeypatch):
    captured = {}

    class FakeYDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, **kwargs):
            captured["url"] = url
            return {"channel_id": "UCabcdefghijklmnopqrstuv"}

    import sys
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYDL))
    assert yf.resolve_channel_id("youtube.com/@creator") == "UCabcdefghijklmnopqrstuv"
    assert captured["url"] == "https://youtube.com/@creator"


def test_resolve_channel_id_rejects_http_and_non_channel_urls():
    with pytest.raises(ValueError):
        yf.resolve_channel_id("http://www.youtube.com/@creator")
    with pytest.raises(ValueError):
        yf.resolve_channel_id("https://www.youtube.com/watch?v=abc123XYZ_1")
