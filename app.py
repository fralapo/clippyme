import os
import uuid
import subprocess
import threading
import json
import shutil
import glob
import time
import asyncio
import ipaddress
import logging
from dotenv import load_dotenv
from typing import Dict, Optional, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("clippyme")
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

load_dotenv()

# Constants
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "output"
DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

VALID_CONFIG_KEYS = ("GEMINI_API_KEY", "GEMINI_MODEL", "YOUTUBE_COOKIES", "HF_TOKEN")
ALLOWED_MODEL_PREFIXES = ("gemini-2.5-", "gemini-3")
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
)


def parse_allowed_origins(raw_value: Optional[str] = None) -> List[str]:
    """Parse a comma-separated ALLOWED_ORIGINS env var with safe localhost defaults."""
    if raw_value is None:
        return list(DEFAULT_ALLOWED_ORIGINS)

    origins = [origin.strip().rstrip("/") for origin in raw_value.split(",") if origin.strip()]
    return origins or list(DEFAULT_ALLOWED_ORIGINS)


ALLOWED_ORIGINS = parse_allowed_origins(os.environ.get("ALLOWED_ORIGINS"))


def is_trusted_origin(origin: Optional[str]) -> bool:
    if not origin:
        return False
    return origin.rstrip("/") in ALLOWED_ORIGINS


def is_trusted_client_host(client_host: Optional[str]) -> bool:
    if not client_host:
        return False

    normalized_host = client_host.strip().lower()
    if normalized_host in {"127.0.0.1", "::1", "localhost"}:
        return True

    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        return False

    return address.is_loopback or address.is_private


def require_trusted_config_request(request: Request) -> None:
    """Protect config endpoints from cross-site browser access."""
    origin = request.headers.get("origin")
    if origin:
        if is_trusted_origin(origin):
            return
        raise HTTPException(status_code=403, detail="Origin not allowed for config access.")

    client_host = request.client.host if request.client else ""
    if is_trusted_client_host(client_host):
        return

    raise HTTPException(status_code=403, detail="Config access requires a trusted local origin.")


def load_persistent_config():
    """Load config from JSON file if exists, falling back to environment variables."""
    config = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        "GEMINI_MODEL": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        "YOUTUBE_COOKIES": os.environ.get("YOUTUBE_COOKIES", ""),
        "HF_TOKEN": os.environ.get("HF_TOKEN", "")
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                persistent = json.load(f)
                # Filter to only keep valid keys
                filtered = {k: v for k, v in persistent.items() if k in VALID_CONFIG_KEYS}
                config.update(filtered)
        except Exception as e:
            logger.warning("Error loading config.json: %s", e)
            
    return config

def save_persistent_config(new_config: dict):
    """Save new configuration to JSON file."""
    try:
        # Load existing first to merge
        current = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                current = json.load(f)
        
        sanitized = {k: new_config.get(k) for k in VALID_CONFIG_KEYS if k in new_config}
        for key, value in sanitized.items():
            if value in (None, ""):
                current.pop(key, None)
                os.environ.pop(key, None)
            else:
                current[key] = value
                os.environ[key] = str(value)

        with open(CONFIG_FILE, "w") as f:
            json.dump(current, f, indent=4)
        return True
    except Exception as e:
        logger.error("Error saving config.json: %s", e)
        return False

# Initial load to env
save_persistent_config(load_persistent_config())

# Configuration
# Default to 1 if not set, but user can set higher for powerful servers
MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", "5"))
MAX_FILE_SIZE_MB = 2048  # 2GB limit
JOB_RETENTION_SECONDS = 3600  # 1 hour retention

# Application State
job_queue = asyncio.Queue(maxsize=50)
jobs: Dict[str, Dict] = {}
batches: Dict[str, Dict] = {}  # batch_id -> {job_ids: [...], created: timestamp}
# Semaphore to limit concurrency to MAX_CONCURRENT_JOBS
concurrency_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

from google import genai

