import os

from clippyme.domain.runtime_state import (
    RuntimeState,
    format_runtime_log,
    is_resumable,
    load_runtime_state,
    runtime_result_fields,
    upsert_runtime_log,
)


def test_runtime_state_roundtrip_and_stage_checkpoint(tmp_path):
    state = RuntimeState(str(tmp_path), job_id="job-1")
    state.begin_attempt(2, 3)
    state.start("transcribing", "speech to text", progress=31)
    state.complete_stage("transcribing", artifacts={"transcript": "hidden.json"})
    state.set_clip_total(2)
    state.mark_clip(0, "ready", {"ok": True})

    loaded = load_runtime_state(str(tmp_path))
    assert loaded["job_id"] == "job-1"
    assert loaded["attempt"] == 2
    assert loaded["stage"] == "transcribing"
    assert "transcribing" in loaded["completed_stages"]
    assert loaded["clips"] == {"ready": 1, "total": 2, "failed": 0}
    assert loaded["qa"]["ok"] == 1
    assert os.path.exists(tmp_path / ".clippyme_runtime.json")


def test_mark_clip_is_idempotent_when_replacing_status(tmp_path):
    state = RuntimeState(str(tmp_path))
    state.set_clip_total(1)
    state.mark_clip(0, "failed", {"critical": True})
    state.mark_clip(0, "warning", {"warnings": ["quiet"]})
    assert state.data["clips"]["ready"] == 1
    assert state.data["clips"]["failed"] == 0
    assert state.data["qa"]["warnings"] == 1
    assert state.data["qa"]["failed"] == 0


def test_runtime_fields_do_not_expose_artifact_paths(tmp_path):
    state = RuntimeState(str(tmp_path))
    state.complete_stage("acquiring", artifacts={"input_video": "/secret/source.mp4"})
    public = runtime_result_fields(str(tmp_path))["operations"]
    assert "artifacts" not in public
    assert "/secret/source.mp4" not in repr(public)


def test_resume_requires_checkpoint_and_recoverable_source(tmp_path):
    upload = tmp_path / "upload.mp4"
    upload.write_bytes(b"video")
    state = RuntimeState(str(tmp_path / "out"))
    state.start("transcribing")

    assert is_resumable(str(tmp_path / "out"), input_path=str(upload), cmd=["python"])
    upload.unlink()
    assert not is_resumable(str(tmp_path / "out"), input_path=str(upload), cmd=["python"])

    url_cmd = [
        "python", "-u", "-m", "clippyme.pipeline.orchestrator",
        "-u", "https://youtu.be/example", "-o", str(tmp_path / "out"),
    ]
    assert is_resumable(str(tmp_path / "out"), cmd=url_cmd)
    assert not is_resumable(
        str(tmp_path / "out"),
        cmd=["python", "-u", "-m", "clippyme.pipeline.main", "-i", "missing.mp4"],
    )


def test_runtime_log_upsert_keeps_one_live_row(tmp_path):
    state = RuntimeState(str(tmp_path))
    state.begin_attempt(1, 3)
    state.set_clip_total(4)
    line = format_runtime_log(state.snapshot(), {"cpu": 12.5, "rss_mb": 100.0})
    logs = ["started"]
    upsert_runtime_log(logs, line)
    upsert_runtime_log(logs, line.replace("cpu=12.5", "cpu=20.0"))
    assert len([item for item in logs if item.startswith("[runtime]")]) == 1
    assert "cpu=20.0" in logs[-1]
