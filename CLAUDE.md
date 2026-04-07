# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ClippyMe is a self-hosted AI video platform that transforms long-form videos (YouTube or local uploads) into viral 9:16 vertical shorts. Fork of OpenShorts.

## Architecture

- **Backend** (`app.py`, ~680 lines): Thin FastAPI layer — endpoint handlers + job queue + worker loop. Heavy logic lives in dedicated modules listed below. Config persistence, async job queue, batch processing.
- **Backend modules** (extracted from `app.py` during 8-round refactor):
  - `compose.py` — `compose_layers()` runs the Smart Cut → Hook → Subtitles pipeline for `/api/compose`. Owns intermediate-file cleanup.
  - `subtitle_pipeline.py` — `run_subtitle_pipeline()` + `resolve_clip_filename()` for `/api/subtitle` and `/api/hook`.
  - `clip_endpoints.py` — `run_smart_cut()` (for `/api/smartcut`) and `restore_job_from_disk()` (for `/api/history/restore`).
  - `job_results.py` — `load_partial_result()` / `load_final_result()` (used by the worker loop) and `build_main_cmd()` (shared between `/api/process` and `/api/batch`).
  - `security.py` — `is_valid_job_id()`, trusted-origin checks.
  - `schemas.py` — Pydantic request models.
  - `metadata_io.py` — `load_job_metadata()` / `save_job_metadata()` atomic helpers.
- **Processing pipeline** (`main.py`): Orchestrates download (yt-dlp) → transcription (faster-whisper, with URL-hash cache) → scene detection (PySceneDetect) → viral moment detection (Google Gemini, returns `viral_score`/`viral_reason`) → smart 9:16 reframing (YOLOv8 + MediaPipe face tracking) → audio normalization → auto-zoom → cover frame selection.
- **Subtitles** (`subtitles.py`): ASS karaoke generation (`generate_ass_karaoke()`) with 6 viral presets + legacy SRT support. Burns via `ass` filter with bundled fonts. Supports `offset_y` for vertical positioning.
- **Smart Cut** (`smartcut.py`): Two-stage post-processing that removes silences and filler words.
  - **Stage 1** — `analyze_silences()` finds keep-segments from Whisper word timestamps (filler words in EN/IT/ES/FR/DE + gaps >0.8s). Renders via `_render_with_auto_editor()` which builds a hand-crafted **auto-editor v3 JSON timeline** and runs `auto-editor plan.json -o out.mp4` for a frame-accurate single-pass render. Falls back to legacy FFmpeg concat demuxer (`_render_with_ffmpeg()`) if the auto-editor binary isn't on PATH.
  - **Stage 2** — `_audio_polish_pass()` runs `auto-editor --edit audio:threshold=0.04 --margin 0.2sec` on the stage-1 output to catch silences the transcript missed (mumbles below ASR confidence, music gaps, ambient quiet). Skipped silently if auto-editor missing or if it doesn't reduce duration by ≥0.5s.
  - The legacy FFmpeg concat path is preserved as a safety net — never deleted, automatically used if auto-editor is unavailable. Public API `smart_cut(clip_path, transcript, clip_start, clip_end, language)` is unchanged. Stats now include `renderer` (`auto-editor-v3` or `ffmpeg-concat`) and optional `audio_polish_saved`.
- **auto-editor binary lifecycle** (`auto_editor_updater.py`):
  - **NOT a pip dep**. The Dockerfile downloads the latest Nim binary (v30.x track) from `https://github.com/WyattBlue/auto-editor/releases/latest/download/auto-editor-linux-{x86_64,aarch64}` at build time and writes it to `/usr/local/bin/auto-editor`.
  - **Runtime auto-update**: `background_updater_loop()` is launched from the FastAPI lifespan as an asyncio task. On startup (and every 24h thereafter) it hits the GitHub Releases API, compares the local `--version` output with the latest tag, and atomically downloads the appropriate arch asset to `/app/data/bin/auto-editor` (writable by the non-root `appuser`).
  - **PATH ordering**: `/app/data/bin` is prepended to `PATH` in the Dockerfile, so the runtime-downloaded binary shadows the build-time install whenever a newer version exists.
  - **Failure modes**: GitHub unreachable / sanity check fails / arch unsupported → updater logs a warning and the existing binary keeps working. Smart Cut's FFmpeg fallback covers the worst case where no binary exists at all.
