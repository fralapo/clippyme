import asyncio
import io

import pytest

from clippyme.domain import job_runner
from clippyme.domain.job_submission import configured_max_attempts


def test_configured_max_attempts_is_bounded_and_tolerant():
    assert configured_max_attempts({}) == 3
    assert configured_max_attempts({"CLIPPYME_JOB_MAX_ATTEMPTS": "bad"}) == 3
    assert configured_max_attempts({"CLIPPYME_JOB_MAX_ATTEMPTS": "0"}) == 1
    assert configured_max_attempts({"CLIPPYME_JOB_MAX_ATTEMPTS": "999"}) == 10


class _FinishedProcess:
    next_pid = 100

    def __init__(self, returncode):
        self.returncode = returncode
        self.pid = _FinishedProcess.next_pid
        _FinishedProcess.next_pid += 1
        self.stdout = io.BytesIO(b"")

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        return None


def _patch_runner_dependencies(monkeypatch, module):
    monkeypatch.setattr(module, "load_persistent_config", lambda: {})
    monkeypatch.setattr(module, "load_partial_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "load_final_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "load_runtime_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "collect_runtime_metrics", lambda *args, **kwargs: {})
    monkeypatch.setattr(module, "runtime_result_fields", lambda *args, **kwargs: {})
    monkeypatch.setattr(module, "relocate_root_job_artifacts", lambda *args, **kwargs: None)
    # Keep Python's real Thread implementation. Replacing threading.Thread on
    # the shared module also replaces the implementation used by
    # asyncio.to_thread's executor, which deadlocks before the worker starts.
    monkeypatch.setattr(module, "enqueue_output", lambda *args, **kwargs: None)


def test_transient_failure_retries_to_limit(monkeypatch, tmp_path):
    _patch_runner_dependencies(monkeypatch, job_runner)
    calls = []

    def popen(*args, **kwargs):
        calls.append(kwargs["env"]["CLIPPYME_ATTEMPT"])
        return _FinishedProcess(1)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(job_runner.subprocess, "Popen", popen)
    monkeypatch.setattr(job_runner.asyncio, "sleep", no_sleep)
    jobs = {"j": {
        "status": "queued", "logs": [], "cmd": ["python", "-m", "x"],
        "env": {}, "output_dir": str(tmp_path), "max_attempts": 3,
    }}
    run_job = job_runner.make_run_job(jobs=jobs, output_root=str(tmp_path))
    asyncio.run(run_job("j", jobs["j"]))
    assert calls == ["1", "2", "3"]
    assert jobs["j"]["status"] == "failed"
    assert any("retry limit" in line for line in jobs["j"]["logs"])


def test_exit_two_never_retries(monkeypatch, tmp_path):
    _patch_runner_dependencies(monkeypatch, job_runner)
    calls = []

    def popen(*args, **kwargs):
        calls.append(kwargs["env"]["CLIPPYME_ATTEMPT"])
        return _FinishedProcess(2)

    monkeypatch.setattr(job_runner.subprocess, "Popen", popen)
    jobs = {"j": {
        "status": "queued", "logs": [], "cmd": ["python", "-m", "x"],
        "env": {}, "output_dir": str(tmp_path), "max_attempts": 5,
    }}
    run_job = job_runner.make_run_job(jobs=jobs, output_root=str(tmp_path))
    asyncio.run(run_job("j", jobs["j"]))
    assert calls == ["1"]
    assert jobs["j"]["status"] == "failed"
    assert any("non-retryable" in line for line in jobs["j"]["logs"])


def _sequence_runner(monkeypatch, tmp_path, returncodes, *, max_attempts, final=None):
    """run_job over a scripted Popen (one exit code per attempt) with a fake
    asyncio.sleep that records every backoff instead of waiting."""
    _patch_runner_dependencies(monkeypatch, job_runner)
    codes = list(returncodes)
    attempts, sleeps = [], []

    def popen(*args, **kwargs):
        attempts.append(kwargs["env"]["CLIPPYME_ATTEMPT"])
        return _FinishedProcess(codes.pop(0))

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(job_runner.subprocess, "Popen", popen)
    monkeypatch.setattr(job_runner.asyncio, "sleep", fake_sleep)
    if final is not None:
        monkeypatch.setattr(job_runner, "load_final_result", lambda *a, **k: final)
    jobs = {"j": {
        "status": "queued", "logs": [], "cmd": ["python", "-m", "x"],
        "env": {}, "output_dir": str(tmp_path), "max_attempts": max_attempts,
    }}
    run_job = job_runner.make_run_job(jobs=jobs, output_root=str(tmp_path))
    return jobs, run_job, attempts, sleeps


def test_transient_failure_then_success_completes_after_one_backoff(monkeypatch, tmp_path):
    jobs, run_job, attempts, sleeps = _sequence_runner(
        monkeypatch, tmp_path, [1, 0], max_attempts=3, final={"clips": [{"title": "T"}]})
    asyncio.run(run_job("j", jobs["j"]))
    assert attempts == ["1", "2"] and sleeps == [1]
    assert jobs["j"]["status"] == "completed"
    assert jobs["j"]["result"] == {"clips": [{"title": "T"}]}


def test_backoff_doubles_and_is_capped_at_thirty_seconds(monkeypatch, tmp_path):
    jobs, run_job, attempts, sleeps = _sequence_runner(
        monkeypatch, tmp_path, [1] * 8, max_attempts=8)
    asyncio.run(run_job("j", jobs["j"]))
    assert sleeps == [1, 2, 4, 8, 16, 30, 30]  # no sleep after the last attempt
    assert len(attempts) == 8 and jobs["j"]["status"] == "failed"


def test_killed_by_a_signal_is_retried(monkeypatch, tmp_path):
    """A negative return code (POSIX: killed by signal, e.g. OOM-killer -9) is
    not the deterministic exit 2: the attempt is retried."""
    jobs, run_job, attempts, sleeps = _sequence_runner(
        monkeypatch, tmp_path, [-9, 0], max_attempts=3, final={"clips": []})
    asyncio.run(run_job("j", jobs["j"]))
    assert attempts == ["1", "2"] and sleeps == [1]
    assert jobs["j"]["status"] == "completed"


def test_exit_two_after_a_transient_failure_stops_retrying(monkeypatch, tmp_path):
    jobs, run_job, attempts, sleeps = _sequence_runner(
        monkeypatch, tmp_path, [1, 2], max_attempts=5)
    asyncio.run(run_job("j", jobs["j"]))
    assert attempts == ["1", "2"] and sleeps == [1]
    assert jobs["j"]["status"] == "failed"
    assert any("exit code 2 (non-retryable" in line for line in jobs["j"]["logs"])


def test_exit_zero_without_metadata_is_a_failure(monkeypatch, tmp_path):
    jobs, run_job, attempts, sleeps = _sequence_runner(
        monkeypatch, tmp_path, [0], max_attempts=3)  # load_final_result → None
    asyncio.run(run_job("j", jobs["j"]))
    assert attempts == ["1"] and sleeps == []
    assert jobs["j"]["status"] == "failed"
    assert "No metadata file generated." in jobs["j"]["logs"]


def test_shutdown_during_backoff_leaves_the_job_for_restart_recovery(monkeypatch, tmp_path):
    """Cancelled while waiting to retry: not a failure, the job stays active
    (journal keeps it), and the attempt that DID finish stays counted."""
    jobs, run_job, attempts, sleeps = _sequence_runner(
        monkeypatch, tmp_path, [1, 0], max_attempts=3)

    async def cancelled_sleep(seconds):
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(job_runner.asyncio, "sleep", cancelled_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_job("j", jobs["j"]))
    assert attempts == ["1"] and sleeps == [1]
    assert jobs["j"]["status"] == "processing"
    assert jobs["j"]["attempt"] == 1
    assert any("left for restart recovery" in line for line in jobs["j"]["logs"])
