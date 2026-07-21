"""Tests for clippyme.domain.live_monitor pure helpers + config validation.

No curl_cffi / ffmpeg / event loop needed — LiveMonitor.__init__ is cheap and
the helpers under test are pure.
"""
from datetime import date, datetime, timezone

import pytest

from clippyme.domain.errors import ConflictError, ValidationError
from clippyme.domain.live_monitor import (
    LiveMonitorRegistry,
    SharedGapScheduler,
    backfill_windows,
    build_backfill_cmd,
    build_monitor_compose,
    remaining_prelive,
    render_template,
    should_process_segment,
    validate_monitor_config,
    _hhmmss,
)
from clippyme.integrations.twitch_client import find_live_vod


# --- build_monitor_compose (monitor auto-publish recipe) -------------------

def test_build_monitor_compose_defaults():
    clip = {"viral_hook_text": "Wait for it", "title": "T"}
    recipe = build_monitor_compose("kick", "grenbaud", clip, None)
    assert recipe["toggles"] == {"hook": True, "subtitles": True, "banner": True}
    assert recipe["hook_params"]["position"] == "top"
    assert recipe["hook_params"]["text"] == "Wait for it"
    # subtitles below the banner, left-aligned
    assert recipe["subtitle_params"] == {"position": "bottom", "align": "left"}
    # banner auto-injected from the monitor's platform + channel
    assert recipe["banner_params"]["platform"] == "kick"
    assert recipe["banner_params"]["handle"] == "grenbaud"
    assert recipe["banner_params"]["enabled"] is True


def test_build_monitor_compose_no_hook_text_disables_hook():
    recipe = build_monitor_compose("twitch", "chan", {}, None)
    assert recipe["toggles"]["hook"] is False


def test_build_monitor_compose_banner_override_disables():
    recipe = build_monitor_compose("kick", "grenbaud", {"viral_hook_text": "x"},
                                   {"banner": {"enabled": False}})
    assert recipe["toggles"]["banner"] is False
    assert recipe["banner_params"] == {}


def test_build_monitor_compose_subtitle_override_merges():
    recipe = build_monitor_compose("kick", "grenbaud", {"viral_hook_text": "x"},
                                   {"subtitle_params": {"align": "center"}})
    assert recipe["subtitle_params"]["align"] == "center"
    assert recipe["subtitle_params"]["position"] == "bottom"  # default kept


def test_validate_monitor_config_carries_banner_and_compose():
    cfg = validate_monitor_config({
        "platform": "kick", "mode": "live", "slug": "grenbaud",
        "platforms": [{"platform": "tiktok", "accountId": "acc"}],
        "banner": {"enabled": False},
        "compose": {"subtitle_params": {"align": "center"}},
    })
    assert cfg["banner"] == {"enabled": False}
    assert cfg["compose"] == {"subtitle_params": {"align": "center"}}


# --- should_process_segment ------------------------------------------------

def test_should_process_segment_floor():
    assert should_process_segment(1800) is True
    assert should_process_segment(300) is True      # exactly 5 min → keep
    assert should_process_segment(299) is False     # just under → drop
    assert should_process_segment(0) is False
    assert should_process_segment(None) is False


# --- remaining_prelive -------------------------------------------------------

def test_remaining_prelive_none_started_at_falls_back_to_full_window():
    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    assert remaining_prelive(1800, None, now) == 1800


def test_remaining_prelive_fresh_stream_returns_partial():
    now = datetime(2026, 7, 21, 12, 10, tzinfo=timezone.utc)  # 10 min in
    started = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    assert remaining_prelive(1800, started, now) == 1200  # 30 - 10 min left


def test_remaining_prelive_already_old_stream_returns_zero():
    now = datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc)  # 2h in
    started = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    assert remaining_prelive(1800, started, now) == 0


def test_remaining_prelive_exactly_at_boundary():
    now = datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc)
    started = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    assert remaining_prelive(1800, started, now) == 0


# --- render_template -------------------------------------------------------

def test_render_template_fills_placeholders():
    clip = {"title": "My Clip", "viral_hook_text": "Wait for it"}
    assert render_template("{title} — {hook}", clip) == "My Clip — Wait for it"


def test_render_template_empty_and_bad():
    assert render_template("", {}) == ""
    # Unknown placeholder → falls back to raw template, never raises.
    assert render_template("{nope}", {"title": "x"}) == "{nope}"


