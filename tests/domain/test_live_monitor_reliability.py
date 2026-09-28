"""Live Monitor reliability: provider failures, restart state, durable publish
queue, publish idempotency and segment ownership.

Every test drives the real LiveMonitor / Registry code; only the network
edges (platform APIs, Zernio, the capture tool, ffmpeg compose) are faked.
"""
import asyncio
import json
import os
import time

import pytest

from clippyme.jobs import job_journal as jj
from clippyme.monitoring import live_monitor as lm
from clippyme.monitoring.live_monitor import LiveMonitor, LiveMonitorRegistry, validate_monitor_config
from clippyme.integrations import social_publisher as sp
from clippyme.integrations.social_publisher import ZernioError


def _cfg(**over):
    raw = {
        "platform": "twitch", "channel": "foo",
        "platforms": [{"platform": "tiktok", "accountId": "a"}],
        "loop": True, "prelive_skip_seconds": 0, "poll_interval": 60,
        "segment_seconds": 600, "timezone": "UTC",
    }
    raw.update(over)
    return validate_monitor_config(raw, default_timezone="UTC")


class ScriptedStrategy:
    """Platform strategy whose get_live_state follows a script of results or
    exceptions (then reports offline)."""

    def __init__(self, script=()):
        self.script = list(script)
        self.calls = 0

    def get_live_state(self):
        self.calls += 1
        item = self.script.pop(0) if self.script else (False, None, None)
        if isinstance(item, BaseException):
            raise item
        return item


def _monitor(tmp_path, *, jobs=None, **cfg):
    mon = LiveMonitor(id="twitch:foo", jobs=jobs if jobs is not None else {},
                      job_queue=None, output_dir=str(tmp_path))
    mon.cfg = _cfg(**cfg)
    mon.platform = "twitch"
    mon._zernio_key = "sk_test"
    mon._gemini_key = "g"
    return mon


def _fake_publisher(monkeypatch, outcomes=()):
    """Replace publish_clip; each call consumes one outcome (exception to raise
    or result dict), then succeeds."""
    outcomes = list(outcomes)
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        out = outcomes.pop(0) if outcomes else {"post_id": f"p{len(calls)}", "status": "scheduled"}
        if callable(out):
            out = out()
        if isinstance(out, BaseException):
            raise out
        return out

    monkeypatch.setattr(sp, "publish_clip", fake)
    return calls


def _entry(tmp_path, name="c.mp4", job="job1"):
    job_dir = tmp_path / job
    job_dir.mkdir(exist_ok=True)
    (job_dir / name).write_bytes(b"x")
    return {"job_id": job, "clip": {"video_url": f"/videos/{job}/{name}", "title": "T"},
            "composed_path": str(job_dir / name)}


def _no_compose(monkeypatch):
    async def compose(self, job_id, clip, base_path=None):
        return base_path or os.path.join(self._output_dir, job_id,
                                         os.path.basename(clip["video_url"]))
    monkeypatch.setattr(LiveMonitor, "_compose_for_publish", compose)


# ---------------------------------------------------------------------------
# A. Provider transient failure (I5, I6, I10)
# ---------------------------------------------------------------------------

def test_transient_live_state_errors_do_not_kill_the_monitor(tmp_path):
    mon = _monitor(tmp_path)
    mon._strategy = ScriptedStrategy([RuntimeError("HTTP 503"), ConnectionError("dns"),
                                      (False, None, None)])
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            mon._stop.set()

    mon._interruptible_sleep = fake_sleep

    async def scenario():
        mon._stop = asyncio.Event()
        await mon._run()

    asyncio.run(scenario())
    assert mon._strategy.calls == 3, "monitor died on the first provider error"
    # Backoff grows while the provider fails, then resets after a success.
    assert sleeps[0] == 120 and sleeps[1] == 240
    assert sleeps[2] <= 75
    assert mon.last_error is None