def _relocate_root_job_artifacts(job_id: str, job_output_dir: str) -> bool:
    """
    Backward-compat rescue:
    If main.py accidentally wrote metadata/clips into OUTPUT_DIR root (e.g. output/<jobid>_...),
    move them into output/<job_id>/ so the API can find and serve them.
    """
    try:
        os.makedirs(job_output_dir, exist_ok=True)
        root = OUTPUT_DIR
        pattern = os.path.join(root, f"{job_id}_*_metadata.json")
        meta_candidates = sorted(glob.glob(pattern), key=lambda p: os.path.getmtime(p), reverse=True)
        if not meta_candidates:
            return False

        # Move the newest metadata and its associated clips.
        metadata_path = meta_candidates[0]
        base_name = os.path.basename(metadata_path).replace("_metadata.json", "")

        # Move metadata
        dest_metadata = os.path.join(job_output_dir, os.path.basename(metadata_path))
        if os.path.abspath(metadata_path) != os.path.abspath(dest_metadata):
            shutil.move(metadata_path, dest_metadata)

        # Move any clips that match the same base_name into the job folder
        clip_pattern = os.path.join(root, f"{base_name}_clip_*.mp4")
        for clip_path in glob.glob(clip_pattern):
            dest_clip = os.path.join(job_output_dir, os.path.basename(clip_path))
            if os.path.abspath(clip_path) != os.path.abspath(dest_clip):
                shutil.move(clip_path, dest_clip)

        # Also move any temp_ clips that might remain
        temp_clip_pattern = os.path.join(root, f"temp_{base_name}_clip_*.mp4")
        for clip_path in glob.glob(temp_clip_pattern):
            dest_clip = os.path.join(job_output_dir, os.path.basename(clip_path))
            if os.path.abspath(clip_path) != os.path.abspath(dest_clip):
                shutil.move(clip_path, dest_clip)

        return True
    except Exception:
        return False

async def cleanup_jobs():
    """Background task to remove old jobs and files."""
    import time
    logger.info("Cleanup task started")
    while True:
        try:
            await asyncio.sleep(300) # Check every 5 minutes
            now = time.time()
            
            # Simple directory cleanup based on modification time
            # Check OUTPUT_DIR
            for job_id in os.listdir(OUTPUT_DIR):
                job_path = os.path.join(OUTPUT_DIR, job_id)
                if os.path.isdir(job_path):
                    if now - os.path.getmtime(job_path) > JOB_RETENTION_SECONDS:
                        logger.info("Purging old job: %s", job_id)
                        shutil.rmtree(job_path, ignore_errors=True)
                        if job_id in jobs:
                            del jobs[job_id]

            # Cleanup Uploads
            for filename in os.listdir(UPLOAD_DIR):
                file_path = os.path.join(UPLOAD_DIR, filename)
                try:
                    if now - os.path.getmtime(file_path) > JOB_RETENTION_SECONDS:
                         os.remove(file_path)
                except Exception: pass

            # Cleanup transcript cache (older than 7 days)
            cache_dir = os.path.join(DATA_DIR, "cache")
            if os.path.isdir(cache_dir):
                for filename in os.listdir(cache_dir):
                    cache_path = os.path.join(cache_dir, filename)
                    try:
                        if now - os.path.getmtime(cache_path) > 7 * 86400:
                            os.remove(cache_path)
                    except Exception: pass

            # Cleanup old batches (older than retention period)
            for bid in list(batches.keys()):
                if now - batches[bid].get("created", 0) > JOB_RETENTION_SECONDS:
                    del batches[bid]

        except Exception as e:
            logger.warning("Cleanup error: %s", e)

async def process_queue():
    """Background worker to process jobs from the queue with concurrency limit."""
    logger.info("Job queue worker started with %d concurrent slots", MAX_CONCURRENT_JOBS)
    while True:
        try:
            # Wait for a job
            job_id = await job_queue.get()
            
            # Acquire semaphore slot (waits if max jobs are running)
            await concurrency_semaphore.acquire()
            logger.info("Acquired slot for job: %s", job_id)

            # Process in background task to not block the loop (allowing other slots to fill)
            asyncio.create_task(run_job_wrapper(job_id))
            
        except Exception as e:
            logger.error("Queue dispatch error: %s", e)
            await asyncio.sleep(1)

async def run_job_wrapper(job_id):
    """Wrapper to run job and release semaphore"""
    try:
        job = jobs.get(job_id)
        if job:
            await run_job(job_id, job)
    except Exception as e:
         logger.error("Job wrapper error %s: %s", job_id, e)
    finally:
        # Always release semaphore and mark queue task done
        concurrency_semaphore.release()
        job_queue.task_done()
        logger.info("Released slot for job: %s", job_id)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start worker and cleanup
    worker_task = asyncio.create_task(process_queue())
    cleanup_task = asyncio.create_task(cleanup_jobs())
    yield
    # Cleanup (optional: cancel worker)

