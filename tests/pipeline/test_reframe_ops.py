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


# --- zoom_for_face_height (continuous close-up correction) ------------------
# Ported from smart-reframe ZoomController: target a constant face-occupancy of
# the crop instead of ClippyMe's coarse 4-bucket zoom (which snaps visibly at
# bucket edges). zoom = max_crop_h * target_occupancy / face_h, clamped.

def test_zoom_for_face_tiny_face_hits_max_zoom():
    # A small talking head in a wide shot → zoom all the way in (clamped).
    assert ro.zoom_for_face_height(face_h=40, max_crop_h=1080) == 1.6


def test_zoom_for_face_large_face_hits_min_zoom():
    # Face already fills the frame → no zoom.
    assert ro.zoom_for_face_height(face_h=900, max_crop_h=1080) == 1.0


def test_zoom_for_face_midsize_is_continuous_value():
    z = ro.zoom_for_face_height(face_h=360, max_crop_h=1080, target_occupancy=0.4)
    assert z == pytest.approx(1.2, abs=1e-6)  # 0.4*1080/360 = 1.2


def test_zoom_for_face_is_monotonic_decreasing():
    zs = [ro.zoom_for_face_height(face_h=h, max_crop_h=1080) for h in (50, 150, 300, 600)]
    assert zs == sorted(zs, reverse=True)


def test_zoom_for_face_nonpositive_height_is_min_zoom():
    assert ro.zoom_for_face_height(face_h=0, max_crop_h=1080) == 1.0


# --- asymmetric_zoom_step (fast pull-back / slow push-in) -------------------
# smart-reframe's signature cinematic move: pull back FAST (never chop a face
# that grew/added a person), push in SLOW (cinematic). In ClippyMe's zoom
# convention a *smaller* zoom factor = bigger crop = pulling back.

def test_asym_zoom_push_in_uses_slow_rate():
    # target > current → zooming IN → slow rate.
    out = ro.asymmetric_zoom_step(1.0, 1.5, rate_in=0.05, rate_out=0.20)
    assert out == pytest.approx(1.0 + 0.5 * 0.05)


def test_asym_zoom_pull_back_uses_fast_rate():
    # target < current → pulling BACK → fast rate.
    out = ro.asymmetric_zoom_step(1.5, 1.0, rate_in=0.05, rate_out=0.20)
    assert out == pytest.approx(1.5 - 0.5 * 0.20)


def test_asym_zoom_pull_back_faster_than_push_in():
    step_in = abs(ro.asymmetric_zoom_step(1.0, 1.4, 0.05, 0.20) - 1.0)
    step_out = abs(ro.asymmetric_zoom_step(1.4, 1.0, 0.05, 0.20) - 1.4)
    assert step_out > step_in


def test_asym_zoom_converges_to_target():
    cur = 1.0
    for _ in range(200):
        cur = ro.asymmetric_zoom_step(cur, 1.45, 0.05, 0.20)
    assert cur == pytest.approx(1.45, abs=1e-3)


# --- smooth_and_clamp (global two-stage trajectory pass) --------------------
# Wires the dormant savgol_1d: smooth a full recorded crop trajectory offline,
# then clamp each value into a valid range. This is the cheap, deterministic
# analogue of smart-reframe's Viterbi PathSolver.

def test_smooth_and_clamp_preserves_length():
    v = list(range(40))
    assert len(ro.smooth_and_clamp(v, window=7, polyorder=2, lo=0, hi=39)) == 40


def test_smooth_and_clamp_reduces_noise():
    rng = np.random.default_rng(7)
    clean = np.linspace(100, 900, 200)
    noisy = clean + rng.normal(0, 25, size=200)
    out = ro.smooth_and_clamp(noisy, window=21, polyorder=2, lo=0, hi=1000)
    assert np.var(out - clean) < np.var(noisy - clean)


def test_smooth_and_clamp_respects_bounds():
    v = [-500.0, 50.0, 2000.0, 50.0, -500.0]
    out = ro.smooth_and_clamp(v, window=3, polyorder=1, lo=0.0, hi=100.0)
    assert all(0.0 <= x <= 100.0 for x in out)


# --- build_smoothed_trajectory (two-stage track-then-render glue) -----------
# Records per-frame raw camera targets, then globally low-passes them PER SCENE
# SEGMENT so the smoother never pans across a hard cut. None entries (GENERAL /
# DISABLED frames that don't use the cameraman) pass straight through.

def test_trajectory_preserves_length_and_none_gaps():
    targets = [(100.0, 50.0, 1.0), None, (110.0, 55.0, 1.1), (120.0, 60.0, 1.2)]
    scene_ids = [0, 0, 0, 0]
    out = ro.build_smoothed_trajectory(targets, scene_ids, window=3, polyorder=1,
                                       x_max=1920, y_max=1080)
    assert len(out) == 4
    assert out[1] is None  # gap preserved