def test_capture_continues_when_live_state_is_unknown(tmp_path, monkeypatch):
    from clippyme.media import media_probe

    mon = _monitor(tmp_path)
    mon._strategy = ScriptedStrategy([(True, "u1", None), RuntimeError("HTTP 503"),
                                      (False, None, None)])
    urls = []

    async def capture(url):
        urls.append(url)
        path = tmp_path / f"seg{len(urls)}.mp4"
        path.write_bytes(b"x")
        return str(path)

    async def submit(seg_path):
        return f"job{len(urls)}"

    async def no_publish(job_id, seg_path):
        return None

    mon._capture_segment = capture
    mon._submit_segment_job = submit
    mon._await_and_publish = no_publish
    monkeypatch.setattr(media_probe, "probe_duration", lambda path: 600.0)

    async def scenario():
        mon._stop = asyncio.Event()
        await mon._marathon(None)

    asyncio.run(scenario())
    # An unanswered poll is not "offline": capture keeps going on the last URL.
    assert urls == ["u1", "u1"]


def test_prelive_wait_survives_unknown_live_state(tmp_path):
    mon = _monitor(tmp_path, prelive_skip_seconds=120)
    mon._strategy = ScriptedStrategy([RuntimeError("HTTP 503"), (True, "u", None)])

    async def fast_sleep(seconds):
        return None

    mon._interruptible_sleep = fast_sleep

    async def scenario():
        mon._stop = asyncio.Event()
        return await mon._skip_prelive(None)

    assert asyncio.run(scenario()) is True
    assert mon._strategy.calls == 2


def test_provider_backoff_is_exponential_and_capped():
    assert lm.provider_backoff_seconds(60, 0) == 60
    assert lm.provider_backoff_seconds(60, 1) == 120
    assert lm.provider_backoff_seconds(60, 2) == 240
    assert lm.provider_backoff_seconds(60, 50) == lm.PROVIDER_BACKOFF_MAX_SECONDS


# ---------------------------------------------------------------------------
# B. Restart + state restore (I3, I4, I9)
# ---------------------------------------------------------------------------

def test_restarting_a_crashed_monitor_keeps_its_durable_state(tmp_path, monkeypatch):
    from clippyme.storage import config_store

    monkeypatch.setattr(config_store, "load_persistent_config", lambda: {"GEMINI_API_KEY": "g"})
    monkeypatch.setattr(config_store, "load_zernio_config", lambda: {"timezone": "UTC", "api_key": "z"})
    monkeypatch.setattr(LiveMonitor, "_make_strategy", lambda self, cfg, pc: ScriptedStrategy())

    async def crash(self):
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr(LiveMonitor, "_run_live", crash)
    state = tmp_path / "state.json"
    reg = LiveMonitorRegistry(jobs={}, job_queue=None, output_dir=str(tmp_path),
                              state_path=str(state))
    raw = {"platform": "twitch", "channel": "foo", "timezone": "UTC",
           "platforms": [{"platform": "tiktok", "accountId": "a"}]}
    pending = _entry(tmp_path)

    async def scenario():
        reg.start(raw)
        mon = reg._monitors["twitch:foo"]
        mon.publishing_enabled = False
        mon._published.add("/out/job0/a.mp4")
        mon._seen_ids.add("vod-1")
        mon._pending_publish.append(pending)
        mon._covered_stream_start, mon._covered_elapsed = "2026-09-28T10:00:00+00:00", 5400
        await mon._task
        assert not mon.is_running()

        reg.start(raw)  # user restarts the crashed monitor
        fresh = reg._monitors["twitch:foo"]
        assert fresh is not mon
        assert fresh._published == {"/out/job0/a.mp4"}
        assert fresh._seen_ids == {"vod-1"}
        assert [e["job_id"] for e in fresh._pending_publish] == ["job1"]
        assert fresh._covered_elapsed == 5400
        await reg.shutdown()

    asyncio.run(scenario())
    snap = json.loads(state.read_text())["monitors"]["twitch:foo"]
    assert snap["published"] == ["/out/job0/a.mp4"]
    assert snap["seen_ids"] == ["vod-1"]
    assert len(snap["pending_publish"]) == 1
    # Coverage survives → backfill after restart starts past the covered span.
    assert lm.effective_backfill_start(0, snap["covered_elapsed"], snap["covered_stream_start"],
                                       "2026-09-28T10:00:00+00:00") == 5400


