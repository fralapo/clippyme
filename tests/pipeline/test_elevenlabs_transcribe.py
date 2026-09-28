"""Unit tests for clippyme.pipeline.transcription.elevenlabs_transcribe.

Pure-logic + mocked-network coverage (no real ElevenLabs calls):
- token-stream parsing (spoken vs audio_event vs spacing)
- logprob → probability conversion + clamping
- speaker_id "speaker_0" → int
- segment chunking + majority speaker
- audio-event weaving into the Gemini text
- form shaping (diarize/tag defaults, no_verbatim v2-only, language auto)
- _post_with_retries: 429-then-200, 5xx exhaustion, network recovery
- transcribe_with_elevenlabs full-shape remap (mocked POST)
Runs on the host — the module only needs `requests`, no cv2/ML runtime.
"""
import math

import pytest

import clippyme.pipeline.transcription.elevenlabs_transcribe as el


# --- pure helpers ----------------------------------------------------------

def test_should_retry_classification():
    for s in (408, 409, 425, 429, 500, 502, 503, 504):
        assert el._should_retry(s) is True
    for s in (200, 400, 401, 403, 404):
        assert el._should_retry(s) is False


def test_compute_backoff_honours_retry_after():
    assert el._compute_backoff(1, "12") == 12.0
    assert el._compute_backoff(10, None) == 30.0  # ceiling


def test_is_v2():
    assert el._is_v2("scribe_v2") is True
    assert el._is_v2("scribe_v1") is False


def test_prob_from_logprob_converts_and_clamps():
    assert el._prob_from_logprob({"logprob": 0.0}) == 1.0
    assert el._prob_from_logprob({"logprob": -0.6931}) == pytest.approx(0.5, abs=1e-3)
    # Missing → default 1.0; positive (impossible logprob) → clamped to 1.0
    assert el._prob_from_logprob({}) == 1.0
    assert el._prob_from_logprob({"logprob": 5.0}) == 1.0


def test_speaker_int_parses_speaker_id():
    assert el._speaker_int({"speaker_id": "speaker_0"}) == 0
    assert el._speaker_int({"speaker_id": "speaker_3"}) == 3
    assert el._speaker_int({"speaker_id": None}) is None
    assert el._speaker_int({}) is None


def test_parse_words_splits_spoken_events_and_drops_spacing():
    raw = [
        {"text": "Hello", "start": 0.0, "end": 0.4, "type": "word", "logprob": 0.0,
         "speaker_id": "speaker_0"},
        {"text": " ", "start": 0.4, "end": 0.5, "type": "spacing"},
        {"text": "(laughter)", "start": 0.5, "end": 1.2, "type": "audio_event"},
        {"text": "world.", "start": 1.2, "end": 1.6, "type": "word"},
    ]
    spoken, events = el._parse_words(raw)
    assert [w["word"] for w in spoken] == ["Hello", "world."]
    assert spoken[0]["speaker"] == 0
    assert "speaker" not in spoken[1]  # no speaker_id on 2nd word
    assert len(events) == 1 and events[0]["text"] == "(laughter)"


def test_segments_from_words_breaks_on_sentence_end():
    words = [
        {"word": "Hi", "start": 0.0, "end": 0.3, "probability": 1.0},
        {"word": "there.", "start": 0.3, "end": 0.7, "probability": 1.0},
        {"word": "Next", "start": 0.8, "end": 1.1, "probability": 1.0},
    ]
    segs = el._segments_from_words(words)
    assert len(segs) == 2
    assert segs[0]["text"] == "Hi there."
    assert segs[1]["text"] == "Next"


def test_segments_from_words_attaches_majority_speaker():
    words = [
        {"word": "a", "start": 0.0, "end": 0.2, "probability": 1.0, "speaker": 1},
        {"word": "b", "start": 0.2, "end": 0.4, "probability": 1.0, "speaker": 1},
        {"word": "c.", "start": 0.4, "end": 0.6, "probability": 1.0, "speaker": 2},
    ]
    segs = el._segments_from_words(words)
    assert segs[0]["speaker"] == 1


def test_weave_text_interleaves_events_by_time():
    spoken = [
        {"word": "funny", "start": 0.0, "end": 0.4},
        {"word": "bit", "start": 0.5, "end": 0.9},
        {"word": "then", "start": 2.0, "end": 2.3},
    ]
    events = [{"text": "(laughter)", "start": 1.0, "end": 1.8}]
    woven = el._weave_text(spoken, events, "fallback")
    assert woven == "funny bit (laughter) then"


def test_weave_text_no_events_returns_fallback():
    assert el._weave_text([], [], "the original") == "the original"


def test_build_form_defaults():
    form = el._build_form("scribe_v1", "")
    assert form["model_id"] == "scribe_v1"
    assert form["diarize"] == "true"
    assert form["tag_audio_events"] == "true"
    assert form["timestamps_granularity"] == "word"
    assert "language_code" not in form  # blank → auto-detect


