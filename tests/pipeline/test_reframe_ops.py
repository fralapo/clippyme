"""Host-runnable TDD for clippyme.pipeline.reframe_ops.

This module is intentionally cv2-free (pure numpy/math), so it imports and
runs on the dev host with no heavy CV runtime — unlike the rest of
clippyme.pipeline.main. Keep it that way.
"""
import numpy as np
import pytest

from clippyme.pipeline import reframe_ops as ro


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


# --- weighted_interest_center -----------------------------------------------

def test_weighted_interest_center_empty_is_none():
    assert ro.weighted_interest_center([]) is None


def test_weighted_interest_center_all_nonpositive_weight_is_none():
    # Zero/negative weights contribute nothing → total weight 0 → None.
    assert ro.weighted_interest_center([(10.0, 20.0, 0.0), (30.0, 40.0, -5.0)]) is None


def test_weighted_interest_center_single_object_returns_its_center():
    cx, cy = ro.weighted_interest_center([(100.0, 200.0, 3.0)])
    assert cx == 100.0 and cy == 200.0


def test_weighted_interest_center_pulls_toward_heavier_object():
    # Object B (weight 3) should dominate object A (weight 1): mean x = (1*0 + 3*100)/4 = 75.
    cx, cy = ro.weighted_interest_center([(0.0, 0.0, 1.0), (100.0, 80.0, 3.0)])
    assert abs(cx - 75.0) < 1e-9
    assert abs(cy - 60.0) < 1e-9


def test_weighted_interest_center_skips_nonpositive_among_valid():
    # A zero-weight box must not shift the centroid away from the valid one.
    cx, cy = ro.weighted_interest_center([(50.0, 50.0, 2.0), (999.0, 999.0, 0.0)])
    assert cx == 50.0 and cy == 50.0


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


# --- kalman_rts_smooth ------------------------------------------------------

def test_kalman_short_input_passthrough():
    assert list(ro.kalman_rts_smooth([5.0])) == [5.0]
    assert list(ro.kalman_rts_smooth([])) == []


def test_kalman_preserves_length():
    raw = [float(i % 7) for i in range(40)]
    assert len(ro.kalman_rts_smooth(raw)) == len(raw)


def test_kalman_constant_stays_constant():
    out = ro.kalman_rts_smooth([100.0] * 20)
    assert np.allclose(out, 100.0, atol=1e-6)


def test_kalman_reduces_jitter():
    rng = np.random.default_rng(0)
    clean = np.linspace(0, 200, 80)
    noisy = clean + rng.normal(0, 15, size=80)
    out = ro.kalman_rts_smooth(noisy)
    # Smoothed path is closer to the underlying ramp than the noisy input.
    assert np.mean((out - clean) ** 2) < np.mean((noisy - clean) ** 2)


def test_kalman_tracks_linear_ramp():
    ramp = [float(i) for i in range(50)]
    out = ro.kalman_rts_smooth(ramp)
    # A constant-velocity model should follow a straight ramp almost exactly.
    assert np.max(np.abs(out - np.array(ramp))) < 2.0


# --- solve_camera_path_l2 ---------------------------------------------------

def test_l2_short_input_passthrough():
    assert list(ro.solve_camera_path_l2([1.0, 2.0])) == [1.0, 2.0]


def test_l2_constant_stays_constant():
    out = ro.solve_camera_path_l2([50.0] * 30)
    assert np.allclose(out, 50.0, atol=1e-6)


def test_l2_reduces_jitter():
    rng = np.random.default_rng(1)
    clean = np.full(60, 300.0)
    noisy = clean + rng.normal(0, 20, size=60)
    out = ro.solve_camera_path_l2(noisy, lambda_smooth=200.0, lambda_trend=20.0)
    assert np.mean((out - clean) ** 2) < np.mean((noisy - clean) ** 2)


