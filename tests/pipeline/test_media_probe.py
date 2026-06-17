"""Host (non-integration) tests for the pure helpers in
``clippyme.pipeline.media_probe`` — VFR detection, start_time parsing, and the
audio-sync seek-arg builder ported from kamilstanuch/Autocrop-vertical.

No cv2/ffprobe needed: every function under test is pure. The ``probe_*``
ffprobe wrappers are exercised only for their never-raise contract.
"""
import pytest

from clippyme.pipeline.media_probe import (
    audio_sync_seek_args,
    is_vfr,
    parse_frame_rate,
    parse_start_time,
    probe_is_variable_frame_rate,
    probe_stream_start_time,
    reconcile_fps,
)


# --- parse_frame_rate ---------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("30/1", 30.0),
    ("25", 25.0),
    ("30000/1001", pytest.approx(29.97, abs=0.01)),
    ("60000/1001", pytest.approx(59.94, abs=0.01)),
])
def test_parse_frame_rate_valid(raw, expected):
    assert parse_frame_rate(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "0/0", "5/0", "abc", "1/2/3", None])
def test_parse_frame_rate_malformed_returns_zero(raw):
    # Malformed/zero-denominator must degrade to 0.0 (treated as "unknown/CFR"),
    # never raise.
    assert parse_frame_rate(raw) == 0.0


# --- is_vfr -------------------------------------------------------------------

def test_is_vfr_true_when_rates_diverge():
    # Nominal 30 vs average 24 → 6 fps gap, clearly VFR.
    assert is_vfr("30/1", "24/1") is True


def test_is_vfr_false_for_matching_cfr():
    assert is_vfr("30/1", "30/1") is False


def test_is_vfr_false_for_ntsc_jitter_under_threshold():
    # 29.97 vs 30.0 differ by 0.03 fps — well under the 0.5 default; not VFR.
    assert is_vfr("30000/1001", "30/1") is False


def test_is_vfr_false_when_a_rate_is_unknown():
    # An unreadable rate must not trigger a needless re-encode.
    assert is_vfr("0/0", "30/1") is False
    assert is_vfr("30/1", "") is False


def test_is_vfr_respects_custom_threshold():
    # 30 vs 30.4 → 0.4 gap: not VFR at default 0.5, VFR at a tighter 0.2.
    assert is_vfr("30/1", "152/5") is False
    assert is_vfr("30/1", "152/5", threshold=0.2) is True


# --- parse_start_time ---------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("1.800000", 1.8),
    ("0.000000", 0.0),
    ("  2.5 ", 2.5),
    ("-0.021333", -0.021333),
])
def test_parse_start_time_valid(raw, expected):
    assert parse_start_time(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["", "N/A", "  ", "garbage", None])
def test_parse_start_time_unparseable_returns_zero(raw):
    assert parse_start_time(raw) == 0.0


# --- audio_sync_seek_args -----------------------------------------------------

def test_audio_sync_seek_args_emits_seek_for_real_offset():
    assert audio_sync_seek_args(1.8) == ["-ss", "1.800"]


def test_audio_sync_seek_args_noop_for_zero_offset():
    # Zero / negligible offset → no args, so the common case is byte-identical.
    assert audio_sync_seek_args(0.0) == []


def test_audio_sync_seek_args_noop_under_min_offset():
    # 1 frame @30fps (~0.033s) is below the 0.05 floor → skip.
    assert audio_sync_seek_args(0.033) == []


def test_audio_sync_seek_args_noop_for_negative_or_none():
    assert audio_sync_seek_args(-0.5) == []
    assert audio_sync_seek_args(None) == []


def test_audio_sync_seek_args_custom_min_offset():
    assert audio_sync_seek_args(0.1, min_offset=0.2) == []
    assert audio_sync_seek_args(0.3, min_offset=0.2) == ["-ss", "0.300"]


# --- reconcile_fps ------------------------------------------------------------

def test_reconcile_fps_keeps_scene_fps_when_within_tolerance():
    # 29.97 vs 30.0 differ by 0.03 < 0.1 → keep detector value (byte-identical).
    assert reconcile_fps(29.97, 30.0) == 30.0


def test_reconcile_fps_prefers_reader_on_divergence():
    # 25 vs 30 is a real disagreement → trust the cv2 reader (the frame source).
    assert reconcile_fps(25.0, 30.0) == 25.0


def test_reconcile_fps_falls_back_to_scene_when_reader_invalid():
    assert reconcile_fps(0.0, 30.0) == 30.0
    assert reconcile_fps(-1.0, 30.0) == 30.0
    assert reconcile_fps(None, 30.0) == 30.0


def test_reconcile_fps_uses_reader_when_scene_invalid():
    assert reconcile_fps(30.0, 0.0) == 30.0
    assert reconcile_fps(30.0, None) == 30.0


def test_reconcile_fps_respects_custom_tolerance():
    # 0.3 gap: kept at tol=0.5, overridden at tol=0.1.
    assert reconcile_fps(30.3, 30.0, tol=0.5) == 30.0
    assert reconcile_fps(30.3, 30.0, tol=0.1) == 30.3


# --- probe_* never-raise contract --------------------------------------------

def test_probe_wrappers_never_raise_on_missing_file(tmp_path):
    # ffprobe may or may not exist on the host; either way these must return the
    # safe default rather than propagating an exception.
    bogus = str(tmp_path / "does_not_exist.mp4")
    assert probe_stream_start_time(bogus) == 0.0
    assert probe_is_variable_frame_rate(bogus) is False
