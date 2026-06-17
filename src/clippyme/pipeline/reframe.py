"""Smart 9:16 reframing: face/speaker tracking + camera smoothing.

Extracted from ``pipeline.main`` (the cv2/YOLO/MediaPipe core). ``ASPECT_RATIO``
lives here as a module global that ``main`` sets per-job via
``reframe.ASPECT_RATIO = ...`` before invoking ``process_video_to_vertical`` —
preserving the original cross-module-global behaviour while moving the heavy
logic out of ``main``. Verified against mediapipe 0.10.14 in the Docker image.
"""
import math
import os
import subprocess
import sys
import time

import cv2
import numpy as np
import torch
import mediapipe as mp
from tqdm import tqdm
from ultralytics import YOLO

from clippyme.pipeline.hardware import DEVICE
from clippyme.pipeline.media_probe import (
    audio_sync_seek_args,
    probe_is_variable_frame_rate,
    probe_stream_start_time,
    reconcile_fps,
)
from clippyme.pipeline.reframe_ops import (
    OneEuroFilter,
    advance_value_with_velocity,
    asymmetric_zoom_step,
    build_smoothed_trajectory,
    drift_to_center,
    limit_step,
    salient_crop_center,
    smooth_and_clamp,
    zoom_for_face_height,
)
from clippyme.pipeline.scene_detection import detect_scenes, get_video_resolution

# Set per-job by main before process_video_to_vertical runs (9:16 default).
ASPECT_RATIO = 9 / 16

_yolo_model = None

def _get_yolo_model():
    """Lazy-load YOLOv8n on first body-detection call."""
    global _yolo_model
    if _yolo_model is None:
        _yolo_model = YOLO('yolov8n.pt')
        _yolo_model.to(DEVICE)
    return _yolo_model

mp_face_detection = mp.solutions.face_detection

face_detection = mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)

mp_face_mesh = mp.solutions.face_mesh

face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=False,
    max_num_faces=1,
    refine_landmarks=False,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)

# MediaPipe FaceMesh mouth landmark indices (inner lips + corners). Defined here
# because compute_mouth_aspect_ratio was extracted from main.py during the
# refactor; without these the MAR call raised NameError on every frame, silently
# disabling active-speaker selection (the exception was swallowed by the
# corrupt-frame guard → ~37% duplicated frames).
_MOUTH_TOP = 13
_MOUTH_BOTTOM = 14
_MOUTH_LEFT = 78
_MOUTH_RIGHT = 308


def compute_mouth_aspect_ratio(frame_bgr, face_box) -> float | None:
    """
    Crops the face region and runs FaceMesh to extract the Mouth Aspect Ratio
    (vertical mouth opening / horizontal mouth width).

    Returns a normalized MAR in [0, ~1.5] or None if landmarks couldn't be
    extracted (e.g. profile view, occlusion). The absolute value matters less
    than its *variance over time* — a still mouth has near-zero variance, a
    talking mouth oscillates.
    """
    x, y, w, h = face_box
    H, W = frame_bgr.shape[:2]
    # Pad the crop a bit so FaceMesh has context
    pad = int(max(w, h) * 0.2)
    x1 = max(0, int(x - pad))
    y1 = max(0, int(y - pad))
    x2 = min(W, int(x + w + pad))
    y2 = min(H, int(y + h + pad))
    if x2 - x1 < 30 or y2 - y1 < 30:
        return None
    roi = frame_bgr[y1:y2, x1:x2]
    rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
    rgb.flags.writeable = False
    res = face_mesh.process(rgb)
    if not res.multi_face_landmarks:
        return None
    lm = res.multi_face_landmarks[0].landmark
    rh, rw = roi.shape[:2]
    top = (lm[_MOUTH_TOP].x * rw, lm[_MOUTH_TOP].y * rh)
    bot = (lm[_MOUTH_BOTTOM].x * rw, lm[_MOUTH_BOTTOM].y * rh)
    left = (lm[_MOUTH_LEFT].x * rw, lm[_MOUTH_LEFT].y * rh)
    right = (lm[_MOUTH_RIGHT].x * rw, lm[_MOUTH_RIGHT].y * rh)
    mouth_h = ((top[0] - bot[0]) ** 2 + (top[1] - bot[1]) ** 2) ** 0.5
    mouth_w = ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5
    if mouth_w < 1:
        return None
    return mouth_h / mouth_w

