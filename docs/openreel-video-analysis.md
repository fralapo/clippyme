# OpenReel-Video analysis

Source: [Augani/openreel-video](https://github.com/Augani/openreel-video) — "Professional browser-based video editor, an open-source CapCut alternative."

Evaluated against ClippyMe to decide what (if anything) is worth porting. Verdict up front: **OpenReel is a client-side browser NLE — a different product, a different language, and a different execution model from ClippyMe (a headless server-side AI viral-shorts generator). Nothing is port-worthy.** The one capability ClippyMe genuinely lacks (beat/tempo detection) has no use case in a talking-head shorts pipeline, and if it were ever wanted, `librosa` is the right source — not a reimplementation of OpenReel's TypeScript.

## What OpenReel is

| Aspect | OpenReel |
|---|---|
| Goal | Interactive multi-track video editing in the browser (timeline NLE, CapCut-style) |
| Runtime | React 18 + TypeScript monorepo (pnpm), ~125k LOC across `apps/web` + `packages/core` |
| Video/audio | MediaBunny + WebCodecs API (hardware encode/decode) |
| Rendering | WebGPU compositor + THREE.js + Canvas 2D — all GPU/shader-bound |
| State / storage | Zustand + IndexedDB (local project persistence) |
| Editing model | Human-driven: keyframes, transitions, effects, text animations placed by hand on a timeline |

The whole architecture is a **real-time, GPU-accelerated, human-in-the-loop browser editor**. ClippyMe is the opposite end of the spectrum: a **headless, automated, server-side ffmpeg/OpenCV/YOLO/MediaPipe pipeline** that turns a long URL into finished 9:16 clips with zero manual editing. The execution models do not overlap — browser WebGPU shader code and WebCodecs encoders have no analogue in (and cannot be ported to) a Python ffmpeg pipeline.

## Capability-by-capability vs ClippyMe

Read the actual source under `packages/core/src/` (`audio/`, `animation/`, `video/`, `text/`).

| Module | OpenReel | ClippyMe | Verdict |
|---|---|---|---|
| `audio/beat-detection-engine.ts` | RMS-energy onset detection + harmonic-voting BPM | **none** — only loudnorm + auto-editor silence | gap, but **out of scope** (see below) |
| `audio/fft.ts` | hand-rolled radix-2 Cooley-Tukey FFT | scipy `rfft` if ever needed | **already-have** (scipy supersedes) |
| `audio/highlight-analyzer.ts` | 5 s RMS/dB chunk "interesting"-moment heuristic | Gemini 5-axis viral rubric over full transcript | **ClippyMe** (strictly more capable) |
| `animation/easing-functions.ts` | 31 eases + cubic-Bézier solver + damped-spring | savgol + Kalman RTS + 1€ filter + damped-spring (`reframe_ops`) | **already-have / exceeded** |
| `video/*` (motion-track, chroma, transitions, gpu-compositor) | WebGPU/WebCodecs shader compositing + feature-point tracking | PySceneDetect + YOLOv8 + MediaPipe + weighted-object crop | **not-portable** (shader-bound; no novel CV) |
| `text/subtitle-engine.ts` | SRT parse/export + merge/split, no smart grouping | semantic line-split (`_group_words`, connector/sentence boundaries, EN/IT/ES/FR/DE) | **ClippyMe** (far more capable) |
| `text/caption-animation-renderer.ts` | per-frame `{opacity, scale, offsetY}` karaoke/bounce/typewriter | native ASS `\k` karaoke via libass | **already-have / not-portable** |
| `text/audio-text-sync-engine.ts` | clip-to-beat-grid B-roll montage sync | none | **out of scope** (no beat-cut montage product) |

### The one gap — beat/tempo detection — and why it stays unported

`beat-detection-engine.ts` (~450 LOC) is a clean, dependency-light beat detector: windowed RMS energy → adaptive threshold (`median + (mean-median)*(1-sensitivity)`) → peak-picking with local-max / rise / min-spacing constraints → BPM by inter-onset-interval histogram with **harmonic voting** (fundamental 1.0, double-tempo 0.5, half-tempo 0.3) → beats snapped to nearest onset. ClippyMe has no beat/tempo/onset detection of any kind (grep-confirmed: no `librosa`, no onset code).

It stays unported for two compounding reasons:

1. **No product use case.** ClippyMe's clips are *viral talking-head moments* selected by Gemini — speech, not music. Beat detection pays off only for music-video / beat-cut montage editing (which is exactly what OpenReel's `audio-text-sync-engine` does), and that is not the ClippyMe product. Porting a beat detector would add a module with **no consumer** — dead code by construction.
2. **Wrong source even if it were wanted.** If a beat-aware feature is ever built (e.g. snapping cut points or transitions to a backing track), `librosa.onset.onset_detect` + `librosa.beat.beat_track` give a more robust, battle-tested result in a few lines and fit ClippyMe's Python/numpy stack natively. The transferable *idea* (harmonic-voting BPM + onset-snap) is worth remembering; the TypeScript implementation is not worth carrying.

The honest engineering call is to **record the idea, not import it** — this doc is that record.

### Why the rest doesn't port

- **FFT** — a hand-rolled Cooley-Tukey is strictly inferior to scipy's `rfft` on a server. Nothing to take.
- **Easings / spring** — OpenReel's spring is the same damped-harmonic-oscillator physics ClippyMe already runs in `reframe_ops.advance_value_with_velocity`, and its 31 eases are *display tweens* for UI keyframes, not signal smoothers for a camera path. ClippyMe's smoother suite (savgol / Kalman RTS / 1€ / spring) already matches or exceeds it for the only thing ClippyMe smooths.
- **Video** — every `video/` engine is WebGPU/WebCodecs/Canvas compositing (chroma key, transitions, GPU compositor) or browser feature-point motion tracking for sticker-pinning. None is a subject-framing or scene-detection algorithm that differs from ClippyMe's CV stack, and the shader code is unportable by definition.
- **Text** — OpenReel's subtitle engine is a basic SRT merge/split with **no** intelligent line grouping; ClippyMe's `subtitles.py` semantic splitter is already more sophisticated. The caption animator computes per-frame transforms that libass karaoke (`\k` tags) renders for free, so there is nothing to gain.

## Bottom line

OpenReel and ClippyMe share a domain (video) but not a product, a language, or an execution model. The comparison is useful as confirmation: ClippyMe's subtitle splitting, reframe smoothing, and viral selection are each ahead of OpenReel's equivalents, and the only thing OpenReel has that ClippyMe lacks — beat detection — is out of scope for a talking-head shorts generator. **No code change is warranted; the net-positive deliverable is this recorded decision.**
