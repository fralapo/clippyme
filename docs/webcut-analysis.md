# WebCut analysis

Source: [tangshuang/webcut](https://github.com/tangshuang/webcut) — a browser-based, CapCut-style video-editing UI you embed as a Vue 3 component.

Evaluated against ClippyMe to decide what (if anything) is worth porting. Verdict up front: **WebCut is a manual, browser-only WYSIWYG timeline editor — a different product, language, and execution model from ClippyMe (a headless server-side AI viral-shorts generator). Nothing is port-worthy.** The few capabilities that could conceptually transfer (clip transitions, simple colour filters) are already covered more cheaply by native ffmpeg filters than by porting browser shader code, and ClippyMe already does ffmpeg slice/transcode/audio-extract natively and better.

## What WebCut is

| Aspect | WebCut |
|---|---|
| Goal | Interactive multi-track timeline editing in the browser (human drags/trims/splits clips) |
| Runtime | TypeScript + Vue 3 SFCs, **100% in the browser** — no Node/Python backend, no CLI |
| Engine | [WebAV](https://github.com/bilibili/WebAV) (`@webav/av-canvas` + `@webav/av-cliper`) — WebCodecs + WebGL canvas compositor does all rendering/encoding |
| Transcode | `@ffmpeg/ffmpeg` (**ffmpeg.wasm**, single-threaded; the multi-thread path is commented out for CORS) |
| Storage | OPFS + IndexedDB (`opfs-tools`, `indb`), MD5 asset dedupe |
| Editing model | Human-driven: drag, trim, split, concat, text overlays, transitions placed by hand on a timeline |

WebCut is essentially a **UI shell over WebAV**: ~150 files, overwhelmingly `.vue` UI (`src/views/`, `src/components/`); the non-UI logic is a thin sliver (`src/libs/`, `src/modules/`, `src/hooks/`, `src/db/`). It has **no transcription, no AI moment detection, no face/object tracking, no reframing, no scene detection, no audio analysis** — a human does the cutting.

ClippyMe is the opposite end of the spectrum: a **headless, automated, server-side ffmpeg/OpenCV/YOLO/MediaPipe pipeline** that turns a long URL into finished 9:16 clips with zero manual editing. The execution models do not overlap — browser WebGL/WebCodecs/OPFS code has no analogue in (and cannot be ported to) a Python ffmpeg pipeline.

## Capability-by-capability vs ClippyMe

Read the actual source under `src/libs/`, `src/modules/`, `src/views/`, `src/db/`.

| WebCut capability | File | ClippyMe | Verdict |
|---|---|---|---|
| Timeline editor UI, drag/trim/split/concat, canvas player, text-overlay editing, undo/redo, media library, theming, i18n | `src/views/**`, `src/libs/timeline.ts`, `src/libs/history-machine.ts` | none (no human-in-the-loop timeline by design) | **irrelevant** (different product) |
| ffmpeg.wasm slice / transcode→faststart MP4 / extract-MP3 | `src/libs/ffmpeg.ts` | native ffmpeg + ffprobe subprocess (`media_probe.py`, `download.py`, `diarization.extract_audio_for_asr`, smartcut auto-editor v3) | **ClippyMe** (native is a superset, faster) |
| WebGL transitions (fade / slide / zoom / blinds / dissolve, GLSL on OffscreenCanvas) | `src/modules/transitions/effects-transitions.ts` | none — ClippyMe emits single continuous shorts, no multi-clip transition stage | **gap, but trivial** (ffmpeg `xfade` covers all five) |
| CSS/canvas colour filters (grayscale/blur/brightness/contrast/saturate) | `src/modules/filters/css-filters.ts` | Ken Burns auto-zoom + burned hooks/subtitles | **low value** (ffmpeg `eq`/`gblur`/`hue` if ever wanted) |
| Keyframe sprite animations (fade/slide/zoom/rotate/pulse/shake/bounce/swing/flash) | `src/modules/animations/preset-animations.ts` | none — a viral-shorts pipeline doesn't auto-apply decorative sprite tweens | **out of scope** (browser-sprite-bound) |
| OPFS/IndexedDB asset library, px↔frame timeline math, async-queue/event-bus utils | `src/db/index.ts`, `src/libs/timeline.ts`, `src/libs/async-queue.ts` | n/a (browser storage / UI-coordinate logic) | **not-portable** (no headless use) |

## Why nothing ports

- **Transitions / filters / animations** are **WebGL/canvas/CSS-bound** — they run against `WebGL2RenderingContext`, `OffscreenCanvas`, and WebAV sprite objects in a live browser compositor. Porting GLSL transition shaders to ClippyMe's headless stack would mean a full rewrite, and ffmpeg already ships equivalents: `xfade=transition=fade|slideleft|…|dissolve` (50+ built-in transitions) and `eq`/`gblur`/`hue` for the colour filters. **The better source is ffmpeg's native filter set, not a shader port** — and even those are unwired because ClippyMe produces one continuous clip per moment, so there is no cut to transition across.
- **The ffmpeg.wasm wrapper** (`src/libs/ffmpeg.ts`) is a strict, slower subset of what ClippyMe already does with native ffmpeg subprocesses. Porting it would be a regression.
- **Timeline px↔frame math, undo/redo, OPFS/IndexedDB, every `.vue` view** are interactive-browser-editor concerns with no headless analogue.
- **The entire AI/CV pipeline ClippyMe is built around** — transcription, Gemini viral detection, YOLO+MediaPipe reframing, scene detection, smart-cut/silence removal, loudnorm, cover selection, social publishing — **WebCut has zero of**. The fit is wrong-direction: WebCut is the manual editor a user reaches for *after* an automated tool like ClippyMe hands them clips.

## Bottom line

WebCut and ClippyMe share a domain (video) but not a product, a language, or an execution model — WebCut is "edit it yourself in the browser", ClippyMe is "generate it automatically on a server". There is no algorithmic asset to harvest: the manual-editing UI is irrelevant, the ffmpeg work is something ClippyMe already does natively and better, and the only conceptually-transferable bits (clip transitions, colour filters) are both out of scope for a single-clip shorts pipeline and already available as native ffmpeg filters if they were ever wanted. **No code change is warranted; the net-positive deliverable is this recorded decision** (same pattern as `docs/openreel-video-analysis.md` and `docs/videolingo-analysis.md`).
