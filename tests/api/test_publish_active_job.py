"""POST /api/publish must refuse a job the pipeline still owns.

While a job is queued/processing/paused the orchestrator subprocess rewrites
the whole metadata file from its own in-memory copy at every clip milestone,
so the publish record written after the upload would be erased by its next
checkpoint (the dashboard only offers publishing once a job is complete; this
closes the same window for direct API callers).
"""
import json

import pytest
from fastapi.testclient import TestClient

from clippyme.api import app as app_module
from clippyme.domain.job_artifacts import load_job_metadata, record_clip_publish
from clippyme.integrations import social_publisher
from clippyme.pipeline.orchestrator import _save_metadata

JOB_ID = "88888888-8888-4888-8888-888888888888"
ORIGIN = {"Origin": "http://localhost:5175"}
PUBLISH = {"platforms": [{"platform": "tiktok", "accountId": "acc"}]}


@pytest.fixture
def job(monkeypatch, tmp_path):
    outputs = tmp_path / "output"
    job_dir = outputs / JOB_ID
    job_dir.mkdir(parents=True)
    (job_dir / "vid_clip_1.mp4").write_bytes(b"RAW")
    (job_dir / "vid_metadata.json").write_text(json.dumps({"shorts": [{"start": 0, "end": 5}]}))
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(outputs))
    monkeypatch.setattr(app_module, "load_zernio_config", lambda: {"api_key": "k"})
    uploads = []
    monkeypatch.setattr(social_publisher, "publish_clip",
                        lambda *, clip_path, **kw: uploads.append(clip_path) or {"post_id": "p"})
    yield TestClient(app_module.app, headers=ORIGIN), job_dir, uploads
    app_module.jobs.pop(JOB_ID, None)


def test_a_publish_record_written_mid_job_is_erased_by_the_pipeline(tmp_path):
    """Why the gate exists: the orchestrator's next checkpoint save wins."""
    out = str(tmp_path)
    (tmp_path / JOB_ID).mkdir()
    meta_path = tmp_path / JOB_ID / "vid_metadata.json"
    pipeline_copy = {"shorts": [{"start": 0, "end": 5}, {"start": 5, "end": 9}]}
    meta_path.write_text(json.dumps(pipeline_copy))

    record_clip_publish(JOB_ID, 0, out, {"post_id": "p1"})
    _save_metadata(str(meta_path), pipeline_copy)   # next clip milestone

    assert "published" not in load_job_metadata(JOB_ID, out)[1]["shorts"][0]


@pytest.mark.parametrize("status", ["queued", "processing", "paused"])
def test_publish_is_refused_while_the_job_is_active(job, status):
    http, _, uploads = job
    app_module.jobs[JOB_ID] = {"status": status}

    r = http.post(f"/api/publish/{JOB_ID}/0", json=PUBLISH)

    assert r.status_code == 409, r.text
    assert uploads == []


def test_publish_of_a_finished_job_still_works(job):
    http, job_dir, uploads = job
    app_module.jobs[JOB_ID] = {"status": "completed"}

    r = http.post(f"/api/publish/{JOB_ID}/0", json=PUBLISH)

    assert r.status_code == 200, r.text
    assert uploads == [str(job_dir / "vid_clip_1.mp4")]
    assert load_job_metadata(JOB_ID, str(job_dir.parent))[1]["shorts"][0]["published"][0]["post_id"] == "p"
