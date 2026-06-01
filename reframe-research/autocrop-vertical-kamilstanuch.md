---
source_url: https://github.com/kamilstanuch/Autocrop-vertical
author: kamilstanuch
topic: video-reframing
---

# AutoCrop-Vertical (kamilstanuch)

Smart video converter using YOLOv8 and FFmpeg to convert horizontal video to vertical 9:16 for social media.

## Core technique
Converts landscape to portrait by analyzing content scene-by-scene, then applying one of two per-scene strategies: TRACK (crop tightly on detected subject) or LETTERBOX (black bars, preserve full frame).

## Models & detection
- YOLOv8 nano (Ultralytics) for fast person detection.
- Haar Cascade (OpenCV) as a face-detection fallback.
- Model weights auto-download on first run.

## Libraries / dependencies
- PySceneDetect — scene boundary detection.
- Ultralytics YOLOv8 — person detection.
- OpenCV — frame manipulation, face detection, video property reading.
- FFmpeg / ffprobe — encoding, audio extraction, stream analysis.
- tqdm. Python 3.8+.

## Pipeline
1. Normalize variable frame rate (VFR) to constant rate.
2. PySceneDetect finds scene boundaries (tunable frame-skip).
3. YOLOv8 analyzes the middle frame of each scene.
4. Rules-based TRACK vs LETTERBOX decision per scene.
5. OpenCV processes every frame with the scene strategy, piped to FFmpeg.
6. Audio extracted separately with start-time offset correction, then merged.

## I/O
Input: any video (MP4, MKV). Output: MP4 at configurable aspect ratio (default 9:16; 4:5, 1:1, custom). Quality presets: fast / balanced / high (CRF mapping).

## Notable design decisions
- Frame-accurate processing using exact frame numbers (not timestamps) to prevent scene-boundary drift.
- Hardware encoders: VideoToolbox (macOS), NVENC (NVIDIA), with automatic fallback.
- `--frame-skip` / `--downscale` speed-vs-accuracy tuning.
- `--plan-only` dry-run previews decisions without encoding.

Closely mirrors the ClippyMe reframe design (scene detection → per-scene TRACK/letterbox strategy → frame-accurate FFmpeg pipe).
