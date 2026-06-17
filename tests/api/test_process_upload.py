"""Tests for the /api/process upload size-limit path in clippyme.api.app.

We drive the endpoint with Starlette's TestClient *without* entering its
context manager, so the FastAPI lifespan (job workers, the auto-editor
updater that needs `fcntl`, background network loops) never starts. The
oversize-reject branch raises before any job-queue interaction, so this is
safe and host-runnable.

What we pin down: an oversize upload must return HTTP 413 and must not leave
the uploaded file or the per-job output dir orphaned on disk — even if one of
the two cleanup calls fails.
"""
import os

import pytest
from fastapi.testclient import TestClient

from clippyme.api import app as app_module


@pytest.fixture
def client(monkeypatch, tmp_path):
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "output"
    uploads.mkdir()
    outputs.mkdir()
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(uploads))
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(outputs))
    monkeypatch.setattr(app_module, "MAX_FILE_SIZE_MB", 0)  # any byte trips the limit
    # /api/process now enforces the trusted-origin gate (CSRF defence); send a
    # default allow-listed Origin so the TestClient is treated like the browser.
    return (
        TestClient(app_module.app, headers={"Origin": "http://localhost:5175"}),
        uploads,
        outputs,
    )


def test_oversize_upload_returns_413_and_cleans_up(client):
    tc, uploads, outputs = client
    resp = tc.post(
        "/api/process",
        headers={"X-Gemini-Key": "k"},
        files={"file": ("v.mp4", b"hello world", "video/mp4")},
    )
    assert resp.status_code == 413
    # No orphaned upload file, no orphaned job output dir.
    assert os.listdir(uploads) == []
    assert os.listdir(outputs) == []


def test_oversize_upload_still_413_when_file_remove_fails(client, monkeypatch):
    tc, uploads, outputs = client

    def boom(*a, **k):
        raise OSError("simulated os.remove failure")

    monkeypatch.setattr(app_module.os, "remove", boom)
    resp = tc.post(
        "/api/process",
        headers={"X-Gemini-Key": "k"},
        files={"file": ("v.mp4", b"hello world", "video/mp4")},
    )
    # A failure removing the upload file must not mask the 413, and the job
    # output dir must still be cleaned up.
    assert resp.status_code == 413
    assert os.listdir(outputs) == []
