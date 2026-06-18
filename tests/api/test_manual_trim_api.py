"""API surface for the manual-trim feature (flycut-ported).

* GET  /api/transcript/{job}/{clip} → clip-relative editable segments
* POST /api/smartcut/{job}/{clip}   → accepts an optional drop_ranges body

TestClient is used WITHOUT its context manager so the FastAPI lifespan (workers,
background loops) never starts. smart_cut's ffmpeg path is monkeypatched away —
we assert the endpoint plumbing, not the render.
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from clippyme.api import app as app_module

JOB_ID = "22222222-2222-4222-8222-222222222222"
ORIGIN = {"Origin": "http://localhost:5175"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    outputs = tmp_path / "output"
    job_dir = outputs / JOB_ID
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(outputs))
    # metadata.json: a clip spanning 10–13s with two utterances inside it.
    meta = {
        "transcript": {
            "language": "en",
            "segments": [
                {"words": [{"word": "keep", "start": 10.0, "end": 10.5},
                           {"word": "this", "start": 10.5, "end": 11.0}]},
                {"words": [{"word": "cut", "start": 12.0, "end": 12.4},
                           {"word": "me", "start": 12.4, "end": 12.9}]},
            ],
        },
        "shorts": [{"start": 10.0, "end": 13.0}],
    }
    with open(job_dir / "vid_metadata.json", "w") as f:
        json.dump(meta, f)
    app_module.jobs[JOB_ID] = {"status": "completed", "result": {"clips": []}}
    yield TestClient(app_module.app, headers=ORIGIN)
    app_module.jobs.pop(JOB_ID, None)


def test_transcript_endpoint_returns_relative_segments(client):
    r = client.get(f"/api/transcript/{JOB_ID}/0")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["duration"] == 3.0
    assert [s["text"] for s in data["segments"]] == ["keep this", "cut me"]
    assert data["segments"][0]["start"] == 0.0   # 10.0 - 10.0
    assert data["segments"][1]["start"] == 2.0   # 12.0 - 10.0


def test_transcript_endpoint_bad_clip_index(client):
    assert client.get(f"/api/transcript/{JOB_ID}/9").status_code == 404


def test_smartcut_accepts_drop_ranges_body(client, monkeypatch):
    captured = {}

    async def fake_run(*, job_id, clip_index, output_dir, metadata_path, data, drop_ranges=None):
        captured["drop_ranges"] = drop_ranges
        return {"success": True, "stats": {}}

    monkeypatch.setattr(app_module, "run_smart_cut", fake_run)
    r = client.post(f"/api/smartcut/{JOB_ID}/0", json={"drop_ranges": [[2.0, 2.9]]})
    assert r.status_code == 200, r.text
    assert captured["drop_ranges"] == [[2.0, 2.9]]


def test_smartcut_no_body_still_works(client, monkeypatch):
    captured = {"called": False}

    async def fake_run(*, job_id, clip_index, output_dir, metadata_path, data, drop_ranges=None):
        captured["called"] = True
        captured["drop_ranges"] = drop_ranges
        return {"success": True, "stats": {}}

    monkeypatch.setattr(app_module, "run_smart_cut", fake_run)
    r = client.post(f"/api/smartcut/{JOB_ID}/0")
    assert r.status_code == 200, r.text
    assert captured["called"] and captured["drop_ranges"] is None