app = FastAPI(lifespan=lifespan)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for serving videos
app.mount("/videos", StaticFiles(directory=OUTPUT_DIR), name="videos")

# Mount static files for serving thumbnails
THUMBNAILS_DIR = os.path.join(OUTPUT_DIR, "thumbnails")
os.makedirs(THUMBNAILS_DIR, exist_ok=True)
app.mount("/thumbnails", StaticFiles(directory=THUMBNAILS_DIR), name="thumbnails")

@app.get("/")
async def root():
    return {"status": "online", "message": "ClippyMe API is running"}

@app.get("/api/health")
async def health():
    return {"status": "healthy"}

@app.get("/api/config/models")
async def list_gemini_models(api_key: Optional[str] = Header(None, alias="X-Gemini-Key")):
    """List available Gemini models using the provided API key."""
    final_api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not final_api_key:
        return {"models": [], "error": "API Key missing"}
    
    try:
        client = genai.Client(api_key=final_api_key)
        models = []
        # list_models returns an iterator of model objects
        for model in client.models.list():
            # Filter for models that support content generation
            if 'generateContent' in model.supported_generation_methods:
                # model.name is like 'models/gemini-pro'
                clean_name = model.name.replace('models/', '')
                # Only show current-generation models (skip deprecated 1.x, 2.0)
                if not any(clean_name.startswith(p) for p in ALLOWED_MODEL_PREFIXES):
                    continue
                models.append({
                    "name": clean_name,
                    "display_name": model.display_name,
                    "description": model.description
                })
        return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}

class ProcessRequest(BaseModel):
    url: str

def enqueue_output(out, job_id):
    """Reads output from a subprocess and appends it to jobs logs."""
    try:
        for line in iter(out.readline, b''):
            decoded_line = line.decode('utf-8').strip()
            if decoded_line:
                print(f"📝 [Job Output] {decoded_line}")
                if job_id in jobs:
                    jobs[job_id]['logs'].append(decoded_line)
    except Exception as e:
        logger.error("Error reading output for job %s: %s", job_id, e)
    finally:
        out.close()

async def run_job(job_id, job_data):
    """Executes the subprocess for a specific job."""
    
    cmd = job_data['cmd']
    env = job_data['env']
    output_dir = job_data['output_dir']
    
    jobs[job_id]['status'] = 'processing'
    jobs[job_id]['logs'].append("Job started by worker.")
    jobs[job_id]['process'] = None  # Will hold Popen reference for cancel
    logger.info("Executing job %s: %s", job_id, ' '.join(cmd))

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=os.getcwd()
        )
        jobs[job_id]['process'] = process
        
        # We need to capture logs in a thread because Popen isn't async
        t_log = threading.Thread(target=enqueue_output, args=(process.stdout, job_id))
        t_log.daemon = True
        t_log.start()
        
        # Async wait for process with incremental updates
        start_wait = time.time()
        while process.poll() is None:
            await asyncio.sleep(2)
            
            # Check for partial results every 2 seconds
            # Look for metadata file
            # main.py writes metadata atomically (complete write + close), so
            # json.load here is safe in the common case. The outer try/except
            # handles the rare edge case of reading during a partial write.
            try:
                json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
                if json_files:
                    target_json = json_files[0]
                    if os.path.getsize(target_json) > 0:
                        with open(target_json, 'r') as f:
                            data = json.load(f)
                            
                        base_name = os.path.basename(target_json).replace('_metadata.json', '')
                        clips = data.get('shorts', [])
                        cost_analysis = data.get('cost_analysis')
                        
                        # Check which clips actually exist on disk
                        ready_clips = []
                        for i, clip in enumerate(clips):
                             clip_filename = f"{base_name}_clip_{i+1}.mp4"
                             clip_path = os.path.join(output_dir, clip_filename)
                             if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                                 # Checking if file is growing? For now assume if it exists and main.py moves it there, it's done.
                                 # main.py writes to temp_... then moves to final name. So presence means ready!
                                 clip['video_url'] = f"/videos/{job_id}/{clip_filename}"
                                 ready_clips.append(clip)
                        
                        if ready_clips:
                             jobs[job_id]['result'] = {'clips': ready_clips, 'cost_analysis': cost_analysis}
            except Exception as e:
                # Ignore read errors during processing
                pass

        returncode = process.returncode

        # Check if job was cancelled while running
        if jobs[job_id]['status'] == 'cancelled':
            jobs[job_id]['logs'].append("Process terminated (cancelled).")
        elif returncode == 0:
            jobs[job_id]['status'] = 'completed'
            jobs[job_id]['logs'].append("Process finished successfully.")
            
            # Find result JSON
            json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
            if not json_files:
                # Backward-compat rescue if outputs were written to OUTPUT_DIR root
                if _relocate_root_job_artifacts(job_id, output_dir):
                    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
            if json_files:
                target_json = json_files[0] 
                with open(target_json, 'r') as f:
                    data = json.load(f)
                
                # Enhance result with video URLs
                base_name = os.path.basename(target_json).replace('_metadata.json', '')
                clips = data.get('shorts', [])
                cost_analysis = data.get('cost_analysis')

                for i, clip in enumerate(clips):
                     clip_filename = f"{base_name}_clip_{i+1}.mp4"
                     clip['video_url'] = f"/videos/{job_id}/{clip_filename}"
                
                jobs[job_id]['result'] = {'clips': clips, 'cost_analysis': cost_analysis}
            else:
                 jobs[job_id]['status'] = 'failed'
                 jobs[job_id]['logs'].append("No metadata file generated.")
        else:
            jobs[job_id]['status'] = 'failed'
            jobs[job_id]['logs'].append(f"Process failed with exit code {returncode}")
            
    except Exception as e:
        jobs[job_id]['status'] = 'failed'
        jobs[job_id]['logs'].append(f"Execution error: {str(e)}")