# --- SharedGapScheduler ----------------------------------------------------

def test_shared_gap_scheduler_enforces_spacing_across_picks():
    sched = SharedGapScheduler(min_gap_seconds=900)
    day = date(2026, 7, 21)  # a Tuesday with wide prime-time windows
    now = datetime(2026, 7, 21, 7, 0)
    slots = [sched.find_slot(day, [], now=now) for _ in range(5)]
    # Every pair of monitor-picked slots respects the 15-minute minimum gap.
    for i in range(len(slots)):
        for j in range(i + 1, len(slots)):
            assert abs((slots[i] - slots[j]).total_seconds()) >= 900
    assert len(sched.picked_slots) == 5


def test_shared_gap_scheduler_merges_external_occupied():
    sched = SharedGapScheduler(min_gap_seconds=900)
    day = date(2026, 7, 21)
    now = datetime(2026, 7, 21, 7, 0)
    external = datetime(2026, 7, 21, 10, 0)
    slot = sched.find_slot(day, [external], now=now)
    assert abs((slot - external).total_seconds()) >= 900


# --- validate_monitor_config -----------------------------------------------

def _base_cfg(**over):
    cfg = {"slug": "somechannel", "platforms": [{"platform": "tiktok", "accountId": "acc1"}]}
    cfg.update(over)
    return cfg


def test_validate_config_defaults():
    cfg = validate_monitor_config(_base_cfg())
    assert cfg["slug"] == "somechannel"
    assert cfg["segment_seconds"] == 1800
    assert cfg["prelive_skip_seconds"] == 1800
    assert cfg["min_gap_seconds"] == 900
    assert cfg["poll_interval"] == 60
    assert cfg["loop"] is False
    assert cfg["timezone"] == "Europe/Rome"


def test_validate_config_lowercases_and_bounds():
    cfg = validate_monitor_config(_base_cfg(
        slug="MixedCase", segment_seconds=99999, poll_interval=1, min_gap_seconds=-5))
    assert cfg["slug"] == "mixedcase"
    assert cfg["segment_seconds"] == 3600   # clamped to max
    assert cfg["poll_interval"] == 30       # clamped to min
    assert cfg["min_gap_seconds"] == 0      # clamped to floor


@pytest.mark.parametrize("bad", ["", "has space", "bad/slug", "UPPER!", "x" * 65])
def test_validate_config_rejects_bad_slug(bad):
    with pytest.raises(ValidationError):
        validate_monitor_config(_base_cfg(slug=bad))


def test_validate_config_manual_queue_allows_no_platforms_by_default():
    cfg = validate_monitor_config({"slug": "chan", "platforms": []})
    assert cfg["publisher_mode"] == "manual_queue"
    assert cfg["platforms"] == []


def test_validate_config_zernio_requires_platforms():
    with pytest.raises(ValidationError):
        validate_monitor_config({"slug": "chan", "publisher_mode": "zernio", "platforms": []})


def test_validate_config_rejects_incomplete_platform():
    with pytest.raises(ValidationError):
        validate_monitor_config({"slug": "chan", "platforms": [{"platform": "tiktok"}]})


def test_validate_config_custom_timezone_passthrough():
    cfg = validate_monitor_config(_base_cfg(timezone="America/New_York"))
    assert cfg["timezone"] == "America/New_York"


def test_validate_config_instructions_trimmed_and_capped():
    cfg = validate_monitor_config(_base_cfg(instructions="  find the funniest bits  "))
    assert cfg["instructions"] == "find the funniest bits"
    from clippyme.domain.job_results import MAX_INSTRUCTIONS_LEN
    cfg = validate_monitor_config(_base_cfg(instructions="x" * (MAX_INSTRUCTIONS_LEN + 1000)))
    assert len(cfg["instructions"]) == MAX_INSTRUCTIONS_LEN


def test_validate_config_instructions_defaults_empty():
    cfg = validate_monitor_config(_base_cfg())
    assert cfg["instructions"] == ""


# --- multi-platform config -------------------------------------------------

def test_validate_config_platform_mode_defaults():
    cfg = validate_monitor_config(_base_cfg())
    assert cfg["platform"] == "kick"
    assert cfg["mode"] == "live"
    assert cfg["channel"] == "somechannel"
    assert cfg["poll_interval"] == 60  # live default


