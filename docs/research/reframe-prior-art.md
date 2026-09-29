# Reframing and shorts-generation prior art

> Research note — not current documentation. See [the research index](README.md).

A survey of projects that solve part of the same problem (landscape → vertical
crop, or long video → short clips). Each entry records the technique and how it
relates to ClippyMe's approach at the time of the survey. Deeper per-project
studies exist for [Autocrop-vertical](autocrop-vertical.md),
[smart-reframe](smart-reframe.md) and
[auto-vertical-reframe](auto-vertical-reframe.md).

## Crop / track reframers

**[kamilstanuch/Autocrop-vertical](https://github.com/kamilstanuch/Autocrop-vertical)**
— PySceneDetect scenes, YOLOv8 person detection on the middle frame of each
scene, then a per-scene TRACK or LETTERBOX decision; frames piped to FFmpeg by
exact frame number; VFR normalised first; audio muxed back with a start-time
offset. Closest match to ClippyMe's design.

**[obi19999/smart-video-reframe](https://github.com/obi19999/smart-video-reframe)**
(studied 2026-06-17) — a ~1000-LOC CLI (the README advertises a GUI and
installers that do not exist): YOLO `.track()` faces, per-scene smoothing,
fit-with-blur fallback, all frames buffered in RAM, `shell=True` ffmpeg, no
tests. ClippyMe already covered everything except one idea: **split-screen
layouts for several faces** (portrait: 2 stacked rows, 3 = top banner + bottom
pair, 4 = 2×2 grid; landscape: equal columns). The layout geometry was ported
as `reframe_ops.split_screen_slots` and removed in 2026-07 because no
multi-face render mode was ever built (git history has it). Wiring such a mode
would need per-face tracking, a most-common face count over a window (so the
layout does not flicker), a per-face box EMA, a new render branch and a
`reframe_mode` option in the UI. It is a product decision, since ClippyMe
deliberately renders one tracked camera.

**[paulpierre/autocrop](https://github.com/paulpierre/autocrop)** — classical
CV, no tracking: samples frames, detects a uniform background, finds the
content boundary and snaps it to 9:16 / 16:9 / 1:1. Useful only for
video-inside-a-frame sources.

**[Poor man's intelligent reframing for GoPro](https://pacavaca.medium.com/poor-mans-intelligent-reframing-for-gopro-videos-c9bb489512db)**
— YOLOv8 + DeepSort (CLIP embeddings) tracking in a first pass, then an eased
crop window in a second pass; a lost subject is held ~3 s then drifts to
centre. The hold-then-drift behaviour matches ClippyMe's lost-subject recovery;
the track-then-render split matches its two-pass global smoothing.

**[bmezaris/RetargetVid](https://github.com/bmezaris/RetargetVid)** (ICIP /
ISM 2021) — saliency maps (Unisal), shot detection (TransNet), HDBSCAN
clustering to pick one focus region, Savitzky-Golay temporal smoothing.
An alternative for scenes with no speaking face; heavy dependencies.

**[keplerlab/Katna](https://github.com/keplerlab/katna)** — keyframe
extraction (LUV frame differences, K-Means, Laplacian-variance sharpness) and
image smart-crop. Relevant to cover-frame selection, not to video reframing.

**[Latent-Reframe](https://latent-reframe.github.io)** — camera control for
video diffusion models at inference time. A different paradigm (generates
camera motion in latent space); not applicable to a deterministic crop
pipeline.

## Shorts pipelines

**[divyaprakash0426/autoshorts](https://github.com/divyaprakash0426/autoshorts)**
— gameplay-focused: audio/motion scoring plus LLM classification into seven
moment types, NVENC rendering, optional TTS voice-over. Parallels ClippyMe's
viral-moment detection; adds voice-over, which ClippyMe does not do.

**[leke-adewa/short-video-maker](https://github.com/leke-adewa/short-video-maker)**
— assembles shorts from supplied images and audio rather than cutting existing
footage. Complementary, not comparable.
