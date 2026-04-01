# GEMINI.md - OpenShorts.app Project Context

## Project Overview
**OpenShorts.app** is a self-hosted AI video platform designed to automate the creation of short-form content. It specializes in transforming long-form videos (from YouTube or local uploads) into viral 9:16 vertical clips using AI-driven moment detection and smart reframing.

### Core Tools
1.  **Clip Generator:** Converts YouTube URLs or local uploads into vertical shorts. It uses AI to detect viral moments, transcribes audio, and performs smart reframing with subject tracking.
2.  **AI Editor & Subtitles:** Provides automated cropping logic and dynamic subtitle generation with customizable styles to enhance clip engagement.

### Architecture
- **Frontend:** React 18, Vite 4, Tailwind CSS. Located in the `dashboard/` directory. Runs as a non-root `node` user in Docker for improved security.
- **Backend:** FastAPI (Python 3.11). Main entry point is `app.py`. Runs as a non-root `appuser` in Docker.
- **Processing Engine:**
    - `main.py`: Orchestrates the pipeline (transcription, scene detection, AI clipping). Uses Deno for YouTube JS challenges.
    - `editor.py`: Core FFmpeg-based video editing, cropping, and smart reframing logic.
    - `subtitles.py`: Automated subtitle generation and styling.
- **Infrastructure:** Docker-based deployment with a job-based background processing queue. Includes a custom bridge network (`clippyme-net`) for service isolation and a persistent `data/config.json` for dynamic API key management.

## Key Technologies
- **AI Models & APIs:**
    - **Google Gemini (1.5 Flash/Pro):** Used for viral moment detection and editing context analysis.
    - **faster-whisper:** Local/high-performance speech-to-text for transcription.
    - **YOLOv8 & MediaPipe:** Subject tracking and face detection for smart 9:16 reframing.
- **Video/Media Tools:** FFmpeg, `yt-dlp` (with Deno runtime for JS challenges), `PySceneDetect`.
- **Infrastructure:** Docker, FastAPI, React.

## Building and Running

### Using Docker (Recommended)
1.  Clone the repository and copy `.env.example` to `.env` (optional).
2.  Run the application:
    ```bash
    docker compose up --build
    ```
3.  Access the dashboard at `http://localhost:5175`.
4.  Configure your API keys directly from the "API Configuration" section in the Dashboard. These are persisted in `data/config.json`.

## Development Conventions

### API Key Management
- API keys can be managed via the Dashboard.
- **Persistent Configuration:** The system uses `data/config.json` (mounted as a Docker volume) to store keys. This file takes precedence over `.env`.
- Keys are updated in the process environment in real-time for all new jobs.

### Environment Variables
- `MAX_CONCURRENT_JOBS`: Controls the number of simultaneous video processing tasks (default: 5).

### Processing Workflow
- **yt-dlp Optimization:** Uses Deno as the JavaScript runtime to solve YouTube's challenges and enable full-speed downloads.
- Most video processing tasks are long-running and executed as **FastAPI BackgroundTasks**.
- A job-based system uses UUIDs to track status, results, and local artifacts.
- Temporary files are stored in `uploads/` and `output/`, with automatic cleanup logic.

### Security & Optimization
- **Non-Root Execution:** Both frontend and backend containers run as non-root users.
- **Layer Caching:** Dockerfiles are optimized to maximize build speed.
- **Healthchecks:** The backend includes a Docker healthcheck to monitor API availability.
- **Networking:** Services communicate over an isolated `clippyme-net` network.
