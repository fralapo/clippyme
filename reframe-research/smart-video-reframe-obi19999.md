---
source_url: https://github.com/obi19999/smart-video-reframe
author: obi19999
topic: video-reframing
---

# smart-video-reframe (obi19999)

Auto-reframe videos for mobile using AI face tracking and scene analysis — optimal framing for TikTok and Reels.

## Core technique
Landscape → vertical 9:16 using AI face detection + scene analysis to keep subjects framed; continuous crop/pan adjustment through the video.

## Models & libraries
- YOLOv8 — face detection and tracking.
- OpenCV — video processing.
- FFmpeg — encode/decode, format conversion. Python 3.7+.

## Pipeline
1. Load landscape video.
2. AI face detection across frames.
3. Scene analysis for important content.
4. Compute optimal vertical framing.
5. Process with adjusted crop/pan.
6. Output reframed vertical video.

## I/O
Input: MP4/AVI/MOV (landscape). Output: 9:16 mobile-optimized video.

## Design decisions
- Desktop-only GUI for non-technical users.
- User-adjustable detection sensitivity.
- Batch processing, cross-platform (Windows/macOS/Linux).

Same core idea as ClippyMe (face-tracked crop/pan + scene analysis) but YOLO-face based rather than MediaPipe MAR active-speaker scoring.
