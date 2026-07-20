"""Tests for clippyme.domain.live_monitor pure helpers + config validation.

No curl_cffi / ffmpeg / event loop needed — LiveMonitor.__init__ is cheap and
the helpers under test are pure.
"""
from datetime import date, datetime

import pytest

from clippyme.domain.errors import ValidationError
from clippyme.domain.live_monitor import (
    SharedGapScheduler,
    render_template,
    should_process_segment,
    validate_monitor_config,
    _hhmmss,
)


# --- should_process_segment ------------------------------------------------

def test_should_process_segment_floor():
    assert should_process_segment(1800) is True
    assert should_process_segment(300) is True      # exactly 5 min → keep
    assert should_process_segment(299) is False     # just under → drop
    assert should_process_segment(0) is False
    assert should_process_segment(None) is False


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


# --- _hhmmss ---------------------------------------------------------------

def test_hhmmss():
    assert _hhmmss(1800) == "00:30:00"
    assert _hhmmss(3661) == "01:01:01"
    assert _hhmmss(0) == "00:00:00"