def test_l2_higher_lambda_is_flatter():
    rng = np.random.default_rng(2)
    noisy = 100.0 + rng.normal(0, 30, size=50)
    soft = ro.solve_camera_path_l2(noisy, lambda_smooth=10.0)
    hard = ro.solve_camera_path_l2(noisy, lambda_smooth=2000.0)
    # Stronger smoothing -> lower step-to-step variance (less camera motion).
    assert np.var(np.diff(hard)) < np.var(np.diff(soft))


def test_l2_keyframe_constraint_pulls_toward_target():
    raw = [0.0] * 21
    mid = 10
    out = ro.solve_camera_path_l2(raw, constraints={mid: 500.0})
    # The constrained frame is pulled strongly toward the keyframe target.
    assert out[mid] > 400.0


# --- build_smoothed_trajectory method dispatch ------------------------------

def _ramp_targets(n):
    return [(float(i), float(i) * 0.5, 1.0) for i in range(n)]


def test_trajectory_method_default_matches_savgol():
    targets = _ramp_targets(30)
    sids = [0] * 30
    a = ro.build_smoothed_trajectory(targets, sids, 7, 2, 1000, 1000)
    b = ro.build_smoothed_trajectory(targets, sids, 7, 2, 1000, 1000, method="savgol")
    assert a == b  # default is byte-identical to explicit savgol


def test_trajectory_kalman_method_runs_and_clamps():
    targets = _ramp_targets(30)
    sids = [0] * 30
    out = ro.build_smoothed_trajectory(targets, sids, 7, 2, 1000, 1000, method="kalman")
    assert len(out) == 30
    assert all(0.0 <= cx <= 1000 and 0.0 <= cy <= 1000 for (cx, cy, _z) in out)


def test_trajectory_l2_method_runs_and_clamps():
    targets = _ramp_targets(30)
    sids = [0] * 30
    out = ro.build_smoothed_trajectory(targets, sids, 7, 2, 1000, 1000, method="l2")
    assert len(out) == 30
    assert all(0.0 <= cx <= 1000 for (cx, _cy, _z) in out)


def test_trajectory_method_preserves_none_gaps():
    targets = _ramp_targets(10) + [None] * 3 + _ramp_targets(10)
    sids = [0] * 23
    out = ro.build_smoothed_trajectory(targets, sids, 5, 2, 1000, 1000, method="kalman")
    assert out[10] is None and out[11] is None and out[12] is None
    assert len(out) == 23


# --- stationary_lock (AutoFlip-style per-scene tripod) -----------------------

def test_stationary_lock_pins_near_static_scene_to_median():
    xs = [500.0, 502.0, 498.0, 501.0]
    ys = [500.0, 501.0, 499.0, 500.0]
    x2, y2, locked = ro.stationary_lock(xs, ys, 1000, 1000, threshold=0.15)
    assert locked
    # within snap_center_dist of centre (500) → snapped exactly to centre
    assert x2 == [500.0] * 4 and y2 == [500.0] * 4


def test_stationary_lock_keeps_moving_scene_untouched():
    xs = [100.0, 400.0, 700.0, 950.0]   # span 850 > 0.15*1000
    ys = [500.0, 500.0, 500.0, 500.0]
    x2, y2, locked = ro.stationary_lock(xs, ys, 1000, 1000, threshold=0.15)
    assert not locked
    assert x2 == xs and y2 == ys          # unchanged → path stays as tracked


def test_stationary_lock_offcenter_static_locks_without_snap():
    xs = [200.0, 201.0, 199.0]            # static but far from centre 500
    ys = [500.0, 500.0, 500.0]
    x2, _y2, locked = ro.stationary_lock(xs, ys, 1000, 1000,
                                         threshold=0.15, snap_center_dist=0.10)
    assert locked
    assert x2[0] == 200.0                  # median, not snapped to centre


def test_build_trajectory_stationary_threshold_zero_is_noop():
    """threshold 0.0 must leave the smoothed path identical (default behaviour)."""
    targets = _ramp_targets(20)
    sids = [0] * 20
    base = ro.build_smoothed_trajectory(targets, sids, 7, 2, 1000, 1000)
    same = ro.build_smoothed_trajectory(targets, sids, 7, 2, 1000, 1000,
                                        stationary_threshold=0.0)
    assert base == same