def test_corrupt_state_file_is_quarantined_not_silently_overwritten(tmp_path):
    state = tmp_path / "live_monitor.json"
    state.write_text('{"monitors": {"twitch:foo": {"published": ["/a.mp4"]', encoding="utf-8")
    reg = LiveMonitorRegistry(jobs={}, job_queue=None, output_dir=str(tmp_path),
                              state_path=str(state))
    reg.persist()
    kept = list(tmp_path.glob("live_monitor.json.corrupt-*"))
    assert len(kept) == 1 and '"/a.mp4"' in kept[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# C. Publication failure: retryable vs permanent (I1, I10)
# ---------------------------------------------------------------------------

def test_retryable_publish_failure_keeps_the_item_queued(tmp_path, monkeypatch):
    calls = _fake_publisher(monkeypatch, [ZernioError("HTTP 503", status_code=503, body="x")])
    mon = _monitor(tmp_path)
    entry = _entry(tmp_path)

    asyncio.run(mon._publish_one(entry))

    assert len(calls) == 1
    assert not mon._published
    assert len(mon._pending_publish) == 1
    item = mon._pending_publish[0]
    assert item["attempts"] == 1 and item["state"] == "retry_wait"
    assert item["next_retry_at"] > time.time()
    assert "503" in item["last_error"]
    assert mon.snapshot()["pending_publish"][0]["publication_id"] == item["publication_id"]


def test_permanent_publish_failure_is_recorded_not_dropped(tmp_path, monkeypatch):
    _fake_publisher(monkeypatch, [ZernioError("HTTP 400", status_code=400, body="bad caption")])
    mon = _monitor(tmp_path)

    asyncio.run(mon._publish_one(_entry(tmp_path)))

    assert mon._pending_publish == []
    assert len(mon._failed_publish) == 1
    assert mon._failed_publish[0]["state"] == "failed"
    assert mon.snapshot()["failed_publish"] == mon._failed_publish
    assert mon.status()["failed_publish"] == 1


def test_retry_budget_is_bounded(tmp_path, monkeypatch):
    _fake_publisher(monkeypatch, [ZernioError("HTTP 503", status_code=503)])
    mon = _monitor(tmp_path)
    entry = _entry(tmp_path)
    entry["attempts"] = lm.PUBLISH_MAX_ATTEMPTS - 1

    asyncio.run(mon._publish_one(entry))

    assert mon._pending_publish == []
    assert [e["attempts"] for e in mon._failed_publish] == [lm.PUBLISH_MAX_ATTEMPTS]


def test_duplicate_409_counts_as_accepted(tmp_path, monkeypatch):
    _fake_publisher(monkeypatch, [ZernioError("HTTP 409", status_code=409, body="existingPostId")])
    mon = _monitor(tmp_path)
    entry = _entry(tmp_path)

    asyncio.run(mon._publish_one(entry))

    assert mon._pending_publish == [] and mon._failed_publish == []
    assert os.path.join(str(tmp_path), "job1", "c.mp4") in mon._published


def test_drain_does_not_lose_the_head_item_on_failure(tmp_path, monkeypatch):
    calls = _fake_publisher(monkeypatch, [ZernioError("HTTP 502", status_code=502)])

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(lm.asyncio, "sleep", no_sleep)
    mon = _monitor(tmp_path)
    a, b = _entry(tmp_path, "a.mp4"), _entry(tmp_path, "b.mp4")
    mon._pending_publish = [a, b]

    async def stop_on_wait(seconds):
        mon._stop.set()

    mon._interruptible_sleep = stop_on_wait
    asyncio.run(mon._drain_pending())

    assert [os.path.basename(c["clip_path"]) for c in calls] == ["a.mp4", "b.mp4"]
    assert [os.path.basename(e["clip"]["video_url"]) for e in mon._pending_publish] == ["a.mp4"]
    assert mon._pending_publish[0]["attempts"] == 1


def test_publish_error_classification():
    classify = lm.classify_publish_error
    assert classify(ZernioError("net", status_code=None)) == "retry"
    for code in (408, 429, 500, 502, 503, 401, 403):
        assert classify(ZernioError("x", status_code=code)) == "retry", code
    for code in (400, 404, 413, 422):
        assert classify(ZernioError("x", status_code=code)) == "permanent", code
    assert classify(ZernioError("dup", status_code=409)) == "duplicate"
    assert classify(ValueError("clip not found")) == "permanent"
    assert classify(RuntimeError("compose boom")) == "retry"


def test_publish_retry_delay_grows_and_is_capped():
    delays = [lm.publish_retry_delay(n) for n in range(1, 12)]
    assert delays[0] == lm.PUBLISH_RETRY_BASE_SECONDS
    assert all(later >= earlier for earlier, later in zip(delays, delays[1:]))
    assert max(delays) == lm.PUBLISH_RETRY_MAX_SECONDS


# ---------------------------------------------------------------------------
# D. Crash window / idempotency (I2, I8, I9)
# ---------------------------------------------------------------------------

def test_crash_after_provider_accepts_retries_with_the_same_request_id(tmp_path, monkeypatch):
    mon = _monitor(tmp_path)
    # The simulated crash happens before the local commit, so the post-accept
    # artifact cleanup never runs in that timeline.
    mon.cfg["delete_after_publish"] = False
    crash_state = {}

    def accept_then_crash():
        # The provider has accepted; the process dies before the local commit.
        crash_state["snap"] = json.loads(json.dumps(mon.snapshot()))
        return {"post_id": "p1", "status": "scheduled"}

    calls = _fake_publisher(monkeypatch, [accept_then_crash])
    asyncio.run(mon._publish_one(_entry(tmp_path)))

    persisted = crash_state["snap"]["pending_publish"]
    assert len(persisted) == 1 and persisted[0]["state"] == "in_flight"

    fresh = _monitor(tmp_path)
    fresh.restore(crash_state["snap"])
    asyncio.run(fresh._drain_pending())

    assert len(calls) == 2
    assert calls[0]["request_id"] and calls[0]["request_id"] == calls[1]["request_id"]
    assert fresh._pending_publish == []


def test_definite_rejection_rotates_the_request_id(tmp_path, monkeypatch):
    calls = _fake_publisher(monkeypatch, [ZernioError("HTTP 500", status_code=500),
                                          ZernioError("HTTP 401", status_code=401)])
    mon = _monitor(tmp_path)
    entry = _entry(tmp_path)
    asyncio.run(mon._publish_one(entry))                      # 500: outcome unknown
    asyncio.run(mon._publish_one(mon._pending_publish[0]))    # 401: definitely rejected
    asyncio.run(mon._publish_one(mon._pending_publish[0]))
    ids = [c["request_id"] for c in calls]
    assert ids[0] == ids[1] != ids[2]
    assert mon._pending_publish == []
    assert os.path.join(str(tmp_path), "job1", "c.mp4") in mon._published


def test_create_post_sends_the_idempotency_header():
    client = sp.ZernioClient("sk_test")
    captured = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"post": {"_id": "p1"}}

    def fake_request(method, url, **kwargs):
        captured.update(kwargs)
        return Resp()

    client._session.request = fake_request
    client.create_post(content="c", media_items=[], platforms=[],
                       request_id="0b6f3c8e-6a57-4c1e-9d2f-0f5d7a1b2c3d")
    assert captured["headers"]["x-request-id"] == "0b6f3c8e-6a57-4c1e-9d2f-0f5d7a1b2c3d"