def test_trajectory_does_not_smooth_across_scene_cut():
    # Two scenes with a big jump at the cut. Each side is constant, so smoothing
    # within-segment must leave each side's value essentially unchanged (no
    # bleed of scene 1's position into scene 0).
    targets = [(100.0, 50.0, 1.0)] * 4 + [(900.0, 50.0, 1.0)] * 4
    scene_ids = [0, 0, 0, 0, 1, 1, 1, 1]
    out = ro.build_smoothed_trajectory(targets, scene_ids, window=5, polyorder=1,
                                       x_max=1920, y_max=1080)
    assert out[3][0] == pytest.approx(100.0, abs=1.0)
    assert out[4][0] == pytest.approx(900.0, abs=1.0)


def test_trajectory_reduces_jitter_within_segment():
    rng = np.random.default_rng(3)
    base_x = np.linspace(200, 800, 60)
    noisy = [(float(x + rng.normal(0, 40)), 540.0, 1.2) for x in base_x]
    scene_ids = [0] * 60
    out = ro.build_smoothed_trajectory(noisy, scene_ids, window=15, polyorder=2,
                                       x_max=1920, y_max=1080)
    sm_x = np.array([o[0] for o in out])
    noisy_x = np.array([t[0] for t in noisy])
    assert np.var(sm_x - base_x) < np.var(noisy_x - base_x)


def test_trajectory_clamps_to_bounds():
    targets = [(-50.0, -50.0, 5.0), (5000.0, 5000.0, 5.0)]
    scene_ids = [0, 0]
    out = ro.build_smoothed_trajectory(targets, scene_ids, window=3, polyorder=1,
                                       x_max=1920, y_max=1080)
    for cx, cy, z in out:
        assert 0.0 <= cx <= 1920
        assert 0.0 <= cy <= 1080
        assert 1.0 <= z <= 1.6


# --- advance_value_with_velocity (momentum / damped-spring smoother) --------
# Ported from KazKozDev/auto-vertical-reframe: a velocity-based camera smoother
# with explicit per-frame velocity cap, distinct from the EMA / 1€ smoothers.

def test_spring_first_step_moves_toward_target():
    new, vel = ro.advance_value_with_velocity(0.0, 100.0, velocity=0.0,
                                              response=0.2, damping=0.8, max_velocity=50.0)
    assert 0.0 < new <= 50.0
    assert vel > 0.0


def test_spring_velocity_is_capped():
    # Huge gap + high response would overshoot the cap → must clamp to max_velocity.
    new, vel = ro.advance_value_with_velocity(0.0, 10000.0, velocity=0.0,
                                              response=0.9, damping=0.9, max_velocity=30.0)
    assert vel == pytest.approx(30.0)
    assert new == pytest.approx(30.0)


def test_spring_converges_to_target():
    cur, vel = 0.0, 0.0
    for _ in range(500):
        cur, vel = ro.advance_value_with_velocity(cur, 250.0, vel,
                                                  response=0.2, damping=0.7, max_velocity=40.0)
    assert cur == pytest.approx(250.0, abs=0.5)
    assert vel == pytest.approx(0.0, abs=0.5)


def test_spring_damping_decays_velocity_at_target():
    # At target, the (target-current) term is 0, so velocity decays by `damping`.
    _, vel = ro.advance_value_with_velocity(100.0, 100.0, velocity=20.0,
                                            response=0.2, damping=0.5, max_velocity=50.0)
    assert vel == pytest.approx(10.0)


# --- limit_step (hard per-frame pan-rate cap) -------------------------------

def test_limit_step_within_cap_returns_target():
    assert ro.limit_step(100.0, 105.0, max_step=10.0) == 105.0


def test_limit_step_clamps_positive_delta():
    assert ro.limit_step(100.0, 200.0, max_step=10.0) == 110.0


def test_limit_step_clamps_negative_delta():
    assert ro.limit_step(100.0, 0.0, max_step=10.0) == 90.0


# --- rank_subject (subject ranking model port) ------------------------------

_BASE = dict(cls_name="person", conf=0.8, mask_area=10000.0, frame_area=1_000_000.0,
             dist_center=100.0, frame_diag=2200.0, has_face=True)


def test_rank_person_beats_unknown_class():
    person = ro.rank_subject(**_BASE)
    other = ro.rank_subject(**{**_BASE, "cls_name": "truck"})
    assert person > other


def test_rank_center_affinity_raises_score():
    near = ro.rank_subject(**{**_BASE, "dist_center": 50.0})
    far = ro.rank_subject(**{**_BASE, "dist_center": 2000.0})
    assert near > far


def test_rank_lock_match_is_strong_bonus():
    locked = ro.rank_subject(**_BASE, lock_match=True)
    assert locked - ro.rank_subject(**_BASE) == pytest.approx(1.30, abs=1e-6)


def test_rank_speaker_active_adds_weight():
    talking = ro.rank_subject(**_BASE, speaker_active=True)
    assert talking - ro.rank_subject(**_BASE) == pytest.approx(0.22, abs=1e-6)


def test_rank_monotonic_in_confidence():
    lo = ro.rank_subject(**{**_BASE, "conf": 0.2})
    hi = ro.rank_subject(**{**_BASE, "conf": 0.95})
    assert hi > lo


def test_rank_no_face_lower_than_face():
    assert ro.rank_subject(**{**_BASE, "has_face": False}) < ro.rank_subject(**_BASE)
