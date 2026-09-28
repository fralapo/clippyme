"""Live Monitor resilience & publication hardening.

* E1  — a full job queue is backpressure, not a monitor crash.
* E2  — a transient YouTube channel-resolve failure is retried; a bad channel
  and a programming error still stop the monitor, visibly.
* E3  — the shared ``picked_slots`` store forgets slots that can no longer
  influence a pick.
* PF1 — the ``published`` dedup guard stays bounded without letting a queued
  duplicate through, across restarts.
* PF2 — post-accept history/artifact I/O leaves the event loop free while
  keeping the clip serialised.
* G-pub2 — a 409 ``idempotency_conflict`` waits at least its Retry-After.

Concurrency is pinned with Events (threading or asyncio) and fake clocks;
waits carry an upper bound only so a regression fails instead of hanging.
"""
import asyncio
import json
import os
import random
import threading
import types
from datetime import datetime, timedelta, timezone

import pytest

from clippyme.monitoring import live_monitor as lm
from clippyme.clips.clip_locks import clip_lock
from clippyme.monitoring.live_monitor import (
    LiveMonitor, LiveMonitorRegistry, SharedGapScheduler, validate_monitor_config,
)
from clippyme.integrations import social_publisher as sp
from clippyme.integrations.social_publisher import ZernioError

from .test_live_monitor_reliability import (
    ScriptedStrategy, _entry, _fake_publisher, _monitor, _until, _wire_e2e,
)


def _fake_clock(monkeypatch, start=1_000_000.0):
    clock = [start]
    monkeypatch.setattr(lm, "time", types.SimpleNamespace(time=lambda: clock[0]))
    return clock


def _conflict(retry_after=None):
    exc = ZernioError("Zernio POST /posts → HTTP 409", status_code=409,
                      body='{"error":"Request in progress","code":"idempotency_conflict"}',
                      code="idempotency_conflict")
    exc.retry_after = retry_after
    return exc


def _segment_monitor(tmp_path, monkeypatch, queue):
    from clippyme.media import media_probe

    monkeypatch.setattr(media_probe, "probe_duration", lambda path: 600.0)
    jobs = {}
    mon = _monitor(tmp_path, jobs=jobs)
    mon._job_queue = queue
    seg = tmp_path / "live_twitch_foo_1.mp4"

    async def capture(url):
        seg.write_bytes(b"segment")
        return str(seg)

    handed = []

    async def await_and_publish(job_id, seg_path):
        handed.append(job_id)

    mon._capture_segment = capture
    mon._await_and_publish = await_and_publish
    return mon, jobs, seg, handed


# ---------------------------------------------------------------------------
# E1 — QueueFullError
# ---------------------------------------------------------------------------

def test_full_job_queue_is_backpressure_not_a_monitor_crash(tmp_path, monkeypatch):
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait("someone-elses-job")
    mon, jobs, seg, handed = _segment_monitor(tmp_path, monkeypatch, queue)
    mon._strategy = ScriptedStrategy([(True, "u", None), (True, "u", None), (False, None, None)])
    waits = []

    async def fake_sleep(seconds):
        waits.append((seconds, mon.last_error, dict(jobs)))
        if len(waits) == 1:
            queue.get_nowait()          # a worker picks up the other job
        else:
            mon._stop.set()

    mon._interruptible_sleep = fake_sleep

    async def scenario():
        mon._stop = asyncio.Event()
        await mon._run()

    asyncio.run(scenario())

    delay, error_while_waiting, jobs_while_waiting = waits[0]
    assert delay == lm.queue_full_retry_delay(1) > 0          # no tight loop
    assert error_while_waiting.startswith("job queue full")   # visible meanwhile
    assert jobs_while_waiting == {}                           # the rejected job rolled back
    assert len(jobs) == 1                                     # submitted exactly once
    job_id = next(iter(jobs))
    assert jobs[job_id]["input_path"] == os.path.abspath(seg)
    assert queue.get_nowait() == job_id
    assert handed == [job_id] and mon._inflight_jobs == {job_id: str(seg)}
    assert seg.exists() and mon.segments_captured == 1
    assert mon._strategy.calls == 3                          # kept watching the stream
    assert mon.last_error is None