def test_publish_clip_still_reads_the_legacy_existing_post_shape(tmp_path, monkeypatch):
    """Legacy fallback: ``{"existingPost": {...}}`` is NOT in the current
    Zernio spec (a replay returns ``{"post": {...}}`` — pinned against the
    vendored spec in integrations/test_zernio_contract.py). Kept so an older
    answer shape still yields the post id instead of a lost acceptance."""
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    seen = {}

    class FakeClient:
        def __init__(self, api_key):
            pass

        def presign_upload(self, *a, **k):
            return {"uploadUrl": "https://u", "publicUrl": "https://p"}

        def upload_to_presigned(self, *a, **k):
            return None

        def create_post(self, **kwargs):
            seen.update(kwargs)
            return {"existingPost": {"_id": "orig", "status": "scheduled"}}

    monkeypatch.setattr(sp, "ZernioClient", FakeClient)
    result = sp.publish_clip(api_key="k", clip_path=str(clip), title="t", caption="c",
                             platform_targets=[{"platform": "tiktok", "accountId": "a"}],
                             request_id="r-1")
    assert seen["request_id"] == "r-1"
    assert result["post_id"] == "orig"


# ---------------------------------------------------------------------------
# E. Segment lifetime / ownership (I7) — interplay with job restart recovery
# ---------------------------------------------------------------------------

