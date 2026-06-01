import os
import sys
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
from pydantic import BaseModel, Field, ValidationError

from clippyme.domain.job_results import load_partial_result, load_final_result, build_main_cmd
from clippyme.domain.compose import compose_layers
from clippyme.domain.uploads import stream_upload_within_limit, FileTooLarge
from clippyme.domain.clip_endpoints import run_smart_cut, restore_job_from_disk
from clippyme.domain.url_utils import filename_from_video_url
from clippyme.api.schemas import (
    BatchRequest,
    ComposeRequest,
    ConfigUpdateRequest,
    ProcessRequest,
    PublishRequest,
    ReframeRequest,
    ZernioConfigRequest,
)
from clippyme.api.security import (
    ALLOWED_ORIGINS,
    is_trusted_client_host,
    is_trusted_origin,
    parse_allowed_origins,
    require_trusted_config_request,
)
from clippyme.storage.config_store import (
    CONFIG_FILE,
    VALID_CONFIG_KEYS,
    load_persistent_config,
    save_persistent_config,
    load_zernio_config,
    save_zernio_config,
    zernio_config_status,
)
from clippyme.domain.job_artifacts import (
    relocate_root_job_artifacts,
    load_job_metadata,
    save_job_metadata,
)
from clippyme.domain.job_worker import make_workers, enqueue_output
from clippyme.pipeline.gemini_service import list_available_models
from clippyme.domain.history_service import scan_history, is_valid_job_id

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
# Default retention is 30 days — the frontend History tab is the
# authoritative source of truth for what the user considers "done".
# Aggressive auto-purge was destroying clips behind the user's back
# (jobs older than 1 hour vanished on the next cleanup tick, meaning
# every docker restart + 5 min wait blew away yesterday's work).
# Override via env: JOB_RETENTION_SECONDS (0 disables auto-purge).
JOB_RETENTION_SECONDS = int(os.environ.get("JOB_RETENTION_SECONDS", str(30 * 86400)))

