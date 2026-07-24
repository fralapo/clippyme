"""Host tests for job journal persistence and restart recovery."""
import asyncio
import json

from clippyme.domain import job_journal as jj
from clippyme.domain.runtime_state import RuntimeState

JOB_Q = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
JOB_P = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
JOB_DONE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
EMPTY_COUNTS = {"requeued": 0, "resumed": 0, "failed": 0, "restored": 0}


def test_snapshot_keeps_only_active_jobs_and_no_secrets():
    jobs = {
        JOB_Q: {
            "status": "queued", "cmd": ["python", "-m", "x"],
            "env": {"GEMINI_API_KEY": "sk-secret"}, "output_dir": "/out/q",
            "input_path": "/uploads/q.mp4", "logs": ["a"],
            "process": object(), "pid": 123, "attempt": 1, "max_attempts": 3,
        },
        JOB_DONE: {"status": "completed", "cmd": [], "output_dir": "/out/d"},
        "failed-job": {"status": "failed", "cmd": [], "output_dir": "/out/f"},
    }
    records = jj.snapshot(jobs)
    assert set(records) == {JOB_Q}
    record = records[JOB_Q]
    assert record["status"] == "queued" and record["pid"] == 123
    assert record["input_path"] == "/uploads/q.mp4"
    assert record["attempt"] == 1 and record["max_attempts"] == 3
    serialized = json.dumps(records)
    assert "sk-secret" not in serialized
    assert "env" not in record and "process" not in record and "logs" not in record


def test_roundtrip_and_corrupt_file(tmp_path):
    path = str(tmp_path / "jobs_journal.json")
    records = {JOB_Q: {"status": "queued", "cmd": ["x"], "output_dir": "o", "pid": None}}
    jj.save_journal(path, records)
    assert jj.load_journal(path)[JOB_Q]["status"] == "queued"
    (tmp_path / "jobs_journal.json").write_text("{not json")
    assert jj.load_journal(path) == {}
    assert jj.load_journal(str(tmp_path / "missing.json")) == {}


def test_journal_writer_never_raises(tmp_path):
    persist = jj.make_journal_writer(jobs={}, path=str(tmp_path / "nodir" / "j.json"))
    persist()


def test_plan_recovery_classification():
    plan = jj.plan_recovery({
        JOB_Q: {"status": "queued"},
        JOB_P: {"status": "processing"},
        "paused": {"status": "paused"},
        "done": {"status": "completed"},
        "junk": None,
    })
    assert [job_id for job_id, _ in plan.requeue] == [JOB_Q]
    assert sorted(job_id for job_id, _ in plan.mark_failed) == [JOB_P, "paused"]


def test_kill_stale_tree_refuses_on_cmd_mismatch(monkeypatch):
    class FakeProc:
        def __init__(self, pid):
            self.pid = pid

        def cmdline(self):
            return ["/usr/bin/someone-elses-process", "arg"]

    import psutil
    monkeypatch.setattr(psutil, "Process", FakeProc)
    assert jj.kill_stale_tree(4321, ["python", "-m", "clippyme.pipeline.orchestrator"]) is False


def test_kill_stale_tree_kills_on_match(monkeypatch):
    killed = []

    class FakeProc:
        def __init__(self, pid):
            self.pid = pid

        def cmdline(self):
            return ["python", "-m", "clippyme.pipeline.orchestrator", "url"]

    import psutil
    monkeypatch.setattr(psutil, "Process", FakeProc)
    monkeypatch.setattr(jj, "terminate_tree", lambda pid, timeout=5: killed.append((pid, timeout)) or 1)
    assert jj.kill_stale_tree(
        4321, ["python", "-m", "clippyme.pipeline.orchestrator", "url"]
    ) is True
    assert killed == [(4321, 5.0)]


def test_kill_stale_tree_refuses_partial_command_match(monkeypatch):
    class FakeProc:
        def __init__(self, pid):
            self.pid = pid

        def cmdline(self):
            return ["python", "-m", "unrelated.module", "--dangerous"]

    import psutil
    monkeypatch.setattr(psutil, "Process", FakeProc)
    assert jj.kill_stale_tree(4321, ["python", "-m", "clippyme.pipeline.orchestrator"]) is False


def test_kill_stale_tree_no_pid_is_noop():
    assert jj.kill_stale_tree(None, ["python"]) is False


