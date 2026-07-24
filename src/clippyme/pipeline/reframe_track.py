"""Pure tracking/camera classes for the reframe pipeline.

No cv2/torch/mediapipe imports: every decision can be host-unit-tested.  The
speaker tracker uses 2D geometry + IoU identity association, mouth-motion
confidence and relative switch hysteresis so the crop follows the actual speaker
without oscillating between nearby faces or inheriting IDs across crossings.
"""
import math
import os
from collections import deque

from clippyme.pipeline.reframe_ops import (
    OneEuroFilter,
    advance_value_with_velocity,
    asymmetric_zoom_step,
    drift_to_center,
    limit_step,
    zoom_for_face_height,
)


class DetectionSmoother:
    """Rolling-average face boxes to suppress detector micro-jitter."""

    def __init__(self, window_size=5):
        self.window_size = window_size
        self.histories = {}
        self.last_seen_frame: dict[int, int] = {}

    def smooth(self, candidates, frame_number):
        smoothed = []
        claimed = set()
        for cand in candidates:
            x, y, w, h = cand["box"]
            cx, cy = x + w / 2, y + h / 2
            best_id = None
            best_cost = float("inf")
            for face_id, history in self.histories.items():
                if face_id in claimed or not history:
                    continue
                lx, ly, lw, lh = history[-1]
                lcx, lcy = lx + lw / 2, ly + lh / 2
                distance = math.hypot(cx - lcx, cy - lcy)
                scale = max(1.0, w, h, lw, lh)
                cost = distance / scale
                if cost < best_cost and cost < 2.0:
                    best_cost = cost
                    best_id = face_id
            if best_id is None:
                best_id = frame_number * 1000 + len(smoothed)
            claimed.add(best_id)
            history = self.histories.setdefault(best_id, deque(maxlen=self.window_size))
            history.append((x, y, w, h))
            self.last_seen_frame[best_id] = frame_number
            smoothed.append({
                **cand,
                "box": [
                    int(sum(box[0] for box in history) / len(history)),
                    int(sum(box[1] for box in history) / len(history)),
                    int(sum(box[2] for box in history) / len(history)),
                    int(sum(box[3] for box in history) / len(history)),
                ],
            })
        stale = [
            face_id for face_id, last in self.last_seen_frame.items()
            if frame_number - last > 60
        ]
        for face_id in stale:
            self.histories.pop(face_id, None)
            self.last_seen_frame.pop(face_id, None)
        return smoothed

    def reset(self):
        self.histories.clear()
        self.last_seen_frame.clear()


