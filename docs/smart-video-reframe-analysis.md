# Comparative analysis: `obi19999/smart-video-reframe` → ClippyMe reframe

Date: 2026-06-17
External repo: <https://github.com/obi19999/smart-video-reframe> @ `main`
Layout: `src/{cli,config}.py` + `detectors/{face_detector,scene_detector}.py` +
`reframer/video_processor.py` + `utils/ffmpeg.py` (~999 LOC). Scope: ClippyMe's
reframe subsystem. Third external reframe study, after
`gauravzazz/smart-reframe` (`smart-reframe-analysis.md`) and
`KazKozDev/auto-vertical-reframe` (`auto-vertical-reframe-analysis.md`).

---

## 0. Maturity caveat (read first)

This repo is **markedly less mature** than the prior two. Concretely:

- **README is AI-generated boilerplate** — it advertises a `.exe`/`.dmg`
  installer and a "Releases Page" that actually point at two checked-in zip
  blobs (`src/utils/*.zip`), not real releases. The described GUI does not
  exist; the code is a CLI.
- **Debug `print()` spam** on every frame (`print("float(conf): ", ...)`,
  `print("threshold: ", ...)`) — no logging framework.
- **Whole-video frame buffering**: `_handle_crop_mode` does
  `frames.append(frame)` for *every* frame before processing, so memory grows
  with clip length. ClippyMe streams frame-by-frame to ffmpeg stdin.
- **`shell=True` ffmpeg** with f-string-interpolated paths (`apply_fit_with_blur`)
  — a command-injection footgun ClippyMe avoids (list-argv subprocess).
- **Dead code**: `upload_frame` builds `filtered_faces` (IoU-dedup) then
  `return faces` (the un-deduped list). The dedup never takes effect.
- **No tests, no CI.**

So most of the repo sits *below* ClippyMe's bar, and several "features" ClippyMe
already does better. The analysis below is deliberately narrow: it extracts the
**one** idea worth taking and is explicit about why everything else was skipped.

---

## 1. Architecture comparison

| Aspect | smart-video-reframe | ClippyMe | Takeaway |
|---|---|---|---|
| Shape | `detectors`/`reframer`/`utils` split, all-in-class methods | `reframe.py` glue + `reframe_ops.py` pure math | ClippyMe's pure/glue split stays the better testability story. |
| Render path | Buffer all frames in RAM → 2 passes in memory → cv2 `VideoWriter` | Streaming single pass to ffmpeg stdin (+ opt-in 2-pass savgol) | ClippyMe scales to long videos; this repo does not. |
| Detector | YOLO `.track()` (configurable `yolov8n`/`yolo11n-face`) | YOLOv8n + MediaPipe faces + MAR speaker | Comparable; ClippyMe adds active-speaker scoring. |
| Identity | center-x sort + IoU dedup (the dedup is dead code) | per-frame re-detect, center match, `iou`/`associate_subject` | ClippyMe already has working IoU helpers. |
| Jitter control | bbox EMA (`smooth_face_detections`) + snap-to-average deadband (`homogenize_nested_dicts`) + per-window count vote (`homogenize_group_sizes`) | two-speed EMA / 1€ / spring, all with a `safe_zone_radius` deadband; `DetectionSmoother` rolling avg | ClippyMe already has the deadband + EMA; nothing net-new here. |
| Scene-segmented smoothing | smooths per scene interval | `build_smoothed_trajectory` smooths per scene segment | Parity. |
| **Multi-face framing** | **split-screen montage** (2-up stack, 3-up top+pair, 2×2 grid) | single cinematic camera only | **The one net-new idea.** Ported as geometry building block. |
| Fit fallback | `apply_fit_with_blur` (scale + boxblur + overlay) | GENERAL letterbox + blur | Parity. |
| Config | `num_faces`, `is_fit`, `width/height` flags | env + per-job reframe mode | Comparable. |

---

## 2. Prioritised improvement list

