# Comparative analysis: `KazKozDev/auto-vertical-reframe` → ClippyMe reframe

Date: 2026-06-17
External repo: <https://github.com/KazKozDev/auto-vertical-reframe> @ `33ac38d`
(MIT). Single module `src/verthor/auto_reframe.py` (2253 LOC). Scope: ClippyMe's
reframe subsystem. This is the second external reframe study; the first
(`gauravzazz/smart-reframe`) is in `smart-reframe-analysis.md`.

---

## 1. Architecture comparison

| Aspect | verthor | ClippyMe (post-upgrade) | Takeaway |
|---|---|---|---|
| Shape | One 2253-LOC file, dataclasses (`Candidate`, `CameraState`) + free functions | `reframe.py` glue + `reframe_ops.py` pure math | ClippyMe's pure/glue split stays the better testability story. |
| Detector | **YOLOv11-seg** (instance masks) + ByteTrack | YOLOv8n (bbox) + MediaPipe faces | Masks give a true silhouette centroid; net-new. |
| Tracking ID | **ByteTrack** persistent IDs (`lap` Hungarian) + subject lock/hysteresis | Per-frame re-detect, center-distance match (IoU `associate_subject` stays unwired) | ByteTrack is the robust-identity piece ClippyMe still lacks. |
| Subject choice | **Linear ranking model** fusing 8+ signals | MAR-variance only | Ported the model as a building block. |
| Camera | Online **spring-damper** (velocity+damping+cap) + EMA velocity feed-forward; **no** global pass | Two-speed EMA / 1€ / **opt-in savgol global 2-pass** | ClippyMe is *more* advanced on global smoothing. Ported their spring as a 3rd smoother. |
| Framing | Pose-driven headroom, mask centroid, two-person union crop | Face-occupancy zoom, single-subject | Pose/two-person are net-new. |
| Presets | `talking_head/sports/pets/cars` (class/zoom/step bundles) | Fixed constants | Useful concept; the per-axis max-step is the portable nugget. |
| Saliency | Handcrafted spectral-residual + optional DeepGaze-MR (torch.hub) | none | Handcrafted is dep-free; DeepGaze is heavyweight/experimental. |
| Robustness | Per-subsystem telemetry, encoder-capability fallback, per-candidate try/except | Deepgram→Whisper fallback, atomic metadata | Telemetry/summary pattern worth adopting. |

### Key correction to their README
Despite README claiming a "path optimizer," verthor's camera is **entirely
online/causal** (spring-damper + EMA feed-forward) — there is no global/offline
trajectory optimization. ClippyMe's opt-in two-stage savgol pass is strictly
more sophisticated here, so nothing was ported on that axis.

---

## 2. Prioritised improvement list

