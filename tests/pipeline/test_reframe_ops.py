"""Host-runnable TDD for clippyme.pipeline.reframe_ops.

This module is intentionally cv2-free (pure numpy/math), so it imports and
runs on the dev host with no heavy CV runtime — unlike the rest of
clippyme.pipeline.main. Keep it that way.
"""
import numpy as np
import pytest

from clippyme.pipeline import reframe_ops as ro


# --- iou --------------------------------------------------------------------

def test_iou_identical_is_one():
    assert ro.iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)


def test_iou_disjoint_is_zero():
    assert ro.iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0


def test_iou_half_overlap():
    # Two 10x10 boxes overlapping in a 10x5 strip -> inter=50, union=150.
    assert ro.iou((0, 0, 10, 10), (0, 5, 10, 15)) == pytest.approx(50 / 150)


# --- associate_subject ------------------------------------------------------

def test_associate_picks_best_overlap():
    prev = (0, 0, 10, 10)
    cands = [(100, 100, 110, 110), (1, 1, 11, 11)]  # second overlaps prev
    assert ro.associate_subject(prev, cands, min_iou=0.3) == 1


def test_associate_returns_none_when_nothing_overlaps():
    prev = (0, 0, 10, 10)
    cands = [(100, 100, 110, 110), (200, 200, 210, 210)]
    assert ro.associate_subject(prev, cands, min_iou=0.3) is None


def test_associate_no_prev_returns_none():
    assert ro.associate_subject(None, [(0, 0, 10, 10)]) is None


# --- OneEuroFilter ----------------------------------------------------------

def test_one_euro_first_sample_is_passthrough():
    f = ro.OneEuroFilter(min_cutoff=1.0, beta=0.0)
    assert f.filter(42.0, dt=1 / 30) == pytest.approx(42.0)


def test_one_euro_constant_stays_constant():
    f = ro.OneEuroFilter(min_cutoff=1.0, beta=0.0)
    out = [f.filter(5.0, dt=1 / 30) for _ in range(10)]
    assert all(o == pytest.approx(5.0) for o in out)


def test_one_euro_damps_a_single_outlier():
    f = ro.OneEuroFilter(min_cutoff=0.5, beta=0.0)
    for _ in range(5):
        f.filter(0.0, dt=1 / 30)
    spike = f.filter(10.0, dt=1 / 30)
    # The spike is followed but heavily damped — not passed through raw.
    assert 0.0 < spike < 5.0


def test_one_euro_reduces_jitter_variance():
    rng = np.random.default_rng(0)
    signal = 100.0 + rng.normal(0, 5, size=200)
    f = ro.OneEuroFilter(min_cutoff=0.3, beta=0.0)
    out = np.array([f.filter(float(x), dt=1 / 30) for x in signal])
    assert out.var() < signal.var()


# --- drift_to_center --------------------------------------------------------

def test_drift_holds_within_hold_window():
    assert ro.drift_to_center(200.0, 500.0, frames_since_seen=10, hold_frames=90) == 200.0


def test_drift_moves_toward_center_after_hold():
    nxt = ro.drift_to_center(200.0, 500.0, frames_since_seen=91, hold_frames=90, drift_rate=0.1)
    assert 200.0 < nxt < 500.0


def test_drift_converges_to_center():
    pos = 200.0
    for i in range(500):
        pos = ro.drift_to_center(pos, 500.0, frames_since_seen=91 + i, hold_frames=90, drift_rate=0.1)
    assert pos == pytest.approx(500.0, abs=1.0)


# --- salient_crop_center ----------------------------------------------------

def test_salient_crop_window_covers_energy_peak():
    frame_w, crop_w = 200, 60
    energy = np.zeros(frame_w)
    energy[80:90] = 1.0  # peak
    x = ro.salient_crop_center(energy, crop_w, frame_w)
    # window [x-30, x+30] must contain the peak
    assert x - crop_w / 2 <= 85 <= x + crop_w / 2


def test_salient_crop_clamps_in_bounds():
    frame_w, crop_w = 200, 60
    energy = np.zeros(frame_w)
    energy[0:5] = 1.0  # peak at the very left edge
    x = ro.salient_crop_center(energy, crop_w, frame_w)
    assert x >= crop_w / 2
    assert x <= frame_w - crop_w / 2


def test_salient_crop_respects_max_step():
    frame_w, crop_w = 400, 100
    energy = np.zeros(frame_w)
    energy[350:360] = 1.0  # far-right peak
    x = ro.salient_crop_center(energy, crop_w, frame_w, prev_x=100.0, max_step=20.0)
    assert abs(x - 100.0) <= 20.0 + 1e-6


# --- savgol_1d --------------------------------------------------------------

def test_savgol_preserves_length():
    v = np.arange(50, dtype=float)
    assert len(ro.savgol_1d(v, window=7, polyorder=2)) == 50


def test_savgol_preserves_straight_line():
    v = 2.0 * np.arange(50, dtype=float) + 3.0
    out = ro.savgol_1d(v, window=7, polyorder=2)
    assert np.allclose(out, v, atol=1e-6)


def test_savgol_reduces_noise_variance():
    rng = np.random.default_rng(1)
    x = np.linspace(0, 4 * np.pi, 300)
    clean = np.sin(x)
    noisy = clean + rng.normal(0, 0.3, size=300)
    smoothed = ro.savgol_1d(noisy, window=21, polyorder=3)
    assert np.var(smoothed - clean) < np.var(noisy - clean)