| Pri | Improvement | Status | Notes |
|---|---|---|---|
| **High** | Multi-face split-screen layout geometry | ✅ ported as tested building block | `split_screen_slots` in `reframe_ops`; unwired — see §3/§4. |
| Medium | Multi-face split-screen **render mode** (wire the geometry into a real output mode) | ⏸ deferred | Net-new product feature. Needs per-face track plumbing + a new render branch + UI mode. Recipe in §4. |
| Low | Per-window face-**count** stabilization (`homogenize_group_sizes`: most-common count vote) | ⏸ deferred | Only matters once multi-face render exists (kills layout flicker). Trivial `Counter` port when needed. |
| Low | Per-face center-x-matched bbox EMA (`smooth_face_detections`) | ⏸ deferred | Also a multi-face-only need; ClippyMe smooths the *camera*, not per-face boxes. |
| Skip | bbox snap-to-average deadband (`homogenize_nested_dicts`) | ❌ already have it | ClippyMe's `safe_zone_radius_x/y` deadband covers this in every smoother. |
| Skip | IoU dedup, EMA, scene-segmented smoothing, fit-with-blur | ❌ already have, better | Parity or ClippyMe-ahead. |
| Skip | Whole-video frame buffering, `shell=True` ffmpeg, `print` spam | ❌ anti-patterns | Strictly worse than ClippyMe's streaming/list-argv/logging. |

---

## 3. What was implemented

### Multi-face split-screen layout — `split_screen_slots` (tested building block)

`reframe_ops.split_screen_slots(n_faces, width, height, portrait=None)` returns
a list of integer `(x, y, w, h)` slot rectangles that tile the output frame with
no gaps or overlaps. Direct port of the layout arithmetic in
`FaceDetector.combine_faces`:

- portrait (9:16 default): `1`→whole frame, `2`→stacked rows, `3`→top banner +
  bottom pair, `4`→2×2 grid, `n`→`n` equal rows;
- landscape: `n` equal columns;
- the last slot in each run absorbs integer-rounding remainder so coverage is
  exact.

Pure math, no cv2, host-unit-tested (8 cases incl. an exact-tiling invariant:
slot areas sum to `W·H`, all in-bounds, pairwise non-overlapping). Ships
**unwired**, matching ClippyMe's existing convention for `rank_subject` /
`associate_subject` / `salient_crop_center` — a verified primitive ready for the
day a multi-face mode lands, without changing any current behavior.

---

## 4. Conflicts & resolutions

- **Split-screen vs ClippyMe's single-camera aesthetic (product conflict).**
  ClippyMe deliberately produces *one* cinematic tracked camera; a split-screen
  montage is a different output style (podcast/interview 2-up, 4-up grids). That
  is a product decision, not a bug fix — so per the "suggest alternatives on
  conflict" instruction, the geometry ships as a tested, documented building
  block and the **render mode is deferred**, not silently switched on. Recipe
  for wiring it later:
  1. In `_handle_crop_mode`'s analogue, keep N tracked faces per frame (reuse
     `associate_subject` for identity, `rank_subject` for selection).
  2. Stabilize the per-frame face count over a window (port
     `homogenize_group_sizes`) and EMA each face box (port
     `smooth_face_detections`) so the layout doesn't flicker.
  3. Call `split_screen_slots(n, out_w, out_h)`; for each slot crop that face's
     source region (reuse the existing crop-center + zoom math) and resize into
     the slot rect; composite. Add a `reframe_mode="split"` (+ `num_faces`) job
     option and a UI toggle.
- **Most of the repo is below ClippyMe's bar.** Reported honestly rather than
  force-porting parity features. The deadband, IoU, EMA, scene-segmented
  smoothing, and fit-with-blur are all already present (and the streaming render,
  list-argv ffmpeg, and structured logging are strictly better). Nothing was
  changed on those axes.
- **No global path optimization here either** (same as verthor). ClippyMe's
  opt-in savgol 2-pass remains ahead.

---

## 5. Verification

- Host `pytest tests/pipeline/test_reframe_ops.py -q` → **56 passed**
  (8 new `split_screen_slots` cases, incl. the exact-tiling invariant).
- Full host `pytest -m "not integration"` re-run to confirm no regression (the
  change is purely additive — one new pure-math function + tests; no existing
  code path touched).
