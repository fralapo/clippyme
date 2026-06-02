import time
import cv2
import scenedetect
import subprocess
import argparse
import re
import sys
from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector
from ultralytics import YOLO
import torch
import os
import numpy as np
from tqdm import tqdm
import yt_dlp
import mediapipe as mp
# import whisper (replaced by faster_whisper inside function)
from google import genai
from dotenv import load_dotenv
import json

from clippyme.pipeline.reframe_ops import OneEuroFilter, drift_to_center, salient_crop_center

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module='google.protobuf')

# Load environment variables
load_dotenv()

# --- Constants ---
ASPECT_RATIO = 9 / 16
CACHE_DIR = os.path.join("data", "cache")
CACHE_TTL_DAYS = 7


def _get_cache_path(url):
    """Return cache file path for a URL, based on SHA256 hash."""
    import hashlib
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"{url_hash}_transcript.json")


def _load_cached_transcript(url):
    """Load a cached transcript if it exists and is not expired."""
    cache_path = _get_cache_path(url)
    if not os.path.exists(cache_path):
        return None
    try:
        mtime = os.path.getmtime(cache_path)
        if time.time() - mtime > CACHE_TTL_DAYS * 86400:
            os.remove(cache_path)
            return None
        with open(cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f"📦 Loaded cached transcript ({os.path.basename(cache_path)})")
        return data
    except Exception:
        return None


def _save_transcript_cache(url, transcript):
    """Save transcript to cache atomically (tmp + replace)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = _get_cache_path(url)
    tmp_path = cache_path + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(transcript, f)
        os.replace(tmp_path, cache_path)
        print(f"💾 Transcript cached ({os.path.basename(cache_path)})")
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        print(f"⚠️  Failed to cache transcript: {e}")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Test if CUDA actually works for faster-whisper (needs libcublas via ctranslate2).
# Creating the model is not enough — libcublas only loads during actual encoding.
CUDA_AVAILABLE = False
GPU_VRAM_GB = 0
if DEVICE == "cuda":
    try:
        from faster_whisper import WhisperModel as _WM
        import numpy as _np
        _m = _WM("tiny", device="cuda", compute_type="float16")
        _dummy = _np.zeros(16000, dtype=_np.float32)
        _m.transcribe(_dummy)
        del _m, _dummy
        CUDA_AVAILABLE = True
        GPU_VRAM_GB = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 1)
        print(f"✅ CUDA runtime verified — GPU {torch.cuda.get_device_name(0)} ({GPU_VRAM_GB}GB VRAM)")
    except Exception as e:
        CUDA_AVAILABLE = False
        print(f"⚠️  CUDA not usable for Whisper: {type(e).__name__} — using CPU")
else:
    print("ℹ️  No CUDA detected — using CPU")

# Auto-select Whisper model based on available hardware
# Models: tiny (39M) < base (74M) < small (244M) < medium (769M) < large-v3 (1.55B)
import psutil as _psutil_check
_total_ram_gb = round(_psutil_check.virtual_memory().total / (1024**3), 1)

if CUDA_AVAILABLE:
    if GPU_VRAM_GB >= 6:
        WHISPER_MODEL = "large-v3"
    elif GPU_VRAM_GB >= 3:
        WHISPER_MODEL = "medium"
    else:
        WHISPER_MODEL = "small"
else:
    if _total_ram_gb >= 16:
        WHISPER_MODEL = "medium"
    elif _total_ram_gb >= 8:
        WHISPER_MODEL = "small"
    else:
        WHISPER_MODEL = "base"

# Allow override via env var
WHISPER_MODEL = os.getenv("WHISPER_MODEL", WHISPER_MODEL)
print(f"🎙️  Whisper model: {WHISPER_MODEL} (auto-selected for {'GPU ' + str(GPU_VRAM_GB) + 'GB' if CUDA_AVAILABLE else 'CPU ' + str(_total_ram_gb) + 'GB RAM'})")

# Per-model pricing ($ per 1M tokens) — update when Google changes rates
MODEL_PRICING = {
    "gemini-2.5-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
}

GEMINI_PROMPT_TEMPLATE = """
You are a senior short-form video editor specialized in TikTok, IG Reels and YouTube Shorts virality. Read the ENTIRE transcript + word-level timestamps and select the 3–15 MOST VIRAL 15–60s moments.

## VIRAL_SCORE RUBRIC (1–100)
Score each axis from 1 to 20 and sum (cap at 100):
- HOOK_STRENGTH: do the first 2s grab attention? (pattern-break, bold claim, surprise)
- EMOTIONAL_PAYOFF: joy / shock / awe / rage / curiosity delivered?
- QUOTABILITY: is there a line viewers would screenshot or repeat?
- SELF_CONTAINED: makes sense without context from the rest of the video?
- DENSITY: no dead air, no rambling, every second earns its place.

## SPEAKER SIGNAL (when available)
Each segment may carry a ``speaker`` integer (0, 1, 2…) from speaker
diarization. When present, use it as a boundary hint:
- Prefer cutting on speaker TURN CHANGES for dialogues / interviews — a
  turn change is a natural editing beat and resets viewer attention.
- For monologues, prefer clips where ONE speaker dominates (less context
  switching = higher SELF_CONTAINED score).
- Never start a clip mid-turn of speaker A if the hook actually belongs
  to speaker B's next utterance.
Diarization is optional — absence of ``speaker`` fields means single
speaker or Whisper fallback path, score normally.

## HARD CONSTRAINTS (violating = clip REJECTED)
- 15s ≤ duration ≤ 60s
- start on a complete sentence boundary; end on a natural beat
- no cold-open ambiguity ("...and then she said" with no setup)
- 0 ≤ start < end ≤ VIDEO_DURATION_SECONDS
- start and end are FLOAT SECONDS with up to 3 decimals (e.g. 12.340, 1517.724).
  NEVER emit "MM.SS.mmm" (e.g. 25.17.724), "MM:SS", "HH:MM:SS", or any two-dot / colon
  time format. A value of 1517.724 is correct; "25.17.724" is a BUG.
- Prefer starting 0.2–0.4s BEFORE the hook and ending 0.2–0.4s AFTER the payoff
- Never cut in the middle of a word or phrase
- viral_reason MUST be at least 20 characters and cite the specific hook, payoff or quote
- viral_hook_text is REQUIRED, NEVER empty: 3-8 words, written AS A SCROLL-STOPPING OVERLAY — NOT a transcript quote, NOT the first words the speaker says. It is standalone copywriting designed to make someone stop scrolling on TikTok/Reels. Use one of these proven patterns:
    * Curiosity gap: "Nessuno ti dice questo", "What they don't want you to know"
    * POV / relatable: "POV: sei il primo a scoprirlo", "POV: you just realized…"
    * Counter-intuitive claim: "Stavo sbagliando tutto", "I was doing it wrong"
    * Direct question: "E se fosse tutto falso?", "What if you're wrong?"
    * Number / stakes: "3 cose che nessuno dice", "3 things nobody tells you"
    * Warning / callout: "Non guardare se…", "Stop scrolling if…"
  The hook must TEASE the content of the clip without spoiling the payoff. Same language as the transcript. Title Case or Sentence case, never ALL CAPS.