class SmoothedCameraman:
    """Adaptive, bounded virtual camera for a tracked face/person box."""

    SMOOTHING_SLOW = 0.08
    SMOOTHING_FAST = 0.30
    FAST_THRESHOLD_RATIO = 0.6
    ZOOM_RATE_IN = 0.05
    ZOOM_RATE_OUT = 0.12

    def __init__(self, output_width, output_height, video_width, video_height,
                 *, aspect_ratio: float = 9 / 16):
        self.output_width = output_width
        self.output_height = output_height
        self.video_width = video_width
        self.video_height = video_height
        self.aspect_ratio = float(aspect_ratio)

        self.max_crop_height = video_height
        self.max_crop_width = int(self.max_crop_height * self.aspect_ratio)
        if self.max_crop_width > video_width:
            self.max_crop_width = video_width
            self.max_crop_height = int(self.max_crop_width / self.aspect_ratio)
        self.min_crop_height = int(self.max_crop_height / 1.6)
        self.min_crop_width = int(self.min_crop_height * self.aspect_ratio)
        self.crop_width = self.max_crop_width
        self.crop_height = self.max_crop_height

        self.current_center_x = video_width / 2
        self.target_center_x = video_width / 2
        self.current_center_y = video_height / 2
        self.target_center_y = video_height / 2
        self.current_zoom = 1.0
        self.target_zoom = 1.0

        self.safe_zone_radius_x = self.max_crop_width * float(os.getenv("REFRAME_DEADZONE_X", "0.05"))
        self.safe_zone_radius_y = self.max_crop_height * float(os.getenv("REFRAME_DEADZONE_Y", "0.08"))
        self.frames_since_target = 0
        self.lost_hold_frames = int(os.getenv("REFRAME_LOST_HOLD", "90"))
        self.lost_drift_rate = float(os.getenv("REFRAME_LOST_DRIFT", "0.05"))

        smoother = os.getenv("REFRAME_SMOOTHER", "").strip().lower()
        self._use_euro = smoother == "euro"
        self._use_spring = smoother == "spring"
        if self._use_euro:
            minimum_cutoff = float(os.getenv("REFRAME_EURO_MINCUTOFF", "0.014"))
            beta = float(os.getenv("REFRAME_EURO_BETA", "0.0008"))
            self._euro_x = OneEuroFilter(min_cutoff=minimum_cutoff, beta=beta)
            self._euro_y = OneEuroFilter(min_cutoff=minimum_cutoff, beta=beta)
        if self._use_spring:
            self._spring_resp = float(os.getenv("REFRAME_SPRING_RESPONSE", "0.18"))
            self._spring_damp = float(os.getenv("REFRAME_SPRING_DAMPING", "0.82"))
            self._vx = 0.0
            self._vy = 0.0
        self._max_step_px = float(os.getenv("REFRAME_MAX_STEP_PX", "0"))
        self._spring_maxv = (
            self._max_step_px if self._max_step_px > 0 else self.max_crop_width * 0.05
        )

    def update_target(self, face_box, is_person_box: bool = False):
        if not face_box:
            return
        self.frames_since_target = 0
        x, y, width, height = face_box
        self.target_center_x = x + width / 2
        if is_person_box:
            self.target_center_y = y + height * 0.15
            self.target_zoom = 1.0
        else:
            self.target_center_y = y + height / 2
            # A wide union/group box must pull back rather than treating its
            # height as a small face and zooming into only the centre speaker.
            if width > height * 1.35:
                self.target_zoom = 1.0
            else:
                self.target_zoom = zoom_for_face_height(
                    height,
                    self.max_crop_height,
                    target_occupancy=0.4,
                    min_zoom=1.0,
                    max_zoom=1.6,
                )

    def _ease_axis(self, current: float, target: float, safe_radius: float, fast_ref: float) -> float:
        difference = target - current
        if abs(difference) <= safe_radius:
            return current
        rate = self.SMOOTHING_FAST if abs(difference) > fast_ref * self.FAST_THRESHOLD_RATIO else self.SMOOTHING_SLOW
        return current + difference * rate

    def get_crop_box(self, force_snap=False):
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
            self.frames_since_target += 1
            if self.frames_since_target > self.lost_hold_frames:
                self.target_center_x = drift_to_center(
                    self.target_center_x,
                    self.video_width / 2,
                    self.frames_since_target,
                    self.lost_hold_frames,
                    self.lost_drift_rate,
                )
                self.target_center_y = drift_to_center(
                    self.target_center_y,
                    self.video_height / 2,
                    self.frames_since_target,
                    self.lost_hold_frames,
                    self.lost_drift_rate,
                )
                if self.target_zoom > 1.0:
                    self.target_zoom = max(1.0, self.target_zoom - 0.01)

            previous_x, previous_y = self.current_center_x, self.current_center_y
            target_x = (
                self.target_center_x
                if abs(self.target_center_x - self.current_center_x) > self.safe_zone_radius_x
                else self.current_center_x
            )
            target_y = (
                self.target_center_y
                if abs(self.target_center_y - self.current_center_y) > self.safe_zone_radius_y
                else self.current_center_y
            )
            if self._use_euro:
                self.current_center_x = self._euro_x.filter(target_x, 1.0)
                self.current_center_y = self._euro_y.filter(target_y, 1.0)
            elif self._use_spring:
                self.current_center_x, self._vx = advance_value_with_velocity(
                    self.current_center_x,
                    target_x,
                    self._vx,
                    self._spring_resp,
                    self._spring_damp,
                    self._spring_maxv,
                )
                self.current_center_y, self._vy = advance_value_with_velocity(
                    self.current_center_y,
                    target_y,
                    self._vy,
                    self._spring_resp,
                    self._spring_damp,
                    self._spring_maxv,
                )
            else:
                self.current_center_x = self._ease_axis(
                    self.current_center_x,
                    self.target_center_x,
                    self.safe_zone_radius_x,
                    self.max_crop_width,
                )
                self.current_center_y = self._ease_axis(
                    self.current_center_y,
                    self.target_center_y,
                    self.safe_zone_radius_y,
                    self.max_crop_height,
                )
            if self._max_step_px > 0:
                self.current_center_x = limit_step(previous_x, self.current_center_x, self._max_step_px)
                self.current_center_y = limit_step(previous_y, self.current_center_y, self._max_step_px)
            if abs(self.target_zoom - self.current_zoom) > 0.01:
                self.current_zoom = asymmetric_zoom_step(
                    self.current_zoom,
                    self.target_zoom,
                    self.ZOOM_RATE_IN,
                    self.ZOOM_RATE_OUT,
                )

        self.crop_width = max(self.min_crop_width, int(self.max_crop_width / self.current_zoom))
        self.crop_height = max(self.min_crop_height, int(self.max_crop_height / self.current_zoom))
        half_width = self.crop_width / 2
        half_height = self.crop_height / 2
        center_x = max(half_width, min(self.video_width - half_width, self.current_center_x))
        center_y = max(half_height, min(self.video_height - half_height, self.current_center_y))
        self.current_center_x = center_x
        self.current_center_y = center_y
        return (
            max(0, int(center_x - half_width)),
            max(0, int(center_y - half_height)),
            min(self.video_width, int(center_x + half_width)),
            min(self.video_height, int(center_y + half_height)),
        )

    def crop_box_at(self, cx: float, cy: float, zoom: float):
        crop_width = max(self.min_crop_width, int(self.max_crop_width / zoom))
        crop_height = max(self.min_crop_height, int(self.max_crop_height / zoom))
        half_width = crop_width / 2
        half_height = crop_height / 2
        cx = max(half_width, min(self.video_width - half_width, cx))
        cy = max(half_height, min(self.video_height - half_height, cy))
        return (
            max(0, int(cx - half_width)),
            max(0, int(cy - half_height)),
            min(self.video_width, int(cx + half_width)),
            min(self.video_height, int(cy + half_height)),
        )


