---
source_url: https://github.com/keplerlab/katna
author: keplerlab
topic: keyframe-and-crop
---

# Katna (keplerlab)

Tool for automating video key-frame extraction, video compression, and image auto-crop / resize.

## Core techniques
- Keyframe extraction: frame differences in LUV colorspace; brightness-score filter; entropy/contrast filter; K-Means clustering of frames by image histogram; Laplacian variance (blur detection) to pick the best frame.
- Image smart-crop: detect edge + saliency + face features, score candidate crops relative to features, reject low-quality crops.
- Smart resize: detect aspect-ratio mismatch and crop before resizing to avoid skew.

## Models / libraries
- OpenCV (contrib for saliency).
- FFmpeg (compression/processing).
- Google MediaPipe / Autoflip (experimental video smart resize).
- Python 3.x with multiprocessing.

## I/O
Inputs: video (.mp4/.mov/.avi), images (.jpg/.png/.jpeg). Outputs: extracted keyframes, compressed video, cropped/resized images.

## Key concepts
- Keyframes = compact representative summary frames.
- Adjustable down-sampling for large images (>2000×2000).
- Extensible Writer framework (v0.9.0+).

Laplacian-variance best-frame selection mirrors ClippyMe's cover-frame scoring; Autoflip is Google's saliency reframing engine. Keyframe selection is reusable for cover/thumbnail picking.
