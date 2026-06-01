---
source_url: https://github.com/leke-adewa/short-video-maker
author: leke-adewa
topic: viral-shorts-pipeline
---

# short-video-maker (leke-adewa)

Create short vertical videos for TikTok, YouTube Shorts, Instagram Reels using AI — fully automated pipeline with traceability.

## Core technique
AI-driven assembly of short vertical (9:16) videos from supplied assets, optimized per platform.

## Models & dependencies
- Python 3.7+, pip.
- FFmpeg for video processing.
- Gemini API and ChatGPT integrations (per repo topics).
- requirements.txt for the rest.

## Pipeline
1. Asset preparation (images, audio, media).
2. Run script with input files.
3. Generate video with customizable params.
4. Output file.

## Traceability
README emphasizes a "fully automated pipeline with traceability," though specific mechanisms aren't detailed.

## I/O
Inputs: image/audio files, CLI-configurable. Outputs: MP4. Params: duration (s), aspect ratio (default 9:16), input/output paths.

## Key concepts
Platform-specific optimization; automation of repetitive production; MIT-licensed, community contributions.

Asset-assembly approach (compose from images/audio) rather than reframing existing footage — complements the crop/track family.