class DetectionSmoother:
    """
    Applies temporal smoothing (rolling average) to face detection bounding boxes.
    Reduces micro-jitter from frame-to-frame detection noise.
    """
    def __init__(self, window_size=5):
        from collections import deque
        self.window_size = window_size
        self.histories = {}  # face_id -> deque of (x, y, w, h)
        self.last_seen_frame: dict[int, int] = {}

    def smooth(self, candidates, frame_number):
        """
        Takes raw face candidates and returns smoothed versions.
        candidates: list of {'box': [x,y,w,h], 'score': float, ...}
        """
        smoothed = []
        for cand in candidates:
            x, y, w, h = cand['box']
            cx = x + w / 2
            # Simple spatial matching to existing tracks
            best_id = None
            min_dist = float('inf')
            for fid, hist in self.histories.items():
                if hist:
                    last = hist[-1]
                    dist = abs(cx - (last[0] + last[2] / 2))
                    if dist < min_dist and dist < w * 2:
                        min_dist = dist
                        best_id = fid
            if best_id is None:
                best_id = frame_number * 1000 + len(smoothed)
            # Update history
            if best_id not in self.histories:
                from collections import deque
                self.histories[best_id] = deque(maxlen=self.window_size)
            self.histories[best_id].append((x, y, w, h))
            self.last_seen_frame[best_id] = frame_number
            # Average
            hist = self.histories[best_id]
            avg_x = int(sum(b[0] for b in hist) / len(hist))
            avg_y = int(sum(b[1] for b in hist) / len(hist))
            avg_w = int(sum(b[2] for b in hist) / len(hist))
            avg_h = int(sum(b[3] for b in hist) / len(hist))
            smoothed.append({**cand, 'box': [avg_x, avg_y, avg_w, avg_h]})
        # Prune tracks not seen in the last 60 frames (~2s @ 30 fps).
        stale = [fid for fid, last in self.last_seen_frame.items()
                 if frame_number - last > 60]
        for fid in stale:
            self.histories.pop(fid, None)
            self.last_seen_frame.pop(fid, None)
        return smoothed