def test_segment_job_is_resumable_and_keeps_its_monitor_policy(tmp_path):
    mon = _monitor(tmp_path, max_clips=3, clip_selection="auto", min_viral_score=80)
    seg = tmp_path / "live_twitch_foo_1.mp4"
    seg.write_bytes(b"x")
    jobs = mon._jobs

    async def scenario():
        mon._job_queue = asyncio.Queue()
        return await mon._submit_segment_job(str(seg))

    job_id = asyncio.run(scenario())
    job = jobs[job_id]
    assert job["input_path"] == os.path.abspath(seg)

    # Graceful shutdown mid-job → journal → startup recovery (Goal 1 path).
    job["status"] = "processing"
    record = jj.snapshot(jobs)[job_id]
    assert "GEMINI_API_KEY" not in json.dumps(record)
    recovered = jj._recovered_entry(job_id, record, "resumed")
    assert recovered["env"]["CLIPPYME_MAX_CLIPS"] == "3"
    assert recovered["env"]["CLIPPYME_MIN_VIRAL_SCORE"] == "80"
    assert recovered["env"]["CLIPPYME_CREATOR_NAME"] == "foo"


def test_stop_while_job_active_keeps_segment_and_tracks_the_job(tmp_path, monkeypatch):
    seg = tmp_path / "seg.mp4"
    seg.write_bytes(b"x")
    mon = _monitor(tmp_path, jobs={"j1": {"status": "processing"}})

    async def scenario():
        mon._stop = asyncio.Event()
        mon._stop.set()  # monitor stop / app shutdown while the job still runs
        await mon._await_and_publish("j1", str(seg))

    asyncio.run(scenario())
    assert seg.exists(), "segment deleted while its job still needs it"
    assert mon.snapshot()["inflight_jobs"] == [{"job_id": "j1", "seg_path": str(seg)}]


def test_no_persisted_state_both_queues_and_still_tracks_a_job(tmp_path, monkeypatch):
    """Crash at ANY persist point must not leave a job both in-flight (→ the
    restart re-attaches and re-consolidates it) and already queued (→ drained):
    that pair would publish the same clip twice under two publication ids."""
    _no_compose(monkeypatch)
    (tmp_path / "j1").mkdir()
    (tmp_path / "j1" / "t_clip_1.mp4").write_bytes(b"clip")
    jobs = {"j1": {"status": "completed", "result": {"clips": [
        {"video_url": "/videos/j1/t_clip_1.mp4", "original_index": 0, "title": "T"}]}}}
    persisted = []
    mon = LiveMonitor(id="twitch:foo", jobs=jobs, job_queue=None, output_dir=str(tmp_path),
                      on_state_change=lambda: persisted.append(json.loads(json.dumps(mon.snapshot()))))
    mon.cfg = _cfg()
    mon.publishing_enabled = False  # keep the entry queued; the drain isn't under test
    seg = tmp_path / "seg.mp4"
    seg.write_bytes(b"x")

    async def scenario():
        mon._stop = asyncio.Event()
        mon._inflight_jobs["j1"] = str(seg)
        await mon._await_and_publish("j1", str(seg))

    asyncio.run(scenario())
    assert any(s["pending_publish"] for s in persisted)
    for snap in persisted:
        tracked = {item["job_id"] for item in snap["inflight_jobs"]}
        queued = {entry["job_id"] for entry in snap["pending_publish"]}
        assert not tracked & queued, snap


def test_terminal_job_releases_its_segment(tmp_path):
    seg = tmp_path / "seg.mp4"
    seg.write_bytes(b"x")
    mon = _monitor(tmp_path, jobs={"j1": {"status": "failed"}})

    async def scenario():
        mon._stop = asyncio.Event()
        await mon._await_and_publish("j1", str(seg))

    asyncio.run(scenario())
    assert not seg.exists()
    assert mon.snapshot().get("inflight_jobs", []) == []


# ---------------------------------------------------------------------------
# End-to-end: capture → job → queue → transient failure → restart → retry
# ---------------------------------------------------------------------------

def _wire_e2e(monkeypatch, tmp_path, strategy_factory):
    from clippyme.media import media_probe
    from clippyme.storage import config_store

    monkeypatch.setattr(config_store, "load_persistent_config", lambda: {"GEMINI_API_KEY": "g"})
    monkeypatch.setattr(config_store, "load_zernio_config", lambda: {"timezone": "UTC", "api_key": "z"})
    monkeypatch.setattr(LiveMonitor, "_make_strategy", lambda self, cfg, pc: strategy_factory())
    monkeypatch.setattr(media_probe, "probe_duration", lambda path: 600.0)
    monkeypatch.setattr(lm, "JOB_POLL_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(lm, "PUBLISH_SPACING_SECONDS", 0)
    monkeypatch.setattr(lm, "PUBLISH_RETRY_BASE_SECONDS", 1.0, raising=False)
    _no_compose(monkeypatch)

    async def capture(self, url):
        path = tmp_path / "uploads" / f"live_twitch_foo_{time.time_ns()}.mp4"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"segment")
        return str(path)

    monkeypatch.setattr(LiveMonitor, "_capture_segment", capture)


