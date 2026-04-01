# GEMINI.md - ClippyMe Project Context

## Project Overview
**ClippyMe** is a self-hosted AI video platform designed to automate the creation of short-form content. It specializes in transforming long-form videos (from YouTube or local uploads) into viral 9:16 vertical clips using AI-driven moment detection and smart reframing.

### Core Tools
1.  **Clip Generator:** Converts YouTube URLs or local uploads into vertical shorts. It uses AI to detect viral moments, transcribes audio, and performs smart reframing with subject tracking.
2.  **AI Editor & Subtitles:** Provides automated cropping logic and dynamic subtitle generation with customizable styles to enhance clip engagement.

### Architecture
- **Frontend:** React 18, Vite 4, Tailwind CSS. Located in the `dashboard/` directory. Runs as a non-root `node` user in Docker.
- **Backend:** FastAPI (Python 3.11). Main entry point is `app.py`. Runs as a non-root `appuser` in Docker.
- **Processing Engine:**
    - `main.py`: Orchestrates the pipeline (transcription, scene detection, AI clipping). Uses Deno for YouTube JS challenges. Supports **Auto-Adaptive Hardware Acceleration** (CUDA/CPU).
    - `editor.py`: Core FFmpeg-based video editing, cropping, and smart reframing logic.
    - `subtitles.py`: Automated subtitle generation and styling.
- **Infrastructure:** Docker-based deployment with a job-based background processing queue. Includes a custom bridge network (`clippyme-net`) for service isolation and a persistent `data/config.json` for dynamic API key management.

## Key Technologies
- **AI Models & APIs:**
    - **Google Gemini (1.5 Flash/Pro):** Used for viral moment detection and editing context analysis.
    - **faster-whisper:** Local/high-performance speech-to-text for transcription. (Accelerated via CUDA if available).
    - **YOLOv8 & MediaPipe:** Subject tracking and face detection for smart 9:16 reframing. (Accelerated via CUDA if available).
- **Video/Media Tools:** FFmpeg, `yt-dlp` (with Deno runtime for JS challenges), `PySceneDetect`.
- **Infrastructure:** Docker, FastAPI, React.

## Building and Running

### Using Docker (Recommended)
1.  Run the application:
    ```bash
    docker compose up --build
    ```
2.  Access the dashboard at `http://localhost:5175`.
3.  Configure your API keys directly from the "Settings" section in the Dashboard. These are persisted in `data/config.json`.

### Hardware Acceleration (Optional)
To enable GPU acceleration for 5-10x faster processing:
- Install [NVIDIA Drivers](https://www.nvidia.com/drivers).
- Install [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
- The system will automatically detect the GPU and switch from CPU (INT8) to GPU (FP16) mode.

## Development Conventions

### API Key Management
- API keys are managed via the Dashboard.
- **Persistent Configuration:** The system uses `data/config.json` (mounted as a Docker volume) to store keys. 
- Keys are updated in the process environment in real-time for all new jobs.

### Environment Variables
- `MAX_CONCURRENT_JOBS`: Controls the number of simultaneous video processing tasks (default: 5).

### Processing Workflow
- **yt-dlp Optimization:** Uses Deno as the JavaScript runtime to solve YouTube's challenges and enable full-speed downloads.
- **Smart Hardware Switching:** The engine detects `torch.cuda.is_available()` at runtime and configures Whisper and YOLOv8 for optimal performance on the specific host hardware.
- Temporary files are stored in `uploads/` and `output/`, with automatic cleanup logic.

### Security & Optimization
- **Non-Root Execution:** Both frontend and backend containers run as non-root users.
- **Layer Caching:** Dockerfiles are optimized to maximize build speed.
- **Healthchecks:** The backend includes a Docker healthcheck to monitor API availability.
- **Privacy:** `data/` directory is ignored by Git to prevent accidental leakage of API keys.