def test_stop_while_the_queue_is_full_discards_the_unsubmitted_segment(tmp_path, monkeypatch):
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait("busy")
    mon, jobs, seg, handed = _segment_monitor(tmp_path, monkeypatch, queue)
    mon._strategy = ScriptedStrategy([(True, "u", None)])

    async def stop_on_wait(seconds):
        mon._stop.set()

    mon._interruptible_sleep = stop_on_wait

    async def scenario():
        mon._stop = asyncio.Event()
        await mon._marathon(None)

    asyncio.run(scenario())
    assert jobs == {} and handed == [] and mon._inflight_jobs == {}
    assert not seg.exists()             # no job will ever read it: released, not leaked
    assert mon.segments_captured == 0
    assert mon.last_error.startswith("job queue full")


def test_queue_full_wait_answers_stop_and_cancel(tmp_path, monkeypatch):
    for how in ("stop", "cancel"):
        queue = asyncio.Queue(maxsize=1)
        queue.put_nowait("busy")
        mon, jobs, seg, _ = _segment_monitor(tmp_path, monkeypatch, queue)
        mon._strategy = ScriptedStrategy([(True, "u", None)])
        monkeypatch.setattr(lm, "JOB_POLL_SECONDS", 3600)   # the real wait would be long

        async def scenario():
            mon._stop = asyncio.Event()
            task = asyncio.create_task(mon._marathon(None))
            await _until(lambda: task.done() or (mon.last_error or "").startswith("job queue full"))
            assert not task.done(), task
            if how == "stop":
                mon._stop.set()
                await asyncio.wait_for(task, 5)
            else:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)

        asyncio.run(scenario())
        assert jobs == {}


def test_queue_full_on_a_vod_item_keeps_it_for_a_later_poll(tmp_path, monkeypatch):
    item = {"id": "new", "url": "https://www.youtube.com/watch?v=abcdefghijk"}
    old = {"id": "old", "url": "https://www.youtube.com/watch?v=00000000000"}

    class Feed:
        def __init__(self, polls):
            self.polls = list(polls)

        def fetch_vods(self):
            return self.polls.pop(0) if self.polls else [item, old]

    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait("busy")
    jobs = {}
    mon = _monitor(tmp_path, jobs=jobs, mode="vod")
    mon.mode = "vod"
    mon._job_queue = queue
    mon._strategy = Feed([[old], [item, old]])
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(mon.snapshot()["seen_ids"])
        if len(sleeps) >= 2:
            mon._stop.set()

    mon._interruptible_sleep = fake_sleep

    async def scenario(m):
        m._stop = asyncio.Event()
        await m._run()

    asyncio.run(scenario(mon))
    # Any persist while waiting (the drain persists too) must not mark the
    # item handled: a crash then would lose it for good.
    assert sleeps[1] == ["old"]
    assert jobs == {}
    assert mon.last_error.startswith("job queue full")
    assert "new" not in mon._seen_ids                    # not consumed by the failed submit
    snap = json.loads(json.dumps(mon.snapshot()))
    assert snap["seen_ids"] == ["old"]

    # Restart with room in the queue: the item is picked up, once.
    fresh = _monitor(tmp_path, jobs=jobs, mode="vod")
    fresh.mode = "vod"
    fresh.restore(snap)
    fresh._job_queue = asyncio.Queue()
    fresh._strategy = Feed([])
    handed = []

    async def no_publish(job_id, seg_path):
        handed.append(job_id)

    async def stop_now(seconds):
        fresh._stop.set()

    fresh._await_and_publish = no_publish
    fresh._interruptible_sleep = stop_now
    asyncio.run(scenario(fresh))
    assert len(jobs) == 1 and handed == list(jobs)
    assert "new" in fresh._seen_ids