class SmoothedCameraman:
    """
    Handles smooth camera movement with adaptive exponential easing.

    The camera accelerates toward the target and decelerates as it approaches,
    mimicking a professional human operator. Smoothing is *adaptive*:
      - Tiny moves (inside safe zone): zero motion (dead-band, kills jitter).
      - Small/medium moves: gentle 0.08 glide (cinematic).
      - Large moves (>60% of crop width away, e.g. speaker switch on opposite
        side): aggressive 0.30 catch-up so the camera doesn't visibly drift
        for a full second.

    This kills the "software-glide" feel on rapid speaker switches inside a
    single PySceneDetect scene, while preserving the smooth feel for normal
    head movement.
    """
    SMOOTHING_SLOW = 0.08   # cinematic glide for small/medium moves
    SMOOTHING_FAST = 0.30   # aggressive catch-up for large jumps
    FAST_THRESHOLD_RATIO = 0.6  # diff > this * crop_width → use fast smoothing
    # Asymmetric zoom rates (ported from smart-reframe): push IN slowly for a
    # cinematic feel, pull BACK fast so a growing face / arriving second person
    # is never left chopped while the crop catches up.
    ZOOM_RATE_IN = 0.05     # zooming in (tighter crop) — slow
    ZOOM_RATE_OUT = 0.12    # pulling back (wider crop) — fast

    def __init__(self, output_width, output_height, video_width, video_height):
        self.output_width = output_width
        self.output_height = output_height
        self.video_width = video_width
        self.video_height = video_height

        # Max crop dimensions (full source height = the widest possible 9:16 frame)
        self.max_crop_height = video_height
        self.max_crop_width = int(self.max_crop_height * ASPECT_RATIO)
        if self.max_crop_width > video_width:
            self.max_crop_width = video_width
            self.max_crop_height = int(self.max_crop_width / ASPECT_RATIO)

        # Min crop dimensions (zoom-in cap: never zoom past 1.6x to avoid mush)
        self.min_crop_height = int(self.max_crop_height / 1.6)
        self.min_crop_width = int(self.min_crop_height * ASPECT_RATIO)

        # Current crop dims (will animate between min and max)
        self.crop_width = self.max_crop_width
        self.crop_height = self.max_crop_height

        # Initial centers (geometric center of source)
        self.current_center_x = video_width / 2
        self.target_center_x = video_width / 2
        self.current_center_y = video_height / 2
        self.target_center_y = video_height / 2

        # Target zoom factor (1.0 = max crop, 1.6 = max zoom). Animates over time.
        self.current_zoom = 1.0
        self.target_zoom = 1.0

        # Safe zones (dead-band to kill jitter). Tunable via env (fraction of the
        # max crop dimension). The old X=0.20 default let a talking head drift up
        # to 20% off-center before the camera reacted, which read as poor framing
        # on single-speaker shots. Measured sweep on a real clip (tmp/reframe_eval)
        # found X=0.05 / Y=0.08 cut centering error ~30% with *lower* jerk (tighter
        # tracking, not jitter), so those are the new defaults; raise to loosen.
        self.safe_zone_radius_x = self.max_crop_width * float(os.getenv("REFRAME_DEADZONE_X", "0.05"))
        self.safe_zone_radius_y = self.max_crop_height * float(os.getenv("REFRAME_DEADZONE_Y", "0.08"))

        # Lost-subject recovery: when no target arrives for a while (speaker
        # leaves / long occlusion), hold then ease back to the source center
        # instead of freezing the camera on empty space. Always on — strictly
        # safer than the old freeze behavior.
        self.frames_since_target = 0
        self.lost_hold_frames = int(os.getenv("REFRAME_LOST_HOLD", "90"))
        self.lost_drift_rate = float(os.getenv("REFRAME_LOST_DRIFT", "0.05"))

        # Optional 1€ adaptive smoother (opt-in via REFRAME_SMOOTHER=euro).
        # Default keeps the proven two-speed EMA. The 1€ path follows fast
        # moves and damps jitter with a single principled tradeoff; enable it
        # to A/B test camera feel in an environment where output can be viewed.
        _smoother = os.getenv("REFRAME_SMOOTHER", "").strip().lower()
        self._use_euro = _smoother == "euro"
        self._use_spring = _smoother == "spring"
        if self._use_euro:
            mc = float(os.getenv("REFRAME_EURO_MINCUTOFF", "0.014"))
            beta = float(os.getenv("REFRAME_EURO_BETA", "0.0008"))
            self._euro_x = OneEuroFilter(min_cutoff=mc, beta=beta)
            self._euro_y = OneEuroFilter(min_cutoff=mc, beta=beta)

        # Optional momentum / damped-spring smoother (REFRAME_SMOOTHER=spring):
        # carries velocity for operator-like accel/decel, with a hard per-frame
        # velocity cap. Ported from KazKozDev/auto-vertical-reframe.
        if self._use_spring:
            self._spring_resp = float(os.getenv("REFRAME_SPRING_RESPONSE", "0.18"))
            self._spring_damp = float(os.getenv("REFRAME_SPRING_DAMPING", "0.82"))
            self._vx = 0.0
            self._vy = 0.0

        # Hard per-frame pan-rate cap in px (applies to every smoother mode).
        # 0 disables it (default). Also caps the spring's max velocity.
        self._max_step_px = float(os.getenv("REFRAME_MAX_STEP_PX", "0"))
        self._spring_maxv = self._max_step_px if self._max_step_px > 0 else self.max_crop_width * 0.05

    def update_target(self, face_box, is_person_box: bool = False):
        """
        Updates target center + target zoom based on a detected face or person box.

        face_box: (x, y, w, h) in source coordinates.
        is_person_box: if True, treat the box as a YOLO person bbox (full body)
                       and aim at the *upper portion* (head zone) instead of
                       the geometric center. Fixes the "camera shows knees"
                       bug from the old YOLO fallback.
        """
        if not face_box:
            return
        # A real target this frame → reset the lost-subject counter.
        self.frames_since_target = 0
        x, y, w, h = face_box
        self.target_center_x = x + w / 2

        if is_person_box:
            # Head is roughly in the top 20% of a standing person bbox
            self.target_center_y = y + h * 0.15
            # Person fallback = no clean face → don't zoom in (could be wide group)
            self.target_zoom = 1.0
        else:
            self.target_center_y = y + h / 2
            # Zoom in proportionally to face size — small faces (talking head in
            # wide shot) trigger more zoom; large faces stay at 1.0. Continuous
            # face-occupancy target (ported from smart-reframe) replaces the old
            # 4-bucket ladder, which snapped visibly at bucket edges. 1.6 ceiling
            # matches min_crop (= max_crop/1.6); face aims for ~40% of crop height.
            self.target_zoom = zoom_for_face_height(
                h, self.max_crop_height, target_occupancy=0.4,
                min_zoom=1.0, max_zoom=1.6,
            )

    def _ease_axis(self, current: float, target: float, safe_radius: float, fast_ref: float) -> float:
        """Adaptive easing for a single axis. Returns the new current value."""
        diff = target - current
        abs_diff = abs(diff)
        if abs_diff <= safe_radius:
            return current  # dead-band
        if abs_diff > fast_ref * self.FAST_THRESHOLD_RATIO:
            return current + diff * self.SMOOTHING_FAST
        return current + diff * self.SMOOTHING_SLOW

    def get_crop_box(self, force_snap=False):
        """
        Returns (x1, y1, x2, y2) for the current frame.

        Tracks both X and Y axes with adaptive easing, and animates zoom level
        based on detected face size. Crop dimensions are recomputed each frame
        from the current zoom factor.
        """
        if force_snap:
            self.current_center_x = self.target_center_x
            self.current_center_y = self.target_center_y
            self.current_zoom = self.target_zoom
            self.frames_since_target = 0
            if self._use_euro:
                self._euro_x.reset()
                self._euro_y.reset()
            if self._use_spring:
                self._vx = 0.0
                self._vy = 0.0
        else:
            # Lost-subject recovery: once we've gone `lost_hold_frames` without
            # a fresh target, ease the TARGET toward the source center (and
            # gently zoom out). Normal easing below then glides the camera
            # there smoothly. Active in TRACK/WIDE only (GENERAL/DISABLED set
            # centers directly and never call this).
            self.frames_since_target += 1
            if self.frames_since_target > self.lost_hold_frames:
                self.target_center_x = drift_to_center(
                    self.target_center_x, self.video_width / 2,
                    self.frames_since_target, self.lost_hold_frames, self.lost_drift_rate)
                self.target_center_y = drift_to_center(
                    self.target_center_y, self.video_height / 2,
                    self.frames_since_target, self.lost_hold_frames, self.lost_drift_rate)
                if self.target_zoom > 1.0:
                    self.target_zoom = max(1.0, self.target_zoom - 0.01)

            prev_center_x, prev_center_y = self.current_center_x, self.current_center_y
            if self._use_euro:
                # Apply the dead-band on the target, then 1€-filter every frame
                # (feeding the filter each frame keeps its velocity estimate live).
                tx = self.target_center_x if abs(self.target_center_x - self.current_center_x) > self.safe_zone_radius_x else self.current_center_x
                ty = self.target_center_y if abs(self.target_center_y - self.current_center_y) > self.safe_zone_radius_y else self.current_center_y
                self.current_center_x = self._euro_x.filter(tx, 1.0)
                self.current_center_y = self._euro_y.filter(ty, 1.0)
            elif self._use_spring:
                # Dead-band, then integrate a velocity-damped move toward target.
                tx = self.target_center_x if abs(self.target_center_x - self.current_center_x) > self.safe_zone_radius_x else self.current_center_x
                ty = self.target_center_y if abs(self.target_center_y - self.current_center_y) > self.safe_zone_radius_y else self.current_center_y
                self.current_center_x, self._vx = advance_value_with_velocity(
                    self.current_center_x, tx, self._vx,
                    self._spring_resp, self._spring_damp, self._spring_maxv)
                self.current_center_y, self._vy = advance_value_with_velocity(
                    self.current_center_y, ty, self._vy,
                    self._spring_resp, self._spring_damp, self._spring_maxv)
            else:
                self.current_center_x = self._ease_axis(
                    self.current_center_x, self.target_center_x,
                    self.safe_zone_radius_x, self.max_crop_width,
                )
                self.current_center_y = self._ease_axis(
                    self.current_center_y, self.target_center_y,
                    self.safe_zone_radius_y, self.max_crop_height,
                )
            # Hard per-frame pan-rate cap (all modes; off when 0). Guarantees the
            # camera never jumps more than REFRAME_MAX_STEP_PX px in one frame.
            if self._max_step_px > 0:
                self.current_center_x = limit_step(prev_center_x, self.current_center_x, self._max_step_px)
                self.current_center_y = limit_step(prev_center_y, self.current_center_y, self._max_step_px)
            # Zoom animates more slowly than position to feel cinematic, and
            # asymmetrically: fast pull-back, slow push-in (smart-reframe port).
            if abs(self.target_zoom - self.current_zoom) > 0.01:
                self.current_zoom = asymmetric_zoom_step(
                    self.current_zoom, self.target_zoom,
                    self.ZOOM_RATE_IN, self.ZOOM_RATE_OUT,
                )

        # Recompute crop dims from current zoom
        self.crop_width = max(self.min_crop_width, int(self.max_crop_width / self.current_zoom))
        self.crop_height = max(self.min_crop_height, int(self.max_crop_height / self.current_zoom))

        # Clamp center inside the source frame
        half_w = self.crop_width / 2
        half_h = self.crop_height / 2

        cx = max(half_w, min(self.video_width - half_w, self.current_center_x))
        cy = max(half_h, min(self.video_height - half_h, self.current_center_y))
        self.current_center_x = cx
        self.current_center_y = cy

        x1 = max(0, int(cx - half_w))
        x2 = min(self.video_width, int(cx + half_w))
        y1 = max(0, int(cy - half_h))
        y2 = min(self.video_height, int(cy + half_h))

        return x1, y1, x2, y2

    def crop_box_at(self, cx: float, cy: float, zoom: float):
        """Crop box (x1, y1, x2, y2) for an explicit center + zoom, with no
        easing. Used by the two-stage global-smoothing render pass, which feeds
        in a pre-smoothed trajectory instead of letting the camera ease online.
        Shares the exact crop-dim + clamp math of ``get_crop_box``.
        """
        crop_width = max(self.min_crop_width, int(self.max_crop_width / zoom))
        crop_height = max(self.min_crop_height, int(self.max_crop_height / zoom))
        half_w = crop_width / 2
        half_h = crop_height / 2
        cx = max(half_w, min(self.video_width - half_w, cx))
        cy = max(half_h, min(self.video_height - half_h, cy))
        x1 = max(0, int(cx - half_w))
        x2 = min(self.video_width, int(cx + half_w))
        y1 = max(0, int(cy - half_h))
        y2 = min(self.video_height, int(cy + half_h))
        return x1, y1, x2, y2

