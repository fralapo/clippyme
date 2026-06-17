"""Unit tests for clippyme.pipeline.deepgram_transcribe.

Pure-logic + mocked-network coverage (no real Deepgram calls):
- retry/backoff classification + Retry-After honouring
- Nova-3 param shaping
- file-size guard
- session reset after errors
- _post_with_retries: 429-then-200 retry, 5xx exhaustion, network recovery
These run on the host (the module only needs `requests`, no cv2/ML runtime).
"""
import pytest

import clippyme.pipeline.deepgram_transcribe as dg


# --- pure helpers ----------------------------------------------------------

def test_should_retry_classification():
    for s in (408, 409, 425, 429, 500, 502, 503, 504):
        assert dg._should_retry(s) is True
    for s in (200, 400, 401, 403, 404):
        assert dg._should_retry(s) is False


def test_compute_backoff_honours_retry_after():
    assert dg._compute_backoff(1, "12") == 12.0
    assert dg._compute_backoff(3, "0.5") == 0.5


def test_compute_backoff_exponential_with_ceiling():
    assert dg._compute_backoff(1, None) == 2.0
    assert dg._compute_backoff(2, None) == 4.0
    assert dg._compute_backoff(10, None) == 30.0  # ceiling


def test_compute_backoff_bad_retry_after_falls_back():
    assert dg._compute_backoff(1, "not-a-number") == 2.0


def test_is_nova3():
    assert dg._is_nova3("nova-3") is True
    assert dg._is_nova3("Nova-3-General") is True
    assert dg._is_nova3("nova-2") is False


def test_build_params_drops_filler_words_on_nova3():
    params = dict(dg._build_params("nova-3", "multi"))
    assert "filler_words" not in params


def test_build_params_keeps_filler_words_on_nova2():
    keys = [k for k, _ in dg._build_params("nova-2", "en")]
    assert "filler_words" in keys


def test_check_file_missing(tmp_path):
    with pytest.raises(dg.DeepgramError, match="File not found"):
        dg._check_file(str(tmp_path / "nope.mp4"))


def test_check_file_empty(tmp_path):
    p = tmp_path / "empty.mp4"
    p.write_bytes(b"")
    with pytest.raises(dg.DeepgramError, match="empty"):
        dg._check_file(str(p))


def test_check_file_too_large(tmp_path, monkeypatch):
    p = tmp_path / "big.mp4"
    p.write_bytes(b"x" * 2048)
    monkeypatch.setenv("DEEPGRAM_MAX_FILE_MB", "0.001")  # ~1KB cap
    with pytest.raises(dg.DeepgramError, match="too large"):
        dg._check_file(str(p))


def test_reset_session_clears_global():
    dg._get_session()
    assert dg._SESSION is not None
    dg._reset_session()
    assert dg._SESSION is None


# --- _post_with_retries (mocked session) -----------------------------------

class _FakeResp:
    def __init__(self, status, text="", headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}


class _FakeSession:
    def __init__(self, responses=None, exc_then=None):
        self._responses = list(responses or [])
        self._exc_then = list(exc_then or [])
        self.calls = 0
        self.closed = False

    def post(self, *a, **k):
        self.calls += 1
        if self._exc_then:
            exc = self._exc_then.pop(0)
            if exc is not None:
                raise exc
        return self._responses.pop(0)

    def close(self):
        self.closed = True


@pytest.fixture
def video_file(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"fake-bytes")
    return str(p)


def _patch_session(monkeypatch, session):
    monkeypatch.setattr(dg, "_SESSION", session)
    monkeypatch.setattr(dg, "_get_session", lambda: session)
    # No real sleeping between retries.
    monkeypatch.setattr(dg.time, "sleep", lambda *_: None)


def test_post_retries_on_429_then_succeeds(monkeypatch, video_file):
    session = _FakeSession(responses=[
        _FakeResp(429, headers={"Retry-After": "0"}),
        _FakeResp(200, text="ok"),
    ])
    _patch_session(monkeypatch, session)
    resp = dg._post_with_retries({}, [], video_file, timeout=1, max_retries=3)
    assert resp.status_code == 200
    assert session.calls == 2


def test_post_raises_after_5xx_exhaustion(monkeypatch, video_file):
    session = _FakeSession(responses=[_FakeResp(503) for _ in range(4)])
    _patch_session(monkeypatch, session)
    with pytest.raises(dg.DeepgramError):
        dg._post_with_retries({}, [], video_file, timeout=1, max_retries=2)


def test_post_does_not_retry_on_4xx(monkeypatch, video_file):
    session = _FakeSession(responses=[_FakeResp(401, text="bad key")])
    _patch_session(monkeypatch, session)
    with pytest.raises(dg.DeepgramError, match="401"):
        dg._post_with_retries({}, [], video_file, timeout=1, max_retries=3)
    assert session.calls == 1


def test_post_recovers_from_network_error(monkeypatch, video_file):
    import requests
    session = _FakeSession(
        responses=[_FakeResp(200, text="ok")],
        exc_then=[requests.ConnectionError("boom"), None],
    )
    _patch_session(monkeypatch, session)
    resp = dg._post_with_retries({}, [], video_file, timeout=1, max_retries=3)
    assert resp.status_code == 200
    assert session.calls == 2