def test_queue_full_during_backfill_keeps_the_window_pending(tmp_path, monkeypatch):
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait("busy")
    mon, jobs, seg, _ = _segment_monitor(tmp_path, monkeypatch, queue)
    mon._missed_windows = [(0, 600)]

    async def download(vod_url, t1, t2):
        seg.write_bytes(b"window")
        return str(seg)

    async def stop_on_wait(seconds):
        mon._stop.set()

    mon._download_vod_range = download
    mon._interruptible_sleep = stop_on_wait

    async def scenario():
        mon._stop = asyncio.Event()
        await mon._backfill_windows("https://vod", [(0, 600)])

    asyncio.run(scenario())
    assert jobs == {}
    assert mon._missed_windows == [(0, 600)] and mon.backfill_pending == 1
    assert not seg.exists()


# ---------------------------------------------------------------------------
# E2 — YouTube channel resolution
# ---------------------------------------------------------------------------

class _Resolver:
    def __init__(self, errors, forever=None):
        self.errors = list(errors)
        self.forever = forever
        self.resolves = 0
        self.fetches = 0

    def resolve(self):
        self.resolves += 1
        if self.forever is not None:
            raise self.forever
        if self.errors:
            raise self.errors.pop(0)

    def fetch_vods(self):
        self.fetches += 1
        return []


def _youtube_monitor(tmp_path, strategy):
    mon = LiveMonitor(id="youtube:abc", jobs={}, job_queue=None, output_dir=str(tmp_path))
    mon.cfg = validate_monitor_config(
        {"platform": "youtube", "mode": "vod", "channel": "@creator", "timezone": "UTC",
         "platforms": [{"platform": "tiktok", "accountId": "a"}]}, default_timezone="UTC")
    mon.platform, mon.mode = "youtube", "vod"
    mon._strategy = strategy
    return mon


def test_transient_channel_resolve_failure_is_retried_with_backoff(tmp_path):
    from yt_dlp.utils import DownloadError

    strategy = _Resolver([OSError("dns failure"), DownloadError("HTTP Error 503")])
    mon = _youtube_monitor(tmp_path, strategy)
    waits = []

    async def fake_sleep(seconds):
        waits.append((seconds, mon.last_error))
        if strategy.fetches:
            mon._stop.set()

    mon._interruptible_sleep = fake_sleep

    async def scenario():
        mon._stop = asyncio.Event()
        await mon._run()

    asyncio.run(scenario())
    poll = mon.cfg["poll_interval"]
    assert strategy.resolves == 3 and strategy.fetches == 1
    assert [w for w, _ in waits[:2]] == [lm.provider_backoff_seconds(poll, 1),
                                         lm.provider_backoff_seconds(poll, 2)]
    assert waits[0][1].startswith("channel resolve failed (1x)")
    assert waits[1][1].startswith("channel resolve failed (2x)")
    assert mon.last_error is None           # cleared once the channel resolved


def test_invalid_channel_stops_the_monitor_with_a_visible_error(tmp_path):
    strategy = _Resolver([ValueError("YouTube channel URLs must use HTTPS")])
    mon = _youtube_monitor(tmp_path, strategy)

    async def no_sleep(seconds):
        raise AssertionError("a permanent error must not be retried")

    mon._interruptible_sleep = no_sleep

    async def scenario():
        mon._stop = asyncio.Event()
        await mon._run()

    asyncio.run(scenario())
    assert strategy.resolves == 1 and strategy.fetches == 0
    assert mon.last_error == "channel resolve failed: YouTube channel URLs must use HTTPS"
    assert mon.state == "idle"


def test_programming_error_in_resolve_is_not_mistaken_for_an_outage(tmp_path):
    strategy = _Resolver([TypeError("unexpected None")])
    mon = _youtube_monitor(tmp_path, strategy)

    async def no_sleep(seconds):
        raise AssertionError("a bug must not be retried as transient")

    mon._interruptible_sleep = no_sleep

    async def scenario():
        mon._stop = asyncio.Event()
        await mon._run()

    asyncio.run(scenario())
    assert strategy.resolves == 1
    assert mon.last_error == "monitor loop crashed"