class SpeakerTracker:
    """
    Tracks speakers over time to prevent rapid switching and handle temporary
    obstructions. Uses Mouth Aspect Ratio (MAR) variance as the primary signal
    for active-speaker detection — a person whose mouth is moving (high MAR
    variance over the last ~1s window) is far more likely to be speaking than
    one whose mouth is still, regardless of face size.
    """
    MAR_WINDOW_SIZE = 25  # ~1s @ 25fps of MAR samples per speaker
    SIZE_WEIGHT = 0.3     # face size still contributes (proximity to camera)
    MOUTH_WEIGHT = 1.0    # mouth motion is the dominant signal

    def __init__(self, stabilization_frames=15, cooldown_frames=30):
        self.active_speaker_id = None
        self.speaker_scores = {}  # {id: smoothed_score}
        self.mar_history = {}     # {id: [mar0, mar1, ...]} sliding window
        self.last_seen = {}
        self.locked_counter = 0

        # Hyperparameters
        self.stabilization_threshold = stabilization_frames
        self.switch_cooldown = cooldown_frames
        self.last_switch_frame = -1000

        # ID tracking
        self.next_id = 0
        self.known_faces = []  # [{'id': 0, 'center': x, 'last_frame': 123}]

    def get_target(self, face_candidates, frame_number, width):
        """
        Decides which face to focus on.

        face_candidates: list of {'box': [x,y,w,h], 'score': float, 'mar': float|None}
          - 'score' is face area (legacy, used for size weighting)
          - 'mar' is mouth aspect ratio at this frame (None if not extractable)
        """
        current_candidates = []

        # 1. Match faces to known IDs (simple distance tracking)
        for face in face_candidates:
            x, y, w, h = face['box']
            center_x = x + w / 2

            best_match_id = -1
            min_dist = width * 0.15

            for kf in self.known_faces:
                if frame_number - kf['last_frame'] > 30:
                    continue
                dist = abs(center_x - kf['center'])
                if dist < min_dist:
                    min_dist = dist
                    best_match_id = kf['id']

            if best_match_id == -1:
                best_match_id = self.next_id
                self.next_id += 1

            self.known_faces = [kf for kf in self.known_faces if kf['id'] != best_match_id]
            self.known_faces.append({'id': best_match_id, 'center': center_x, 'last_frame': frame_number})

            current_candidates.append({
                'id': best_match_id,
                'box': face['box'],
                'score': face['score'],
                'mar': face.get('mar'),
            })

        # 2. Update MAR history (sliding window) for each visible face
        for cand in current_candidates:
            pid = cand['id']
            if cand['mar'] is not None:
                hist = self.mar_history.setdefault(pid, [])
                hist.append(cand['mar'])
                if len(hist) > self.MAR_WINDOW_SIZE:
                    hist.pop(0)

        # Decay smoothed scores; drop stale entries
        for pid in list(self.speaker_scores.keys()):
            self.speaker_scores[pid] *= 0.85
            if self.speaker_scores[pid] < 0.05:
                del self.speaker_scores[pid]
                self.mar_history.pop(pid, None)

        # 3. Compute combined score: mouth-motion variance + face size
        for cand in current_candidates:
            pid = cand['id']
            size_norm = cand['score'] / (width * width * 0.05)

            mar_hist = self.mar_history.get(pid, [])
            if len(mar_hist) >= 5:
                mean = sum(mar_hist) / len(mar_hist)
                variance = sum((m - mean) ** 2 for m in mar_hist) / len(mar_hist)
                # Scale variance to a useful range (0..~3)
                mouth_motion = min(variance * 200.0, 3.0)
            else:
                # Not enough samples yet → fall back to neutral
                mouth_motion = 0.5

            combined = self.SIZE_WEIGHT * size_norm + self.MOUTH_WEIGHT * mouth_motion
            self.speaker_scores[pid] = self.speaker_scores.get(pid, 0) + combined

        # 3. Determine Best Speaker
        if not current_candidates:
            # If no one found, maintain last active speaker if cooldown allows
            # to avoid black screen or jump to 0,0
            return None 
            
        best_candidate = None
        max_score = -1
        
        for cand in current_candidates:
            pid = cand['id']
            total_score = self.speaker_scores.get(pid, 0)
            
            # Hysteresis: HUGE Bonus for current active speaker
            if pid == self.active_speaker_id:
                total_score *= 3.0 # Sticky factor
                
            if total_score > max_score:
                max_score = total_score
                best_candidate = cand

        # 4. Decide Switch
        if best_candidate:
            target_id = best_candidate['id']
            
            if target_id == self.active_speaker_id:
                self.locked_counter += 1
                return best_candidate['box']
            
            # New person
            if frame_number - self.last_switch_frame < self.switch_cooldown:
                old_cand = next((c for c in current_candidates if c['id'] == self.active_speaker_id), None)
                if old_cand:
                    return old_cand['box']
                # Active speaker temporarily off-screen: hold the previous
                # framing (return None → cameraman keeps its current target)
                # instead of switching. Prevents rapid A→B→A oscillation
                # when A briefly turns away / occludes.
                return None

            self.active_speaker_id = target_id
            self.last_switch_frame = frame_number
            self.locked_counter = 0
            return best_candidate['box']
            
        return None

