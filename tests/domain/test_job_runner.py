"""merge_persistent_config precedence: Settings vs inherited process env."""
from clippyme.jobs.job_runner import merge_persistent_config


def test_settings_override_empty_env_values():
    # docker compose exports DEEPGRAM_API_KEY= (empty) — Settings must win.
    env = {"DEEPGRAM_API_KEY": "", "TRANSCRIPTION_PROVIDER": "deepgram"}
    merge_persistent_config(env, {
        "DEEPGRAM_API_KEY": "dg-key",
        "TRANSCRIPTION_PROVIDER": "elevenlabs",
    })
    assert env["DEEPGRAM_API_KEY"] == "dg-key"
    assert env["TRANSCRIPTION_PROVIDER"] == "elevenlabs"


def test_settings_override_nonempty_env_values():
    # A compose-pinned provider must not shadow the user's Settings choice.
    env = {"TRANSCRIPTION_PROVIDER": "deepgram"}
    merge_persistent_config(env, {"TRANSCRIPTION_PROVIDER": "whisper"})
    assert env["TRANSCRIPTION_PROVIDER"] == "whisper"


def test_empty_persisted_values_never_clobber_env():
    # Env-only deploy: nothing saved in Settings → env values survive.
    env = {"DEEPGRAM_API_KEY": "env-key", "HF_TOKEN": "hf-env"}
    merge_persistent_config(env, {"DEEPGRAM_API_KEY": "", "HF_TOKEN": None})
    assert env["DEEPGRAM_API_KEY"] == "env-key"
    assert env["HF_TOKEN"] == "hf-env"


def test_gemini_header_key_wins_over_settings():
    env = {"GEMINI_API_KEY": "header-key"}
    merge_persistent_config(env, {"GEMINI_API_KEY": "settings-key"})
    assert env["GEMINI_API_KEY"] == "header-key"


def test_gemini_settings_key_fills_missing_env():
    env = {}
    merge_persistent_config(env, {"GEMINI_API_KEY": "settings-key"})
    assert env["GEMINI_API_KEY"] == "settings-key"


def test_cancelling_runner_terminates_process_tree(monkeypatch, tmp_path):
    import asyncio
    import io

    from clippyme.jobs import job_runner as module

    class Proc:
        def __init__(self):
            self.pid = 123
            self.stdout = io.BytesIO(b"")
            self.running = True
            self.returncode = None

        def poll(self):
            return None if self.running else -15

        def wait(self, timeout=None):
            self.running = False
            self.returncode = -15
            return -15

        def kill(self):
            self.wait()

    proc = Proc()
    terminated = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(module, "load_persistent_config", lambda: {})
    monkeypatch.setattr(module, "load_partial_result", lambda *a, **k: None)

    def terminate(pid, timeout):
        terminated.append(pid)
        proc.wait()
        return 1

    monkeypatch.setattr(module.job_control, "terminate_tree", terminate)
    jobs = {
        "j": {
            "status": "queued",
            "logs": [],
            "cmd": ["python", "-m", "x"],
            "env": {},
            "output_dir": str(tmp_path),
        }
    }
    run_job = module.make_run_job(jobs=jobs, output_root=str(tmp_path))

    async def scenario():
        task = asyncio.create_task(run_job("j", jobs["j"]))
        while jobs["j"].get("process") is None:
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert terminated == [123]
    assert proc.running is False
    # Graceful server shutdown is not a job failure: the job stays active so
    # the journal keeps it for checkpoint resume on the next startup.
    assert jobs["j"]["status"] == "processing"
    assert any("shutdown" in line.lower() for line in jobs["j"]["logs"])


# ---------------------------------------------------------------------------
# Shutdown vs user action vs genuine failure vs completion
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402

from clippyme.jobs import job_journal as jj  # noqa: E402


class _Proc:
    """Popen stand-in: runs until ``finish`` or termination."""

    def __init__(self, returncode=None):
        self.pid = 4242
        self.stdout = io.BytesIO(b"")
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def finish(self, code):
        self.returncode = code

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = -15
        return self.returncode

    def kill(self):
        self.wait()


