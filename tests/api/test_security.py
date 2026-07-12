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

    def __init__(self, origin=None, client_host=None, sec_fetch_site=None):
        self.headers = {}
        if origin is not None:
            self.headers["origin"] = origin
        if sec_fetch_site is not None:
            self.headers["sec-fetch-site"] = sec_fetch_site
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


# --- Sec-Fetch-Site CSRF guard (regression for the IP-fallback bypass) ------

@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_require_trusted_request_rejects_cross_site_sec_fetch(site):
    # A cross-origin browser request (e.g. an HTML form POST that omits Origin)
    # still carries a browser-set Sec-Fetch-Site header that JS cannot forge.
    # Even from a private/loopback client it must be rejected — this is the
    # CSRF hole the IP-fallback branch used to leave open.
    req = _FakeRequest(origin=None, client_host="127.0.0.1", sec_fetch_site=site)
    with pytest.raises(HTTPException) as exc:
        require_trusted_config_request(req)
    assert exc.value.status_code == 403


def test_require_trusted_request_cross_site_beats_trusted_origin(monkeypatch):
    # Sec-Fetch-Site is checked first, so a spoofed-but-allow-listed Origin
    # cannot rescue a cross-site request.
    monkeypatch.setattr(security, "ALLOWED_ORIGINS", ["http://localhost:5175"])
    req = _FakeRequest(origin="http://localhost:5175", client_host="127.0.0.1",
                       sec_fetch_site="cross-site")
    with pytest.raises(HTTPException) as exc:
        require_trusted_config_request(req)
    assert exc.value.status_code == 403


def test_require_trusted_request_allows_same_origin_sec_fetch(monkeypatch):
    # The real frontend sends Sec-Fetch-Site: same-origin with a trusted Origin.
    monkeypatch.setattr(security, "ALLOWED_ORIGINS", ["http://localhost:5175"])
    req = _FakeRequest(origin="http://localhost:5175", client_host="127.0.0.1",
                       sec_fetch_site="same-origin")
    assert require_trusted_config_request(req) is None


def test_require_trusted_request_allows_cli_no_sec_fetch():
    # curl / CLI tools send no Sec-Fetch-Site and no Origin → fall through to
    # the private-IP check, which still works.
    req = _FakeRequest(origin=None, client_host="127.0.0.1")
    assert require_trusted_config_request(req) is None


# --- client_ip / X-Forwarded-For -------------------------------------------

