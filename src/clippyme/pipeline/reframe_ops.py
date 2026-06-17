"""Pure reframe decision math — no cv2, no heavy CV runtime.

Everything here operates on plain numbers, tuples, and numpy arrays so it can
be unit-tested on any host. main.py owns the cv2 glue (frame capture, FaceMesh,
saliency-map generation) and calls into these functions. Do NOT import cv2 here.

Provides:
- iou / associate_subject     — stable subject identity across detection frames
- OneEuroFilter               — adaptive jitter-vs-lag camera smoothing
- drift_to_center             — graceful lost-subject recovery
- salient_crop_center         — content-aware crop window for faceless scenes
- savgol_1d                    — Savitzky-Golay smoothing for a future two-stage
                                 global-trajectory pass
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np


# --- identity ---------------------------------------------------------------

def iou(box_a, box_b) -> float:
    """Intersection-over-union of two (x1, y1, x2, y2) boxes."""
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def associate_subject(prev_box, candidates: Sequence, min_iou: float = 0.3) -> Optional[int]:
    """Index of the candidate box that best overlaps the previously-tracked
    subject, or None when there's no prior box or nothing overlaps enough.

    Used in WIDE/multi-speaker scenes to bias toward identity continuity before
    falling back to mouth-aspect-ratio scoring.
    """
    if prev_box is None or not candidates:
        return None
    best_i: Optional[int] = None
    best = min_iou
    for i, cand in enumerate(candidates):
        v = iou(prev_box, cand)
        if v >= best:
            best = v
            best_i = i
    return best_i


# --- smoothing --------------------------------------------------------------

class OneEuroFilter:
    """1€ filter — adaptive low-pass that follows fast moves and damps jitter.

    `min_cutoff` sets the floor smoothing (lower = smoother/laggier at rest);
    `beta` raises the cutoff with speed (higher = snappier on fast moves).
    State is O(1); call `filter(value, dt)` once per frame per axis.
    """

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.0, d_cutoff: float = 1.0):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self.x_prev: Optional[float] = None
        self.dx_prev: float = 0.0

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter(self, x: float, dt: float) -> float:
        x = float(x)
        if dt <= 0:
            dt = 1e-6
        if self.x_prev is None:
            self.x_prev = x
            self.dx_prev = 0.0
            return x
        dx = (x - self.x_prev) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        dx_hat = self.dx_prev + a_d * (dx - self.dx_prev)
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = self.x_prev + a * (x - self.x_prev)
        self.x_prev = x_hat
        self.dx_prev = dx_hat
        return x_hat

    def reset(self) -> None:
        self.x_prev = None
        self.dx_prev = 0.0


def drift_to_center(current: float, center: float, frames_since_seen: int,
                    hold_frames: int = 90, drift_rate: float = 0.05) -> float:
    """Lost-subject recovery: hold the last position for `hold_frames`, then
    ease toward `center` by `drift_rate` per frame. Avoids freezing the camera
    on empty space when the active speaker disappears.
    """
    if frames_since_seen <= hold_frames:
        return current
    return current + (center - current) * drift_rate


# --- zoom control (ported from smart-reframe ZoomController) -----------------

def zoom_for_face_height(face_h: float, max_crop_h: float,
                         target_occupancy: float = 0.4,
                         min_zoom: float = 1.0, max_zoom: float = 1.6) -> float:
    """Continuous close-up correction: pick the zoom factor that makes the face
    occupy ``target_occupancy`` of the crop height, clamped to [min, max].

    Replaces the old 4-bucket step ladder (1.0/1.15/1.3/1.5), which snapped
    visibly whenever a face crossed a bucket edge. In ClippyMe's convention the
    crop height is ``max_crop_h / zoom`` (larger zoom ⇒ tighter crop), so a face
    of height ``face_h`` occupies ``face_h * zoom / max_crop_h`` of the frame.
    Solving ``occupancy == target_occupancy`` gives ``zoom = max_crop_h *
    target_occupancy / face_h``. Adapted from smart-reframe's
    ``needed_zoom_for_size`` (gauravzazz/smart-reframe, framing/zoom.py).
    """
    if face_h <= 0:
        return min_zoom
    zoom = max_crop_h * target_occupancy / face_h
    return max(min_zoom, min(zoom, max_zoom))


def advance_value_with_velocity(current: float, target: float, velocity: float,
                                response: float, damping: float,
                                max_velocity: float):
    """Momentum / damped-spring smoother — returns ``(new_value, new_velocity)``.

    ``velocity = velocity*damping + (target-current)*response``, clamped to
    ``±max_velocity`` (a hard per-frame rate cap), then ``current + velocity``.
    Unlike the EMA / 1€ smoothers this carries momentum, so it accelerates and
    decelerates like a real operator and can never jump more than
    ``max_velocity`` px/frame. Ported from KazKozDev/auto-vertical-reframe
    (``advance_value_with_velocity``).
    """
    velocity = velocity * damping + (target - current) * response
    if velocity > max_velocity:
        velocity = max_velocity
    elif velocity < -max_velocity:
        velocity = -max_velocity
    return current + velocity, velocity


def limit_step(current: float, target: float, max_step: float) -> float:
    """Clamp a move from ``current`` toward ``target`` to at most ``max_step``
    per call — a hard per-frame pan-rate cap. Ported from
    KazKozDev/auto-vertical-reframe (``limit_step``).
    """
    delta = target - current
    if delta > max_step:
        return current + max_step
    if delta < -max_step:
        return current - max_step
    return target


# --- subject ranking (ported from auto-vertical-reframe SubjectRankingModel) -

# Hand-tuned linear fusion weights. A larger lock/tracking bonus than the
# per-frame signals deliberately favours identity continuity over chasing
# whoever momentarily scores highest — this is the anti-ping-pong recipe.
_RANK_CLASS_BIAS = {
    "person": 0.22, "dog": 0.12, "cat": 0.10, "car": 0.06,
    "bicycle": 0.02, "motorcycle": 0.02, "bus": 0.01, "truck": 0.01,
}
_RANK_FEATURE_WEIGHTS = {
    "det_conf": 1.35, "mask_presence": 0.95, "center_affinity": 0.55,
    "face_presence": 0.48, "pose_presence": 0.34, "saliency_presence": 0.72,
    "saliency_conf": 0.78, "tracking_match": 1.05, "lock_match": 1.30,
    "speaker_active": 0.22, "size_logit": 0.26,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def rank_subject(*, cls_name: str, conf: float, mask_area: float, frame_area: float,
                 dist_center: float, frame_diag: float, has_face: bool,
                 has_pose: bool = False, saliency_confidence: float = 0.0,
                 tracking_match: bool = False, lock_match: bool = False,
                 speaker_active: bool = False) -> float:
    """Linear subject-importance score fusing detection/size/center/face/
    continuity/speaker signals. Higher = more likely the intended subject.

    Direct port of KazKozDev/auto-vertical-reframe ``SubjectRankingModel``.
    Callers pass whatever signals they have; absent ones default to off, so the
    function degrades gracefully (ClippyMe has no masks/pose/saliency yet, so
    those features simply contribute 0). The strong ``lock_match`` / ``tracking_match``
    weights bias toward keeping the current subject, killing camera ping-pong.
    """
    norm_area = _clamp(mask_area / max(frame_area, 1.0), 0.0, 1.0)
    center_affinity = 1.0 - _clamp(dist_center / max(frame_diag, 1.0), 0.0, 1.0)
    features = {
        "det_conf": _clamp(conf, 0.0, 1.0),
        "mask_presence": math.sqrt(norm_area),
        "center_affinity": center_affinity,
        "face_presence": 1.0 if has_face else 0.0,
        "pose_presence": 1.0 if has_pose else 0.0,
        "saliency_presence": 1.0 if saliency_confidence > 0.0 else 0.0,
        "saliency_conf": _clamp(saliency_confidence, 0.0, 1.0),
        "tracking_match": 1.0 if tracking_match else 0.0,
        "lock_match": 1.0 if lock_match else 0.0,
        "speaker_active": 1.0 if speaker_active else 0.0,
        "size_logit": math.log1p(norm_area * 250.0),
    }
    score = _RANK_CLASS_BIAS.get(cls_name, 0.0)
    for name, value in features.items():
        score += _RANK_FEATURE_WEIGHTS[name] * value
    return score


def asymmetric_zoom_step(current: float, target: float,
                         rate_in: float, rate_out: float) -> float:
    """Ease ``current`` toward ``target`` with direction-dependent speed.

    Pull-back (target < current ⇒ a bigger crop) uses the fast ``rate_out`` so
    the camera never lingers cropped-in while a face grows or a second person
    enters; push-in (target > current) uses the slow ``rate_in`` for a
    cinematic feel. Ported from smart-reframe's asymmetric zoom smoothing
    (framing/zoom.py:117-130), translated into ClippyMe's inverted zoom
    convention (smaller factor = wider crop = pull-back).
    """
    diff = target - current
    rate = rate_in if diff > 0 else rate_out
    return current + diff * rate


# --- multi-face split-screen layout (ported from obi19999/smart-video-reframe) ---

def split_screen_slots(n_faces: int, width: int, height: int,
                       portrait: Optional[bool] = None):
    """Tile a ``width``×``height`` output frame into ``n_faces`` slot rectangles
    for a multi-face split-screen montage (podcast / interview 2-up, 3-up, 4-up).

    Returns a list of integer ``(x, y, w, h)`` slots that tile the frame with no
    gaps or overlaps; a caller crops each tracked face into its slot. Direct port
    of the layout arithmetic in obi19999/smart-video-reframe
    ``FaceDetector.combine_faces`` — that repo's one net-new idea relative to
    ClippyMe's single-camera reframer. Kept here as a tested-but-unwired building
    block (the same convention as ``rank_subject`` / ``associate_subject`` /
    ``salient_crop_center``) until a multi-face render mode is wired in; today
    ClippyMe reframes to one cinematic camera, so nothing calls this yet.

    Layout (portrait, the 9:16 default):
      1 → whole frame   2 → stacked rows   3 → top banner + bottom pair
      4 → 2×2 grid      n → n equal rows
    Landscape mirrors into equal columns. The last slot in each run absorbs the
    integer-rounding remainder so the slots always cover the frame exactly.
    """
    if n_faces <= 0:
        return []
    if portrait is None:
        portrait = height >= width
    n = n_faces
    if n == 1:
        return [(0, 0, width, height)]

    if portrait:
        if n == 2:
            h0 = height // 2
            return [(0, 0, width, h0), (0, h0, width, height - h0)]
        if n == 3:
            top_h = int(height * 0.35)
            bot_h = height - top_h
            half_w = width // 2
            return [
                (0, 0, width, top_h),
                (0, top_h, half_w, bot_h),
                (half_w, top_h, width - half_w, bot_h),
            ]
        if n == 4:
            half_w = width // 2
            half_h = height // 2
            return [
                (0, 0, half_w, half_h),
                (half_w, 0, width - half_w, half_h),
                (0, half_h, half_w, height - half_h),
                (half_w, half_h, width - half_w, height - half_h),
            ]
        row_h = height // n
        slots, y = [], 0
        for i in range(n):
            h = height - y if i == n - 1 else row_h
            slots.append((0, y, width, h))
            y += h
        return slots

    col_w = width // n
    slots, x = [], 0
    for i in range(n):
        w = width - x if i == n - 1 else col_w
        slots.append((x, 0, w, height))
        x += w
    return slots


# --- saliency-based crop selection (faceless scenes) ------------------------

def salient_crop_center(column_energy, crop_w: float, frame_w: float,
                        prev_x: Optional[float] = None,
                        max_step: Optional[float] = None) -> float:
    """Pick the crop-window center x that captures the most saliency energy.

    `column_energy` is a 1-D array of per-column saliency (length == frame_w),
    produced from a cv2 saliency map by the caller. Returns the window center,
    clamped so the window stays in-bounds and optionally rate-limited against
    `prev_x` for temporal stability.
    """
    energy = np.asarray(column_energy, dtype=float)
    w = int(round(crop_w))
    w = max(1, min(w, int(frame_w)))
    half = crop_w / 2.0

    csum = np.concatenate([[0.0], np.cumsum(energy)])
    max_s = max(0, int(frame_w) - w)
    best_s, best_val = 0, -1.0
    for s in range(0, max_s + 1):
        val = csum[s + w] - csum[s]
        if val > best_val:
            best_val = val
            best_s = s
    center = best_s + w / 2.0

    center = min(max(center, half), frame_w - half)
    if prev_x is not None and max_step is not None:
        if center > prev_x + max_step:
            center = prev_x + max_step
        elif center < prev_x - max_step:
            center = prev_x - max_step
    return center


# --- Savitzky-Golay (future two-stage global smoothing) ---------------------

def savgol_1d(values, window: int, polyorder: int):
    """Savitzky-Golay smoothing of a 1-D signal, pure numpy (no scipy).

    Preserves length and reproduces polynomials up to `polyorder` exactly.
    Interior points use precomputed SG coefficients; edges fit a local
    polynomial over the clipped window. Intended for smoothing a full crop
    trajectory in a two-stage track-then-render pass.
    """
    v = np.asarray(values, dtype=float)
    n = len(v)
    if n == 0:
        return v.copy()
    if window % 2 == 0:
        window += 1
    if window > n:
        window = n if n % 2 == 1 else max(1, n - 1)
    half = window // 2
    polyorder = min(polyorder, window - 1)

    offsets = np.arange(-half, half + 1)
    A = np.vander(offsets, polyorder + 1, increasing=True)
    center_coeffs = np.linalg.pinv(A)[0]  # evaluates the fitted poly at t=0

    out = np.empty(n)
    for i in range(n):
        lo, hi = i - half, i + half
        if lo < 0 or hi >= n:
            a, b = max(0, lo), min(n - 1, hi)
            t = np.arange(a, b + 1) - i
            order = min(polyorder, (b - a))
            Aw = np.vander(t, order + 1, increasing=True)
            cw, *_ = np.linalg.lstsq(Aw, v[a:b + 1], rcond=None)
            out[i] = cw[0]
        else:
            out[i] = center_coeffs @ v[lo:hi + 1]
    return out


def smooth_and_clamp(values, window: int, polyorder: int,
                     lo: float, hi: float):
    """Savitzky-Golay smooth a full 1-D trajectory, then clamp into [lo, hi].

    The wired entry point for the two-stage track-then-render reframe pass: a
    cheap, deterministic analogue of smart-reframe's Viterbi ``PathSolver``.
    Where they globally optimise the crop path with dynamic programming over
    per-frame saliency maps, we record the per-frame camera targets in pass one
    and globally low-pass them here before rendering in pass two — same goal
    (a smooth, jitter-free global trajectory) at a fraction of the cost.
    """
    smoothed = savgol_1d(values, window, polyorder)
    return np.clip(smoothed, lo, hi)


# --- alternative global smoothers (ported from mfahsold/montage-ai) ----------

def kalman_rts_smooth(values, process_noise: float = 1.0,
                      measurement_noise: float = 10.0):
    """Forward Kalman + backward RTS smoother over a 1-D camera-center path.

    Constant-velocity model (state ``[position, velocity]``, observe position).
    The forward pass filters causally; the Rauch–Tung–Striebel backward pass
    then refines every estimate using future frames, so the result is a smooth,
    non-causal trajectory that *extrapolates motion through detection gaps*
    (where the input simply repeats the last center) instead of flat-lining —
    something the Savitzky-Golay low-pass and the online EMA/1€/spring smoothers
    can't do. Pure numpy. Direct port of mfahsold/montage-ai
    ``SubjectKalmanFilter.smooth_sequence`` (auto_reframe.py).

    Higher ``measurement_noise`` (relative to ``process_noise``) ⇒ the filter
    trusts the model over the measurements ⇒ smoother output.
    """
    v = np.asarray(values, dtype=float)
    n = len(v)
    if n < 2:
        return v.copy()

    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    Q = np.array([[process_noise, 0.0], [0.0, process_noise * 0.1]])
    R = np.array([[measurement_noise]])

    x = np.array([v[0], 0.0])
    P = np.eye(2) * 100.0
    xf, Pf = [], []  # filtered state + covariance per step
    for z in v:
        # Predict
        x = F @ x
        P = F @ P @ F.T + Q
        # Update
        S = H @ P @ H.T + R
        K = P @ H.T @ np.linalg.inv(S)
        x = x + (K @ (np.array([z]) - H @ x)).flatten()
        P = (np.eye(2) - K @ H) @ P
        xf.append(x.copy())
        Pf.append(P.copy())

    smoothed = [None] * n
    smoothed[-1] = xf[-1]
    for i in range(n - 2, -1, -1):
        P_pred = F @ Pf[i] @ F.T + Q
        C = Pf[i] @ F.T @ np.linalg.inv(P_pred)
        smoothed[i] = xf[i] + C @ (smoothed[i + 1] - F @ xf[i])
    return np.array([s[0] for s in smoothed])


def solve_camera_path_l2(values, lambda_smooth: float = 100.0,
                         lambda_trend: float = 10.0, constraints=None):
    """Global L2-convex camera-path optimiser over a 1-D center signal.

    Minimises ``Σ(xₜ−cₜ)² + λ_smooth·Σ(xₜ−xₜ₋₁)² + λ_trend·Σ(xₜ−2xₜ₋₁+xₜ₋₂)²``
    — i.e. stay near the detected subject, while penalising camera *velocity*
    (shake) and *acceleration* (jerk). Setting the gradient to zero gives the
    closed-form linear system ``(I + λ_smooth·D1ᵀD1 + λ_trend·D2ᵀD2)·x = c``,
    solved here densely in pure numpy. This is a principled global optimiser —
    the closed-form analogue of smart-reframe's Viterbi ``PathSolver`` that the
    Savitzky-Golay pass only approximates. Direct port of mfahsold/montage-ai
    ``CameraMotionOptimizer.solve`` (auto_reframe.py), with its scipy.sparse
    solve replaced by a dense numpy solve to honour reframe_ops' no-scipy rule
    (fine for clip-length paths; a banded/sparse solve is the O(n) upgrade).

    ``constraints``: optional ``{frame_index: target_center}`` keyframes pulled
    in with a strong penalty — manual overrides of the automatic path.
    """
    c = np.asarray(values, dtype=float)
    n = len(c)
    if n < 3:
        return c.copy()

    eye_n = np.eye(n)
    d1 = np.eye(n - 1, n, k=1) - np.eye(n - 1, n, k=0)          # first difference
    d2 = (np.eye(n - 2, n, k=0) - 2.0 * np.eye(n - 2, n, k=1)   # second difference
          + np.eye(n - 2, n, k=2))
    a = eye_n + lambda_smooth * (d1.T @ d1) + lambda_trend * (d2.T @ d2)
    b = c.copy()

    if constraints:
        lam_c = 10000.0  # strong pull toward each keyframe
        for idx, target in constraints.items():
            if 0 <= idx < n:
                a[idx, idx] += lam_c
                b[idx] += lam_c * float(target)

    try:
        return np.linalg.solve(a, b)
    except np.linalg.LinAlgError:
        return c.copy()


def _smooth_axis(values, method: str, window: int, polyorder: int,
                 lo: float, hi: float):
    """Smooth one 1-D camera axis with the selected global method, then clamp.

    ``"savgol"`` (default) keeps the proven Savitzky-Golay behaviour;
    ``"kalman"`` uses the RTS smoother; ``"l2"`` uses the convex path optimiser.
    All three are clamped into ``[lo, hi]`` exactly like ``smooth_and_clamp``.
    """
    if method == "kalman":
        out = kalman_rts_smooth(values)
    elif method == "l2":
        out = solve_camera_path_l2(values)
    else:
        out = savgol_1d(values, window, polyorder)
    return np.clip(out, lo, hi)


def build_smoothed_trajectory(targets, scene_ids, window: int, polyorder: int,
                              x_max: float, y_max: float,
                              min_zoom: float = 1.0, max_zoom: float = 1.6,
                              method: str = "savgol"):
    """Smooth a recorded ``(cx, cy, zoom)`` camera trajectory, per scene segment.

    ``targets[i]`` is the raw per-frame camera target (or ``None`` for frames
    that bypass the cameraman, e.g. GENERAL/DISABLED). ``scene_ids[i]`` is the
    scene index of frame ``i``. Each maximal run of consecutive non-None frames
    that share a scene index is low-passed independently with ``savgol_1d`` —
    so the smoother never pans across a hard cut — and clamped to the source
    bounds. ``None`` entries pass through unchanged, preserving length.

    This is the host-testable core of the two-stage track-then-render reframe
    pass; the cv2 glue in ``reframe.py`` records ``targets`` in pass one and
    renders from the smoothed result in pass two.
    """
    n = len(targets)
    out = [None] * n
    i = 0
    while i < n:
        if targets[i] is None:
            i += 1
            continue
        # Extend a run while frames are non-None and in the same scene.
        j = i
        sid = scene_ids[i]
        while j < n and targets[j] is not None and scene_ids[j] == sid:
            j += 1
        seg = targets[i:j]
        # Pan axes (cx, cy) use the selected global method; zoom always uses
        # savgol — the L2/Kalman optimisers are tuned for the pan *path*, not the
        # narrow, slowly-varying zoom signal.
        xs = _smooth_axis([t[0] for t in seg], method, window, polyorder, 0.0, x_max)
        ys = _smooth_axis([t[1] for t in seg], method, window, polyorder, 0.0, y_max)
        zs = smooth_and_clamp([t[2] for t in seg], window, polyorder, min_zoom, max_zoom)
        for k in range(j - i):
            out[i + k] = (float(xs[k]), float(ys[k]), float(zs[k]))
        i = j
    return out
