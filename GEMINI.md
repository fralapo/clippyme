# GEMINI.md - ClippyMe Project Context

## Project Overview
**ClippyMe** is a high-performance, self-hosted AI video platform designed to automate the creation of short-form content. It specializes in transforming long-form videos (from YouTube or local uploads) into viral 9:16 vertical clips using AI-driven moment detection, smart reframing, and automated subtitling.

### Core Tools
1.  **Clip Generator:** Converts YouTube URLs or local uploads into vertical shorts. It uses Google Gemini to detect viral moments, faster-whisper for transcription, and performs smart reframing with subject tracking.
2.  **AI Editor & Subtitles:** Provides automated cropping logic and dynamic subtitle generation with a real-time preview and customizable styles.

### Architecture
- **Frontend:** React 18, Vite 4, Tailwind CSS. Features a "Hyper-Dark" pro-tool aesthetic with glassmorphism and real-time telemetry feeds. Runs as a non-root `node` user in Docker.
- **Backend:** FastAPI (Python 3.11). Main entry point is `app.py`. Orchestrates long-running tasks via an asynchronous job queue. Runs as a non-root `appuser` in Docker.
- **Processing Engine:**
    - `main.py`: Orchestrates the pipeline (transcription, scene detection, AI clipping). Uses Deno for YouTube JS challenges. Supports **Auto-Adaptive Hardware Acceleration** (CUDA/CPU).
    - `editor.py`: Core FFmpeg-based video editing and smart reframing logic. Uses dynamic Gemini model selection.
    - `subtitles.py`: Automated subtitle generation and styling.
- **Infrastructure:** Docker-based deployment with a persistent `data/config.json` for dynamic API key and model management. Isolated service communication via `clippyme-net`.

## Key Technologies
- **AI Models & APIs:**
    - **Google Gemini (2.5 Flash Recommended):** Used for viral moment detection and context-aware editing. Supports dynamic model switching (2.5 Pro, 2.5 Flash-Lite, etc.).
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
3.  Configure your Gemini API key and select your preferred model from the "Settings" section.

### Hardware Acceleration (Optional)
To enable GPU acceleration for 5-10x faster processing:
- Install [NVIDIA Drivers](https://www.nvidia.com/drivers).
- Install [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
- The system automatically detects CUDA and switches from CPU (INT8) to GPU (FP16) mode.

## Development Conventions

### API Key & Model Management
- **Dashboard Control:** API keys and models are managed entirely via the UI.
- **Dynamic Fetching:** The system fetches the latest Gemini models directly from Google once a valid key is provided.
- **Persistence:** Settings are stored in `data/config.json` (mounted as a Docker volume) and updated in the process environment in real-time.

### Processing Workflow
- **yt-dlp Optimization:** Uses Deno as the JavaScript runtime to bypass YouTube bot detection and enable full-speed downloads.
- **Smart Hardware Switching:** The engine detects hardware capabilities at runtime for optimal performance.
- **Job Lifecycle:** Tasks are executed as background processes. Temporary files are stored in `uploads/` and `output/` with automatic cleanup logic.

### Security & Optimization
- **Non-Root Execution:** All containers run as non-root users for maximum security.
- **Strict Validation:** Backend implements strict regex validation for `job_id` to prevent path traversal.
- **API Safety:** Keys are masked in the UI and never exposed fully in logs or API responses.
- **Build Efficiency:** Optimized `.dockerignore` prevents large cache uploads, ensuring fast build times.
- **Privacy:** The `data/` directory is strictly ignored by Git to prevent accidental leakage of credentials.
