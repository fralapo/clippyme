"""Tests for clippyme.api.security — trusted-origin / private-network gate.

These guard the config endpoints (API keys, Zernio creds, cookies). The
functions are pure and dependency-free, so they run on the host without the
cv2/mediapipe/ffmpeg runtime stack.
"""
import pytest
from fastapi import HTTPException

from clippyme.api import security
from clippyme.api.security import (
    DEFAULT_ALLOWED_ORIGINS,
    is_trusted_client_host,
    is_trusted_origin,
    parse_allowed_origins,
    require_trusted_config_request,
)


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    """Minimal stand-in for starlette Request.

    require_trusted_config_request only touches ``headers.get("origin")``
    and ``client.host``, so a dict + namespace is enough.
    """

    def __init__(self, origin=None, client_host=None):
        self.headers = {"origin": origin} if origin is not None else {}
        self.client = _FakeClient(client_host) if client_host is not None else None


# --- parse_allowed_origins -------------------------------------------------

def test_parse_allowed_origins_none_returns_defaults():
    assert parse_allowed_origins(None) == list(DEFAULT_ALLOWED_ORIGINS)


def test_parse_allowed_origins_splits_and_strips_trailing_slash():
    raw = "https://a.example.com/, http://b.example.com , https://c.example.com/"
    assert parse_allowed_origins(raw) == [
        "https://a.example.com",
        "http://b.example.com",
        "https://c.example.com",
    ]


def test_parse_allowed_origins_empty_string_falls_back_to_defaults():
    assert parse_allowed_origins("") == list(DEFAULT_ALLOWED_ORIGINS)


def test_parse_allowed_origins_only_separators_falls_back_to_defaults():
    assert parse_allowed_origins("  ,  , ") == list(DEFAULT_ALLOWED_ORIGINS)


# --- is_trusted_origin -----------------------------------------------------

def test_is_trusted_origin_accepts_known_origin(monkeypatch):
    monkeypatch.setattr(security, "ALLOWED_ORIGINS", ["http://localhost:5175"])
    assert is_trusted_origin("http://localhost:5175") is True


def test_is_trusted_origin_ignores_trailing_slash(monkeypatch):
    monkeypatch.setattr(security, "ALLOWED_ORIGINS", ["http://localhost:5175"])
    assert is_trusted_origin("http://localhost:5175/") is True


def test_is_trusted_origin_rejects_unknown_origin(monkeypatch):
    monkeypatch.setattr(security, "ALLOWED_ORIGINS", ["http://localhost:5175"])
    assert is_trusted_origin("http://evil.example.com") is False


def test_is_trusted_origin_rejects_none_and_empty(monkeypatch):
    monkeypatch.setattr(security, "ALLOWED_ORIGINS", ["http://localhost:5175"])
    assert is_trusted_origin(None) is False
    assert is_trusted_origin("") is False


# --- is_trusted_client_host ------------------------------------------------

@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "LOCALHOST"])
def test_is_trusted_client_host_accepts_loopback(host):
    assert is_trusted_client_host(host) is True


@pytest.mark.parametrize("host", ["192.168.1.10", "10.0.0.5", "172.16.0.1"])
def test_is_trusted_client_host_accepts_private(host):
    assert is_trusted_client_host(host) is True


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1", "9.9.9.9"])
def test_is_trusted_client_host_rejects_public(host):
    assert is_trusted_client_host(host) is False


@pytest.mark.parametrize("host", [None, "", "not-an-ip", "999.999.999.999"])
def test_is_trusted_client_host_rejects_invalid(host):
    assert is_trusted_client_host(host) is False


# --- require_trusted_config_request ----------------------------------------

def test_require_trusted_request_allows_trusted_origin(monkeypatch):
    monkeypatch.setattr(security, "ALLOWED_ORIGINS", ["http://localhost:5175"])
    req = _FakeRequest(origin="http://localhost:5175", client_host="8.8.8.8")
    # Public client host is irrelevant once a trusted Origin is present.
    assert require_trusted_config_request(req) is None


def test_require_trusted_request_rejects_untrusted_origin(monkeypatch):
    monkeypatch.setattr(security, "ALLOWED_ORIGINS", ["http://localhost:5175"])
    req = _FakeRequest(origin="http://evil.example.com", client_host="127.0.0.1")
    # An untrusted Origin is rejected even from a loopback client — a
    # cross-site browser request must never reach the config endpoints.
    with pytest.raises(HTTPException) as exc:
        require_trusted_config_request(req)
    assert exc.value.status_code == 403


def test_require_trusted_request_allows_private_client_without_origin():
    req = _FakeRequest(origin=None, client_host="127.0.0.1")
    assert require_trusted_config_request(req) is None


def test_require_trusted_request_rejects_public_client_without_origin():
    req = _FakeRequest(origin=None, client_host="8.8.8.8")
    with pytest.raises(HTTPException) as exc:
        require_trusted_config_request(req)
    assert exc.value.status_code == 403


def test_require_trusted_request_rejects_when_no_client():
    req = _FakeRequest(origin=None, client_host=None)
    with pytest.raises(HTTPException) as exc:
        require_trusted_config_request(req)
    assert exc.value.status_code == 403
