import asyncio
import io

from clippyme.domain import job_runner


class _ImmediateThread:
    def __init__(self, target, args=(), **kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)

    def is_alive(self):
        return False

    def join(self, timeout=None):
        return None


class _Process:
    def __init__(self, returncode, attempt_log, env):
        self.returncode = returncode
        self.pid = 1234
        self.stdout = io.BytesIO(b"")
        attempt_log.append(env["CLIPPYME_ATTEMPT"])

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        return None


def _patch(monkeypatch, attempts, returncode=1):
    monkeypatch.setattr(job_runner, "load_persistent_config", lambda: {})
    monkeypatch.setattr(job_runner, "load_partial_result", lambda *args: None)
    monkeypatch.setattr(job_runner, "load_final_result", lambda *args: None)
    monkeypatch.setattr(job_runner, "load_runtime_state", lambda *args: None)
    monkeypatch.setattr(job_runner, "collect_runtime_metrics", lambda *args: {})
    monkeypatch.setattr(job_runner, "runtime_result_fields", lambda *args: {})
    monkeypatch.setattr(job_runner.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(
        job_runner.subprocess,
        "Popen",
        lambda *args, **kwargs: _Process(returncode, attempts, kwargs["env"]),
    )


async def _no_sleep(_seconds):
    return None


def test_recovered_job_uses_only_remaining_attempt(monkeypatch, tmp_path):
    attempts = []
    _patch(monkeypatch, attempts)
    monkeypatch.setattr(job_runner.asyncio, "sleep", _no_sleep)
    jobs = {"job": {
        "status": "queued",
        "logs": ["Server restarted; resuming from checkpoint."],
        "cmd": ["python", "-m", "pipeline"],
        "env": {},
        "output_dir": str(tmp_path),
        "attempt": 2,
        "max_attempts": 3,
    }}
    runner = job_runner.make_run_job(jobs=jobs, output_root=str(tmp_path))
    asyncio.run(runner("job", jobs["job"]))
    assert attempts == ["3"]
    assert jobs["job"]["status"] == "failed"


def test_exhausted_recovered_job_never_dispatches(monkeypatch, tmp_path):
    attempts = []
    _patch(monkeypatch, attempts)
    jobs = {"job": {
        "status": "queued",
        "logs": [],
        "cmd": ["python", "-m", "pipeline"],
        "env": {},
        "output_dir": str(tmp_path),
        "attempt": 3,
        "max_attempts": 3,
    }}
    runner = job_runner.make_run_job(jobs=jobs, output_root=str(tmp_path))
    asyncio.run(runner("job", jobs["job"]))
    assert attempts == []
    assert jobs["job"]["status"] == "failed"
    assert any("already exhausted" in line for line in jobs["job"]["logs"])
