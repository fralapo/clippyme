"""Tests for the pause / resume / graceful-stop control endpoints in app.py.

Driven with Starlette's TestClient WITHOUT entering its context manager, so the
FastAPI lifespan (job workers, background loops) never starts. A fake Popen-like
object is injected into the in-memory ``jobs`` dict and the psutil process-tree
helpers + partial-result loader are monkeypatched, so no real OS process is
touched. We pin the status-machine behaviour the frontend relies on:

* pause only from 'processing'; resume only from 'paused'
* graceful stop keeps the finished clips (status 'stopped', kept_clips count)
* a queued job can be stopped before its subprocess ever launches
"""
import pytest
from fastapi.testclient import TestClient

from clippyme.api import app as app_module

JOB_ID = "11111111-1111-4111-8111-111111111111"
ORIGIN = {"Origin": "http://localhost:5175"}


class FakeProc:
    def __init__(self, pid=4321, running=True):
        self.pid = pid
        self._running = running
        self.killed = False

    def poll(self):
        return None if self._running else 0

    def kill(self):
        self.killed = True
        self._running = False

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def client(monkeypatch):
    # Neutralise the psutil tree calls — return a fixed count, touch nothing.
    monkeypatch.setattr(app_module.job_control, "suspend_tree", lambda pid: 1)
    monkeypatch.setattr(app_module.job_control, "resume_tree", lambda pid: 1)
    app_module.jobs.pop(JOB_ID, None)
    yield TestClient(app_module.app, headers=ORIGIN)
    app_module.jobs.pop(JOB_ID, None)


def _seed(status="processing", proc=None):
    app_module.jobs[JOB_ID] = {
        "status": status,
        "logs": [],
        "process": proc,
        "output_dir": "",
    }


def test_pause_then_resume(client):
    _seed("processing", FakeProc())
    r = client.post(f"/api/pause/{JOB_ID}")
    assert r.status_code == 200 and r.json()["status"] == "paused"
    assert app_module.jobs[JOB_ID]["status"] == "paused"

    r = client.post(f"/api/resume/{JOB_ID}")
    assert r.status_code == 200 and r.json()["status"] == "processing"
    assert app_module.jobs[JOB_ID]["status"] == "processing"


def test_pause_rejected_when_not_processing(client):
    _seed("completed", FakeProc())
    assert client.post(f"/api/pause/{JOB_ID}").status_code == 400


def test_resume_rejected_when_not_paused(client):
    _seed("processing", FakeProc())
    assert client.post(f"/api/resume/{JOB_ID}").status_code == 400


def test_stop_keeps_finished_clips(client, monkeypatch):
    monkeypatch.setattr(app_module, "load_partial_result", lambda *a, **k: {"clips": [{}, {}]})
    proc = FakeProc()
    _seed("processing", proc)
    r = client.post(f"/api/stop/{JOB_ID}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "stopped" and body["kept_clips"] == 2
    assert app_module.jobs[JOB_ID]["status"] == "stopped"
    assert proc.killed is True  # subprocess was actually killed


def test_stop_queued_job_before_launch(client):
    _seed("queued", None)  # not yet dispatched → no process handle
    r = client.post(f"/api/stop/{JOB_ID}")
    assert r.status_code == 200 and r.json()["status"] == "stopped"
    assert app_module.jobs[JOB_ID]["status"] == "stopped"


def test_controls_404_for_unknown_job(client):
    for ep in ("pause", "resume", "stop"):
        assert client.post(f"/api/{ep}/{JOB_ID}").status_code == 404


def test_controls_400_for_bad_job_id(client):
    assert client.post("/api/pause/not-a-uuid").status_code == 400
