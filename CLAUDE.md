# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ClippyMe is a self-hosted AI video platform that transforms long-form videos (YouTube or local uploads) into viral 9:16 vertical shorts. Fork of OpenShorts.

## Architecture

- **Backend** (`app.py`): FastAPI server on port 8000. Config persistence, API endpoints, async job queue, batch processing.
- **Processing pipeline** (`main.py`): Orchestrates download (yt-dlp) → transcription (faster-whisper, with URL-hash cache) → scene detection (PySceneDetect) → viral moment detection (Google Gemini, returns `viral_score`/`viral_reason`) → smart 9:16 reframing (YOLOv8 + MediaPipe face tracking) → audio normalization → auto-zoom → cover frame selection.
- **Editor** (`editor.py`): FFmpeg filter generation with 3-level retry (full Gemini filter → simplified → passthrough). Gemini File API integration for context-aware editing.
- **Subtitles** (`subtitles.py`): ASS karaoke generation (`generate_ass_karaoke()`) with 6 viral presets + legacy SRT support. Burns via `ass` filter with bundled fonts.
- **Smart Cut** (`smartcut.py`): Optional post-processing that removes silences (>0.8s) and filler words using FFmpeg concat demuxer. Triggered on-demand, never automatic.
- **Frontend** (`dashboard/`): React 18 + Vite 4 + Tailwind CSS. Premium glass-morphism design inspired by Linear/Raycast. Polls backend at 2s intervals for job status. Served on port 5175 (Docker) or 5173 (dev).
  - **Logo**: Custom SVG with multi-color gradient design (`public/logo.svg`)
  - **Color palette**: Dark foundation (#050507, #0f0f13, #16161d, #1e1e28) + brand colors (blue #0a81d9 primary, pink-purple-indigo gradient accent, teal #02c5bf, cyan #00d9ff)
  - **Design tokens**: Glassmorphism with backdrop-blur, gradient borders, glow shadows, ambient noise texture, responsive single-column layout
  - **Components**: TopNav (logo + tabs), MediaInput (URL/Upload/Batch tabs, advanced options), ResultCard (9:16 video + actions), SubtitleModal/HookModal (two-column settings/preview), ProcessingAnimation, Landing page
  - **Fonts** (`fonts/`): Bundled TTF fonts for subtitle rendering (Anton, Bangers, Montserrat-Black/ExtraBold, Poppins-Black/Medium) + ASS karaoke support
- **Fonts** (`fonts/`): Bundled TTF fonts for ASS subtitle rendering (Anton, Bangers, Montserrat-Black/ExtraBold, Poppins-Black/Medium, NotoSerif-Bold).

Config is persisted in `data/config.json` (git-ignored). API keys and Gemini model selection are managed via the dashboard UI, not env files.

## Frontend Design & Components

**Design Philosophy**: Premium, minimal aesthetic with modern glass morphism effects, responsive mobile-first layout, smooth gradient animations.

**Key Components** (`dashboard/src/components/`):
- **TopNav**: Slim header with ClippyMe logo/text, step-based tabs (Create/History/Settings), status indicator. Replaces previous sidebar.
- **MediaInput**: Three tabs (URL, Upload, Batch) with paste button, drag-drop zone, advanced options collapsible. Batch mode shows URL counter (max 20).
- **ResultCard**: 9:16 aspect ratio video player, viral score badge (color-coded: green 80+, yellow 50-79, orange <50 with tooltip), duration, action buttons (Auto Edit, Subtitles, Hook, Smart Cut), download button, YouTube title/TikTok caption fields.
- **SubtitleModal / HookModal**: Two-column layout (settings left, live preview right; stacks vertically on mobile). Modal backdrop blur, gradient apply buttons, color pickers, preset dropdowns.
- **ProcessingAnimation**: Source video container with pulsing gradient border, status badge with animated dots, model/hardware info badges, synced playback indicator.
- **Landing**: Hero with gradient logo, "ClippyMe" text (pink→purple→blue), feature grid (6 items), "How it works" (3 steps), premium CTAs. Triggered on first load or via "Create" tab from idle state.

**Tailwind Config Customizations**:
- Extended color palette with dark surfaces and brand gradients
- Custom animations: `gradient-shift` (8s background cycle for animations)
- Custom shadows: `glow-pink`, `elevated` for layered effects
- Border utilities using `rgba(255,255,255,0.04)` to `0.12)` for subtle dividers

**CSS Features** (`dashboard/src/index.css`):
- `.glass-panel`: backdrop-blur-2xl with subtle gradient, used on modals and cards
- `.gradient-border`: pink-to-blue gradient pseudo-element border
- `.btn-primary`, `.btn-ghost`: gradient and transparent button styles with hover glow
- Refined scrollbar (6px, transparent track, rounded thumb)
- Body texture: subtle noise/grain via `::after` pseudo-element
- `.bg-ambient`: layered radial gradients in brand colors replacing grid pattern

**App State & Flow** (`dashboard/src/App.jsx`):
- Step-based workflow: idle (input) → processing (logs) → complete (results/history)
- Session persistence: `localStorage` for credentials, history, job results
- Job polling: 2-second interval via `setInterval`, cleared on unmount
- Batch processing: `batchId` and `batchJobs` state for multi-URL submissions
- Error handling: red-bordered error panel with retry CTA
- Confetti animation (40 particles) triggered on job completion
- All original API calls, event handlers, and state transitions preserved

## Commands

### Run with Docker (primary method)
```
docker compose up --build
```
Backend: http://localhost:8000 | Frontend: http://localhost:5175

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

## Key Patterns

- **Job queue**: In-memory async queue in `app.py`. Jobs submitted via `POST /api/process`, polled via `GET /api/status/{job_id}`.
- **Batch processing**: `POST /api/batch` accepts up to 20 URLs, creates one job per URL, returns `batch_id`. Polled via `GET /api/batch/{batch_id}`.
- **Transcription cache**: `data/cache/` stores transcripts keyed by SHA256(url)[:16]. TTL 7 days, pruned by the background cleanup task.
- **Hardware auto-detection**: CUDA/CPU fallback at runtime for faster-whisper and YOLOv8. No manual config needed.
- **yt-dlp uses Deno** as JS runtime for YouTube bot-detection bypass.
- **Security**: `job_id` validated with strict regex to prevent path traversal. Config endpoints require trusted origin or private network client. Containers run as non-root users.
- **Temp files**: Uploads go to `uploads/`, outputs to `output/`. Both are transient and git-ignored.

## main.py CLI Args

```
python main.py <url_or_path> [options]
  --instructions "focus on hooks"   # Directive injected into Gemini prompt
  --no-zoom                         # Disable Ken Burns auto-zoom (1.0→1.05x)
```

## API Endpoints (key additions)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/batch` | Submit multiple URLs for batch processing |
| GET | `/api/batch/{batch_id}` | Aggregated status of a batch |
| POST | `/api/smartcut/{job_id}/{clip_index}` | Run Smart Cut on a specific clip |
| GET | `/api/subtitle/presets` | List available subtitle preset names |

## Subtitle Presets

Defined in `subtitles.py:SUBTITLE_PRESETS`. Six built-in presets:
`classic_white`, `hormozi_bold`, `neon_glow`, `mrbeast_box`, `minimal_clean`, `fire_impact`.

When using ASS karaoke, the `ass` FFmpeg filter is used with `fontsdir` pointing to the `fonts/` directory. For SRT the `subtitles` filter is used with `MarginV=350` (safe zone for vertical video).

## Reframing Modes

`analyze_scenes_strategy()` in `main.py` returns one of four modes per scene:
- `TRACK`: single speaker, exponential easing (`diff * 0.08` per frame)
- `TRACK_GROUP`: 2+ faces within 40% of frame width → camera centers on barycentre
- `WIDE`: 2+ faces spread across >50% frame → letterbox
- `GENERAL`: no faces detected → static or scene-based framing

`DetectionSmoother` applies a rolling average (window=5) on bounding boxes before feeding to `SmoothedCameraman`.

## Pipeline Post-processing (per clip)

After `process_video_to_vertical()`:
1. `apply_subtle_zoom(clip_path)` — Ken Burns 1.0→1.05x zoom via `zoompan`
2. `normalize_audio(clip_path)` — two-pass EBU R128 loudnorm at -14 LUFS
3. `select_cover_frame(clip_path)` — scores frames by face presence + sharpness (Laplacian) + exposure; saves `{clip}_cover.jpg`