def test_resolve_backoff_answers_stop_and_cancel(tmp_path):
    for how in ("stop", "cancel"):
        strategy = _Resolver([], forever=OSError("network unreachable"))
        mon = _youtube_monitor(tmp_path, strategy)
        mon.cfg["poll_interval"] = 3600

        async def scenario():
            mon._stop = asyncio.Event()
            task = asyncio.create_task(mon._run_vod())
            await _until(lambda: task.done() or strategy.resolves >= 1
                         and (mon.last_error or "").startswith("channel resolve failed"))
            await asyncio.sleep(0)
            assert not task.done(), task
            if how == "stop":
                mon._stop.set()
                await asyncio.wait_for(task, 5)
            else:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)

        asyncio.run(scenario())
        assert strategy.fetches == 0 and strategy.resolves == 1


# ---------------------------------------------------------------------------
# E3 — picked_slots retention
# ---------------------------------------------------------------------------

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def test_prune_picked_slots_retention_boundary():
    keep = lm.PICKED_SLOT_RETENTION_SECONDS
    inside = NOW - timedelta(seconds=keep - 1)
    outside = NOW - timedelta(seconds=keep + 1)
    future = NOW + timedelta(hours=3)
    slots = [outside, future, inside, outside - timedelta(days=3)]

    lm.prune_picked_slots(slots, NOW, min_gap_seconds=900)

    assert slots == [future, inside]            # order kept, in place


def test_prune_picked_slots_keeps_whatever_a_longer_gap_still_sees():
    old = NOW - timedelta(seconds=lm.PICKED_SLOT_RETENTION_SECONDS + 3600)
    slots = [old]
    lm.prune_picked_slots(slots, NOW, min_gap_seconds=2 * lm.PICKED_SLOT_RETENTION_SECONDS)
    assert slots == [old]


def test_prune_picked_slots_handles_naive_legacy_stamps():
    stale = (NOW - timedelta(days=5)).replace(tzinfo=None)
    fresh = (NOW + timedelta(hours=1)).replace(tzinfo=None)
    slots = [stale, fresh]
    lm.prune_picked_slots(slots, NOW, min_gap_seconds=900)
    assert slots == [fresh]


def test_pruning_never_changes_the_slot_the_scheduler_picks():
    src = random.Random(20260928)
    for trial in range(300):
        now = NOW.replace(hour=src.randint(0, 23), minute=src.randint(0, 59))
        slots = [now + timedelta(minutes=src.randint(-4 * 1440, 2 * 1440)) for _ in range(40)]
        gap = src.choice([0, 900, 5400, 86400])
        later = now + timedelta(minutes=src.randint(0, 600))   # find_slot runs after the prune
        day = (later + timedelta(days=src.choice([0, 0, 1]))).date()
        pruned = list(slots)
        lm.prune_picked_slots(pruned, now, min_gap_seconds=gap)
        full = SharedGapScheduler(min_gap_seconds=gap, picked_slots=list(slots),
                                  rng=random.Random(trial))
        lean = SharedGapScheduler(min_gap_seconds=gap, picked_slots=pruned,
                                  rng=random.Random(trial))
        assert full.find_slot(day, [], now=later) == lean.find_slot(day, [], now=later), trial


def _slot_monitor(tmp_path, monkeypatch, shared, outcome):
    now = datetime.now(timezone.utc)
    mon = _monitor(tmp_path)
    mon._picked_slots = shared
    mon._scheduler = SharedGapScheduler(min_gap_seconds=900, picked_slots=shared)
    reserved = now + timedelta(hours=9)

    def fake_publish(**kw):
        kw["scheduler"].picked_slots.append(reserved)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(sp, "publish_clip", fake_publish)
    return mon, reserved


