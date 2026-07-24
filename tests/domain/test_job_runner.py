"""merge_persistent_config precedence: Settings vs inherited process env."""
from clippyme.domain.job_runner import merge_persistent_config


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

    from clippyme.domain import job_runner as module

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
    assert jobs["j"]["status"] == "failed"
    assert any("shutdown" in line.lower() for line in jobs["j"]["logs"])
