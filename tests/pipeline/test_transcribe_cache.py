"""Tests for clippyme.pipeline.transcribe_cache (stdlib-only, host-runnable)."""
import json
import os
import time

import pytest

from clippyme.pipeline import transcribe_cache as tc


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path / "cache"


def test_cache_path_is_url_hash_stable(tmp_cache):
    p1 = tc.get_cache_path("https://youtu.be/abc")
    p2 = tc.get_cache_path("https://youtu.be/abc")
    p3 = tc.get_cache_path("https://youtu.be/xyz")
    assert p1 == p2
    assert p1 != p3
    assert p1.endswith("_transcript.json")


def test_load_missing_returns_none(tmp_cache):
    assert tc.load_cached_transcript("https://youtu.be/none") is None


def test_round_trip(tmp_cache):
    payload = {"segments": [{"text": "hi", "start": 0, "end": 1}], "language": "en"}
    tc.save_transcript_cache("https://youtu.be/abc", payload)
    loaded = tc.load_cached_transcript("https://youtu.be/abc")
    assert loaded == payload


def test_expired_entry_is_pruned(tmp_cache):
    url = "https://youtu.be/old"
    tc.save_transcript_cache(url, {"x": 1})
    path = tc.get_cache_path(url)
    # Backdate beyond the TTL.
    old = time.time() - (tc.CACHE_TTL_DAYS + 1) * 86400
    os.utime(path, (old, old))
    assert tc.load_cached_transcript(url) is None
    assert not os.path.exists(path)  # pruned on read


def test_corrupt_cache_returns_none(tmp_cache):
    url = "https://youtu.be/bad"
    os.makedirs(str(tmp_cache), exist_ok=True)
    with open(tc.get_cache_path(url), "w", encoding="utf-8") as f:
        f.write("{not json")
    assert tc.load_cached_transcript(url) is None


def test_save_is_atomic_no_tmp_left(tmp_cache):
    url = "https://youtu.be/atomic"
    tc.save_transcript_cache(url, {"ok": True})
    assert not os.path.exists(tc.get_cache_path(url) + ".tmp")
    assert json.load(open(tc.get_cache_path(url), encoding="utf-8")) == {"ok": True}
