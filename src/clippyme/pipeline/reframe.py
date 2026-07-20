"""Smart 9:16 reframing — orchestrator (scene analysis, frame strategies, render).

Split into three layers:

* ``reframe_track`` — the pure tracking/camera classes (DetectionSmoother,
  SmoothedCameraman, SpeakerTracker); no cv2/ML imports, host-unit-tested.
* ``reframe_detect`` — the ML-bound detectors (YOLO, MediaPipe face/mesh
  singletons, MAR).
* this module — frame-composition strategies, scene analysis, the streaming
  and global-smooth render loops, and ``process_video_to_vertical``.

The moved names are re-exported here for back-compat (main.py and the
integration tests import them from ``reframe``). The output aspect ratio is an
explicit ``process_video_to_vertical(..., aspect_ratio=)`` parameter — the old
``reframe.ASPECT_RATIO`` cross-module global is gone. Verified against
mediapipe 0.10.14 in the Docker image.
"""
import os
import subprocess
import sys
import time

import cv2
import numpy as np
from tqdm import tqdm

from clippyme.domain.encode import x264_video_args
from clippyme.pipeline.media_probe import (
    audio_sync_seek_args,
    probe_is_variable_frame_rate,
    probe_stream_start_time,
    reconcile_fps,
)
from clippyme.pipeline.reframe_ops import (
    PanSmoother,
    build_smoothed_trajectory,
    centroid_span,
    collapse_scene_targets,
    salient_crop_center,
    weighted_interest_center,
)
from clippyme.pipeline.scene_detection import detect_scenes, get_video_resolution

# Moved pieces, re-exported for back-compat: main.py and the integration tests
# import these names from `reframe` (and monkeypatch them here).
from clippyme.pipeline.reframe_detect import (  # noqa: F401
    _get_face_detection,
    _get_face_mesh,
    _get_yolo_model,
    compute_mouth_aspect_ratio,
    detect_face_candidates,
    detect_person_yolo,
)
from clippyme.pipeline.reframe_track import (  # noqa: F401
    DetectionSmoother,
    SmoothedCameraman,
    SpeakerTracker,
)


# Curated COCO classes that read as a "subject" in faceless B-roll, with a pull
# weight (animals strongest, then vehicles, then commonly-demoed held objects).
# Person is intentionally absent — people are framed by the face/person tracker
# upstream, never by this faceless fallback.
_DEFAULT_OBJECT_WEIGHTS = {
    "dog": 3.0, "cat": 3.0, "horse": 3.0, "bird": 2.5, "cow": 2.5,
    "sheep": 2.5, "elephant": 3.0, "bear": 3.0, "zebra": 2.5, "giraffe": 2.5,
    "car": 2.0, "motorcycle": 2.0, "bicycle": 1.8, "bus": 1.8, "truck": 1.8,
    "boat": 1.8, "airplane": 1.8, "train": 1.8,
    "bottle": 1.5, "cup": 1.5, "wine glass": 1.5, "cell phone": 1.8,
    "laptop": 1.8, "book": 1.3, "handbag": 1.3, "sports ball": 1.5,
}


def _object_weights():
    """Parse REFRAME_OBJECT_WEIGHTS into a ``{coco_class: weight}`` map.

    Empty/unset → ``None`` (feature off → GENERAL path byte-identical). A bare
    truthy flag (``1``/``true``/``default``/``auto``) → the curated defaults. A
    comma list of ``name:weight`` pairs (e.g. ``dog:3,car:2,bottle:1.5``) →
    those overrides. Returns ``None`` if nothing valid parses, so the caller
    falls through to the existing salient/letterbox behaviour.
    """
    raw = (os.getenv("REFRAME_OBJECT_WEIGHTS") or "").strip()
    if not raw:
        return None
    if ":" not in raw:
        if raw.lower() in ("1", "true", "yes", "on", "default", "auto"):
            return dict(_DEFAULT_OBJECT_WEIGHTS)
        return None
    weights = {}
    for pair in raw.split(","):
        name, sep, wv = pair.partition(":")
        if not sep:
            continue
        name = name.strip().lower()
        try:
            w = float(wv.strip())
        except ValueError:
            continue
        if name and w > 0:
            weights[name] = w
    return weights or None


def _weighted_object_general_crop(frame, output_width, output_height, weights=None):
    """Object-aware crop for faceless (GENERAL) scenes — opt-in via
    REFRAME_OBJECT_WEIGHTS.

    ``weights`` overrides the env-derived map (used by the ``object`` reframe
    mode, which forces the curated defaults on regardless of the env flag).

    Reuses the existing lazily-loaded YOLOv8 model (no second network) to detect
    every COCO object in the frame, weights each by ``class_weight * area *
    confidence``, and crops a full-height 9:16 window centred on the weighted
    centroid (``reframe_ops.weighted_interest_center``) so a B-roll subject
    (product, dog, car) stays framed instead of being parked behind the
    letterbox bars. Returns ``None`` on any failure, when the feature is off, or
    when no weighted object is present — the caller then falls through to the
    salient/letterbox path. Person detections are ignored (handled upstream by
    the face/person tracker), so this never competes with talking-head framing.

    The YOLO call here runs the same forward pass the person-fallback already
    uses; only the output class filter differs, so the marginal cost is NMS, not
    a second inference.
    """
    if weights is None:
        weights = _object_weights()
    if not weights:
        return None
    try:
        orig_h, orig_w = frame.shape[:2]
        target_ar = output_width / float(output_height)
        crop_w = int(round(orig_h * target_ar))
        if crop_w < 1 or crop_w >= orig_w:
            return None  # already narrower than target → nothing to crop
        model = _get_yolo_model()
        results = model(frame, verbose=False)  # all classes, single inference
        names = getattr(model, "names", {}) or {}
        boxes_xyw = []
        for result in results:
            for box in result.boxes:
                cls_name = str(names.get(int(box.cls[0]), "")).lower()
                w = weights.get(cls_name)
                if not w:
                    continue
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
                if area <= 0:
                    continue
                conf = float(box.conf[0]) if box.conf is not None else 1.0
                boxes_xyw.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0, w * area * conf))
        center = weighted_interest_center(boxes_xyw)
        if center is None:
            return None
        x1 = int(round(center[0] - crop_w / 2.0))
        x1 = max(0, min(orig_w - crop_w, x1))
        cropped = frame[:, x1:x1 + crop_w]
        if cropped.shape[0] < 1 or cropped.shape[1] < 1:
            return None
        return _resize_to_output(cropped, output_width, output_height)
    except Exception:
        return None


