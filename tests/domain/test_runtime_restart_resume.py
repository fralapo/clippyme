import asyncio
import json

from clippyme.domain import job_journal
from clippyme.domain.runtime_state import RuntimeState


JOB_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


def test_partial_metadata_is_resumed_not_restored(tmp_path, monkeypatch):
    output = tmp_path / JOB_ID
    output.mkdir()
    (output / "video_metadata.json").write_text(
        json.dumps({"shorts": [{"start": 0, "end": 5, "clip_filename": "clip.mp4"}]}),
        encoding="utf-8",
    )
    (output / "clip.mp4").write_bytes(b"partial output")
    runtime = RuntimeState(str(output), job_id=JOB_ID)
    runtime.start("reframing", "rendering first clip", progress=75)

    command = [
        "python", "-u", "-m", "clippyme.pipeline.orchestrator",
        "-u", "https://youtu.be/example", "-o", str(output),
    ]
    journal = tmp_path / "jobs_journal.json"
    job_journal.save_journal(str(journal), {
        JOB_ID: {
            "status": "processing",
            "cmd": command,
            "output_dir": str(output),
            "pid": 123,
            "attempt": 1,
            "max_attempts": 3,
        },
    })
    monkeypatch.setattr(job_journal, "kill_stale_tree", lambda *args, **kwargs: True)

    jobs = {}
    queue = asyncio.Queue(maxsize=2)
    counts = job_journal.recover_jobs(
        journal_path=str(journal),
        jobs=jobs,
        job_queue=queue,
        output_root=str(tmp_path),
    )

    assert counts == {"requeued": 0, "resumed": 1, "failed": 0, "restored": 0}
    assert jobs[JOB_ID]["status"] == "queued"
    assert jobs[JOB_ID]["result"]["operations"]["stage"] == "reframing"
    assert queue.get_nowait() == JOB_ID


def test_completed_runtime_allows_disk_restore(tmp_path):
    output = tmp_path / JOB_ID
    output.mkdir()
    (output / "video_metadata.json").write_text(
        json.dumps({"shorts": [{"start": 0, "end": 5}]}),
        encoding="utf-8",
    )
    (output / "video_clip_1.mp4").write_bytes(b"finished")
    runtime = RuntimeState(str(output), job_id=JOB_ID)
    runtime.finish()

    journal = tmp_path / "jobs_journal.json"
    job_journal.save_journal(str(journal), {
        JOB_ID: {
            "status": "processing",
            "cmd": ["python"],
            "output_dir": str(output),
            "pid": None,
        },
    })
    jobs = {}
    queue = asyncio.Queue(maxsize=2)
    counts = job_journal.recover_jobs(
        journal_path=str(journal),
        jobs=jobs,
        job_queue=queue,
        output_root=str(tmp_path),
    )
    assert counts["restored"] == 1
    assert jobs[JOB_ID]["status"] == "completed"
