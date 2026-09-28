"""POST /api/history/{id}/restore must never replace a job that is still live.

Restore rebuilds a ``completed`` entry from the files on disk. For a job the
worker still owns (queued / processing / paused) that swap made the dispatcher
skip a queued job, hid the running process from stop/cancel/pause (the new
entry has no ``process``) and dropped the job from the crash journal, which
only keeps ACTIVE entries — so a restart could no longer resume it.

TestClient is used without its context manager (no lifespan). The e2e test
drives the real runner + a real subprocess against the app's own registry.
"""
import asyncio
import json
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

from clippyme.api import app as app_module
from clippyme.jobs import job_journal as jj
from clippyme.jobs.job_runner import make_run_job

JOB_ID = "77777777-7777-4777-8777-777777777777"
ORIGIN = {"Origin": "http://localhost:5175"}


def _job_on_disk(outputs):
    job_dir = outputs / JOB_ID
    job_dir.mkdir(parents=True)
    (job_dir / "vid_clip_1.mp4").write_bytes(b"\x00")
    (job_dir / "vid_metadata.json").write_text(json.dumps({"shorts": [{"start": 0, "end": 5}]}))
    return job_dir


@pytest.fixture
def client(monkeypatch, tmp_path):
    outputs = tmp_path / "output"
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(outputs))
    yield TestClient(app_module.app, headers=ORIGIN), outputs
    app_module.jobs.pop(JOB_ID, None)


@pytest.mark.parametrize("status", ["queued", "processing", "paused"])
def test_restore_refuses_an_active_job(client, status):
    http, outputs = client
    _job_on_disk(outputs)
    live = {"status": status, "logs": [], "process": object()}
    app_module.jobs[JOB_ID] = live

    r = http.post(f"/api/history/{JOB_ID}/restore")

    assert r.status_code == 409, r.text
    assert app_module.jobs[JOB_ID] is live
    assert live["status"] == status


@pytest.mark.parametrize("status", ["completed", "failed", "stopped"])
def test_restore_replaces_a_finished_in_memory_entry(client, status):
    http, outputs = client
    _job_on_disk(outputs)
    app_module.jobs[JOB_ID] = {"status": status, "logs": []}

    r = http.post(f"/api/history/{JOB_ID}/restore")

    assert r.status_code == 200, r.text
    assert app_module.jobs[JOB_ID]["status"] == "completed"
    assert len(app_module.jobs[JOB_ID]["result"]["clips"]) == 1


def test_restore_of_a_job_unknown_in_memory(client):
    http, outputs = client
    _job_on_disk(outputs)

    assert http.post(f"/api/history/{JOB_ID}/restore").status_code == 200
    assert app_module.jobs[JOB_ID]["status"] == "completed"


def test_restore_of_a_job_missing_on_disk_is_404(client):
    http, _ = client
    assert http.post(f"/api/history/{JOB_ID}/restore").status_code == 404
    assert JOB_ID not in app_module.jobs


# Stand-in pipeline: the first clip is already on disk (so a restore has
# something to rebuild), then it blocks until released and exits cleanly.
FAKE_PIPELINE = r'''
import json, os, sys, time
out = sys.argv[1]
with open(os.path.join(out, "vid_clip_1.mp4"), "wb") as fh:
    fh.write(b"\x00")
with open(os.path.join(out, "vid_metadata.json"), "w") as fh:
    json.dump({"shorts": [{"start": 0, "end": 5}, {"start": 5, "end": 9}]}, fh)
open(os.path.join(out, "started"), "w").close()
while not os.path.exists(os.path.join(out, "release")):
    time.sleep(0.05)
with open(os.path.join(out, "vid_clip_2.mp4"), "wb") as fh:
    fh.write(b"\x00")
'''


async def _wait_for(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not reached before timeout")


def test_restore_during_a_running_job_leaves_the_live_job_intact(client, tmp_path):
    http, outputs = client
    output_dir = outputs / JOB_ID
    output_dir.mkdir(parents=True)
    script = tmp_path / "fake_pipeline.py"
    script.write_text(FAKE_PIPELINE, encoding="utf-8")
    journal = str(tmp_path / "jobs_journal.json")
    jobs = app_module.jobs
    persist = jj.make_journal_writer(jobs=jobs, path=journal)
    run_job = make_run_job(jobs=jobs, output_root=str(outputs), on_change=persist)
    jobs[JOB_ID] = {
        "status": "queued", "logs": [], "result": None,
        "cmd": [sys.executable, "-u", str(script), str(output_dir)],
        "env": dict(os.environ), "output_dir": str(output_dir), "max_attempts": 1,
    }

    async def scenario():
        runner = asyncio.create_task(run_job(JOB_ID, dict(jobs[JOB_ID])))
        await _wait_for(lambda: (output_dir / "started").exists() and jobs[JOB_ID].get("pid"))
        live = jobs[JOB_ID]
        response = await asyncio.to_thread(http.post, f"/api/history/{JOB_ID}/restore")
        assert jobs[JOB_ID] is live and live["status"] == "processing"
        persist()
        assert jj.load_journal(journal)[JOB_ID]["status"] == "processing"
        (output_dir / "release").write_text("")
        await asyncio.wait_for(runner, 30)
        return response

    response = asyncio.run(scenario())

    assert response.status_code == 409, response.text
    job = jobs[JOB_ID]
    assert job["status"] == "completed"
    assert "Process finished successfully." in job["logs"]
    assert len(job["result"]["clips"]) == 2
