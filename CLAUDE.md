# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ClippyMe is a self-hosted AI video platform that transforms long-form videos (YouTube or local uploads) into viral 9:16 vertical shorts. Fork of OpenShorts.

## Repo layout (post-refactor)

All Python backend code lives under `src/clippyme/` (src-layout, installed via `pip install -e .`):

- `src/clippyme/api/` — FastAPI app (`app.py`), `schemas.py`, `security.py`
- `src/clippyme/pipeline/` — `main.py` orchestrator (~800 LOC, was 2216), `deepgram_transcribe.py`, `gemini_parser.py`, `gemini_service.py`, plus extracted stages: `transcribe_cache.py`, `download.py`, `scene_detection.py`, `postprocess.py`, `diarization.py`, `hardware.py` (DEVICE/Whisper-model selection), `reframe.py` (cv2/YOLO/MediaPipe core: `process_video_to_vertical` + `SmoothedCameraman`/`SpeakerTracker`/`DetectionSmoother` + face/person detection; `ASPECT_RATIO` is a module global `main` sets per-job via `reframe.ASPECT_RATIO = ...`), pure-math `reframe_ops.py`, and `media_probe.py` (cv2-free ffprobe wrappers + pure A/V-sync helpers: VFR detection, stream `start_time` compensation, frame-rate parsing — host-unit-tested; wired into `reframe.py`/`main.py` to fix VFR drift + YouTube audio desync. Ported from `kamilstanuch/Autocrop-vertical`, see `docs/autocrop-vertical-analysis.md`). `main` re-exports the reframe classes for back-compat. Verify pipeline changes with `docker compose run --rm -u root backend sh -lc "pip install -q pytest && pytest -m integration"`.
- `src/clippyme/domain/` — `compose.py`, `clip_endpoints.py`, `job_results.py`, `job_artifacts.py`, `job_worker.py`, `history_service.py`, `subtitles.py`, `smartcut.py`, `hooks.py`
- `src/clippyme/integrations/` — `social_publisher.py`, `auto_editor_updater.py`
- `src/clippyme/storage/` — `config_store.py`

Run with `uvicorn clippyme.api.app:app` and the pipeline CLI as `python -m clippyme.pipeline.main`. The descriptions below reference the **logical module names** (e.g. `compose.py`); their on-disk path is `src/clippyme/<subpkg>/<file>`.

## Architecture

- **Backend** (`clippyme.api.app`): Thin FastAPI layer — endpoint handlers + job queue + worker loop. Heavy logic lives in dedicated modules listed below. Config persistence, async job queue, batch processing.
- **Backend modules** (extracted from `app.py` during 8-round refactor):
  - `compose.py` — `compose_layers()` runs the **Subtitles → Smart Cut → Hook** pipeline for `/api/compose`. Owns intermediate-file cleanup. (Order matters: subtitles are burned onto the full-length base clip first so their absolute-timestamp timing is exact, *then* Smart Cut removes silences — the subs travel with the frames and never drift; Hook overlays last so it shows on every kept frame. Do **not** reorder to Smart-Cut-first or the subtitle drift bug returns — see the comment in `compose_layers`.)
  - `clip_endpoints.py` — `run_smart_cut()` (for `/api/smartcut`) and `restore_job_from_disk()` (for `/api/history/restore`).
  - `job_results.py` — `load_partial_result()` / `load_final_result()` (used by the worker loop) and `build_main_cmd()` (shared between `/api/process` and `/api/batch`).
  - `security.py` — `is_valid_job_id()`, trusted-origin checks.
  - `schemas.py` — Pydantic request models.
  - `job_artifacts.py` — `load_job_metadata()` / `save_job_metadata()` atomic helpers (tmp+replace) for `*_metadata.json`.