def _salient_general_crop(frame, output_width, output_height):
    """Content-aware crop for faceless (GENERAL) scenes — opt-in via
    REFRAME_SALIENT_GENERAL=1.

    The default GENERAL handling letterboxes a faceless shot (blurred bars +
    fit-to-width), which parks an off-centre B-roll subject behind the bars.
    When enabled, this instead crops a full-height 9:16 window centred on the
    most salient column band — the highest image-gradient energy — via
    ``reframe_ops.salient_crop_center`` (host-tested). Saliency uses a plain
    Sobel gradient (base cv2, no opencv-contrib dependency). Returns ``None`` on
    any failure or when the source is already narrower than the target, so the
    caller transparently falls back to the proven letterbox path.
    """
    try:
        orig_h, orig_w = frame.shape[:2]
        target_ar = output_width / float(output_height)
        crop_w = int(round(orig_h * target_ar))
        if crop_w < 1 or crop_w >= orig_w:
            return None  # nothing to crop horizontally
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        column_energy = np.abs(gx).sum(axis=0) + np.abs(gy).sum(axis=0)  # len == orig_w
        center = salient_crop_center(column_energy, crop_w, orig_w)
        x1 = int(round(center - crop_w / 2.0))
        x1 = max(0, min(orig_w - crop_w, x1))
        cropped = frame[:, x1:x1 + crop_w]
        if cropped.shape[0] < 1 or cropped.shape[1] < 1:
            return None
        return _resize_to_output(cropped, output_width, output_height)
    except Exception:
        return None


def create_general_frame(frame, output_width, output_height, force_object_weights=False):
    """
    Creates a 'General Shot' frame:
    - Background: Blurred zoom of original
    - Foreground: Original video scaled to fit width, centered vertically.

    Opt-in crops for faceless scenes (tried most-specific first, each falling
    through to the next on None):
      1. REFRAME_OBJECT_WEIGHTS — centre on the weighted-object centroid so a
         B-roll subject (product/dog/car) stays framed (_weighted_object_general_crop)
      2. REFRAME_SALIENT_GENERAL=1 — centre on the Sobel-salient column band
         (_salient_general_crop)
    Both default-off, keeping the letterbox path below byte-identical.

    ``force_object_weights=True`` (used by the ``object`` reframe mode) turns the
    object-centroid crop on with the curated default weights regardless of the
    env flag, so element-aware framing is the primary path and the blurred
    letterbox below is only the no-element fallback.
    """
    obj = _weighted_object_general_crop(
        frame, output_width, output_height,
        weights=dict(_DEFAULT_OBJECT_WEIGHTS) if force_object_weights else None,
    )
    if obj is not None:
        return obj

    if os.getenv("REFRAME_SALIENT_GENERAL", "").strip().lower() in ("1", "true", "yes", "on"):
        salient = _salient_general_crop(frame, output_width, output_height)
        if salient is not None:
            return salient

    orig_h, orig_w = frame.shape[:2]

    # 1. Background (Fill Height)
    # Crop center to aspect ratio
    bg_scale = output_height / orig_h
    bg_w = int(orig_w * bg_scale)
    bg_resized = cv2.resize(frame, (bg_w, output_height))
    
    # Crop center of background
    start_x = (bg_w - output_width) // 2
    if start_x < 0: start_x = 0
    background = bg_resized[:, start_x:start_x+output_width]
    if background.shape[1] != output_width:
        background = cv2.resize(background, (output_width, output_height))
        
    # Blur background
    background = cv2.GaussianBlur(background, (51, 51), 0)
    
    # 2. Foreground (Fit Width)
    scale = output_width / orig_w
    fg_h = int(orig_h * scale)
    foreground = cv2.resize(frame, (output_width, fg_h))
    
    # 3. Overlay
    y_offset = (output_height - fg_h) // 2
    
    # Clone background to avoid modifying it
    final_frame = background.copy()
    final_frame[y_offset:y_offset+fg_h, :] = foreground

    return final_frame


# FrameShift face-first reframe weights. Mirror the FrameShift GUI defaults
# (face 1.0, person 0.8, every other COCO class = default 0.5), see
# https://github.com/fralapo/FrameShift. Used by the ``object`` reframe mode,
# which now frames faces/people first instead of being objects-only.
_FRAMESHIFT_FACE_WEIGHT = 1.0
_FRAMESHIFT_PERSON_WEIGHT = 0.8
_FRAMESHIFT_DEFAULT_WEIGHT = 0.5


def _frameshift_weights():
    """Resolve FrameShift class weights, honouring REFRAME_FRAMESHIFT_WEIGHTS.

    Returns ``(face_w, person_w, default_w, extra)`` where ``extra`` maps named
    COCO classes to a per-class override. The env var is a comma list of
    ``name:weight`` pairs; the special names ``face`` / ``person`` / ``default``
    override the three GUI sliders, anything else overrides a single COCO class.
    Empty/unset → the GUI defaults (face 1.0, person 0.8, default 0.5).
    """
    face_w = _FRAMESHIFT_FACE_WEIGHT
    person_w = _FRAMESHIFT_PERSON_WEIGHT
    default_w = _FRAMESHIFT_DEFAULT_WEIGHT
    extra = {}
    raw = (os.getenv("REFRAME_FRAMESHIFT_WEIGHTS") or "").strip()
    for pair in raw.split(","):
        name, sep, wv = pair.partition(":")
        if not sep:
            continue
        name = name.strip().lower()
        try:
            w = float(wv.strip())
        except ValueError:
            continue
        if not name:
            continue
        if name == "face":
            face_w = w
        elif name == "person":
            person_w = w
        elif name == "default":
            default_w = w
        else:
            extra[name] = w
    return face_w, person_w, default_w, extra


def _black_pad_to_output(frame, output_width, output_height):
    """Fit the whole frame inside the output by width and add black bars.

    FrameShift's "Enable Padding → black" mode: nothing is cropped, the source
    is letterboxed into the vertical canvas. Used as the OBJECT-mode fallback so
    a scene with no detectable subject is shown in full on black bars (matching
    the GUI screenshot) rather than blurred/zoomed.
    """
    orig_h, orig_w = frame.shape[:2]
    scale = output_width / float(orig_w)
    fg_h = int(round(orig_h * scale))
    if fg_h % 2 != 0:
        fg_h += 1
    foreground = cv2.resize(frame, (output_width, fg_h))
    canvas = np.zeros((output_height, output_width, 3), dtype=np.uint8)
    if fg_h >= output_height:
        crop_y = (fg_h - output_height) // 2
        canvas[:] = foreground[crop_y:crop_y + output_height, :]
    else:
        y_offset = (output_height - fg_h) // 2
        canvas[y_offset:y_offset + fg_h, :] = foreground
    return canvas


