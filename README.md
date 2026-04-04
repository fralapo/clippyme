# ClippyMe

<div align="center">
  <img src="dashboard/public/logo.svg" alt="ClippyMe Logo" width="80" />
  <p><strong>Self-hosted AI video platform that turns long-form videos into viral 9:16 shorts.</strong></p>
</div>

## Features

- **Viral Moment Detection** — Google Gemini analyzes transcripts and scenes to score and rank the best moments
- **Smart 9:16 Reframing** — YOLOv8 + MediaPipe face tracking with exponential easing; auto-switches between single-face tracking and wide letterbox for groups
- **Toggle System** — Smart Cut, Hook, and Subtitles as independent toggles per clip; compose only at download time
- **ASS Karaoke Subtitles** — 6 viral presets with live preview, font selection, and vertical offset slider
- **Smart Cut** — Silence and filler-word removal (supports EN, IT, ES, FR, DE)
- **Hook Overlay** — Text overlay with emoji support, configurable position and size
- **Pre-selection** — Choose options before processing; applied automatically to all generated clips
- **Batch Processing** — Submit up to 20 URLs at once
- **Reframe Modes** — Auto (face tracking) or Disabled (4:3 crop with black bars)

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI, Python 3.11, async job queue |
| AI | Google Gemini, faster-whisper, YOLOv8, MediaPipe |
| Video | FFmpeg, yt-dlp (Deno JS runtime), PySceneDetect |
| Frontend | React 18, Vite 5, Tailwind CSS v4, shadcn/ui |
| Infra | Docker (NVIDIA CUDA 12.3 + CPU fallback) |

## Quick Start

```bash
git clone https://github.com/your-user/clippyme
cd clippyme
docker compose up --build
```

Open **http://localhost:5175**, enter your Gemini API key in Settings, and start clipping.

> [!TIP]
> First run or after dependency changes: `docker compose down -v && docker compose up --build` to clear cached volumes.

## Local Development

```bash
# Backend
pip install -r requirements.txt
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd dashboard && npm install && npm run dev
```

Frontend dev server: http://localhost:5173 | Backend: http://localhost:8000

## Configuration

All settings are managed through the dashboard UI (**Settings** tab):

| Setting | Required | Description |
|---------|----------|-------------|
| Gemini API Key | Yes | Powers viral detection, hook generation, and clip analysis |
| HuggingFace Token | No | Faster Whisper model downloads |
| YouTube/Twitch Cookies | No | Netscape `.txt` file for bypassing download restrictions |
| Gemini Model | No | Model selection (default: gemini-2.5-flash) |

> [!NOTE]
> No `.env` file needed. Config persists in `data/config.json` (git-ignored). Cookies are stored in `data/cookies.txt`.

## How It Works

```
Input (URL or file)
  → Download (yt-dlp)
  → Transcribe (faster-whisper, cached by URL hash)
  → Detect scenes (PySceneDetect)
  → Rank viral moments (Gemini)
  → Reframe to 9:16 (face tracking or letterbox)
  → Post-process (zoom, audio normalization, cover frame)
  → User toggles: Smart Cut / Hook / Subtitles
  → Compose & Download
```

## Architecture

```
app.py          FastAPI server, job queue, compose endpoint, config
main.py         Pipeline: download → transcribe → detect → reframe → normalize
subtitles.py    ASS karaoke (6 presets) + SRT, vertical offset support
smartcut.py     Silence/filler removal via FFmpeg concat demuxer
hooks.py        Text overlay with emoji support (Pillow + NotoColorEmoji)
dashboard/      React + Vite + Tailwind v4 + shadcn/ui frontend
fonts/          Bundled TTF fonts for subtitle and hook rendering
data/           Config, cookies, transcription cache (git-ignored)
```

## API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/process` | Process single video (URL or file upload) |
| POST | `/api/batch` | Submit up to 20 URLs for batch processing |
| GET | `/api/status/{job_id}` | Poll job progress |
| GET | `/api/batch/{batch_id}` | Batch status |
| POST | `/api/compose/{job_id}/{clip_index}` | Compose final video from active toggles |
| POST | `/api/smartcut/{job_id}/{clip_index}` | Generate smart-cut version |
| POST | `/api/subtitle` | Generate and burn subtitles |
| POST | `/api/hook` | Add hook text overlay |
| POST | `/api/config/cookies` | Upload persistent cookies file |
| GET | `/api/config/cookies/status` | Check if cookies are configured |

## Subtitle Presets

`classic_white` · `hormozi_bold` · `neon_glow` · `mrbeast_box` · `minimal_clean` · `fire_impact`

## CLI

```bash
python main.py <url_or_path> [options]
  --instructions "focus on hooks"        # Directive for Gemini
  --no-zoom                              # Disable Ken Burns auto-zoom
  --reframe-mode auto|disabled           # Auto tracking or 4:3 crop
```

## Security

- Pre-commit hook blocks API keys, tokens, and cookie data from being committed
- `.gitignore` covers `data/`, cookies, `.env`, and all output directories
- Job IDs validated with strict regex to prevent path traversal
- Containers run as non-root users

> [!IMPORTANT]
> After cloning, activate the pre-commit hook: `git config core.hooksPath .githooks`

## CPU / Apple Silicon

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up --build
```
