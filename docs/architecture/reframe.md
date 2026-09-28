# Reframe

Reframing turns a landscape source slice into the output aspect (9:16 by
default; the aspect is an explicit per-job parameter). It runs inside the job
and again, on demand, when a user switches a clip's mode.

## Modes

| Mode | Behaviour |
|------|-----------|
| `auto` (default) | Face and active-speaker tracking with a per-scene strategy (below). |
| `subject` | FrameShift-style weighted-interest crop: every detection contributes by class weight × area × confidence (faces 1.0, persons 0.8, other objects 0.5, `REFRAME_FRAMESHIFT_WEIGHTS`). A face pulls hardest; a scene with nothing detected is letterboxed. `object` is accepted as a legacy alias. |
| `disabled` | Letterbox: the whole frame, scaled to the output width, between black bars. Nothing is cropped. `letterbox_zoom` (0.05–0.15) optionally trims the width for a fixed zoom. The Ken Burns push is forced off so a locked frame never drifts. |

A finished clip can switch mode with `POST /api/reframe/{job_id}/{clip_index}`,
which runs `main.py --reframe-only` on the preserved `source_<clip>.mp4`.
Jobs created before slices were kept answer 409.

## `auto`: per-scene strategy

Scenes come from PySceneDetect. Seven frames per scene are sampled to choose:

- **TRACK** — one near-static speaker: a crop locked on the face.
- **WIDE** — two or more faces, or one subject that moves more than
  `REFRAME_MOTION_WIDE_THRESH` of the frame: a locked, zoomed-out crop.
- **GENERAL** — no faces: letterbox (optionally a saliency or weighted-object
  crop via `REFRAME_SALIENT_GENERAL` / `REFRAME_OBJECT_WEIGHTS`).

Who is speaking is decided by YOLOv8 person detection plus MediaPipe FaceMesh
mouth movement, with identities associated by 2-D distance and box overlap,
switch hysteresis (`REFRAME_SPEAKER_SWITCH_MARGIN`), a minimum face size, and
optional two-person dialogue framing. Tracker state resets at every scene cut.

## Camera policy: the camera does not move within a shot

Continuous tracking with a zoom that "breathes" is what makes auto-reframed
video feel seasick. The default policy therefore keeps the camera still:

- **Comfort mode** (`REFRAME_COMFORT`, on) renders in two passes: track the
  whole clip, then decide the camera per scene.
- **Static auto** (`REFRAME_STATIC_AUTO`, on) makes that decision one fixed
  crop per scene (`collapse_scene_targets`). Zoom can change only at a cut,
  which reads as a new shot.

Consequences, kept for A/B comparison rather than as live options:

- With `REFRAME_STATIC_AUTO=0` the two-pass render smooths a moving camera
  path instead: `REFRAME_GLOBAL_METHOD` (`savgol`, `kalman`, `l2`), the
  stationary lock (`REFRAME_STATIONARY_THRESH`) and the per-scene zoom lock
  (`REFRAME_ZOOM_LOCK`) only take effect there.
- The single-pass streaming tracker, and with it `REFRAME_SMOOTHER=euro|spring`
  and the dead-zone settings, only renders the output with `REFRAME_COMFORT=0`
  and `REFRAME_GLOBAL_SMOOTH` unset.

If a subject is lost for `REFRAME_LOST_HOLD` frames, the camera eases back to
the centre instead of freezing on empty space.

## Code map

| Module | Contents | Host-testable |
|--------|----------|---------------|
| `pipeline/reframe.py` | Render orchestration: scene analysis, strategies, render loops, `process_video_to_vertical` | No (OpenCV) |
| `pipeline/reframe_detect.py` | YOLO and MediaPipe detectors | No |
| `pipeline/reframe_track.py` | `SpeakerTracker`, `SmoothedCameraman`, smoothing filters | Yes |
| `pipeline/reframe_ops.py` | Camera and decision math: trajectories, locks, zoom, letterbox geometry | Yes |
| `pipeline/media_probe.py` | ffprobe helpers: variable frame rate, stream start times, fps | Yes |

New reframe logic goes in `reframe_ops.py` or `reframe_track.py` so it can be
tested without the CV stack. `reframe.py` re-exports the moved tracking and
detection names for older imports.

Tuning knobs: [configuration reference](../reference/configuration.md#reframe).
Background research (AutoFlip, prior art):
[research/reframe-autoflip.md](../research/reframe-autoflip.md),
[research/reframe-prior-art.md](../research/reframe-prior-art.md).
