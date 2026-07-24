import asyncio
import io

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
