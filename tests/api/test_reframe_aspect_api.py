"""Post-hoc /api/reframe must re-render at the job's ORIGINAL aspect.

Regression guard: the reframe-only subprocess used to omit `--aspect`, so
flipping reframe mode on a 1:1 / 16:9 job silently squashed it back to 9:16.
The job aspect is now persisted in metadata at process time and threaded into
the subprocess argv. We mock the subprocess away and assert the argv.

TestClient is used WITHOUT its context manager so the FastAPI lifespan never
starts. asyncio.create_subprocess_exec is monkeypatched to capture the cmd.
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from clippyme.api import app as app_module

JOB_ID = "33333333-3333-4333-8333-333333333333"
ORIGIN = {"Origin": "http://localhost:5175"}


class _FakeProc:
    returncode = 0

    async def communicate(self):
        return (b"", None)


def _make_client(monkeypatch, tmp_path, *, aspect):
    outputs = tmp_path / "output"
    job_dir = outputs / JOB_ID
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(outputs))

    meta = {"transcript": {"language": "en"}, "shorts": [{"start": 0.0, "end": 5.0}]}
    if aspect is not None:
        meta["aspect"] = aspect
    with open(job_dir / "vid_metadata.json", "w") as f:
        json.dump(meta, f)
    # The 409 guard requires the preserved source slice to exist on disk.
    open(job_dir / "source_vid_clip_1.mp4", "wb").close()
    app_module.jobs[JOB_ID] = {"status": "completed", "result": {"clips": [{}]}}

    captured = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return _FakeProc()

    monkeypatch.setattr(app_module.asyncio, "create_subprocess_exec", fake_exec)
    return TestClient(app_module.app, headers=ORIGIN), captured


def teardown_function():
    app_module.jobs.pop(JOB_ID, None)


@pytest.mark.parametrize("aspect", ["1:1", "16:9", "9:16"])
def test_reframe_passes_job_aspect(monkeypatch, tmp_path, aspect):
    client, captured = _make_client(monkeypatch, tmp_path, aspect=aspect)
    # Post the LEGACY 'object' alias and confirm it is normalized to the
    # canonical 'subject' in the subprocess argv (alias end-to-end).
    r = client.post(f"/api/reframe/{JOB_ID}/0", json={"reframe_mode": "object"})
    assert r.status_code == 200, r.text
    cmd = captured["cmd"]
    assert "--aspect" in cmd, cmd
    assert cmd[cmd.index("--aspect") + 1] == aspect
    assert cmd[cmd.index("--reframe-mode") + 1] == "subject"


def test_reframe_no_aspect_in_metadata_omits_flag(monkeypatch, tmp_path):
    # Legacy job (pre-aspect-persistence): no --aspect → main.py default 9:16.
    client, captured = _make_client(monkeypatch, tmp_path, aspect=None)
    r = client.post(f"/api/reframe/{JOB_ID}/0", json={"reframe_mode": "auto"})
    assert r.status_code == 200, r.text
    assert "--aspect" not in captured["cmd"]


def test_reframe_rejects_tampered_aspect(monkeypatch, tmp_path):
    # A garbage aspect in metadata must NOT reach argv (allow-list guard).
    client, captured = _make_client(monkeypatch, tmp_path, aspect="9:16; rm -rf /")
    r = client.post(f"/api/reframe/{JOB_ID}/0", json={"reframe_mode": "auto"})
    assert r.status_code == 200, r.text
    assert "--aspect" not in captured["cmd"]
