# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ClippyMe is a self-hosted AI video platform that transforms long-form videos (YouTube or local uploads) into viral 9:16 vertical shorts. Fork of OpenShorts.

## Architecture

- **Backend** (`app.py`): FastAPI server on port 8000. Config persistence, API endpoints, async job queue, batch processing, compose endpoint for toggle-based export.
- **Processing pipeline** (`main.py`): Orchestrates download (yt-dlp) → transcription (faster-whisper, with URL-hash cache) → scene detection (PySceneDetect) → viral moment detection (Google Gemini, returns `viral_score`/`viral_reason`) → smart 9:16 reframing (YOLOv8 + MediaPipe face tracking) → audio normalization → auto-zoom → cover frame selection.
- **Subtitles** (`subtitles.py`): ASS karaoke generation (`generate_ass_karaoke()`) with 6 viral presets + legacy SRT support. Burns via `ass` filter with bundled fonts. Supports `offset_y` for vertical positioning.
- **Smart Cut** (`smartcut.py`): Optional post-processing that removes silences (>0.8s) and filler words using FFmpeg concat demuxer. Supports EN, IT, ES, FR, DE.
- **Hooks** (`hooks.py`): Text overlay generation with Pillow. Supports emoji via NotoColorEmoji font (lazy-downloaded). Configurable position, size, and `offset_y`.
- **Editor** (`editor.py`): Legacy file — no longer imported by `app.py`. Kept on disk but unused. Do not reference.
- **Frontend** (`dashboard/`): React 18 + Vite 5 + Tailwind CSS v4 + shadcn/ui. Toggle-based editing system with compose-on-download. Polls backend at 2s intervals for job status. Served on port 5175 (Docker) or 5173 (dev).
  - **Logo**: Custom SVG with multi-color gradient design (`public/logo.svg`)
  - **Color palette**: Dark foundation (#050507, #0f0f13, #16161d, #1e1e28) + brand colors (blue #0a81d9 primary, pink-purple-indigo gradient accent, teal #02c5bf, cyan #00d9ff)
  - **Design tokens**: Glassmorphism with backdrop-blur, gradient borders, glow shadows, ambient noise texture, responsive single-column layout
  - **Components**: TopNav (logo + tabs), MediaInput (URL/Upload/Batch tabs, pre-selection panel), ResultCard (9:16 video + toggles + compose download), SubtitleModal/HookModal (two-column settings/preview with offset slider), ProcessingAnimation, Landing page
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

**Auto Edit was removed** — the `/api/edit` endpoint and `VideoEditor` class are no longer used.

## Frontend Design & Components

**Design Philosophy**: Premium, minimal aesthetic with modern glass morphism effects, responsive mobile-first layout, smooth gradient animations.

**Key Components** (`dashboard/src/components/`):
- **TopNav**: Slim header with ClippyMe logo/text, step-based tabs (Create/History/Settings), status indicator.
- **MediaInput**: Three tabs (URL, Upload, Batch) with paste button, drag-drop zone, AI instructions collapsible. **Clip Options** collapsible panel: reframe mode (auto/disabled), Smart Cut toggle, Subtitles toggle+config (preset, mode), Hook toggle+config (position, size). Cookie warning banner when cookies not configured.
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

## Reframing Modes

`analyze_scenes_strategy()` in `main.py` returns one of three modes per scene:
- `TRACK`: single speaker, exponential easing (`diff * 0.08` per frame) via `SmoothedCameraman`
- `WIDE`: 2+ faces detected → letterbox with blurred background (stable, no camera movement)
- `GENERAL`: no faces detected → static letterbox framing

Additionally, `--reframe-mode disabled` overrides all scenes to `DISABLED`: center-crops to 4:3 and adds black bars top/bottom.

`DetectionSmoother` applies a rolling average (window=5) on bounding boxes before feeding to `SmoothedCameraman`.

## Pipeline Post-processing (per clip)

After `process_video_to_vertical()`:
1. `apply_subtle_zoom(clip_path)` — Ken Burns 1.0→1.05x zoom via `zoompan`
2. `normalize_audio(clip_path)` — two-pass EBU R128 loudnorm at -14 LUFS
3. `select_cover_frame(clip_path)` — scores frames by face presence + sharpness (Laplacian) + exposure; saves `{clip}_cover.jpg`