def create_frameshift_frame(frame, output_width, output_height, smoother=None):
    """FrameShift face-first 9:16 reframe — the ``object`` reframe mode.

    Computes a weighted-interest centroid over every detection in the frame —
    faces (weight 1.0), persons (0.8) and every other COCO object (default 0.5),
    matching the FrameShift GUI defaults — each scaled by its pixel area and
    confidence (``reframe_ops.weighted_interest_center``), then crops a
    full-height window of the target aspect ratio centred on that point. A face
    therefore pulls the camera hardest, so a talking head stays framed while
    relevant on-screen objects still bias the crop. Faces use MediaPipe
    FaceDetection; persons + objects reuse the single lazily-loaded YOLOv8 pass.

    Falls back to black-padded letterbox (FrameShift "Enable Padding → black")
    when nothing is detected or the source is already narrower than the target,
    so a faceless/objectless shot is shown in full on black bars rather than
    arbitrarily cropped. Never returns None — always yields a valid output frame.
    """
    try:
        orig_h, orig_w = frame.shape[:2]
        target_ar = output_width / float(output_height)
        crop_w = int(round(orig_h * target_ar))
        face_w, person_w, default_w, extra = _frameshift_weights()

        boxes = []
        if face_w > 0:
            try:
                for cand in detect_face_candidates(frame):
                    x, y, w, h = cand['box']
                    area = max(0, w) * max(0, h)
                    if area > 0:
                        boxes.append((x + w / 2.0, y + h / 2.0, face_w * area))
            except Exception:
                pass

        model = _get_yolo_model()
        names = getattr(model, "names", {}) or {}
        for result in model(frame, verbose=False):
            for box in result.boxes:
                cls_name = str(names.get(int(box.cls[0]), "")).lower()
                if cls_name == "person":
                    w = person_w
                else:
                    w = extra.get(cls_name, default_w)
                if w <= 0:
                    continue
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
                if area <= 0:
                    continue
                conf = float(box.conf[0]) if box.conf is not None else 1.0
                boxes.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0, w * area * conf))

        if crop_w < 1 or crop_w >= orig_w:
            # Source already at/under the target width → black-pad, always.
            return _black_pad_to_output(frame, output_width, output_height)

        center = weighted_interest_center(boxes)
        # Route the raw centroid through the caller's PanSmoother: detections
        # jitter a few px per frame, and cropping straight off them shakes the
        # whole scene. The smoother holds the centre inside a deadband and also
        # bridges detection dropouts (None target → held centre), so a single
        # missed frame doesn't flash the letterbox fallback mid-scene.
        center_x = center[0] if center is not None else None
        if smoother is not None:
            center_x = smoother.smooth(center_x, orig_w)
        if center_x is None:
            # No subject (and no held position) → black-pad.
            return _black_pad_to_output(frame, output_width, output_height)

        x1 = int(round(center_x - crop_w / 2.0))
        x1 = max(0, min(orig_w - crop_w, x1))
        cropped = frame[:, x1:x1 + crop_w]
        if cropped.shape[0] < 1 or cropped.shape[1] < 1:
            return _black_pad_to_output(frame, output_width, output_height)
        return _resize_to_output(cropped, output_width, output_height)
    except Exception:
        return _black_pad_to_output(frame, output_width, output_height)


def analyze_scenes_strategy(video_path, scenes):
    """
    Analyzes each scene to determine framing strategy.

    Strategies (AUTO static-framing policy — the camera never pans within a
    scene; see ``collapse_scene_targets``):
      TRACK   — a SINGLE, near-static subject → locked crop on the face.
      WIDE    — 2+ faces in the scene OR a single subject that MOVES too much to
                hold without panning → a locked, zoomed-out crop that keeps
                everyone/everything in frame with zero camera motion.
      GENERAL — no faces detected → letterbox / element-aware fallback.

    A single moving subject is deliberately demoted from TRACK to WIDE: chasing
    it would force the very camera motion the policy exists to avoid, so instead
    we pull back to a static wide shot. Motion is measured by the primary face's
    normalised centroid travel across the sampled frames
    (``REFRAME_MOTION_WIDE_THRESH``, default 0.12 of the frame).
    """
    cap = cv2.VideoCapture(video_path)
    strategies = []

    if not cap.isOpened():
        return ['TRACK'] * len(scenes)

    try:
        frame_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1.0
        frame_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1.0
        _mt = (os.getenv("REFRAME_MOTION_WIDE_THRESH") or "").strip()
        motion_thresh = float(_mt) if _mt else 0.12

        for start, end in tqdm(scenes, desc="   Analyzing Scenes"):
            # Sample 7 frames evenly across the scene for a more reliable
            # face-count estimate (was 3 frames). Catches mixed-content scenes
            # where the face count changes mid-scene.
            s_frame = start.get_frames()
            e_frame = end.get_frames()
            # Degenerate scene (shorter than the sampling window, or zero/negative
            # span) → invalid frame indices. Default to GENERAL and skip sampling.
            if e_frame <= s_frame:
                strategies.append('GENERAL')
                continue
            if e_frame - s_frame < 14:
                # Clamp every sample inside [s_frame, e_frame): on a <5-frame
                # scene the unclamped s_frame+2 / e_frame-2 land in the
                # ADJACENT scene and can misclassify this one from a
                # neighbour's content (e.g. a faceless flash-cut read as TRACK
                # because it borrowed the next shot's face).
                frames_to_check = sorted({
                    min(s_frame + 2, e_frame - 1),
                    (s_frame + e_frame) // 2,
                    max(e_frame - 2, s_frame),
                })
            else:
                step = (e_frame - s_frame) // 8
                frames_to_check = [s_frame + step * i for i in range(1, 8)]

            face_counts = []
            primary_centers = []  # centre of the largest face per sampled frame
            for f_idx in frames_to_check:
                cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
                ret, frame = cap.read()
                if not ret:
                    continue
                candidates = detect_face_candidates(frame)
                face_counts.append(len(candidates))
                if candidates:
                    # Largest-area face = the primary subject we'd track.
                    px, py, pw, ph = max(candidates, key=lambda c: c['box'][2] * c['box'][3])['box']
                    primary_centers.append((px + pw / 2.0, py + ph / 2.0))
                else:
                    primary_centers.append(None)

            if not face_counts:
                strategies.append('GENERAL')
                continue

            avg_faces = sum(face_counts) / len(face_counts)
            max_faces = max(face_counts)

            if avg_faces < 0.4:
                strategies.append('GENERAL')
            elif max_faces >= 2 and avg_faces > 1.0:
                # More than one face in the scene → WIDE (locked, zoomed-out).
                strategies.append('WIDE')
            elif centroid_span(primary_centers, frame_w, frame_h) > motion_thresh:
                # Single subject but it roams too far to hold statically → WIDE.
                strategies.append('WIDE')
            else:
                # Single, near-static subject → TRACK (locked crop on the face).
                strategies.append('TRACK')
    finally:
        cap.release()
    return strategies