def detect_face_candidates(frame):
    """
    Returns list of all detected faces using lightweight FaceDetection.
    """
    height, width, _ = frame.shape
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_detection.process(rgb_frame)
    
    candidates = []
    
    if not results.detections:
        return []
        
    for detection in results.detections:
        bboxC = detection.location_data.relative_bounding_box
        x = int(bboxC.xmin * width)
        y = int(bboxC.ymin * height)
        w = int(bboxC.width * width)
        h = int(bboxC.height * height)
        
        candidates.append({
            'box': [x, y, w, h],
            'score': w * h # Area as score
        })
            
    return candidates

def detect_person_yolo(frame):
    """
    Fallback: Detect largest person using YOLO when face detection fails.
    Returns [x, y, w, h] of the person's 'upper body' approximation.
    """
    results = _get_yolo_model()(frame, verbose=False, classes=[0])  # class 0 is person
    
    if not results:
        return None
        
    best_box = None
    max_area = 0
    
    for result in results:
        boxes = result.boxes
        for box in boxes:
            x1, y1, x2, y2 = [int(i) for i in box.xyxy[0]]
            w = x2 - x1
            h = y2 - y1
            area = w * h
            
            if area > max_area:
                max_area = area
                # Return the full person bbox. SmoothedCameraman.update_target
                # applies the head-zone offset itself when is_person_box=True
                # (y_center = y + h*0.15). Previously we truncated here AND
                # there, which stacked the offsets and aimed above the head.
                best_box = [x1, y1, w, h]
                
    return best_box

