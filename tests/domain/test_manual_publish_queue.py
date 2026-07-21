import json
import io
import os
import stat
import uuid
from pathlib import Path

import pytest

from clippyme.domain.errors import ConflictError, NotFoundError, ValidationError
from clippyme.domain.manual_publish_queue import ManualPublishQueue


JOB_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def queue(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    return ManualPublishQueue(output, tmp_path / "data" / "manual_publish_queue.json")


def _source(queue, name="clip.mp4"):
    path = queue.output_dir / JOB_ID / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    return path


def _enqueue(queue, source=None, **overrides):
    values = {
        "job_id": JOB_ID,
        "clip_index": 0,
        "source_path": source or _source(queue),
        "title": "Title",
        "caption": "Caption",
        "source_platform": "kick",
        "source_channel": "grenbaud",
        "source_kind": "live",
        "project_title": "Stream",
        "monitor_id": "kick:grenbaud",
    }
    values.update(overrides)
    return queue.enqueue(**values)


def test_enqueue_freezes_artifact_and_persists_private_atomic_state(queue):
    entry = _enqueue(queue)

    assert uuid.UUID(entry["id"])
    assert entry["status"] == "pending"
    artifact = queue.output_dir.parent / entry["artifact"]
    assert artifact.read_bytes() == b"video"
    assert artifact == queue.output_dir / JOB_ID / "manual_queue" / f"{entry['id']}.mp4"
    if os.name != "nt":
        assert queue.state_path.stat().st_mode & 0o777 == 0o600
    assert not queue.state_path.with_suffix(queue.state_path.suffix + ".tmp").exists()
    assert json.loads(queue.state_path.read_text(encoding="utf-8"))["entries"][0]["id"] == entry["id"]


def test_enqueue_falls_back_to_copy_when_hardlink_fails(queue, monkeypatch):
    source = _source(queue)

    def fail_link(*_args):
        raise OSError("cross-device")

    monkeypatch.setattr(os, "link", fail_link)
    entry = _enqueue(queue, source)

    artifact = queue.output_dir.parent / entry["artifact"]
    assert artifact.read_bytes() == source.read_bytes()
    assert artifact.stat().st_ino != source.stat().st_ino


def test_complete_and_restore_are_reversible_without_deleting_artifact(queue):
    entry = _enqueue(queue)
    artifact = queue.output_dir.parent / entry["artifact"]

    completed = queue.complete(entry["id"])
    assert completed["status"] == "completed"
    assert completed["completed_at"] is not None
    assert artifact.exists()
    assert queue.list_entries("pending") == []
    assert [item["id"] for item in queue.list_entries("completed")] == [entry["id"]]

    restored = queue.restore(entry["id"])
    assert restored["status"] == "pending"
    assert restored["completed_at"] is None
    assert artifact.exists()


def test_invalid_transition_and_unknown_entry_raise_domain_errors(queue):
    entry = _enqueue(queue)
    with pytest.raises(ConflictError):
        queue.restore(entry["id"])
    queue.complete(entry["id"])
    with pytest.raises(ConflictError):
        queue.complete(entry["id"])
    with pytest.raises(NotFoundError):
        queue.complete(str(uuid.uuid4()))


def test_missing_artifacts_are_excluded_and_cannot_be_resolved(queue):
    entry = _enqueue(queue)
    (queue.output_dir.parent / entry["artifact"]).unlink()

    assert queue.list_entries("all") == []
    with pytest.raises(NotFoundError):
        queue.resolve_video(entry["id"])


@pytest.mark.parametrize("status", ["", "other", None])
def test_list_rejects_unknown_status(queue, status):
    with pytest.raises(ValidationError):
        queue.list_entries(status)


@pytest.mark.parametrize(
    "job_id,source_factory",
    [
        ("../escape", lambda queue: _source(queue)),
        (JOB_ID, lambda queue: queue.output_dir.parent / "outside.mp4"),
    ],
)
def test_enqueue_rejects_traversal_and_sources_outside_output(queue, job_id, source_factory):
    source = source_factory(queue)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.touch(exist_ok=True)
    with pytest.raises(ValidationError):
        _enqueue(queue, source, job_id=job_id)


def test_tampered_artifact_path_rejects_persisted_state(queue):
    entry = _enqueue(queue)
    state = json.loads(queue.state_path.read_text(encoding="utf-8"))
    state["entries"][0]["artifact"] = "../outside.mp4"
    queue.state_path.write_text(json.dumps(state), encoding="utf-8")

    reloaded = ManualPublishQueue(queue.output_dir, queue.state_path)
    with pytest.raises(ValidationError):
        reloaded.list_entries("all")
    with pytest.raises(ValidationError):
        reloaded.resolve_video(entry["id"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "arbitrary"),
        ("status", None),
        ("id", "not-a-uuid"),
        ("job_id", "../escape"),
        ("clip_index", -1),
        ("title", None),
        ("completed_at", "unexpected"),
    ],
)
def test_malformed_persisted_entry_is_never_exposed_by_all(queue, field, value):
    _enqueue(queue)
    state = json.loads(queue.state_path.read_text(encoding="utf-8"))
    state["entries"][0][field] = value
    queue.state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(ValidationError):
        queue.list_entries("all")


