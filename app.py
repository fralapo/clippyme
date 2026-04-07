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
from compose import compose_layers
from subtitle_pipeline import resolve_clip_filename, run_subtitle_pipeline
from clip_endpoints import run_smart_cut, restore_job_from_disk
from schemas import (
    BatchRequest,
    ComposeRequest,
    ConfigUpdateRequest,
    HookRequest,
    ProcessRequest,
    PublishRequest,
    SubtitleRequest,
    ZernioConfigRequest,
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
    load_zernio_config,
    save_zernio_config,
    zernio_config_status,
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
    # Background auto-update for the auto-editor binary used by smartcut.py.
    # Failures are non-fatal — smartcut has an FFmpeg fallback path.
    from auto_editor_updater import background_updater_loop
    ae_updater_task = asyncio.create_task(background_updater_loop())
    yield
    ae_updater_task.cancel()

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
    
    filename = resolve_clip_filename(req, clip_data, metadata_path)
    input_path = os.path.join(output_dir, filename)
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")

    output_filename = f"subtitled_{filename}"
    try:
        await run_subtitle_pipeline(
            req=req,
            output_dir=output_dir,
            transcript=transcript,
            clip_data=clip_data,
            input_path=input_path,
            output_filename=output_filename,
        )
    except HTTPException:
        raise
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
    return await run_smart_cut(
        job_id=job_id,
        clip_index=clip_index,
        output_dir=output_dir,
        metadata_path=metadata_path,
        data=data,
    )


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

    filename = resolve_clip_filename(req, clip_data, metadata_path)
    input_path = os.path.join(output_dir, filename)
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")

    output_filename = f"hook_{filename}"
    output_path = os.path.join(output_dir, output_filename)
    font_scale = {"S": 0.8, "M": 1.0, "L": 1.3}.get(req.size, 1.0)

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: add_hook_to_video(
                input_path, req.text, output_path, position=req.position, font_scale=font_scale
            ),
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

    try:
        composed_filename = await compose_layers(
            base_clip=base_clip,
            job_dir=job_dir,
            clip_index=clip_index,
            metadata=metadata,
            clip_info=clip_info,
            toggles=req.toggles,
            hook_params=req.hook_params,
            subtitle_params=req.subtitle_params,
        )
        return {"composed_url": f"/videos/{job_id}/{composed_filename}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Compose error for job %s clip %d: %s", job_id, clip_index, e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Publish (Zernio) endpoints
# ---------------------------------------------------------------------------

@app.get("/api/config/zernio")
async def get_zernio_config(request: Request):
    """Return persisted Zernio settings (api_key masked)."""
    require_trusted_config_request(request)
    return zernio_config_status()


@app.post("/api/config/zernio")
async def update_zernio_config(req: ZernioConfigRequest, request: Request):
    """Update Zernio API key + accounts + timezone (merge semantics)."""
    require_trusted_config_request(request)
    ok = save_zernio_config(
        api_key=req.api_key,
        accounts=req.accounts,
        timezone=req.timezone,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save Zernio config")
    return zernio_config_status()


@app.get("/api/zernio/accounts")
async def list_zernio_accounts(request: Request):
    """Discovery: list connected social accounts via Zernio API."""
    require_trusted_config_request(request)
    cfg = load_zernio_config()
    api_key = cfg.get("api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Zernio API key not configured")
    from social_publisher import ZernioClient, ZernioError
    try:
        client = ZernioClient(api_key)
        accounts = client.list_accounts()
    except ZernioError as e:
        raise HTTPException(status_code=502, detail=f"Zernio API error: {e}")
    return {"accounts": accounts}


@app.post("/api/publish/{job_id}/{clip_index}")
async def publish_clip_endpoint(job_id: str, clip_index: int, req: PublishRequest):
    """Upload a clip to Zernio and create a post on the requested platforms.

    If req.compose_first is True, the clip is freshly composed (Smart Cut →
    Hook → Subtitles) using req.toggles before upload — same flow as
    /api/compose. Otherwise we look for an existing composed_clip_{i}.mp4
    on disk and fall back to the base clip.
    """
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    if not os.path.isdir(job_dir):
        raise HTTPException(status_code=404, detail="Job not found")

    cfg = load_zernio_config()
    api_key = cfg.get("api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Zernio API key not configured")

    metadata_files = glob.glob(os.path.join(job_dir, "*_metadata.json"))
    if not metadata_files:
        raise HTTPException(status_code=404, detail="No metadata found")
    with open(metadata_files[0]) as f:
        metadata = json.load(f)
    clips = metadata.get("shorts", [])
    if clip_index < 0 or clip_index >= len(clips):
        raise HTTPException(status_code=400, detail="Invalid clip index")
    clip_info = clips[clip_index]

    # Resolve the source clip
    base_filename = clip_info.get("video_url", "").split("/")[-1]
    if not base_filename:
        base_name = os.path.basename(metadata_files[0]).replace("_metadata.json", "")
        base_filename = f"{base_name}_clip_{clip_index + 1}.mp4"
    base_clip = os.path.join(job_dir, base_filename)

    upload_path = base_clip
    composed_path = os.path.join(job_dir, f"composed_clip_{clip_index}.mp4")

    if req.compose_first and req.toggles:
        try:
            composed_filename = await compose_layers(
                base_clip=base_clip,
                job_dir=job_dir,
                clip_index=clip_index,
                metadata=metadata,
                clip_info=clip_info,
                toggles=req.toggles,
                hook_params=req.hook_params or {},
                subtitle_params=req.subtitle_params or {},
            )
            upload_path = os.path.join(job_dir, composed_filename)
        except Exception as e:
            logger.error("publish: compose_layers failed for %s/%d: %s", job_id, clip_index, e)
            raise HTTPException(status_code=500, detail=f"Compose before publish failed: {e}")
    elif os.path.exists(composed_path):
        upload_path = composed_path

    if not os.path.exists(upload_path):
        raise HTTPException(status_code=404, detail=f"Clip file not found: {upload_path}")

    # Run the publish in a worker thread (presign + PUT + create are blocking)
    from social_publisher import publish_clip, ZernioError
    try:
        result = await asyncio.to_thread(
            publish_clip,
            api_key=api_key,
            clip_path=upload_path,
            title=req.title or clip_info.get("title", "")[:100] or f"Clip {clip_index + 1}",
            caption=req.caption or "",
            platform_targets=req.platforms,
            schedule_mode=req.schedule_mode,
            scheduled_for=req.scheduled_for,
            timezone=req.timezone or cfg.get("timezone") or "Europe/Rome",
            tiktok_settings=req.tiktok_settings,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ZernioError as e:
        logger.error("publish: Zernio error: %s (status=%s body=%s)",
                     e, e.status_code, (e.body or "")[:200])
        raise HTTPException(
            status_code=502 if e.status_code is None else e.status_code,
            detail=f"Zernio API error: {e}",
        )
    except Exception as e:
        logger.exception("publish: unexpected error")
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True, **result}


@app.post("/api/history/{job_id}/restore")
async def restore_job(job_id: str):
    """Restore a past job into the in-memory jobs dict so edit/hook/subtitle endpoints work."""
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    job_entry = restore_job_from_disk(job_id, OUTPUT_DIR, job_dir)
    jobs[job_id] = job_entry
    logger.info("Restored job %s into memory (%d clips)", job_id, len(job_entry["result"]["clips"]))
    return {"success": True, "status": "completed", "result": job_entry["result"]}
