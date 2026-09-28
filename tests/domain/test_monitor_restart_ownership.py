"""Live Monitor work ownership across a process restart.

* B1 — a monitor job that COMPLETED before the restart but was not yet handed
  to the publish queue (the monitor had not polled it yet, or was composing
  its clips) must still be published once after the restart. The job journal
  keeps active jobs only, so the job is gone from the registry: the durable
  proof of completion is the job dir (runtime stage ``completed`` + metadata).
* B2 — a backfill window whose job is in flight is owned by that job: a
  restart re-attaches the job and never cuts the same window again.

Every life runs the real Registry / LiveMonitor / submit_job / job journal /
recover_jobs code and reads back what the previous life persisted. A crash is
modelled as the on-disk state at the crash instant (captured, then put back
after the event loop is torn down) — never by injecting the post-recovery
state under test. Only the network edges (platform API, capture tool,
yt-dlp, Zernio, ffmpeg compose) are faked.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from clippyme.jobs import job_journal as jj
from clippyme.monitoring import live_monitor as lm
from clippyme.jobs.job_results import load_final_result
from clippyme.monitoring.live_monitor import LiveMonitor, LiveMonitorRegistry
from clippyme.jobs.runtime_state import RuntimeState

from .test_live_monitor_reliability import (
    ScriptedStrategy, _fake_publisher, _until, _wire_e2e,
)

RAW = {"platform": "twitch", "channel": "foo", "timezone": "UTC", "loop": True,
       "prelive_skip_seconds": 0, "segment_seconds": 600,
       "platforms": [{"platform": "tiktok", "accountId": "a"}]}
MID = "twitch:foo"


class _Paths:
    def __init__(self, tmp_path):
        self.out = tmp_path / "out"
        self.out.mkdir()
        self.uploads = tmp_path / "uploads"
        self.state = tmp_path / "live_monitor.json"
        self.journal = tmp_path / "jobs_journal.json"


def _registry(paths, jobs):
    return LiveMonitorRegistry(
        jobs=jobs, job_queue=asyncio.Queue(), output_dir=str(paths.out),
        upload_dir=str(paths.uploads), state_path=str(paths.state),
        on_job_change=jj.make_journal_writer(jobs=jobs, path=str(paths.journal)))


def _crash_image(paths):
    """What a kill -9 right now would leave on disk."""
    return {p: (p.read_bytes() if p.exists() else None) for p in (paths.state, paths.journal)}


def _put_back(image):
    for path, data in image.items():
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(data)


def _complete_like_the_pipeline(jobs, paths, job_id, n_clips=1):
    """Orchestrator + job runner success path: clips + metadata on disk, runtime
    stage ``completed``, then the registry entry, then the journal write."""
    job_dir = paths.out / job_id
    shorts = []
    for i in range(n_clips):
        (job_dir / f"t_clip_{i + 1}.mp4").write_bytes(b"clip")
        shorts.append({"title": f"T{i}", "clip_filename": f"t_clip_{i + 1}.mp4",
                       "start": 30 * i, "end": 30 * i + 30})
    (job_dir / "seg_metadata.json").write_text(json.dumps({"shorts": shorts}))
    RuntimeState(str(job_dir), job_id=job_id).finish()
    jobs[job_id]["status"] = "completed"
    jobs[job_id]["result"] = load_final_result(job_id, str(job_dir))
    jj.make_journal_writer(jobs=jobs, path=str(paths.journal))()


def _recorded_states(monkeypatch, paths):
    """Every monitor state the registry durably writes, in order."""
    states = []
    real = jj.save_journal

    def save(path, data):
        if os.path.abspath(path) == os.path.abspath(paths.state):
            states.append(json.loads(json.dumps(data))["monitors"].get(MID))
        real(path, data)

    monkeypatch.setattr(jj, "save_journal", save)
    return states


def _snapshot(paths):
    if not paths.state.exists():
        return {}
    return json.loads(paths.state.read_text())["monitors"].get(MID) or {}


# ---------------------------------------------------------------------------
# B1 — completed before the restart, not yet handed off
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("boundary, n_clips", [
    ("completion_unobserved", 1),
    ("crash_mid_handoff", 1),
    ("crash_after_first_clip_composed", 2),
])
def test_completed_job_not_yet_handed_off_is_published_after_restart(
        tmp_path, monkeypatch, boundary, n_clips):
    paths = _Paths(tmp_path)

    # --- life 1: live → segment → job; the job completes; crash --------------
    _wire_e2e(monkeypatch, tmp_path,
              lambda: ScriptedStrategy([(True, "u", None), (True, "u", None),
                                        (False, None, None)]))
    composing = []
    if boundary == "completion_unobserved":
        # The monitor polls its jobs every JOB_POLL_SECONDS: the job finishes
        # and the process dies before the next poll.
        monkeypatch.setattr(lm, "JOB_POLL_SECONDS", 3600)
    else:
        # The monitor saw the completion and is composing the clips (minutes
        # for a real segment) when the process dies — on the first clip, or
        # after the first one already landed in the monitor folder.
        hang_on = 0 if boundary == "crash_mid_handoff" else 1
        real_compose = LiveMonitor._compose_for_publish

        async def compose(self, job_id, clip, base_path=None):
            if clip["original_index"] == hang_on:
                composing.append(job_id)
                await asyncio.sleep(3600)
            return await real_compose(self, job_id, clip, base_path)

        monkeypatch.setattr(LiveMonitor, "_compose_for_publish", compose)
    jobs1 = {}

    async def life1():
        reg = _registry(paths, jobs1)
        reg.start(RAW)
        await _until(lambda: len(jobs1) == 1)
        job_id = next(iter(jobs1))
        await _until(lambda: _snapshot(paths).get("inflight_jobs"))
        _complete_like_the_pipeline(jobs1, paths, job_id, n_clips)
        if boundary != "completion_unobserved":
            await _until(lambda: composing)
        return job_id, jobs1[job_id]["input_path"], _crash_image(paths)

    job_id, seg, image = asyncio.run(life1())
    _put_back(image)
    snap = _snapshot(paths)
    assert snap["inflight_jobs"] == [{"job_id": job_id, "seg_path": seg}]
    assert snap["pending_publish"] == [] and snap["published"] == []
    assert os.path.exists(seg)

    # --- life 2: restart → real journal recovery → auto-resume --------------
    _wire_e2e(monkeypatch, tmp_path, lambda: ScriptedStrategy())
    calls = _fake_publisher(monkeypatch)
    states = _recorded_states(monkeypatch, paths)
    clip_paths = [os.path.join(str(paths.out), job_id, f"t_clip_{i + 1}.mp4")
                  for i in range(n_clips)]
    jobs2 = {}

    async def life2():
        jj.recover_jobs(journal_path=str(paths.journal), jobs=jobs2,
                        job_queue=asyncio.Queue(), output_root=str(paths.out))
        # The journal keeps active jobs only: the completed job is not back.
        assert job_id not in jobs2
        reg = _registry(paths, jobs2)
        await reg.auto_resume()
        assert reg.publication_owner(job_id, 0) == MID
        mon = reg._monitors[MID]
        await _until(lambda: set(clip_paths) <= mon._published
                     or not (mon._inflight_jobs or mon._pending_publish))
        await reg.shutdown()
        return mon, reg

    mon, reg = asyncio.run(life2())
    assert set(clip_paths) <= mon._published, "completed work lost across the restart"
    # Each clip exactly once — a re-consolidation after the re-attach never
    # queues a clip twice (nothing was queued before the crash).
    assert len(calls) == n_clips and mon.clips_published == n_clips
    assert all(reg.publication_owner(job_id, i) is None for i in range(n_clips))
    assert not os.path.exists(seg)
    final = _snapshot(paths)
    assert final["inflight_jobs"] == [] and final["pending_publish"] == []
    # No durable state in between may have dropped the work: until every clip
    # was accepted, the job is either still tracked or has clips queued.
    for state in states:
        tracked = {i["job_id"] for i in state["inflight_jobs"]}
        queued = {e["job_id"] for e in state["pending_publish"]}
        assert (job_id in tracked | queued
                or set(clip_paths) <= set(state["published"])), state

    # --- life 3: a second restart replays nothing ---------------------------
    _wire_e2e(monkeypatch, tmp_path, lambda: ScriptedStrategy())
    jobs3 = {}

    async def life3():
        jj.recover_jobs(journal_path=str(paths.journal), jobs=jobs3,
                        job_queue=asyncio.Queue(), output_root=str(paths.out))
        reg = _registry(paths, jobs3)
        await reg.auto_resume()
        await reg.shutdown()

    asyncio.run(life3())
    assert len(calls) == n_clips
    assert _snapshot(paths)["published"] == sorted(clip_paths)


def test_job_unknown_after_restart_without_proof_of_completion_is_released(tmp_path):
    """The recovery is not "job gone = publish anyway": a job dir whose runtime
    state never reached ``completed`` (failed, stopped, crashed) publishes
    nothing and releases its segment, as before."""
    paths = _Paths(tmp_path)
    job_dir = paths.out / "j1"
    job_dir.mkdir()
    (job_dir / "t_clip_1.mp4").write_bytes(b"partial")
    (job_dir / "seg_metadata.json").write_text(json.dumps({"shorts": [
        {"title": "T", "clip_filename": "t_clip_1.mp4"}]}))
    RuntimeState(str(job_dir), job_id="j1").start("rendering")
    seg = tmp_path / "seg.mp4"
    seg.write_bytes(b"x")
    mon = LiveMonitor(id=MID, jobs={}, job_queue=None, output_dir=str(paths.out))
    mon.cfg = lm.validate_monitor_config(dict(RAW), default_timezone="UTC")

    async def scenario():
        mon._stop = asyncio.Event()
        await mon._await_and_publish("j1", str(seg))

    asyncio.run(scenario())
    assert mon._pending_publish == [] and mon._inflight_jobs == {}
    assert not seg.exists()


# ---------------------------------------------------------------------------
# B2 — a backfill window owned by an in-flight job
# ---------------------------------------------------------------------------

class _TwitchLive(ScriptedStrategy):
    def __init__(self, started_at):
        super().__init__([(True, "u", started_at)])

    def live_vod_url(self):
        return "https://vod.example/1"


def _wire_backfill(monkeypatch, tmp_path, started_at, downloads):
    _wire_e2e(monkeypatch, tmp_path, lambda: _TwitchLive(started_at))

    async def download(self, vod_url, t1, t2):
        downloads.append((t1, t2))
        path = tmp_path / "uploads" / f"backfill_twitch_foo_{t1}_{t2}_{len(downloads)}.mp4"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"vod range")
        return str(path)

    monkeypatch.setattr(LiveMonitor, "_download_vod_range", download)


def _backfill_running():
    """A monitor backfill task (``LiveMonitor.*backfill*``) is still pending."""
    names = (getattr(t.get_coro(), "__qualname__", "")
             for t in asyncio.all_tasks() if not t.done())
    return any(n.startswith("LiveMonitor.") and "backfill" in n for n in names)


@pytest.mark.parametrize("ending", ["crash", "graceful_stop"])
def test_backfill_window_in_flight_is_not_cut_again_after_restart(
        tmp_path, monkeypatch, ending):
    paths = _Paths(tmp_path)
    # One missed 600 s window [0, 600] (the 10 s tail is below the floor).
    started_at = datetime.now(timezone.utc) - timedelta(seconds=610)
    downloads = []

    # --- life 1: live, backfill W → job J submitted; J still running --------
    _wire_backfill(monkeypatch, tmp_path, started_at, downloads)
    jobs1 = {}

    async def life1():
        reg = _registry(paths, jobs1)
        reg.start(RAW)
        await _until(lambda: _snapshot(paths).get("inflight_jobs"))
        job_id = next(iter(jobs1))
        if ending == "crash":
            return job_id, _crash_image(paths)
        await reg.shutdown()
        return job_id, None

    job_id, image = asyncio.run(life1())
    if image is not None:
        _put_back(image)
    assert downloads == [(0, 600)]
    assert _snapshot(paths)["inflight_jobs"][0]["job_id"] == job_id

    # --- life 2: restart; the same stream is still live ---------------------
    _wire_backfill(monkeypatch, tmp_path, started_at, downloads)
    calls = _fake_publisher(monkeypatch)
    jobs2 = {}

    async def life2():
        jj.recover_jobs(journal_path=str(paths.journal), jobs=jobs2,
                        job_queue=asyncio.Queue(), output_root=str(paths.out))
        assert jobs2[job_id]["status"] == "queued"  # J resumed by the journal
        reg = _registry(paths, jobs2)
        await reg.auto_resume()
        mon = reg._monitors[MID]
        # The marathon has run _schedule_backfill once it is back to waiting.
        await _until(lambda: mon.state == "waiting_live" or len(jobs2) > 1)
        _complete_like_the_pipeline(jobs2, paths, job_id)
        clip_path = os.path.join(str(paths.out), job_id, "t_clip_1.mp4")
        await _until(lambda: len(jobs2) > 1
                     or (clip_path in mon._published and not _backfill_running()))
        await reg.shutdown()

    asyncio.run(life2())
    assert set(jobs2) == {job_id}, "backfill window cut again as a second job"
    assert downloads == [(0, 600)]
    assert len(calls) == 1
    final = _snapshot(paths)
    assert final["missed_windows"] == [] and final["inflight_jobs"] == []
    assert final["pending_publish"] == []

    # --- life 3: a second restart replays nothing ---------------------------
    _wire_backfill(monkeypatch, tmp_path, started_at, downloads)
    jobs3 = {}

    async def life3():
        jj.recover_jobs(journal_path=str(paths.journal), jobs=jobs3,
                        job_queue=asyncio.Queue(), output_root=str(paths.out))
        reg = _registry(paths, jobs3)
        await reg.auto_resume()
        mon = reg._monitors[MID]
        await _until(lambda: mon.state == "waiting_live")
        await reg.shutdown()

    asyncio.run(life3())
    assert jobs3 == {} and downloads == [(0, 600)] and len(calls) == 1


def _legacy_backfill_state(paths, started_at, seg_name):
    """A state file as the previous version left it when killed while a
    backfill job ran: the job in flight AND its window still pending."""
    cfg = lm.validate_monitor_config(dict(RAW), default_timezone="UTC")
    job_dir = paths.out / "J"
    job_dir.mkdir()
    RuntimeState(str(job_dir), job_id="J")
    paths.uploads.mkdir(exist_ok=True)
    seg = paths.uploads / seg_name
    seg.write_bytes(b"vod range")
    snap = {"platform": "twitch", "mode": "live", "channel": "foo", "config": cfg,
            "resume_on_start": True, "covered_elapsed": 610,
            "covered_stream_start": started_at.isoformat(),
            "inflight_jobs": [{"job_id": "J", "seg_path": str(seg)}],
            "missed_windows": [[0, 600]]}
    paths.state.write_text(json.dumps({"monitors": {MID: snap}, "picked_slots": []}))
    jj.save_journal(str(paths.journal), {"J": {
        "status": "queued", "cmd": ["python", "-m", "clippyme.pipeline.orchestrator"],
        "output_dir": str(job_dir), "input_path": str(seg)}})


def _resume_and_settle(paths, jobs):
    async def life():
        jj.recover_jobs(journal_path=str(paths.journal), jobs=jobs,
                        job_queue=asyncio.Queue(), output_root=str(paths.out))
        reg = _registry(paths, jobs)
        await reg.auto_resume()
        mon = reg._monitors[MID]
        await _until(lambda: len(jobs) > 1
                     or (mon.state == "waiting_live" and not _backfill_running()))
        await reg.shutdown()

    asyncio.run(life())


def test_legacy_snapshot_with_window_and_its_job_does_not_cut_it_again(tmp_path, monkeypatch):
    paths = _Paths(tmp_path)
    started_at = datetime.now(timezone.utc) - timedelta(seconds=610)
    downloaded_at = int(started_at.timestamp()) + 5
    _legacy_backfill_state(paths, started_at, f"backfill_twitch_foo_0_600_{downloaded_at}.mp4")
    downloads = []
    _wire_backfill(monkeypatch, tmp_path, started_at, downloads)
    jobs = {}

    _resume_and_settle(paths, jobs)
    assert set(jobs) == {"J"} and downloads == []
    snap = _snapshot(paths)
    assert snap["missed_windows"] == []
    assert snap["inflight_jobs"][0]["job_id"] == "J"


def test_same_numbered_window_of_a_newer_stream_is_still_recovered(tmp_path, monkeypatch):
    """A backfill job of the PREVIOUS stream (downloaded before this stream
    started) does not own this stream's [0, 600] window."""
    paths = _Paths(tmp_path)
    started_at = datetime.now(timezone.utc) - timedelta(seconds=610)
    downloaded_at = int(started_at.timestamp()) - 3600
    _legacy_backfill_state(paths, started_at, f"backfill_twitch_foo_0_600_{downloaded_at}.mp4")
    downloads = []
    _wire_backfill(monkeypatch, tmp_path, started_at, downloads)
    jobs = {}

    _resume_and_settle(paths, jobs)
    assert downloads == [(0, 600)] and len(jobs) == 2