def test_resolve_video_returns_an_open_regular_file_handle(queue):
    entry = _enqueue(queue)

    with queue.resolve_video(entry["id"]) as stream:
        assert isinstance(stream, io.BufferedReader)
        assert stat.S_ISREG(os.fstat(stream.fileno()).st_mode)
        assert stream.read() == b"video"
    assert stream.closed


def test_open_video_descriptor_remains_bound_if_path_is_replaced(queue):
    entry = _enqueue(queue)
    artifact = queue.output_dir.parent / entry["artifact"]
    stream = queue.resolve_video(entry["id"])
    try:
        if os.name == "nt":
            pytest.skip("Windows prevents replacing an open artifact")
        artifact.unlink()
        artifact.write_bytes(b"replacement")
        assert stream.read() == b"video"
    finally:
        stream.close()


def test_remove_clip_and_job_remove_records_but_not_history_sources(queue):
    first_source = _source(queue, "first.mp4")
    first = _enqueue(queue, first_source, clip_index=0)
    second_source = _source(queue, "second.mp4")
    second = _enqueue(queue, second_source, clip_index=1)

    queue.remove_clip(JOB_ID, 0)
    assert first_source.exists()
    assert not (queue.output_dir.parent / first["artifact"]).exists()
    assert [item["id"] for item in queue.list_entries("all")] == [second["id"]]

    queue.remove_job(JOB_ID)
    assert second_source.exists()
    assert not (queue.output_dir.parent / second["artifact"]).exists()
    assert queue.list_entries("all") == []


def test_remove_is_idempotent_after_success(queue):
    _enqueue(queue)

    assert queue.remove_clip(JOB_ID, 0) == 1
    assert queue.remove_clip(JOB_ID, 0) == 0
    assert queue.remove_job(JOB_ID) == 0


def test_unlink_failure_keeps_state_retriable(queue, monkeypatch):
    entry = _enqueue(queue)
    artifact = queue.output_dir.parent / entry["artifact"]
    real_unlink = Path.unlink

    def fail_artifact_unlink(path, *args, **kwargs):
        if path == artifact:
            raise PermissionError("active reader")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_artifact_unlink)
    with pytest.raises(ConflictError):
        queue.remove_clip(JOB_ID, 0)

    assert [item["id"] for item in queue.list_entries("all")] == [entry["id"]]
    monkeypatch.setattr(Path, "unlink", real_unlink)
    assert queue.remove_clip(JOB_ID, 0) == 1
    assert queue.remove_clip(JOB_ID, 0) == 0
