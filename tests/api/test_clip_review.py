"""Durable operator review decisions and the manual-publish approval gate."""
import json

import pytest
from fastapi.testclient import TestClient

from clippyme.api import app as app_module
from clippyme.integrations import social_publisher
from clippyme.jobs.job_artifacts import load_job_metadata

JOB = "91919191-9191-4191-8191-919191919191"
ORIGIN = {"Origin": "http://localhost:5175"}
PUBLISH = {"platforms": [{"platform": "tiktok", "accountId": "acc"}]}


@pytest.fixture
def job(monkeypatch, tmp_path):
    outputs = tmp_path / "output"
    job_dir = outputs / JOB
    job_dir.mkdir(parents=True)
    (job_dir / "clip.mp4").write_bytes(b"clip")
    (job_dir / "clip_metadata.json").write_text(json.dumps({
        "shorts": [{"start": 0, "end": 10, "clip_filename": "clip.mp4"}],
    }))
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(outputs))
    monkeypatch.setattr(app_module, "load_zernio_config", lambda: {"api_key": "test"})
    uploads = []
    monkeypatch.setattr(social_publisher, "publish_clip", lambda **kwargs:
                        uploads.append(kwargs["clip_path"]) or {"post_id": "p1"})
    app_module.jobs[JOB] = {"status": "completed"}
    yield TestClient(app_module.app, headers=ORIGIN), outputs, uploads
    app_module.jobs.pop(JOB, None)


def test_review_state_is_saved_in_job_metadata_and_change_requests_need_a_note(job):
    http, outputs, _ = job

    missing_note = http.patch(f"/api/review/{JOB}/0", json={"status": "changes_requested"})
    assert missing_note.status_code == 422

    changed = http.patch(f"/api/review/{JOB}/0", json={
        "status": "changes_requested", "note": "  Keep the full sentence.  ",
    })
    assert changed.status_code == 200, changed.text
    clip = load_job_metadata(JOB, str(outputs))[1]["shorts"][0]
    assert clip["review_status"] == "changes_requested"
    assert clip["review_note"] == "Keep the full sentence."
    assert clip["review_updated_at"]

    approved = http.patch(f"/api/review/{JOB}/0", json={"status": "approved"})
    assert approved.status_code == 200, approved.text
    clip = load_job_metadata(JOB, str(outputs))[1]["shorts"][0]
    assert clip["review_status"] == "approved"
    assert "review_note" not in clip
    restored = http.post(f"/api/history/{JOB}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["result"]["clips"][0]["review_status"] == "approved"


def test_manual_publish_fails_closed_until_the_clip_is_approved(job):
    http, outputs, uploads = job

    denied = http.post(f"/api/publish/{JOB}/0", json=PUBLISH)
    assert denied.status_code == 409
    assert "approval" in denied.json()["detail"].lower()
    assert uploads == []

    assert http.patch(f"/api/review/{JOB}/0", json={"status": "approved"}).status_code == 200
    accepted = http.post(f"/api/publish/{JOB}/0", json=PUBLISH)
    assert accepted.status_code == 200, accepted.text
    assert uploads == [str(outputs / JOB / "clip.mp4")]
    clip = load_job_metadata(JOB, str(outputs))[1]["shorts"][0]
    assert clip["published"][0]["post_id"] == "p1"


def test_review_is_refused_while_the_job_is_active(job):
    http, _, _ = job
    app_module.jobs[JOB] = {"status": "processing"}

    response = http.patch(f"/api/review/{JOB}/0", json={"status": "approved"})

    assert response.status_code == 409
