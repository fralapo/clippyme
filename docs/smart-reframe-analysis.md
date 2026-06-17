# Comparative analysis: `gauravzazz/smart-reframe` → ClippyMe reframe

Date: 2026-06-17
External repo analysed: <https://github.com/gauravzazz/smart-reframe> @ `29822eb`
(MIT licensed). Scope: the auto-reframe subsystem only
(`src/clippyme/pipeline/reframe.py` + `reframe_ops.py`).

---

## 1. Architecture comparison

| Aspect | smart-reframe | ClippyMe | Takeaway |
|---|---|---|---|
| Package shape | Standalone lib (`smart_reframe/`), ~2 800 LOC, modular by concern (`detectors/`, `tracking/`, `framing/`, `solver/`, `audio/`, `compositor/`) | Two files: `reframe.py` (cv2 glue, 944 LOC) + `reframe_ops.py` (pure math, 187 LOC) inside a larger product | Their fine-grained split is cleaner, but ClippyMe's **pure-math / cv2-glue** split is the higher-value idea: it makes the decision logic host-unit-testable. We kept and extended that. |
| Camera path | **Offline / 2-pass**: per-frame 1-D saliency maps → Viterbi DP (`solver/path_finder.py`) finds the globally optimal crop trajectory | **Online / single-pass streaming**: per-frame EMA (or 1€) easing, no look-ahead | smart-reframe's global optimum is smoother; ClippyMe is cheaper and lower-latency. We ported the *spirit* (global smoothing) cheaply. |
| Active speaker | Audio activity (`librosa`) fused with face position | Visual only — Mouth-Aspect-Ratio variance | Audio fusion is real value but a bigger dependency/sync change — deferred. |
| Identity | SFace 128-D ONNX embeddings, re-ID at cosine 0.4 | Frame-to-frame horizontal-center proximity | Embedding re-ID is more robust through occlusion; deferred (extra model + dep). |
| Zoom | Continuous face-occupancy target + **asymmetric smoothing** (fast pull-back, slow push-in) + close-up correction (face ≤55% height) | Coarse 4-bucket zoom ladder, symmetric ease | **Ported** — biggest visible quality win for least risk. |
| Text/banners | Canny edge-density detector (`detectors/text_detector.py`) to avoid cropping captions | None | Deferred (medium): needs cv2 detector + crop-bias logic. |
| Multi-speaker | Split-screen compositor (`compositor/split_screen.py`) | Switches single crop between speakers | Output-format change → out of scope ("don't rewrite"). |

### Similarities (independent convergence — validates both designs)
- Both ship a **1€ filter** (`OneEuroFilter`) for adaptive jitter/lag smoothing.
- Both use MediaPipe faces + a person fallback and a sliding-window detection smoother.
- Both special-case faceless scenes and hard cuts (scene snap).

---

## 2. Prioritised improvement list

| Pri | Improvement | Status | Rationale |
|---|---|---|---|
| **High** | Continuous close-up zoom (face-occupancy target) | ✅ implemented | Removes visible zoom "snaps" at bucket edges; pure math, host-tested. |
| **High** | Asymmetric zoom smoothing (fast pull-back / slow push-in) | ✅ implemented | smart-reframe's headline feel; never leaves a grown face chopped. Pure math. |
| **High** | Global 2-stage trajectory smoothing (wire dormant `savgol_1d`) | ✅ implemented (opt-in) | Cheap, deterministic analogue of their Viterbi `PathSolver`; the codebase already anticipated it. |
| Medium | Text/banner avoidance (Canny density → crop bias) | ⏸ deferred | Real value; needs a cv2 detector + Y-bias in the crop solver. Documented for a follow-up. |
| Medium | Audio-fused active-speaker selection | ⏸ deferred | Adds `librosa` + per-clip audio extraction + A/V sync; larger surface. |
| Low | Face re-ID via SFace embeddings | ⏸ deferred | Adds an ONNX model + runtime; center-distance is adequate today. |
| Low | Split-screen multi-speaker compositor | ⏸ deferred | Changes the output format — conflicts with "don't rewrite". |
| Low | Audio-reactive beat "pulse" zoom | ❌ rejected | Gimmick; inconsistent with ClippyMe's cinematic-stability goal. |

---

## 3. What was implemented

All three High items, kept coherent with ClippyMe's existing
pure-math-in-`reframe_ops` pattern so the new logic is host-unit-testable.

### A. `zoom_for_face_height()` — continuous close-up correction
`reframe_ops.py`. Replaces the 4-bucket ladder (`1.0/1.15/1.3/1.5`) in
`SmoothedCameraman.update_target`. Targets a constant face occupancy
(~40 % of crop height): `zoom = max_crop_h * target_occupancy / face_h`,
clamped to `[1.0, 1.6]`. Adapted from smart-reframe `framing/zoom.py`
`needed_zoom_for_size`, translated into ClippyMe's inverted zoom convention.

### B. `asymmetric_zoom_step()` — fast pull-back, slow push-in
`reframe_ops.py`, wired into `get_crop_box`. Pull-back (wider crop) eases at
`ZOOM_RATE_OUT=0.12`, push-in at `ZOOM_RATE_IN=0.05`. Direct port of
smart-reframe's asymmetric zoom rates.

### C. Two-stage global trajectory smoothing — opt-in
Wires the previously-dormant `savgol_1d` via a new
`build_smoothed_trajectory()` (pure, host-tested) + `smooth_and_clamp()`.
`reframe.py:_render_global_smooth` records the raw per-frame `(cx, cy, zoom)`
target in pass 1, Savitzky-Golay-smooths it **per scene segment** (never across
a cut), then renders in pass 2 via the new `SmoothedCameraman.crop_box_at`.
Gated by `REFRAME_GLOBAL_SMOOTH=1`; default-off keeps the proven single-pass
path byte-identical. This is ClippyMe's cheap analogue of their Viterbi
`PathSolver` (no per-pixel saliency, no DP — just a global low-pass).

### Bonus bugfix (surfaced by the new integration test)
`reframe.py` used `tqdm` and `sys.stdout` without importing either — a latent
break from the original `main.py` extraction that the existing tests never hit
(they only exercise the tracker *classes*, not a full render). Added
`import sys` + `from tqdm import tqdm`, making the module self-contained.

---

## 4. Verification

- Host: `pytest -m "not integration"` → **213 passed, 2 skipped** (16 new pure-math tests).
- Docker: full suite → **237 passed** (was 219), incl. 2 new end-to-end integration
  tests proving the opt-in path renders a valid 9:16 clip with frame-count
  parity against the single-pass path.

---

## 5. Conflicts with current design & chosen resolutions

- **Streaming vs offline.** ClippyMe is intentionally single-pass for low
  latency. Rather than convert the default path to 2-pass (a rewrite), the
  global smoother is **opt-in** and isolated, mirroring the existing
  `REFRAME_SMOOTHER=euro` opt-in convention.
- **Saliency-DP vs savgol.** Their Viterbi solver is powerful but heavy
  (O(N·states·velocity-window) + per-frame saliency maps). A global savgol
  low-pass achieves the dominant benefit (a smooth, jitter-free global path)
  at a fraction of the cost and with zero new dependencies — a better fit for a
  product pipeline that also runs Deepgram, Gemini, YOLO and ffmpeg per job.