def test_validate_config_vod_poll_default():
    cfg = validate_monitor_config(_base_cfg(platform="youtube", mode="vod", slug="@somebody"))
    assert cfg["poll_interval"] == 600  # vod default
    assert cfg["channel"] == "@somebody"


def test_validate_config_youtube_live_rejected():
    with pytest.raises(ValidationError):
        validate_monitor_config(_base_cfg(platform="youtube", mode="live", slug="@x"))


def test_validate_config_bad_platform_or_mode():
    with pytest.raises(ValidationError):
        validate_monitor_config(_base_cfg(platform="rumble"))
    with pytest.raises(ValidationError):
        validate_monitor_config(_base_cfg(mode="clip"))


@pytest.mark.parametrize("chan", ["@handle", "UCabcdefghijklmnopqrstuv", "https://youtube.com/@x"])
def test_validate_config_youtube_channel_forms(chan):
    cfg = validate_monitor_config(_base_cfg(platform="youtube", mode="vod", slug=chan))
    assert cfg["channel"] == chan


def test_validate_config_youtube_rejects_junk_channel():
    with pytest.raises(ValidationError):
        validate_monitor_config(_base_cfg(platform="youtube", mode="vod", slug="not a handle"))


# --- global slot sharing across monitors -----------------------------------

def test_two_monitors_share_one_picked_slots_store():
    shared = []
    s1 = SharedGapScheduler(min_gap_seconds=900, picked_slots=shared)
    s2 = SharedGapScheduler(min_gap_seconds=900, picked_slots=shared)
    day = date(2026, 7, 21)
    now = datetime(2026, 7, 21, 7, 0)
    a = s1.find_slot(day, [], now=now)
    b = s2.find_slot(day, [], now=now)  # different scheduler, same store
    assert abs((a - b).total_seconds()) >= 900
    assert len(shared) == 2


# --- registry --------------------------------------------------------------

def test_registry_rejects_duplicate(tmp_path):
    reg = LiveMonitorRegistry(
        jobs={}, job_queue=None, output_dir=str(tmp_path),
        state_path=str(tmp_path / "state.json"))

    class _FakeRunning:
        def is_running(self):
            return True
    reg._monitors["kick:foo"] = _FakeRunning()

    with pytest.raises(ConflictError):
        reg.start(_base_cfg(platform="kick", mode="live", slug="foo"))


def test_registry_stop_retires_monitor_but_keeps_snapshot(tmp_path):
    reg = LiveMonitorRegistry(
        jobs={}, job_queue=None, output_dir=str(tmp_path),
        state_path=str(tmp_path / "state.json"))

    class _FakeMon:
        id = "kick:foo"

        async def stop(self):
            return {"id": self.id, "running": False}

        def status(self):
            return {"id": self.id, "running": False}

        def snapshot(self):
            return {"platform": "kick", "channel": "foo", "seen_ids": ["v1"]}

    reg._monitors["kick:foo"] = _FakeMon()
    import asyncio
    asyncio.run(reg.stop("kick:foo"))
    # Gone from the visible list…
    assert reg.status()["monitors"] == []
    # …but the guard snapshot survives for a future restart of the channel.
    assert reg._snapshots["kick:foo"]["seen_ids"] == ["v1"]


def test_registry_migrates_legacy_state(tmp_path):
    import json
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "slug": "oldchan", "published": ["/a.mp4"],
        "picked_slots": ["2026-07-21T10:00:00"],
    }), encoding="utf-8")
    reg = LiveMonitorRegistry(
        jobs={}, job_queue=None, output_dir=str(tmp_path), state_path=str(state))
    assert "kick:oldchan" in reg._snapshots
    assert reg._snapshots["kick:oldchan"]["published"] == ["/a.mp4"]
    assert len(reg._picked_slots) == 1


# --- _hhmmss ---------------------------------------------------------------

def test_hhmmss():
    assert _hhmmss(1800) == "00:30:00"
    assert _hhmmss(3661) == "01:01:01"
    assert _hhmmss(0) == "00:00:00"


# --- backfill_windows ------------------------------------------------------

def test_backfill_windows_already_live_two_hours():
    # 2h elapsed, skip first 30 min, 30-min segments → 3 full windows.
    windows = backfill_windows(7200, 1800, 1800)
    assert windows == [(1800, 3600), (3600, 5400), (5400, 7200)]