@app.post("/api/process")
async def process_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None)
):
    api_key = request.headers.get("X-Gemini-Key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")
    
    # Handle JSON body manually for URL payload
    instructions = None
    reframe_mode = None
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        url = body.get("url")
        instructions = body.get("instructions")
        reframe_mode = body.get("reframe_mode")

    if not url and not file:
        raise HTTPException(status_code=400, detail="Must provide URL or File")

    job_id = str(uuid.uuid4())
    job_output_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_output_dir, exist_ok=True)
    
    # Prepare Command
    cmd = ["python", "-u", "main.py"] # -u for unbuffered
    env = os.environ.copy()
    env["GEMINI_API_KEY"] = api_key # Override with key from request
    
    if url:
        cmd.extend(["-u", url])
        # Use persistent cookies if available
        cookies_path = os.path.join("data", "cookies.txt")
        if os.path.exists(cookies_path):
            cmd.extend(["-c", cookies_path])
    else:
        # Save uploaded file with size limit check
        input_path = os.path.join(UPLOAD_DIR, f"{job_id}_{file.filename}")
        
        # Read file in chunks to check size
        size = 0
        limit_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
        
        with open(input_path, "wb") as buffer:
            while content := await file.read(1024 * 1024): # Read 1MB chunks
                size += len(content)
                if size > limit_bytes:
                    os.remove(input_path)
                    shutil.rmtree(job_output_dir)
                    raise HTTPException(status_code=413, detail=f"File too large. Max size {MAX_FILE_SIZE_MB}MB")
                buffer.write(content)
                
        cmd.extend(["-i", input_path])

    cmd.extend(["-o", job_output_dir])

    if instructions:
        cmd.extend(["--instructions", instructions])

    if reframe_mode and reframe_mode != 'auto':
        cmd.extend(["--reframe-mode", reframe_mode])

    # Enqueue Job
    jobs[job_id] = {
        'status': 'queued',
        'logs': [f"Job {job_id} queued."],
        'cmd': cmd,
        'env': env,
        'output_dir': job_output_dir
    }

    try:
        job_queue.put_nowait(job_id)
    except asyncio.QueueFull:
        del jobs[job_id]
        shutil.rmtree(job_output_dir, ignore_errors=True)
        raise HTTPException(status_code=429, detail="Server busy. Please try again later.")

    return {"job_id": job_id, "status": "queued"}


class BatchRequest(BaseModel):
    urls: List[str] = Field(..., min_length=1, max_length=20)
    instructions: Optional[str] = None


