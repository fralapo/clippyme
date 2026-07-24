"""Host tests for clippyme.domain.job_journal — persistence + restart recovery."""
import asyncio
import json
import os

from clippyme.domain import job_journal as jj

JOB_Q = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
JOB_P = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
JOB_DONE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


# --- snapshot ----------------------------------------------------------------

def test_snapshot_keeps_only_active_jobs_and_no_secrets():
    jobs = {
        JOB_Q: {"status": "queued", "cmd": ["python", "-m", "x"], "env": {"GEMINI_API_KEY": "sk-secret"},
                "output_dir": "/out/q", "input_path": "/uploads/q.mp4",
                "logs": ["a"], "process": object(), "pid": 123},
        JOB_DONE: {"status": "completed", "cmd": [], "output_dir": "/out/d"},
        "failed-job": {"status": "failed", "cmd": [], "output_dir": "/out/f"},
    }
    records = jj.snapshot(jobs)
    assert set(records) == {JOB_Q}
    rec = records[JOB_Q]
    assert rec["status"] == "queued" and rec["pid"] == 123
    assert rec["input_path"] == "/uploads/q.mp4"
    serialized = json.dumps(records)
    assert "sk-secret" not in serialized
    assert "env" not in rec and "process" not in rec and "logs" not in rec


# --- save / load roundtrip ---------------------------------------------------

def test_roundtrip_and_corrupt_file(tmp_path):
    path = str(tmp_path / "jobs_journal.json")
    records = {JOB_Q: {"status": "queued", "cmd": ["x"], "output_dir": "o", "pid": None}}
    jj.save_journal(path, records)
    loaded = jj.load_journal(path)
    assert loaded[JOB_Q]["status"] == "queued"

    with open(path, "w") as f:
        f.write("{not json")
    assert jj.load_journal(path) == {}
    assert jj.load_journal(str(tmp_path / "missing.json")) == {}


def test_journal_writer_never_raises(tmp_path):
    # Point the writer at an unwritable path — it must swallow the error.
    persist = jj.make_journal_writer(jobs={}, path=str(tmp_path / "nodir" / "j.json"))
    persist()  # no exception


# --- plan_recovery (pure) ----------------------------------------------------

def test_plan_recovery_classification():
    plan = jj.plan_recovery({
        JOB_Q: {"status": "queued"},
        JOB_P: {"status": "processing"},
        "paused": {"status": "paused"},
        "done": {"status": "completed"},
        "junk": None,
    })
    assert [j for j, _ in plan.requeue] == [JOB_Q]
    assert sorted(j for j, _ in plan.mark_failed) == [JOB_P, "paused"]


# --- kill_stale_tree ---------------------------------------------------------

def test_kill_stale_tree_refuses_on_cmd_mismatch(monkeypatch):
    class FakeProc:
        def __init__(self, pid):
            self.killed = False

        def cmdline(self):
            return ["/usr/bin/someone-elses-process", "arg"]

        def children(self, recursive=True):
            return []

        def kill(self):
            self.killed = True

    import psutil
    monkeypatch.setattr(psutil, "Process", FakeProc)
    assert jj.kill_stale_tree(4321, ["python", "-m", "clippyme.pipeline.main"]) is False


def test_kill_stale_tree_kills_on_match(monkeypatch):
    killed = []

    class FakeProc:
        def __init__(self, pid):
            pass

        def cmdline(self):
            return ["python", "-m", "clippyme.pipeline.main", "url"]

    import psutil
    monkeypatch.setattr(psutil, "Process", FakeProc)
    monkeypatch.setattr(jj, "terminate_tree", lambda pid, timeout=5: killed.append((pid, timeout)) or 1)
    assert jj.kill_stale_tree(
        4321, ["python", "-m", "clippyme.pipeline.main", "url"]
    ) is True
    assert killed == [(4321, 5.0)]


