# GEMINI.md - OpenShorts.app Project Context

## Project Overview
**OpenShorts.app** is a comprehensive, self-hosted AI video platform designed to automate the creation of short-form content. It provides a suite of tools to transform long-form videos into viral clips, generate AI-powered UGC marketing videos, and manage YouTube metadata.

### Core Tools
1.  **Clip Generator:** Converts YouTube URLs or local uploads into 9:16 vertical shorts. It uses AI to detect viral moments, transcribes audio, and performs smart reframing with face tracking.
2.  **AI Shorts (UGC):** Generates marketing videos from a website URL or description. The pipeline includes web research, scriptwriting, AI actor generation, voiceover, talking-head video generation, and final composition.
3.  **YouTube Studio:** An AI toolkit for generating viral titles, descriptions, and thumbnails with custom face overlays, including direct publishing to social platforms.

### Architecture
- **Frontend:** React 18, Vite 4, Tailwind CSS. Located in the `dashboard/` directory. Runs as a non-root `node` user in Docker for improved security.
- **Backend:** FastAPI (Python 3.11). Main entry point is `app.py`. Runs as a non-root `appuser` in Docker.
- **Processing Engine:**
    - `main.py`: Orchestrates the Clip Generator pipeline (transcription, scene detection, AI clipping). Now uses Deno for YouTube JS challenges.
    - `saasshorts.py`: Orchestrates the AI Shorts/UGC pipeline.
    - `editor.py`: Core FFmpeg-based video editing, cropping, and effects logic.
    - `subtitles.py`: Subtitle generation and styling using `.ass` templates.
    - `s3_uploader.py`: Integration with AWS S3 for artifact storage and public gallery hosting.
- **Infrastructure:** Docker-based deployment with a job-based background processing queue. Includes a custom bridge network (`clippyme-net`) for service isolation and a persistent `config.json` for dynamic API key management.

## Key Technologies
- **AI Models & APIs:**
    - **Google Gemini (3.0 Flash/Pro):** Used for viral moment detection, scriptwriting, and web research.
    - **fal.ai:** Hosts various models for image/video generation (Flux, Kling, Hailuo, VEED).
    - **ElevenLabs:** Text-to-Speech, voice cloning, and AI dubbing.
    - **faster-whisper:** Local/high-performance speech-to-text.
    - **YOLOv8 & MediaPipe:** Subject tracking and face detection for smart reframing.
- **Video/Media Tools:** FFmpeg, `yt-dlp` (with Deno runtime for JS challenges), `PySceneDetect`.
- **Infrastructure:** AWS S3, Docker, FastAPI, React.

## Building and Running

### Using Docker (Recommended)
1.  Clone the repository and copy `.env.example` to `.env` (optional, as keys can be set via Dashboard).
2.  Run the application:
    ```bash
    docker compose up --build
    ```
3.  Access the dashboard at `http://localhost:5175`.
4.  Configure your API keys directly from the "API Configuration" section in the Dashboard. These are persisted in `config.json`.

## Development Conventions

### API Key Management
- API keys can be managed via the Dashboard or environment variables.
- **Persistent Configuration:** The system uses `config.json` (mounted as a Docker volume) to store keys set via the UI. This file takes precedence over `.env`.
- Keys are sent to the backend and updated in the process environment in real-time.

### Environment Variables
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`: Required for S3 storage.
- `AWS_S3_BUCKET`: Private bucket for processing clips.
- `AWS_S3_PUBLIC_BUCKET`: Public bucket for the gallery and avatars.
- `MAX_CONCURRENT_JOBS`: Controls the number of simultaneous video processing tasks (default: 5).

### Processing Workflow
- **yt-dlp Optimization:** Uses Deno as the JavaScript runtime to solve YouTube's `n` challenges and avoid throttled speeds. Automatic updates are enabled via `remote_components`.
- Most video processing tasks are long-running and executed as **FastAPI BackgroundTasks**.
- A job-based system uses `job_id` (UUID) to track status, results, and artifacts.
- Temporary files are stored in `uploads/` and `output/`, with automatic cleanup logic in `app.py`.

### Security & Optimization
- **Non-Root Execution:** Both frontend and backend containers run as non-root users.
- **Layer Caching:** Dockerfiles are optimized to install dependencies and create users before copying source code.
- **Healthchecks:** The backend includes a Docker healthcheck to monitor API availability.
- **Networking:** Services communicate over an isolated `clippyme-net` network.