async def _until(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached before timeout")


def _finish_job(jobs, out, job_id):
    (out / job_id).mkdir(exist_ok=True)
    (out / job_id / "t_clip_1.mp4").write_bytes(b"clip")
    jobs[job_id]["status"] = "completed"
    jobs[job_id]["result"] = {"clips": [{"video_url": f"/videos/{job_id}/t_clip_1.mp4",
                                         "original_index": 0, "title": "T"}]}


@pytest.mark.parametrize("finish_before_shutdown", [True, False])
def test_e2e_publish_survives_transient_failure_and_restart(tmp_path, monkeypatch,
                                                            finish_before_shutdown):
    out = tmp_path / "out"
    out.mkdir()
    state = tmp_path / "live_monitor.json"
    raw = {"platform": "twitch", "channel": "foo", "timezone": "UTC", "loop": True,
           "prelive_skip_seconds": 0, "segment_seconds": 600,
           "platforms": [{"platform": "tiktok", "accountId": "a"}]}

    # --- life 1: live → one segment → job; publish hits a 503 --------------
    _wire_e2e(monkeypatch, tmp_path,
              lambda: ScriptedStrategy([(True, "u", None), (True, "u", None),
                                        (False, None, None)]))
    calls = _fake_publisher(monkeypatch, [ZernioError("HTTP 503", status_code=503)])
    jobs1 = {}

    async def life1():
        reg = LiveMonitorRegistry(jobs=jobs1, job_queue=asyncio.Queue(), output_dir=str(out),
                                  upload_dir=str(tmp_path / "uploads"), state_path=str(state))
        reg.start(raw)
        await _until(lambda: len(jobs1) == 1)
        job_id = next(iter(jobs1))
        seg = jobs1[job_id]["input_path"]
        assert seg and os.path.exists(seg)
        if finish_before_shutdown:
            _finish_job(jobs1, out, job_id)
            mon = reg._monitors["twitch:foo"]
            await _until(lambda: mon._pending_publish and mon._pending_publish[0].get("attempts") == 1)
            assert not os.path.exists(seg)  # job terminal → segment released
        await reg.shutdown()
        return job_id, seg

    job_id, seg = asyncio.run(life1())
    snap = json.loads(state.read_text())["monitors"]["twitch:foo"]
    if finish_before_shutdown:
        assert [e["attempts"] for e in snap["pending_publish"]] == [1]
    else:
        assert os.path.exists(seg), "shutdown deleted the input of a still-running job"
        assert snap["inflight_jobs"] == [{"job_id": job_id, "seg_path": seg}]

    # --- life 2: restart; job (resumed by the job journal) completes --------
    jobs2 = {job_id: {"status": "processing"}}
    if not finish_before_shutdown:
        _finish_job(jobs2, out, job_id)
    else:
        jobs2[job_id]["status"] = "completed"
    _wire_e2e(monkeypatch, tmp_path, lambda: ScriptedStrategy())

    async def life2():
        reg = LiveMonitorRegistry(jobs=jobs2, job_queue=asyncio.Queue(), output_dir=str(out),
                                  upload_dir=str(tmp_path / "uploads"), state_path=str(state))
        await reg.auto_resume()
        mon = reg._monitors["twitch:foo"]
        clip_path = os.path.join(str(out), job_id, "t_clip_1.mp4")
        await _until(lambda: clip_path in mon._published)
        await reg.shutdown()
        return mon

    mon = asyncio.run(life2())
    assert mon._pending_publish == [] and mon._failed_publish == []
    assert mon.clips_published == 1
    assert not os.path.exists(seg)
    final = json.loads(state.read_text())["monitors"]["twitch:foo"]
    assert final["pending_publish"] == [] and final["inflight_jobs"] == []
    # The 503 hit in life 1 (or, when the job was still running at shutdown,
    # in life 2): outcome unknown → the one retry reuses the idempotency key.
    assert len(calls) == 2 and calls[0]["request_id"] == calls[1]["request_id"]
