import os
import uuid
import subprocess
import threading
import json
import shutil
import glob
import time
import asyncio
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

from job_results import load_partial_result, load_final_result, build_main_cmd
from schemas import (
    BatchRequest,
    ComposeRequest,
    ConfigUpdateRequest,
    HookRequest,
    ProcessRequest,
    SubtitleRequest,
)
from security import (
    ALLOWED_ORIGINS,
    is_trusted_client_host,
    is_trusted_origin,
    parse_allowed_origins,
    require_trusted_config_request,
)
from config_store import (
    CONFIG_FILE,
    VALID_CONFIG_KEYS,
    load_persistent_config,
    save_persistent_config,
)
from job_artifacts import (
    relocate_root_job_artifacts,
    load_job_metadata,
    save_job_metadata,
)
from job_worker import make_workers, enqueue_output
from gemini_service import list_available_models
from history_service import scan_history, is_valid_job_id

load_dotenv()

# Constants
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "output"
DATA_DIR = "data"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    # run_job is defined later in this module, so we bind workers here.
    cleanup_jobs, process_queue, _run_job_wrapper = make_workers(
        jobs=jobs,
        batches=batches,
        job_queue=job_queue,
        concurrency_semaphore=concurrency_semaphore,
        run_job=run_job,
        output_dir=OUTPUT_DIR,
        upload_dir=UPLOAD_DIR,
        data_dir=DATA_DIR,
        job_retention_seconds=JOB_RETENTION_SECONDS,
        max_concurrent_jobs=MAX_CONCURRENT_JOBS,
    )
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

# Mount static files for serving fonts (used by subtitle preview in frontend)
app.mount("/fonts", StaticFiles(directory="fonts"), name="fonts")

@app.get("/")
async def root():
    return {"status": "online", "message": "ClippyMe API is running"}

@app.get("/api/health")
async def health():
    return {"status": "healthy"}

@app.get("/api/config/models")
async def list_gemini_models(api_key: Optional[str] = Header(None, alias="X-Gemini-Key")):
    """List available Gemini models using the provided API key."""
    return list_available_models(api_key or os.environ.get("GEMINI_API_KEY"))

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
        t_log = threading.Thread(target=enqueue_output, args=(process.stdout, job_id, jobs))
        t_log.daemon = True
        t_log.start()
        
        # Async wait for process with incremental partial-result updates
        while process.poll() is None:
            await asyncio.sleep(2)
            partial = load_partial_result(job_id, output_dir)
            if partial:
                jobs[job_id]['result'] = partial

        returncode = process.returncode

        if jobs[job_id]['status'] == 'cancelled':
            jobs[job_id]['logs'].append("Process terminated (cancelled).")
        elif returncode == 0:
            jobs[job_id]['status'] = 'completed'
            jobs[job_id]['logs'].append("Process finished successfully.")
            # Backward-compat rescue if outputs were written to OUTPUT_DIR root
            if not glob.glob(os.path.join(output_dir, "*_metadata.json")):
                relocate_root_job_artifacts(job_id, output_dir, OUTPUT_DIR)
            final = load_final_result(job_id, output_dir)
            if final:
                jobs[job_id]['result'] = final
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

    # For multipart/form-data uploads, extract reframe_mode from form fields
    if "multipart/form-data" in content_type:
        form = await request.form()
        reframe_mode = form.get("reframe_mode", reframe_mode)

    if not url and not file:
        raise HTTPException(status_code=400, detail="Must provide URL or File")

    job_id = str(uuid.uuid4())
    job_output_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_output_dir, exist_ok=True)
    
    env = os.environ.copy()
    env["GEMINI_API_KEY"] = api_key

    input_path = None
    if not url:
        # Save uploaded file with size limit check
        input_path = os.path.join(UPLOAD_DIR, f"{job_id}_{file.filename}")
        size = 0
        limit_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
        with open(input_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):
                size += len(content)
                if size > limit_bytes:
                    os.remove(input_path)
                    shutil.rmtree(job_output_dir)
                    raise HTTPException(status_code=413, detail=f"File too large. Max size {MAX_FILE_SIZE_MB}MB")
                buffer.write(content)

    cmd = build_main_cmd(
        url=url,
        input_path=input_path,
        output_dir=job_output_dir,
        instructions=instructions,
        reframe_mode=reframe_mode,
        cookies_path=os.path.join("data", "cookies.txt"),
    )

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

        cmd = build_main_cmd(
            url=url,
            output_dir=job_output_dir,
            instructions=req.instructions,
            reframe_mode=req.reframe_mode,
        )

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

