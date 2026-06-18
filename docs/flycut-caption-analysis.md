# flycut-caption analysis

Source: [x007xyz/flycut-caption](https://github.com/x007xyz/flycut-caption) — "A complete video subtitle editing React component with AI-powered speech recognition and visual editing."

Evaluated against ClippyMe to decide what (if anything) is worth porting. Verdict up front: **flycut is a strictly narrower, browser-only subset of what ClippyMe already does — with exactly one idea worth taking: interactive transcript-driven trimming.** That idea is now ported as a backend engine (see below).

## What flycut is

| Aspect | flycut-caption |
|---|---|
| Runtime | 100% browser — React 19 + TypeScript + Vite |
| ASR | Whisper via Hugging Face **Transformers.js**, running locally in the browser (Web Worker) |
| Video processing | **WebAV / WebCodecs** in-browser (its sibling project `flycut` is a CapCut-Web clone) |
| Core workflow | transcribe → show subtitle segments → user **selects + deletes** segments → matching video intervals are cut → burn-in / export |
| Editing | visual segment selection, batch delete, **undo/redo history**, real-time preview |
| Export | SRT, JSON, burned-in MP4 |
| Scope | subtitles + trim only. No reframe, no AI moment selection, no publishing. |

## Capability-by-capability vs ClippyMe

| Capability | flycut | ClippyMe | Winner |
|---|---|---|---|
| ASR | local browser Whisper (slow, device-bound, no diarization) | Deepgram Nova-3 cloud (EN+IT code-switch) + faster-whisper fallback, URL-cached, audio-only FLAC extraction | **ClippyMe** |
| Silence / filler removal | **manual** — user deletes segments by hand | **automatic** — `analyze_silences` (filler EN/IT/ES/FR/DE + gaps >0.8s) + auto-editor v3 timeline + audio-loudness polish pass | both — different axes |
| Manual override of the cut | ✅ core feature | ❌ was auto-only (no way to hand-pick spans) | **flycut** → **ported** |
| 9:16 reframe | none | YOLOv8 + MediaPipe, per-scene strategy, comfort mode, global-smooth | **ClippyMe** |
| Viral moment detection | none | Gemini 5-axis rubric | **ClippyMe** |
| Subtitle styling | font/color/position | 6 ASS karaoke presets + Instagram-Stories hook styling + custom fonts | **ClippyMe** |
| Publishing | none | Zernio multi-platform + SmartScheduler | **ClippyMe** |
| Render location | browser (WebCodecs) | server (ffmpeg / auto-editor) | tie — different deployment model |

### Why the browser bits are *not* worth porting

- **Transformers.js Whisper**: a downgrade. ClippyMe's Deepgram path is faster, multilingual code-switching, and offloads the device. Porting browser ASR would duplicate worse.
- **WebAV/WebCodecs cutting**: ClippyMe renders server-side with auto-editor's frame-accurate v3 timeline (+ ffmpeg-concat fallback). Re-implementing cutting in the browser would fork the render path for no gain and lose the audio-polish second pass.
- **Undo/redo store (Zustand)**: ClippyMe already persists per-clip state in `useClipStates` (localStorage). A general history stack is a nice-to-have, not a gap.

## The one idea worth taking — interactive transcript trim

flycut's genuine differentiator: the operator can **look at the transcript and hand-pick what to cut**, instead of trusting an automatic pass. ClippyMe's Smart Cut had no manual override — if it kept a flubbed line or removed a wanted phrase, the user was stuck.

**Pros of adding it**
- Real editorial control for client work (e.g. ASCENSORE): drop a specific sentence, keep a pause for emphasis.
- Composes with the existing auto pass — manual drops layer *on top of* filler/silence detection, not instead of.
- The hard part (frame-accurate render) already exists; only the cut-plan needs a manual input.

**Cons / why it stayed scoped**
- A full transcript-editor UI (segment list, multi-select, live preview) is a sizable frontend feature.
- Browser-side cutting (flycut's approach) is the wrong fit — ClippyMe must render server-side.

**Decision:** port the *engine* now (pure, tested, API-reachable); leave the transcript-editor **UI** as a documented follow-up so it can be built deliberately rather than bolted on.

## What was ported

`src/clippyme/domain/smartcut.py` — pure interval arithmetic, host-unit-tested (`tests/domain/test_smartcut_manual_trim.py`), no ffmpeg/cv2:

- `normalize_drop_ranges(raw)` — tolerant coercion of HTTP-supplied spans (`[[s,e],…]` or `[{"start","end"},…]`); discards garbage, caps count.
- `subtract_ranges(keep, drops)` — removes hand-picked spans from the keep-segment list, splitting a kept span when a drop lands inside it.
- `analyze_silences(..., drop_ranges=None)` — applies manual drops on top of the auto cut; also honours drops on transcripts with no word-level timing (manual spans are absolute, not word-derived).
- `smart_cut(..., drop_ranges=None)` — threads the param; a manual trim renders even for a small/single-segment cut (explicit user intent), while the automatic path keeps its conservative ≥1s guard.

`POST /api/smartcut/{job_id}/{clip_index}` accepts an optional `{"drop_ranges": [[start, end], …]}` body (clip-relative seconds). Legacy callers that POST no body are unaffected — pure auto Smart Cut. `drop_ranges` also rides on `POST /api/compose` and the `compose_first` path of `POST /api/publish`, so a manual trim survives the final download / publish — not just the smartcut preview.

`GET /api/transcript/{job_id}/{clip_index}` returns the per-clip transcript as editable segments (`{index, text, start, end}`, clip-relative seconds) via the pure `clip_transcript_segments` helper.

### Frontend (shipped)

The interactive trim lives in the Smart Cut section of `EditClipModal` (`redesign/captions.jsx`). When Smart Cut is toggled on it lazy-loads `GET /api/transcript`, renders the segments as a tap-to-cut checklist (strikethrough + scissors on dropped lines), and converts the dropped set into `drop_ranges`. The spans flow through `reprocessClip` (Edit), `exportClip` (download) and `PublishModal` (publish), and persist per-clip in `useClipStates` (`dropRanges`) so they survive a reload. So: auto Smart Cut removes silence + fillers, and the operator hand-cuts anything else — flycut's editorial control on top of ClippyMe's automation.
