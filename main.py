import time
import cv2
import scenedetect
import subprocess
import argparse
import re
import sys
from scenedetect import VideoManager, SceneManager
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
    """Save transcript to cache."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = _get_cache_path(url)
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(transcript, f)
        print(f"💾 Transcript cached ({os.path.basename(cache_path)})")
    except Exception as e:
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
You are a senior short-form video editor. Read the ENTIRE transcript and word-level timestamps to choose the 3–15 MOST VIRAL moments for TikTok/IG Reels/YouTube Shorts. Each clip must be between 15 and 60 seconds long.

⚠️ FFMPEG TIME CONTRACT — STRICT REQUIREMENTS:
- Return timestamps in ABSOLUTE SECONDS from the start of the video (usable in: ffmpeg -ss <start> -to <end> -i <input> ...).
- Only NUMBERS with decimal point, up to 3 decimals (examples: 0, 1.250, 17.350).
- Ensure 0 ≤ start < end ≤ VIDEO_DURATION_SECONDS.
- Each clip between 15 and 60 s (inclusive).
- Prefer starting 0.2–0.4 s BEFORE the hook and ending 0.2–0.4 s AFTER the payoff.
- Use silence moments for natural cuts; never cut in the middle of a word or phrase.
- STRICTLY FORBIDDEN to use time formats other than absolute seconds.

VIDEO_DURATION_SECONDS: {video_duration}

TRANSCRIPT_TEXT (raw):
{transcript_text}

WORDS_JSON (array of {{w, s, e}} where s/e are seconds):
{words_json}

STRICT EXCLUSIONS:
- No generic intros/outros or purely sponsorship segments unless they contain the hook.
- No clips < 15 s or > 60 s.

{user_instructions_block}

OUTPUT — RETURN ONLY VALID JSON (no markdown, no comments). Order clips by predicted performance (best to worst). In the descriptions, ALWAYS include a CTA like "Follow me and comment X and I'll send you the workflow" (especially if discussing an n8n workflow):
{{
  "shorts": [
    {{
      "start": <number in seconds, e.g., 12.340>,
      "end": <number in seconds, e.g., 37.900>,
      "viral_score": <integer 0-100, predicted viral performance>,
      "viral_reason": "<1 sentence explaining WHY this clip is viral, in the SAME LANGUAGE as the transcript>",
      "video_description_for_tiktok": "<description for TikTok oriented to get views>",
      "video_description_for_instagram": "<description for Instagram oriented to get views>",
      "video_title_for_youtube_short": "<title for YouTube Short oriented to get views 100 chars max>",
      "viral_hook_text": "<SHORT punchy text overlay (max 10 words). MUST BE IN THE SAME LANGUAGE AS THE VIDEO TRANSCRIPT. Examples: 'POV: You realized...', 'Did you know?', 'Stop doing this!'>"
    }}
  ]
}}
"""

# Load the YOLO model once (Keep for backup or scene analysis if needed)
model = YOLO('yolov8n.pt')
model.to(DEVICE)

# --- MediaPipe Setup ---
# Use standard Face Detection (BlazeFace) for speed
mp_face_detection = mp.solutions.face_detection
face_detection = mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)

class DetectionSmoother:
    """
    Applies temporal smoothing (rolling average) to face detection bounding boxes.
    Reduces micro-jitter from frame-to-frame detection noise.
    """
    def __init__(self, window_size=5):
        from collections import deque
        self.window_size = window_size
        self.histories = {}  # face_id -> deque of (x, y, w, h)

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
            # Average
            hist = self.histories[best_id]
            avg_x = int(sum(b[0] for b in hist) / len(hist))
            avg_y = int(sum(b[1] for b in hist) / len(hist))
            avg_w = int(sum(b[2] for b in hist) / len(hist))
            avg_h = int(sum(b[3] for b in hist) / len(hist))
            smoothed.append({**cand, 'box': [avg_x, avg_y, avg_w, avg_h]})
        # Prune old tracks (not seen in a while)
        active_ids = {id(c) for c in smoothed}  # not perfect but tracks get re-matched
        return smoothed