def select_cover_frame(video_path):
    """
    Auto-select the best frame for a thumbnail/cover image.
    Scores frames by: face presence, sharpness, good exposure.
    Saves as {video_name}_cover.jpg alongside the video.
    """
    cover_path = os.path.splitext(video_path)[0] + "_cover.jpg"
    try:
        cap = cv2.VideoCapture(video_path)
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0 or fps <= 0:
                return None

            # Sample 1 frame per second
            sample_interval = max(1, int(fps))
            best_score = -1
            best_frame = None

            for frame_idx in range(0, total_frames, sample_interval):
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if not ret:
                    continue

                score = 0.0

                # Face detection (reuse existing MediaPipe)
                candidates = detect_face_candidates(frame)
                if candidates:
                    score += 50  # Face present = big bonus

                # Sharpness (Laplacian variance — higher = sharper)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
                score += min(30, laplacian_var / 100 * 30)  # Cap at 30 points

                # Exposure (prefer well-lit, not too dark or blown out)
                mean_brightness = gray.mean()
                if 80 < mean_brightness < 200:
                    score += 20  # Good exposure range
                elif 50 < mean_brightness < 230:
                    score += 10

                if score > best_score:
                    best_score = score
                    best_frame = frame.copy()
        finally:
            cap.release()

        if best_frame is not None:
            cv2.imwrite(cover_path, best_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            print(f"🖼️  Cover frame saved: {os.path.basename(cover_path)} (score: {best_score:.0f})")
            return cover_path

    except Exception as e:
        print(f"⚠️  Cover frame selection failed: {e}")

    return None

def create_disabled_reframe(frame, output_width, output_height):
    """
    Center-crop to 4:3 then add black bars top/bottom to fill 9:16.
    """
    h, w = frame.shape[:2]
    target_ratio = 4 / 3
    current_ratio = w / h
    if current_ratio > target_ratio:
        new_w = int(h * target_ratio)
        x_start = (w - new_w) // 2
        cropped = frame[:, x_start:x_start + new_w]
    else:
        new_h = int(w / target_ratio)
        y_start = (h - new_h) // 2
        cropped = frame[y_start:y_start + new_h, :]

    scale = output_width / cropped.shape[1]
    scaled_w = output_width
    scaled_h = int(cropped.shape[0] * scale)
    if scaled_h % 2 != 0:
        scaled_h += 1
    scaled = cv2.resize(cropped, (scaled_w, scaled_h))

    canvas = np.zeros((output_height, output_width, 3), dtype=np.uint8)
    y_offset = (output_height - scaled_h) // 2
    if y_offset < 0:
        crop_y = (-y_offset)
        canvas[:] = scaled[crop_y:crop_y + output_height, :]
    else:
        canvas[y_offset:y_offset + scaled_h, :] = scaled

    return canvas

def _resize_to_output(img, w, h):
    """Resize a crop to output size with scale-aware interpolation.

    LANCZOS4 when enlarging (the common case — a zoomed crop is smaller than the
    1080-tall vertical output, and Lanczos keeps faces/edges crisp), INTER_AREA
    when shrinking (best downscale filter, avoids moiré). cv2's default bilinear
    softens both. Idea ported from fralapo/FrameShift (lanczos default resize).
    """
    src_h, src_w = img.shape[:2]
    interp = cv2.INTER_AREA if (w * h) < (src_w * src_h) else cv2.INTER_LANCZOS4
    return cv2.resize(img, (w, h), interpolation=interp)


def _reframe_comfort_enabled() -> bool:
    """Comfort (anti-nausea) reframe policy — default ON.

    When on, the renderer uses the two-pass global-smooth path with an AutoFlip
    stationary-first decision and per-scene zoom lock, which removes the
    sustained, variable-velocity camera motion (and breathing zoom) that causes
    motion sickness. Set ``REFRAME_COMFORT=0`` to fall back to the original
    single-pass streaming tracker.
    """
    # Empty-safe: an unset OR empty (`REFRAME_COMFORT=` from docker-compose's
    # `${VAR:-}`) value means "use the default" (on).
    val = (os.getenv("REFRAME_COMFORT") or "").strip().lower()
    if not val:
        return True
    return val in ("1", "true", "yes", "on")


def _render_global_smooth(input_video, ffmpeg_process, cameraman, speaker_tracker,
                          detection_smoother, scene_boundaries, scene_strategies,
                          output_width, output_height, original_width, original_height,
                          total_frames, fps):
    """Two-stage track-then-render reframe (opt-in via REFRAME_GLOBAL_SMOOTH).

    Pass 1 decodes the clip and records the raw per-frame camera target
    (center_x, center_y, zoom) without any online easing. The full trajectory
    is then low-passed per scene segment with a Savitzky-Golay filter
    (``build_smoothed_trajectory``) so the camera follows one globally smooth
    path instead of reacting frame-by-frame. Pass 2 re-decodes and renders each
    frame from the smoothed trajectory. This is ClippyMe's cheap, deterministic
    analogue of smart-reframe's offline Viterbi ``PathSolver``.

    Trades a second decode pass for a markedly smoother result; default-off so
    the proven single-pass streaming path is untouched.
    """
    win = int(round(fps * 0.7))
    if win % 2 == 0:
        win += 1
    win = max(5, win)

    # --- Pass 1: record raw trajectory -------------------------------------
    targets, scene_ids, strategies = [], [], []
    cap = cv2.VideoCapture(input_video)
    frame_number = 0
    current_scene_index = 0
    print("   🔁 Global-smooth pass 1/2: tracking trajectory...")
    try:
        with tqdm(total=total_frames, desc="   Pass 1", file=sys.stdout) as pbar:
            while cap.isOpened():
                # Scene bookkeeping first (needs only frame_number) so we know
                # whether this frame's PIXELS are ever looked at: detection runs
                # on even frames of TRACK/WIDE scenes only. Everything else can
                # cap.grab() — decode without the retrieve+BGR-convert memcpy —
                # which trims a solid chunk of pass-1 cost for free.
                if current_scene_index < len(scene_boundaries):
                    _, end_f = scene_boundaries[current_scene_index]
                    if frame_number >= end_f and current_scene_index < len(scene_boundaries) - 1:
                        current_scene_index += 1
                        # Hard cut: drop identities/histories from the previous
                        # shot. Carrying them across lets a near-positioned face
                        # in the new scene inherit the old active-speaker bonus
                        # + cooldown and be box-averaged with stale frames —
                        # and under comfort mode the polluted early targets
                        # skew the whole scene's collapsed median crop.
                        speaker_tracker.reset(frame_number)
                        detection_smoother.reset()
                strat = scene_strategies[current_scene_index] if current_scene_index < len(scene_strategies) else 'TRACK'
                needs_pixels = strat not in ('DISABLED', 'GENERAL') and frame_number % 2 == 0
                if needs_pixels:
                    ret, frame = cap.read()
                else:
                    ret = cap.grab()
                if not ret:
                    break
                strategies.append(strat)
                scene_ids.append(current_scene_index)
                if strat in ('DISABLED', 'GENERAL'):
                    targets.append(None)
                else:
                    if needs_pixels:
                        candidates = detect_face_candidates(frame)
                        candidates = detection_smoother.smooth(candidates, frame_number)
                        for cand in candidates:
                            cand['mar'] = compute_mouth_aspect_ratio(frame, cand['box'])
                        target_box = speaker_tracker.get_target(candidates, frame_number, original_width)
                        if target_box:
                            cameraman.update_target(target_box)
                        elif strat == 'TRACK':
                            person_box = detect_person_yolo(frame)
                            if person_box:
                                cameraman.update_target(person_box, is_person_box=True)
                    targets.append((cameraman.target_center_x, cameraman.target_center_y, cameraman.target_zoom))
                frame_number += 1
                pbar.update(1)
    finally:
        cap.release()

    # --- Global smoothing pass ---------------------------------------------
    # Global smoother for the pan path: savgol (default) | kalman | l2. The two
    # alternatives (RTS Kalman, L2 convex optimiser) are ported from
    # mfahsold/montage-ai; default stays savgol so behaviour is unchanged unless
    # opted in via REFRAME_GLOBAL_METHOD.
    global_method = os.getenv("REFRAME_GLOBAL_METHOD", "savgol").strip().lower()
    # Comfort mode (default on) biases hard toward a locked/stationary crop and a
    # fixed per-scene zoom — the research-backed anti-nausea policy (continuous
    # tracking + breathing zoom is what causes seasickness, not jitter). The
    # individual env vars still override these comfort defaults when set.
    comfort = _reframe_comfort_enabled()
    # NB: read env vars empty-safe — docker-compose passes these as `VAR=`
    # (empty string) via `${VAR:-}`, and os.getenv(name, default) returns that
    # empty string rather than the default, so a plain float("") would crash.
    # AutoFlip-style per-scene stationary lock. Comfort default 0.30 of the frame
    # dimension (a talking head may drift this far before the camera moves at all);
    # 0.0 = off (no-op) when comfort is disabled.
    _st = (os.getenv("REFRAME_STATIONARY_THRESH") or "").strip()
    stationary_thresh = float(_st) if _st else (0.30 if comfort else 0.0)
    _sc = (os.getenv("REFRAME_SNAP_CENTER") or "").strip()
    snap_center_dist = float(_sc) if _sc else 0.10
    # Per-scene zoom lock — on by default under comfort.
    _zl = (os.getenv("REFRAME_ZOOM_LOCK") or "").strip().lower()
    lock_zoom = (_zl in ("1", "true", "yes", "on")) if _zl else comfort

    # AUTO static-framing policy (default ON): collapse each scene to a single
    # fixed (cx,cy,zoom) so the camera is a locked tripod within every shot —
    # zero pan, zero mid-shot zoom. TRACK locks on the (near-static) face; WIDE
    # locks zoomed-out and centred between the faces / a roaming subject. This is
    # the deterministic end-state of comfort mode; set REFRAME_STATIC_AUTO=0 to
    # fall back to the per-frame Savitzky-Golay smoother (legacy moving-but-eased
    # camera), still A/B-able.
    _static = (os.getenv("REFRAME_STATIC_AUTO") or "").strip().lower()
    static_auto = (_static in ("1", "true", "yes", "on")) if _static else True
    if static_auto:
        smoothed = collapse_scene_targets(
            targets, scene_ids, strategies,
            x_max=original_width, y_max=original_height,
            wide_zoom=1.0, snap_center_dist=snap_center_dist,
        )
    else:
        smoothed = build_smoothed_trajectory(
            targets, scene_ids, window=win, polyorder=2,
            x_max=original_width, y_max=original_height,
            min_zoom=1.0, max_zoom=1.6, method=global_method,
            stationary_threshold=stationary_thresh, snap_center_dist=snap_center_dist,
            lock_zoom=lock_zoom,
        )

    # --- Pass 2: render from the smoothed trajectory -----------------------
    print("   🔁 Global-smooth pass 2/2: rendering...")
    cap = cv2.VideoCapture(input_video)
    frame_number = 0
    # Corrupt/failed-frame resilience — mirror the streaming render loop: a single
    # malformed frame duplicates the last good output instead of aborting pass 2
    # and truncating the clip (ported from kamilstanuch/Autocrop-vertical).
    dropped_frames = 0
    last_output_frame = None
    try:
        with tqdm(total=total_frames, desc="   Pass 2", file=sys.stdout) as pbar:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                try:
                    strat = strategies[frame_number] if frame_number < len(strategies) else 'TRACK'
                    if strat == 'DISABLED':
                        output_frame = create_disabled_reframe(frame, output_width, output_height)
                    elif strat == 'GENERAL':
                        output_frame = create_general_frame(frame, output_width, output_height)
                    else:
                        tgt = smoothed[frame_number] if frame_number < len(smoothed) else None
                        if tgt is None:
                            output_frame = cv2.resize(frame, (output_width, output_height))
                        else:
                            cx, cy, zoom = tgt
                            x1, y1, x2, y2 = cameraman.crop_box_at(cx, cy, zoom)
                            if y2 > y1 and x2 > x1:
                                output_frame = _resize_to_output(frame[y1:y2, x1:x2], output_width, output_height)
                            else:
                                output_frame = cv2.resize(frame, (output_width, output_height))
                    last_output_frame = output_frame
                except Exception:
                    dropped_frames += 1
                    # Surface the FIRST failure unconditionally — a systemic bug
                    # (e.g. a NameError on every frame) otherwise hides entirely
                    # behind the duplicate-last-frame fallback. REFRAME_DEBUG_EXC
                    # adds the next 4 for context.
                    if dropped_frames == 1 or (os.environ.get('REFRAME_DEBUG_EXC') and dropped_frames <= 5):
                        import traceback
                        print(f"   🐛 global-smooth frame {frame_number} failed:", file=sys.stderr)
                        traceback.print_exc()
                    if last_output_frame is not None:
                        output_frame = last_output_frame
                    else:
                        output_frame = np.zeros((output_height, output_width, 3), dtype=np.uint8)
                ffmpeg_process.stdin.write(output_frame.tobytes())
                frame_number += 1
                pbar.update(1)
    finally:
        cap.release()
    if dropped_frames > 0:
        pct = 100.0 * dropped_frames / max(1, total_frames)
        print(f"   ⚠️ {dropped_frames} frame(s) ({pct:.1f}%) failed processing and were duplicated from the previous good frame.")
        if pct >= 25.0:
            print(f"   ❗ High drop rate ({pct:.1f}%) — likely a systemic bug, not isolated corrupt frames. Re-run with REFRAME_DEBUG_EXC=1 for full tracebacks.", file=sys.stderr)


def process_video_to_vertical(input_video, final_output_video, reframe_mode='auto',
                              zoom_end=None, aspect_ratio: float = 9 / 16):
    """
    Core logic to convert horizontal video to vertical using scene detection and Active Speaker Tracking (MediaPipe).

    zoom_end: when set (e.g. 1.05), the Ken Burns 1.0→zoom_end zoompan is
    folded INTO the master encode instead of running as a separate
    apply_subtle_zoom decode+encode afterwards — one generation cheaper per
    clip. Falls back to the legacy post-pass when the container's frame count
    is unreadable (zoompan needs it for the per-frame increment).

    aspect_ratio: output width/height ratio (9/16 vertical default; 1.0 and
    16/9 for square/landscape jobs). Passed explicitly by main.py per job —
    this replaced the old ``reframe.ASPECT_RATIO`` module global.
    """
    # 'object' is the legacy name for the FrameShift face-first 'subject' mode —
    # normalize once here so the rest of this function only ever sees 'subject'.
    if reframe_mode == 'object':
        reframe_mode = 'subject'
    script_start_time = time.time()
    
    # Define temporary file paths based on the output name
    base_name = os.path.splitext(final_output_video)[0]
    temp_video_output = f"{base_name}_temp_video.mp4"
    temp_audio_output = f"{base_name}_temp_audio.aac"
    temp_cfr_input = f"{base_name}_temp_cfr_input.mp4"

    # Clean up previous temp files if they exist
    if os.path.exists(temp_video_output): os.remove(temp_video_output)
    if os.path.exists(temp_audio_output): os.remove(temp_audio_output)
    if os.path.exists(temp_cfr_input): os.remove(temp_cfr_input)
    if os.path.exists(final_output_video): os.remove(final_output_video)

    # --- VFR → CFR pre-normalization (ported from kamilstanuch/Autocrop-vertical) ---
    # The render loop decodes frames with OpenCV and re-emits them at a *fixed*
    # `-r fps`. If the source is variable-frame-rate (phone uploads, some YouTube
    # downloads), its real per-frame timing wanders from the nominal rate, so the
    # fixed-rate output drifts against the stream-copied audio. Detect VFR up front
    # and re-mux to constant frame rate first. This is a no-op for the common case:
    # the normal pipeline feeds already-re-encoded CFR clip slices, so detection
    # returns False and the proven path stays byte-identical. Only the whole-video
    # fallback / standalone --reframe-only on a raw download pays the extra pass.
    if probe_is_variable_frame_rate(input_video):
        print("   ⚠️ Variable frame rate detected — normalizing to constant frame rate first...")
        cfr_cmd = [
            'ffmpeg', '-y', '-i', input_video,
            '-vsync', 'cfr', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-c:a', 'copy', temp_cfr_input,
        ]
        try:
            subprocess.run(cfr_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)
            input_video = temp_cfr_input
            print("   ✅ VFR normalization complete.")
        except subprocess.CalledProcessError:
            # Non-fatal: fall back to the original file (sync may be imperfect, but
            # a failed normalization must never abort the whole clip).
            print("   ⚠️ VFR normalization failed; proceeding with the original file.")
            if os.path.exists(temp_cfr_input):
                os.remove(temp_cfr_input)

    print(f"🎬 Processing clip: {input_video}")
    if reframe_mode == 'disabled':
        print("   🚫 Reframe mode: DISABLED — clip placed inside a 9:16 frame with letterbox (black bars top & bottom).")
        print("      (Scene detection still runs for consistency; face tracking is skipped.)")
    elif reframe_mode == 'subject':
        print("   🧩 Reframe mode: SUBJECT — FrameShift face-first 9:16 crop (faces 1.0 → persons 0.8 → objects 0.5).")
        print("      (Weighted-interest centroid per frame; black-padded letterbox when no subject is detected.)")
    else:
        print("   🎯 Reframe mode: AUTO — face tracking + dynamic 9:16 crop.")
    print("   Step 1: Detecting scenes...")
    scenes, fps = detect_scenes(input_video)

    # fps reconciliation (Autocrop-vertical learning): the frames written below
    # are decoded by OpenCV, so the encoder's -r must match OpenCV's reported rate.
    # PySceneDetect can disagree (e.g. 29.97 vs 30); on a genuine divergence trust
    # the cv2 reader. Within tolerance the detector value is kept → byte-identical.
    _probe_cap = cv2.VideoCapture(input_video)
    _cv2_fps = _probe_cap.get(cv2.CAP_PROP_FPS)
    _probe_total_frames = int(_probe_cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    _probe_cap.release()
    _reconciled_fps = reconcile_fps(_cv2_fps, fps)
    if _reconciled_fps != fps:
        print(f"   ⏱️  fps reconciled: detector={fps:.4f} → cv2 reader={_reconciled_fps:.4f}")
    fps = _reconciled_fps

    if not scenes:
        print("   ❌ No scenes were detected. Using full video as one scene.")
        # If scene detection fails or finds nothing, treat whole video as one scene
        cap = cv2.VideoCapture(input_video)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        from scenedetect import FrameTimecode
        scenes = [(FrameTimecode(0, fps), FrameTimecode(total_frames, fps))]

    print(f"   ✅ Found {len(scenes)} scenes.")

    print("\n   🧠 Step 2: Preparing Active Tracking...")
    original_width, original_height = get_video_resolution(input_video)
    
    OUTPUT_HEIGHT = original_height
    OUTPUT_WIDTH = int(OUTPUT_HEIGHT * aspect_ratio)
    if OUTPUT_WIDTH % 2 != 0:
        OUTPUT_WIDTH += 1

    # Initialize Cameraman
    cameraman = SmoothedCameraman(OUTPUT_WIDTH, OUTPUT_HEIGHT, original_width, original_height,
                                  aspect_ratio=aspect_ratio)
    
    # --- New Strategy: Per-Scene Analysis ---
    if reframe_mode == 'disabled':
        print("\n   🤖 Step 3: Skipping scene analysis (reframe disabled).")
        scene_strategies = ['DISABLED'] * len(scenes)
    elif reframe_mode == 'subject':
        print("\n   🤖 Step 3: Skipping scene analysis (subject mode — every scene is FrameShift face-first cropped).")
        scene_strategies = ['OBJECT'] * len(scenes)
    else:
        print("\n   🤖 Step 3: Analyzing Scenes for Strategy (Single vs Group)...")
        scene_strategies = analyze_scenes_strategy(input_video, scenes)

    print("\n   ✂️ Step 4: Processing video frames...")

    # Ken Burns fold: applying the 1.0→zoom_end zoompan inside THIS encode
    # saves the whole apply_subtle_zoom decode+encode generation per clip.
    # zoompan needs the total frame count for its per-frame increment; when
    # the container lies (count<=0) the legacy post-pass runs instead (below).
    zoom_folded = False
    zoom_vf_args = []
    if zoom_end and float(zoom_end) > 1.0 and _probe_total_frames > 0:
        zpf = (float(zoom_end) - 1.0) / _probe_total_frames
        zoom_vf_args = ['-vf', (
            f"zoompan=z='1+{zpf:.8f}*on'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:fps={fps}"
        )]
        zoom_folded = True
        print(f"   🔍 Ken Burns zoom (1.0→{zoom_end}x) folded into the master encode.")

    command = [
        'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}', '-pix_fmt', 'bgr24',
        '-r', str(fps), '-i', '-',
        *zoom_vf_args,
        # Master generation: this is the first (and most important) encode of the
        # reframed frames — everything downstream re-encodes from it, so it runs
        # at the shared near-visually-lossless CRF (18 / medium) instead of the
        # old CRF 23 that softened the whole chain. pix_fmt yuv420p is forced
        # inside x264_video_args: the raw input is bgr24 and without it libx264
        # may pick yuv444p (rejected by many players/mobile decoders).
        # faststart=False: this is an intermediate file; the final mux stream-
        # copies it, which is where +faststart is applied.
        # -vsync cfr: lock output to a constant frame rate matching `-r`
        # (ported from kamilstanuch/Autocrop-vertical).
        *x264_video_args(faststart=False),
        '-vsync', 'cfr', '-an', temp_video_output
    ]

    ffmpeg_process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    cap = cv2.VideoCapture(input_video)
    stderr_output = ""
    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
        frame_number = 0
        current_scene_index = 0
        # Corrupt/failed-frame resilience (ported from kamilstanuch/Autocrop-vertical):
        # if a single frame raises mid-processing, duplicate the last good output
        # instead of letting the exception abort the whole render (which would
        # truncate the video and desync the full-length stream-copied audio).
        dropped_frames = 0
        last_output_frame = None

        # Pre-calculate scene boundaries
        scene_boundaries = []
        for s_start, s_end in scenes:
            scene_boundaries.append((s_start.get_frames(), s_end.get_frames()))

        # Global tracker for single-person shots
        # Cooldown of 45 frames (~1.5s @ 30fps) protects against rapid back-and-forth
        # switching in WIDE multi-speaker scenes (interview/podcast botta-risposta).
        speaker_tracker = SpeakerTracker(cooldown_frames=45)
        detection_smoother = DetectionSmoother(window_size=5)
        # OBJECT (subject/FrameShift) strategy: hysteresis smoother on the crop
        # centre — without it the raw per-frame centroid shakes every scene.
        frameshift_smoother = PanSmoother()

        # Opt-in two-stage global trajectory smoothing (REFRAME_GLOBAL_SMOOTH).
        # When on, a dedicated track-then-render pass handles all frames and the
        # single-pass streaming loop below is skipped (its `while` short-circuits
        # on `not global_smooth`). Default-off keeps the proven path byte-identical.
        # Global-smooth is a face-tracking pan smoother → only meaningful in AUTO.
        # OBJECT (per-frame element crop) and DISABLED (static) run the streaming
        # loop below.
        global_smooth = (
            (os.getenv("REFRAME_GLOBAL_SMOOTH", "").strip().lower() in ("1", "true", "yes", "on")
             or _reframe_comfort_enabled())
            and reframe_mode == 'auto'
        )
        if global_smooth:
            _render_global_smooth(
                input_video, ffmpeg_process, cameraman,
                speaker_tracker, detection_smoother,
                scene_boundaries, scene_strategies,
                OUTPUT_WIDTH, OUTPUT_HEIGHT,
                original_width, original_height, total_frames, fps,
            )

        with tqdm(total=total_frames, desc="   Processing", file=sys.stdout) as pbar:
            while cap.isOpened() and not global_smooth:
                ret, frame = cap.read()
                if not ret:
                    break

                # Update Scene Index
                if current_scene_index < len(scene_boundaries):
                    start_f, end_f = scene_boundaries[current_scene_index]
                    if frame_number >= end_f and current_scene_index < len(scene_boundaries) - 1:
                        current_scene_index += 1
                        # Hard cut: reset tracker identities so the previous
                        # shot's active-speaker bonus/cooldown and box history
                        # can't bleed onto an unrelated face in the new scene
                        # (the force_snap below only snaps the CAMERA, not the
                        # tracker state).
                        speaker_tracker.reset(frame_number)
                        detection_smoother.reset()
                        # New shot: drop the held FrameShift pan centre so the
                        # first detection of the scene snaps instead of easing
                        # over from the previous shot's framing.
                        frameshift_smoother.reset()
            
                # Determine Strategy for current frame based on scene
                current_strategy = scene_strategies[current_scene_index] if current_scene_index < len(scene_strategies) else 'TRACK'
            
                # Apply Strategy. Guarded so a single malformed frame (bad crop,
                # corrupt decode) duplicates the previous good output rather than
                # aborting the render and truncating the clip.
                try:
                    if current_strategy == 'DISABLED':
                        output_frame = create_disabled_reframe(frame, OUTPUT_WIDTH, OUTPUT_HEIGHT)

                    elif current_strategy == 'OBJECT':
                        # FrameShift face-first crop: weighted-interest centroid
                        # over faces (1.0) → persons (0.8) → objects (0.5), with a
                        # black-padded letterbox fallback when nothing is detected.
                        output_frame = create_frameshift_frame(
                            frame, OUTPUT_WIDTH, OUTPUT_HEIGHT,
                            smoother=frameshift_smoother,
                        )

                    elif current_strategy == 'GENERAL':
                        # No faces detected anywhere in scene → letterbox fallback
                        output_frame = create_general_frame(frame, OUTPUT_WIDTH, OUTPUT_HEIGHT)
                        cameraman.current_center_x = original_width / 2
                        cameraman.target_center_x = original_width / 2
                        cameraman.current_center_y = original_height / 2
                        cameraman.target_center_y = original_height / 2
                        cameraman.current_zoom = 1.0
                        cameraman.target_zoom = 1.0

                    else:
                        # TRACK (single speaker) or WIDE (multi-speaker) — both use the
                        # same active-speaker tracker now. WIDE relies on MAR-variance
                        # to pick whichever face is currently talking, switching
                        # dynamically with cooldown protection.
                        if frame_number % 2 == 0:
                            candidates = detect_face_candidates(frame)
                            candidates = detection_smoother.smooth(candidates, frame_number)
                            for cand in candidates:
                                cand['mar'] = compute_mouth_aspect_ratio(frame, cand['box'])
                            target_box = speaker_tracker.get_target(candidates, frame_number, original_width)
                            if target_box:
                                cameraman.update_target(target_box)
                            elif current_strategy == 'TRACK':
                                # Single-speaker scene: fall back to YOLO body detection
                                person_box = detect_person_yolo(frame)
                                if person_box:
                                    cameraman.update_target(person_box, is_person_box=True)
                            # WIDE: if no face detected this frame, just keep the
                            # cameraman's current target (don't fall back to body
                            # tracking which would jump to a random person).

                        # Snap camera on scene change to avoid panning from previous scene position
                        is_scene_start = (frame_number == scene_boundaries[current_scene_index][0])

                        x1, y1, x2, y2 = cameraman.get_crop_box(force_snap=is_scene_start)

                        # Crop
                        if y2 > y1 and x2 > x1:
                            cropped = frame[y1:y2, x1:x2]
                            output_frame = _resize_to_output(cropped, OUTPUT_WIDTH, OUTPUT_HEIGHT)
                        else:
                            output_frame = cv2.resize(frame, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
                    last_output_frame = output_frame
                except Exception:
                    dropped_frames += 1
                    # First failure always surfaces (see global-smooth guard);
                    # REFRAME_DEBUG_EXC adds the next 4 for context.
                    if dropped_frames == 1 or (os.environ.get('REFRAME_DEBUG_EXC') and dropped_frames <= 5):
                        import traceback
                        print(f"   🐛 frame {frame_number} ({current_strategy}) failed:", file=sys.stderr)
                        traceback.print_exc()
                    if last_output_frame is not None:
                        output_frame = last_output_frame
                    else:
                        output_frame = np.zeros((OUTPUT_HEIGHT, OUTPUT_WIDTH, 3), dtype=np.uint8)

                ffmpeg_process.stdin.write(output_frame.tobytes())
                frame_number += 1
                pbar.update(1)

        if dropped_frames > 0:
            pct = 100.0 * dropped_frames / max(1, total_frames)
            print(f"   ⚠️ {dropped_frames} frame(s) ({pct:.1f}%) failed processing and were duplicated from the previous good frame.")
            if pct >= 25.0:
                print(f"   ❗ High drop rate ({pct:.1f}%) — likely a systemic bug, not isolated corrupt frames. Re-run with REFRAME_DEBUG_EXC=1 for full tracebacks.", file=sys.stderr)
    
        ffmpeg_process.stdin.close()
        stderr_output = ffmpeg_process.stderr.read().decode()
        ffmpeg_process.wait()
    finally:
        cap.release()
        # If we left the loop abnormally (exception, early break on a
        # write error), make sure ffmpeg can't linger as a zombie holding
        # the stdin pipe open.
        if ffmpeg_process.poll() is None:
            try:
                if ffmpeg_process.stdin and not ffmpeg_process.stdin.closed:
                    ffmpeg_process.stdin.close()
            except (OSError, ValueError):
                pass
            ffmpeg_process.terminate()
            try:
                ffmpeg_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                ffmpeg_process.kill()
                ffmpeg_process.wait()

    if ffmpeg_process.returncode != 0:
        print("\n   ❌ FFmpeg frame processing failed.")
        print("   Stderr:", stderr_output)
        return False

    print("\n   🔊 Step 5: Extracting audio...")
    # A/V-sync fix (ported from kamilstanuch/Autocrop-vertical): many sources —
    # especially YouTube downloads — carry a non-zero video-stream start_time
    # (audio at 0.0s, video at e.g. 1.8s). The vertical video above was re-encoded
    # from frame 0, so we must drop the matching audio lead-in or the streams
    # desync. `audio_sync_seek_args` returns [] for the common zero-start case,
    # keeping behaviour byte-identical there.
    video_start = probe_stream_start_time(input_video, 'v:0')
    seek_args = audio_sync_seek_args(video_start)
    if seek_args:
        print(f"   ⏱️  Compensating video start_time offset {video_start:.3f}s in audio.")
    audio_extract_command = [
        'ffmpeg', '-y', *seek_args, '-i', input_video, '-vn', '-acodec', 'copy', temp_audio_output
    ]
    try:
        result = subprocess.run(audio_extract_command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)
    except subprocess.CalledProcessError as e:
        stderr_msg = e.stderr.decode(errors='replace').strip() if e.stderr else 'unknown'
        print(f"\n   ⚠️ Audio extraction failed: {stderr_msg}")
        print("   Continuing without audio — output video will be silent.")
        if os.path.exists(temp_audio_output):
            os.remove(temp_audio_output)

    print("\n   ✨ Step 6: Merging...")
    if os.path.exists(temp_audio_output):
        merge_command = [
            'ffmpeg', '-y', '-i', temp_video_output, '-i', temp_audio_output,
            # -shortest reconciles any residual length mismatch between the
            # freshly-encoded video and the (possibly trimmed) audio so the output
            # ends cleanly instead of freezing on the last frame with trailing
            # audio (ported from kamilstanuch/Autocrop-vertical).
            '-c:v', 'copy', '-c:a', 'copy', '-shortest', final_output_video
        ]
    else:
         merge_command = [
            'ffmpeg', '-y', '-i', temp_video_output,
            '-c:v', 'copy', final_output_video
        ]
        
    try:
        subprocess.run(merge_command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)
        print(f"   ✅ Clip saved to {final_output_video}")
    except subprocess.CalledProcessError as e:
        print("\n   ❌ Final merge failed.")
        print("   Stderr:", e.stderr.decode())
        return False

    # Clean up temp files
    if os.path.exists(temp_video_output): os.remove(temp_video_output)
    if os.path.exists(temp_audio_output): os.remove(temp_audio_output)
    if os.path.exists(temp_cfr_input): os.remove(temp_cfr_input)

    # Zoom requested but the fold was impossible (unreadable frame count) →
    # legacy post-pass so the caller still gets the motion it asked for.
    if zoom_end and float(zoom_end) > 1.0 and not zoom_folded:
        from clippyme.pipeline.postprocess import apply_subtle_zoom
        apply_subtle_zoom(final_output_video, float(zoom_end))

    return True

