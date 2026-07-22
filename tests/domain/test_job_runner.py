"""merge_persistent_config precedence: Settings vs inherited process env."""
import json

from clippyme.domain.job_runner import _enqueue_completed_job, merge_persistent_config
from clippyme.domain.job_submission import write_publisher_mode
from clippyme.domain.manual_publish_queue import ManualPublishQueue

JOB_ID = "33333333-3333-4333-8333-333333333333"


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


# -- _enqueue_completed_job: the job-completion → manual-publish hook (Task 4b) --

def _make_job(output, job_id, *, clips):
    job_dir = output / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "video_metadata.json").write_text(
        json.dumps({"shorts": clips}), encoding="utf-8")
    for i in range(len(clips)):
        (job_dir / f"video_clip_{i + 1}.mp4").write_bytes(b"video")
    return job_dir


def test_enqueues_clips_when_mode_is_manual_queue(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    job_dir = _make_job(output, JOB_ID, clips=[{"start": 0, "end": 10}])
    write_publisher_mode(str(job_dir), "manual_queue")
    queue = ManualPublishQueue(output, tmp_path / "data" / "manual_publish_queue.json")

    _enqueue_completed_job(queue, JOB_ID, str(job_dir))

    assert len(queue.list_entries("all")) == 1


def test_skips_enqueue_when_mode_is_zernio(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    job_dir = _make_job(output, JOB_ID, clips=[{"start": 0, "end": 10}])
    write_publisher_mode(str(job_dir), "zernio")
    queue = ManualPublishQueue(output, tmp_path / "data" / "manual_publish_queue.json")

    _enqueue_completed_job(queue, JOB_ID, str(job_dir))

    assert queue.list_entries("all") == []


def test_missing_sidecar_defaults_to_manual_queue_enqueue(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    job_dir = _make_job(output, JOB_ID, clips=[{"start": 0, "end": 10}])
    # No publisher_mode.json written — legacy-style job.
    queue = ManualPublishQueue(output, tmp_path / "data" / "manual_publish_queue.json")

    _enqueue_completed_job(queue, JOB_ID, str(job_dir))

    assert len(queue.list_entries("all")) == 1


def test_enqueue_failure_is_non_fatal(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    job_dir = output / JOB_ID
    job_dir.mkdir(parents=True)
    write_publisher_mode(str(job_dir), "manual_queue")
    # No metadata file on disk at all — enqueue_job_clips raises FileNotFoundError
    # internally; the hook must swallow it, never propagate.
    queue = ManualPublishQueue(output, tmp_path / "data" / "manual_publish_queue.json")

    _enqueue_completed_job(queue, JOB_ID, str(job_dir))  # must not raise

    assert queue.list_entries("all") == []


def test_hook_skips_monitor_owned_job(tmp_path):
    """The live monitor is the single queue writer for its own jobs: the
    completion hook must not enqueue anything when the sidecar records
    owner='live_monitor', even though the mode is manual_queue."""
    output = tmp_path / "output"
    output.mkdir()
    job_dir = _make_job(output, JOB_ID, clips=[{"start": 0, "end": 10}])
    write_publisher_mode(str(job_dir), "manual_queue", owner="live_monitor")
    queue = ManualPublishQueue(output, tmp_path / "data" / "manual_publish_queue.json")

    _enqueue_completed_job(queue, JOB_ID, str(job_dir))

    assert queue.list_entries("all") == []


def test_hook_first_then_monitor_yields_exactly_one_composed_entry(tmp_path):
    """Production order: the hook fires the moment the job completes; the
    monitor's _publish_one enqueues its composed clip seconds later. The queue
    must end with exactly ONE entry — the monitor's (template caption), never
    a raw hook-written one."""
    output = tmp_path / "output"
    output.mkdir()
    job_dir = _make_job(output, JOB_ID, clips=[{"start": 0, "end": 10}])
    write_publisher_mode(str(job_dir), "manual_queue", owner="live_monitor")
    queue = ManualPublishQueue(output, tmp_path / "data" / "manual_publish_queue.json")

    _enqueue_completed_job(queue, JOB_ID, str(job_dir))  # hook fires first: no-op
    # ... then the monitor enqueues its composed artifact with template caption.
    source = job_dir / "video_clip_1.mp4"
    queue.enqueue(
        job_id=JOB_ID, clip_index=0, source_path=source, title="Monitor Title",
        caption="template caption", source_platform="kick", source_channel="grenbaud",
        source_kind="live", project_title="Stream", monitor_id="mon-1",
    )

    entries = queue.list_entries("all")
    assert len(entries) == 1
    assert entries[0]["monitor_id"] == "mon-1"
    assert entries[0]["caption"] == "template caption"


def test_no_double_enqueue_when_clip_already_queued(tmp_path):
    """Legacy monitor job (sidecar written before the owner field existed):
    the monitor already enqueued the clip, then the hook runs. Dedup by
    (job_id, clip_index) must keep it a single entry."""
    output = tmp_path / "output"
    output.mkdir()
    job_dir = _make_job(output, JOB_ID, clips=[{"start": 0, "end": 10}])
    write_publisher_mode(str(job_dir), "manual_queue")
    queue = ManualPublishQueue(output, tmp_path / "data" / "manual_publish_queue.json")
    source = job_dir / "video_clip_1.mp4"
    queue.enqueue(
        job_id=JOB_ID, clip_index=0, source_path=source, title="Monitor Title",
        caption="c", source_platform="kick", source_channel="grenbaud",
        source_kind="live", project_title="Stream", monitor_id="mon-1",
    )

    _enqueue_completed_job(queue, JOB_ID, str(job_dir))

    entries = queue.list_entries("all")
    assert len(entries) == 1
    assert entries[0]["monitor_id"] == "mon-1"
