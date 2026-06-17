# Comparative analysis: `mfahsold/montage-ai` → ClippyMe reframe

Date: 2026-06-17
External repo: <https://github.com/mfahsold/montage-ai> @ `main`
Size: ~80k LOC Python across `src/montage_ai/` (86 modules) + k3s deploy, Drone /
Jenkins CI, MoE expert routing, creative director, color grading, dialogue
ducking, distributed render. Scope of this study: ClippyMe's reframe subsystem.
Fourth external reframe study, after `gauravzazz/smart-reframe`,
`KazKozDev/auto-vertical-reframe`, and `obi19999/smart-video-reframe`.

---

## 0. Scope note

montage-ai is a large, genuinely mature platform — far broader than ClippyMe
(distributed k3s rendering, a mixture-of-experts selection engine, full color
grading, audio dialogue ducking, timeline/EDL export). A 1:1 comparison of the
whole system is out of scope and mostly off ClippyMe's product axis. This study
stays in the **reframe lane** — `src/montage_ai/auto_reframe.py` (725 LOC) — where
ClippyMe has deep, host-testable infrastructure (`reframe_ops.py`) and a clean
port path. Broader net-new subsystems observed are catalogued in §4 as deferred,
with rationale, rather than force-fit.

---

## 1. Architecture comparison (reframe)

| Aspect | montage-ai `auto_reframe.py` | ClippyMe | Takeaway |
|---|---|---|---|
| Shape | `AutoReframeEngine` + `CameraMotionOptimizer` + `SubjectKalmanFilter`, all in one cv2 module | `reframe.py` glue + `reframe_ops.py` pure math | Comparable; ClippyMe's pure/glue split keeps the math host-tested. |
| Camera path | **Global L2 convex optimiser** (data + velocity + accel penalties, keyframe constraints) via scipy.sparse solve | Two-speed EMA / 1€ / spring (online) + opt-in **savgol** global 2-pass | montage-ai's optimiser is *more principled* than savgol. **Ported.** |
| Smoothing fallback | **Forward-backward Kalman (RTS) smoother**, scipy-free | savgol / EMA | RTS extrapolates through detection gaps — net-new. **Ported.** |
| Keyframe overrides | constraints dict → strong-penalty pull in the solve | none | Net-new; came free with the L2 port. |
| Detector | MediaPipe FaceDetection (full-range) + IoU subject lock + OpenCV KCF/CSRT object-track fallback | YOLOv8n + MediaPipe FaceMesh + MAR speaker | Comparable; ClippyMe adds active-speaker scoring. |
| Lost-subject | hold last center; reset after `fps·1.0` lost frames | `drift_to_center` after `REFRAME_LOST_HOLD` | Parity (different policy). |
| Render | segmented `trim+crop+concat` filtergraph (camera "cuts") | streaming single-pass + opt-in 2-pass | Parity. |
| Optional-dep discipline | `find_spec` lazy scipy/mediapipe, graceful fallback, test stubs | env-gated, Deepgram→Whisper fallback | Both strong; their lazy-import-to-cut-startup pattern is worth noting. |

---

## 2. Prioritised improvement list

| Pri | Improvement | Status | Notes |
|---|---|---|---|
| **High** | Forward-backward **Kalman RTS** global smoother | ✅ implemented + wired (opt-in) | `kalman_rts_smooth`; `REFRAME_GLOBAL_METHOD=kalman`. Handles detection gaps. |
| **High** | **L2 convex** camera-path optimiser (data/velocity/accel + keyframe constraints) | ✅ implemented + wired (opt-in) | `solve_camera_path_l2`; `REFRAME_GLOBAL_METHOD=l2`. Principled global optimiser. |
| Medium | Lazy `find_spec` import to cut package startup (~700ms claim) | ⏸ note | ClippyMe already lazy-loads YOLO/MediaPipe via subprocess reframe; minor. |
| Low | Color grading / LUT pipeline (`clip_enhancement.py`, `data/luts`) | ⏸ deferred | Net-new product area; off the current reframe scope. |
| Low | Dialogue ducking (`dialogue_ducking.py`) | ⏸ deferred | ClippyMe has loudnorm; ducking is a separate audio feature. |
| Low | MoE selection engine (`moe/experts`, `selection_engine.py`) | ⏸ deferred | Overlaps ClippyMe's Gemini viral detection; large, different design. |
| Skip | Distributed k3s render, MoE control plane, timeline EDL export | ❌ | Platform-scale infra beyond ClippyMe's single-host scope. |

