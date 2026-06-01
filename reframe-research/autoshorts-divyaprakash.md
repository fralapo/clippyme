---
source_url: https://github.com/divyaprakash0426/autoshorts
author: divyaprakash0426
topic: viral-shorts-pipeline
---

# autoshorts (divyaprakash0426)

Generate viral-ready vertical short clips from long-form gameplay footage using AI scene analysis, GPU-accelerated rendering, and optional AI voiceovers.

## Core technique
AI-powered scene detection finds engaging gameplay moments, then crops/renders/enhances them for vertical distribution.

## AI scene analysis (multi-provider)
- OpenAI / Gemini APIs — context-aware classification across 7 semantic types.
- Gemini Deep Analysis — full-video upload for holistic context.
- Local mode — heuristic-only scoring, no API.
- Scene categories: action, funny, clutch, wtf, epic_fail, hype, skill.

## GPU rendering
NVIDIA NVENC encoding (libx264 CPU fallback); CUDA via decord + cupy; PyTorch motion estimation/filtering.

## Models & dependencies
- Qwen3-TTS 1.7B-VoiceDesign — voice generation from natural-language descriptions.
- OpenAI Whisper — speech transcription.
- decord — GPU video decode.
- PyCaps — styled subtitle rendering.
- FFmpeg 4.4.2.

## Pipeline
1. Ingest video + frame sampling.
2. GPU audio analysis (RMS, spectral flux).
3. Motion detection + scene boundaries.
4. AI semantic classification of candidate clips.
5. Rank by composite score (audio 60% + video 40%).
6. Subtitle generation (ASR or AI captions).
7. Optional TTS voiceover with dynamic voice design.
8. Hardware-accelerated render + aspect-ratio conversion.
9. Output clips.

## I/O
Input: long gameplay videos in `gameplay/`. Output: 9:16 MP4 clips + subtitle JSON + render logs.

## Key concepts
Semantic tagging drives style-adaptive captions; graceful fallback when components unavailable; smart cropping with optional blurred background for non-vertical source.

Strong parallel to ClippyMe's viral-moment detection + compose pipeline, but gameplay-specialized and adds TTS voiceover.
