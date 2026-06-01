---
source_url: https://github.com/bmezaris/RetargetVid
author: bmezaris
topic: video-reframing
---

# RetargetVid / SmartVidCrop (bmezaris)

Video dataset + code for changing a video's aspect ratio (smart-cropping / retargeting). From two papers: IEEE ICIP 2021 and IEEE ISM 2021.

## Core technique
Visual-saliency-driven cropping with "filtering-through-clustering" to pick the primary focus region among multiple salient areas, then temporally smooth the crop window.

## Models & algorithms
- Saliency detection: Unisal.
- Shot/transition detection: TransNet.
- Clustering for focus selection: HDBSCAN.
- Temporal smoothing: Savitzky-Golay filter (ISM 2021, replaced LOESS).
- Focus-stability mechanism rejecting sudden focus changes (ISM 2021).

## Dependencies
TensorFlow 1.14, PyTorch 1.7.1, OpenCV 4.2.0, SciPy 1.5.1, hdbscan 0.8.26, scikit-learn 0.24.1, FFmpeg, ImUtils. Bundles Unisal + TransNet in 3rd_party_libs.

## Dataset (RetargetVid)
200 videos from DHF1k (16:9), annotated by 6 subjects. 2400 annotation files (200 videos × 2 target ratios × 6 annotators). Extreme target ratios 1:3 and 3:1.

## Pipeline
1. Saliency map generation.
2. Spatial subsampling (ISM 2021).
3. Filtering-through-clustering on salient regions.
4. Per-frame crop window selection.
5. Temporal smoothing with stability filtering.
6. Optional quality assessment + padding fallback.

## I/O
Input: video of any aspect ratio. Output: per-frame crop window coords (top, left, bottom, right) + retargeted video.

## Results
ICIP 2021: 49.9% IoU (1:3), 71.4% IoU (3:1) at ~19-20% real-time. ISM 2021: 52.9% IoU (1:3), 75.3% IoU (3:1) at ~13-14% real-time.

## Papers
- Apostolidis & Mezaris (2021), "A fast smart-cropping method and dataset for video retargeting," IEEE ICIP.
- Apostolidis & Mezaris (2021), "A Web Service for Video Smart-Cropping," IEEE ISM.

Saliency+clustering is an alternative to ClippyMe's face/MAR active-speaker approach — useful where there is no speaking face to track.