- **Processing pipeline** (`main.py`): Orchestrates download (yt-dlp) → transcription (**Deepgram Nova-3 cloud by default, faster-whisper as automatic fallback**, URL-hash cached) → scene detection (PySceneDetect) → viral moment detection (Google Gemini, returns `viral_score`/`viral_reason`) → smart 9:16 reframing (YOLOv8 + MediaPipe face tracking) → audio normalization → auto-zoom → cover frame selection.
- **Transcription** (`deepgram_transcribe.py` + `main.transcribe_video`): Provider is selected via the `TRANSCRIPTION_PROVIDER` env var (`deepgram` default, or `whisper`).
  - **Deepgram path** (`deepgram_transcribe.transcribe_with_deepgram`): Direct REST call to `POST https://api.deepgram.com/v1/listen` via `requests` — **no `deepgram-sdk` dependency**. Uses Nova-3 with `language=multi` (native EN+IT code-switching), `smart_format`, `punctuate`, `paragraphs`, `utterances`, `numerals`, `measurements`. Module is Nova-3-aware: drops `filler_words` (Nova-2 only, Nova-3 rejects it) and only sends `keyterm` entries on Nova-3. Retry/backoff with honoured `Retry-After` headers on 408/409/425/429/5xx. Module-level `requests.Session` for TLS keep-alive across batch jobs. File size guard, request_id logging, speedup-vs-realtime metric in the output. Returns the exact same dict shape as `transcribe_video` (prefers Deepgram `utterances` → falls back to sentence/12s word chunking).
  - **Whisper path**: Unchanged — faster-whisper with auto CUDA/CPU detection, `large-v3` / `medium` / `small` / `base` selected by VRAM or RAM.
  - **Fallback semantics**: If `TRANSCRIPTION_PROVIDER=deepgram` and the Deepgram call raises *any* exception (missing key, network, 4xx/5xx after retries, malformed response), `transcribe_video` silently falls back to Faster-Whisper with a warning log. The pipeline never breaks because of a misconfigured Deepgram key.
  - **Env vars**: `DEEPGRAM_API_KEY` (required for cloud path), `DEEPGRAM_MODEL` (default `nova-3`), `DEEPGRAM_LANGUAGE` (default `multi`), `DEEPGRAM_KEYTERMS` (comma-separated, Nova-3 only — boosts brand/jargon recognition), `DEEPGRAM_HTTP_TIMEOUT` (600s), `DEEPGRAM_MAX_RETRIES` (3), `DEEPGRAM_MAX_FILE_MB` (1900, below Deepgram's 2 GB hard limit).
  - **Why not the SDK**: `requests` is already a dep; `deepgram-sdk` would add ~5 MB and extra maintenance surface for ~300 LOC of wrapper. Direct REST gives us full control over the segment remapping (utterances → Whisper-shape) needed by the rest of the pipeline.
  - **Audio-only extraction (both paths)**: `transcribe_video` first strips the source to a compact mono-16 kHz FLAC via `diarization.extract_audio_for_asr` and hands *that* to the provider (Deepgram upload / Whisper decode) instead of the full mp4. Turns a 50-200 MB+ video into a few-MB file → far faster Deepgram upload, fewer mid-upload network errors on batch jobs, no risk of hitting the file-size cap on long videos, and skips Whisper's redundant video demux. FLAC is lossless at 16 kHz mono (exactly what ASR models consume) → zero accuracy cost. Temp file is cleaned in a `finally`. Opt out with `CLIPPYME_TRANSCRIBE_AUDIO_ONLY=false`; on extraction failure it transparently falls back to the source file.
  - **Model default**: `GEMINI_MODEL` defaults to **`gemini-3.5-flash`** (GA, 1M context, native thinking — stronger viral-judgment reasoning + cleaner strict-JSON than 2.5-flash at modest extra cost). `gemini-2.5-flash` remains the documented budget option; `gemini-3.1-pro-preview` / `gemini-2.5-pro` are the per-job "max quality" overrides. Allow-list prefixes (`gemini-2.5-`/`gemini-3` in `gemini_service.py`) already accept it.
- **Subtitles** (`subtitles.py`): ASS karaoke generation (`generate_ass_karaoke()`) with 6 viral presets + legacy SRT support. Burns via `ass` filter with bundled fonts. Supports `offset_y` for vertical positioning.
- **Smart Cut** (`smartcut.py`): Two-stage post-processing that removes silences and filler words.
  - **Stage 1** — `analyze_silences()` finds keep-segments from Whisper word timestamps (filler words in EN/IT/ES/FR/DE + gaps >0.8s). Renders via `_render_with_auto_editor()` which builds a hand-crafted **auto-editor v3 JSON timeline** and runs `auto-editor plan.json -o out.mp4` for a frame-accurate single-pass render. Falls back to legacy FFmpeg concat demuxer (`_render_with_ffmpeg()`) if the auto-editor binary isn't on PATH.
  - **Stage 2** — `_audio_polish_pass()` runs `auto-editor --edit audio:threshold=0.04 --margin 0.2sec` on the stage-1 output to catch silences the transcript missed (mumbles below ASR confidence, music gaps, ambient quiet). Skipped silently if auto-editor missing or if it doesn't reduce duration by ≥0.5s.
  - The legacy FFmpeg concat path is preserved as a safety net — never deleted, automatically used if auto-editor is unavailable. Public API `smart_cut(clip_path, transcript, clip_start, clip_end, language, drop_ranges=None)`. Stats now include `renderer` (`auto-editor-v3` or `ffmpeg-concat`) and optional `audio_polish_saved`.
  - **Manual trim** (`drop_ranges`, flycut-caption-ported — see `docs/flycut-caption-analysis.md`): caller-picked spans `[[start, end], …]` (clip-relative seconds) removed **on top of** the automatic filler/silence pass — the interactive transcript-editing path our auto-only Smart Cut lacked. Pure interval arithmetic in `smartcut.py` (`normalize_drop_ranges` tolerant HTTP coercion + `subtract_ranges` interval split), host-unit-tested (`tests/domain/test_smartcut_manual_trim.py`). A manual trim renders even for a small/single-segment cut (explicit intent); the auto path keeps its ≥1s guard. Drops are honoured even on transcripts with no word-level timing (manual spans are absolute). `POST /api/smartcut/{job}/{clip}` accepts an optional `{"drop_ranges": […]}` body; no body → pure auto Smart Cut (back-compat). `drop_ranges` also rides on `/api/compose` + the `compose_first` path of `/api/publish` (schema-bounded by `_validate_drop_ranges`), so a manual trim survives the final download/publish. **Frontend (shipped):** the Smart Cut section of `EditClipModal` (`redesign/captions.jsx`) lazy-loads `GET /api/transcript/{job}/{clip}` (per-clip segments via pure `clip_transcript_segments`), renders a tap-to-cut transcript checklist, and threads the dropped spans through `reprocessClip`/`exportClip`/`PublishModal`, persisted per-clip in `useClipStates.dropRanges`.
- **auto-editor binary lifecycle** (`auto_editor_updater.py`):
  - **NOT a pip dep**. The Dockerfile downloads the latest Nim binary (v30.x track) from `https://github.com/WyattBlue/auto-editor/releases/latest/download/auto-editor-linux-{x86_64,aarch64}` at build time and writes it to `/usr/local/bin/auto-editor`.
  - **Runtime auto-update**: `background_updater_loop()` is launched from the FastAPI lifespan as an asyncio task. On startup (and every 24h thereafter) it hits the GitHub Releases API, compares the local `--version` output with the latest tag, and atomically downloads the appropriate arch asset to `/app/data/bin/auto-editor` (writable by the non-root `appuser`).
  - **PATH ordering**: `/app/data/bin` is prepended to `PATH` in the Dockerfile, so the runtime-downloaded binary shadows the build-time install whenever a newer version exists.
  - **Failure modes**: GitHub unreachable / sanity check fails / arch unsupported → updater logs a warning and the existing binary keeps working. Smart Cut's FFmpeg fallback covers the worst case where no binary exists at all.
- **Hooks** (`hooks.py`): Text overlay generation with Pillow. Supports emoji via NotoColorEmoji font (lazy-downloaded). Configurable position, size, and `offset_y`. **Instagram-Stories-style text customization** (`create_hook_image(..., style=)`, defaults in `HOOK_STYLE_DEFAULTS`): a toggleable coloured **banner** behind the text (`bg_enabled` / `bg_color` / `bg_opacity` / `corner_radius`), independent **text colour** (`text_color`), a text **outline/stroke** (`outline_color` / `outline_width`, Pillow `stroke_width`), and a **font** choice (`font` — resolved from the bundled + uploaded `data/fonts/` dirs, shared with subtitles). With no `style` it reproduces the legacy white-banner / black-serif look (back-compat). Bannerless render auto-adds a soft drop shadow for legibility. Style keys ride on `hook_params` through `compose._apply_hook`; the frontend controls live in `redesign/hookStyle.jsx` (`HookStyleControls` + WYSIWYG `HookPreview`), shared by the Create hook drawer and the Edit modal.
- **Frontend** (`dashboard/`): React 18 + Vite 5 + Tailwind CSS v4 + shadcn/ui. Polls backend at 2s intervals for job status. Served on port 5175 (Docker) or 5173 (dev).
  - **The whole UI lives in `dashboard/src/redesign/`.** `main.jsx` renders `redesign/RedesignApp`. (The earlier `App.jsx` + `dashboard/src/components/*` tree was deleted once it became fully unreachable — git history has it if ever needed.) Edit the `redesign/` files for anything user-facing. The live UI has **no per-job model picker** — Gemini model is driven purely by the backend `GEMINI_MODEL` default.
  - **Custom hooks** (`dashboard/src/hooks/`): `useJobSubmission` (process+batch handlers), `useJobPolling` (status polling loop), `useHistory` (history list state), `useSessionPersistence` (localStorage round-trip), `useBackendStatus` (health check), `useClipStates` (per-clip disable/delete/published flags persisted in localStorage per jobId).
  - **Logo**: Custom SVG with multi-color gradient design (`public/logo.svg`)
  - **Color palette**: Dark foundation (#050507, #0f0f13, #16161d, #1e1e28) + brand colors (blue #0a81d9 primary, pink-purple-indigo gradient accent, teal #02c5bf, cyan #00d9ff)
  - **Design tokens**: the live system (`redesign/tokens.css` + `redesign/app.css`) is **dark · flat · editorial** — the viral gradient is a *signal only* (logo, primary CTA, score, hero word), no glow shadows, no decorative gradient borders, full-border (not left-stripe) selection states, Geist + Anton fonts. `src/index.css` is a separate legacy base layer (Tailwind preflight + global a11y/keyframes + a dormant amber/Fraunces `@theme` the redesign doesn't use); tokens.css/app.css load after it and win the cascade. Don't trust index.css's amber/Fraunces values — they don't reach the screen.
  - **Redesign components** (`dashboard/src/redesign/`): `RedesignApp.jsx` (top-level state + tab orchestration), `chrome.jsx` (TopNav + Hero), `create.jsx` (Single/Batch input + Clip Options), `processing.jsx` (`ProcessingView` — live logs, pipeline, partial clips, **pause/resume/stop & keep / discard** controls), `results.jsx` (`ResultsView` + `ClipCard` — video player, viral score, reframe badge, **Edit & reprocess** button, compose-download, publish, **remove**, select-mode batch actions), `publish.jsx` (single + batch publish), `captions.jsx` (`EditClipModal` — the unified per-clip editor: reframe mode + Smart Cut + Subtitles + Hook, all staged behind one **Apply & reprocess** button), `views.jsx` (Settings + History + ApiKey modal), `primitives.jsx` (Btn/Badge/Panel/etc.), `icon.jsx` (lucide map), `realApi.js` (backend client), `data.js` (presets/options/pipeline). Custom hooks shared from `dashboard/src/hooks/`.
- **Fonts** (`fonts/`): Bundled TTF fonts for subtitle and hook rendering (Anton, Bangers, Montserrat-Black/ExtraBold, Poppins-Black/Medium, NotoSerif-Bold). Served via `/fonts` static mount.

Config is persisted in `data/config.json` (git-ignored). Cookies in `data/cookies.txt`. API keys, Gemini model, and cookies are managed via the dashboard UI Settings tab, not env files.

## Post-hoc reframe switching

After a job completes, every clip can be flipped between the **three reframe modes** — **`auto`** (face tracking), **`object`** (element-aware crop), and **`disabled`** (4:3 + black bars) — without re-running the entire pipeline. To enable this the clip generator (`main.py`) now **preserves the 16:9 source slice per clip** on disk as `source_<clip_filename>.mp4` (never deleted at the end of the pipeline). The new endpoint `POST /api/reframe/{job_id}/{clip_index}` spawns `python -m clippyme.pipeline.main --reframe-only -i <source> -o <target> --reframe-mode <mode>` which:
1. Calls `process_video_to_vertical` with the new mode
2. Re-runs `apply_subtle_zoom` (unless `--no-zoom`), `normalize_audio`, `select_cover_frame`
3. Overwrites the same clip filename so all downstream references (subtitle/hook/compose) keep working

The endpoint updates metadata.json (`clip.video_url` + `clip.reframe_mode`) and the in-memory `jobs[job_id]['result']['clips'][i]`, and returns a cache-busted `new_video_url` (with a `?v=<timestamp>` query string appended) so the browser `<video>` element re-fetches instead of serving the stale reframed clip from the HTTP cache.

**Frontend**: the results `ClipCard` (`redesign/results.jsx`) shows the current reframe mode as a **read-only badge** (Crop=auto, Layers=object, Square=off) in the top-left corner. Switching modes happens in the per-clip **Edit & reprocess** modal (`captions.jsx` → `EditClipModal`), not via an instant click on the card — the old auto-on-every-click cycle button was removed because it kicked off a reframe subprocess on each tap. In the modal the three modes are a `Segmented` control; pressing **Apply & reprocess** calls `POST /api/reframe` (only when the mode actually changed), then composes any active layers. State is persisted per-clip via `useClipStates.reframeMode` + `previewUrl`/`reframeBust` cache-busters (`realApi.clipPreviewSrc` prefers a composed `previewUrl`, else the reframed/raw clip). The Create tab's **Clip Options** exposes the same three modes as a `Segmented` control (Auto / Object / Off → `opts.reframeMode`, persisted in preselections; the old boolean `opts.reframe` is read only as a back-compat fallback in `optsToPreselections`). Legacy jobs (created before the source-slice feature landed and therefore missing the `source_*.mp4` slice) return HTTP 409 and the frontend shows a toast explaining the clip must be reprocessed.

**Why subprocess, not in-process import**: importing `main.py` into the FastAPI worker would eagerly load YOLO + MediaPipe models. We want the reframe endpoint to be latency-tolerant but not pay that startup cost on every API boot. Spawning `main.py --reframe-only` reuses the exact same code path the initial run used (same reframe algorithm, same zoom/normalize/cover) with zero code duplication.

## Toggle System (Compose-on-Download)

The post-processing workflow uses independent toggles per clip:

- **Smart Cut** — on/off, no additional params needed
- **Hook** — on/off + text (auto-filled from Gemini suggestion), position, size, offset_y
- **Subtitles** — on/off + preset, mode (karaoke/classic), font, colors, offset_y

**Behavior**: Toggles are UI-only state. No processing happens on toggle click. At download time, `POST /api/compose/{job_id}/{clip_index}` receives active toggles + params and composes the final video in a single pipeline: **Subtitles → Smart Cut → Hook** (this order avoids subtitle drift — see `compose_layers`).

**Pre-selections**: Users can pre-configure toggle states and params before processing (in MediaInput's "Clip Options" panel). These defaults are applied to all generated clips. Each clip can be overridden individually.

**Subtitle pre-selection mode coupling**: The pre-selection panel shows different controls depending on `mode`:
- **Karaoke**: visual 2×3 grid of the 6 `SUBTITLE_PRESETS` (Classic, Hormozi, Neon, MrBeast, Minimal, Fire) — each rendered with its actual font/color/shadow style.
- **Classic**: font dropdown (Verdana, Montserrat-Black, Anton, Bangers, Poppins-Black/Medium) + font color swatches + position (top/middle/bottom). These params are propagated via `preselections.subtitles.{font, font_color, position}` and seeded into each `ResultCard`'s `subtitleParams` so the compose endpoint receives them per-clip without manual reconfiguration.

**Persistence**: pre-selections (reframe mode, smart-cut toggle, subtitle mode+preset+font+colors+position, hook text/size/position, ASR language) are persisted in `localStorage` under `clippyme_preselections_v3`. Per-clip toggle overrides (smartcut/hook/subtitles + their params) are persisted per jobId via `useClipStates` under `clippyme_clip_states_{jobId}` — so user choices survive page reloads without a backend round-trip.

## Frontend Design & Components

**Design Philosophy**: Premium, minimal aesthetic with modern glass morphism effects, responsive mobile-first layout, smooth gradient animations.

**Key UI features** (implemented in `dashboard/src/redesign/` — the bullets below describe behaviour; the old `components/` filenames they reference were deleted, but the features live on in the redesign files mapped above):
- **TopNav** (`chrome.jsx`): Slim header with ClippyMe logo/text, step-based tabs (Create/History/Settings), status indicator.
- **MediaInput**: **Two tabs** — `Single` (with internal URL/Upload toggle, paste button, drag-drop zone) and `Batch` (textarea for URLs + multi-file upload zone with removable list, total counter URLs+files / 20). AI instructions collapsible. **Clip Options** collapsible panel: reframe mode (auto/disabled), Smart Cut toggle, Subtitles toggle+config (mode-aware: karaoke shows visual preset grid, classic shows font/color/position), Hook toggle+config (position, size — defaults to **S**). Cookie warning banner when cookies not configured.
- **ResultCard**: 9:16 aspect ratio video player, viral score badge (color-coded: green 80+, yellow 50-79, orange <50 with tooltip), duration. **Toggle buttons** (Smart Cut, Hook, Subtitles) with pink active state + gear icon for config. Compose-on-download: clicking Download calls `/api/compose` with active toggles, or downloads original clip if no toggles active. YouTube title/TikTok caption fields.
- **SubtitleModal / HookModal**: Two-column layout (settings left, live preview right; stacks vertically on mobile). Modal backdrop blur, gradient apply buttons, color pickers, preset dropdowns. **Vertical offset slider** (-50% to +50%). Font preview loads actual TTFs via FontFace API.
- **KeyInput** (Settings): Gemini API key, HuggingFace token, **Deepgram API key**, Gemini model selector, **Transcription provider selector** (Deepgram Nova-3 / Faster-Whisper). Shows an amber warning if Deepgram is selected without a saved key (pipeline falls back to Whisper). **Cookie upload** section: file input (.txt), save/remove buttons, configured status indicator.
- **ProcessingAnimation**: Source video container with pulsing gradient border, status badge with animated dots, model/hardware info badges, synced playback indicator.
- **Landing**: Hero with gradient logo, "ClippyMe" text (pink→purple→blue), feature grid (6 items), "How it works" (3 steps), premium CTAs.

**Tailwind v4 Setup**:
- Uses `@tailwindcss/vite` Vite plugin (NOT PostCSS — `postcss.config.js` only has autoprefixer)
- All brand tokens defined in `@theme {}` block in `index.css` (no separate config needed for most things)
- `tailwind.config.js` retained only for shadcn CSS variable color mappings (`foreground`, `card`, `popover`, etc.)
- Custom colors: dark surfaces, brand gradients, full shadcn token set (`primary-foreground`, `secondary`, `input`, etc.)
- Custom animations: `gradient-shift` (8s cycle), `float`, `shimmer`, `pulseRing`, `scanLine`
- Custom shadows: `glow-primary`, `glow-accent`, `glow-pink`, `elevated`, `glass`
- `@` path alias configured in `vite.config.js` and `jsconfig.json` → resolves to `dashboard/src/`
- **Vite dev proxy** (`vite.config.js`): `/api`, `/videos`, `/thumbnails`, **`/fonts`** → all proxied to `http://backend:8000`. (`server.watch.usePolling` is on — Windows/macOS Docker bind mounts don't deliver inotify, so without polling Vite never sees host edits and HMR silently dies.) The `/fonts` proxy is **mandatory** for the SubtitleModal font preview to work — without it, `FontFace` requests 404 and the preview falls back silently to the system font (this was a real bug).

**CSS Features** (`dashboard/src/index.css`):
- Tailwind v4 syntax: `@import "tailwindcss"` + `@import "tw-animate-css"`
- `.glass-panel`: backdrop-blur with subtle gradient, used on modals and cards
- `.gradient-border`: pink-to-blue gradient pseudo-element border
- `.btn-primary`, `.btn-ghost`, `.btn-secondary`, `.btn-modern`: button variant classes
- `.input-field`: base input styling with focus ring
- Refined scrollbar (6px, transparent track, rounded thumb) — applied globally, no class needed
- Body texture: subtle noise/grain via `::after` pseudo-element
- `.bg-ambient`: layered radial gradients in brand colors
- `prefers-reduced-motion` media query disables all animations for accessibility
- `:focus-visible` ring for keyboard navigation accessibility

**App State & Flow** (`dashboard/src/App.jsx`):
- Default export is `AppWithProviders` which wraps `App` in `TooltipProvider` (Radix requirement)
- `<Toaster position="bottom-right" richColors closeButton />` rendered inside App for sonner toasts
- Step-based workflow: idle (input) → processing (logs) → complete (results/history)
- Session persistence: `localStorage` for credentials (`gemini_key`), model (`clippyme_model`), history (`clippyme_history`), session (`clippyme_session`)
- Job polling: 2-second interval via `setInterval`, cleared on unmount
- Batch processing: `batchId` and `batchJobs` state for multi-URL submissions
- `preselections` state: stores user's pre-selected toggle options, passed to ResultCards
- `cookiesConfigured` state: fetched on mount, passed to MediaInput for warning display
- Error toasts via sonner replace inline error banners
- Confetti animation (40 particles) triggered on job completion
- Auto-apply: when smartcut pre-selected and job completes, fires `/api/smartcut` for each clip

## Commands

### Run with Docker (primary method)
```
docker compose up --build
```
Backend: http://localhost:8000 | Frontend: http://localhost:5175

> **First run or after package changes**: use `docker compose down -v && docker compose up --build` to clear the stale `/app/node_modules` anonymous volume.

### Local development
```
# Backend
pip install -r requirements.txt
pip install -e .
python -m uvicorn clippyme.api.app:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd dashboard && npm install && npm run dev
```

### Frontend build
```
cd dashboard && npm run build
```

### UI primitives
The redesign uses hand-rolled primitives in `dashboard/src/redesign/primitives.jsx` (Btn/Badge/Panel/etc.) + the lucide icon map in `icon.jsx` — **not** the shadcn CLI. Add new primitives there, matching the existing Tailwind v4 token classes.

## Key Patterns

- **Job queue**: In-memory async queue in `app.py`. Jobs submitted via `POST /api/process`, polled via `GET /api/status/{job_id}`.
- **Job control (pause / resume / stop / cancel)** — `clippyme.domain.job_control` owns the state machine. Statuses: `queued → processing ⇄ paused → {completed, failed, cancelled, stopped}`. Pure transition guards (`can_pause/can_resume/can_stop/can_cancel/should_skip_dispatch`) are host-unit-tested; `suspend_tree`/`resume_tree` use **psutil** (already a dep) to signal the whole subprocess tree (children-first suspend, parent-first resume) — cross-platform (SIGSTOP/SIGCONT on Linux, SuspendThread on Windows), unlike `os.kill(SIGSTOP)`. `/api/pause`+`/api/resume` suspend/resume; `/api/stop` is a **graceful** stop that kills the subprocess but promotes the partial result to final (`run_job`'s post-loop sees status `stopped` and keeps the clips); `/api/cancel` is the **hard discard** (kill + `rmtree`). The pipeline subprocess has no IPC, so a kill is the only mid-run stop — there is no clean inter-clip boundary. `run_job` has a pre-dispatch guard (`should_skip_dispatch`) so a job cancelled/stopped while still `queued` never launches. Frontend controls live in `redesign/processing.jsx` (`ProcessingView`: Pause/Resume + **Stop & keep** + **Discard**), wired through `RedesignApp.jsx`; `useJobPolling` treats backend `stopped` as terminal-with-clips and routes to the editable viewer.
- **Live editable clips during processing**: the backend already streams partial clips (`load_partial_result` with `only_ready=True`). The Create tab now renders the **full `ResultsGrid`** (with `clipStates`/`onUpdateClipState`) as soon as `results.clips.length > 0` while `status` is `processing`/`paused`, so finished clips are viewable + editable + publishable while later ones still render. `ProcessingView` is shown only in the no-clips-yet phase.
- **Per-job LLM model override**: the Gemini model for viral detection is global (Settings → `GEMINI_MODEL`) but can be overridden **per job** via `ProcessRequest.model`/`BatchRequest.model` → `build_main_cmd(model=...)` → `--model` CLI arg → `main.py` sets `os.environ["GEMINI_MODEL"]` before `get_viral_clips` (mirrors the `--language` override). Validated at the boundary by `job_results.GEMINI_MODEL_RE` (`^gemini-[A-Za-z0-9.\-]{1,64}$` — blocks argv injection; allows future `gemini-3*`). Frontend: a quick-picker in MediaInput's Clip Options (`preselections.model`) + the live-discovery dropdown in Settings (`/api/config/models`, allow-list prefixes `gemini-2.5-`/`gemini-3` in `gemini_service.py`). Unknown models fall through to a `$0.00` "Pricing not available" cost note (`main.py:MODEL_PRICING`).
- **Batch processing**: `POST /api/batch` accepts up to 20 URLs, creates one job per URL, and returns the list of `job_id`s. The frontend polls each job individually via `GET /api/status/{job_id}` and aggregates progress client-side. Supports `reframe_mode` parameter.
- **Mixed batch (URLs + files)**: The frontend `useJobSubmission.handleBatchProcess` supports both. URLs are submitted in one shot to `/api/batch`; each file is submitted individually to `/api/process`. The hook then unifies polling across all returned `job_id`s using `/api/status/{job_id}`, aggregating progress until every job reaches a terminal state. No backend change is needed for mixed batches.
- **Compose endpoint**: `POST /api/compose/{job_id}/{clip_index}` accepts `toggles` (smartcut/hook/subtitles/**logo** booleans), `hook_params`, `subtitle_params`, **`logo_params`**. Composes layers in order: **Subtitles → Smart Cut → Hook → Logo** (subtitle-drift-safe; logo absolutely last so the brand mark sits on top of every other layer). Returns `composed_url`. Cleans up intermediate files.
- **Brand assets** (client deliverables — e.g. ASCENSORE): a persistent **logo overlay** + **custom subtitle fonts**, both managed in Settings → *Brand assets*.
  - **Logo** (`domain/logo.py:add_logo_to_video`): ffmpeg `overlay` of an uploaded transparent PNG (`data/logo.png`, set via `POST /api/config/logo`). Placement is a position preset (7 anchors: corners + edge-centers + center) × size preset (`S/M/L` → 0.12/0.18/0.26 of frame width) × opacity. Geometry helper `logo_overlay_xy` is pure (host-tested, no ffmpeg). The compose **logo** layer reads `LOGO_PATH` and skips silently if no logo is uploaded.
  - **Custom fonts** (`subtitles.py:list_available_fonts` / `effective_fonts_dir`): user TTF/OTF uploads (`POST /api/config/fonts`) land in the writable `data/fonts/` volume; `effective_fonts_dir()` seeds it with copies of the bundled `fonts/` faces so a single `fontsdir` serves both (libass's `ass`/`subtitles` filter takes only one dir). Both burn branches pass `fontsdir`, so an uploaded face (e.g. a licensed **Stratos**) resolves at burn time. Upload validates the sfnt magic + the strict `_FONT_NAME_RE` (the stem becomes the libass font name injected into the ASS style). Frontend font dropdowns live-merge bundled + uploaded via `hooks/useFontList.js`.
  - **Subtitle colours**: `SUB_COLORS` (classic-mode `font_color` swatches) leads with the ASCENSORE brand set — white `#FFFFFF` (judges), yellow `#FDE700` / purple `#581BBA` (contestants).
- **Transcription cache**: `data/cache/` stores transcripts keyed by SHA256(url)[:16]. TTL 7 days, pruned by the background cleanup task.
- **Hardware auto-detection**: CUDA/CPU fallback at runtime for faster-whisper and YOLOv8. No manual config needed.
- **yt-dlp uses Deno** as JS runtime for YouTube bot-detection bypass.
- **Cookie management**: Uploaded once in Settings, persisted at `data/cookies.txt`. Used automatically for all downloads. Fallback chain: `data/cookies.txt` → `YOUTUBE_COOKIES` env var → none.
- **Security**: `job_id` validated with strict regex to prevent path traversal. Config endpoints require trusted origin or private network client. Containers run as non-root users. A secret-scan **pre-commit hook** lives at `.githooks/pre-commit` (blocks API keys, HF/OpenAI tokens, Deepgram tokens, Netscape cookie files, and the secret files `data/cookies.txt` / `data/config.json` / `.env`). Enable it once per clone with `git config core.hooksPath .githooks`; bypass a confirmed false positive with `git commit --no-verify`.
- **Temp files**: Uploads go to `uploads/`, outputs to `output/`. Both are transient and git-ignored.
- **Font serving**: `/fonts` static mount serves bundled TTFs to frontend for SubtitleModal preview (loaded via FontFace API).

## main.py CLI Args

```
python -m clippyme.pipeline.main <url_or_path> [options]
  --instructions "focus on hooks"        # Directive injected into Gemini prompt
  --no-zoom                              # Disable Ken Burns auto-zoom (1.0→1.05x)
  --reframe-mode auto|object|disabled    # auto=face tracking · object=element-aware crop · disabled=4:3 crop w/ black bars
  --model gemini-2.5-pro                 # Override the Gemini model for THIS job (else GEMINI_MODEL)
```

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/process` | Process single video (accepts `reframe_mode`) |
| POST | `/api/batch` | Submit multiple URLs (accepts `reframe_mode`) |
| GET | `/api/status/{job_id}` | Poll job progress |
| POST | `/api/compose/{job_id}/{clip_index}` | Compose final video from active toggles |
| POST | `/api/smartcut/{job_id}/{clip_index}` | Generate smart-cut version of a clip (optional `drop_ranges` body for manual trim) |
| GET | `/api/transcript/{job_id}/{clip_index}` | Per-clip transcript segments (clip-relative) for the manual-trim UI |
| POST | `/api/reframe/{job_id}/{clip_index}` | Switch a clip between `auto` / `object` / `disabled` reframe mode (requires preserved source slice) |
| POST | `/api/config/cookies` | Upload persistent cookies file |
| GET | `/api/config/cookies/status` | Check if cookies are configured |
| DELETE | `/api/config/cookies` | Remove cookies file |
| POST | `/api/config/logo` | Upload brand logo PNG (compose logo overlay) |
| GET | `/api/config/logo/status` | Check if a logo is configured |
| DELETE | `/api/config/logo` | Remove the brand logo |
| GET | `/api/config/fonts` | List available subtitle fonts (bundled + uploaded) |
| POST | `/api/config/fonts` | Upload a custom .ttf/.otf font (e.g. Stratos) |
| DELETE | `/api/config/fonts/{name}` | Remove an uploaded font |
| POST | `/api/cancel/{job_id}` | Cancel a running job (hard kill **+ delete all output**) |
| POST | `/api/pause/{job_id}` | Suspend the job's process tree → status `paused` |
| POST | `/api/resume/{job_id}` | Resume a paused job → status `processing` |
| POST | `/api/stop/{job_id}` | Graceful stop: kill subprocess but **keep finished clips** → status `stopped` |
| GET | `/api/history` | List past jobs |
| POST | `/api/history/{job_id}/restore` | Restore job to memory |
| DELETE | `/api/history/{job_id}` | Delete job from disk |

## Subtitle Presets

Defined in `subtitles.py:SUBTITLE_PRESETS`. Six built-in presets:
`classic_white`, `hormozi_bold`, `neon_glow`, `mrbeast_box`, `minimal_clean`, `fire_impact`.

When using ASS karaoke, the `ass` FFmpeg filter is used with `fontsdir` pointing to the `fonts/` directory. For SRT the `subtitles` filter is used with adjustable `MarginV` (default 350, modified by `offset_y`).

**Safe zone defaults**: MarginL/R = **110 px** (≈10% of the 1080px vertical frame → TikTok/Reels safe zone so long captions don't get cropped). Preset fontsize defaults have been reduced twice: first pass (`80→62`, `85→66`, `75→58`, `70→54`) and then a **−35% second pass** for cleaner reading on mobile vertical frames → current values: `classic_white=40`, `hormozi_bold=43`, `neon_glow=40`, `mrbeast_box=38`, `minimal_clean=35`, `fire_impact=43`.

## Faithful modal preview scaling

`SubtitleModal.jsx` and `HookModal.jsx` render **pixel-faithful** previews of the burned-in output. Shared spec in `dashboard/src/lib/subtitlePresets.js` mirrors `subtitles.py:SUBTITLE_PRESETS` 1:1 and exports `scaleFontToPreview(backendFontsize, renderedHeightPx)` (formula: `backendFontsize * renderedHeightPx / 1920`) + `outlineToTextShadow()` (8-way CSS shadow approximating libass outline). Modals measure `<video>` `clientHeight` via `ResizeObserver` and feed it through the scaler. HookModal replicates `hooks.py` formula `video_width * 0.9 * 0.05 * font_scale` with `S=0.8 / M=1.0 / L=1.3`.

**Hard rule:** if you change a preset's fontsize on the backend, update `subtitlePresets.js` in the same commit.

## Unified vertical position slider

`HookModal.jsx` and `SubtitleModal.jsx` expose a **single `-50 → +50` slider** for vertical placement — no more separate top/center/bottom radio buttons. The slider value is the absolute Y position in percent (−50 = top, 0 = center, +50 = bottom) and the modal preview uses `top: {50 + offsetY}%` so what-you-see matches what-you-get.

Under the hood the frontend always sends `position='center'` to the backend, which is aliased to `'middle'` in both `subtitles.py` and `hooks.py`. This keeps the existing ASS/ffmpeg pipeline untouched while giving the user a single continuous control.

The apply buttons are labelled **"Apply Hook"** / **"Apply Karaoke Subtitles"** / **"Apply Classic Subtitles"** (not "Add" — the toggle switch outside already decides whether the layer is rendered at download time).

## Clip lifecycle & batch publish

- **`useClipStates(jobId)`** (`dashboard/src/hooks/useClipStates.js`) — per-clip state keyed by index, persisted in localStorage under `clippyme_clip_states_{jobId}`. Shape: `{ disabled, deleted, publishedAt }`. Survives page reloads without a backend round-trip.
- **`ResultCard.jsx`** top-left action toolbar: Eye/Eye-off (disable → opacity 50%, excluded from batch publish), Trash (with confirm → hides from grid, file stays on disk). Top-right: green **"Published"** pill when `publishedAt` is set.
- **`BatchPublishModal.jsx`** — launched from the `Publish all (N)` button in `ResultsGrid`. Iterates every clip where `!disabled && !deleted && !publishedAt` and calls `POST /api/publish/{jobId}/{index}` sequentially with live per-clip status (pending / ok / error / **skipped**). Supports `schedule_mode='auto'` (SmartScheduler picks a different slot per clip) and `'now'` (all immediate). Each successful publish marks the clip via `onUpdateClipState(index, { publishedAt: Date.now() })`.
  - **Auto-slot start date**: when `schedule_mode='auto'` the modal shows a date picker defaulting to today (local timezone, YYYY-MM-DD). The value is forwarded to the backend as `start_date` on every `/api/publish/...` call. `social_publisher.publish_clip` parses it and hands it to `SmartScheduler.find_slot` as the `target_day` override (clamped to `max(requested, now.date())` so past dates never slip through).
  - **One-clip-per-day spacing** (default ON): replicates the original `tmp/programma_shorts.py` behavior. When enabled, the frontend increments `start_date` by `+batchIndex` days inside the loop (`clip #0 → startDate`, `clip #1 → startDate + 1 day`, …) so each clip lands on its **own day**, bypassing Zernio's per-platform 5/day posting limit. The UI shows a live date-range preview (`2026-04-08 → 2026-04-16` for a 9-clip batch). Can be toggled off to compress all clips into a single day — only useful for very small batches (≤5) that fit under the daily limit.
  - **Per-platform daily-limit handling**: when Zernio returns HTTP 429 with a "Daily limit reached" error (e.g. YouTube's 5/5 daily posts cap), the modal parses the offending platform from the error body (regex on `"platform":"..."` — the backend passes the Zernio body verbatim through `ZernioError`), disables that platform in the local `activePlatforms` map for the rest of the batch, and continues publishing the remaining clips to the other platforms. If all selected platforms get exhausted, the remaining clips are marked `skipped` (not `error`) and left untouched so the user can republish them tomorrow. A toast explains exactly which platform was disabled and the final summary reports `ok / failed / skipped` counts plus the exhausted platform list.
- **`PublishModal.jsx`** (single-clip path) now accepts an `onPublished` callback so the parent `ResultCard` can flip the clip's `publishedAt` flag without duplicating state.

## Reframing Modes

There are **two layers** of "mode". The **user-facing `--reframe-mode`** (`auto` | `object` | `disabled`) selects the whole-clip policy; within `auto`, **per-scene strategies** are then chosen automatically.

**User-facing `--reframe-mode`** (CLI / `ProcessRequest.reframe_mode` / per-clip post-hoc `/api/reframe`):
- **`auto`** (default) — face tracking; runs `analyze_scenes_strategy()` to pick a per-scene strategy (below). The comfort 2-pass / global-smooth path applies here only.
- **`object`** — element-aware crop everywhere: every scene is forced to the `OBJECT` strategy → `create_general_frame(force_object_weights=True)`, which crops on the weighted-object centroid → Sobel saliency → blurred letterbox bands (fallback). Skips face tracking and scene analysis; the curated `_DEFAULT_OBJECT_WEIGHTS` are forced on regardless of the `REFRAME_OBJECT_WEIGHTS` env flag. This is the FrameShift-style "crop to the elements present, fall back to bands" mode. Streaming loop only (no global-smooth — that's a face-pan smoother).
- **`disabled`** — overrides all scenes → 4:3 center crop + black bars (`create_disabled_reframe`).

**Per-scene strategies** (only used inside `auto`; `analyze_scenes_strategy()` samples 7 frames per scene):
- `TRACK`: a **single, near-static** subject → locked crop on the face (static-framing policy below). Pass-1 still records `SpeakerTracker` + `SmoothedCameraman` targets; the static policy then collapses them to one fixed viewpoint.
- `WIDE`: **2+ faces** in the scene **OR a single subject that moves too far to hold without panning** (primary-face centroid travel > `REFRAME_MOTION_WIDE_THRESH`, default `0.12` of the frame) → a **locked, zoomed-out** crop (zoom forced to 1.0) centred between the faces / on the subject's average position. Shows everyone with zero camera motion.
- `GENERAL`: no faces → `create_general_frame()` (letterbox, or content-aware crop if the `REFRAME_OBJECT_WEIGHTS` / `REFRAME_SALIENT_GENERAL` env flags are set)

**AUTO static-framing policy (`REFRAME_STATIC_AUTO`, DEFAULT ON)**: the headline rule — *within a scene the camera never moves*. Built on the comfort-mode global-smooth 2-pass: pass 1 records the raw per-frame target, then `reframe_ops.collapse_scene_targets` (pure-math, host-tested) collapses **each scene to a single `(cx, cy, zoom)`** so every frame of a shot renders from one fixed crop — zero pan, zero mid-shot zoom breathing. TRACK locks on the scene's median face centre with zoom capped at `1.35` (framed but never aggressively pushed in); WIDE locks zoomed-out (`wide_zoom=1.0`) on the median centre. A single *moving* subject is deliberately demoted TRACK→WIDE rather than chased, because chasing it would create the very motion the policy removes (`reframe_ops.centroid_span` measures the travel; threshold `REFRAME_MOTION_WIDE_THRESH`). The lock point snaps to exact frame centre within `REFRAME_SNAP_CENTER` (0.10). Set `REFRAME_STATIC_AUTO=0` to fall back to the per-frame Savitzky-Golay eased smoother (legacy moving-but-eased camera — `build_smoothed_trajectory`). Guarded by `tests/pipeline/test_reframe_ops.py` (`centroid_span` + `collapse_scene_targets`).

**`SpeakerTracker`**: mouth-aspect-ratio (MAR) variance from MediaPipe FaceMesh (landmarks 13/14/78/308, defined as `_MOUTH_TOP/_BOTTOM/_LEFT/_RIGHT` module constants **in `reframe.py`**), 1s sliding window per speaker. Score = `0.3 * face_size_norm + 1.0 * MAR_variance`. 3× sticky bonus on the active speaker, switches require `cooldown_frames=45`. **Regression note:** these constants were once defined only in `main.py` while `compute_mouth_aspect_ratio` was extracted to `reframe.py`, so the MAR call raised `NameError` every frame — silently swallowed by the corrupt-frame guard, disabling active-speaker selection and duplicating ~37% of frames. Guarded by `tests/pipeline/test_reframe_mar.py` (asserts no undefined globals in the function) and surfaced by `REFRAME_DEBUG_EXC=1` (prints the first 5 swallowed per-frame tracebacks to stderr).

**Dead-band (`REFRAME_DEADZONE_X` / `REFRAME_DEADZONE_Y`)**: jitter-killing safe zone as a fraction of the max crop dimension before the camera reacts. Defaults `X=0.05` / `Y=0.08` (were `0.20`/`0.15`). A measured fitness sweep (`tmp/reframe_eval/`: re-detect faces in the *output*, score centering + jerk + coverage) found the old `X=0.20` let a talking head drift 20% off-centre; tightening to `0.05`/`0.08` cut centering error ~30% with *lower* jerk (tighter tracking, not jitter). Raise to loosen on shaky sources.

**`SmoothedCameraman`**: adaptive smoothing (`SLOW=0.08`, `FAST=0.30` for jumps >60% of crop_width), X+Y axis tracking, **continuous** 1.0–1.6× zoom (`reframe_ops.zoom_for_face_height` — face targets ~40% of crop height; replaced the old 4-bucket ladder that snapped at bucket edges), **asymmetric zoom easing** (`reframe_ops.asymmetric_zoom_step` — `ZOOM_RATE_OUT=0.12` fast pull-back so a growing face is never left chopped, `ZOOM_RATE_IN=0.05` slow cinematic push-in; ported from gauravzazz/smart-reframe), YOLO person bbox fallback aiming at upper 15% (head zone) when no face detected. `DetectionSmoother` rolling average (window=5) before MAR.

**Lost-subject recovery (always on)**: when no fresh target arrives for `REFRAME_LOST_HOLD` frames (default 90 ≈ 3 s) in a TRACK/WIDE scene, the camera eases its target back toward the source center at `REFRAME_LOST_DRIFT`/frame (default 0.05) and gently zooms out, instead of freezing on empty space.

**Pure decision math lives in `reframe_ops.py`** (no cv2 import → host-unit-tested): `iou`/`associate_subject` (IoU identity association), `OneEuroFilter` (1€ adaptive smoother), `drift_to_center`, `salient_crop_center`, `zoom_for_face_height` + `asymmetric_zoom_step` (continuous + asymmetric zoom control), `savgol_1d` + `smooth_and_clamp` + `build_smoothed_trajectory` (two-stage global-trajectory smoothing), `kalman_rts_smooth` + `solve_camera_path_l2` (alternative global pan-path smoothers — forward-backward Kalman RTS + L2 convex optimiser, ported from mfahsold/montage-ai). `SmoothedCameraman` is thin cv2 glue that calls in. Add new reframe logic here, not in `main.py`, so it stays testable on the host.

**Optional smoothers** (`REFRAME_SMOOTHER`): blank = default two-speed EMA; `euro` = 1€ filter (`REFRAME_EURO_MINCUTOFF` default 0.014 = smoothness floor; `REFRAME_EURO_BETA` default 0.0008 = speed responsiveness); `spring` = momentum / damped-spring (`reframe_ops.advance_value_with_velocity`, `REFRAME_SPRING_RESPONSE` default 0.18, `REFRAME_SPRING_DAMPING` default 0.82 — carries velocity for operator-like accel/decel; ported from KazKozDev/auto-vertical-reframe). **Hard pan-rate cap** `REFRAME_MAX_STEP_PX` (px, 0 = off) clamps the per-frame center move for *every* smoother via `reframe_ops.limit_step` (also caps the spring's max velocity). **A/B procedure**: process the same clip with and without the flag (env vars are in `docker-compose.yml`), compare camera feel — lower `MINCUTOFF` = smoother/laggier at rest, higher `BETA` = snappier on fast speaker switches. `salient_crop_center` (saliency crop) is **wired as opt-in**: `REFRAME_SALIENT_GENERAL=1` content-aware-crops faceless (GENERAL) scenes around the highest image-gradient column band (Sobel saliency, base cv2 — no opencv-contrib) instead of letterboxing them; default-off keeps the letterbox path byte-identical, and the helper falls back to letterbox on any failure (`reframe._salient_general_crop`, integration-tested). **Weighted-object follow** (`REFRAME_OBJECT_WEIGHTS`) is a second opt-in GENERAL crop that takes precedence over `SALIENT_GENERAL`: in faceless scenes it **reuses the existing YOLO forward pass** (no 2nd network — the person-fallback already runs YOLO; only the class filter differs) to weight every COCO detection by `class_weight·area·conf` and crops a 9:16 window on the weighted centroid (`reframe_ops.weighted_interest_center`, pure-math host-tested), so a B-roll product/dog/car stays framed instead of parked behind letterbox bars. `1`/`true`/`default` → curated COCO defaults (`reframe._DEFAULT_OBJECT_WEIGHTS`: animals 2.5–3, vehicles 1.8–2, held objects 1.3–1.8); `dog:3,car:2,bottle:1.5` → custom weights. **Person is excluded** (people are framed by the face/person tracker upstream), so this never competes with talking-head framing — which is precisely why it's a net-only improvement: it only fires where the old path would letterbox. Falls through to salient/letterbox on no-object/failure (`reframe._weighted_object_general_crop`, integration-tested). This is the no-con realization of FrameShift's `calculate_weighted_interest_region` idea — the 2nd-YOLO/rank_subject/talking-head cons all dissolve once it's scoped to the faceless fallback and piggybacks the existing inference. The remaining `associate_subject` (IoU identity — largely redundant with `SpeakerTracker`'s existing center-distance identity + hysteresis), `rank_subject` (linear subject-importance fusion — pays off only once mask/pose/track signals exist, which they don't yet), and `split_screen_slots` (multi-face split-screen geometry — needs a net-new multi-face render mode + per-face tracking) stay implemented + tested but unwired, gated on infrastructure that doesn't exist yet — see the reframe design spec + `docs/auto-vertical-reframe-analysis.md` / `docs/smart-video-reframe-analysis.md`.

**Optional global trajectory smoothing (opt-in 2-pass)**: set `REFRAME_GLOBAL_SMOOTH=1` to switch the render to a two-stage track-then-render pass (`reframe._render_global_smooth`). Pass 1 records the raw per-frame `(cx, cy, zoom)` camera target; `build_smoothed_trajectory` Savitzky-Golay-smooths it **per scene segment** (never across a cut); pass 2 renders from the smoothed path via `SmoothedCameraman.crop_box_at`. This is a cheap, dependency-free analogue of gauravzazz/smart-reframe's offline Viterbi `PathSolver`. Default-off keeps the proven single-pass streaming path byte-identical; the opt-in path costs a second video decode. See `docs/smart-reframe-analysis.md` for the full comparison. A/B the same way as the 1€ smoother (output must be viewed). The pan-path smoother is selectable via `REFRAME_GLOBAL_METHOD` (`savgol` default | `kalman` = forward-backward Kalman RTS, extrapolates through detection gaps | `l2` = L2 convex optimiser minimising data+velocity+acceleration with optional keyframe constraints; both ported from mfahsold/montage-ai — see `docs/montage-ai-analysis.md`). Zoom always uses savgol. Default `savgol` is byte-identical to before.

**AutoFlip-style stationary lock (opt-in, global-smooth only)**: `REFRAME_STATIONARY_THRESH` (default `0.0` = off) ports Google AutoFlip's `motion_stabilization_threshold_percent`. In `build_smoothed_trajectory`, after per-scene smoothing, if a scene's camera target spans less than this fraction of the frame on **both** axes (`reframe_ops.stationary_lock`, host-tested), the whole scene is pinned to the segment's median target — a locked tripod instead of micro-tracking detector jitter. `REFRAME_SNAP_CENTER` (default `0.10`) snaps that lock point to exact frame centre when it lands within this fraction of centre. At threshold `0.0` the path is byte-identical. Measured on a real clip (`tmp/reframe_eval`): global-smooth (savgol) already cut centering error to cx≈0.078 (vs the streaming default's ≈0.13) at higher output face-coverage; stationary `0.15` further trims jerk on near-static scenes. The default render stays single-pass streaming (one decode); enable `REFRAME_GLOBAL_SMOOTH=1` (+ optional stationary) for the highest-quality framing at the cost of a second decode. See `docs/reframe-improvements-research.md`.

**Comfort mode (anti-nausea, DEFAULT ON — `REFRAME_COMFORT`)**: research (Google AutoFlip + cybersickness literature, see the reframe research agent findings in `docs/reframe-improvements-research.md`) shows the seasickness from auto-reframe is caused by the **policy**, not the smoothing math: continuously tracking the face keeps the camera in sustained, *variable-velocity* motion, and acceleration/jerk (plus breathing zoom = radial "looming" flow) is the proven nausea trigger — no low-pass filter removes it. `_reframe_comfort_enabled()` (default `1`) therefore makes the **global-smooth 2-pass the default render** and turns on two policies that bias toward a locked camera: (1) **stationary-first** — `REFRAME_STATIONARY_THRESH` defaults to `0.30` under comfort (vs `0.0`/off otherwise) so any scene whose target span stays within 30 % of the frame is pinned to a tripod; (2) **per-scene zoom lock** — `REFRAME_ZOOM_LOCK` (default on under comfort) collapses each scene to one zoom level (segment median) via `build_smoothed_trajectory(lock_zoom=True)`, so the frame never breathes mid-shot (zoom still varies *between* scenes, which reads as a new shot across a cut, not motion). Cost: the 2-pass decode. Set `REFRAME_COMFORT=0` to fall back to the original single-pass streaming tracker (measured tight-deadzone centering, `X=0.05`/`Y=0.08`). **The prior deadzone tuning optimized centering error, which the research identifies as the *wrong* objective — perfect centering requires constant motion. The streaming defaults are left untouched; comfort mode addresses nausea via policy instead.** Final arbiter is still the eye — A/B comfort on/off on a real talking-head clip.

## Pipeline Post-processing (per clip)

After `process_video_to_vertical()`:
1. `apply_subtle_zoom(clip_path)` — Ken Burns 1.0→1.05x zoom via `zoompan`
2. `normalize_audio(clip_path)` — two-pass EBU R128 loudnorm at -14 LUFS
3. `select_cover_frame(clip_path)` — scores frames by face presence + sharpness (Laplacian) + exposure; saves `{clip}_cover.jpg`

## Social Publishing (Zernio integration)

Clips can be published/scheduled directly to TikTok, Instagram and YouTube from the ResultCard's **Publish** button. All posting goes through **Zernio** (https://zernio.com) as the unified multi-platform API.

- **`social_publisher.py`**: the integration module.
  - `ZernioClient` — minimal REST client (requests-based, no SDK dep). Methods: `list_accounts()`, `list_scheduled_posts()`, `presign_upload()`, `upload_to_presigned()`, `create_post()`. All raise `ZernioError` on HTTP failures.
  - `SmartScheduler` — picks an optimal posting slot based on Italian-prime-time windows per weekday (tuned for TikTok / Reels / Shorts), with a configurable minimum gap between posts (default 90 min) and anti-collision against already-scheduled posts. Fully deterministic when the `rng` field is seeded — enables reproducible tests. **1:1 port of `tmp/programma_shorts.py:trova_orario_smart`**, including the exact `FASCE_ORARIE` weekday windows:
    ```
    Mon: 12-14, 18-21   Tue: 9-12, 14-22   Wed: 7-11, 14-22
    Thu: 9-12, 15-21    Fri: 11-15, 16-22  Sat: 9-13, 15-20
    Sun: 8-17, 18-20
    ```
    Algorithm (3 steps, same as original):
    1. **Free prime-time window**: find windows with no pre-existing posts inside; pick one at random; try up to 30 random `(hour, minute)` candidates inside it; accept the first one that is `> now` and has `abs(dist) >= min_gap` from every occupied slot.
    2. **15-min scan 07:00-23:00**: if every window has at least one post, scan every 15 minutes across the safe daytime range; collect all candidates passing `> now + 90min gap`; pick one at random.
    3. **Fallback**: pick a random prime-time window + random `(hour, minute)` inside it (gap check skipped — only hit when the whole day is overcrowded).
  - `publish_clip()` emits **verbose SmartScheduler traces** on every `schedule_mode='auto'` call: logs the target day + weekday, the prime-time windows for that weekday, the list of already-occupied times pulled from Zernio, and the picked slot with the reason (`free prime-time window HH-HH` or `fallback`). Lets you see in backend logs exactly why a given timestamp was chosen and confirm collisions are being avoided.
  - `publish_clip()` — orchestrator. Three `schedule_mode` values: `"now"` (publishNow=true), `"auto"` (SmartScheduler picks the slot after fetching existing scheduled posts), `"manual"` (caller supplies `scheduled_for` ISO 8601). Does presign → PUT upload → create post. Returns `{post_id, status, scheduled_for, schedule_mode, platforms}`.

- **Persistence**: Zernio credentials live in `data/config.json` under a dedicated `"zernio"` namespace (isolated from the core keys). `load_zernio_config()` / `save_zernio_config()` in `config_store.py`. The API key is never returned in full — only a `{prefix}...{suffix}` masked form via `zernio_config_status()`.

- **Endpoints** (all require trusted-origin / private-network client):
  - `GET /api/config/zernio` — masked status
  - `POST /api/config/zernio` — merge-update (api_key, accounts, timezone)
  - `GET /api/zernio/accounts` — discovery via Zernio's `/v1/accounts`
  - `POST /api/publish/{job_id}/{clip_index}` — upload + schedule. Accepts `PublishRequest` with title, caption, platforms (list of `{platform, accountId, platformSpecificData?}`), `schedule_mode`, `scheduled_for?`, `timezone?`, `tiktok_settings?`. Optionally runs a fresh compose pass first (`compose_first=true` + toggles/hook_params/subtitle_params) so the uploaded clip reflects the user's Smart Cut / Hook / Subtitles toggles.

- **Frontend** (`dashboard/src/components/`):
  - `ZernioSettings.jsx` — API key input (masked), per-platform account ID fields for TikTok/Instagram/YouTube, "Discover from Zernio" button that hits `/api/zernio/accounts` and lets the user click-pick from discovered accounts, timezone field. Rendered inside SettingsTab.
  - `PublishModal.jsx` — modal launched from the ResultCard's **Publish** button. Title + caption editor (prefilled from clip's `video_title_for_youtube_short` and `tiktok_caption`), platform toggles (disabled if no account ID saved), schedule mode picker (`Now` / `Auto slot` / `Pick time`), datetime-local input for manual mode. Automatically forwards the current ResultCard toggles (Smart Cut / Hook / Subtitles) via `compose_first` so published clips match what the user sees in the preview.
  - `ResultCard.jsx` — has a new **Publish** button next to **Download**. Preserves the existing toggle/compose flow: if any toggle is active, the publish request asks the backend to re-compose before upload.

- **Env vars**: `ZERNIO_BASE_URL` (default `https://zernio.com/api/v1`), `ZERNIO_DEFAULT_TZ` (default `Europe/Rome`), `ZERNIO_HTTP_TIMEOUT` (60s), `ZERNIO_UPLOAD_TIMEOUT` (600s), `ZERNIO_MIN_GAP_SECONDS` (5400 = 90 min for SmartScheduler).

- **Security note**: the reference script shared by the user lives in `tmp/` and contains a real API key in plaintext. **`tmp/` is gitignored** via `.gitignore` — never commit anything from that directory.

## Gemini viral detection — parsing chain

`clippyme.pipeline.gemini_parser` applies a **5-level fallback** when Gemini emits malformed JSON: `strict` → `clean` (smart-quote/comma/backslash fix) → `json_repair` lib → `retry` (one round-trip with error context) → `fallback` (None → whole-video mode). Prompt emits chain-of-thought BEFORE a `### JSON ###` delimiter and uses a 5-axis viral_score rubric (HOOK_STRENGTH, EMOTIONAL_PAYOFF, QUOTABILITY, SELF_CONTAINED, DENSITY) + 3 few-shot examples. Each attempt logs `📊 gemini_parse path=<...> duration_ms=<N>`. Pydantic validation (`ViralClip`) enforces `10≤duration≤75`, `viral_score∈[1,100]`, `viral_reason≥20 chars`. `validate_and_dedupe` drops clips with IoU>0.7 vs a higher-scoring neighbour.

## Code organization rules

- **Backend:** endpoint handlers stay thin (validate → call helper → return JSON). If a handler grows past ~25 lines, extract into a `clippyme.domain.*` module. Don't re-merge `app.py`.
- **Frontend:** `App.jsx` only owns top-level state wiring + JSX composition. Side effects → custom hooks (`hooks/`), visual chunks → components (`components/`).
