# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ClippyMe is a self-hosted AI video platform that transforms long-form videos (YouTube or local uploads) into viral 9:16 vertical shorts. Fork of OpenShorts.

## Architecture

- **Backend** (`app.py`): FastAPI server on port 8000. Config persistence, API endpoints, async job queue.
- **Processing pipeline** (`main.py`): Orchestrates download (yt-dlp) → transcription (faster-whisper) → scene detection (PySceneDetect) → viral moment detection (Google Gemini) → smart 9:16 reframing (YOLOv8 + MediaPipe face tracking).
- **Editor** (`editor.py`): FFmpeg filter generation, Gemini File API integration for context-aware editing.
- **Subtitles** (`subtitles.py`): SRT generation with word grouping optimized for vertical video (max 20 chars, 2s segments).
- **Frontend** (`dashboard/`): React 18 + Vite 4 + Tailwind CSS. Polls backend at 2s intervals for job status. Served on port 5175 (Docker) or 5173 (dev).

Config is persisted in `data/config.json` (git-ignored). API keys and Gemini model selection are managed via the dashboard UI, not env files.

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
- **Hardware auto-detection**: CUDA/CPU fallback at runtime for faster-whisper and YOLOv8. No manual config needed.
- **yt-dlp uses Deno** as JS runtime for YouTube bot-detection bypass.
- **Security**: `job_id` validated with strict regex to prevent path traversal. Config endpoints require trusted origin or private network client. Containers run as non-root users.
- **Temp files**: Uploads go to `uploads/`, outputs to `output/`. Both are transient and git-ignored.