- **Hooks** (`hooks.py`): Text overlay generation with Pillow. Supports emoji via NotoColorEmoji font (lazy-downloaded). Configurable position, size, and `offset_y`.
- **Frontend** (`dashboard/`): React 18 + Vite 5 + Tailwind CSS v4 + shadcn/ui. `App.jsx` (~270 lines) is now a thin orchestrator — wiring + composition only. Toggle-based editing system with compose-on-download. Polls backend at 2s intervals for job status. Served on port 5175 (Docker) or 5173 (dev).
  - **Custom hooks** (`dashboard/src/hooks/`): `useJobSubmission` (process+batch handlers), `useJobPolling` (status polling loop), `useHistory` (history list state), `useSessionPersistence` (localStorage round-trip), `useBackendStatus` (health check), `useClipStates` (per-clip disable/delete/published flags persisted in localStorage per jobId).
  - **Logo**: Custom SVG with multi-color gradient design (`public/logo.svg`)
  - **Color palette**: Dark foundation (#050507, #0f0f13, #16161d, #1e1e28) + brand colors (blue #0a81d9 primary, pink-purple-indigo gradient accent, teal #02c5bf, cyan #00d9ff)
  - **Design tokens**: Glassmorphism with backdrop-blur, gradient borders, glow shadows, ambient noise texture, responsive single-column layout
  - **Components** (`dashboard/src/components/`): `TopNav` (logo + tabs + status + cancel), `IdleHero`, `MediaInput` (**Single** tab with URL/Upload toggle + **Batch** tab with mixed URLs+files, pre-selection panel), `ResultCard` (9:16 video + toggles + compose download + disable/delete/publish + `Published` pill), `ResultsGrid` (grid + **`Publish all`** batch button), `SubtitleModal`/`HookModal` (two-column settings/preview with **unified vertical position slider**, `Apply` buttons), `PublishModal` (single-clip publish), `BatchPublishModal` (sequential multi-clip publish with per-clip live status), `ProcessingView` (merges processing + error + partial-results states), `ProcessingAnimation`, `PipelineSteps`, `LogsPanel`, `HistoryTab`, `SettingsTab` (with `ZernioSettings`), `ApiKeyModal`, `ConfettiOverlay`, Landing page
  - **shadcn/ui components** (`dashboard/src/components/ui/`): Button, Badge, Tooltip, Skeleton, Sonner (toasts), Progress, Dialog, Tabs — all using Radix UI primitives via `radix-ui` monorepo
- **Fonts** (`fonts/`): Bundled TTF fonts for subtitle and hook rendering (Anton, Bangers, Montserrat-Black/ExtraBold, Poppins-Black/Medium, NotoSerif-Bold). Served via `/fonts` static mount.

Config is persisted in `data/config.json` (git-ignored). Cookies in `data/cookies.txt`. API keys, Gemini model, and cookies are managed via the dashboard UI Settings tab, not env files.

## Toggle System (Compose-on-Download)

The post-processing workflow uses independent toggles per clip:

- **Smart Cut** — on/off, no additional params needed
- **Hook** — on/off + text (auto-filled from Gemini suggestion), position, size, offset_y
- **Subtitles** — on/off + preset, mode (karaoke/classic), font, colors, offset_y

**Behavior**: Toggles are UI-only state. No processing happens on toggle click. At download time, `POST /api/compose/{job_id}/{clip_index}` receives active toggles + params and composes the final video in a single pipeline: Smart Cut → Hook → Subtitles.

**Pre-selections**: Users can pre-configure toggle states and params before processing (in MediaInput's "Clip Options" panel). These defaults are applied to all generated clips. Each clip can be overridden individually.

**Subtitle pre-selection mode coupling**: The pre-selection panel shows different controls depending on `mode`:
- **Karaoke**: visual 2×3 grid of the 6 `SUBTITLE_PRESETS` (Classic, Hormozi, Neon, MrBeast, Minimal, Fire) — each rendered with its actual font/color/shadow style.
- **Classic**: font dropdown (Verdana, Montserrat-Black, Anton, Bangers, Poppins-Black/Medium) + font color swatches + position (top/middle/bottom). These params are propagated via `preselections.subtitles.{font, font_color, position}` and seeded into each `ResultCard`'s `subtitleParams` so the compose endpoint receives them per-clip without manual reconfiguration.

**Auto Edit was removed** — the `/api/edit` endpoint and `VideoEditor` class are no longer used.

## Frontend Design & Components

**Design Philosophy**: Premium, minimal aesthetic with modern glass morphism effects, responsive mobile-first layout, smooth gradient animations.

**Key Components** (`dashboard/src/components/`):
- **TopNav**: Slim header with ClippyMe logo/text, step-based tabs (Create/History/Settings), status indicator.
- **MediaInput**: **Two tabs** — `Single` (with internal URL/Upload toggle, paste button, drag-drop zone) and `Batch` (textarea for URLs + multi-file upload zone with removable list, total counter URLs+files / 20). AI instructions collapsible. **Clip Options** collapsible panel: reframe mode (auto/disabled), Smart Cut toggle, Subtitles toggle+config (mode-aware: karaoke shows visual preset grid, classic shows font/color/position), Hook toggle+config (position, size — defaults to **S**). Cookie warning banner when cookies not configured.
- **ResultCard**: 9:16 aspect ratio video player, viral score badge (color-coded: green 80+, yellow 50-79, orange <50 with tooltip), duration. **Toggle buttons** (Smart Cut, Hook, Subtitles) with pink active state + gear icon for config. Compose-on-download: clicking Download calls `/api/compose` with active toggles, or downloads original clip if no toggles active. YouTube title/TikTok caption fields.
- **SubtitleModal / HookModal**: Two-column layout (settings left, live preview right; stacks vertically on mobile). Modal backdrop blur, gradient apply buttons, color pickers, preset dropdowns. **Vertical offset slider** (-50% to +50%). Font preview loads actual TTFs via FontFace API.
- **KeyInput** (Settings): Gemini API key, HuggingFace token, Gemini model selector. **Cookie upload** section: file input (.txt), save/remove buttons, configured status indicator.
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
- **Vite dev proxy** (`vite.config.js`): `/api`, `/videos`, `/thumbnails`, `/gallery`, `/video`, **`/fonts`** → all proxied to `http://backend:8000`. The `/fonts` proxy is **mandatory** for the SubtitleModal font preview to work — without it, `FontFace` requests 404 and the preview falls back silently to the system font (this was a real bug).

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
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd dashboard && npm install && npm run dev
```

### Tests
```
python -m pytest tests/test_backend_fixes.py -v
```
Tests use `unittest` with mocks. Run from project root (test file adds root to `sys.path`).

### Frontend build
```
cd dashboard && npm run build
```

### Adding shadcn/ui components
```
cd dashboard && npx shadcn add <component>
```
Components land in `src/components/ui/`. They use Tailwind v4 class syntax — verify compatibility before adding.

### Git security setup
```
git config core.hooksPath .githooks
```
Activates the pre-commit hook that blocks sensitive data (API keys, cookies, tokens).

## Key Patterns

- **Job queue**: In-memory async queue in `app.py`. Jobs submitted via `POST /api/process`, polled via `GET /api/status/{job_id}`.
- **Batch processing**: `POST /api/batch` accepts up to 20 URLs, creates one job per URL, returns `batch_id`. Polled via `GET /api/batch/{batch_id}`. Supports `reframe_mode` parameter.
- **Mixed batch (URLs + files)**: The frontend `useJobSubmission.handleBatchProcess` supports both. URLs are submitted in one shot to `/api/batch`; each file is submitted individually to `/api/process`. The hook then unifies polling across all returned `job_id`s using `/api/status/{job_id}`, aggregating progress until every job reaches a terminal state. No backend change is needed for mixed batches.
- **Compose endpoint**: `POST /api/compose/{job_id}/{clip_index}` accepts `toggles` (smartcut/hook/subtitles booleans), `hook_params`, `subtitle_params`. Composes layers in order: Smart Cut → Hook → Subtitles. Returns `composed_url`. Cleans up intermediate files.
- **Transcription cache**: `data/cache/` stores transcripts keyed by SHA256(url)[:16]. TTL 7 days, pruned by the background cleanup task.
- **Hardware auto-detection**: CUDA/CPU fallback at runtime for faster-whisper and YOLOv8. No manual config needed.
- **yt-dlp uses Deno** as JS runtime for YouTube bot-detection bypass.
- **Cookie management**: Uploaded once in Settings, persisted at `data/cookies.txt`. Used automatically for all downloads. Fallback chain: `data/cookies.txt` → `YOUTUBE_COOKIES` env var → none.
- **Security**: `job_id` validated with strict regex to prevent path traversal. Config endpoints require trusted origin or private network client. Containers run as non-root users. Pre-commit hook blocks API keys, tokens, and cookie data.
- **Temp files**: Uploads go to `uploads/`, outputs to `output/`. Both are transient and git-ignored.
- **Font serving**: `/fonts` static mount serves bundled TTFs to frontend for SubtitleModal preview (loaded via FontFace API).

## main.py CLI Args

```
python main.py <url_or_path> [options]
  --instructions "focus on hooks"        # Directive injected into Gemini prompt
  --no-zoom                              # Disable Ken Burns auto-zoom (1.0→1.05x)
  --reframe-mode auto|disabled           # Auto face tracking or 4:3 crop with black bars
```

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/process` | Process single video (accepts `reframe_mode`) |
| POST | `/api/batch` | Submit multiple URLs (accepts `reframe_mode`) |
| GET | `/api/status/{job_id}` | Poll job progress |
| GET | `/api/batch/{batch_id}` | Aggregated batch status |
| POST | `/api/compose/{job_id}/{clip_index}` | Compose final video from active toggles |
| POST | `/api/smartcut/{job_id}/{clip_index}` | Generate smart-cut version of a clip |
| POST | `/api/subtitle` | Generate and burn subtitles |
| POST | `/api/hook` | Add hook text overlay |
| GET | `/api/subtitle/presets` | List available subtitle preset names |
| POST | `/api/config/cookies` | Upload persistent cookies file |
| GET | `/api/config/cookies/status` | Check if cookies are configured |
| DELETE | `/api/config/cookies` | Remove cookies file |
| POST | `/api/cancel/{job_id}` | Cancel a running job |
| GET | `/api/history` | List past jobs |
| POST | `/api/history/{job_id}/restore` | Restore job to memory |
| DELETE | `/api/history/{job_id}` | Delete job from disk |

## Subtitle Presets

Defined in `subtitles.py:SUBTITLE_PRESETS`. Six built-in presets:
`classic_white`, `hormozi_bold`, `neon_glow`, `mrbeast_box`, `minimal_clean`, `fire_impact`.

When using ASS karaoke, the `ass` FFmpeg filter is used with `fontsdir` pointing to the `fonts/` directory. For SRT the `subtitles` filter is used with adjustable `MarginV` (default 350, modified by `offset_y`).

**Safe zone defaults**: MarginL/R = **110 px** (≈10% of the 1080px vertical frame → TikTok/Reels safe zone so long captions don't get cropped). Preset fontsize defaults have been reduced (`80→62`, `85→66`, `75→58`, `70→54`) to avoid horizontal overflow.

## Unified vertical position slider

`HookModal.jsx` and `SubtitleModal.jsx` expose a **single `-50 → +50` slider** for vertical placement — no more separate top/center/bottom radio buttons. The slider value is the absolute Y position in percent (−50 = top, 0 = center, +50 = bottom) and the modal preview uses `top: {50 + offsetY}%` so what-you-see matches what-you-get.

Under the hood the frontend always sends `position='center'` to the backend, which is aliased to `'middle'` in both `subtitles.py` and `hooks.py`. This keeps the existing ASS/ffmpeg pipeline untouched while giving the user a single continuous control.

The apply buttons are labelled **"Apply Hook"** / **"Apply Karaoke Subtitles"** / **"Apply Classic Subtitles"** (not "Add" — the toggle switch outside already decides whether the layer is rendered at download time).

## Clip lifecycle & batch publish

- **`useClipStates(jobId)`** (`dashboard/src/hooks/useClipStates.js`) — per-clip state keyed by index, persisted in localStorage under `clippyme_clip_states_{jobId}`. Shape: `{ disabled, deleted, publishedAt }`. Survives page reloads without a backend round-trip.
- **`ResultCard.jsx`** top-left action toolbar: Eye/Eye-off (disable → opacity 50%, excluded from batch publish), Trash (with confirm → hides from grid, file stays on disk). Top-right: green **"Published"** pill when `publishedAt` is set.
- **`BatchPublishModal.jsx`** — launched from the `Publish all (N)` button in `ResultsGrid`. Iterates every clip where `!disabled && !deleted && !publishedAt` and calls `POST /api/publish/{jobId}/{index}` sequentially with live per-clip status (pending / ok / error). Supports `schedule_mode='auto'` (SmartScheduler picks a different slot per clip) and `'now'` (all immediate). Each successful publish marks the clip via `onUpdateClipState(index, { publishedAt: Date.now() })`.
- **`PublishModal.jsx`** (single-clip path) now accepts an `onPublished` callback so the parent `ResultCard` can flip the clip's `publishedAt` flag without duplicating state.

## Reframing Modes (overhauled)

`analyze_scenes_strategy()` samples **7 frames per scene** (was 3) and returns one of three modes:
- `TRACK`: single speaker (≤1.0 avg faces) → active-speaker tracking via `SpeakerTracker` + `SmoothedCameraman`
- `WIDE`: multi-speaker (max ≥2 and avg >1.0) → **also routed through `SpeakerTracker`** with longer cooldown (45 frames ≈ 1.5s) for interview/podcast switching. **No more letterbox-with-blurred-bg fallback.**
- `GENERAL`: no faces seen anywhere in scene → letterbox via `create_general_frame()`

`--reframe-mode disabled` overrides all scenes to `DISABLED`: center-crops to 4:3 + black bars.

### Active speaker detection (`SpeakerTracker`)
Uses **mouth-aspect-ratio (MAR) variance** as the dominant signal. For each detected face the pipeline:
1. Runs MediaPipe `FaceMesh` (max_num_faces=1) on the face ROI to extract mouth landmarks (13/14/78/308) → `compute_mouth_aspect_ratio()`
2. Keeps a 1-second sliding window of MAR samples per speaker ID
3. Combined score = `0.3 * face_size_norm + 1.0 * MAR_variance` — mouth motion dominates, so a small but speaking face beats a larger silent one
4. Hysteresis: active speaker gets a 3.0× sticky bonus; switches require `cooldown_frames=45` to elapse

### `SmoothedCameraman` (overhauled)
- **Adaptive smoothing**: `SMOOTHING_SLOW=0.08` for small/medium moves, `SMOOTHING_FAST=0.30` when target is >60% of crop_width away (eliminates "software-glide" on speaker switches inside one scene)
- **Y-axis tracking**: crop now follows faces vertically, not just horizontally — separate dead-band per axis
- **Dynamic vertical zoom**: animates between 1.0× and 1.6× based on detected face height ratio (small face → tight zoom; large face → no zoom)
- **YOLO person fallback**: when faces aren't detectable, the YOLO body bbox is used with `is_person_box=True` so the cameraman aims at the upper 15% (head zone) instead of the body center — fixes the "camera shows knees" bug

`DetectionSmoother` still applies a rolling average (window=5) on bbox coordinates before feeding to `SpeakerTracker`. MAR is computed *after* smoothing on the smoothed bbox.

## Pipeline Post-processing (per clip)

After `process_video_to_vertical()`:
1. `apply_subtle_zoom(clip_path)` — Ken Burns 1.0→1.05x zoom via `zoompan`
2. `normalize_audio(clip_path)` — two-pass EBU R128 loudnorm at -14 LUFS
3. `select_cover_frame(clip_path)` — scores frames by face presence + sharpness (Laplacian) + exposure; saves `{clip}_cover.jpg`

## Social Publishing (Zernio integration)

Clips can be published/scheduled directly to TikTok, Instagram and YouTube from the ResultCard's **Publish** button. All posting goes through **Zernio** (https://zernio.com) as the unified multi-platform API.

- **`social_publisher.py`**: the integration module.
  - `ZernioClient` — minimal REST client (requests-based, no SDK dep). Methods: `list_accounts()`, `list_scheduled_posts()`, `presign_upload()`, `upload_to_presigned()`, `create_post()`. All raise `ZernioError` on HTTP failures.
  - `SmartScheduler` — picks an optimal posting slot based on Italian-prime-time windows per weekday (tuned for TikTok / Reels / Shorts), with a configurable minimum gap between posts (default 90 min) and anti-collision against already-scheduled posts. Fully deterministic when the `rng` field is seeded — enables reproducible tests.
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

- **Tests**: `tests/test_social_publisher.py` covers SmartScheduler (slot selection, gap enforcement, past-time skipping, fallback when overcrowded), publish_clip input validation, and ZernioClient with a mocked `requests.Session` (no real network). 13 tests; the full suite including smartcut is 32 tests in ~0.1s.

- **Security note**: the reference script shared by the user lives in `tmp/` and contains a real API key in plaintext. **`tmp/` is gitignored** via `.gitignore` — never commit anything from that directory.

## Refactor History (8-round autoresearch pipeline)

`app.py` and `App.jsx` were systematically split into focused modules. **Do not re-merge them.** When adding new logic, prefer extending an existing module or creating a new one over growing the orchestrators.

| File | Before | After | Δ |
|---|---|---|---|
| `app.py` | 1271 | 678 | −47% |
| `dashboard/src/App.jsx` | 1068 | 270 | −75% |

**Backend rule of thumb:** if an endpoint handler grows past ~25 lines, extract its body into a helper module (see `compose.py`, `subtitle_pipeline.py`, `clip_endpoints.py`). Endpoints should stay thin: validate → call helper → return JSON.

**Frontend rule of thumb:** `App.jsx` only owns top-level state wiring + JSX composition. Side effects belong in custom hooks (`hooks/`), visual chunks belong in components (`components/`).