@app.post("/api/batch")
async def batch_process(req: BatchRequest, request: Request):
    """Submit multiple URLs for batch processing. Each URL becomes a separate job."""
    api_key = request.headers.get("X-Gemini-Key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")

    batch_id = str(uuid.uuid4())
    batch_jobs = []

    for url in req.urls:
        url = url.strip()
        if not url:
            continue

        job_id = str(uuid.uuid4())
        job_output_dir = os.path.join(OUTPUT_DIR, job_id)
        os.makedirs(job_output_dir, exist_ok=True)

        cmd = ["python", "-u", "main.py", "-u", url, "-o", job_output_dir]
        if req.instructions:
            cmd.extend(["--instructions", req.instructions])

        env = os.environ.copy()
        env["GEMINI_API_KEY"] = api_key

        jobs[job_id] = {
            'status': 'queued',
            'logs': [f"Job {job_id} queued (batch {batch_id})."],
            'cmd': cmd,
            'env': env,
            'output_dir': job_output_dir
        }

        try:
            job_queue.put_nowait(job_id)
            batch_jobs.append({"url": url, "job_id": job_id})
        except asyncio.QueueFull:
            del jobs[job_id]
            shutil.rmtree(job_output_dir, ignore_errors=True)
            # Stop adding more — queue is full
            break

    if not batch_jobs:
        raise HTTPException(status_code=400, detail="No valid URLs provided or queue is full.")

    batches[batch_id] = {
        "job_ids": [j["job_id"] for j in batch_jobs],
        "created": time.time()
    }

    return {"batch_id": batch_id, "jobs": batch_jobs, "total": len(batch_jobs)}


@app.get("/api/batch/{batch_id}")
async def get_batch_status(batch_id: str):
    """Return aggregated status of all jobs in a batch."""
    if batch_id not in batches:
        raise HTTPException(status_code=404, detail="Batch not found")

    batch = batches[batch_id]
    job_statuses = []
    for jid in batch["job_ids"]:
        job = jobs.get(jid, {})
        status_entry = {
            "job_id": jid,
            "status": job.get("status", "unknown"),
        }
        if job.get("result"):
            status_entry["clip_count"] = len(job["result"].get("clips", []))
        job_statuses.append(status_entry)

    completed = sum(1 for j in job_statuses if j["status"] == "completed")
    failed = sum(1 for j in job_statuses if j["status"] == "failed")

    return {
        "batch_id": batch_id,
        "total": len(job_statuses),
        "completed": completed,
        "failed": failed,
        "jobs": job_statuses
    }


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    return {
        "status": job['status'],
        "logs": job['logs'],
        "result": job.get('result')
    }

@app.post("/api/cancel/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a running job by killing its subprocess."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    if job['status'] not in ('processing', 'queued'):
        raise HTTPException(status_code=400, detail="Job is not running")

    proc = job.get('process')
    if proc and proc.poll() is None:
        import signal
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass

    job['status'] = 'cancelled'
    job['logs'].append("Job cancelled by user.")
    logger.info("Job %s cancelled by user", job_id)

    # Cleanup output dir
    output_dir = job.get('output_dir', '')
    if output_dir and os.path.isdir(output_dir):
        shutil.rmtree(output_dir, ignore_errors=True)

    return {"success": True, "status": "cancelled"}

@app.get("/api/config")
async def get_config(request: Request):
    """Return current active configuration (keys are partially masked for safety)."""
    require_trusted_config_request(request)
    config = load_persistent_config()
    masked = {}
    for k, v in config.items():
        if v and len(v) > 8:
            masked[k] = f"{v[:4]}...{v[-4:]}"
        else:
            masked[k] = v
    return masked

class ConfigUpdateRequest(BaseModel):
    keys: dict

@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest, request: Request):
    """Update and persist API keys."""
    require_trusted_config_request(request)
    if save_persistent_config(req.keys):
        return {"success": True, "message": "Configuration updated and persisted."}
    else:
        raise HTTPException(status_code=500, detail="Failed to save configuration.")

@app.post("/api/config/cookies")
async def upload_cookies(cookies_file: UploadFile = File(...)):
    """Upload and persist a Netscape-format cookies.txt file."""
    os.makedirs("data", exist_ok=True)
    cookies_path = os.path.join("data", "cookies.txt")
    content = await cookies_file.read()
    with open(cookies_path, "wb") as f:
        f.write(content)
    return {"status": "ok", "message": "Cookies saved"}