def _box_iou(first, second) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = max(0.0, aw * ah) + max(0.0, bw * bh) - intersection
    return intersection / union if union > 0 else 0.0


def _union_box(candidates):
    left = min(item["box"][0] for item in candidates)
    top = min(item["box"][1] for item in candidates)
    right = max(item["box"][0] + item["box"][2] for item in candidates)
    bottom = max(item["box"][1] + item["box"][3] for item in candidates)
    return [left, top, right - left, bottom - top]


class SpeakerTracker:
    """Track face identities and select a stable active-speaker target.

    Identity matching combines IoU and normalized 2D distance, which is robust to
    two people crossing horizontally.  A challenger must beat the current
    speaker by a configurable relative margin after the cooldown.  When two
    similarly-scored prominent faces are far apart, a temporary group box keeps
    the dialogue reaction in frame instead of snap-cutting between them.
    """

    MAR_WINDOW_SIZE = 25
    SIZE_WEIGHT = 0.30
    MOUTH_WEIGHT = 1.0

    def __init__(self, cooldown_frames=30):
        self.active_speaker_id = None
        self.speaker_scores = {}
        self.mar_history = {}
        self.last_seen = {}
        self.locked_counter = 0
        self.switch_cooldown = cooldown_frames
        self.last_switch_frame = -1000
        self.next_id = 0
        self.known_faces = []
        self.switch_margin = max(1.0, float(os.getenv("REFRAME_SPEAKER_SWITCH_MARGIN", "1.25")))
        self.min_face_ratio = max(0.0, min(1.0, float(os.getenv("REFRAME_MIN_FACE_RATIO", "0.10"))))
        self.group_enabled = os.getenv("REFRAME_DIALOGUE_GROUP", "1").lower() not in {"0", "false", "no"}
        self.group_score_ratio = max(0.5, min(1.0, float(os.getenv("REFRAME_DIALOGUE_SCORE_RATIO", "0.88"))))
        self.group_separation = max(0.05, min(0.9, float(os.getenv("REFRAME_DIALOGUE_SEPARATION", "0.28"))))

    def reset(self, frame_number=None):
        self.active_speaker_id = None
        self.speaker_scores = {}
        self.mar_history = {}
        self.last_seen = {}
        self.locked_counter = 0
        self.known_faces = []
        if frame_number is not None:
            self.last_switch_frame = frame_number - self.switch_cooldown

    def _match_identity(self, box, frame_number, frame_width, claimed):
        x, y, width, height = box
        center_x, center_y = x + width / 2, y + height / 2
        best_id = None
        best_cost = float("inf")
        for known in self.known_faces:
            if known["id"] in claimed or frame_number - known["last_frame"] > 30:
                continue
            previous = known["box"]
            px, py, pw, ph = previous
            previous_x, previous_y = px + pw / 2, py + ph / 2
            distance = math.hypot(center_x - previous_x, center_y - previous_y)
            scale = max(1.0, width, height, pw, ph, frame_width * 0.03)
            normalized = distance / scale
            iou = _box_iou(box, previous)
            cost = normalized - iou * 0.75
            if cost < best_cost and (iou >= 0.05 or normalized <= 1.8):
                best_cost = cost
                best_id = known["id"]
        if best_id is None:
            best_id = self.next_id
            self.next_id += 1
        return best_id

    def _mouth_motion(self, face_id) -> float:
        history = self.mar_history.get(face_id, [])
        if len(history) < 5:
            return 0.35
        mean = sum(history) / len(history)
        variance = sum((sample - mean) ** 2 for sample in history) / len(history)
        return min(variance * 200.0, 3.0)

    def get_target(self, face_candidates, frame_number, width):
        # Prune expired identities before matching. Otherwise long
        # streams accumulate an ever-growing candidate list.
        self.known_faces = [
            known
            for known in self.known_faces
            if frame_number - known["last_frame"] <= 30
        ]
        if not face_candidates:
            return None
        maximum_area = max(
            max(0.0, float(face.get("score") or face["box"][2] * face["box"][3]))
            for face in face_candidates
        )
        candidates = [
            face for face in face_candidates
            if float(face.get("score") or face["box"][2] * face["box"][3])
            >= maximum_area * self.min_face_ratio
        ]

        current = []
        claimed = set()
        for face in sorted(candidates, key=lambda item: float(item.get("score") or 0), reverse=True):
            face_id = self._match_identity(face["box"], frame_number, width, claimed)
            claimed.add(face_id)
            self.known_faces = [known for known in self.known_faces if known["id"] != face_id]
            self.known_faces.append({
                "id": face_id,
                "box": list(face["box"]),
                "last_frame": frame_number,
            })
            candidate = {
                "id": face_id,
                "box": face["box"],
                "score": float(face.get("score") or face["box"][2] * face["box"][3]),
                "mar": face.get("mar"),
            }
            current.append(candidate)
            self.last_seen[face_id] = frame_number
            if candidate["mar"] is not None:
                history = self.mar_history.setdefault(face_id, [])
                history.append(float(candidate["mar"]))
                if len(history) > self.MAR_WINDOW_SIZE:
                    del history[:-self.MAR_WINDOW_SIZE]

        visible_ids = {candidate["id"] for candidate in current}
        for face_id in list(self.speaker_scores):
            if face_id not in visible_ids:
                self.speaker_scores[face_id] *= 0.82
            if frame_number - self.last_seen.get(face_id, frame_number) > 60:
                self.speaker_scores.pop(face_id, None)
                self.mar_history.pop(face_id, None)
                self.last_seen.pop(face_id, None)

        frame_area_ref = max(1.0, width * width * 0.05)
        for candidate in current:
            face_id = candidate["id"]
            instant = (
                self.SIZE_WEIGHT * candidate["score"] / frame_area_ref
                + self.MOUTH_WEIGHT * self._mouth_motion(face_id)
            )
            previous = self.speaker_scores.get(face_id, instant)
            self.speaker_scores[face_id] = previous * 0.72 + instant * 0.28

        ranked = sorted(current, key=lambda item: self.speaker_scores.get(item["id"], 0.0), reverse=True)
        challenger = ranked[0]
        challenger_score = self.speaker_scores.get(challenger["id"], 0.0)
        active = next((item for item in current if item["id"] == self.active_speaker_id), None)
        active_score = self.speaker_scores.get(self.active_speaker_id, 0.0)

        # Ambiguous dialogue/reaction: keep both prominent faces centred. It is
        # deliberately disabled while one mouth score decisively wins.
        if self.group_enabled and len(ranked) >= 2:
            second = ranked[1]
            second_score = self.speaker_scores.get(second["id"], 0.0)
            first_center = ranked[0]["box"][0] + ranked[0]["box"][2] / 2
            second_center = second["box"][0] + second["box"][2] / 2
            if (
                challenger_score > 0
                and second_score / challenger_score >= self.group_score_ratio
                and abs(first_center - second_center) >= width * self.group_separation
            ):
                return _union_box(ranked[:2])

        if active is None:
            if self.active_speaker_id is not None and frame_number - self.last_switch_frame < self.switch_cooldown:
                return None
            self.active_speaker_id = challenger["id"]
            self.last_switch_frame = frame_number
            self.locked_counter = 0
            return challenger["box"]

        if challenger["id"] == self.active_speaker_id:
            self.locked_counter += 1
            return active["box"]

        cooldown_done = frame_number - self.last_switch_frame >= self.switch_cooldown
        decisive = challenger_score >= max(0.05, active_score * self.switch_margin)
        if cooldown_done and decisive:
            self.active_speaker_id = challenger["id"]
            self.last_switch_frame = frame_number
            self.locked_counter = 0
            return challenger["box"]

        return active["box"]
