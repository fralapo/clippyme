# Clippyme

High-performance AI clip generator focused on viral 9:16 shorts. Streamlined fork of OpenShorts.

## Features

- **Clip Generator** — Turn long YouTube videos or local uploads into viral-ready 9:16 shorts for TikTok, Instagram Reels, and YouTube Shorts
- **Viral Moment Detection** — Google Gemini analyzes transcripts and scene boundaries to score and rank high-potential moments
- **Smart 9:16 Reframing** — YOLOv8 + MediaPipe face tracking with exponential easing; 4 reframing modes (track, track-group, wide, general)
- **ASS Karaoke Subtitles** — 6 viral presets (Classic White, Hormozi Bold, Neon Glow, MrBeast Box, Minimal Clean, Fire Impact) with live preview
- **Smart Cut** — On-demand silence and filler-word removal via FFmpeg concat demuxer
- **Batch Processing** — Submit up to 20 URLs at once; each processed in parallel
- **Cookies.txt Support** — Upload cookies via dashboard to bypass YouTube restrictions
- **Premium UI** — Glass-morphism dark design with shadcn/ui components, sonner toasts, Radix UI primitives

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI + uvicorn, Python 3.11 |
| AI | Google Gemini (viral detection + editing), faster-whisper (transcription), YOLOv8 + MediaPipe (face tracking) |
| Video | FFmpeg, yt-dlp (with Deno JS runtime), PySceneDetect |
| Frontend | React 18, Vite 5, Tailwind CSS v4, shadcn/ui, Radix UI |
| Infra | Docker (NVIDIA CUDA 12.3 + CPU fallback), Node 20 Alpine |

## Quick Start

```bash
git clone https://github.com/your-user/clippyme
cd clippyme
docker compose up --build
```

Open **http://localhost:5175**, enter your Gemini API key in Settings, and start clipping.

> **First run or after dependency changes**: use `docker compose down -v && docker compose up --build` to clear cached node_modules volume.

## Local Development

```bash
# Backend
pip install -r requirements.txt
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd dashboard && npm install && npm run dev
```

Frontend dev server: http://localhost:5173 (proxies `/api` to backend on 8000)

## API Keys

All keys are managed through the dashboard UI (Settings tab) — no `.env` file needed.

- **Gemini API key** — required for viral detection, auto-edit, hook generation
- **HuggingFace token** (optional) — for private model access

## Architecture

```
app.py          FastAPI server, job queue, config persistence
main.py         Processing pipeline: download → transcribe → detect → reframe → normalize
editor.py       FFmpeg filter generation via Gemini (3-level retry)
subtitles.py    ASS karaoke generation, 6 presets, SRT fallback
smartcut.py     Silence/filler removal via FFmpeg concat demuxer
dashboard/      React + Vite frontend
fonts/          Bundled TTF fonts for subtitle rendering
data/           Config + transcription cache (git-ignored)
```

## Subtitle Presets

`classic_white` · `hormozi_bold` · `neon_glow` · `mrbeast_box` · `minimal_clean` · `fire_impact`

## CPU / Apple Silicon

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up --build
```
