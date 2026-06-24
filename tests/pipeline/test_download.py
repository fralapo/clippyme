"""Tests for clippyme.pipeline.download helpers (host-runnable; no network)."""
import os

import pytest

from clippyme.pipeline import download as dl


def _fake_getaddrinfo(*ips):
    """Build a getaddrinfo stub returning the given IP strings."""
    def _stub(host, port, *a, **k):
        return [(None, None, None, "", (ip, 0)) for ip in ips]
    return _stub


def test_reject_rebound_literal_internal_ip_raises():
    with pytest.raises(ValueError):
        dl._reject_rebound_internal("http://127.0.0.1/video")


def test_reject_rebound_literal_public_ip_passes():
    # 8.8.8.8 is public — must not raise.
    dl._reject_rebound_internal("http://8.8.8.8/video")


def test_reject_rebound_all_internal_resolution_raises(monkeypatch):
    monkeypatch.setattr(dl.socket, "getaddrinfo", _fake_getaddrinfo("192.168.1.10", "127.0.0.1"))
    with pytest.raises(ValueError):
        dl._reject_rebound_internal("http://rebind.evil.test/x")


def test_reject_rebound_public_resolution_passes(monkeypatch):
    monkeypatch.setattr(dl.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    dl._reject_rebound_internal("http://example.com/x")  # no raise


def test_reject_rebound_mixed_public_and_internal_raises(monkeypatch):
    # ANY internal address → reject. A split-horizon / round-robin host that
    # returns one public + one loopback/private address must NOT pass: yt-dlp
    # could otherwise connect to the internal one (SSRF via DNS rebinding).
    monkeypatch.setattr(dl.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34", "10.0.0.1"))
    with pytest.raises(ValueError):
        dl._reject_rebound_internal("http://example.com/x")


def test_reject_rebound_no_host_returns_none():
    assert dl._reject_rebound_internal("not a url") is None


def test_reject_rebound_resolution_failure_is_swallowed(monkeypatch):
    def _boom(*a, **k):
        raise OSError("dns down")
    monkeypatch.setattr(dl.socket, "getaddrinfo", _boom)
    # Resolution hiccup must not block a legit download — yt-dlp handles it.
    assert dl._reject_rebound_internal("http://example.com/x") is None


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