def test_kill_stale_tree_refuses_partial_command_match(monkeypatch):
    class FakeProc:
        def __init__(self, pid):
            pass

        def cmdline(self):
            return ["python", "-m", "unrelated.module", "--dangerous"]

    import psutil
    monkeypatch.setattr(psutil, "Process", FakeProc)
    assert jj.kill_stale_tree(4321, ["python", "-m", "clippyme.pipeline.main"]) is False


def test_kill_stale_tree_no_pid_is_noop():
    assert jj.kill_stale_tree(None, ["python"]) is False


# --- recover_jobs (end to end against tmp_path) -------------------------------

def _recover(tmp_path, journal_records, monkeypatch=None, final_result=None):
    journal = str(tmp_path / "jobs_journal.json")
    jj.save_journal(journal, journal_records)
    jobs, q = {}, asyncio.Queue(maxsize=10)
    counts = jj.recover_jobs(journal_path=journal, jobs=jobs,
                             job_queue=q, output_root=str(tmp_path))
    return jobs, q, counts, journal


def test_recover_requeues_queued_jobs(tmp_path):
    out = tmp_path / JOB_Q
    out.mkdir()
    jobs, q, counts, _ = _recover(tmp_path, {
        JOB_Q: {"status": "queued", "cmd": ["python", "-m", "x"], "output_dir": str(out), "pid": None},
    })
    assert counts == {"requeued": 1, "failed": 0, "restored": 0}
    assert jobs[JOB_Q]["status"] == "queued"
    assert "Re-enqueued after server restart." in jobs[JOB_Q]["logs"]
    assert q.get_nowait() == JOB_Q
    # env is rebuilt from the process environment, never from the journal
    assert isinstance(jobs[JOB_Q]["env"], dict)


def test_recover_fails_interrupted_job_and_kills_orphan(tmp_path, monkeypatch):
    killed = {}
    monkeypatch.setattr(jj, "kill_stale_tree", lambda pid, cmd: killed.setdefault("args", (pid, cmd)) or True)
    out = tmp_path / JOB_P
    out.mkdir()
    jobs, q, counts, _ = _recover(tmp_path, {
        JOB_P: {"status": "processing", "cmd": ["python"], "output_dir": str(out), "pid": 777},
    })
    assert counts["failed"] == 1
    assert jobs[JOB_P]["status"] == "failed"
    assert "Job interrupted by server restart." in jobs[JOB_P]["logs"]
    assert killed["args"] == (777, ["python"])
    assert q.qsize() == 0


def test_recover_restores_completed_on_disk_instead_of_failing(tmp_path):
    # Simulate a job killed AFTER its final render landed: metadata + clip on disk.
    out = tmp_path / JOB_P
    out.mkdir()
    meta = {"shorts": [{"video_url": f"/videos/{JOB_P}/done_clip_1.mp4",
                        "start": 0, "end": 5}]}
    with open(out / "done_metadata.json", "w") as f:
        json.dump(meta, f)
    (out / "done_clip_1.mp4").write_bytes(b"\x00")
    jobs, q, counts, _ = _recover(tmp_path, {
        JOB_P: {"status": "processing", "cmd": ["python"], "output_dir": str(out), "pid": None},
    })
    assert counts["restored"] == 1 and counts["failed"] == 0
    assert jobs[JOB_P]["status"] == "completed"
    assert len(jobs[JOB_P]["result"]["clips"]) == 1


def test_recover_rewrites_journal_after_classification(tmp_path):
    out = tmp_path / JOB_P
    out.mkdir()
    jobs, q, counts, journal = _recover(tmp_path, {
        JOB_P: {"status": "processing", "cmd": [], "output_dir": str(out), "pid": None},
    })
    # The failed job is terminal → pruned from the rewritten journal.
    assert jj.load_journal(journal) == {}


def test_recover_empty_journal_is_noop(tmp_path):
    jobs, q, counts, _ = _recover(tmp_path, {})
    assert counts == {"requeued": 0, "failed": 0, "restored": 0}
    assert jobs == {} and q.qsize() == 0