---

## 3. What was implemented

Both ports live in `reframe_ops.py` (pure numpy, no cv2/scipy, host-unit-tested)
and are wired as **selectable global-smoothing methods** in the existing opt-in
two-stage pass. The default is unchanged.

### A. Kalman RTS smoother — `kalman_rts_smooth`
Constant-velocity Kalman forward pass + Rauch–Tung–Striebel backward pass over
the 1-D pan path. Non-causal, so it refines every frame with future context, and
— unlike savgol / EMA — *extrapolates motion through detection gaps* instead of
flat-lining on the repeated last-center. Pure numpy port of montage-ai
`SubjectKalmanFilter.smooth_sequence`.

### B. L2 convex path optimiser — `solve_camera_path_l2`
Minimises `Σ(x−c)² + λ_smooth·Σvelocity² + λ_trend·Σaccel²`; the zero-gradient
condition is the linear system `(I + λ_smooth·D1ᵀD1 + λ_trend·D2ᵀD2)·x = c`,
solved densely in numpy. A principled global optimiser — the closed-form analogue
of smart-reframe's Viterbi `PathSolver` that the savgol pass only approximates.
Supports `{frame: target}` keyframe constraints (strong-penalty pull). Port of
montage-ai `CameraMotionOptimizer.solve`, with its scipy.sparse solve swapped for
a dense numpy solve to honour reframe_ops' no-scipy rule.

### C. Wiring — `REFRAME_GLOBAL_METHOD`
`build_smoothed_trajectory(..., method="savgol")` gains a method selector;
`reframe._render_global_smooth` reads `REFRAME_GLOBAL_METHOD` (default `savgol`).
The pan axes (cx, cy) use the chosen method; zoom always stays savgol (the
optimisers are tuned for the pan path, not the narrow zoom signal). Active only
when `REFRAME_GLOBAL_SMOOTH=1` is also set.

---

## 4. Conflicts & resolutions

- **Savgol is the incumbent global smoother (choice conflict).** ClippyMe already
  shipped savgol for `REFRAME_GLOBAL_SMOOTH`. Per the "suggest alternatives on
  conflict" instruction, the L2 optimiser and Kalman RTS smoother are added as
  **opt-in alternatives** behind `REFRAME_GLOBAL_METHOD`, with `savgol` remaining
  the default — so default camera feel is provably unchanged (a unit test asserts
  the default is byte-identical to explicit savgol). They can be A/B'd the same
  way as the other smoothers (output must be viewed).
- **scipy dependency.** montage-ai's optimiser uses `scipy.sparse`; reframe_ops
  is deliberately scipy-free (savgol is hand-rolled to avoid it). Resolved by
  porting the optimiser with a dense numpy solve — correct and dependency-free,
  at O(n³) instead of O(n) for the banded system. Acceptable for clip-length
  paths (≤~2250 frames); the doc notes the banded/sparse solve as the upgrade if
  a long-form path ever needs it.
- **Zoom vs pan.** The convex/Kalman models target a positional path; applying
  them to the slowly-varying 1.0–1.6 zoom signal would be ill-conditioned, so
  zoom keeps savgol while only cx/cy switch method.
- **Breadth not force-ported.** montage-ai's color grading, dialogue ducking, MoE
  selection, and distributed render are real and good, but are separate product
  areas (or platform-scale infra) — catalogued as deferred rather than rewritten,
  honouring "Non riscrivere tutto."

---

## 5. Verification

- Host `pytest tests/pipeline/test_reframe_ops.py -q` → **70 passed**
  (14 new: Kalman RTS, L2 optimiser incl. keyframe-constraint + lambda-monotonicity,
  and the `method` dispatch incl. a default-equals-savgol byte-identity test).
- Full host `pytest -m "not integration"` → **248 passed, 2 skipped** — no
  regression. The reframe.py wiring is additive and default-gated (`savgol`), so
  the integration global-smooth path is unchanged at default; the new methods are
  exercised directly by the unit tests above.