def test_build_form_multi_is_auto_detect():
    form = el._build_form("scribe_v1", "multi")
    assert "language_code" not in form


def test_build_form_locks_language():
    form = el._build_form("scribe_v1", "it")
    assert form["language_code"] == "it"


def test_build_form_no_verbatim_only_on_v2(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_NO_VERBATIM", "true")
    assert "no_verbatim" not in el._build_form("scribe_v1", "")   # v1 rejects it
    assert el._build_form("scribe_v2", "")["no_verbatim"] == "true"


def test_check_file_missing(tmp_path):
    with pytest.raises(el.ElevenLabsError, match="not found"):
        el._check_file(str(tmp_path / "nope.flac"))


def test_check_file_too_large(tmp_path, monkeypatch):
    p = tmp_path / "big.flac"
    p.write_bytes(b"x" * 2048)
    monkeypatch.setenv("ELEVENLABS_MAX_FILE_MB", "0.001")
    with pytest.raises(el.ElevenLabsError, match="too large"):
        el._check_file(str(p))


# --- _post_with_retries (mocked session) -----------------------------------

class _FakeResp:
    def __init__(self, status, text="", headers=None, payload=None, content=b""):
        self.status_code = status
        self.text = text
        self.headers = headers or {}
        self.content = content
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeSession:
    def __init__(self, responses=None, exc_then=None):
        self._responses = list(responses or [])
        self._exc_then = list(exc_then or [])
        self.calls = 0

    def post(self, *a, **k):
        self.calls += 1
        if self._exc_then:
            exc = self._exc_then.pop(0)
            if exc is not None:
                raise exc
        return self._responses.pop(0)

    def close(self):
        pass


@pytest.fixture
def audio_file(tmp_path):
    p = tmp_path / "clip.flac"
    p.write_bytes(b"fake-bytes")
    return str(p)


def _patch_session(monkeypatch, session):
    monkeypatch.setattr(el, "_SESSION", session)
    monkeypatch.setattr(el, "_get_session", lambda: session)
    monkeypatch.setattr(el.time, "sleep", lambda *_: None)


def test_post_retries_on_429_then_succeeds(monkeypatch, audio_file):
    session = _FakeSession(responses=[
        _FakeResp(429, headers={"Retry-After": "0"}),
        _FakeResp(200, text="ok"),
    ])
    _patch_session(monkeypatch, session)
    resp = el._post_with_retries("http://x", {}, {}, audio_file, "file", 1, 3)
    assert resp.status_code == 200
    assert session.calls == 2


def test_post_raises_after_5xx_exhaustion(monkeypatch, audio_file):
    session = _FakeSession(responses=[_FakeResp(503) for _ in range(4)])
    _patch_session(monkeypatch, session)
    with pytest.raises(el.ElevenLabsError):
        el._post_with_retries("http://x", {}, {}, audio_file, "file", 1, 2)


def test_post_recovers_from_network_error(monkeypatch, audio_file):
    import requests
    session = _FakeSession(
        responses=[_FakeResp(200, text="ok")],
        exc_then=[requests.ConnectionError("boom"), None],
    )
    _patch_session(monkeypatch, session)
    resp = el._post_with_retries("http://x", {}, {}, audio_file, "file", 1, 3)
    assert resp.status_code == 200
    assert session.calls == 2


# --- transcribe_with_elevenlabs (mocked POST) ------------------------------

def test_transcribe_full_shape(monkeypatch, audio_file):
    payload = {
        "language_code": "en",
        "language_probability": 0.98,
        "text": "Hello world",
        "audio_duration_secs": 2.0,
        "words": [
            {"text": "Hello", "start": 0.0, "end": 0.4, "type": "word", "logprob": 0.0,
             "speaker_id": "speaker_0"},
            {"text": " ", "start": 0.4, "end": 0.5, "type": "spacing"},
            {"text": "(laughter)", "start": 0.5, "end": 1.0, "type": "audio_event"},
            {"text": "world.", "start": 1.0, "end": 1.5, "type": "word",
             "speaker_id": "speaker_0"},
        ],
    }
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_test")
    monkeypatch.setattr(el, "_post_with_retries",
                        lambda *a, **k: _FakeResp(200, payload=payload))

    out = el.transcribe_with_elevenlabs(audio_file)
    assert out["language"] == "en"
    # Audio event woven into the Gemini-facing text, but NOT into the word stream.
    assert "(laughter)" in out["text"]
    all_words = [w["word"] for seg in out["segments"] for w in seg["words"]]
    assert all_words == ["Hello", "world."]
    assert "(laughter)" not in all_words
    # The event is surfaced separately for observability / viral signal.
    assert out["audio_events"] == [{"text": "(laughter)", "start": 0.5, "end": 1.0}]
    # Diarization label propagated.
    assert out["segments"][0]["words"][0]["speaker"] == 0


def test_transcribe_requires_key(monkeypatch, audio_file):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(el.ElevenLabsError, match="not configured"):
        el.transcribe_with_elevenlabs(audio_file)