def test_build_trajectory_locks_a_static_segment():
    targets = [(500.0, 500.0, 1.0)] * 20   # perfectly static scene
    sids = [0] * 20
    out = ro.build_smoothed_trajectory(targets, sids, 7, 2, 1000, 1000,
                                       stationary_threshold=0.15)
    cxs = {round(cx, 3) for (cx, _cy, _z) in out}
    assert cxs == {500.0}                   # all frames pinned to one point


def test_build_trajectory_lock_zoom_pins_scene_to_single_zoom():
    """lock_zoom collapses an in-scene zoom ramp to one constant level."""
    targets = [(500.0, 500.0, 1.0 + i * 0.02) for i in range(20)]  # zoom 1.0→1.38
    sids = [0] * 20
    out = ro.build_smoothed_trajectory(targets, sids, 7, 2, 1000, 1000,
                                       lock_zoom=True)
    zs = {round(z, 4) for (_cx, _cy, z) in out}
    assert len(zs) == 1                     # every frame shares one zoom


def test_build_trajectory_lock_zoom_default_off_keeps_varying_zoom():
    targets = [(500.0, 500.0, 1.0 + i * 0.02) for i in range(20)]
    sids = [0] * 20
    out = ro.build_smoothed_trajectory(targets, sids, 7, 2, 1000, 1000)
    zs = {round(z, 4) for (_cx, _cy, z) in out}
    assert len(zs) > 1                      # zoom still varies when unlocked


def test_build_trajectory_lock_zoom_independent_per_scene():
    """Each scene gets its own locked zoom — change across a cut is allowed."""
    targets = ([(500.0, 500.0, 1.1)] * 10) + ([(500.0, 500.0, 1.5)] * 10)
    sids = ([0] * 10) + ([1] * 10)
    out = ro.build_smoothed_trajectory(targets, sids, 5, 2, 1000, 1000,
                                       lock_zoom=True)
    zs_scene0 = {round(z, 4) for (_cx, _cy, z) in out[:10]}
    zs_scene1 = {round(z, 4) for (_cx, _cy, z) in out[10:]}
    assert len(zs_scene0) == 1 and len(zs_scene1) == 1
    assert zs_scene0 != zs_scene1           # different zoom per scene survives


# --- centroid_span (motion measure for AUTO static policy) ------------------

def test_centroid_span_static_subject_is_zero():
    centers = [(500.0, 500.0)] * 5
    assert ro.centroid_span(centers, 1000, 1000) == pytest.approx(0.0)


def test_centroid_span_skips_none_frames():
    centers = [(400.0, 500.0), None, (600.0, 500.0), None]
    # x span = 200/1000 = 0.2, y span = 0 -> max 0.2
    assert ro.centroid_span(centers, 1000, 1000) == pytest.approx(0.2)


def test_centroid_span_uses_larger_axis():
    centers = [(500.0, 300.0), (500.0, 800.0)]  # y span 500/1000=0.5 dominates
    assert ro.centroid_span(centers, 1000, 1000) == pytest.approx(0.5)


def test_centroid_span_too_few_points_is_zero():
    assert ro.centroid_span([(500.0, 500.0)], 1000, 1000) == 0.0
    assert ro.centroid_span([None, None], 1000, 1000) == 0.0


# --- collapse_scene_targets (per-scene static framing) ----------------------

def test_collapse_track_locks_on_median_with_zoom_cap():
    # A TRACK scene with a small drift + an aggressive zoom request.
    targets = [(480.0, 500.0, 1.6), (520.0, 500.0, 1.6), (500.0, 500.0, 1.6)]
    sids = [0, 0, 0]
    strats = ['TRACK', 'TRACK', 'TRACK']
    out = ro.collapse_scene_targets(targets, sids, strats, x_max=1000, y_max=1000,
                                    track_zoom_cap=1.35, snap_center_dist=0.0)
    assert len({t for t in out}) == 1           # one fixed target for the scene
    cx, cy, z = out[0]
    assert cx == pytest.approx(500.0)           # median x
    assert z == pytest.approx(1.35)             # capped below the 1.6 request