def create_general_frame(frame, output_width, output_height):
    """
    Creates a 'General Shot' frame: 
    - Background: Blurred zoom of original
    - Foreground: Original video scaled to fit width, centered vertically.
    """
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

def analyze_scenes_strategy(video_path, scenes):
    """
    Analyzes each scene to determine framing strategy.
    Strategies:
      TRACK   — single subject, follow with smart crop
      WIDE    — 2+ faces, use letterbox (blur bg + centered full frame)
      GENERAL — no faces detected, use letterbox
    """
    cap = cv2.VideoCapture(video_path)
    strategies = []

    if not cap.isOpened():
        return ['TRACK'] * len(scenes)

    for start, end in tqdm(scenes, desc="   Analyzing Scenes"):
        # Sample 7 frames evenly across the scene for a more reliable
        # face-count estimate (was 3 frames). Catches mixed-content scenes
        # where the face count changes mid-scene.
        s_frame = start.get_frames()
        e_frame = end.get_frames()
        if e_frame - s_frame < 14:
            frames_to_check = [s_frame + 2, (s_frame + e_frame) // 2, e_frame - 2]
        else:
            step = (e_frame - s_frame) // 8
            frames_to_check = [s_frame + step * i for i in range(1, 8)]

        face_counts = []
        for f_idx in frames_to_check:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret, frame = cap.read()
            if not ret:
                continue
            candidates = detect_face_candidates(frame)
            face_counts.append(len(candidates))

        if not face_counts:
            strategies.append('GENERAL')
            continue

        avg_faces = sum(face_counts) / len(face_counts)
        max_faces = max(face_counts)

        if avg_faces < 0.4:
            strategies.append('GENERAL')
        elif max_faces >= 2 and avg_faces > 1.0:
            # Multi-speaker scene → WIDE (now uses dynamic switching, not letterbox)
            strategies.append('WIDE')
        else:
            strategies.append('TRACK')

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
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0 or fps <= 0:
            cap.release()
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
    with tqdm(total=total_frames, desc="   Pass 1", file=sys.stdout) as pbar:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            if current_scene_index < len(scene_boundaries):
                _, end_f = scene_boundaries[current_scene_index]
                if frame_number >= end_f and current_scene_index < len(scene_boundaries) - 1:
                    current_scene_index += 1
            strat = scene_strategies[current_scene_index] if current_scene_index < len(scene_strategies) else 'TRACK'
            strategies.append(strat)
            scene_ids.append(current_scene_index)
            if strat in ('DISABLED', 'GENERAL'):
                targets.append(None)
            else:
                if frame_number % 2 == 0:
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
    cap.release()

    # --- Global smoothing pass ---------------------------------------------
    # Global smoother for the pan path: savgol (default) | kalman | l2. The two
    # alternatives (RTS Kalman, L2 convex optimiser) are ported from
    # mfahsold/montage-ai; default stays savgol so behaviour is unchanged unless
    # opted in via REFRAME_GLOBAL_METHOD.
    global_method = os.getenv("REFRAME_GLOBAL_METHOD", "savgol").strip().lower()
    smoothed = build_smoothed_trajectory(
        targets, scene_ids, window=win, polyorder=2,
        x_max=original_width, y_max=original_height,
        min_zoom=1.0, max_zoom=1.6, method=global_method,
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
                            output_frame = cv2.resize(frame[y1:y2, x1:x2], (output_width, output_height))
                        else:
                            output_frame = cv2.resize(frame, (output_width, output_height))
                last_output_frame = output_frame
            except Exception:
                dropped_frames += 1
                if last_output_frame is not None:
                    output_frame = last_output_frame
                else:
                    output_frame = np.zeros((output_height, output_width, 3), dtype=np.uint8)
            ffmpeg_process.stdin.write(output_frame.tobytes())
            frame_number += 1
            pbar.update(1)
    cap.release()
    if dropped_frames > 0:
        print(f"   ⚠️ {dropped_frames} frame(s) failed processing and were duplicated from the previous good frame.")


def process_video_to_vertical(input_video, final_output_video, reframe_mode='auto'):
    """
    Core logic to convert horizontal video to vertical using scene detection and Active Speaker Tracking (MediaPipe).
    """
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
            subprocess.run(cfr_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
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
    OUTPUT_WIDTH = int(OUTPUT_HEIGHT * ASPECT_RATIO)
    if OUTPUT_WIDTH % 2 != 0:
        OUTPUT_WIDTH += 1

    # Initialize Cameraman
    cameraman = SmoothedCameraman(OUTPUT_WIDTH, OUTPUT_HEIGHT, original_width, original_height)
    
    # --- New Strategy: Per-Scene Analysis ---
    if reframe_mode == 'disabled':
        print("\n   🤖 Step 3: Skipping scene analysis (reframe disabled).")
        scene_strategies = ['DISABLED'] * len(scenes)
    else:
        print("\n   🤖 Step 3: Analyzing Scenes for Strategy (Single vs Group)...")
        scene_strategies = analyze_scenes_strategy(input_video, scenes)

    print("\n   ✂️ Step 4: Processing video frames...")
    
    command = [
        'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}', '-pix_fmt', 'bgr24',
        '-r', str(fps), '-i', '-', '-c:v', 'libx264',
        # -pix_fmt yuv420p: the raw input is bgr24; without this libx264 may pick a
        # non-subsampled format (yuv444p) that some players/mobile decoders reject.
        # Later post-process passes (zoom/subtitles) already force 420p, but a clip
        # with those skipped would otherwise ship a non-420p codec.
        # -vsync cfr: lock output to a constant frame rate matching `-r`.
        # (Both ported from kamilstanuch/Autocrop-vertical.)
        '-pix_fmt', 'yuv420p', '-vsync', 'cfr',
        '-preset', 'fast', '-crf', '23', '-an', temp_video_output
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

        # Opt-in two-stage global trajectory smoothing (REFRAME_GLOBAL_SMOOTH).
        # When on, a dedicated track-then-render pass handles all frames and the
        # single-pass streaming loop below is skipped (its `while` short-circuits
        # on `not global_smooth`). Default-off keeps the proven path byte-identical.
        global_smooth = (
            os.getenv("REFRAME_GLOBAL_SMOOTH", "").strip().lower() in ("1", "true", "yes", "on")
            and reframe_mode != 'disabled'
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
            
                # Determine Strategy for current frame based on scene
                current_strategy = scene_strategies[current_scene_index] if current_scene_index < len(scene_strategies) else 'TRACK'
            
                # Apply Strategy. Guarded so a single malformed frame (bad crop,
                # corrupt decode) duplicates the previous good output rather than
                # aborting the render and truncating the clip.
                try:
                    if current_strategy == 'DISABLED':
                        output_frame = create_disabled_reframe(frame, OUTPUT_WIDTH, OUTPUT_HEIGHT)

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
                            output_frame = cv2.resize(cropped, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
                        else:
                            output_frame = cv2.resize(frame, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
                    last_output_frame = output_frame
                except Exception:
                    dropped_frames += 1
                    if os.environ.get('REFRAME_DEBUG_EXC') and dropped_frames <= 5:
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
            print(f"   ⚠️ {dropped_frames} frame(s) failed processing and were duplicated from the previous good frame.")
    
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
        result = subprocess.run(audio_extract_command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
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
        subprocess.run(merge_command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print(f"   ✅ Clip saved to {final_output_video}")
    except subprocess.CalledProcessError as e:
        print("\n   ❌ Final merge failed.")
        print("   Stderr:", e.stderr.decode())
        return False

    # Clean up temp files
    if os.path.exists(temp_video_output): os.remove(temp_video_output)
    if os.path.exists(temp_audio_output): os.remove(temp_audio_output)
    if os.path.exists(temp_cfr_input): os.remove(temp_cfr_input)

    return True

