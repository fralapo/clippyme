# Reframe improvements — web research & verdict

Date: 2026-06-18
Context: after the empirical optimization pass on `clip_3`
(`fix/reframe-mar-deadband`, PR #20) this is a literature/state-of-the-art
check on the three changes that were applied, to decide **keep vs. replace** and
to catalogue research-validated next steps.

## The three changes under review

1. **MAR NameError fix** — restored active-speaker selection (was throwing every
   frame, swallowed by the corrupt-frame guard → 37% duplicated frames).
2. **Tighter centering dead-band** — `REFRAME_DEADZONE_X` 0.20→0.05,
   `REFRAME_DEADZONE_Y` 0.15→0.08.
3. **`REFRAME_DEBUG_EXC`** diagnostic + regression test.

---

## Verdict: KEEP all three. None is superseded by a better drop-in.

| Change | Research check | Verdict |
|---|---|---|
| MAR fix | n/a — correctness bug | **Keep** (non-negotiable) |
| Dead-band 0.05/0.08 | It is an *online* approximation of Google **AutoFlip's "stationary" mode** (lock the viewport when scene motion is small). No better online drop-in; the principled offline version already exists in ClippyMe as the opt-in global-smooth pass. | **Keep** |
| `REFRAME_DEBUG_EXC` + test | Standard "don't let a guard swallow real exceptions" hygiene. | **Keep** |

The dead-band values were tuned empirically (not from a standard); the sweep
showed they cut centering error ~30% with *lower* jerk, so they generalize as a
safe default. AutoFlip confirms the underlying principle: a still subject should
get a still camera, not micro-tracking.

---

## Research-validated improvements worth doing next (prioritised)

### High value, low cost
1. **Rule-of-thirds vertical target (headroom bias).** Pro convention frames a
   talking head with the **eyes ~1/3 from the top**, not the face centred at
   0.5. `update_target` currently sets `target_center_y = face_y + h/2` (face at
   crop centre). Biasing it so the *eyes* land near 1/3 (≈ shift the crop centre
   down by ~0.10–0.12·crop_h) matches cinematography and is a few lines. Measure
   with the existing `tmp/reframe_eval` harness (the scorer already uses
   `TARGET_Y=0.42`, i.e. it already rewards this).
   Sources: EditMentor, Icon Photography, vidpros.

2. **Head-yaw-aware lead room.** A subject looking off-axis should get space on
   the side they face (the t=5s frame in the last pass was *correctly* offset for
   this reason — perfect centering would be wrong). FaceMesh **already runs every
   even frame for MAR**, so head yaw is nearly free: `cv2.solvePnP` on ~6 canonical
   landmarks → Euler angles, then offset `target_center_x` toward the gaze side.
   This also explains the residual `cx_err` floor the harness couldn't beat.
   Sources: MediaPipe head-pose guides; lead-room composition refs.

### Medium value
3. **Per-scene stationary-vs-track decision (AutoFlip's model).** AutoFlip
   buffers a whole scene, measures object motion, and picks **stationary / pan /
   track** via `motion_stabilization_threshold_percent`. ClippyMe already buffers
   scenes (scene detection) and has a global-smooth pass — adding an explicit
   "lock the camera for this scene if subject motion < threshold" mode would beat
   the per-frame dead-band on near-static shots. The dead-band stays as the
   streaming fallback.
   Source: Google AutoFlip (research.google blog + MediaPipe docs).

4. **L1-optimal camera path.** ClippyMe's global smoothers are savgol / Kalman /
   **L2** (`reframe_ops.solve_camera_path_l2`). Google's L1-optimal path
   (Grundmann et al., the AutoFlip/stabilization basis) is *sparse* — it produces
   genuinely static segments joined by constant/linear/parabolic pans, which reads
   more "professional tripod" than L2's residual drift. Add
   `solve_camera_path_l1` alongside the existing methods (`REFRAME_GLOBAL_METHOD=l1`).
   Source: "Auto-Directed Video Stabilization with Robust L1 Optimal Camera Paths".

### Higher cost (only if accuracy demands it)
5. **Audio-visual active-speaker detection / ASR fusion.** Visual-only MAR
   variance is weaker than SOTA audio-visual ASD (TalkNet, Light-ASD, LoCoNet).
   ClippyMe **already produces Deepgram word timings + diarization**, so a cheap
   win is to *bias* the MAR speaker score by which diarized speaker is talking in
   that time window — no new heavy model, reuses an existing pipeline output.
   A full TalkNet-style model is a large dependency and probably overkill.
   Sources: LoCoNet (arXiv 2301.08237); TalkNet; robust-ASD (arXiv 2403.19002).

### Cosmetic
6. **Blurred-background padding instead of black bars.** AutoFlip fills
   uncoverable areas with the solid background colour or a *blurred* copy of the
   frame rather than black letterbox (GENERAL mode). Nicer-looking fallback.
   Source: AutoFlip.

---

## How the current changes map to the field

ClippyMe's reframer is, feature-for-feature, close to AutoFlip's design
(per-scene strategy, salient-subject detection, smoothing/stabilization, padding
fallback) — and ahead of it in active-speaker selection (AutoFlip has none). The
gaps are: (a) an explicit *stationary* scene mode, (b) L1 path option, (c)
rule-of-thirds/lead-room framing, (d) audio fusion. The applied changes are
correct and on-architecture; the items above are the next increments, not
replacements.

---

## Deep dive: AutoFlip internals (extracted) + what was implemented

Pulled the concrete AutoFlip configuration from the MediaPipe docs:

| Parameter | Default | Meaning |
|---|---|---|
| `motion_stabilization_threshold_percent` | `0.5` | scene held steady if all focus objects stay within this fraction of the frame |
| `snap_center_max_distance_percent` | (unset) | snap the locked viewpoint to exact centre if within this of centre |
| `salient_point_bound` | `0.499` | keep salient points inside the crop |
| `max_scene_size` | `600` | scene buffer cap (frames) |
| Camera path | — | **L2** Euclidean-norm fit of a low-degree polynomial to the bounding boxes (not L1) |
| SignalFusing scores | face 0.85–0.9 > human 0.75–0.8 > object 0.1–0.2 | per-class saliency weight |
| Padding | `blur_cv_size: 200` | blurred-frame fill when content can't be covered |

Two corrections to the first-pass notes above: AutoFlip's reframer path is **L2
polynomial**, which ClippyMe's savgol global-smooth already approximates (so the
L1 idea is a *nice-to-have*, not a gap); and AutoFlip's face>human>object
weighting matches ClippyMe's existing face-over-person-box priority.

**Implemented (this pass):** AutoFlip's stationary lock + center-snap, as the
host-tested pure helper `reframe_ops.stationary_lock`, wired into
`build_smoothed_trajectory` and exposed as `REFRAME_STATIONARY_THRESH` /
`REFRAME_SNAP_CENTER` (opt-in, default off → byte-identical).

### Measured (clip_3, scorer = re-detect faces in output; lower fitness better)

| config | cx_err | jerk | coverage | fitness |
|---|---|---|---|---|
| streaming default (shipped) | 0.129 | 0.055 | 0.719 | **3.80** |
| global-smooth (savgol) | **0.078** | 0.073 | **0.763** | 3.90 |
| global-smooth + stationary 0.15 | 0.099 | 0.069 | 0.757 | 3.87 |

**Reading the numbers honestly:** global-smooth frames *much* better (centering
error ~40% lower, higher coverage — confirmed by eye at t=5s, where the speaker
goes from hard-left to well-centred). Its higher "jerk" is the camera faithfully
holding a moving subject, not jitter; the scorer's heavy jerk weight is what
makes it rank below the streaming default, so the fitness *under*-rates it. The
stationary lock does what AutoFlip intends — trims jerk on near-static scenes —
for a small net gain. Conclusion: keep streaming as the fast default; recommend
`REFRAME_GLOBAL_SMOOTH=1` (optionally `+ REFRAME_STATIONARY_THRESH=0.15`) as the
quality preset. The lesson is that an output-only proxy metric can't fully
referee tracking-vs-stillness — final camera *feel* still needs a human view.

## Sources
- AutoFlip — <https://research.google/blog/autoflip-an-open-source-framework-for-intelligent-video-reframing/>, <https://github.com/google/mediapipe/blob/master/docs/solutions/autoflip.md>
- L1 optimal camera paths — <https://research.google.com/pubs/archive/37041.pdf>
- LoCoNet ASD — <https://arxiv.org/pdf/2301.08237> ; Robust ASD — <https://arxiv.org/html/2403.19002v2>
- Head pose w/ MediaPipe — <https://medium.com/@susanne.thierfelder/head-pose-estimation-with-mediapipe-and-opencv-in-javascript-c87980df3acb>
- Framing/headroom/lead-room — <https://help.editmentor.com/en/articles/6050471-headroom-and-lead-room>, <https://vidpros.com/framing-talking-head-videos-best-practices/>