# Application State
job_queue = asyncio.Queue(maxsize=50)
jobs: Dict[str, Dict] = {}
# Semaphore to limit concurrency to MAX_CONCURRENT_JOBS
concurrency_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # run_job is defined later in this module, so we bind workers here.
    cleanup_jobs, process_queue, _run_job_wrapper = make_workers(
        jobs=jobs,
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
    from clippyme.integrations.auto_editor_updater import background_updater_loop
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
async def list_gemini_models(
    request: Request,
    api_key: Optional[str] = Header(None, alias="X-Gemini-Key"),
):
    """List available Gemini models using the provided API key."""
    require_trusted_config_request(request)
    return list_available_models(api_key or os.environ.get("GEMINI_API_KEY"))

async def run_job(job_id, job_data):
    """Executes the subprocess for a specific job."""
    
    cmd = job_data['cmd']
    env = job_data['env']
    output_dir = job_data['output_dir']

    # Merge the LATEST persisted config into the job env at run time (not
    # at enqueue time). Fixes a race where the user updates a key
    # (Deepgram / HF / Gemini model / transcription provider) in Settings
    # between submit and dispatch: without this, the worker would use the
    # stale values captured at enqueue. Keys already present in `env`
    # (e.g. GEMINI_API_KEY set from the X-Gemini-Key header) win over the
    # persistent config, matching the reframe-endpoint behaviour.
    try:
        for k, v in (load_persistent_config() or {}).items():
            if v is not None and k not in env:
                env[str(k)] = str(v)
    except Exception as exc:
        logger.warning("Could not merge persistent config into job env for %s: %s", job_id, exc)

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
        
        # Async wait for process with incremental partial-result updates.
        # The partial-result load touches disk, so run it off the event loop
        # to avoid stalling other handlers while a batch of jobs polls.
        while process.poll() is None:
            await asyncio.sleep(2)
            partial = await asyncio.to_thread(load_partial_result, job_id, output_dir)
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
                await asyncio.to_thread(relocate_root_job_artifacts, job_id, output_dir, OUTPUT_DIR)
            final = await asyncio.to_thread(load_final_result, job_id, output_dir)
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
    
    # Handle JSON body via ProcessRequest for URL payloads. Pydantic
    # enforces the reframe_mode regex and the instructions length cap
    # before we hand anything to build_main_cmd. Multipart uploads keep
    # the manual form extraction because the file streaming path is
    # already using FastAPI's File/Form dependencies.
    instructions = None
    reframe_mode = None
    language = None
    no_zoom = False
    skip_analysis = False
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            validated = ProcessRequest.model_validate(body or {})
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.errors())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        url = validated.url
        instructions = validated.instructions
        reframe_mode = validated.reframe_mode
        language = validated.language
        no_zoom = bool(validated.no_zoom)
        skip_analysis = bool(validated.skip_analysis)

    # For multipart/form-data uploads, extract reframe_mode + language from form fields
    if "multipart/form-data" in content_type:
        form = await request.form()
        reframe_mode = form.get("reframe_mode", reframe_mode)
        language = form.get("language", language)
        # Also honour the optional instructions field in multipart mode
        # so drag-and-drop uploads can pass AI directives just like URL
        # submissions (was previously ignored).
        instructions = form.get("instructions", instructions)
        no_zoom = str(form.get("no_zoom", "")).lower() in {"1", "true", "yes"} or no_zoom
        skip_analysis = str(form.get("skip_analysis", "")).lower() in {"1", "true", "yes"} or skip_analysis
        # Validate the multipart values through the same schema for
        # consistency — we drop the url requirement since we're using
        # an uploaded file path.
        try:
            ProcessRequest.model_validate({
                "url": "file://upload",
                "reframe_mode": reframe_mode or None,
                "language": language or None,
                "instructions": instructions or None,
                "no_zoom": no_zoom,
                "skip_analysis": skip_analysis,
            })
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.errors())

    if not url and not file:
        raise HTTPException(status_code=400, detail="Must provide URL or File")

    job_id = str(uuid.uuid4())
    job_output_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_output_dir, exist_ok=True)
    
    env = os.environ.copy()
    env["GEMINI_API_KEY"] = api_key

    input_path = None
    if not url:
        # Save uploaded file with a server-generated name. We deliberately
        # discard the client-supplied filename (path traversal risk) and only
        # preserve a sanitized extension whitelisted to known media formats.
        raw_ext = os.path.splitext(file.filename or "")[1].lower()
        safe_ext = raw_ext if raw_ext in {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"} else ".mp4"
        input_path = os.path.join(UPLOAD_DIR, f"{job_id}{safe_ext}")
        try:
            await stream_upload_within_limit(file, input_path, MAX_FILE_SIZE_MB * 1024 * 1024)
        except FileTooLarge as exc:
            # The helper already removed the partial upload; we still own the
            # per-job output dir, so clean that up before surfacing the 413.
            shutil.rmtree(job_output_dir, ignore_errors=True)
            raise HTTPException(status_code=413, detail=str(exc)) from exc

    try:
        cmd = build_main_cmd(
            url=url,
            input_path=input_path,
            output_dir=job_output_dir,
            instructions=instructions,
            reframe_mode=reframe_mode,
            cookies_path=os.path.join("data", "cookies.txt"),
            language=language,
            no_zoom=no_zoom,
            skip_analysis=skip_analysis,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

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

    batch_jobs = []

    for url in req.urls:
        url = url.strip()
        if not url:
            continue

        job_id = str(uuid.uuid4())
        job_output_dir = os.path.join(OUTPUT_DIR, job_id)
        os.makedirs(job_output_dir, exist_ok=True)

        try:
            cmd = build_main_cmd(
                url=url,
                output_dir=job_output_dir,
                instructions=req.instructions,
                reframe_mode=req.reframe_mode,
                cookies_path=os.path.join("data", "cookies.txt"),
                language=getattr(req, "language", None),
                no_zoom=bool(getattr(req, "no_zoom", False)),
                skip_analysis=bool(getattr(req, "skip_analysis", False)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        env = os.environ.copy()
        env["GEMINI_API_KEY"] = api_key

        jobs[job_id] = {
            'status': 'queued',
            'logs': [f"Job {job_id} queued (batch)."],
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

    return {"jobs": batch_jobs, "total": len(batch_jobs)}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
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
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
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

COOKIES_MAX_BYTES = 10 * 1024 * 1024  # 10 MB hard cap

@app.post("/api/config/cookies")
async def upload_cookies(request: Request, cookies_file: UploadFile = File(...)):
    """Upload and persist a Netscape-format cookies.txt file."""
    require_trusted_config_request(request)
    os.makedirs("data", exist_ok=True)
    cookies_path = os.path.join("data", "cookies.txt")

    # Stream-read with hard size cap to avoid buffering arbitrary uploads in RAM.
    chunks: list[bytes] = []
    total = 0
    while chunk := await cookies_file.read(64 * 1024):
        total += len(chunk)
        if total > COOKIES_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Cookies file too large (max 10 MB)")
        chunks.append(chunk)
    content = b"".join(chunks)

    # Validate Netscape format: first non-comment line should mention the header
    # or look like a tab-separated cookie row. We accept either the canonical
    # header or a permissive check that ensures the file is plain text.
    try:
        text_head = content[:4096].decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Cookies file must be UTF-8 text")
    if "Netscape HTTP Cookie File" not in text_head and "\t" not in text_head:
        raise HTTPException(status_code=400, detail="File does not look like a Netscape cookies.txt")

    fd = os.open(cookies_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return {"status": "ok", "message": "Cookies saved"}

@app.get("/api/config/cookies/status")
async def cookies_status(request: Request):
    """Check if a cookies file is configured."""
    require_trusted_config_request(request)
    cookies_path = os.path.join("data", "cookies.txt")
    return {"configured": os.path.exists(cookies_path)}

@app.delete("/api/config/cookies")
async def delete_cookies(request: Request):
    """Remove the persisted cookies file."""
    require_trusted_config_request(request)
    cookies_path = os.path.join("data", "cookies.txt")
    if os.path.exists(cookies_path):
        os.remove(cookies_path)
    return {"status": "ok", "message": "Cookies removed"}

from clippyme.domain.smartcut import smart_cut

@app.post("/api/smartcut/{job_id}/{clip_index}")
async def smart_cut_clip(job_id: str, clip_index: int):
    """Generate a smart-cut version of a clip (silences + filler words removed)."""
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
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


@app.post("/api/reframe/{job_id}/{clip_index}")
async def reframe_clip(job_id: str, clip_index: int, req: ReframeRequest):
    """Switch a clip between reframe modes (auto ↔ disabled) after generation.

    Requires the per-clip 16:9 source slice (``source_<clip>.mp4``) to still
    exist on disk. Spawns ``main.py --reframe-only`` as a subprocess to reuse
    the exact same reframing / zoom / normalize / cover pipeline the initial
    run used. Updates metadata.json and the in-memory job state so the
    dashboard picks up the new video URL on the next poll.
    """
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job_id")
    mode = (req.reframe_mode or "auto").strip().lower()
    if mode not in ("auto", "disabled"):
        raise HTTPException(status_code=400, detail="reframe_mode must be 'auto' or 'disabled'")

    output_dir = os.path.join(OUTPUT_DIR, job_id)
    if not os.path.isdir(output_dir):
        raise HTTPException(status_code=404, detail="Job output dir not found")

    try:
        metadata_path, data = load_job_metadata(job_id, OUTPUT_DIR)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Metadata not found")

    clips = data.get("shorts", [])
    if clip_index < 0 or clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[clip_index]

    # Resolve the current clip filename (same logic as smartcut / subtitle)
    filename = filename_from_video_url(clip_data.get("video_url"))
    if not filename:
        base_name = os.path.basename(metadata_path).replace("_metadata.json", "")
        filename = f"{base_name}_clip_{clip_index + 1}.mp4"

    # Target path = the ORIGINAL reframed clip path (we overwrite it in place
    # so all downstream references — subtitle/hook/compose — keep working).
    base_name = os.path.basename(metadata_path).replace("_metadata.json", "")
    original_clip_filename = f"{base_name}_clip_{clip_index + 1}.mp4"
    target_path = os.path.join(output_dir, original_clip_filename)
    source_path = os.path.join(output_dir, f"source_{original_clip_filename}")

    if not os.path.exists(source_path):
        raise HTTPException(
            status_code=409,
            detail=(
                "Source slice not available for this clip — this job was "
                "generated before the post-hoc reframe feature landed. "
                "Re-process the source to enable mode switching."
            ),
        )

    cmd = [
        sys.executable,
        "-m",
        "clippyme.pipeline.main",
        "--reframe-only",
        "-i", source_path,
        "-o", target_path,
        "--reframe-mode", mode,
    ]

    logger.info("Reframe subprocess: %s", " ".join(cmd))

    # Propagate persisted config (Deepgram / HF / Gemini keys, transcription
    # provider, etc.) into the subprocess env. Without this, the reframe-only
    # path could silently fall back to Whisper when the user expects Deepgram,
    # or fail transcription entirely if the keys live only in data/config.json.
    reframe_env = os.environ.copy()
    try:
        for k, v in (load_persistent_config() or {}).items():
            if v is not None and k not in reframe_env:
                reframe_env[str(k)] = str(v)
    except Exception as exc:
        logger.warning("Could not merge persistent config into reframe env: %s", exc)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=reframe_env,
        )
        stdout_data, _ = await proc.communicate()
    except Exception as e:
        logger.error("Reframe subprocess launch failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to launch reframe: {e}")

    output_text = (stdout_data or b"").decode(errors="replace")
    if proc.returncode != 0:
        logger.error("Reframe failed (code %s):\n%s", proc.returncode, output_text[-2000:])
        raise HTTPException(
            status_code=500,
            detail=f"Reframe failed (exit {proc.returncode}). Last output: {output_text[-400:]}",
        )

    # Cache-busting suffix so the <video> element reloads.
    # CRITICAL: the query string MUST NOT end up in the stored video_url —
    # the publish endpoint (and any future consumer) resolves the clip
    # file on disk via `video_url.split("/")[-1]`, so a trailing `?v=...`
    # would produce `clip_1.mp4?v=1234` and a "clip file not found" error
    # on upload. Keep the clean path in metadata and append cache-bust
    # only in the HTTP response, which is what the <video> element sees.
    cache_bust = int(time.time())
    clean_video_url = f"/videos/{job_id}/{original_clip_filename}"
    new_video_url = f"{clean_video_url}?v={cache_bust}"

    # Update metadata.json and in-memory job state with the CLEAN url
    try:
        clips[clip_index]["video_url"] = clean_video_url
        clips[clip_index]["reframe_mode"] = mode
        data["shorts"] = clips
        save_job_metadata(metadata_path, data)
    except Exception as e:
        logger.warning("Failed to update metadata.json after reframe: %s", e)

    if (
        job_id in jobs
        and "result" in jobs[job_id]
        and "clips" in jobs[job_id]["result"]
        and clip_index < len(jobs[job_id]["result"]["clips"])
    ):
        # In-memory state also gets the clean URL — the frontend applies
        # its own cache-bust via `new_video_url` below on the <video> tag.
        jobs[job_id]["result"]["clips"][clip_index]["video_url"] = clean_video_url
        jobs[job_id]["result"]["clips"][clip_index]["reframe_mode"] = mode

    return {
        "success": True,
        "new_video_url": new_video_url,
        "reframe_mode": mode,
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
    clip_filename = filename_from_video_url(clip_info.get("video_url"))
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
        raise HTTPException(status_code=500, detail="Compose pipeline failed")


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
    from clippyme.integrations.social_publisher import ZernioClient, ZernioError
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

    # Resolve the source clip via the shared helper — safe against
    # cache-busting query strings left behind by old reframe responses.
    base_filename = filename_from_video_url(clip_info.get("video_url"))
    if not base_filename:
        base_name = os.path.basename(metadata_files[0]).replace("_metadata.json", "")
        base_filename = f"{base_name}_clip_{clip_index + 1}.mp4"
    base_clip = os.path.join(job_dir, base_filename)

    upload_path = base_clip
    composed_path = os.path.join(job_dir, f"composed_clip_{clip_index}.mp4")

    logger.info(
        "publish_clip_endpoint: job=%s clip=%d compose_first=%s toggles=%s has_hook_params=%s has_sub_params=%s",
        job_id, clip_index, req.compose_first,
        list((req.toggles or {}).keys()),
        bool(req.hook_params),
        bool(req.subtitle_params),
    )

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
    from clippyme.integrations.social_publisher import publish_clip, ZernioError
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
            start_date=req.start_date,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ZernioError as e:
        logger.error("publish: Zernio error: %s (status=%s body=%s)",
                     e, e.status_code, (e.body or "")[:200])
        # Include the full response body (truncated) in the HTTPException
        # detail so the frontend can parse per-platform failures like the
        # Zernio "Daily limit reached" 429 and skip the exhausted platform
        # for the rest of a batch publish run.
        body_snippet = (e.body or "")[:500]
        detail_msg = f"Zernio API error: {e}"
        if body_snippet:
            detail_msg = f"{detail_msg} | body={body_snippet}"
        raise HTTPException(
            status_code=502 if e.status_code is None else e.status_code,
            detail=detail_msg,
        )
    except Exception:
        logger.exception("publish: unexpected error")
        raise HTTPException(status_code=500, detail="Publish failed")

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
