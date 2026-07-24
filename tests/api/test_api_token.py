"""Optional CLIPPYME_API_TOKEN gate (security.enforce_api_token + middleware).

Unset token (the default loopback self-host) must be a byte-identical no-op;
set token must 401 every /api request that doesn't carry it, via either the
X-API-Token header or Authorization: Bearer. Pure host tests — no cv2/ffmpeg.
"""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from clippyme.api import app as app_module
from clippyme.api.security import configured_api_token, enforce_api_token

ORIGIN = {"Origin": "http://localhost:5175"}


class _FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


# --- unit: enforce_api_token -------------------------------------------------

def test_noop_when_unset(monkeypatch):
    monkeypatch.delenv("CLIPPYME_API_TOKEN", raising=False)
    assert configured_api_token() is None
    enforce_api_token(_FakeRequest())  # must not raise


def test_blank_env_counts_as_unset(monkeypatch):
    monkeypatch.setenv("CLIPPYME_API_TOKEN", "   ")
    assert configured_api_token() is None
    enforce_api_token(_FakeRequest())


def test_missing_header_rejected(monkeypatch):
    monkeypatch.setenv("CLIPPYME_API_TOKEN", "s3cret")
    with pytest.raises(HTTPException) as exc:
        enforce_api_token(_FakeRequest())
    assert exc.value.status_code == 401


def test_wrong_token_rejected(monkeypatch):
    monkeypatch.setenv("CLIPPYME_API_TOKEN", "s3cret")
    with pytest.raises(HTTPException):
        enforce_api_token(_FakeRequest({"x-api-token": "nope"}))


def test_x_api_token_header_accepted(monkeypatch):
    monkeypatch.setenv("CLIPPYME_API_TOKEN", "s3cret")
    enforce_api_token(_FakeRequest({"x-api-token": "s3cret"}))


def test_bearer_accepted(monkeypatch):
    monkeypatch.setenv("CLIPPYME_API_TOKEN", "s3cret")
    enforce_api_token(_FakeRequest({"authorization": "Bearer s3cret"}))


def test_x_api_token_wins_over_bearer(monkeypatch):
    """An explicit X-API-Token is used as-is; a stale Authorization header
    doesn't rescue a wrong one."""
    monkeypatch.setenv("CLIPPYME_API_TOKEN", "s3cret")
    with pytest.raises(HTTPException):
        enforce_api_token(_FakeRequest({"x-api-token": "wrong", "authorization": "Bearer s3cret"}))


# --- integration: middleware on the real app ---------------------------------

def _client():
    return TestClient(app_module.app, headers=ORIGIN)


def test_middleware_401s_api_without_token(monkeypatch):
    monkeypatch.setenv("CLIPPYME_API_TOKEN", "s3cret")
    r = _client().get("/api/history")
    assert r.status_code == 401


def test_middleware_passes_with_token(monkeypatch):
    monkeypatch.setenv("CLIPPYME_API_TOKEN", "s3cret")
    r = _client().get("/api/history", headers={"X-API-Token": "s3cret"})
    assert r.status_code == 200


def test_middleware_noop_when_unset(monkeypatch):
    monkeypatch.delenv("CLIPPYME_API_TOKEN", raising=False)
    r = _client().get("/api/history")
    assert r.status_code == 200


def test_cors_preflight_allows_authorization_header(monkeypatch):
    monkeypatch.delenv("CLIPPYME_API_TOKEN", raising=False)
    response = _client().options(
        "/api/history",
        headers={
            "Origin": "http://localhost:5175",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert response.status_code == 200
    assert "authorization" in response.headers.get("access-control-allow-headers", "").lower()
