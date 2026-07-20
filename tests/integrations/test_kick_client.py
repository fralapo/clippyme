"""Tests for clippyme.integrations.kick_client.

Pure readers (is_live / playback_url) plus get_channel with a fake curl_cffi
module injected — no network, no curl_cffi wheel required on the host.
"""
from clippyme.integrations import kick_client
from clippyme.integrations.kick_client import KickClient, is_live, playback_url


# --- is_live / playback_url (pure) -----------------------------------------

def test_is_live_true_when_livestream_present():
    assert is_live({"livestream": {"is_live": True, "playback_url": "x"}}) is True


def test_is_live_defaults_true_when_flag_absent():
    # A non-null livestream object with no explicit flag still means live.
    assert is_live({"livestream": {"playback_url": "x"}}) is True


def test_is_live_false_when_offline():
    assert is_live({"livestream": None}) is False
    assert is_live({}) is False
    assert is_live(None) is False
    assert is_live({"livestream": {"is_live": False}}) is False


def test_playback_url_extraction():
    assert playback_url({"livestream": {"playback_url": "http://hls"}}) == "http://hls"
    assert playback_url({"playback_url": "http://top"}) == "http://top"
    assert playback_url({"livestream": {}}) is None
    assert playback_url(None) is None


# --- get_channel (fake curl_cffi) ------------------------------------------

class _FakeResp:
    def __init__(self, status_code, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("bad json")
        return self._payload


class _FakeRequests:
    """Stand-in for curl_cffi.requests recording the impersonate profiles used."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.profiles_used = []

    def get(self, url, impersonate=None, timeout=None):
        self.profiles_used.append(impersonate)
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def _client_with(responses):
    client = KickClient()
    fake = _FakeRequests(responses)
    client._cf_requests = lambda: fake
    return client, fake


def test_get_channel_success():
    client, _ = _client_with([_FakeResp(200, {"slug": "foo", "livestream": None})])
    assert client.get_channel("foo") == {"slug": "foo", "livestream": None}


def test_get_channel_404_returns_none():
    client, _ = _client_with([_FakeResp(404)])
    assert client.get_channel("nope") is None


def test_get_channel_rotates_profile_on_403():
    # First profile 403s, second succeeds — should rotate and return the 200.
    client, fake = _client_with([_FakeResp(403), _FakeResp(200, {"ok": 1})])
    assert client.get_channel("foo") == {"ok": 1}
    assert fake.profiles_used[0] != fake.profiles_used[1]


def test_get_channel_all_403_gives_up():
    client, fake = _client_with([_FakeResp(403), _FakeResp(403), _FakeResp(403)])
    assert client.get_channel("foo") is None
    # One attempt per profile.
    assert len(fake.profiles_used) == len(kick_client.DEFAULT_PROFILES)


def test_get_channel_network_error_rotates():
    client, _ = _client_with([ConnectionError("boom"), _FakeResp(200, {"ok": 2})])
    assert client.get_channel("foo") == {"ok": 2}


def test_get_channel_bad_json_returns_none():
    client, _ = _client_with([_FakeResp(200, raise_json=True)])
    assert client.get_channel("foo") is None


def test_get_channel_5xx_returns_none():
    client, _ = _client_with([_FakeResp(503)])
    assert client.get_channel("foo") is None