class SmoothedCameraman:
    """
    Handles smooth camera movement with exponential easing.
    The camera accelerates toward the target and decelerates as it approaches,
    mimicking a professional human operator.
    """
    SMOOTHING = 0.08  # Exponential decay factor (0.05=slow, 0.08=balanced, 0.12=snappy)

    def __init__(self, output_width, output_height, video_width, video_height):
        self.output_width = output_width
        self.output_height = output_height
        self.video_width = video_width
        self.video_height = video_height

        # Initial State
        self.current_center_x = video_width / 2
        self.target_center_x = video_width / 2

        # Calculate crop dimensions once
        self.crop_height = video_height
        self.crop_width = int(self.crop_height * ASPECT_RATIO)
        if self.crop_width > video_width:
             self.crop_width = video_width
             self.crop_height = int(self.crop_width / ASPECT_RATIO)

        # Safe Zone: 25% of crop width
        # If target is within this radius of current center, camera stays still.
        self.safe_zone_radius = self.crop_width * 0.25

    def update_target(self, face_box):
        """
        Updates the target center based on detected face/person.
        """
        if face_box:
            x, y, w, h = face_box
            self.target_center_x = x + w / 2

    def get_crop_box(self, force_snap=False):
        """
        Returns the (x1, y1, x2, y2) for the current frame.
        Uses exponential easing: camera covers ~8% of remaining distance each frame,
        creating natural acceleration/deceleration.
        """
        if force_snap:
            self.current_center_x = self.target_center_x
        else:
            diff = self.target_center_x - self.current_center_x

            # Only move if target is outside the safe zone
            if abs(diff) > self.safe_zone_radius:
                # Exponential easing: move a fraction of the remaining distance
                # This naturally accelerates (large diff → large step) and
                # decelerates (small diff → small step) like a real camera operator
                self.current_center_x += diff * self.SMOOTHING

            # If inside safe zone, camera stays still (no micro-jitter)
                
        # Clamp center
        half_crop = self.crop_width / 2
        
        if self.current_center_x - half_crop < 0:
            self.current_center_x = half_crop
        if self.current_center_x + half_crop > self.video_width:
            self.current_center_x = self.video_width - half_crop
            
        x1 = int(self.current_center_x - half_crop)
        x2 = int(self.current_center_x + half_crop)
        
        x1 = max(0, x1)
        x2 = min(self.video_width, x2)
        
        y1 = 0
        y2 = self.video_height
        
        return x1, y1, x2, y2