def test_backfill_windows_drops_short_trailing_chunk():
    # 5000s elapsed, skip 1800, 1800 segs → [1800-3600, 3600-5400→clamped 5000
    # (1400s < 300? no, 1400>=300 keep)]. Use a genuinely short tail instead.
    windows = backfill_windows(3700, 1800, 1800)  # tail 3600-3700 = 100s < 300
    assert windows == [(1800, 3600)]


def test_backfill_windows_nothing_to_recover():
    assert backfill_windows(1800, 1800, 1800) == []   # elapsed == skip
    assert backfill_windows(1000, 1800, 1800) == []   # elapsed < skip


def test_backfill_windows_clamps_bad_input():
    assert backfill_windows(-100, 1800, 1800) == []
    assert backfill_windows(7200, 1800, 0) == []      # zero segment
    assert backfill_windows("x", 1800, 1800) == []    # non-numeric


# --- build_backfill_cmd ----------------------------------------------------

def test_build_backfill_cmd_download_sections_format():
    cmd = build_backfill_cmd("https://www.twitch.tv/videos/42", 1800, 3600, "/out.mp4")
    assert "-m" in cmd and "yt_dlp" in cmd
    i = cmd.index("--download-sections")
    assert cmd[i + 1] == "*00:30:00-01:00:00"
    assert cmd[cmd.index("-o") + 1] == "/out.mp4"
    assert "--force-overwrites" in cmd and "-q" in cmd


# --- find_live_vod (twitch in-progress archive VOD) ------------------------

def test_find_live_vod_matches_stream_id():
    videos = {"data": [
        {"id": "v1", "stream_id": "999", "url": "https://twitch.tv/videos/v1"},
        {"id": "v2", "stream_id": "111"},
    ]}
    assert find_live_vod(videos, "999") == "https://twitch.tv/videos/v1"
    # falls back to a constructed url when the object omits it
    assert find_live_vod(videos, "111") == "https://www.twitch.tv/videos/v2"


def test_find_live_vod_no_match_or_malformed():
    assert find_live_vod({"data": [{"id": "v1", "stream_id": "1"}]}, "2") is None
    assert find_live_vod(None, "1") is None
    assert find_live_vod({}, "1") is None
    assert find_live_vod({"data": [{"id": "v1"}]}, "1") is None  # no stream_id
    assert find_live_vod({"data": [{"stream_id": "1"}]}, None) is None  # no stream id


# --- effective_backfill_start (restart mid-stream coverage guard) ----------

def test_effective_backfill_start_same_stream_uses_coverage():
    from clippyme.domain.live_monitor import effective_backfill_start
    # Same stream session → prior coverage floors the backfill start.
    assert effective_backfill_start(1800, 40000, "2026-07-20T10:00:00+00:00",
                                    "2026-07-20T10:00:00+00:00") == 40000
    # Coverage below prelive skip → prelive wins.
    assert effective_backfill_start(1800, 600, "s", "s") == 1800


def test_effective_backfill_start_new_stream_ignores_coverage():
    from clippyme.domain.live_monitor import effective_backfill_start
    assert effective_backfill_start(1800, 40000, "2026-07-20T10:00:00+00:00",
                                    "2026-07-21T09:00:00+00:00") == 1800
    assert effective_backfill_start(1800, 40000, None, "x") == 1800
    assert effective_backfill_start(1800, 40000, "x", None) == 1800


def test_snapshot_restore_roundtrips_coverage(tmp_path):
    from clippyme.domain.live_monitor import LiveMonitor
    mon = LiveMonitor(id="kick:chan", jobs={}, job_queue=None,
                      output_dir=str(tmp_path))
    mon._covered_elapsed = 12345
    mon._covered_stream_start = "2026-07-20T10:00:00+00:00"
    snap = mon.snapshot()
    mon2 = LiveMonitor(id="kick:chan", jobs={}, job_queue=None,
                       output_dir=str(tmp_path))
    mon2.restore(snap)
    assert mon2._covered_elapsed == 12345
    assert mon2._covered_stream_start == "2026-07-20T10:00:00+00:00"


# --- _publish_one: 429 backoff + retry -------------------------------------

