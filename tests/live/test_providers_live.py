"""Opt-in provider contract tests against REAL APIs. Never enabled by CI.

Read-only account/model discovery by default; billable audio/LLM requests need
CLIPPYME_LIVE_BILLABLE=1 and a small explicit WAV fixture. No real social posts.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

pytestmark = pytest.mark.live


@pytest.fixture(scope="module", autouse=True)
def live_opt_in():
    if os.getenv("CLIPPYME_LIVE_SMOKE") != "1":
        pytest.skip("Live provider tests are opt-in: set CLIPPYME_LIVE_SMOKE=1")


def _key(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


def _request_json(url: str, headers: dict, *, body: bytes | None = None, timeout=20):
    req = Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    with urlopen(req, timeout=timeout) as response:
        return json.load(response)


def test_deepgram_key_can_list_projects():
    body = _request_json("https://api.deepgram.com/v1/projects",
                         {"Authorization": f"Token {_key('DEEPGRAM_API_KEY')}"})
    assert isinstance(body.get("projects"), list)


def test_elevenlabs_key_can_read_account():
    body = _request_json("https://api.elevenlabs.io/v1/user",
                         {"xi-api-key": _key("ELEVENLABS_API_KEY")})
    assert isinstance(body.get("user_id"), str)


def test_gemini_key_can_discover_models():
    body = _request_json("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                         {"x-goog-api-key": _key("GEMINI_API_KEY")})
    assert isinstance(body.get("models"), list)


@pytest.mark.parametrize(("provider", "key_name"), [
    ("openai", "OPENAI_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("deepseek", "DEEPSEEK_API_KEY"),
])
def test_llm_provider_key_can_discover_models(provider, key_name):
    from clippyme.pipeline.analysis.llm_service import list_provider_models

    result = list_provider_models(provider, _key(key_name), force_refresh=True)
    assert not result.get("error"), result.get("error")
    assert isinstance(result.get("models"), list)


def test_zernio_key_can_list_accounts_without_publishing():
    body = _request_json("https://zernio.com/api/v1/accounts",
                         {"Authorization": f"Bearer {_key('ZERNIO_API_KEY')}"})
    assert isinstance(body.get("accounts"), list)


def _billable_wav():
    if os.getenv("CLIPPYME_LIVE_BILLABLE") != "1":
        pytest.skip("Billable provider checks require CLIPPYME_LIVE_BILLABLE=1")
    file = Path(os.getenv("CLIPPYME_LIVE_MEDIA_WAV", ""))
    if not file.is_file() or not 44 < file.stat().st_size < 1_000_000:
        pytest.skip("Provide a small spoken WAV under 1 MB via CLIPPYME_LIVE_MEDIA_WAV")
    return file.read_bytes()


def test_deepgram_accepts_real_audio():
    wav = _billable_wav()
    body = _request_json(
        "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true",
        {"Authorization": f"Token {_key('DEEPGRAM_API_KEY')}", "Content-Type": "audio/wav"},
        body=wav, timeout=50,
    )
    assert "results" in body


def test_elevenlabs_accepts_real_audio():
    wav = _billable_wav()
    boundary = "clippyme" + uuid4().hex
    parts = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model_id\"\r\n\r\n"
        f"scribe_v1\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"sample.wav\"\r\nContent-Type: audio/wav\r\n\r\n"
    ).encode() + wav + f"\r\n--{boundary}--\r\n".encode()
    body = _request_json(
        "https://api.elevenlabs.io/v1/speech-to-text",
        {"xi-api-key": _key("ELEVENLABS_API_KEY"),
         "Content-Type": f"multipart/form-data; boundary={boundary}"},
        body=parts, timeout=60,
    )
    assert isinstance(body.get("text"), str)


def test_gemini_accepts_real_generation():
    if os.getenv("CLIPPYME_LIVE_BILLABLE") != "1":
        pytest.skip("Billable generation requires CLIPPYME_LIVE_BILLABLE=1")
    body = _request_json(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        {"x-goog-api-key": _key("GEMINI_API_KEY"), "Content-Type": "application/json"},
        body=json.dumps({"contents": [{"parts": [{"text": "Reply with one word: OK"}]}]}).encode(),
        timeout=60,
    )
    assert isinstance(body.get("candidates"), list)
