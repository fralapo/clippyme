# GEMINI.md - OpenShorts.app Project Context

## Project Overview
**OpenShorts.app** is a comprehensive, self-hosted AI video platform designed to automate the creation of short-form content. It provides a suite of tools to transform long-form videos into viral clips, generate AI-powered UGC marketing videos, and manage YouTube metadata.

### Core Tools
1.  **Clip Generator:** Converts YouTube URLs or local uploads into 9:16 vertical shorts. It uses AI to detect viral moments, transcribes audio, and performs smart reframing with face tracking.
2.  **AI Shorts (UGC):** Generates marketing videos from a website URL or description. The pipeline includes web research, scriptwriting, AI actor generation, voiceover, talking-head video generation, and final composition.
3.  **YouTube Studio:** An AI toolkit for generating viral titles, descriptions, and thumbnails with custom face overlays, including direct publishing to social platforms.

### Architecture
- **Frontend:** React 18, Vite 4, Tailwind CSS. Located in the `dashboard/` directory.
- **Backend:** FastAPI (Python 3.11). Main entry point is `app.py`.
- **Processing Engine:**
    - `main.py`: Orchestrates the Clip Generator pipeline (transcription, scene detection, AI clipping).
    - `saasshorts.py`: Orchestrates the AI Shorts/UGC pipeline.
    - `editor.py`: Core FFmpeg-based video editing, cropping, and effects logic.
    - `subtitles.py`: Subtitle generation and styling using `.ass` templates.
    - `s3_uploader.py`: Integration with AWS S3 for artifact storage and public gallery hosting.
- **Infrastructure:** Docker-based deployment with a job-based background processing queue.

## Key Technologies
- **AI Models & APIs:**
    - **Google Gemini (3.0 Flash/Pro):** Used for viral moment detection, scriptwriting, and web research.
    - **fal.ai:** Hosts various models for image/video generation (Flux, Kling, Hailuo, VEED).
    - **ElevenLabs:** Text-to-Speech and voice cloning.
    - **faster-whisper:** Local/high-performance speech-to-text.
    - **YOLOv8 & MediaPipe:** Subject tracking and face detection for smart reframing.
- **Video/Media Tools:** FFmpeg, `yt-dlp`, `PySceneDetect`.
- **Infrastructure:** AWS S3, Docker, FastAPI, React.

## Building and Running

### Using Docker (Recommended)
1.  Clone the repository and copy `.env.example` to `.env`.
2.  Run the application:
    ```bash
    docker compose up --build
    ```
3.  Access the dashboard at `http://localhost:5175`.

### Manual Setup (Development)
**Backend:**
1.  Install dependencies: `pip install -r requirements.txt`
2.  Ensure FFmpeg is installed on your system.
3.  Start the server: `uvicorn app:app --reload --port 8000`

**Frontend:**
1.  Navigate to the dashboard: `cd dashboard`
2.  Install dependencies: `npm install`
3.  Start the development server: `npm run dev`

## Development Conventions

### API Key Management
- API keys (Gemini, fal.ai, ElevenLabs, Upload-Post) are **not stored on the server**.
- They are managed client-side (typically in `localStorage`) and sent to the backend via headers for each request.

### Environment Variables
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`: Required for S3 storage.
- `AWS_S3_BUCKET`: Private bucket for processing clips.
- `AWS_S3_PUBLIC_BUCKET`: Public bucket for the gallery and avatars.
- `MAX_CONCURRENT_JOBS`: Controls the number of simultaneous video processing tasks.

### Processing Workflow
- Most video processing tasks are long-running and executed as **FastAPI BackgroundTasks**.
- A job-based system uses `job_id` (UUID) to track status, results, and artifacts.
- Temporary files are stored in `uploads/` and `output/`, with automatic cleanup logic in `app.py`.

### Code Style
- **Python:** Standard PEP 8, using `asyncio` for I/O bound tasks and `subprocess` for FFmpeg operations.
- **Frontend:** Modern React with functional components and hooks. Tailwind for styling.
- **Video Editing:** Logic is heavily centered around FFmpeg command construction in `editor.py`.