def _runner(monkeypatch, tmp_path, procs, **job):
    from clippyme.jobs import job_runner as module

    queue = list(procs)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: queue.pop(0))
    monkeypatch.setattr(module, "load_persistent_config", lambda: {})
    monkeypatch.setattr(module.job_control, "terminate_tree", lambda pid, timeout: 1)
    jobs = {"j": {"status": "queued", "logs": [], "cmd": ["python", "-m", "x"],
                  "env": {}, "output_dir": str(tmp_path), **job}}
    journal = {}

    def on_change():
        journal.clear()
        journal.update(jj.snapshot(jobs))

    run_job = module.make_run_job(jobs=jobs, output_root=str(tmp_path), on_change=on_change)
    return jobs, journal, run_job


async def _until(predicate):
    for _ in range(2000):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached")


def _shutdown(task):
    task.cancel()


def test_graceful_shutdown_keeps_job_journalled_and_refunds_attempt(monkeypatch, tmp_path):
    proc = _Proc()
    jobs, journal, run_job = _runner(monkeypatch, tmp_path, [proc], max_attempts=1)

    async def scenario():
        task = asyncio.create_task(run_job("j", jobs["j"]))
        await _until(lambda: jobs["j"].get("process") is proc)
        _shutdown(task)
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert proc.returncode == -15
    assert jobs["j"]["status"] == "processing"
    # The interrupted attempt never finished, so it is not charged: with
    # max_attempts=1 the resumed job can still run.
    assert journal["j"]["status"] == "processing"
    assert journal["j"]["attempt"] == 0
    assert journal["j"]["pid"] is None


def test_shutdown_during_retry_backoff_keeps_the_genuinely_failed_attempt(monkeypatch, tmp_path):
    jobs, journal, run_job = _runner(monkeypatch, tmp_path, [_Proc(returncode=1)], max_attempts=3)

    async def scenario():
        task = asyncio.create_task(run_job("j", jobs["j"]))
        await _until(lambda: any("resuming from checkpoints" in line for line in jobs["j"]["logs"]))
        _shutdown(task)
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert jobs["j"]["status"] == "processing"
    assert journal["j"]["attempt"] == 1  # attempt 1 really failed; not refunded


def test_user_cancel_is_terminal_and_leaves_the_journal(monkeypatch, tmp_path):
    proc = _Proc()
    jobs, journal, run_job = _runner(monkeypatch, tmp_path, [proc])

    async def scenario():
        task = asyncio.create_task(run_job("j", jobs["j"]))
        await _until(lambda: jobs["j"].get("process") is proc)
        jobs["j"]["status"] = "cancelled"  # what cancel_job_action publishes
        proc.finish(-15)
        await task

    asyncio.run(scenario())
    assert jobs["j"]["status"] == "cancelled"
    assert journal == {}


def test_shutdown_after_user_stop_preserves_the_terminal_status(monkeypatch, tmp_path):
    proc = _Proc()
    jobs, journal, run_job = _runner(monkeypatch, tmp_path, [proc])

    async def scenario():
        task = asyncio.create_task(run_job("j", jobs["j"]))
        await _until(lambda: jobs["j"].get("process") is proc)
        jobs["j"]["status"] = "stopped"
        _shutdown(task)
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert jobs["j"]["status"] == "stopped"
    assert journal == {}


def test_genuine_failure_is_failed_and_leaves_the_journal(monkeypatch, tmp_path):
    jobs, journal, run_job = _runner(monkeypatch, tmp_path, [_Proc(returncode=1)], max_attempts=1)
    asyncio.run(run_job("j", jobs["j"]))
    assert jobs["j"]["status"] == "failed"
    assert any("retry limit reached" in line for line in jobs["j"]["logs"])
    assert journal == {}


def test_normal_completion_is_completed_and_leaves_the_journal(monkeypatch, tmp_path):
    (tmp_path / "demo_metadata.json").write_text(json.dumps({"shorts": [{"start": 0, "end": 5}]}))
    (tmp_path / "demo_clip_1.mp4").write_bytes(b"\x00")
    jobs, journal, run_job = _runner(monkeypatch, tmp_path, [_Proc(returncode=0)])
    asyncio.run(run_job("j", jobs["j"]))
    assert jobs["j"]["status"] == "completed"
    assert len(jobs["j"]["result"]["clips"]) == 1
    assert journal == {}
