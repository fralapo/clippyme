"""The job journal never persists a secret.

The journal replays only the allow-listed, non-secret pipeline knobs
(``JOURNAL_ENV_KEYS``) into a resumed job; the job ``env`` — which carries the
API keys — is never written. Fake secret values are generated per run, so a
leak shows up as the literal value in the journal bytes.
"""
import asyncio
import json
import secrets

from clippyme.jobs import job_journal as jj
from clippyme.monitoring.live_monitor import LiveMonitor, validate_monitor_config

SECRET_KEYS = ("GEMINI_API_KEY", "ZERNIO_API_KEY", "DEEPGRAM_API_KEY",
               "ELEVENLABS_API_KEY", "HF_TOKEN", "TWITCH_CLIENT_SECRET")


def _fake_secrets():
    return {key: f"fake-{key.lower()}-{secrets.token_hex(12)}" for key in SECRET_KEYS}


def test_snapshot_keeps_allow_listed_knobs_and_no_secret():
    fake = _fake_secrets()
    knobs = {"CLIPPYME_MAX_CLIPS": "3", "CLIPPYME_MIN_VIRAL_SCORE": "80",
             "CLIPPYME_CREATOR_NAME": "foo"}
    jobs = {"j1": {
        "status": "processing", "cmd": ["python", "-m", "clippyme.pipeline.orchestrator"],
        "output_dir": "out/j1", "env": {**fake, **knobs},
        # A caller that hands the whole env over as journal_env must not leak it.
        "journal_env": {**fake, **knobs},
    }}
    records = jj.snapshot(jobs)
    blob = json.dumps(records)
    for value in fake.values():
        assert value not in blob
    assert "env" not in records["j1"]
    assert records["j1"]["journal_env"] == knobs
    assert set(jj.JOURNAL_ENV_KEYS) == set(knobs)  # a new knob must be judged here


def test_recovery_never_brings_a_journaled_secret_back(tmp_path, monkeypatch):
    """A tampered/legacy journal record carrying secrets in journal_env: the
    resumed job's env gets the knob, never the journal's secret."""
    fake = _fake_secrets()
    for key in SECRET_KEYS:
        monkeypatch.delenv(key, raising=False)
    entry = jj._recovered_entry("j1", {
        "status": "queued", "cmd": ["python"], "output_dir": str(tmp_path),
        "journal_env": {**fake, "CLIPPYME_MAX_CLIPS": "2"}}, "requeued")
    assert entry["env"]["CLIPPYME_MAX_CLIPS"] == "2"
    assert not set(fake.values()) & set(entry["env"].values())
    assert entry["journal_env"] == {"CLIPPYME_MAX_CLIPS": "2"}


def test_monitor_job_submission_writes_no_secret_to_the_journal(tmp_path, monkeypatch):
    """The real path: a monitor submits a segment job (the Gemini key in its
    env) through submit_job, whose on_change writes the journal to disk."""
    fake = _fake_secrets()
    for key, value in fake.items():
        monkeypatch.setenv(key, value)  # os.environ is copied into the job env
    journal = tmp_path / "jobs_journal.json"
    jobs = {}
    mon = LiveMonitor(id="twitch:foo", jobs=jobs, job_queue=None, output_dir=str(tmp_path / "out"),
                      on_job_change=jj.make_journal_writer(jobs=jobs, path=str(journal)))
    mon.cfg = validate_monitor_config({
        "platform": "twitch", "channel": "foo", "timezone": "UTC", "max_clips": 3,
        "platforms": [{"platform": "tiktok", "accountId": "a"}]}, default_timezone="UTC")
    mon._gemini_key = fake["GEMINI_API_KEY"]
    seg = tmp_path / "seg.mp4"
    seg.write_bytes(b"segment")

    async def submit():
        mon._job_queue = asyncio.Queue()
        return await mon._submit_segment_job(str(seg))

    job_id = asyncio.run(submit())
    assert jobs[job_id]["env"]["GEMINI_API_KEY"] == fake["GEMINI_API_KEY"]  # the job has it
    raw = journal.read_text(encoding="utf-8")
    for value in fake.values():
        assert value not in raw
    record = json.loads(raw)[job_id]
    assert record["journal_env"]["CLIPPYME_MAX_CLIPS"] == "3"
    assert set(record["journal_env"]) <= set(jj.JOURNAL_ENV_KEYS)