| Pri | Improvement | Status | Notes |
|---|---|---|---|
| **High** | Spring-damper smoother (velocity + damping + per-frame cap) | ✅ implemented (opt-in) | 3rd `REFRAME_SMOOTHER=spring` mode; pure-math, host-tested. |
| **High** | Hard per-frame pan-rate cap | ✅ implemented (opt-in) | `REFRAME_MAX_STEP_PX`; applies to every smoother. |
| **High** | Subject ranking model (linear signal fusion) | ✅ ported as tested building block | `rank_subject` in `reframe_ops`; not wired into the default path — see §4. |
| Medium | Mask-centroid framing (YOLOv8n → yolo11n-seg) | ⏸ deferred | True silhouette centroid + top-of-head. Needs a model swap + mask plumbing. |
| Medium | ByteTrack persistent IDs + lock/hysteresis (`min_hold=12`, `switch_thresh=1.20`, `0.92` sticky) | ⏸ deferred | Wires the unwired `associate_subject`; needs `model.track(persist=True)` streaming + `lap` dep. |
| Medium | Two-person union framing (trigger `second.score ≥ 0.78·first.score`, union bounds + zoom-to-fit, pad 12%x/16%y) | ⏸ deferred | Net-new for podcast/interview; needs candidate ranking + bounds plumbing. |
| Medium | Pose-driven headroom (`framing_cy=(eye+shoulder)/2`, head-and-shoulders `±1.15·fw`, `top −1.55·fh`, `bottom +4.0·fh`) | ⏸ deferred | Adds MediaPipe Pose inference per subject. |
| Medium | EMA velocity feed-forward (`v=0.6·v+0.4·Δ`, lead `x·0.8 / y·0.45`) | ⏸ deferred | Predictive lead-the-subject; needs A/B vs current smoothers. |
| Low | Saliency-driven no-subject recovery (spectral-residual; replaces drift-to-center for B-roll) | ⏸ deferred | Dep-free cv2; nicer than center-drift on faceless cutaways. |
| Low | Post unsharp/denoise (`hqdn3d=1.2:1.2:6:6,unsharp=5:5:0.6:5:5:0.0`) | ⏸ deferred | One ffmpeg-filter string; recovers sharpness lost to zoom upscale. |
| Low | Telemetry/structured per-clip summary + encoder fallback | ⏸ deferred | Cheap quality-signal for debugging bad reframes. |
| Skip | DeepGaze-MR deep saliency model | ❌ | Heavyweight torch.hub research model; author calls it slow/experimental. Adopt only its fallback-wrapper discipline. |

---

## 3. What was implemented

All in `reframe_ops.py` (pure math, host-unit-tested), wired into
`SmoothedCameraman` where stateful.

### A. Spring-damper smoother — `advance_value_with_velocity` (opt-in)
`REFRAME_SMOOTHER=spring`. `velocity = velocity·damping + (target−current)·response`,
clamped to `±max_velocity`, then `current += velocity`. Carries momentum (real
operator accel/decel) and can never jump more than the cap per frame. Joins the
existing `euro`/EMA modes. Tunables `REFRAME_SPRING_RESPONSE` (0.18),
`REFRAME_SPRING_DAMPING` (0.82).

### B. Hard per-frame pan-rate cap — `limit_step` (opt-in)
`REFRAME_MAX_STEP_PX` (px, 0 = off). Applied as a final clamp on the per-frame
center move for **every** smoother mode, and as the spring's `max_velocity`.
Guarantees the camera never snaps more than N px/frame.

### C. Subject ranking model — `rank_subject` (tested building block)
Exact port of verthor's `SubjectRankingModel`: `class_bias + Σ weightᵢ·featureᵢ`
over det-conf / mask / center-affinity / face / pose / saliency / tracking /
lock / speaker signals. Host-unit-tested with the published weights.

---

## 4. Conflicts & resolutions

- **Ranking model not wired into the default path (deliberate).** ClippyMe has
  no segmentation masks, pose, saliency, or persistent track IDs yet, so most of
  the model's features would be constant/zero and it would only marginally
  re-weight the existing MAR score — while *changing* default speaker selection
  in a way no automated test can A/B. So `rank_subject` ships as a tested,
  documented building block (the same convention ClippyMe already uses for the
  unwired-but-tested `associate_subject` / `salient_crop_center`). It becomes the
  natural fusion point once the deferred mask/pose/ByteTrack signals land.
- **Spring vs existing smoothers.** Not a gap — a third option. Kept opt-in and
  default-off, mirroring `REFRAME_SMOOTHER=euro`, so default camera feel is
  unchanged. The genuinely net-new idea beyond a 3rd lerp is the **explicit
  per-frame velocity cap**, surfaced separately as `REFRAME_MAX_STEP_PX` so it
  composes with EMA and 1€ too.
- **Global path optimization.** verthor has none; ClippyMe already shipped the
  opt-in savgol 2-pass last round. No change.

---

## 5. Verification

- Host `pytest -m "not integration"` → **226 passed, 2 skipped** (13 new pure-math cases).
- Docker full suite → **250 passed**, incl. running the reframe integration tests
  under `REFRAME_SMOOTHER=spring REFRAME_MAX_STEP_PX=40` (no crash, frame-count parity).