@app.post("/api/subtitle")
async def add_subtitles(req: SubtitleRequest):
    if req.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[req.job_id]
    output_dir = os.path.join(OUTPUT_DIR, req.job_id)
    try:
        metadata_path, data = load_job_metadata(req.job_id, OUTPUT_DIR)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Metadata not found")

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
             base_name = os.path.basename(metadata_path).replace('_metadata.json', '')
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
            save_job_metadata(metadata_path, data)
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
    try:
        metadata_path, data = load_job_metadata(job_id, OUTPUT_DIR)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Metadata not found")

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
        base_name = os.path.basename(metadata_path).replace('_metadata.json', '')
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


@app.post("/api/hook")
async def add_hook(req: HookRequest):
    if req.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[req.job_id]
    output_dir = os.path.join(OUTPUT_DIR, req.job_id)
    try:
        metadata_path, data = load_job_metadata(req.job_id, OUTPUT_DIR)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Metadata not found")

    clips = data.get('shorts', [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[req.clip_index]

    if req.input_filename:
        filename = os.path.basename(req.input_filename)
    else:
        filename = clip_data.get('video_url', '').split('/')[-1]
        if not filename:
            base_name = os.path.basename(metadata_path).replace('_metadata.json', '')
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
            save_job_metadata(metadata_path, data)
    except Exception as e:
        logger.warning("Failed to update metadata.json: %s", e)

    return {
        "success": True,
        "new_video_url": f"/videos/{req.job_id}/{output_filename}"
    }


@app.get("/api/history")
async def list_history():
    """Scan output/ for past jobs with metadata files."""
    return {"jobs": scan_history(OUTPUT_DIR)}

@app.delete("/api/history/{job_id}")
async def delete_history(job_id: str):
    """Delete a job's output directory and all its files."""
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    if not os.path.isdir(job_dir):
        raise HTTPException(status_code=404, detail="Job not found on disk")
    shutil.rmtree(job_dir, ignore_errors=True)
    if job_id in jobs:
        del jobs[job_id]
    logger.info("Deleted job %s and all files", job_id)
    return {"success": True}

@app.post("/api/compose/{job_id}/{clip_index}")
async def compose_clip(job_id: str, clip_index: int, req: ComposeRequest):
    """Compose a final video from active toggle layers (Smart Cut → Hook → Subtitles)."""
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")

    job_dir = os.path.join(OUTPUT_DIR, job_id)
    if not os.path.isdir(job_dir):
        raise HTTPException(status_code=404, detail="Job not found")

    # Find metadata
    metadata_files = glob.glob(os.path.join(job_dir, "*_metadata.json"))
    if not metadata_files:
        raise HTTPException(status_code=404, detail="No metadata found")

    with open(metadata_files[0]) as f:
        metadata = json.load(f)

    clips = metadata.get("shorts", [])
    if clip_index < 0 or clip_index >= len(clips):
        raise HTTPException(status_code=400, detail="Invalid clip index")

    clip_info = clips[clip_index]

    # Resolve the base clip filename (same logic as other endpoints)
    clip_filename = clip_info.get("video_url", "").split("/")[-1]
    if not clip_filename:
        base_name = os.path.basename(metadata_files[0]).replace("_metadata.json", "")
        clip_filename = f"{base_name}_clip_{clip_index + 1}.mp4"
    base_clip = os.path.join(job_dir, clip_filename)

    if not os.path.exists(base_clip):
        raise HTTPException(status_code=404, detail="Clip file not found")

    active = {k: v for k, v in req.toggles.items() if v}
    if not active:
        return {"composed_url": f"/videos/{job_id}/{clip_filename}"}

    current_input = base_clip
    intermediate_files = []  # Track files to clean up

    try:
        # Step 1: Smart Cut
        if active.get("smartcut"):
            smartcut_path = base_clip.replace(".mp4", "_smartcut.mp4")
            if os.path.exists(smartcut_path):
                current_input = smartcut_path
            else:
                transcript = metadata.get("transcript", {})
                clip_start = clip_info.get("start", 0)
                clip_end = clip_info.get("end", 0)
                language = transcript.get("language")
                loop = asyncio.get_event_loop()
                sc_output, sc_stats = await loop.run_in_executor(
                    None, smart_cut, current_input, transcript, clip_start, clip_end, language
                )
                if sc_output:
                    current_input = sc_output

        # Step 2: Hook
        if active.get("hook") and req.hook_params.get("text"):
            from hooks import add_hook_to_video
            hook_output = os.path.join(job_dir, f"composed_hook_{clip_index}.mp4")
            intermediate_files.append(hook_output)
            position = req.hook_params.get("position", "top")
            size_map = {"S": 0.8, "M": 1.0, "L": 1.3}
            font_scale = size_map.get(req.hook_params.get("size", "M"), 1.0)
            hook_offset_y = req.hook_params.get("offset_y", 0)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, add_hook_to_video, current_input, req.hook_params["text"],
                hook_output, position, font_scale, hook_offset_y
            )
            current_input = hook_output

        # Step 3: Subtitles
        if active.get("subtitles"):
            sub_output = os.path.join(job_dir, f"composed_sub_{clip_index}.mp4")
            intermediate_files.append(sub_output)
            transcript = metadata.get("transcript", {})
            clip_start = clip_info.get("start", 0)
            clip_end = clip_info.get("end", 0)
            sub_mode = req.subtitle_params.get("mode", "karaoke")
            sub_offset_y = req.subtitle_params.get("offset_y", 0)

            if sub_mode == "karaoke":
                preset_name = req.subtitle_params.get("preset", "classic_white")
                ass_path = os.path.join(job_dir, f"composed_subs_{clip_index}.ass")
                intermediate_files.append(ass_path)
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(
                    None, lambda: generate_ass_karaoke(
                        transcript, clip_start, clip_end, ass_path,
                        preset=preset_name,
                        mode=req.subtitle_params.get("display_mode", "word_group"),
                        uppercase=req.subtitle_params.get("uppercase", True),
                        highlight_color=req.subtitle_params.get("highlight_color"),
                        font_name=req.subtitle_params.get("font"),
                        font_size=req.subtitle_params.get("font_size"),
                        position=req.subtitle_params.get("position", "bottom"),
                        offset_y=sub_offset_y
                    )
                )
                if not success:
                    raise HTTPException(status_code=400, detail="No words found for this clip range.")
                await loop.run_in_executor(
                    None, burn_subtitles, current_input, ass_path, sub_output, 2, 16,
                    "Verdana", "#FFFFFF", "#000000", 2, "#000000", 0.0, sub_offset_y
                )
            else:
                srt_path = os.path.join(job_dir, f"composed_subs_{clip_index}.srt")
                intermediate_files.append(srt_path)
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(
                    None, generate_srt, transcript, clip_start, clip_end, srt_path
                )
                if not success:
                    raise HTTPException(status_code=400, detail="No words found for this clip range.")
                await loop.run_in_executor(
                    None, lambda: burn_subtitles(
                        current_input, srt_path, sub_output,
                        alignment=req.subtitle_params.get("position", "bottom"),
                        fontsize=req.subtitle_params.get("font_size", 16),
                        font_name=req.subtitle_params.get("font", "Verdana"),
                        font_color=req.subtitle_params.get("font_color", "#FFFFFF"),
                        border_color=req.subtitle_params.get("border_color", "#000000"),
                        border_width=req.subtitle_params.get("border_width", 2),
                        bg_color=req.subtitle_params.get("bg_color", "#000000"),
                        bg_opacity=req.subtitle_params.get("bg_opacity", 0.0),
                        offset_y=sub_offset_y
                    )
                )
            current_input = sub_output

        # Copy to final composed path
        composed_filename = f"composed_clip_{clip_index}.mp4"
        composed_path = os.path.join(job_dir, composed_filename)
        if os.path.abspath(current_input) != os.path.abspath(composed_path):
            shutil.copy2(current_input, composed_path)

        # Clean up intermediate files
        for temp_file in intermediate_files:
            if temp_file and os.path.exists(temp_file) and os.path.abspath(temp_file) != os.path.abspath(composed_path):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass

        return {"composed_url": f"/videos/{job_id}/{composed_filename}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Compose error for job %s clip %d: %s", job_id, clip_index, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/history/{job_id}/restore")
async def restore_job(job_id: str):
    """Restore a past job into the in-memory jobs dict so edit/hook/subtitle endpoints work."""
    if not is_valid_job_id(job_id):
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
