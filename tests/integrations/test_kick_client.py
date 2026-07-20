"""Tests for clippyme.integrations.kick_client.

Pure readers (is_live / playback_url) plus get_channel with a fake curl_cffi
module injected — no network, no curl_cffi wheel required on the host.
"""
from datetime import timezone

from clippyme.integrations import kick_client
from clippyme.integrations.kick_client import (
    KickClient,
    extract_vods,
    is_live,
    playback_url,
    stream_started_at,
)


# --- extract_vods (defensive field fallbacks) ------------------------------

def test_extract_vods_previous_livestreams_nested_video():
    ch = {"previous_livestreams": [{"video": {"uuid": "u1"}, "created_at": "t1"}]}
    vods = extract_vods(ch)
    assert vods == [{"id": "u1", "url": "https://kick.com/video/u1", "created_at": "t1"}]


def test_extract_vods_flat_list_payload():
    vods = extract_vods([{"uuid": "u2", "start_time": "t2"}])
    assert vods[0]["id"] == "u2"
    assert vods[0]["url"] == "https://kick.com/video/u2"


def test_extract_vods_videos_field_and_id_fallback():
    vods = extract_vods({"videos": [{"id": "u3"}]})
    assert vods[0]["id"] == "u3"


def test_extract_vods_empty_and_bad():
    assert extract_vods(None) == []
    assert extract_vods({}) == []
    assert extract_vods([{"no_id": 1}]) == []


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


# --- stream_started_at (pure, tolerant) -------------------------------------

def test_stream_started_at_iso_z():
    dt = stream_started_at({"livestream": {"created_at": "2026-07-21T12:00:00.000000Z"}})
    assert dt == dt.replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    assert dt.tzinfo is not None


def test_stream_started_at_space_separated():
    dt = stream_started_at({"livestream": {"start_time": "2026-07-21 09:30:00"}})
    assert dt.tzinfo is not None
    assert (dt.hour, dt.minute) == (9, 30)


def test_stream_started_at_missing_or_bad():
    assert stream_started_at(None) is None
    assert stream_started_at({}) is None
    assert stream_started_at({"livestream": None}) is None
    assert stream_started_at({"livestream": {"created_at": "not a date"}}) is None
    assert stream_started_at({"livestream": {"created_at": 12345}}) is None


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
