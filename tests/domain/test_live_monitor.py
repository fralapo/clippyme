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


def test_validate_config_requires_platforms():
    with pytest.raises(ValidationError):
        validate_monitor_config({"slug": "chan", "platforms": []})


def test_validate_config_rejects_incomplete_platform():
    with pytest.raises(ValidationError):
        validate_monitor_config({"slug": "chan", "platforms": [{"platform": "tiktok"}]})


def test_validate_config_custom_timezone_passthrough():
    cfg = validate_monitor_config(_base_cfg(timezone="America/New_York"))
    assert cfg["timezone"] == "America/New_York"


def test_validate_config_instructions_trimmed_and_capped():
    cfg = validate_monitor_config(_base_cfg(instructions="  find the funniest bits  "))
    assert cfg["instructions"] == "find the funniest bits"
    cfg = validate_monitor_config(_base_cfg(instructions="x" * 3000))
    assert len(cfg["instructions"]) == 2000


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