def _recover(tmp_path, journal_records):
    journal = str(tmp_path / "jobs_journal.json")
    jj.save_journal(journal, journal_records)
    jobs, queue = {}, asyncio.Queue(maxsize=10)
    counts = jj.recover_jobs(
        journal_path=journal, jobs=jobs, job_queue=queue, output_root=str(tmp_path),
    )
    return jobs, queue, counts, journal


def test_recover_requeues_queued_jobs(tmp_path):
    output = tmp_path / JOB_Q
    output.mkdir()
    jobs, queue, counts, _ = _recover(tmp_path, {
        JOB_Q: {
            "status": "queued", "cmd": ["python", "-m", "x"],
            "output_dir": str(output), "pid": None,
        },
    })
    assert counts == {**EMPTY_COUNTS, "requeued": 1}
    assert jobs[JOB_Q]["status"] == "queued"
    assert "Re-enqueued after server restart." in jobs[JOB_Q]["logs"]
    assert queue.get_nowait() == JOB_Q
    assert isinstance(jobs[JOB_Q]["env"], dict)


def test_recover_fails_legacy_interrupted_job_and_kills_orphan(tmp_path, monkeypatch):
    killed = {}
    monkeypatch.setattr(jj, "kill_stale_tree", lambda pid, cmd: killed.setdefault("args", (pid, cmd)) or True)
    output = tmp_path / JOB_P
    output.mkdir()
    jobs, queue, counts, _ = _recover(tmp_path, {
        JOB_P: {"status": "processing", "cmd": ["python"], "output_dir": str(output), "pid": 777},
    })
    assert counts["failed"] == 1 and counts["resumed"] == 0
    assert jobs[JOB_P]["status"] == "failed"
    assert "Job interrupted by server restart." in jobs[JOB_P]["logs"]
    assert killed["args"] == (777, ["python"])
    assert queue.qsize() == 0


def test_recover_resumes_checkpointed_url_job(tmp_path, monkeypatch):
    monkeypatch.setattr(jj, "kill_stale_tree", lambda pid, cmd: True)
    output = tmp_path / JOB_P
    output.mkdir()
    runtime = RuntimeState(str(output), job_id=JOB_P)
    runtime.start("transcribing")
    command = [
        "python", "-u", "-m", "clippyme.pipeline.orchestrator",
        "-u", "https://youtu.be/example", "-o", str(output),
    ]
    jobs, queue, counts, _ = _recover(tmp_path, {
        JOB_P: {
            "status": "processing", "cmd": command, "output_dir": str(output),
            "pid": 777, "attempt": 1, "max_attempts": 3,
        },
    })
    assert counts["resumed"] == 1 and counts["failed"] == 0
    assert jobs[JOB_P]["status"] == "queued"
    assert "resuming" in jobs[JOB_P]["logs"][0].lower()
    assert queue.get_nowait() == JOB_P
    assert jobs[JOB_P]["result"]["operations"]["stage"] == "transcribing"


def test_recover_restores_completed_on_disk_instead_of_resuming(tmp_path):
    output = tmp_path / JOB_P
    output.mkdir()
    metadata = {"shorts": [{"start": 0, "end": 5}]}
    (output / "done_metadata.json").write_text(json.dumps(metadata))
    (output / "done_clip_1.mp4").write_bytes(b"\x00")
    jobs, queue, counts, _ = _recover(tmp_path, {
        JOB_P: {"status": "processing", "cmd": ["python"], "output_dir": str(output), "pid": None},
    })
    assert counts["restored"] == 1 and counts["failed"] == 0
    assert jobs[JOB_P]["status"] == "completed"
    assert len(jobs[JOB_P]["result"]["clips"]) == 1
    assert queue.qsize() == 0


def test_recover_rewrites_journal_after_classification(tmp_path):
    output = tmp_path / JOB_P
    output.mkdir()
    _, _, _, journal = _recover(tmp_path, {
        JOB_P: {"status": "processing", "cmd": [], "output_dir": str(output), "pid": None},
    })
    assert jj.load_journal(journal) == {}


def test_recover_empty_journal_is_noop(tmp_path):
    jobs, queue, counts, _ = _recover(tmp_path, {})
    assert counts == EMPTY_COUNTS
    assert jobs == {} and queue.qsize() == 0