def test_client_ip_ignores_forwarded_headers_without_trust_proxy(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    req = _FakeRequest(client_host="127.0.0.1")
    req.headers["x-forwarded-for"] = "9.9.9.9"
    assert security.client_ip(req) == "127.0.0.1"


def test_client_ip_reads_last_hop_from_appending_proxy(monkeypatch):
    # Regression: the shipped nginx.conf APPENDS the peer to X-Forwarded-For
    # ($proxy_add_x_forwarded_for). Reading the FIRST hop would let a client
    # behind the proxy forge "X-Forwarded-For: 127.0.0.1" and be treated as
    # loopback (config access) while dodging per-IP rate limits. The last
    # hop is the address the trusted proxy itself wrote.
    monkeypatch.setenv("TRUST_PROXY", "1")
    req = _FakeRequest(client_host="172.18.0.2")  # the proxy container
    req.headers["x-forwarded-for"] = "127.0.0.1, 9.9.9.9"
    assert security.client_ip(req) == "9.9.9.9"
    assert security.is_trusted_client_host(security.client_ip(req)) is False


def test_client_ip_single_hop_overwriting_proxy(monkeypatch):
    # With a proxy that overwrites the header there is one hop: last == first.
    monkeypatch.setenv("TRUST_PROXY", "1")
    req = _FakeRequest(client_host="172.18.0.2")
    req.headers["x-forwarded-for"] = "8.8.8.8"
    assert security.client_ip(req) == "8.8.8.8"


def test_client_ip_untrusted_peer_never_honours_forwarded(monkeypatch):
    # TRUST_PROXY=1 left on while the app is also reachable directly: a
    # public peer's forged header must be ignored (second gate).
    monkeypatch.setenv("TRUST_PROXY", "1")
    req = _FakeRequest(client_host="8.8.8.8")
    req.headers["x-forwarded-for"] = "127.0.0.1"
    assert security.client_ip(req) == "8.8.8.8"


def test_client_ip_x_real_ip_fallback(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    req = _FakeRequest(client_host="127.0.0.1")
    req.headers["x-real-ip"] = "9.9.9.9"
    assert security.client_ip(req) == "9.9.9.9"


# --- rate limiting ---------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_rate_state():
    security._rate_state.clear()
    yield
    security._rate_state.clear()


def test_rate_limit_allows_until_capacity_then_blocks():
    key = ("bucket", "1.2.3.4")
    # capacity 3, no refill within the same instant
    assert security._rate_limit_allow(key, 3, 0.0, now=100.0) is True
    assert security._rate_limit_allow(key, 3, 0.0, now=100.0) is True
    assert security._rate_limit_allow(key, 3, 0.0, now=100.0) is True
    assert security._rate_limit_allow(key, 3, 0.0, now=100.0) is False


def test_rate_limit_refills_over_time():
    key = ("bucket", "1.2.3.4")
    assert security._rate_limit_allow(key, 1, 1.0, now=0.0) is True
    assert security._rate_limit_allow(key, 1, 1.0, now=0.0) is False
    # one second later, one token refilled
    assert security._rate_limit_allow(key, 1, 1.0, now=1.0) is True


def test_rate_limit_isolated_per_client_and_bucket():
    assert security._rate_limit_allow(("a", "ip1"), 1, 0.0, now=0.0) is True
    assert security._rate_limit_allow(("a", "ip1"), 1, 0.0, now=0.0) is False
    # different client → fresh bucket
    assert security._rate_limit_allow(("a", "ip2"), 1, 0.0, now=0.0) is True
    # different bucket, same client → fresh
    assert security._rate_limit_allow(("b", "ip1"), 1, 0.0, now=0.0) is True


def test_enforce_rate_limit_raises_429(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    req = _FakeRequest(client_host="9.9.9.9")
    security.enforce_rate_limit(req, "process", capacity=1, refill_per_sec=0.0)
    with pytest.raises(HTTPException) as exc:
        security.enforce_rate_limit(req, "process", capacity=1, refill_per_sec=0.0)
    assert exc.value.status_code == 429


def test_eviction_judges_each_bucket_by_its_own_capacity(monkeypatch):
    # Regression: eviction used the CURRENT request's capacity for every
    # entry, so a small-capacity bucket checked during a large-capacity
    # request was never seen as idle (its tokens can't reach the larger
    # capacity) and idle entries survived while active ones got mass-purged.
    monkeypatch.setattr(security, "_RATE_STATE_MAX", 3)
    # Idle small bucket: full at its own capacity (2.0).
    assert security._rate_limit_allow(("small", "ip1"), 2, 10.0, now=0.0) is True
    # Two active large buckets, freshly drained (no refill).
    assert security._rate_limit_allow(("big", "ip2"), 30, 0.0, now=100.0) is True
    assert security._rate_limit_allow(("big", "ip3"), 30, 0.0, now=100.0) is True
    # Table is at max → the next call triggers targeted eviction. The small
    # bucket refilled to ITS capacity long ago and must be the one dropped.
    assert security._rate_limit_allow(("big", "ip4"), 30, 0.0, now=100.0) is True
    assert ("small", "ip1") not in security._rate_state
    assert ("big", "ip2") in security._rate_state
    assert ("big", "ip3") in security._rate_state


def test_enforce_rate_limit_disabled_via_env(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "0")
    req = _FakeRequest(client_host="9.9.9.9")
    # Never raises when disabled, regardless of how many calls.
    for _ in range(50):
        security.enforce_rate_limit(req, "process", capacity=1, refill_per_sec=0.0)
