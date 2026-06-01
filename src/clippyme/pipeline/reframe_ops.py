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
