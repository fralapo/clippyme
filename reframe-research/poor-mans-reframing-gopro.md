---
source_url: https://pacavaca.medium.com/poor-mans-intelligent-reframing-for-gopro-videos-c9bb489512db
author: Maxim Leonovich
topic: video-reframing
---

# Poor man's intelligent reframing for GoPro videos (Maxim Leonovich)

Automated subject tracking + dynamic reframing to center a detected subject, turning wide-angle GoPro footage into vertical Instagram content while keeping quality.

## ML components
- Object detection: YOLOv8 (people, class_id == 0).
- Multi-object tracking: DeepSort with a CLIP embedder for feature extraction (minimizes identity switches).

## Libraries
- OpenCV (frame read), imageio (video write).
- YOLOv8, DeepSort, OpenAI CLIP.
- FFmpeg via ffmpeg-python. Python 3.11.

## Algorithm — two stages
Stage 1 (tracking): read frames (skip every other for speed) → YOLOv8 detect people → update DeepSort tracks with CLIP embeddings → compute track durations → heuristics (drop bottom 80% of tracks by duration; skip reframing if >8 people; pick longest-duration track as subject) → save subject positions to pickle.
Stage 2 (reframing): load tracking data → per frame ease the crop window toward subject → on lost subject, hold 3s then drift to center → crop to 9:16 → write via imageio → extract original audio with FFmpeg → mux video + audio.

## Key concepts
- Easing/damping (`damping_factor=0.1`) for smooth, non-jittery camera motion.
- Heuristic subject selection: longest track present in the current frame.
- Two-stage design separates expensive tracking from cheap iterative reframing tuning.

## I/O
Input: GoPro video (16:9, 8:7, etc.). Output: 9:16 with original audio preserved.

## Trade-offs
Speed vs accuracy (every-other-frame); CLIP slow on Apple Silicon; heuristic (not ML) subject classification; quality loss on 360-cam crops.

The damping/easing camera and "hold-then-drift-to-center on lost subject" logic directly parallel ClippyMe's SmoothedCameraman; the two-stage (track then render) split mirrors ClippyMe's source-slice preservation for post-hoc reframe.
