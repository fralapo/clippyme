# Reframing and shorts-generation prior art

> Research note — not current documentation. See [the research index](README.md).

A survey of projects that solve part of the same problem (landscape → vertical
crop, or long video → short clips). Each entry records the technique and how it
relates to ClippyMe's approach at the time of the survey. Deeper per-project
studies exist for [Autocrop-vertical](autocrop-vertical.md) and
[smart-video-reframe](smart-video-reframe.md).

## Crop / track reframers

**[kamilstanuch/Autocrop-vertical](https://github.com/kamilstanuch/Autocrop-vertical)**
— PySceneDetect scenes, YOLOv8 person detection on the middle frame of each
scene, then a per-scene TRACK or LETTERBOX decision; frames piped to FFmpeg by
exact frame number; VFR normalised first; audio muxed back with a start-time
offset. Closest match to ClippyMe's design.

**[obi19999/smart-video-reframe](https://github.com/obi19999/smart-video-reframe)**
— YOLOv8 face tracking with continuous crop/pan, desktop GUI. Same idea as
ClippyMe, but no active-speaker scoring.

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
