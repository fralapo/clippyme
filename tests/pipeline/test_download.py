"""Tests for clippyme.pipeline.download helpers (host-runnable; no network)."""
import os

import pytest

from clippyme import netutil
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
    monkeypatch.setattr(netutil.socket, "getaddrinfo", _fake_getaddrinfo("192.168.1.10", "127.0.0.1"))
    with pytest.raises(ValueError):
        dl._reject_rebound_internal("http://rebind.evil.test/x")


def test_reject_rebound_public_resolution_passes(monkeypatch):
    monkeypatch.setattr(netutil.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    dl._reject_rebound_internal("http://example.com/x")  # no raise


def test_reject_rebound_mixed_public_and_internal_raises(monkeypatch):
    # ANY internal address → reject. A split-horizon / round-robin host that
    # returns one public + one loopback/private address must NOT pass: yt-dlp
    # could otherwise connect to the internal one (SSRF via DNS rebinding).
    monkeypatch.setattr(netutil.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34", "10.0.0.1"))
    with pytest.raises(ValueError):
        dl._reject_rebound_internal("http://example.com/x")


def test_reject_rebound_no_host_returns_none():
    assert dl._reject_rebound_internal("not a url") is None


def test_reject_rebound_resolution_failure_is_swallowed(monkeypatch):
    def _boom(*a, **k):
        raise OSError("dns down")
    monkeypatch.setattr(netutil.socket, "getaddrinfo", _boom)
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


# ── player-client fallback chain ──────────────────────────────────────────

def test_player_client_chain_default(monkeypatch):
    monkeypatch.delenv("YTDLP_PLAYER_CLIENTS", raising=False)
    assert dl._player_client_chain() == ["default", "tv+tv_embedded", "web_safari"]


def test_player_client_chain_env_override(monkeypatch):
    monkeypatch.setenv("YTDLP_PLAYER_CLIENTS", " web_safari , tv , default ")
    assert dl._player_client_chain() == ["web_safari", "tv", "default"]


def test_player_client_chain_blank_env_falls_back(monkeypatch):
    monkeypatch.setenv("YTDLP_PLAYER_CLIENTS", "   ")
    assert dl._player_client_chain() == ["default", "tv+tv_embedded", "web_safari"]


def test_extractor_args_default_is_none():
    assert dl._extractor_args_for("default") is None
    assert dl._extractor_args_for("") is None


def test_extractor_args_single_client():
    assert dl._extractor_args_for("web_safari") == {
        "youtube": {"player_client": ["web_safari"]}
    }


def test_extractor_args_joined_clients():
    assert dl._extractor_args_for("tv+tv_embedded") == {
        "youtube": {"player_client": ["tv", "tv_embedded"]}
    }


# ── classify_download_error (retry vs fatal) ──────────────────────────────

@pytest.mark.parametrize("msg", [
    "ERROR: unable to download video data: HTTP Error 403: Forbidden",
    "Requested format is not available",
    "requested format not available. Use --list-formats",
    "No video formats found!; please report this issue",
    "empty formats returned by extractor",
    "403 Forbidden",
])
def test_classify_retry(msg):
    assert dl.classify_download_error(msg) == "retry"


@pytest.mark.parametrize("msg", [
    "ERROR: Sign in to confirm you're not a bot. Use --cookies",
    "ERROR: Private video. Sign in if you've been granted access",
    "This video is private",
    "Video unavailable. This video has been removed by the user",
    "Video unavailable",
    "The uploader has not made this video available in your country",
    "The uploader has blocked it in your country on copyright grounds",
    "This video is no longer available because the account was terminated",
    "some totally unrecognised failure mode",
    "",
])
def test_classify_fatal(msg):
    assert dl.classify_download_error(msg) == "fatal"


def test_classify_bot_wall_beats_any_incidental_403():
    # Page-level bot wall is fatal even if a 403 substring is nearby.
    msg = "Sign in to confirm you're not a bot (HTTP Error 403)"
    assert dl.classify_download_error(msg) == "fatal"