@app.get("/api/config/cookies/status")
async def cookies_status():
    """Check if a cookies file is configured."""
    cookies_path = os.path.join("data", "cookies.txt")
    return {"configured": os.path.exists(cookies_path)}

@app.delete("/api/config/cookies")
async def delete_cookies():
    """Remove the persisted cookies file."""
    cookies_path = os.path.join("data", "cookies.txt")
    if os.path.exists(cookies_path):
        os.remove(cookies_path)
    return {"status": "ok", "message": "Cookies removed"}

from subtitles import generate_srt, burn_subtitles, generate_srt_from_video, generate_ass_karaoke, SUBTITLE_PRESETS
from smartcut import smart_cut
from hooks import add_hook_to_video

class SubtitleRequest(BaseModel):
    job_id: str = Field(..., pattern=r"^[0-9a-fA-F-]{36}$")
    clip_index: int
    position: str = "bottom"
    font_size: int = 16
    font_name: str = "Verdana"
    font_color: str = "#FFFFFF"
    border_color: str = "#000000"
    border_width: int = 2
    bg_color: str = "#000000"
    bg_opacity: float = 0.0
    input_filename: Optional[str] = None
    # Karaoke / viral subtitle options
    preset: Optional[str] = None  # e.g. "classic_white", "hormozi_bold", etc.
    karaoke_mode: Optional[str] = None  # "word_group" or "full_line"
    words_per_group: int = 3
    uppercase: bool = True
    highlight_color: Optional[str] = None

