"""client_ip honours forwarded headers only behind a trusted proxy peer.

Pins the TRUST_PROXY hardening: X-Forwarded-For is trusted only when
TRUST_PROXY=1 AND the immediate TCP peer is a private/loopback proxy. A
direct public peer can never spoof its IP via a forged header.
"""
from clippyme.api import security


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, peer, headers=None):
        self.client = _FakeClient(peer) if peer is not None else None
        self.headers = headers or {}


def test_no_trust_proxy_uses_peer(monkeypatch):
    # 8.8.8.8 is a real globally-routable IP (documentation ranges like
    # 203.0.113.x are flagged non-global / "private" by ipaddress).
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    req = _FakeRequest("8.8.8.8", {"x-forwarded-for": "10.0.0.5"})
    assert security.client_ip(req) == "8.8.8.8"


def test_trust_proxy_with_private_peer_honours_xff(monkeypatch):
    # LAST hop, not first: the shipped nginx APPENDS the peer it saw to any
    # incoming header, so the last entry is the proxy-written real client
    # while earlier entries are client-controlled.
    monkeypatch.setenv("TRUST_PROXY", "1")
    req = _FakeRequest("192.168.1.2", {"x-forwarded-for": "10.0.0.5, 8.8.4.4"})
    assert security.client_ip(req) == "8.8.4.4"


def test_trust_proxy_with_public_peer_ignores_spoofed_xff(monkeypatch):
    # Public attacker connects directly with TRUST_PROXY accidentally on:
    # the forged header must be ignored, real peer used.
    monkeypatch.setenv("TRUST_PROXY", "1")
    req = _FakeRequest("8.8.8.8", {"x-forwarded-for": "127.0.0.1"})
    assert security.client_ip(req) == "8.8.8.8"


def test_trust_proxy_loopback_peer_honours_real_ip(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    req = _FakeRequest("127.0.0.1", {"x-real-ip": "8.8.4.4"})
    assert security.client_ip(req) == "8.8.4.4"


def test_missing_client_returns_empty(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    assert security.client_ip(_FakeRequest(None)) == ""