def test_publish_one_retries_on_429_then_succeeds(tmp_path, monkeypatch):
    """A Zernio 429 must be retried after backoff, not drop the clip."""
    import asyncio

    from clippyme.domain import live_monitor as lm
    from clippyme.domain.live_monitor import LiveMonitor
    from clippyme.integrations import social_publisher as sp
    from clippyme.integrations.social_publisher import ZernioError

    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "c.mp4").write_bytes(b"x")

    monkeypatch.setattr(lm, "PUBLISH_429_BACKOFF_SECONDS", 0)
    calls = []

    def fake_publish_clip(**kwargs):
        calls.append(kwargs)
        if len(calls) < 3:
            raise ZernioError("Zernio POST /posts → HTTP 429",
                              status_code=429, body="rate limited")

    monkeypatch.setattr(sp, "publish_clip", fake_publish_clip)

    mon = LiveMonitor(id="kick:chan", jobs={}, job_queue=None,
                      output_dir=str(tmp_path))
    mon.cfg = {"title_template": "{title}", "caption_template": "{hook}",
               "platforms": [{"platform": "tiktok", "accountId": "a"}],
               "timezone": "Europe/Rome"}
    mon._zernio_key = "sk_test"
    # original_index missing → _compose_for_publish returns the raw path.
    clip = {"video_url": "/videos/job1/c.mp4", "title": "T", "viral_hook_text": "H"}

    asyncio.run(mon._publish_one("job1", clip))

    assert len(calls) == 3
    assert mon.clips_published == 1


def test_publish_one_rolls_start_date_on_daily_limit(tmp_path, monkeypatch):
    """A 'Daily limit reached' 429 must reschedule on the next day, not sleep-retry."""
    import asyncio
    from datetime import date, timedelta

    from clippyme.domain.live_monitor import LiveMonitor
    from clippyme.integrations import social_publisher as sp
    from clippyme.integrations.social_publisher import ZernioError

    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "c.mp4").write_bytes(b"x")

    calls = []

    def fake_publish_clip(**kwargs):
        calls.append(kwargs.get("start_date"))
        if len(calls) < 3:
            raise ZernioError(
                "Zernio POST /posts → HTTP 429", status_code=429,
                body='{"error":"Daily limit reached for this account: 5/5 posts today."}')

    monkeypatch.setattr(sp, "publish_clip", fake_publish_clip)

    mon = LiveMonitor(id="kick:chan", jobs={}, job_queue=None,
                      output_dir=str(tmp_path))
    mon.cfg = {"title_template": "{title}", "caption_template": "{hook}",
               "platforms": [{"platform": "tiktok", "accountId": "a"}],
               "timezone": "Europe/Rome"}
    mon._zernio_key = "sk_test"
    clip = {"video_url": "/videos/job1/c.mp4", "title": "T", "viral_hook_text": "H"}

    asyncio.run(mon._publish_one("job1", clip))

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    day_after = (date.today() + timedelta(days=2)).isoformat()
    assert calls == [None, tomorrow, day_after]
    assert mon.clips_published == 1


def test_publish_one_non_429_fails_without_retry(tmp_path, monkeypatch):
    import asyncio

    from clippyme.domain.live_monitor import LiveMonitor
    from clippyme.integrations import social_publisher as sp
    from clippyme.integrations.social_publisher import ZernioError

    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "c.mp4").write_bytes(b"x")

    calls = []

    def fake_publish_clip(**kwargs):
        calls.append(kwargs)
        raise ZernioError("Zernio POST /posts → HTTP 500", status_code=500, body="boom")

    monkeypatch.setattr(sp, "publish_clip", fake_publish_clip)

    mon = LiveMonitor(id="kick:chan", jobs={}, job_queue=None,
                      output_dir=str(tmp_path))
    mon.cfg = {"title_template": "{title}", "caption_template": "{hook}",
               "platforms": [{"platform": "tiktok", "accountId": "a"}],
               "timezone": "Europe/Rome"}
    mon._zernio_key = "sk_test"
    clip = {"video_url": "/videos/job1/c.mp4", "title": "T", "viral_hook_text": "H"}

    asyncio.run(mon._publish_one("job1", clip))

    assert len(calls) == 1
    assert mon.clips_published == 0
    assert "HTTP 500" in (mon.last_error or "")


# --- manual-queue dispatch -------------------------------------------------