@app.post("/api/subtitle")
async def add_subtitles(req: SubtitleRequest):
    if req.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[req.job_id]
    output_dir = os.path.join(OUTPUT_DIR, req.job_id)
    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
    
    if not json_files:
        raise HTTPException(status_code=404, detail="Metadata not found")
        
    with open(json_files[0], 'r') as f:
        data = json.load(f)
        
    transcript = data.get('transcript')
    if not transcript:
        raise HTTPException(status_code=400, detail="Transcript not found in metadata.")
        
    clips = data.get('shorts', [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")
        
    clip_data = clips[req.clip_index]
    
    if req.input_filename:
        filename = os.path.basename(req.input_filename)
    else:
        filename = clip_data.get('video_url', '').split('/')[-1]
        if not filename:
             base_name = os.path.basename(json_files[0]).replace('_metadata.json', '')
             filename = f"{base_name}_clip_{req.clip_index+1}.mp4"
         
    input_path = os.path.join(output_dir, filename)
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")
        
    use_karaoke = req.preset is not None and req.preset in SUBTITLE_PRESETS
    ts = int(time.time())

    if use_karaoke:
        sub_filename = f"subs_{req.clip_index}_{ts}.ass"
    else:
        sub_filename = f"subs_{req.clip_index}_{ts}.srt"
    sub_path = os.path.join(output_dir, sub_filename)

    output_filename = f"subtitled_{filename}"
    output_path = os.path.join(output_dir, output_filename)

    try:
        if use_karaoke:
            success = generate_ass_karaoke(
                transcript, clip_data['start'], clip_data['end'], sub_path,
                preset=req.preset,
                mode=req.karaoke_mode or "word_group",
                words_per_group=req.words_per_group,
                uppercase=req.uppercase,
                font_name=req.font_name if req.font_name != "Verdana" else None,
                font_color=req.font_color if req.font_color != "#FFFFFF" else None,
                highlight_color=req.highlight_color,
                font_size=req.font_size if req.font_size != 16 else None,
                outline_width=req.border_width if req.border_width != 2 else None,
                position=req.position
            )
        else:
            success = generate_srt(transcript, clip_data['start'], clip_data['end'], sub_path)

        if not success:
             raise HTTPException(status_code=400, detail="No words found for this clip range.")

        def run_burn():
             burn_subtitles(input_path, sub_path, output_path,
                           alignment=req.position, fontsize=req.font_size,
                           font_name=req.font_name, font_color=req.font_color,
                           border_color=req.border_color, border_width=req.border_width,
                           bg_color=req.bg_color, bg_opacity=req.bg_opacity)
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_burn)
        
    except Exception as e:
        logger.error("Subtitle error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
        
    if req.clip_index < len(job['result']['clips']):
         job['result']['clips'][req.clip_index]['video_url'] = f"/videos/{req.job_id}/{output_filename}"
    
    try:
        if req.clip_index < len(clips):
            clips[req.clip_index]['video_url'] = f"/videos/{req.job_id}/{output_filename}"
            data['shorts'] = clips
            with open(json_files[0], 'w') as f:
                json.dump(data, f, indent=4)
    except Exception as e:
        logger.warning("Failed to update metadata.json: %s", e)

    return {
        "success": True,
        "new_video_url": f"/videos/{req.job_id}/{output_filename}"
    }

@app.get("/api/subtitle/presets")
async def get_subtitle_presets():
    """Return available subtitle style presets."""
    return {name: {k: v for k, v in preset.items() if k != "margin_v"}
            for name, preset in SUBTITLE_PRESETS.items()}

@app.post("/api/smartcut/{job_id}/{clip_index}")
async def smart_cut_clip(job_id: str, clip_index: int):
    """Generate a smart-cut version of a clip (silences + filler words removed)."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    output_dir = os.path.join(OUTPUT_DIR, job_id)
    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
    if not json_files:
        raise HTTPException(status_code=404, detail="Metadata not found")

    with open(json_files[0], 'r') as f:
        data = json.load(f)

    transcript = data.get('transcript')
    if not transcript:
        raise HTTPException(status_code=400, detail="Transcript not found in metadata.")

    clips = data.get('shorts', [])
    if clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[clip_index]
    language = transcript.get('language', 'en')

    # Find the clip file
    clip_url = clip_data.get('video_url', '')
    filename = clip_url.split('/')[-1] if clip_url else None
    if not filename:
        base_name = os.path.basename(json_files[0]).replace('_metadata.json', '')
        filename = f"{base_name}_clip_{clip_index + 1}.mp4"

    clip_path = os.path.join(output_dir, filename)
    if not os.path.exists(clip_path):
        raise HTTPException(status_code=404, detail=f"Clip file not found: {filename}")

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        result_path, stats = await loop.run_in_executor(
            None, smart_cut, clip_path, transcript,
            clip_data['start'], clip_data['end'], language
        )

        if result_path is None:
            return {
                "success": False,
                "message": "No significant silences or fillers found to remove.",
                "stats": stats
            }

        smartcut_filename = os.path.basename(result_path)
        new_url = f"/videos/{job_id}/{smartcut_filename}"

        return {
            "success": True,
            "new_video_url": new_url,
            "stats": stats
        }

    except Exception as e:
        logger.error("Smart cut error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


class HookRequest(BaseModel):
    job_id: str = Field(..., pattern=r"^[0-9a-fA-F-]{36}$")
    clip_index: int
    text: str
    input_filename: Optional[str] = None
    position: str = "top"
    size: str = "M"

@app.post("/api/hook")
async def add_hook(req: HookRequest):
    if req.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[req.job_id]
    output_dir = os.path.join(OUTPUT_DIR, req.job_id)
    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))

    if not json_files:
        raise HTTPException(status_code=404, detail="Metadata not found")

    with open(json_files[0], 'r') as f:
        data = json.load(f)

    clips = data.get('shorts', [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[req.clip_index]

    if req.input_filename:
        filename = os.path.basename(req.input_filename)
    else:
        filename = clip_data.get('video_url', '').split('/')[-1]
        if not filename:
            base_name = os.path.basename(json_files[0]).replace('_metadata.json', '')
            filename = f"{base_name}_clip_{req.clip_index+1}.mp4"

    input_path = os.path.join(output_dir, filename)
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")

    output_filename = f"hook_{filename}"
    output_path = os.path.join(output_dir, output_filename)

    size_map = {"S": 0.8, "M": 1.0, "L": 1.3}
    font_scale = size_map.get(req.size, 1.0)

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: add_hook_to_video(input_path, req.text, output_path, position=req.position, font_scale=font_scale)
        )
    except Exception as e:
        logger.error("Hook error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    if 'result' in job and 'clips' in job['result'] and req.clip_index < len(job['result']['clips']):
        job['result']['clips'][req.clip_index]['video_url'] = f"/videos/{req.job_id}/{output_filename}"

    try:
        if req.clip_index < len(clips):
            clips[req.clip_index]['video_url'] = f"/videos/{req.job_id}/{output_filename}"
            data['shorts'] = clips
            with open(json_files[0], 'w') as f:
                json.dump(data, f, indent=4)
    except Exception as e:
        logger.warning("Failed to update metadata.json: %s", e)

    return {
        "success": True,
        "new_video_url": f"/videos/{req.job_id}/{output_filename}"
    }


import re as _re

@app.get("/api/history")
async def list_history():
    """Scan output/ for past jobs with metadata files."""
    results = []
    try:
        for entry in os.listdir(OUTPUT_DIR):
            job_dir = os.path.join(OUTPUT_DIR, entry)
            if not os.path.isdir(job_dir) or not _re.match(r'^[0-9a-fA-F-]{36}$', entry):
                continue
            meta_files = glob.glob(os.path.join(job_dir, "*_metadata.json"))
            if not meta_files:
                continue
            try:
                with open(meta_files[0], 'r') as f:
                    data = json.load(f)
                clips = data.get('shorts', [])
                clip_files = []
                for i, clip in enumerate(clips):
                    clip_filename = clip.get('video_url', '').split('/')[-1]
                    if not clip_filename:
                        base_name = os.path.basename(meta_files[0]).replace('_metadata.json', '')
                        clip_filename = f"{base_name}_clip_{i+1}.mp4"
                    clip_path = os.path.join(job_dir, clip_filename)
                    if os.path.exists(clip_path):
                        clip_files.append({
                            "video_url": f"/videos/{entry}/{clip_filename}",
                            "title": clip.get('video_title_for_youtube_short', ''),
                            "start": clip.get('start', 0),
                            "end": clip.get('end', 0),
                        })
                dir_mtime = os.path.getmtime(job_dir)
                results.append({
                    "jobId": entry,
                    "timestamp": int(dir_mtime * 1000),
                    "clipCount": len(clip_files),
                    "clips": clip_files,
                    "cost": data.get('cost_analysis', {}).get('total_cost') if data.get('cost_analysis') else None,
                    "source": os.path.basename(meta_files[0]).replace('_metadata.json', '').replace('_', ' '),
                })
            except Exception:
                continue
    except Exception as e:
        logger.warning("Error scanning history: %s", e)
    results.sort(key=lambda x: x['timestamp'], reverse=True)
    return {"jobs": results}

@app.delete("/api/history/{job_id}")
async def delete_history(job_id: str):
    """Delete a job's output directory and all its files."""
    if not _re.match(r'^[0-9a-fA-F-]{36}$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    if not os.path.isdir(job_dir):
        raise HTTPException(status_code=404, detail="Job not found on disk")
    shutil.rmtree(job_dir, ignore_errors=True)
    if job_id in jobs:
        del jobs[job_id]
    logger.info("Deleted job %s and all files", job_id)
    return {"success": True}

@app.post("/api/history/{job_id}/restore")
async def restore_job(job_id: str):
    """Restore a past job into the in-memory jobs dict so edit/hook/subtitle endpoints work."""
    if not _re.match(r'^[0-9a-fA-F-]{36}$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    if not os.path.isdir(job_dir):
        raise HTTPException(status_code=404, detail="Job not found on disk")
    meta_files = glob.glob(os.path.join(job_dir, "*_metadata.json"))
    if not meta_files:
        raise HTTPException(status_code=404, detail="No metadata found for this job")
    with open(meta_files[0], 'r') as f:
        data = json.load(f)
    clips = data.get('shorts', [])
    base_name = os.path.basename(meta_files[0]).replace('_metadata.json', '')
    for i, clip in enumerate(clips):
        clip_filename = clip.get('video_url', '').split('/')[-1]
        if not clip_filename:
            clip_filename = f"{base_name}_clip_{i+1}.mp4"
        clip['video_url'] = f"/videos/{job_id}/{clip_filename}"
    cost_analysis = data.get('cost_analysis')
    jobs[job_id] = {
        'status': 'completed',
        'logs': ['Restored from disk.'],
        'cmd': [],
        'env': {},
        'output_dir': job_dir,
        'result': {'clips': clips, 'cost_analysis': cost_analysis}
    }
    logger.info("Restored job %s into memory (%d clips)", job_id, len(clips))
    return {
        "success": True,
        "status": "completed",
        "result": {'clips': clips, 'cost_analysis': cost_analysis}
    }