def test_each_publish_prunes_the_shared_slot_store(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    stale = [now - timedelta(days=d) for d in range(2, 502)]
    live = [now - timedelta(hours=1), now + timedelta(hours=5)]
    shared = stale + live
    mon, reserved = _slot_monitor(tmp_path, monkeypatch, shared, {"post_id": "p1"})

    asyncio.run(mon._publish_one(_entry(tmp_path)))

    assert shared == live + [reserved]


def test_rejected_publish_frees_its_slot_after_the_prune(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    live = [now + timedelta(hours=5)]
    shared = [now - timedelta(days=d) for d in range(2, 12)] + live
    mon, _ = _slot_monitor(tmp_path, monkeypatch, shared,
                           ZernioError("HTTP 400", status_code=400, body="bad"))

    asyncio.run(mon._publish_one(_entry(tmp_path)))

    assert shared == live                      # reserved slot released, stale ones gone


# ---------------------------------------------------------------------------
# PF1 — the published dedup guard
# ---------------------------------------------------------------------------

def _clip_key(tmp_path, job, name="c.mp4"):
    return os.path.join(str(tmp_path), job, name)


def test_published_guard_stays_bounded_on_a_long_running_monitor(tmp_path, monkeypatch):
    clock = _fake_clock(monkeypatch)
    _fake_publisher(monkeypatch)
    mon = _monitor(tmp_path)
    mon.cfg["delete_after_publish"] = False
    counts, sizes = [], []
    for i in range(96):                        # four days, one clip an hour
        clock[0] += 3600
        asyncio.run(mon._publish_one(_entry(tmp_path, job=f"job{i:03d}")))
        snap = mon.snapshot()
        counts.append(len(snap["published"]))
        sizes.append(len(json.dumps({k: snap[k] for k in ("published", "published_at")})))

    assert mon.clips_published == 96
    per_day = lm.PUBLISHED_RETENTION_SECONDS // 3600
    assert max(counts) == per_day + 1          # one window of acceptances, no more
    assert counts[-1] == counts[per_day + 1]
    assert sizes[-1] == sizes[per_day + 1]     # the persisted guard stops growing
    assert set(mon.snapshot()["published"]) == mon._published


def test_published_guard_outlives_the_window_while_its_job_is_queued(tmp_path, monkeypatch):
    """A duplicate entry for an accepted clip (other publication id) must be
    skipped however late it is drained, restart included."""
    clock = _fake_clock(monkeypatch)
    calls = _fake_publisher(monkeypatch)
    mon = _monitor(tmp_path)
    mon.cfg["delete_after_publish"] = False
    first = LiveMonitor._as_publication(_entry(tmp_path, job="jobA"))
    dup = LiveMonitor._as_publication(_entry(tmp_path, job="jobA"))
    assert first["publication_id"] != dup["publication_id"]
    mon._pending_publish = [first, dup]

    asyncio.run(mon._publish_one(first))
    clock[0] += 3 * lm.PUBLISHED_RETENTION_SECONDS
    asyncio.run(mon._publish_one(_entry(tmp_path, "b.mp4", job="jobB")))   # prunes
    snap = json.loads(json.dumps(mon.snapshot()))

    fresh = _monitor(tmp_path)
    fresh.restore(snap)
    asyncio.run(fresh._drain_pending())

    assert [os.path.basename(os.path.dirname(c["clip_path"])) for c in calls] == ["jobA", "jobB"]
    assert fresh._pending_publish == []
    assert _clip_key(tmp_path, "jobA") in snap["published"]    # kept: jobA still queued


def test_recent_acceptance_survives_restart_then_expires(tmp_path, monkeypatch):
    clock = _fake_clock(monkeypatch)
    _fake_publisher(monkeypatch)
    mon = _monitor(tmp_path)
    mon.cfg["delete_after_publish"] = False
    asyncio.run(mon._publish_one(_entry(tmp_path, job="jobA")))
    clock[0] += 3600
    fresh = _monitor(tmp_path)
    fresh.restore(json.loads(json.dumps(mon.snapshot())))
    assert _clip_key(tmp_path, "jobA") in fresh._published          # inside the window

    clock[0] += lm.PUBLISHED_RETENTION_SECONDS
    asyncio.run(fresh._publish_one(_entry(tmp_path, job="jobB")))
    assert _clip_key(tmp_path, "jobA") not in fresh._published      # expired, unreferenced
    assert _clip_key(tmp_path, "jobB") in fresh._published


def test_legacy_published_list_without_times_is_kept_one_window(tmp_path, monkeypatch):
    clock = _fake_clock(monkeypatch)
    _fake_publisher(monkeypatch)
    mon = _monitor(tmp_path)
    mon.cfg["delete_after_publish"] = False
    mon.restore({"published": ["/out/legacy/a.mp4"]})
    asyncio.run(mon._publish_one(_entry(tmp_path, job="jobA")))
    assert "/out/legacy/a.mp4" in mon._published
    clock[0] += lm.PUBLISHED_RETENTION_SECONDS + 1
    asyncio.run(mon._publish_one(_entry(tmp_path, job="jobB")))
    assert "/out/legacy/a.mp4" not in mon._published


# ---------------------------------------------------------------------------
# PF2 — post-accept I/O off the event loop, clip still serialised
# ---------------------------------------------------------------------------

def _two_clip_job(tmp_path):
    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "c.mp4").write_bytes(b"x")
    (job_dir / "d.mp4").write_bytes(b"x")
    (job_dir / "run_metadata.json").write_text(json.dumps({"shorts": [
        {"video_url": "/videos/job1/c.mp4"}, {"video_url": "/videos/job1/d.mp4"}]}))
    return job_dir


def test_post_accept_io_frees_the_loop_but_not_the_clip(tmp_path, monkeypatch):
    job_dir = _two_clip_job(tmp_path)
    _fake_publisher(monkeypatch)
    mon = _monitor(tmp_path, jobs={"job1": {"status": "completed"}})
    clip = {"video_url": "/videos/job1/c.mp4", "title": "T", "original_index": 0}
    entry = {"job_id": "job1", "clip": clip, "composed_path": str(job_dir / "c.mp4")}
    cleanup_started, release = threading.Event(), threading.Event()
    other_clip_ran, same_clip_acquired = threading.Event(), threading.Event()
    seen = {}
    real_mark = LiveMonitor._mark_clip_deleted

    def blocking_mark(self, job_id, idx):
        cleanup_started.set()
        seen["released_in_time"] = release.wait(5)
        real_mark(self, job_id, idx)

    monkeypatch.setattr(LiveMonitor, "_mark_clip_deleted", blocking_mark)

    async def same_clip():
        async with clip_lock(str(job_dir), 0):
            same_clip_acquired.set()
            seen["raw_on_disk_when_acquired"] = (job_dir / "c.mp4").exists()

    async def other_clip():
        async with clip_lock(str(job_dir), 1):
            other_clip_ran.set()

    async def scenario():
        publish = asyncio.create_task(mon._publish_one(entry))
        assert await asyncio.to_thread(cleanup_started.wait, 5)
        contender = asyncio.create_task(same_clip())
        bystander = asyncio.create_task(other_clip())
        seen["other_clip_ran"] = await asyncio.to_thread(other_clip_ran.wait, 5)
        seen["same_clip_before_release"] = same_clip_acquired.is_set()
        release.set()
        await asyncio.wait_for(asyncio.gather(publish, contender, bystander), 10)

    asyncio.run(scenario())
    assert seen["released_in_time"], "post-accept I/O blocked the event loop"
    assert seen["other_clip_ran"]
    assert seen["same_clip_before_release"] is False, "clip lock released before cleanup"
    assert seen["raw_on_disk_when_acquired"] is False      # no use-after-delete window
    meta = json.loads((job_dir / "run_metadata.json").read_text())
    assert meta["shorts"][0]["deleted_after_publish"] is True
    assert mon._pending_publish == [] and mon.clips_published == 1


def test_accept_still_records_the_monitor_publish(tmp_path, monkeypatch):
    from clippyme.jobs import job_artifacts

    job_dir = _two_clip_job(tmp_path)
    _fake_publisher(monkeypatch)
    records = []
    loop_thread = []

    def spy(job_id, idx, output_dir, record):
        loop_thread.append(threading.current_thread() is threading.main_thread())
        records.append((job_id, idx, record["source"], record["post_id"]))

    monkeypatch.setattr(job_artifacts, "record_clip_publish", spy)
    mon = _monitor(tmp_path, jobs={"job1": {"status": "completed"}})
    clip = {"video_url": "/videos/job1/c.mp4", "title": "T", "original_index": 0}
    asyncio.run(mon._publish_one({"job_id": "job1", "clip": clip,
                                  "composed_path": str(job_dir / "c.mp4")}))
    assert records == [("job1", 0, "monitor:twitch:foo", "p1")]
    assert loop_thread == [False]                  # written off the event loop


# ---------------------------------------------------------------------------
# G-pub2 — Retry-After on 409 idempotency_conflict
# ---------------------------------------------------------------------------

def test_zernio_error_carries_the_retry_after_header():
    client = sp.ZernioClient("sk_test")

    class Resp:
        status_code = 409
        headers = {"Retry-After": "120"}
        text = '{"code":"idempotency_conflict"}'

        def json(self):
            return {"code": "idempotency_conflict"}

    client._session.request = lambda method, url, **kw: Resp()
    with pytest.raises(ZernioError) as caught:
        client.create_post(content="c", media_items=[], platforms=[], request_id="k")
    assert lm.retry_after_seconds(caught.value) == 120


BASE = 60  # publish_retry_delay(1)


@pytest.mark.parametrize("header,expected", [
    ("600", 600),                                  # honoured
    ("1e9", lm.PUBLISH_RETRY_MAX_SECONDS),         # absurd → capped inside the key window
    ("30", BASE),                                  # never shortens the backoff
    (None, BASE), ("0", BASE), ("-5", BASE), ("soon", BASE),
    ("Wed, 21 Oct 2026 07:28:00 GMT", BASE),       # HTTP-date: not parsed → backoff
])
def test_idempotency_conflict_waits_at_least_its_retry_after(tmp_path, monkeypatch, header, expected):
    assert lm.publish_retry_delay(1) == BASE
    clock = _fake_clock(monkeypatch)
    _fake_publisher(monkeypatch, [_conflict(header)])
    mon = _monitor(tmp_path)
    entry = LiveMonitor._as_publication(_entry(tmp_path))
    key = entry["request_id"]

    asyncio.run(mon._publish_one(entry))

    assert entry["state"] == "retry_wait" and entry["attempts"] == 1
    assert entry["next_retry_at"] - clock[0] == expected
    assert entry["request_id"] == key                 # conflict never rotates the key
    assert mon._published == set()


def test_retry_wait_deadline_survives_a_restart(tmp_path, monkeypatch):
    clock = _fake_clock(monkeypatch)
    calls = []

    def fake_publish(**kw):
        calls.append((clock[0], kw["request_id"]))
        if len(calls) == 1:
            raise _conflict("900")
        return {"post_id": "p1", "status": "scheduled"}

    monkeypatch.setattr(sp, "publish_clip", fake_publish)
    mon = _monitor(tmp_path)
    mon.cfg["delete_after_publish"] = False
    persisted = []
    mon._on_state_change = lambda: persisted.append(json.loads(json.dumps(mon.snapshot())))
    asyncio.run(mon._publish_one(_entry(tmp_path)))
    deadline = persisted[-1]["pending_publish"][0]["next_retry_at"]
    assert deadline == clock[0] + 900

    fresh = _monitor(tmp_path)
    fresh.cfg["delete_after_publish"] = False
    fresh.restore(persisted[-1])
    waits = []

    async def advance(seconds):
        waits.append(seconds)
        clock[0] += seconds

    fresh._interruptible_sleep = advance
    asyncio.run(fresh._drain_pending())

    assert waits == [900]
    assert calls[1][0] >= deadline and calls[1][1] == calls[0][1]
    assert fresh._pending_publish == [] and fresh.clips_published == 1


# ---------------------------------------------------------------------------
# Integrated lifecycle: queue full → submit → job → 409 conflict → restart
# → wait out Retry-After → same key → accepted → record + cleanup
# ---------------------------------------------------------------------------

def test_goal8_lifecycle_across_backpressure_conflict_and_restart(tmp_path, monkeypatch):
    import time as real_time

    from clippyme.jobs import job_artifacts

    records = []
    real_record = job_artifacts.record_clip_publish

    def recording(job_id, idx, output_dir, record):
        real_record(job_id, idx, output_dir, record)
        records.append(job_artifacts.load_job_metadata(job_id, output_dir)[1]["shorts"][idx])

    monkeypatch.setattr(job_artifacts, "record_clip_publish", recording)
    out = tmp_path / "out"
    out.mkdir()
    state = tmp_path / "live_monitor.json"
    raw = {"platform": "twitch", "channel": "foo", "timezone": "UTC", "loop": True,
           "prelive_skip_seconds": 0, "segment_seconds": 600,
           "platforms": [{"platform": "tiktok", "accountId": "a"}]}
    _wire_e2e(monkeypatch, tmp_path,
              lambda: ScriptedStrategy([(True, "u", None), (True, "u", None),
                                        (False, None, None)]))
    calls = []

    def fake_publish(**kw):
        calls.append((real_time.time(), kw["request_id"]))
        if len(calls) == 1:
            raise _conflict("2")
        return {"post_id": "p1", "status": "scheduled", "scheduled_for": "2026-09-29T19:00:00"}

    monkeypatch.setattr(sp, "publish_clip", fake_publish)
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait("someone-elses-job")
    jobs1 = {}

    async def life1():
        reg = LiveMonitorRegistry(jobs=jobs1, job_queue=queue, output_dir=str(out),
                                  upload_dir=str(tmp_path / "uploads"), state_path=str(state))
        reg.start(raw)
        mon = reg._monitors["twitch:foo"]
        await _until(lambda: (mon.last_error or "").startswith("job queue full"))
        assert mon.is_running() and jobs1 == {}
        queue.get_nowait()                                 # a worker frees a slot
        await _until(lambda: len(jobs1) == 1)
        job_id = next(iter(jobs1))
        job_dir = out / job_id
        job_dir.mkdir(exist_ok=True)
        (job_dir / "t_clip_1.mp4").write_bytes(b"clip")
        (job_dir / "run_metadata.json").write_text(json.dumps(
            {"shorts": [{"video_url": f"/videos/{job_id}/t_clip_1.mp4", "title": "T"}]}))
        jobs1[job_id]["status"] = "completed"
        jobs1[job_id]["result"] = {"clips": [{"video_url": f"/videos/{job_id}/t_clip_1.mp4",
                                              "original_index": 0, "title": "T"}]}
        await _until(lambda: mon._pending_publish
                     and mon._pending_publish[0].get("state") == "retry_wait")
        await reg.shutdown()
        return job_id

    job_id = asyncio.run(life1())
    snap = json.loads(state.read_text())["monitors"]["twitch:foo"]
    [waiting] = snap["pending_publish"]
    assert waiting["state"] == "retry_wait" and len(calls) == 1

    jobs2 = {job_id: {"status": "completed"}}
    _wire_e2e(monkeypatch, tmp_path, lambda: ScriptedStrategy())   # channel offline now

    async def life2():
        reg = LiveMonitorRegistry(jobs=jobs2, job_queue=asyncio.Queue(), output_dir=str(out),
                                  upload_dir=str(tmp_path / "uploads"), state_path=str(state))
        await reg.auto_resume()
        mon = reg._monitors["twitch:foo"]
        await _until(lambda: mon.clips_published == 1)
        assert mon.is_running()                            # still watching afterwards
        await reg.shutdown()
        return mon

    mon = asyncio.run(life2())
    assert len(calls) == 2
    assert calls[1][0] >= waiting["next_retry_at"]         # nothing before the deadline
    assert calls[1][1] == calls[0][1] == waiting["request_id"]
    assert mon._pending_publish == [] and mon._failed_publish == []
    [published] = [r for r in records[0]["published"]]     # history written before cleanup
    assert published["source"] == "monitor:twitch:foo" and published["post_id"] == "p1"
    assert not (out / job_id).exists()                     # artifacts cleaned up
    final = json.loads(state.read_text())["monitors"]["twitch:foo"]
    assert final["pending_publish"] == [] and final["inflight_jobs"] == []
