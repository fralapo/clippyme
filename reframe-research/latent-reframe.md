---
source_url: https://latent-reframe.github.io
author: Latent-Reframe authors
topic: diffusion-camera-control
---

# Latent-Reframe

Enabling camera control for video diffusion models without training.

## Core method
Adds camera-pose control to pre-trained video diffusion models without fine-tuning — operates at the sampling/inference stage, not via training data.

## Key innovation
Uses time-aware point clouds to reframe the latent codes of video frames, aligning them with an input camera trajectory. Then latent-code inpainting + harmonization refine the latent space for high-quality output.

## Why no training
Works at inference time instead of fine-tuning on paired video-camera datasets. Preserves the original model distribution and avoids retraining cost.

## Technical components
- Latent manipulation to match camera movement.
- Time-aware point-cloud processing for spatio-temporal alignment.
- Inpainting + harmonization for latent consistency.

## Results
Comparable or better than training-based methods (MotionCtrl, CameraCtrl); rotational + translational control; works with EasyAnimate, VideoCrafter2; robust across visual styles.

Fundamentally different paradigm from crop-based reframing: it generates/controls camera motion in a diffusion model's latent space rather than cropping real footage. Relevant as a future direction, not a drop-in for ClippyMe's deterministic crop pipeline.
