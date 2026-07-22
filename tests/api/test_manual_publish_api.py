from fastapi.testclient import TestClient
import io
import pytest

from clippyme.api import app as app_module
from clippyme.domain.manual_publish_queue import ManualPublishQueue


JOB_ID = "22222222-2222-4222-8222-222222222222"
ORIGIN = {"Origin": "http://localhost:5175"}


@pytest.fixture
def client_and_entry(monkeypatch, tmp_path):
    output = tmp_path / "output"
    source = output / JOB_ID / "clip.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"mp4-data")
    queue = ManualPublishQueue(output, tmp_path / "data" / "manual_publish_queue.json")
    entry = queue.enqueue(
        job_id=JOB_ID,
        clip_index=0,
        source_path=source,
        title="Title",
        caption="Caption",
        source_platform="kick",
        source_channel="grenbaud",
        source_kind="live",
        project_title="Stream",
    )
    monkeypatch.setattr(app_module, "manual_publish_queue", queue)
    return TestClient(app_module.app, headers=ORIGIN), entry


def test_list_complete_restore_and_video(client_and_entry):
    client, entry = client_and_entry

    response = client.get("/api/manual-publish")
    assert response.status_code == 200
    assert response.json()["entries"][0]["id"] == entry["id"]

    response = client.post(f"/api/manual-publish/{entry['id']}/complete")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert client.get("/api/manual-publish?status=pending").json() == {"entries": []}

    response = client.post(f"/api/manual-publish/{entry['id']}/restore")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"

    response = client.get(f"/api/manual-publish/{entry['id']}/video")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.content == b"mp4-data"


def test_invalid_status_is_rejected(client_and_entry):
    client, _entry = client_and_entry
    assert client.get("/api/manual-publish?status=broken").status_code == 422


def test_queue_routes_require_trusted_request(client_and_entry):
    _client, entry = client_and_entry
    untrusted = TestClient(app_module.app, headers={"Origin": "https://evil.example"})
    assert untrusted.get("/api/manual-publish").status_code == 403
    assert untrusted.post(f"/api/manual-publish/{entry['id']}/complete").status_code == 403
    assert untrusted.get(f"/api/manual-publish/{entry['id']}/video").status_code == 403


def test_video_no_range_returns_full_200(client_and_entry):
    client, entry = client_and_entry
    response = client.get(f"/api/manual-publish/{entry['id']}/video")
    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == "8"
    assert response.content == b"mp4-data"


def test_video_ranged_request_returns_206_slice(client_and_entry):
    client, entry = client_and_entry
    response = client.get(
        f"/api/manual-publish/{entry['id']}/video", headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.content == b"mp4-"
    assert response.headers["content-range"] == "bytes 0-3/8"
    assert response.headers["content-length"] == "4"
    assert response.headers["accept-ranges"] == "bytes"


def test_video_open_ended_range(client_and_entry):
    client, entry = client_and_entry
    response = client.get(
        f"/api/manual-publish/{entry['id']}/video", headers={"Range": "bytes=4-"})
    assert response.status_code == 206
    assert response.content == b"data"
    assert response.headers["content-range"] == "bytes 4-7/8"


def test_video_suffix_range(client_and_entry):
    client, entry = client_and_entry
    response = client.get(
        f"/api/manual-publish/{entry['id']}/video", headers={"Range": "bytes=-4"})
    assert response.status_code == 206
    assert response.content == b"data"
    assert response.headers["content-range"] == "bytes 4-7/8"


def test_video_end_clamped_to_size(client_and_entry):
    client, entry = client_and_entry
    response = client.get(
        f"/api/manual-publish/{entry['id']}/video", headers={"Range": "bytes=2-999"})
    assert response.status_code == 206
    assert response.content == b"4-data"
    assert response.headers["content-range"] == "bytes 2-7/8"


def test_video_invalid_range_returns_416(client_and_entry):
    client, entry = client_and_entry
    for bad in ("bytes=8-", "bytes=5-2", "bytes=-0", "bytes=abc", "bytes=0-1,4-5"):
        response = client.get(
            f"/api/manual-publish/{entry['id']}/video", headers={"Range": bad})
        assert response.status_code == 416, bad
        assert response.headers["content-range"] == "bytes */8"


def test_video_exempt_from_api_token_gate(client_and_entry, monkeypatch):
    """<video src>/download anchors can't send X-API-Token — the media route
    stays off the token gate (like /videos) while every other queue route
    still requires the token."""
    client, entry = client_and_entry
    monkeypatch.setenv("CLIPPYME_API_TOKEN", "s3cret")
    assert client.get("/api/manual-publish").status_code == 401
    assert client.post(f"/api/manual-publish/{entry['id']}/complete").status_code == 401
    response = client.get(f"/api/manual-publish/{entry['id']}/video")
    assert response.status_code == 200
    assert response.content == b"mp4-data"


def test_video_stream_closes_queue_opened_handle(client_and_entry, monkeypatch):
    client, entry = client_and_entry
    stream = io.BytesIO(b"streamed")

    def open_video(entry_id):
        assert entry_id == entry["id"]
        return stream

    monkeypatch.setattr(app_module.manual_publish_queue, "open_video", open_video)
    monkeypatch.setattr(
        app_module.manual_publish_queue,
        "resolve_video",
        lambda _entry_id: pytest.fail("API must not resolve and reopen a path"),
    )
    response = client.get(f"/api/manual-publish/{entry['id']}/video")

    assert response.status_code == 200
    assert response.content == b"streamed"
    assert stream.closed
