"""POST /api/edit-ai returns Gemini-suggested drop spans for a clip.

The Gemini call (suggest_drops) is mocked — this guards the endpoint wiring:
metadata load, clip lookup, transcript→segments, key resolution, response shape.
TestClient is used WITHOUT its context manager so the FastAPI lifespan never
starts.
"""
import json

import pytest
from fastapi.testclient import TestClient

from clippyme.api import app as app_module
import clippyme.domain.clip_edit_ai as clip_edit_ai

JOB_ID = "44444444-4444-4444-8444-444444444444"
ORIGIN = {"Origin": "http://localhost:5175", "X-Gemini-Key": "dummy-test-key-not-real"}


def _make_client(monkeypatch, tmp_path):
    outputs = tmp_path / "output"
    job_dir = outputs / JOB_ID
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(outputs))
    meta = {
        "transcript": {
            "language": "en",
            "segments": [{"words": [
                {"start": 0.0, "end": 1.0, "word": "intro"},
                {"start": 3.0, "end": 4.0, "word": "body"},
            ]}],
        },
        "shorts": [{"start": 0.0, "end": 5.0}],
    }
    with open(job_dir / "vid_metadata.json", "w") as f:
        json.dump(meta, f)
    return TestClient(app_module.app, headers=ORIGIN)


def teardown_function():
    app_module.jobs.pop(JOB_ID, None)


def test_edit_ai_returns_drop_ranges(monkeypatch, tmp_path):
    captured = {}

    def fake_suggest(*, api_key, model, segments, instruction, clip_duration):
        captured.update(instruction=instruction, model=model, duration=clip_duration)
        return {"drops": [[0.0, 1.0]], "explanation": "cut intro"}

    monkeypatch.setattr(clip_edit_ai, "suggest_drops", fake_suggest)
    client = _make_client(monkeypatch, tmp_path)
    r = client.post(f"/api/edit-ai/{JOB_ID}/0", json={"instruction": "cut the intro"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["drop_ranges"] == [[0.0, 1.0]]
    assert body["explanation"] == "cut intro"
    assert captured["instruction"] == "cut the intro"
    assert captured["duration"] == 5.0


def test_edit_ai_404_for_bad_clip(monkeypatch, tmp_path):
    monkeypatch.setattr(clip_edit_ai, "suggest_drops",
                        lambda **k: {"drops": [], "explanation": ""})
    client = _make_client(monkeypatch, tmp_path)
    r = client.post(f"/api/edit-ai/{JOB_ID}/99", json={"instruction": "x"})
    assert r.status_code == 404


def test_edit_ai_rejects_empty_instruction(monkeypatch, tmp_path):
    client = _make_client(monkeypatch, tmp_path)
    r = client.post(f"/api/edit-ai/{JOB_ID}/0", json={"instruction": ""})
    assert r.status_code == 422  # schema min_length=1