- No generic intros/outros or pure sponsorship unless they ARE the hook

## LANGUAGE RULE
Every text field (viral_reason, descriptions, titles, hook_text) MUST be in the SAME LANGUAGE as the transcript.

## FEW-SHOT EXAMPLES
GOOD (score 87):
  start=12.340 end=37.900
  viral_reason="Opens with 'Everyone lies about this' — pattern-break hook, then delivers a counter-intuitive reveal with a clean payoff line at 34s viewers will quote."
  viral_hook_text="The lie everyone believes"          ← teaser, NOT the literal opening line

GOOD (score 78):
  start=102.500 end=148.200
  viral_reason="Builds tension with three failed attempts then lands a punchline at 140s — classic rule-of-three payoff structure perfect for Reels."
  viral_hook_text="I failed 3 times before this"      ← number + stakes, standalone overlay

BAD hooks (DO NOT emit these — they literally echo the transcript):
  "Hello everyone welcome back"          ← transcript intro, not a hook
  "So today I wanted to talk about"      ← filler, no curiosity gap
  "And then what happened next was"      ← mid-sentence fragment

BAD (would score ~30 — DO NOT emit anything like this):
  viral_reason="Interesting point about the topic"   ← too generic, no hook, no payoff specified

## VIDEO METADATA
VIDEO_DURATION_SECONDS: {video_duration}

TRANSCRIPT_TEXT (raw):
{transcript_text}

WORDS_JSON (array of {{w, s, e}} where s/e are seconds):
{words_json}

{user_instructions_block}

## OUTPUT CONTRACT (READ CAREFULLY)
1. First think step-by-step internally about candidate moments.
2. Then, on its own line, emit the LITERAL delimiter `### JSON ###`.
3. Then emit ONLY the JSON object — no markdown, no code fences, no prose after.

JSON formatting rules (violating = parse failure):
- Escape every backslash as \\\\ inside strings
- Use straight double quotes " only — NO curly/smart quotes
- No trailing commas before }} or ]
- Strings stay on a single line (no raw \\n mid-string)
- In the descriptions, ALWAYS include a CTA like "Follow me and comment X and I'll send you the workflow"

Output schema:
### JSON ###
{{
  "shorts": [
    {{
      "start": 12.340,
      "end": 37.900,
      "viral_score": 87,
      "viral_reason": "<>=20 chars, cite specific hook/payoff/quote, same language as transcript>",
      "video_description_for_tiktok": "<TikTok description with CTA>",
      "video_description_for_instagram": "<Instagram description with CTA>",
      "video_title_for_youtube_short": "<max 100 chars>",
      "viral_hook_text": "<REQUIRED, 3-8 words, scroll-stopping overlay copy — NOT a transcript quote. Use curiosity gap, POV, counter-claim, question, number, or warning pattern. Same language as transcript.>"
    }}
  ]
}}
"""

# YOLO is lazy-loaded on first use. Keeping the model at import time
# forced every entry-point (including --reframe-only, which never calls
# detect_person_yolo) to pay the load + GPU transfer cost on startup.
_yolo_model = None


def _get_yolo_model():
    """Lazy-load YOLOv8n on first body-detection call."""
    global _yolo_model
    if _yolo_model is None:
        _yolo_model = YOLO('yolov8n.pt')
        _yolo_model.to(DEVICE)
    return _yolo_model


# Whisper models are expensive to construct (weights load + device placement),
# so cache one per (model, device, compute_type) for the life of the process.
# Batch jobs re-using the same config reuse the loaded model instead of paying
# the init cost on every clip.
_whisper_models: dict = {}


def _get_whisper_model(model_name, device, compute_type):
    """Lazy-load + cache a faster-whisper model keyed by its config."""
    from faster_whisper import WhisperModel
    key = (model_name, device, compute_type)
    if key not in _whisper_models:
        _whisper_models[key] = WhisperModel(model_name, device=device, compute_type=compute_type)
    return _whisper_models[key]

# --- MediaPipe Setup ---
# Use standard Face Detection (BlazeFace) for speed
mp_face_detection = mp.solutions.face_detection
face_detection = mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)

# FaceMesh is used to extract mouth landmarks for active-speaker detection.
# We process small ROIs (the face crop), not the full frame, to keep cost low.
# refine_landmarks=False keeps it fast (478 → 468 landmarks).
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=False,
    max_num_faces=1,
    refine_landmarks=False,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)

# MediaPipe FaceMesh landmark indices for the mouth region
# Upper lip top, lower lip bottom, left mouth corner, right mouth corner
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

        # Safe zones (dead-band to kill jitter)
        self.safe_zone_radius_x = self.max_crop_width * 0.20
        self.safe_zone_radius_y = self.max_crop_height * 0.15

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
        self._use_euro = os.getenv("REFRAME_SMOOTHER", "").strip().lower() == "euro"
        if self._use_euro:
            mc = float(os.getenv("REFRAME_EURO_MINCUTOFF", "0.014"))
            beta = float(os.getenv("REFRAME_EURO_BETA", "0.0008"))
            self._euro_x = OneEuroFilter(min_cutoff=mc, beta=beta)
            self._euro_y = OneEuroFilter(min_cutoff=mc, beta=beta)

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
            # wide shot) trigger more zoom; large faces stay at 1.0.
            face_height_ratio = h / self.video_height
            if face_height_ratio < 0.15:
                self.target_zoom = 1.5  # tight zoom
            elif face_height_ratio < 0.25:
                self.target_zoom = 1.3  # medium zoom
            elif face_height_ratio < 0.4:
                self.target_zoom = 1.15  # gentle zoom
            else:
                self.target_zoom = 1.0  # no zoom (face already fills frame)

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

            if self._use_euro:
                # Apply the dead-band on the target, then 1€-filter every frame
                # (feeding the filter each frame keeps its velocity estimate live).
                tx = self.target_center_x if abs(self.target_center_x - self.current_center_x) > self.safe_zone_radius_x else self.current_center_x
                ty = self.target_center_y if abs(self.target_center_y - self.current_center_y) > self.safe_zone_radius_y else self.current_center_y
                self.current_center_x = self._euro_x.filter(tx, 1.0)
                self.current_center_y = self._euro_y.filter(ty, 1.0)
            else:
                self.current_center_x = self._ease_axis(
                    self.current_center_x, self.target_center_x,
                    self.safe_zone_radius_x, self.max_crop_width,
                )
                self.current_center_y = self._ease_axis(
                    self.current_center_y, self.target_center_y,
                    self.safe_zone_radius_y, self.max_crop_height,
                )
            # Zoom animates more slowly than position to feel cinematic
            zoom_diff = self.target_zoom - self.current_zoom
            if abs(zoom_diff) > 0.01:
                self.current_zoom += zoom_diff * 0.05

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

def detect_scenes(video_path):
    # PySceneDetect v0.6+ API — VideoManager was removed. `open_video` returns
    # a VideoStream that SceneManager consumes directly.
    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector())
    scene_manager.detect_scenes(video=video)
    scene_list = scene_manager.get_scene_list()
    fps = video.frame_rate
    return scene_list, fps

def get_video_resolution(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Could not open video file {video_path}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return width, height


def sanitize_filename(filename):
    """Remove invalid characters from filename."""
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = filename.replace(' ', '_')
    return filename[:100]


def _resolve_cookies_path(explicit: str | None) -> str | None:
    """Resolve the cookies.txt path used by yt-dlp.

    Precedence:
      1. Explicit path passed on the CLI / by the caller.
      2. Repo-root ``data/cookies.txt`` (the path the dashboard writes to).
      3. ``YOUTUBE_COOKIES`` env var → materialized into ``data/cookies_env.txt``.
      4. None (no cookies).

    The repo-root resolution uses the current working directory, which
    matches how the FastAPI backend and the Docker container launch the
    pipeline (both run from the repo root). This replaces the pre-refactor
    ``os.path.dirname(__file__)`` logic that silently pointed at
    ``src/clippyme/pipeline/data/`` after the src-layout migration.
    """
    if explicit:
        return explicit
    repo_root_cookies = os.path.join("data", "cookies.txt")
    if os.path.exists(repo_root_cookies):
        return os.path.abspath(repo_root_cookies)
    env_cookies = os.environ.get("YOUTUBE_COOKIES")
    if env_cookies:
        env_path = os.path.join("data", "cookies_env.txt")
        os.makedirs(os.path.dirname(env_path) or ".", exist_ok=True)
        with open(env_path, "w") as f:
            f.write(env_cookies)
        return os.path.abspath(env_path)
    return None


def download_youtube_video(url, output_dir=".", cookies_file_path=None):
    """
    Downloads a YouTube video using yt-dlp.
    Returns the path to the downloaded video and the video title.
    """
    print(f"🔍 Debug: yt-dlp version: {yt_dlp.version.__version__}")
    print("📥 Downloading video from YouTube...")
    step_start_time = time.time()

    cookies_path = _resolve_cookies_path(cookies_file_path)
    if cookies_path:
        print(f"🍪 Using cookies file: {cookies_path}")
    else:
        print("⚠️ No cookies file found.")
    
    # Common yt-dlp options to work around YouTube bot detection.
    # Avoid the OAuth/PO-token checks that block server IPs.
    _COMMON_YDL_OPTS = {
        'quiet': False,
        'verbose': True,
        'no_warnings': False,
        'cookiefile': cookies_path if cookies_path else None,
        'socket_timeout': 30,
        'retries': 10,
        'fragment_retries': 10,
        # SSL verification stays ON (security) — previously disabled. If a
        # legitimate cert chain issue resurfaces in a sandbox, set the
        # YTDLP_NOCHECKCERT=1 env var to opt out temporarily.
        'nocheckcertificate': os.environ.get('YTDLP_NOCHECKCERT') == '1',
        # Detect YouTube's per-fragment throttling and re-fetch the slow
        # segment. Threshold is bytes/sec — 100 KB/s catches the 16-23h
        # evening throttle window without tripping on legit slow networks.
        'throttledratelimit': int((os.environ.get('YTDLP_THROTTLED_RATE') or '').strip() or 100 * 1024),
        'cachedir': False,
        'remote_components': ['ejs:github'],
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
        },
    }

    with yt_dlp.YoutubeDL(_COMMON_YDL_OPTS) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            video_title = info.get('title', 'youtube_video')
            sanitized_title = sanitize_filename(video_title)
        except Exception as e:
            # Force print to stderr/stdout immediately so it's captured before crash
            import sys
            import traceback
            
            # Print minimal error first to ensure something gets out
            print("🚨 YOUTUBE DOWNLOAD ERROR 🚨", file=sys.stderr)
            
            error_msg = f"""
            