class SpeakerTracker:
    """
    Tracks speakers over time to prevent rapid switching and handle temporary obstructions.
    """
    def __init__(self, stabilization_frames=15, cooldown_frames=30):
        self.active_speaker_id = None
        self.speaker_scores = {}  # {id: score}
        self.last_seen = {}       # {id: frame_number}
        self.locked_counter = 0   # How long we've been locked on current speaker
        
        # Hyperparameters
        self.stabilization_threshold = stabilization_frames # Frames needed to confirm a new speaker
        self.switch_cooldown = cooldown_frames              # Minimum frames before switching again
        self.last_switch_frame = -1000
        
        # ID tracking
        self.next_id = 0
        self.known_faces = [] # [{'id': 0, 'center': x, 'last_frame': 123}]

    def get_target(self, face_candidates, frame_number, width):
        """
        Decides which face to focus on.
        face_candidates: list of {'box': [x,y,w,h], 'score': float}
        """
        current_candidates = []
        
        # 1. Match faces to known IDs (simple distance tracking)
        for face in face_candidates:
            x, y, w, h = face['box']
            center_x = x + w / 2
            
            best_match_id = -1
            min_dist = width * 0.15 # Reduced matching radius to avoid jumping in groups
            
            # Try to match with known faces seen recently
            for kf in self.known_faces:
                if frame_number - kf['last_frame'] > 30: # Forgot faces older than 1s (was 2s)
                    continue
                    
                dist = abs(center_x - kf['center'])
                if dist < min_dist:
                    min_dist = dist
                    best_match_id = kf['id']
            
            # If no match, assign new ID
            if best_match_id == -1:
                best_match_id = self.next_id
                self.next_id += 1
            
            # Update known face
            self.known_faces = [kf for kf in self.known_faces if kf['id'] != best_match_id]
            self.known_faces.append({'id': best_match_id, 'center': center_x, 'last_frame': frame_number})
            
            current_candidates.append({
                'id': best_match_id,
                'box': face['box'],
                'score': face['score']
            })

        # 2. Update Scores with decay
        for pid in list(self.speaker_scores.keys()):
             self.speaker_scores[pid] *= 0.85 # Faster decay (was 0.9)
             if self.speaker_scores[pid] < 0.1:
                 del self.speaker_scores[pid]

        # Add new scores
        for cand in current_candidates:
            pid = cand['id']
            # Score is purely based on size (proximity) now that we don't have mouth
            raw_score = cand['score'] / (width * width * 0.05)
            self.speaker_scores[pid] = self.speaker_scores.get(pid, 0) + raw_score

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
    # Use the globally loaded model
    results = model(frame, verbose=False, classes=[0]) # class 0 is person
    
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
                # Focus on the top 40% of the person (head/chest) for framing
                # This approximates where the face is if we can't detect it directly
                face_h = int(h * 0.4)
                best_box = [x1, y1, w, face_h]
                
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
      TRACK       — single subject, follow with smart crop
      TRACK_GROUP — 2+ faces close together, center on group baricentro
      WIDE        — 2+ faces spread wide, use letterbox (blur bg + centered full frame)
      GENERAL     — no faces detected, use letterbox
    """
    cap = cv2.VideoCapture(video_path)
    strategies = []

    if not cap.isOpened():
        return ['TRACK'] * len(scenes)

    video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

    for start, end in tqdm(scenes, desc="   Analyzing Scenes"):
        frames_to_check = [
            start.get_frames() + 5,
            int((start.get_frames() + end.get_frames()) / 2),
            end.get_frames() - 5
        ]

        face_counts = []
        spread_ratios = []  # how spread out faces are (0-1 of frame width)
        for f_idx in frames_to_check:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret, frame = cap.read()
            if not ret:
                continue

            candidates = detect_face_candidates(frame)
            face_counts.append(len(candidates))

            if len(candidates) >= 2:
                # Measure horizontal spread of faces
                centers_x = [c['box'][0] + c['box'][2] / 2 for c in candidates]
                spread = (max(centers_x) - min(centers_x)) / video_width if video_width else 0
                spread_ratios.append(spread)

        if not face_counts:
            avg_faces = 0
        else:
            avg_faces = sum(face_counts) / len(face_counts)

        avg_spread = sum(spread_ratios) / len(spread_ratios) if spread_ratios else 0

        # Decision logic
        if avg_faces < 0.5:
            strategies.append('GENERAL')      # No faces → letterbox
        elif avg_faces <= 1.2:
            strategies.append('TRACK')         # Single person → follow
        elif avg_spread > 0.50:
            strategies.append('WIDE')          # Group spread wide → letterbox
        else:
            strategies.append('TRACK_GROUP')   # Group close together → center on group

    cap.release()
    return strategies

def detect_scenes(video_path):
    video_manager = VideoManager([video_path])
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector())
    video_manager.set_downscale_factor()
    video_manager.start()
    scene_manager.detect_scenes(frame_source=video_manager)
    scene_list = scene_manager.get_scene_list()
    fps = video_manager.get_framerate()
    video_manager.release()
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


def download_youtube_video(url, output_dir=".", cookies_file_path=None):
    """
    Downloads a YouTube video using yt-dlp.
    Returns the path to the downloaded video and the video title.
    """
    print(f"🔍 Debug: yt-dlp version: {yt_dlp.version.__version__}")
    print("📥 Downloading video from YouTube...")
    step_start_time = time.time()

    if cookies_file_path:
        cookies_path = cookies_file_path
        print(f"🍪 Using provided cookies file: {cookies_path}")
    else:
        cookies_path = '/app/cookies.txt'
        cookies_env = os.environ.get("YOUTUBE_COOKIES")
        if cookies_env:
            print("🍪 Found YOUTUBE_COOKIES env var, creating cookies file inside container...")
            try:
                with open(cookies_path, 'w') as f:
                    f.write(cookies_env)
                if os.path.exists(cookies_path):
                     print(f"   Debug: Cookies file created. Size: {os.path.getsize(cookies_path)} bytes")
                     with open(cookies_path, 'r') as f:
                         content = f.read(100)
                         print(f"   Debug: First 100 chars of cookie file: {content}")
            except Exception as e:
                print(f"⚠️ Failed to write cookies file: {e}")
                cookies_path = None
        else:
            cookies_path = None
            print("⚠️ YOUTUBE_COOKIES env var not found.")
    
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
        'nocheckcertificate': True,
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
            '-f', 'null', '/dev/null'
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


def process_video_to_vertical(input_video, final_output_video):
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
    print("\n   🤖 Step 3: Analyzing Scenes for Strategy (Single vs Group)...")
    scene_strategies = analyze_scenes_strategy(input_video, scenes)
    # scene_strategies is a list of 'TRACK' or 'General' corresponding to scenes
    
    print("\n   ✂️ Step 4: Processing video frames...")
    
    command = [
        'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}', '-pix_fmt', 'bgr24',
        '-r', str(fps), '-i', '-', '-c:v', 'libx264',
        '-preset', 'fast', '-crf', '23', '-an', temp_video_output
    ]

    ffmpeg_process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    cap = cv2.VideoCapture(input_video)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    frame_number = 0
    current_scene_index = 0
    
    # Pre-calculate scene boundaries
    scene_boundaries = []
    for s_start, s_end in scenes:
        scene_boundaries.append((s_start.get_frames(), s_end.get_frames()))

    # Global tracker for single-person shots
    speaker_tracker = SpeakerTracker(cooldown_frames=30)
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
            if current_strategy in ('GENERAL', 'WIDE'):
                # Letterbox: blur background + centered full frame
                output_frame = create_general_frame(frame, OUTPUT_WIDTH, OUTPUT_HEIGHT)

                # Reset cameraman so it doesn't drift while inactive
                cameraman.current_center_x = original_width / 2
                cameraman.target_center_x = original_width / 2

            elif current_strategy == 'TRACK_GROUP':
                # Group tracking: center crop on the baricentro of all detected faces
                if frame_number % 2 == 0:
                    candidates = detect_face_candidates(frame)
                    candidates = detection_smoother.smooth(candidates, frame_number)
                    if len(candidates) >= 2:
                        centers_x = [c['box'][0] + c['box'][2] / 2 for c in candidates]
                        group_center_x = sum(centers_x) / len(centers_x)
                        avg_w = sum(c['box'][2] for c in candidates) / len(candidates)
                        cameraman.update_target((group_center_x - avg_w / 2, 0, avg_w, 0))
                    elif candidates:
                        cameraman.update_target(candidates[0]['box'])

                is_scene_start = (frame_number == scene_boundaries[current_scene_index][0])
                x1, y1, x2, y2 = cameraman.get_crop_box(force_snap=is_scene_start)

                if y2 > y1 and x2 > x1:
                    cropped = frame[y1:y2, x1:x2]
                    output_frame = cv2.resize(cropped, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
                else:
                    output_frame = cv2.resize(frame, (OUTPUT_WIDTH, OUTPUT_HEIGHT))

            else:
                # TRACK: single speaker tracking
                if frame_number % 2 == 0:
                    candidates = detect_face_candidates(frame)
                    candidates = detection_smoother.smooth(candidates, frame_number)
                    target_box = speaker_tracker.get_target(candidates, frame_number, original_width)
                    if target_box:
                        cameraman.update_target(target_box)
                    else:
                        person_box = detect_person_yolo(frame)
                        if person_box:
                            cameraman.update_target(person_box)

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
    cap.release()

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

def transcribe_video(video_path):
    from faster_whisper import WhisperModel

    device = "cuda" if CUDA_AVAILABLE else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    print(f"🎙️  Transcribing with Faster-Whisper [{WHISPER_MODEL}] ({device.upper()} mode)...")
    model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute_type)
    segments, info = model.transcribe(video_path, word_timestamps=True)
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
        transcript_text=json.dumps(transcript_result['text']),
        words_json=json.dumps(words),
        user_instructions_block=user_instructions_block
    )

    # Retry with exponential backoff for rate limits / transient errors
    response = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            break
        except Exception as e:
            wait = 2 ** attempt * 2  # 2s, 4s, 8s
            if attempt < 2:
                print(f"⚠️  Gemini API error (attempt {attempt + 1}/3): {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"❌ Gemini API failed after 3 attempts: {e}")
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

    # Parse response JSON
    try:
        text = response.text
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        result_json = json.loads(text)

        # Validate clips schema
        if 'shorts' in result_json and isinstance(result_json['shorts'], list):
            valid_clips = []
            for i, clip in enumerate(result_json['shorts']):
                if not isinstance(clip, dict):
                    print(f"⚠️  Skipping clip {i+1}: not a dict")
                    continue
                if 'start' not in clip or 'end' not in clip:
                    print(f"⚠️  Skipping clip {i+1}: missing start/end")
                    continue
                try:
                    clip['start'] = float(clip['start'])
                    clip['end'] = float(clip['end'])
                except (ValueError, TypeError):
                    print(f"⚠️  Skipping clip {i+1}: start/end not numeric")
                    continue
                if clip['end'] <= clip['start'] or clip['end'] - clip['start'] < 15:
                    print(f"⚠️  Skipping clip {i+1}: invalid duration {clip['end'] - clip['start']:.1f}s ({clip['start']}-{clip['end']})")
                    continue
                valid_clips.append(clip)
            result_json['shorts'] = valid_clips
            if not valid_clips:
                print("❌ No valid clips found after validation")
                return None
            if len(valid_clips) < len(result_json.get('shorts', [])):
                print(f"⚠️  {len(result_json['shorts'])} clips passed validation out of {len(result_json['shorts']) + (len(result_json['shorts']) - len(valid_clips))}")

        if cost_analysis:
            result_json['cost_analysis'] = cost_analysis
        return result_json
    except (json.JSONDecodeError, AttributeError) as e:
        print(f"❌ Failed to parse Gemini response: {e}")
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

    args = parser.parse_args()

    script_start_time = time.time()
    
    def _ensure_dir(path: str) -> str:
        """Create directory if missing and return the same path."""
        if path:
            os.makedirs(path, exist_ok=True)
        return path
    
    # 1. Get Input Video
    if args.url:
        # For multi-clip runs, treat --output as an OUTPUT DIRECTORY (create it if needed).
        # For whole-video runs (--skip-analysis), --output can be a file path.
        if args.output and not args.skip_analysis:
            output_dir = _ensure_dir(args.output)
        else:
            # If output is a directory, use it; if it's a filename, use its directory; else default "."
            if args.output and os.path.isdir(args.output):
                output_dir = args.output
            elif args.output and not os.path.isdir(args.output):
                output_dir = os.path.dirname(args.output) or "."
            else:
                output_dir = "."
        
        input_video, video_title = download_youtube_video(args.url, output_dir, args.cookies)
    else:
        input_video = args.input
        video_title = os.path.splitext(os.path.basename(input_video))[0]
        
        if args.output and not args.skip_analysis:
            # For multi-clip runs, treat --output as an OUTPUT DIRECTORY (create it if needed).
            output_dir = _ensure_dir(args.output)
        else:
            # If output is a directory, use it; if it's a filename, use its directory; else default to input dir.
            if args.output and os.path.isdir(args.output):
                output_dir = args.output
            elif args.output and not os.path.isdir(args.output):
                output_dir = os.path.dirname(args.output) or os.path.dirname(input_video)
            else:
                output_dir = os.path.dirname(input_video)

    if not os.path.exists(input_video):
        print(f"❌ Input file not found: {input_video}")
        exit(1)

    # 2. Decision: Analyze clips or process whole?
    if args.skip_analysis:
        print("⏩ Skipping analysis, processing entire video...")
        output_file = args.output if args.output else os.path.join(output_dir, f"{video_title}_vertical.mp4")
        process_video_to_vertical(input_video, output_file)
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
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps
        cap.release()

        # 4. Gemini Analysis
        clips_data = get_viral_clips(transcript, duration, instructions=args.instructions)
        
        if not clips_data or 'shorts' not in clips_data:
            print("❌ Failed to identify clips. Converting whole video as fallback.")
            output_file = os.path.join(output_dir, f"{video_title}_vertical.mp4")
            process_video_to_vertical(input_video, output_file)
        else:
            print(f"🔥 Found {len(clips_data['shorts'])} viral clips!")
            
            # Save metadata
            clips_data['transcript'] = transcript # Save full transcript for subtitles
            metadata_file = os.path.join(output_dir, f"{video_title}_metadata.json")
            with open(metadata_file, 'w') as f:
                json.dump(clips_data, f, indent=2)
            print(f"   Saved metadata to {metadata_file}")

            # 5. Process each clip
            for i, clip in enumerate(clips_data['shorts']):
                start = clip['start']
                end = clip['end']
                print(f"\n🎬 Processing Clip {i+1}: {start}s - {end}s")
                print(f"   Title: {clip.get('video_title_for_youtube_short', 'No Title')}")
                
                # Cut clip
                clip_filename = f"{video_title}_clip_{i+1}.mp4"
                clip_temp_path = os.path.join(output_dir, f"temp_{clip_filename}")
                clip_final_path = os.path.join(output_dir, clip_filename)
                
                # ffmpeg cut
                # Using re-encoding for precision as requested by strict seconds
                cut_command = [
                    'ffmpeg', '-y', 
                    '-ss', str(start), 
                    '-to', str(end), 
                    '-i', input_video,
                    '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
                    '-c:a', 'aac',
                    clip_temp_path
                ]
                subprocess.run(cut_command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                
                # Process vertical
                success = process_video_to_vertical(clip_temp_path, clip_final_path)
                
                if success:
                    if not args.no_zoom:
                        apply_subtle_zoom(clip_final_path)
                    normalize_audio(clip_final_path)
                    select_cover_frame(clip_final_path)
                    print(f"   ✅ Clip {i+1} ready: {clip_final_path}")

                # Clean up temp cut
                if os.path.exists(clip_temp_path):
                    os.remove(clip_temp_path)

    # Clean up original if requested
    if args.url and not args.keep_original and os.path.exists(input_video):
        os.remove(input_video)
        print(f"🗑️  Cleaned up downloaded video.")

    total_time = time.time() - script_start_time
    print(f"\n⏱️  Total execution time: {total_time:.2f}s")
