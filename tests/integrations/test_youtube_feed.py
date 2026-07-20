"""Tests for clippyme.integrations.youtube_feed pure helpers (no network)."""
import pytest

from clippyme.integrations.youtube_feed import (
    feed_url,
    parse_feed,
    uploads_playlist_id,
)

SAMPLE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>abc123XYZ</yt:videoId>
    <title>First long-form upload</title>
  </entry>
  <entry>
    <yt:videoId>def456UVW</yt:videoId>
    <title>Second</title>
  </entry>
</feed>"""


def test_uploads_playlist_id():
    assert uploads_playlist_id("UCabcdefghij") == "UULFabcdefghij"


def test_uploads_playlist_id_rejects_non_uc():
    with pytest.raises(ValueError):
        uploads_playlist_id("PLxxxx")


def test_feed_url():
    assert "playlist_id=UULFabc" in feed_url("UULFabc")


def test_parse_feed_order_and_urls():
    items = parse_feed(SAMPLE_FEED)
    assert [i["id"] for i in items] == ["abc123XYZ", "def456UVW"]
    assert items[0]["url"] == "https://www.youtube.com/watch?v=abc123XYZ"


def test_parse_feed_empty():
    assert parse_feed(b"<feed></feed>") == []
    assert parse_feed("") == []
