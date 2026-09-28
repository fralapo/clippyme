"""Tests for smartcut's LRU probe caches (Phase 2 perf work).

These are pure/host-runnable: smart_cut's heavy ffmpeg paths are not exercised
— we monkeypatch the `_run` subprocess shim and assert the caching contract.
"""
import os

import pytest

from clippyme.editing import smartcut as sc


# --- LRU helper ------------------------------------------------------------

def test_cache_put_evicts_least_recently_used():
    cache = {}
    sc._cache_put(cache, "a", 1, limit=2)
    sc._cache_put(cache, "b", 2, limit=2)
    # Touch "a" so "b" becomes the least-recently-used.
    assert sc._cache_get(cache, "a") == 1
    sc._cache_put(cache, "c", 3, limit=2)
    assert "b" not in cache          # evicted (LRU)
    assert "a" in cache and "c" in cache


def test_cache_get_returns_none_for_missing():
    assert sc._cache_get({}, "nope") is None


# --- _probe_duration caching ----------------------------------------------

@pytest.fixture
def fake_run(monkeypatch):
    calls = {"n": 0}

    def _fake(cmd, timeout=None):
        calls["n"] += 1
        return (0, "12.5", "")

    monkeypatch.setattr(sc, "_run", _fake)
    return calls


def test_probe_duration_caches_per_file(fake_run, tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"data")
    assert sc._probe_duration(str(f)) == 12.5
    assert sc._probe_duration(str(f)) == 12.5
    assert fake_run["n"] == 1  # second call served from cache


def test_probe_duration_reprobes_when_file_changes(fake_run, tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"data")
    sc._DURATION_CACHE.clear()
    sc._probe_duration(str(f))
    # A new size alone changes the (path, size, mtime) key.
    f.write_bytes(b"data-much-longer-now")
    sc._probe_duration(str(f))
    assert fake_run["n"] == 2


def test_probe_duration_reprobes_a_same_size_rewrite(fake_run, tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"aaaa")
    os.utime(f, (1_700_000_000, 1_700_000_000))
    sc._DURATION_CACHE.clear()
    sc._probe_duration(str(f))
    f.write_bytes(b"bbbb")  # same size, rewritten
    os.utime(f, (1_700_000_100, 1_700_000_100))
    sc._probe_duration(str(f))
    assert fake_run["n"] == 2