class _RecordingManualQueue:
    def __init__(self, *, fail_first=False):
        self.calls = []
        self.fail_first = fail_first

    def enqueue(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_first and len(self.calls) == 1:
            raise OSError("disk full")
        return {"id": f"entry-{len(self.calls)}"}


def test_manual_dispatch_composes_renders_templates_and_enqueues_without_zernio(tmp_path, monkeypatch):
    import asyncio
    from clippyme.domain.live_monitor import LiveMonitor
    from clippyme.integrations import social_publisher as sp

    job_id = "11111111-1111-4111-8111-111111111111"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    base = job_dir / "clip.mp4"
    composed = job_dir / "composed.mp4"
    base.write_bytes(b"base")
    composed.write_bytes(b"composed")
    queue = _RecordingManualQueue()
    mon = LiveMonitor(id="kick:grenbaud", jobs={}, job_queue=None,
                      output_dir=str(tmp_path), manual_publish_queue=queue)
    mon.cfg = {
        "publisher_mode": "manual_queue", "title_template": "Title: {title}",
        "caption_template": "Hook: {hook}", "platforms": [],
        "timezone": "Europe/Rome", "channel": "grenbaud", "mode": "live",
    }

    async def compose(*_args):
        return str(composed)

    def no_zernio(*_args, **_kwargs):
        pytest.fail("manual delivery must never call Zernio")

    monkeypatch.setattr(mon, "_compose_for_publish", compose)
    monkeypatch.setattr(sp, "publish_clip", no_zernio)

    asyncio.run(mon._publish_one(job_id, {
        "video_url": f"/videos/{job_id}/clip.mp4", "original_index": 2,
        "title": "A title", "viral_hook_text": "A hook", "project_title": "Live 42",
    }))

    assert queue.calls == [{
        "job_id": job_id, "clip_index": 2, "source_path": str(composed),
        "title": "Title: A title", "caption": "Hook: A hook",
        "source_platform": "kick", "source_channel": "grenbaud", "source_kind": "live",
        "project_title": "Live 42", "monitor_id": "kick:grenbaud",
    }]
    assert mon._published == set()
    assert mon._manual_queued[str(base)] == "entry-1"


def test_manual_enqueue_failure_is_retryable_and_duplicate_callback_is_not(tmp_path, monkeypatch):
    import asyncio
    from clippyme.domain.live_monitor import LiveMonitor
    from clippyme.integrations import social_publisher as sp

    job_id = "11111111-1111-4111-8111-111111111111"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "clip.mp4").write_bytes(b"base")
    queue = _RecordingManualQueue(fail_first=True)
    mon = LiveMonitor(id="kick:grenbaud", jobs={}, job_queue=None,
                      output_dir=str(tmp_path), manual_publish_queue=queue)
    mon.cfg = {
        "publisher_mode": "manual_queue", "title_template": "", "caption_template": "",
        "platforms": [], "timezone": "Europe/Rome", "channel": "grenbaud", "mode": "live",
    }

    def no_zernio(*_args, **_kwargs):
        pytest.fail("manual delivery must never call Zernio")

    monkeypatch.setattr(sp, "publish_clip", no_zernio)
    clip = {"video_url": f"/videos/{job_id}/clip.mp4", "original_index": 0, "title": "T"}
    asyncio.run(mon._publish_one(job_id, clip))
    assert str(job_dir / "clip.mp4") not in mon._manual_queued

    asyncio.run(mon._publish_one(job_id, clip))
    asyncio.run(mon._publish_one(job_id, clip))
    assert len(queue.calls) == 2
    assert mon._manual_queued[str(job_dir / "clip.mp4")] == "entry-2"


def test_delivery_uses_publisher_mode_current_at_callback_time(tmp_path, monkeypatch):
    import asyncio
    from clippyme.domain.live_monitor import LiveMonitor
    from clippyme.integrations import social_publisher as sp

    job_id = "11111111-1111-4111-8111-111111111111"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "clip.mp4").write_bytes(b"base")
    queue = _RecordingManualQueue()
    mon = LiveMonitor(id="kick:grenbaud", jobs={}, job_queue=None,
                      output_dir=str(tmp_path), manual_publish_queue=queue)
    mon.cfg = {
        "publisher_mode": "zernio", "title_template": "", "caption_template": "",
        "platforms": [{"platform": "tiktok", "accountId": "account"}],
        "timezone": "Europe/Rome", "channel": "grenbaud", "mode": "live",
    }
    mon.cfg["publisher_mode"] = "manual_queue"

    monkeypatch.setattr(sp, "publish_clip", lambda **_kwargs: pytest.fail("must queue manually"))
    asyncio.run(mon._publish_one(job_id, {
        "video_url": f"/videos/{job_id}/clip.mp4", "original_index": 0, "title": "T",
    }))

    assert len(queue.calls) == 1