❌ ================================================================= ❌
❌ FATAL ERROR: YOUTUBE DOWNLOAD FAILED
❌ ================================================================= ❌
            
REASON: YouTube has blocked the download request (Error 429/Unavailable).
        This is likely a temporary IP ban on this server.

👇 SOLUTION FOR USER 👇
---------------------------------------------------------------------
1. Download the video manually to your computer.
2. Use the 'Upload Video' tab in this app to process it.
---------------------------------------------------------------------

Technical Details: {str(e)}
            """
            # Print to both streams to ensure capture
            print(error_msg, file=sys.stdout)
            print(error_msg, file=sys.stderr)
            
            # Force flush
            sys.stdout.flush()
            sys.stderr.flush()
            
            # Wait a split second to allow buffer to drain before raising
            time.sleep(0.5)
            
            raise e
    
    output_template = os.path.join(output_dir, f'{sanitized_title}.%(ext)s')
    expected_file = os.path.join(output_dir, f'{sanitized_title}.mp4')
    if os.path.exists(expected_file):
        os.remove(expected_file)
        print(f"🗑️  Removed existing file to re-download with H.264 codec")
    
    ydl_opts = {
        **_COMMON_YDL_OPTS,
        'format': 'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[vcodec^=avc1]+bestaudio/best[ext=mp4]/best',
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'overwrites': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    downloaded_file = os.path.join(output_dir, f'{sanitized_title}.mp4')
    
    if not os.path.exists(downloaded_file):
        for f in os.listdir(output_dir):
            if f.startswith(sanitized_title) and f.endswith('.mp4'):
                downloaded_file = os.path.join(output_dir, f)
                break
    
    step_end_time = time.time()
    print(f"✅ Video downloaded in {step_end_time - step_start_time:.2f}s: {downloaded_file}")
    
    return downloaded_file, sanitized_title

def normalize_audio(video_path):
    """
    Two-pass EBU R128 loudness normalization to -14 LUFS (social media standard).
    Normalizes in-place by creating a temp file and replacing.
    """
    import tempfile
    temp_out = video_path + ".norm.mp4"
    try:
        # Pass 1: Analyze
        analyze_cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-af', 'loudnorm=I=-14:TP=-1.5:LRA=7:print_format=json',
            '-f', 'null', os.devnull
        ]
        result = subprocess.run(analyze_cmd, capture_output=True, text=True)
        # Parse measured values from stderr (loudnorm outputs JSON at the end)
        stderr = result.stderr
        json_start = stderr.rfind('{')
        json_end = stderr.rfind('}') + 1
        if json_start < 0 or json_end <= json_start:
            print("⚠️  Audio normalization: could not parse loudnorm analysis, skipping")
            return
        measured = json.loads(stderr[json_start:json_end])

        # Pass 2: Apply
        apply_cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-af', (
                f"loudnorm=I=-14:TP=-1.5:LRA=7"
                f":measured_I={measured['input_i']}"
                f":measured_TP={measured['input_tp']}"
                f":measured_LRA={measured['input_lra']}"
                f":measured_thresh={measured['input_thresh']}"
                f":offset={measured['target_offset']}"
                f":linear=true"
            ),
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k',
            temp_out
        ]
        norm_result = subprocess.run(apply_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if norm_result.returncode == 0 and os.path.exists(temp_out):
            os.replace(temp_out, video_path)
            print(f"🔊 Audio normalized to -14 LUFS: {os.path.basename(video_path)}")
        else:
            print(f"⚠️  Audio normalization failed, keeping original audio")
            if os.path.exists(temp_out):
                os.remove(temp_out)
    except Exception as e:
        print(f"⚠️  Audio normalization error: {e}")
        if os.path.exists(temp_out):
            os.remove(temp_out)


def apply_subtle_zoom(video_path, zoom_end=1.05):
    """
    Apply a subtle Ken Burns zoom (1.0x → zoom_end over the clip duration).
    Creates visual motion even on static shots, improving viewer retention.
    Operates in-place.
    """
    temp_out = video_path + ".zoom.mp4"
    try:
        # Get video info
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height,r_frame_rate,nb_frames',
             '-of', 'csv=s=x:p=0', video_path],
            capture_output=True, text=True
        )
        parts = probe.stdout.strip().split('x')
        if len(parts) < 3:
            return
        w, h = int(parts[0]), int(parts[1])
        # r_frame_rate is like "30/1" or "30000/1001"
        fps_parts = parts[2].split('/')
        fps = int(fps_parts[0]) / int(fps_parts[1]) if len(fps_parts) == 2 else float(fps_parts[0])
        total_frames = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

        if total_frames <= 0 or fps <= 0:
            return

        # Zoom increment per frame: from 1.0 to zoom_end over total_frames
        zoom_per_frame = (zoom_end - 1.0) / total_frames

        zoom_filter = (
            f"zoompan=z='1+{zoom_per_frame:.8f}*on'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={w}x{h}:fps={fps}"
        )

        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', zoom_filter,
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '23',
            '-c:a', 'copy', temp_out
        ]
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if result.returncode == 0 and os.path.exists(temp_out):
            os.replace(temp_out, video_path)
            print(f"🔍 Subtle zoom applied (1.0→{zoom_end}x): {os.path.basename(video_path)}")
        else:
            if os.path.exists(temp_out):
                os.remove(temp_out)
    except Exception as e:
        print(f"⚠️  Subtle zoom failed (non-critical): {e}")
        if os.path.exists(temp_out):
            os.remove(temp_out)


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


def process_video_to_vertical(input_video, final_output_video, reframe_mode='auto'):
    """
    Core logic to convert horizontal video to vertical using scene detection and Active Speaker Tracking (MediaPipe).
    """
    script_start_time = time.time()
    
    # Define temporary file paths based on the output name
    base_name = os.path.splitext(final_output_video)[0]
    temp_video_output = f"{base_name}_temp_video.mp4"
    temp_audio_output = f"{base_name}_temp_audio.aac"
    
    # Clean up previous temp files if they exist
    if os.path.exists(temp_video_output): os.remove(temp_video_output)
    if os.path.exists(temp_audio_output): os.remove(temp_audio_output)
    if os.path.exists(final_output_video): os.remove(final_output_video)

    print(f"🎬 Processing clip: {input_video}")
    if reframe_mode == 'disabled':
        print("   🚫 Reframe mode: DISABLED — clip placed inside a 9:16 frame with letterbox (black bars top & bottom).")
        print("      (Scene detection still runs for consistency; face tracking is skipped.)")
    else:
        print("   🎯 Reframe mode: AUTO — face tracking + dynamic 9:16 crop.")
    print("   Step 1: Detecting scenes...")
    scenes, fps = detect_scenes(input_video)
    
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
        '-preset', 'fast', '-crf', '23', '-an', temp_video_output
    ]

    ffmpeg_process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    cap = cv2.VideoCapture(input_video)
    stderr_output = ""
    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
        frame_number = 0
        current_scene_index = 0
    
        # Pre-calculate scene boundaries
        scene_boundaries = []
        for s_start, s_end in scenes:
            scene_boundaries.append((s_start.get_frames(), s_end.get_frames()))

        # Global tracker for single-person shots
        # Cooldown of 45 frames (~1.5s @ 30fps) protects against rapid back-and-forth
        # switching in WIDE multi-speaker scenes (interview/podcast botta-risposta).
        speaker_tracker = SpeakerTracker(cooldown_frames=45)
        detection_smoother = DetectionSmoother(window_size=5)

        with tqdm(total=total_frames, desc="   Processing", file=sys.stdout) as pbar:
            while cap.isOpened():
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
            
                # Apply Strategy
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

                ffmpeg_process.stdin.write(output_frame.tobytes())
                frame_number += 1
                pbar.update(1)
    
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
    audio_extract_command = [
        'ffmpeg', '-y', '-i', input_video, '-vn', '-acodec', 'copy', temp_audio_output
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
            '-c:v', 'copy', '-c:a', 'copy', final_output_video
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
    
    return True

def _diarize_with_pyannote(audio_path: str) -> list[tuple[float, float, int]] | None:
    """Run pyannote.audio speaker-diarization-3.1 on a local audio file.

    Returns a list of ``(start, end, speaker_int)`` tuples in chronological
    order, or ``None`` if diarization is disabled / unavailable / fails.

    Gating:
      - ``WHISPER_DIARIZE=false`` → skip entirely (fast path).
      - pyannote.audio not installed → soft warning + skip (no crash).
      - ``HUGGINGFACE_TOKEN`` missing → warning + skip (the model is gated).

    This keeps pyannote as a fully optional dependency: users who want
    speaker diarization on the Whisper path install it manually via
    ``pip install pyannote.audio>=3.1`` and accept the
    ``pyannote/speaker-diarization-3.1`` license on Hugging Face. The
    rest of the pipeline keeps working with or without speakers.
    """
    if (os.getenv("WHISPER_DIARIZE") or "true").strip().lower() == "false":
        return None

    hf_token = (
        os.getenv("HUGGINGFACE_TOKEN")
        or os.getenv("HF_TOKEN")
        or ""
    ).strip()
    if not hf_token:
        print(
            "   ⚠️  Whisper diarization skipped: HUGGINGFACE_TOKEN not set "
            "(required to download pyannote/speaker-diarization-3.1)."
        )
        return None

    try:
        from pyannote.audio import Pipeline as _PyannotePipeline  # type: ignore
    except ImportError:
        print(
            "   ⚠️  Whisper diarization skipped: pyannote.audio not installed. "
            "Install with `pip install pyannote.audio>=3.1` and accept the "
            "pyannote/speaker-diarization-3.1 license on Hugging Face."
        )
        return None

    try:
        print("   🗣️  Running pyannote speaker diarization (may take a while)…")
        t0 = time.time()
        pipeline = _PyannotePipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
        if CUDA_AVAILABLE:
            try:
                import torch  # type: ignore
                pipeline.to(torch.device("cuda"))
            except Exception:  # noqa: BLE001
                pass
        diarization = pipeline(audio_path)
    except Exception as exc:  # noqa: BLE001 — any pyannote failure is non-fatal
        print(f"   ⚠️  Whisper diarization failed ({exc}); continuing without speakers.")
        return None

    # Normalize pyannote output into (start, end, speaker_int) tuples.
    # pyannote emits labels like "SPEAKER_00", "SPEAKER_01" — map to ints
    # so the downstream shape matches Deepgram's.
    label_to_int: dict[str, int] = {}
    turns: list[tuple[float, float, int]] = []
    for turn, _, label in diarization.itertracks(yield_label=True):
        if label not in label_to_int:
            label_to_int[label] = len(label_to_int)
        turns.append((float(turn.start), float(turn.end), label_to_int[label]))
    turns.sort(key=lambda t: t[0])

    elapsed = time.time() - t0
    n_speakers = len(label_to_int)
    print(
        f"   ✅ pyannote OK — {len(turns)} turns, {n_speakers} speakers, "
        f"wall={elapsed:.1f}s"
    )
    return turns


def _assign_speakers_to_words(
    words: list[dict],
    turns: list[tuple[float, float, int]],
) -> None:
    """Merge diarization turns into Whisper words by maximum overlap.

    Mutates ``words`` in place, adding a ``speaker`` key where a matching
    turn exists. Words that fall outside every turn (silence, non-speech)
    are left untouched. Runs in O(n+m) thanks to the ordered walk.
    """
    if not words or not turns:
        return
    # Sort words by start (Whisper generally emits them ordered, but the
    # cost is marginal and guarantees the two-pointer walk is correct).
    words.sort(key=lambda w: float(w.get("start", 0.0)))

    ti = 0
    for w in words:
        try:
            ws = float(w.get("start", 0.0))
            we = float(w.get("end", ws))
        except (TypeError, ValueError):
            continue

        # Advance ti until the current turn could still overlap this word.
        while ti < len(turns) and turns[ti][1] < ws:
            ti += 1
        if ti >= len(turns):
            break

        # Find the turn with the maximum overlap against [ws, we]. Because
        # turns are sorted and mostly non-overlapping (diarization emits
        # contiguous turns), at most 2-3 candidates need to be checked.
        best_speaker: int | None = None
        best_overlap = 0.0
        j = ti
        while j < len(turns) and turns[j][0] <= we:
            ts, te, sp = turns[j]
            overlap = max(0.0, min(te, we) - max(ts, ws))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = sp
            j += 1

        if best_speaker is not None:
            w["speaker"] = best_speaker


def _extract_audio_to_wav(video_path: str) -> str | None:
    """ffmpeg-extract a mono 16 kHz WAV next to the source video.

    pyannote.audio needs a plain WAV (won't accept .mp4 directly), so we
    produce a temp file and return its path. Returns ``None`` if ffmpeg
    is missing or the extraction fails — caller should skip diarization.
    """
    out_path = os.path.join(
        os.path.dirname(os.path.abspath(video_path)) or ".",
        f".diarize_{int(time.time())}_{os.getpid()}.wav",
    )
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", video_path,
                "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le",
                out_path,
            ],
            check=True,
        )
        return out_path
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"   ⚠️  Could not extract audio for diarization: {exc}")
        return None


def transcribe_video(video_path):
    """Dispatch to the configured transcription provider.

    Provider is selected via the ``TRANSCRIPTION_PROVIDER`` env var:
      - "deepgram" → call Deepgram REST API (requires DEEPGRAM_API_KEY)
      - anything else (default) → local Faster-Whisper

    On Deepgram failure we automatically fall back to Faster-Whisper so a
    misconfigured key never breaks the pipeline.

    Whisper path: after transcription, optionally runs pyannote speaker
    diarization (if ``pyannote.audio`` is installed and a HF token is
    available) and merges speaker labels into the word timestamps so the
    downstream Gemini prompt + subtitle writer see the same ``speaker``
    field as the Deepgram path.
    """
    provider = (os.getenv("TRANSCRIPTION_PROVIDER") or "deepgram").strip().lower()
    if provider == "deepgram":
        try:
            from clippyme.pipeline.deepgram_transcribe import transcribe_with_deepgram, DeepgramError
            return transcribe_with_deepgram(video_path)
        except Exception as exc:  # noqa: BLE001 — broad catch for safe fallback
            print(f"⚠️  Deepgram transcription failed ({exc}); falling back to Faster-Whisper.")

    device = "cuda" if CUDA_AVAILABLE else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    print(f"🎙️  Transcribing with Faster-Whisper [{WHISPER_MODEL}] ({device.upper()} mode)...")
    model = _get_whisper_model(WHISPER_MODEL, device, compute_type)
    # Honor per-job language override (set by main.py --language → CLIPPYME_LANGUAGE).
    # 'multi' / '' / unset → let Faster-Whisper auto-detect.
    _lang_override = (os.getenv("CLIPPYME_LANGUAGE") or "").strip().lower()
    _whisper_lang = _lang_override if _lang_override and _lang_override != "multi" else None
    if _whisper_lang:
        print(f"   🌐 Whisper language override: {_whisper_lang}")
    segments, info = model.transcribe(
        video_path, word_timestamps=True, language=_whisper_lang
    )
    segments = list(segments)

    print(f"   Detected language '{info.language}' with probability {info.language_probability:.2f}")

    # Convert to openai-whisper compatible format
    transcript_segments = []
    full_text = ""

    for segment in segments:
        # Print progress to keep user informed (and prevent timeouts feeling)
        print(f"   [{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")

        seg_dict = {
            'text': segment.text,
            'start': segment.start,
            'end': segment.end,
            'words': []
        }

        if segment.words:
            for word in segment.words:
                seg_dict['words'].append({
                    'word': word.word,
                    'start': word.start,
                    'end': word.end,
                    'probability': word.probability
                })

        transcript_segments.append(seg_dict)
        full_text += segment.text + " "

    # --- Optional speaker diarization (pyannote.audio) ------------------
    # Runs only when pyannote is installed AND HF token is set AND
    # WHISPER_DIARIZE != "false". Short-circuit BEFORE extracting audio
    # so we don't pay the ffmpeg cost when diarization is disabled.
    wav_tmp: str | None = None
    diarize_enabled = (
        (os.getenv("WHISPER_DIARIZE") or "true").strip().lower() != "false"
        and bool((os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN") or "").strip())
    )
    try:
        if diarize_enabled:
            wav_tmp = _extract_audio_to_wav(video_path)
        if wav_tmp:
            turns = _diarize_with_pyannote(wav_tmp)
            if turns:
                # Flatten words, merge speakers, then distribute back to
                # their parent segments via majority vote.
                flat_words: list[dict] = []
                for seg in transcript_segments:
                    flat_words.extend(seg.get("words") or [])
                _assign_speakers_to_words(flat_words, turns)

                for seg in transcript_segments:
                    counts: dict[int, int] = {}
                    for w in seg.get("words") or []:
                        sp = w.get("speaker")
                        if sp is None:
                            continue
                        counts[sp] = counts.get(sp, 0) + 1
                    if counts:
                        seg["speaker"] = max(counts, key=counts.get)

                speakers_seen = {sp for _, _, sp in turns}
                print(f"   🗣️  Whisper transcript enriched with {len(speakers_seen)} speaker label(s).")
    finally:
        if wav_tmp and os.path.exists(wav_tmp):
            try:
                os.remove(wav_tmp)
            except OSError:
                pass

    return {
        'text': full_text.strip(),
        'segments': transcript_segments,
        'language': info.language
    }

def get_viral_clips(transcript_result, video_duration, instructions=None):
    print("🤖  Analyzing with Gemini...")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: GEMINI_API_KEY not found in environment variables.")
        return None

    client = genai.Client(api_key=api_key)
    
    # Use selected model from env, or default to gemini-2.5-flash
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash") 
    
    print(f"🤖  Initializing Gemini with model: {model_name}")

    if any(old in model_name for old in ("1.0", "1.5", "2.0")):
        print(f"⚠️  WARNING: {model_name} is deprecated. Please switch to gemini-2.5-flash or later via the dashboard.")

    # Extract words
    words = []
    for segment in transcript_result['segments']:
        for word in segment.get('words', []):
            words.append({
                'w': word['word'],
                's': word['start'],
                'e': word['end']
            })

    user_instructions_block = ""
    if instructions:
        user_instructions_block = f"USER INSTRUCTIONS (follow these priorities when selecting clips):\n{instructions}"

    prompt = GEMINI_PROMPT_TEMPLATE.format(
        video_duration=video_duration,
        transcript_text=json.dumps(transcript_result.get('text', '')),
        words_json=json.dumps(words),
        user_instructions_block=user_instructions_block
    )

    # Retry with exponential backoff for rate limits / transient errors.
    # 429 (quota) gets a longer base backoff because Google's "wait N
    # seconds" signal lives in the error message rather than structured
    # metadata in the python SDK — we can't honor it precisely, but we
    # can at least slow down instead of retrying immediately.
    response = None
    max_attempts = int(os.getenv("GEMINI_MAX_RETRIES", "3") or "3")
    for attempt in range(max_attempts):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            break
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = (
                "429" in err_str
                or "rate limit" in err_str
                or "quota" in err_str
                or "resource_exhausted" in err_str
            )
            # 429 → 10s / 20s / 40s; transient → 2s / 4s / 8s
            base = 10 if is_rate_limit else 2
            wait = base * (2 ** attempt)
            if attempt < max_attempts - 1:
                reason = "rate-limited" if is_rate_limit else "transient error"
                print(
                    f"⚠️  Gemini API {reason} (attempt {attempt + 1}/{max_attempts}): "
                    f"{e}. Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                print(f"❌ Gemini API failed after {max_attempts} attempts: {e}")
                return None

    if response is None:
        return None

    # --- Cost Calculation ---
    cost_analysis = None
    try:
        usage = response.usage_metadata
        if usage:
            pricing = MODEL_PRICING.get(model_name, None)
            input_price_per_million = pricing["input"] if pricing else 0.0
            output_price_per_million = pricing["output"] if pricing else 0.0

            prompt_tokens = usage.prompt_token_count
            output_tokens = usage.candidates_token_count

            input_cost = (prompt_tokens / 1_000_000) * input_price_per_million
            output_cost = (output_tokens / 1_000_000) * output_price_per_million
            total_cost = input_cost + output_cost

            cost_analysis = {
                "input_tokens": prompt_tokens,
                "output_tokens": output_tokens,
                "input_cost": input_cost,
                "output_cost": output_cost,
                "total_cost": total_cost,
                "model": model_name
            }
            if not pricing:
                cost_analysis["note"] = "Pricing not available for this model"

            print(f"💰 Token Usage ({model_name}):")
            print(f"   - Input Tokens: {prompt_tokens} (${input_cost:.6f})")
            print(f"   - Output Tokens: {output_tokens} (${output_cost:.6f})")
            print(f"   - Total Estimated Cost: ${total_cost:.6f}")
    except Exception as e:
        print(f"⚠️ Could not calculate cost: {e}")

    # Parse response JSON via the 5-level chain in gemini_parser.
    # See CLAUDE.md section "Gemini viral detection — parsing chain".
    try:
        from clippyme.pipeline.gemini_parser import parse_gemini_response, validate_and_dedupe, backfill_hook_text
        from pydantic import ValidationError

        text = response.text or ""

        def _retry_gemini(err_msg: str) -> str:
            """Level-4 retry: reformat ONLY, using the cheap flash model.

            The reasoning is already done in the primary call — if it
            produced text we just failed to parse, the bottleneck is
            formatting, not understanding. Decouple the two concerns
            (Gopalan, Google Cloud Community, Oct 2025) and hand the
            retry to gemini-2.5-flash which is ~10x cheaper than pro
            and plenty capable of reformatting JSON.

            Crucially, we do NOT resend the full transcript + prompt:
            we hand the model ONLY the previous broken output and ask
            it to reformat. That avoids paying the input-token cost of
            the transcript twice and keeps the retry latency-bounded.
            """
            retry_model = os.getenv("GEMINI_RETRY_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"
            retry_prompt = (
                "You are a JSON reformatter. The previous response below was not "
                "valid JSON and failed parsing with this error:\n\n"
                f"ERROR: {err_msg}\n\n"
                "PREVIOUS_BROKEN_OUTPUT:\n"
                f"{text}\n\n"
                "Return ONLY a valid JSON object matching this exact shape:\n"
                '{"shorts": [{"start": <float>, "end": <float>, '
                '"viral_score": <int 1-100>, "viral_reason": "<str min 20 chars>", '
                '"video_description_for_tiktok": "<str>", '
                '"video_description_for_instagram": "<str>", '
                '"video_title_for_youtube_short": "<str>", '
                '"viral_hook_text": "<str>"}]}\n\n'
                "Rules: straight double quotes only, no trailing commas, no markdown, "
                "no code fences, no prose before or after. Escape every backslash as \\\\."
            )
            try:
                retry_resp = client.models.generate_content(
                    model=retry_model,
                    contents=retry_prompt,
                )
                print(f"🔁 Retry via {retry_model} (cheap reformatter)")
                return retry_resp.text or ""
            except Exception as e:
                print(f"⚠️  Gemini retry failed: {e}")
                return ""

        parse_result = parse_gemini_response(
            text,
            retry_fn=_retry_gemini,
            request_id=os.urandom(4).hex(),
        )

        # Structured log line for observability.
        print(
            f"📊 gemini_parse path={parse_result.parse_path} "
            f"duration_ms={parse_result.duration_ms:.1f} "
            f"error={parse_result.error or 'none'}"
        )

        if parse_result.data is None:
            print(f"❌ Failed to parse Gemini response: {parse_result.error}")
            return None

        try:
            clips = validate_and_dedupe(
                parse_result.data,
                video_duration=video_duration,
                overlap_threshold=0.7,
                drop_generic=True,
            )
        except ValidationError as e:
            print(f"❌ Pydantic validation failed: {e}")
            return None

        if not clips:
            print("❌ No valid clips after Pydantic validation + dedupe")
            return None

        # Ensure every clip has a viral_hook_text. Logic lives in
        # gemini_parser.backfill_hook_text so both the main pipeline AND
        # the metadata-reload path in job_results.py use the exact same
        # strategy (no drift between live runs and restored jobs).
        backfill_hook_text(clips, words)

        print(f"✅ {len(clips)} clips passed validation + dedupe")
        result_json = {"shorts": clips}
        if cost_analysis:
            result_json["cost_analysis"] = cost_analysis
        return result_json
    except Exception as e:
        print(f"❌ Unexpected error in Gemini response processing: {e}")
        return None

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="AutoCrop-Vertical with Viral Clip Detection.")
    
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('-i', '--input', type=str, help="Path to the input video file.")
    input_group.add_argument('-u', '--url', type=str, help="YouTube URL to download and process.")
    
    parser.add_argument('-o', '--output', type=str, help="Output directory or file (if processing whole video).")
    parser.add_argument('--keep-original', action='store_true', help="Keep the downloaded YouTube video.")
    parser.add_argument('--skip-analysis', action='store_true', help="Skip AI analysis and convert the whole video.")
    parser.add_argument('-c', '--cookies', type=str, help="Path to cookies.txt file for yt-dlp")
    parser.add_argument('--instructions', type=str, help="Custom instructions for AI clip selection (e.g., 'find the funniest parts')")
    parser.add_argument('--no-zoom', action='store_true', help="Disable subtle auto-zoom effect on clips")
    parser.add_argument('--reframe-mode', choices=['auto', 'disabled'], default='auto',
                        help='Reframe mode: auto (face tracking) or disabled (4:3 crop with black bars)')
    parser.add_argument('--reframe-only', action='store_true',
                        help='Skip download/analysis/cutting: take --input (an existing 16:9 '
                             'source slice) and re-run reframing + zoom/normalize/cover only. '
                             'Used by POST /api/reframe to switch modes on an already-generated clip.')
    parser.add_argument('--language', type=str, default=None,
                        help="Override ASR language for this job (e.g. 'en', 'it', 'es', 'multi'). "
                             "When unset, Deepgram uses DEEPGRAM_LANGUAGE from env (default 'multi' "
                             "for native EN+IT code-switching). Single-language mode improves both "
                             "transcription accuracy AND speaker diarization reliability.")
    parser.add_argument('--aspect', choices=['9:16', '1:1', '16:9'], default='9:16',
                        help="Output aspect ratio: 9:16 vertical (default), 1:1 square, or 16:9 horizontal.")

    args = parser.parse_args()

    # Output aspect ratio drives the crop dimensions + SmoothedCameraman crop
    # box. ASPECT_RATIO is a module global read by process_video_to_vertical and
    # SmoothedCameraman; this runs at module scope once per job (subprocess), so
    # rebinding it here from the arg applies to every clip in this run.
    ASPECT_RATIO = {'9:16': 9 / 16, '1:1': 1.0, '16:9': 16 / 9}.get(args.aspect, 9 / 16)
    if args.aspect != '9:16':
        print(f"📐 Aspect ratio: {args.aspect} ({ASPECT_RATIO:.3f})")

    # Per-job language override — propagate to the env BEFORE any transcription
    # call so deepgram_transcribe.transcribe_with_deepgram reads the user's
    # choice (it reads DEEPGRAM_LANGUAGE at call time). Also used to hint the
    # Whisper fallback path via faster-whisper's auto-detect being bypassed.
    if args.language:
        os.environ["DEEPGRAM_LANGUAGE"] = args.language
        os.environ["CLIPPYME_LANGUAGE"] = args.language
        print(f"🌐  Language override: {args.language} (overrides default 'multi')")

    # --- Reframe-only fast path: reuse an existing 16:9 slice ----------------
    if args.reframe_only:
        if not args.input or not args.output:
            print("❌ --reframe-only requires both --input (source slice) and --output (target)")
            sys.exit(2)
        if not os.path.exists(args.input):
            print(f"❌ Source slice not found: {args.input}")
            sys.exit(2)
        reframe_start = time.time()
        print(f"🔁 Reframe-only mode ({args.reframe_mode}) on {os.path.basename(args.input)}")
        # Atomic write: render into <output>.reframe.tmp.mp4 so a crash
        # mid-rendering never leaves the user's existing clip truncated
        # or deleted. Only on full success do we os.replace() the temp
        # into the final output path. process_video_to_vertical has an
        # unconditional os.remove(final_output_video) at the top which
        # is what wiped clips on failure before this fix.
        final_output = args.output
        tmp_output = final_output + ".reframe.tmp.mp4"
        try:
            success = process_video_to_vertical(args.input, tmp_output, reframe_mode=args.reframe_mode)
            if not success:
                print("❌ Reframe failed.")
                if os.path.exists(tmp_output):
                    try:
                        os.remove(tmp_output)
                    except OSError:
                        pass
                sys.exit(1)
            if not args.no_zoom:
                apply_subtle_zoom(tmp_output)
            normalize_audio(tmp_output)
            select_cover_frame(tmp_output)
            os.replace(tmp_output, final_output)
            print(f"✅ Reframe-only done in {time.time() - reframe_start:.1f}s → {final_output}")
            sys.exit(0)
        except Exception as e:
            print(f"❌ Reframe-only crashed: {e}")
            if os.path.exists(tmp_output):
                try:
                    os.remove(tmp_output)
                except OSError:
                    pass
            sys.exit(1)
    # -------------------------------------------------------------------------


    script_start_time = time.time()

    _VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm", ".avi"}

    def _resolve_output_dir(out: str | None, default: str) -> str:
        """Treat ``out`` as a directory unless it has a video suffix.

        Fixes the edge case where a user passes a new (non-existent)
        directory and the old logic called ``os.path.dirname`` on it,
        landing the output one level above the intended dir.
        """
        if not out:
            return default
        if os.path.splitext(out)[1].lower() in _VIDEO_SUFFIXES:
            return os.path.dirname(out) or default
        os.makedirs(out, exist_ok=True)
        return out

    # 1. Get Input Video
    if args.url:
        output_dir = _resolve_output_dir(args.output, default=".")
        input_video, video_title = download_youtube_video(args.url, output_dir, args.cookies)
    else:
        input_video = args.input
        video_title = os.path.splitext(os.path.basename(input_video))[0]
        output_dir = _resolve_output_dir(
            args.output,
            default=os.path.dirname(input_video) or ".",
        )

    if not os.path.exists(input_video):
        print(f"❌ Input file not found: {input_video}")
        sys.exit(1)

    # 2. Decision: Analyze clips or process whole?
    if args.skip_analysis:
        print("⏩ Skipping analysis, processing entire video...")
        output_file = args.output if args.output else os.path.join(output_dir, f"{video_title}_vertical.mp4")
        process_video_to_vertical(input_video, output_file, reframe_mode=args.reframe_mode)
    else:
        # 3. Transcribe (with cache for URL-based jobs)
        cached = _load_cached_transcript(args.url) if args.url else None
        if cached:
            transcript = cached
        else:
            transcript = transcribe_video(input_video)
            if args.url:
                _save_transcript_cache(args.url, transcript)

        # Get duration
        cap = cv2.VideoCapture(input_video)
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        finally:
            cap.release()
        # OpenCV returns 0 for fps/frame_count on corrupt or unreadable files;
        # guard the division so the pipeline degrades to whole-video mode
        # instead of crashing with ZeroDivisionError.
        if fps and fps > 0 and frame_count > 0:
            duration = frame_count / fps
        else:
            print(f"   ⚠️ Could not read duration (fps={fps}, frames={frame_count}); defaulting to 0.")
            duration = 0.0

        # 4. Gemini Analysis
        clips_data = get_viral_clips(transcript, duration, instructions=args.instructions)
        
        if not clips_data or 'shorts' not in clips_data:
            print("❌ Failed to identify clips. Converting whole video as fallback.")
            output_file = os.path.join(output_dir, f"{video_title}_vertical.mp4")
            process_video_to_vertical(input_video, output_file, reframe_mode=args.reframe_mode)
        else:
            print(f"🔥 Found {len(clips_data['shorts'])} viral clips!")
            
            # Save metadata
            clips_data['transcript'] = transcript # Save full transcript for subtitles
            # Annotate each clip with the reframe mode used for the initial
            # render so the dashboard can render the correct per-clip state
            # without guessing (the /api/reframe endpoint updates this
            # field in place when the user flips the mode later on).
            for _clip_entry in clips_data.get('shorts', []):
                _clip_entry.setdefault('reframe_mode', args.reframe_mode)
            metadata_file = os.path.join(output_dir, f"{video_title}_metadata.json")
            metadata_tmp = metadata_file + ".tmp"
            with open(metadata_tmp, 'w') as f:
                json.dump(clips_data, f, indent=2)
            os.replace(metadata_tmp, metadata_file)
            print(f"   Saved metadata to {metadata_file}")

            # 5. Process each clip
            for i, clip in enumerate(clips_data['shorts']):
                start = clip['start']
                end = clip['end']
                print(f"\n🎬 Processing Clip {i+1}: {start}s - {end}s")
                print(f"   Title: {clip.get('video_title_for_youtube_short', 'No Title')}")
                
                # Cut clip
                clip_filename = f"{video_title}_clip_{i+1}.mp4"
                # Keep the 16:9 source slice persistently so the user can
                # later switch reframe modes from the dashboard without
                # re-running the entire pipeline. Naming convention:
                # source_<clip_filename>  (picked up by /api/reframe).
                clip_source_path = os.path.join(output_dir, f"source_{clip_filename}")
                clip_final_path = os.path.join(output_dir, clip_filename)

                # ffmpeg cut
                # Using re-encoding for precision as requested by strict seconds.
                # NOTE on seek: `-ss` BEFORE `-i` uses fast input seek (jumps
                # to the nearest keyframe before `start` and then decodes
                # forward to the exact start). On very long source videos
                # (e.g. 1h+) this can take 30-60s for the first cut — the
                # file has to be partially decoded to reach the target.
                # Subsequent cuts on the same file are usually faster.
                clip_duration = float(end) - float(start)
                cut_command = [
                    'ffmpeg', '-y',
                    '-ss', f'{float(start):.3f}',
                    '-i', input_video,
                    '-t', f'{clip_duration:.3f}',
                    '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
                    '-c:a', 'aac',
                    clip_source_path,
                ]
                # Emit a "beat" before/after so the user sees progress even
                # though ffmpeg runs silent (stdout=DEVNULL). Hard timeout of
                # 10 minutes per cut prevents an infinite hang on corrupt
                # sources — 10 min is ~10x the worst legitimate seek time
                # on a 1 hour input video.
                print(f"   ✂️  ffmpeg cut: seek→{start:.2f}s, duration={clip_duration:.2f}s …", flush=True)
                try:
                    cut_proc = subprocess.run(
                        cut_command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        timeout=600,  # 10 min hard cap
                    )
                    if cut_proc.returncode != 0:
                        err_tail = (cut_proc.stderr or b'').decode('utf-8', errors='replace')[-500:]
                        print(f"   ⚠️  ffmpeg cut failed (code {cut_proc.returncode}): {err_tail}", flush=True)
                    else:
                        print(f"   ✅ ffmpeg cut done", flush=True)
                except subprocess.TimeoutExpired:
                    print(f"   ❌ ffmpeg cut TIMED OUT after 10 min — skipping this clip. Input may be corrupt or seek is stuck.", flush=True)
                    continue

                # Process vertical from the preserved source slice
                success = process_video_to_vertical(clip_source_path, clip_final_path, reframe_mode=args.reframe_mode)

                if success:
                    if not args.no_zoom:
                        apply_subtle_zoom(clip_final_path)
                    normalize_audio(clip_final_path)
                    select_cover_frame(clip_final_path)
                    print(f"   ✅ Clip {i+1} ready: {clip_final_path}")
                    print(f"      📼 Source slice preserved at: {clip_source_path}")

                # NOTE: we intentionally do NOT delete clip_source_path.
                # It's needed by POST /api/reframe/{job_id}/{clip_index} to
                # re-run reframing with a different mode on demand.

    # Clean up original if requested
    if args.url and not args.keep_original and os.path.exists(input_video):
        os.remove(input_video)
        print(f"🗑️  Cleaned up downloaded video.")

    total_time = time.time() - script_start_time
    print(f"\n⏱️  Total execution time: {total_time:.2f}s")
