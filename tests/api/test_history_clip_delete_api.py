import json

from fastapi.testclient import TestClient

from clippyme.api import app as app_module
from clippyme.domain.manual_publish_queue import ManualPublishQueue


JOB_ID = "33333333-3333-4333-8333-333333333333"
ORIGIN = {"Origin": "http://localhost:5175"}


def _client(monkeypatch, tmp_path):
    output = tmp_path / "output"
    job_dir = output / JOB_ID
    job_dir.mkdir(parents=True)
    (job_dir / "video_metadata.json").write_text(
        json.dumps({"shorts": [{"video_url": f"/videos/{JOB_ID}/video_clip_1.mp4"}]}),
        encoding="utf-8",
    )
    (job_dir / "video_clip_1.mp4").write_bytes(b"clip")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(output))
    monkeypatch.setattr(
        app_module, "manual_publish_queue",
        ManualPublishQueue(output, tmp_path / "data" / "manual_publish_queue.json"),
    )
    return TestClient(app_module.app, headers=ORIGIN)


def test_delete_history_clip_endpoint(monkeypatch, tmp_path):
    response = _client(monkeypatch, tmp_path).delete(f"/api/history/{JOB_ID}/clips/0")
    assert response.status_code == 200
    assert response.json() == {"project_deleted": True, "remaining": 0}


def test_delete_history_clip_endpoint_validates_and_requires_trusted_origin(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    assert client.delete(f"/api/history/{JOB_ID}/clips/-1").status_code == 400
    untrusted = TestClient(app_module.app, headers={"Origin": "https://evil.example"})
    assert untrusted.delete(f"/api/history/{JOB_ID}/clips/0").status_code == 403


def test_delete_whole_history_project_removes_manual_queue_records_first(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    calls = []
    real_remove_job = app_module.manual_publish_queue.remove_job

    def remove_job(job_id):
        calls.append(("queue", job_id))
        return real_remove_job(job_id)

    monkeypatch.setattr(app_module.manual_publish_queue, "remove_job", remove_job)
    response = client.delete(f"/api/history/{JOB_ID}")

    assert response.status_code == 200
    assert calls == [("queue", JOB_ID)]
