# 🚀 Clippyme

✂️ High-performance AI Clip Generator focused on viral 9:16 shorts. Streamlined fork of OpenShorts.

## Features
- **Clip Generator**: Turn long YouTube videos or local uploads into viral-ready 9:16 shorts for TikTok, Instagram Reels, and YouTube Shorts.
- **Viral Moment Detection**: Google Gemini 3.0 Flash analyzes transcripts and scene boundaries to detect high-potential moments.
- **Smart 9:16 Cropping**: AI reframing with face tracking and blurred background modes.
- **Auto Subtitles**: faster-whisper with word-level timestamps.
- **Cookies.txt Support**: Easily upload a `cookies.txt` file via the dashboard to bypass YouTube restrictions during `yt-dlp` downloads.

## Setup and Running

1. Clone this repository.
2. Copy `.env.example` to `.env` and set up your variables.
3. Start using Docker:
   ```bash
   docker compose up --build
   ```
4. Access the dashboard at `http://localhost:5175`.