def test_collapse_wide_forces_widest_zoom():
    targets = [(400.0, 500.0, 1.5), (600.0, 500.0, 1.4)]
    sids = [0, 0]
    strats = ['WIDE', 'WIDE']
    out = ro.collapse_scene_targets(targets, sids, strats, x_max=1000, y_max=1000,
                                    wide_zoom=1.0, snap_center_dist=0.0)
    cx, cy, z = out[0]
    assert z == pytest.approx(1.0)              # WIDE always widest, no zoom-in
    assert cx == pytest.approx(500.0)           # centred between the two faces


def test_collapse_snaps_near_center_to_exact_center():
    targets = [(505.0, 500.0, 1.1)] * 4
    sids = [0] * 4
    strats = ['TRACK'] * 4
    out = ro.collapse_scene_targets(targets, sids, strats, x_max=1000, y_max=1000,
                                    snap_center_dist=0.10)
    assert out[0][0] == pytest.approx(500.0)    # 5px off -> snapped to centre


def test_collapse_is_static_per_scene_but_varies_across_cut():
    targets = ([(300.0, 500.0, 1.2)] * 5) + ([(700.0, 500.0, 1.2)] * 5)
    sids = ([0] * 5) + ([1] * 5)
    strats = ['TRACK'] * 10
    out = ro.collapse_scene_targets(targets, sids, strats, x_max=1000, y_max=1000,
                                    snap_center_dist=0.0)
    assert len({t for t in out[:5]}) == 1       # scene 0 fully static
    assert len({t for t in out[5:]}) == 1       # scene 1 fully static
    assert out[0] != out[5]                     # but the two scenes differ


def test_collapse_passes_through_none_targets():
    targets = [(500.0, 500.0, 1.1), None, (500.0, 500.0, 1.1)]
    sids = [0, 0, 0]
    strats = ['TRACK', 'GENERAL', 'TRACK']
    out = ro.collapse_scene_targets(targets, sids, strats, x_max=1000, y_max=1000)
    assert out[1] is None                       # GENERAL/None frame untouched


# --- PanSmoother (subject/FrameShift per-frame jitter fix) -------------------

def test_pan_smoother_first_target_snaps():
    s = ro.PanSmoother()
    assert s.smooth(400.0, 1920) == 400.0


def test_pan_smoother_holds_inside_deadband():
    # Detection noise of a few px must never move the crop.
    s = ro.PanSmoother(deadband_frac=0.04)
    s.smooth(400.0, 1920)
    for noisy in (401.0, 398.5, 403.0, 396.0, 400.7):
        assert s.smooth(noisy, 1920) == 400.0


def test_pan_smoother_moves_after_deadband_breach_and_settles():
    s = ro.PanSmoother(deadband_frac=0.04, settle_frac=0.005, alpha=0.2)
    s.smooth(400.0, 1920)
    target = 700.0  # 300px jump > 76.8px deadband
    prev = 400.0
    for _ in range(60):
        prev = s.smooth(target, 1920)
    assert abs(prev - target) <= 0.005 * 1920
    assert s.moving is False
    # Once settled, small noise holds again.
    assert s.smooth(prev + 2.0, 1920) == prev


def test_pan_smoother_none_target_returns_held_center():
    s = ro.PanSmoother()
    s.smooth(500.0, 1920)
    assert s.smooth(None, 1920) == 500.0   # dropout bridged


def test_pan_smoother_none_before_any_target_is_none():
    assert ro.PanSmoother().smooth(None, 1920) is None


def test_pan_smoother_reset_snaps_next_target():
    s = ro.PanSmoother()
    s.smooth(500.0, 1920)
    s.reset()
    assert s.smooth(900.0, 1920) == 900.0
