# Browser video editors (FreeCut, OpenReel, WebCut)

> Research note — not current documentation. See [the research index](README.md).

Three open-source browser editors were evaluated for anything worth porting.
The verdict was the same for all three: **nothing to port**.

| Project | What it is |
|---------|-----------|
| [walterlow/freecut](https://github.com/walterlow/freecut) | Multi-track timeline editor in TypeScript/React on WebGPU + WebCodecs + Mediabunny; Chromium-only, no ffmpeg |
| [Augani/openreel-video](https://github.com/Augani/openreel-video) | Client-side "CapCut alternative" in the browser |
| [tangshuang/webcut](https://github.com/tangshuang/webcut) | CapCut-style editing UI embedded as a Vue 3 component |

## Why nothing was ported

- **Different product.** They are human-driven editors: a person drags, trims
  and keyframes clips. ClippyMe is a headless server pipeline that turns a long
  video into finished clips without manual editing.
- **Different execution model.** Their engines are WebGPU shaders, WebCodecs
  and browser storage (OPFS, IndexedDB). None of that runs in a Python/ffmpeg
  backend.
- **Overlapping features already exist in ClippyMe in a stronger form.**
  Transcription (cloud providers with a local fallback), scene detection
  (PySceneDetect `ContentDetector`), subtitle formatting (ASS karaoke presets).
  FreeCut's chi-squared histogram scene-cut detector is a hand-rolled version
  of the algorithm family PySceneDetect already provides.
- **Remaining capabilities have no use case here.** Transitions, colour
  filters and time-stretch would come from ffmpeg's native filters (`xfade`,
  `eq`, `atempo`) if ever needed. Beat/tempo detection (OpenReel) has no role
  in talking-head shorts; `librosa` would be the source if it ever did.

The useful outcome of these evaluations is the recorded decision itself.
