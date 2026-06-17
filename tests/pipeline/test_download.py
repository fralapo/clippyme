"""Tests for clippyme.pipeline.download helpers (host-runnable; no network)."""
import os

from clippyme.pipeline import download as dl


def test_sanitize_filename_strips_invalid_chars():
    assert dl.sanitize_filename('a<b>c:d"e/f\\g|h?i*j') == "abcdefghij"


def test_sanitize_filename_replaces_spaces():
    assert dl.sanitize_filename("my cool video") == "my_cool_video"


def test_sanitize_filename_truncates_to_100():
    assert len(dl.sanitize_filename("x" * 250)) == 100


def test_resolve_cookies_explicit_wins(tmp_path):
    explicit = str(tmp_path / "given.txt")
    assert dl._resolve_cookies_path(explicit) == explicit


def test_resolve_cookies_repo_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YOUTUBE_COOKIES", raising=False)
    os.makedirs("data", exist_ok=True)
    open(os.path.join("data", "cookies.txt"), "w").close()
    resolved = dl._resolve_cookies_path(None)
    assert resolved.endswith(os.path.join("data", "cookies.txt"))
    assert os.path.isabs(resolved)


def test_resolve_cookies_from_env_materializes_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YOUTUBE_COOKIES", "# Netscape cookie\nfoo\tbar")
    resolved = dl._resolve_cookies_path(None)
    assert resolved.endswith(os.path.join("data", "cookies_env.txt"))
    with open(resolved) as f:
        assert "Netscape" in f.read()


def test_resolve_cookies_none_when_nothing_available(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YOUTUBE_COOKIES", raising=False)
    assert dl._resolve_cookies_path(None) is None
