---
source_url: https://github.com/paulpierre/autocrop
author: paulpierre
topic: video-reframing
---

# autocrop (paulpierre)

Automatically crop a video clip within another video clip — content-aware cropping that detects content surrounded by uniform background and snaps to a standard aspect ratio.

## Core technique
Traditional computer vision (no deep learning). Detects uniform background regions, finds the main content boundary, classifies orientation, then crops to the nearest standard aspect ratio.

## Libraries / dependencies
- OpenCV (cv2) — frame analysis, image processing.
- NumPy — numerical computation.
- FFmpeg — encode/decode and crop. Python 3.9+.

## Pipeline
1. Randomly sample frames from the video.
2. Detect uniform background color.
3. Locate main content boundaries.
4. Classify orientation (portrait / landscape / square).
5. Snap crop area to closest standard ratio (9:16, 16:9, 1:1).
6. Crop via FFmpeg.

## I/O
Input: MP4. Output: cropped MP4 with optional audio replacement/silencing. Batch processing supported. CLI + Python library.

## Notable
- Best when there is clear content/background distinction (Shorts/Reels with branding clutter).
- No face/person tracking — purely background-vs-content geometry.
- Acknowledged limitation: results vary on complex scenes.
