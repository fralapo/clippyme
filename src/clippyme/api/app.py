import os
import sys
import uuid
import shutil
import asyncio
import logging
from dotenv import load_dotenv
from typing import Dict, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("clippyme")

# The pinned dependency set (faster-whisper, mediapipe, etc.) is only tested on
# Python 3.11+. Warn loudly rather than failing with a cryptic import error on
# an older interpreter.
if sys.version_info < (3, 11):
    logger.warning(
        "ClippyMe requires Python 3.11+. Detected %s — imports may fail or behave unexpectedly.",
        ".".join(map(str, sys.version_info[:3])),
    )

from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from clippyme.domain.job_results import build_main_cmd, canonical_reframe_mode
from clippyme.domain.compose import compose_layers
from clippyme.domain.reframe_service import run_reframe
from clippyme.domain.errors import ClippyMeError
from clippyme.domain.uploads import stream_upload_within_limit, FileTooLarge
from clippyme.domain.clip_endpoints import run_smart_cut, restore_job_from_disk
from clippyme.domain.clip_resolve import resolve_clip
from clippyme.domain import job_control
from clippyme.domain.job_actions import cancel_job_action, stop_job_action
from clippyme.domain.job_journal import JOURNAL_FILENAME, make_journal_writer, recover_jobs
from clippyme.domain.job_runner import make_run_job
from clippyme.domain.job_submission import QueueFullError, submit_job
from clippyme.domain.publish_service import publish_clip_flow
from clippyme.api.schemas import (
    BatchRequest,
    ComposeRequest,
    EditAIRequest,
    LiveMonitorStartRequest,
    ProcessRequest,
    PublishRequest,
    ReframeRequest,
    _validate_drop_ranges,
)
from clippyme.api.security import (
    ALLOWED_ORIGINS,
    enforce_api_token,
    enforce_rate_limit,
    require_trusted_config_request,
)
from clippyme.storage.config_store import (
    load_persistent_config,
    save_persistent_config,
    load_zernio_config,
)
from clippyme.domain.job_worker import make_workers
from clippyme.domain.history_service import scan_history, is_valid_job_id
from clippyme.api.config_routes import router as config_router

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
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "16384"))
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

# Job journal: persists the ACTIVE jobs to data/jobs_journal.json on every
# status transition so a restart can re-enqueue queued jobs and fail (or
# restore) interrupted ones instead of silently forgetting them.
JOURNAL_PATH = os.path.join(DATA_DIR, JOURNAL_FILENAME)
persist_jobs = make_journal_writer(jobs=jobs, path=JOURNAL_PATH)

# The per-job subprocess runner, bound to the shared jobs dict (thin-handler
# rule: the body lives in clippyme.domain.job_runner).
run_job = make_run_job(jobs=jobs, output_root=OUTPUT_DIR, on_change=persist_jobs)

# Multi-platform content monitor registry: concurrent asyncio tasks (one per
# platform:channel) that detect live streams / new VODs, submit them as normal
# jobs, and auto-publish clips with GLOBAL publish spacing. Bound to the same
# shared job state (thin-handler rule: logic lives in domain.live_monitor).
from clippyme.domain.live_monitor import LiveMonitorRegistry
live_monitor = LiveMonitorRegistry(
    jobs=jobs, job_queue=job_queue, output_dir=OUTPUT_DIR,
    upload_dir=UPLOAD_DIR, on_job_change=persist_jobs,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Recover journalled jobs from the previous server life BEFORE the
    # dispatcher starts: queued jobs are re-enqueued, interrupted ones are
    # marked failed (or restored as completed when their result is on disk).
    # Runs on the event loop (not to_thread): asyncio.Queue.put_nowait is not
    # thread-safe, and the journal is small so the startup pause is negligible.
    try:
        recover_jobs(journal_path=JOURNAL_PATH, jobs=jobs,
                     job_queue=job_queue, output_root=OUTPUT_DIR)
    except Exception:
        logger.exception("Job journal recovery failed — starting with an empty queue")

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
    # Bring back every monitor that was still marked resume_on_start when the
    # process last went down (durable auto-resume). Never fatal to startup —
    # a per-monitor failure stays visible via its status() instead.
    try:
        await live_monitor.auto_resume()
    except Exception:
        logger.exception("live monitor auto-resume failed")
    yield
    # Stop the live monitor first so its in-flight capture/publish tasks unwind
    # cleanly before we tear down the worker loops they depend on. shutdown()
    # (not stop()) so resume_on_start survives for the next auto-resume.
    try:
        await live_monitor.shutdown()
    except Exception:
        logger.exception("live monitor failed to stop cleanly")
    # Cancel ALL background tasks on shutdown — not just the updater. Leaving
    # the worker/cleanup loops pending blocks uvicorn's graceful exit and logs
    # "Task was destroyed but it is pending!" tracebacks.
    _bg_tasks = (worker_task, cleanup_task, ae_updater_task)
    for _t in _bg_tasks:
        _t.cancel()
    for _t in _bg_tasks:
        try:
            await _t
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("background task raised during shutdown")

app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def _api_token_gate(request: Request, call_next):
    """Optional shared-secret auth for deliberate LAN deployments.

    Active only when CLIPPYME_API_TOKEN is set (default unset = no-op). Guards
    every /api route; the static media mounts (/videos, /thumbnails, /fonts)
    stay IP-open because <video>/<img>/FontFace requests can't attach custom
    headers. HTTPException is converted here because raise inside middleware
    bypasses FastAPI's exception handlers.
    """
    if request.url.path.startswith("/api/") and request.method != "OPTIONS":
        try:
            enforce_api_token(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Add OWASP-recommended hardening headers to every response.

    - nosniff: block MIME-confusion attacks on served media/JSON.
    - frame-ancestors/X-Frame-Options: clickjacking defence.
    - Referrer-Policy: don't leak full URLs (job ids) to third parties.
    - CSP default-src 'none': the API serves JSON + media consumed by the
      separate Vite frontend; it should never itself be a script/HTML host.
    Ref: OWASP Secure Headers Project.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    return response


@app.exception_handler(ClippyMeError)
async def _clippyme_error_handler(request: Request, exc: ClippyMeError):
    """Map domain exceptions to HTTP responses so domain modules don't need
    to import FastAPI's HTTPException."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception):
    """Catch-all so a stray exception never leaks a traceback / internal path
    to the client. FastAPI's HTTPException is handled separately and is not
    affected by this."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-Gemini-Key", "X-API-Token"],
)

# Mount static files for serving videos.
# The output directory also holds *_metadata.json (full transcripts + AI
# analysis) and source_*.mp4 (the raw 16:9 slices). Those are internal
# artifacts and must NOT be publicly downloadable — only the rendered clips,
# composed clips, covers and thumbnails are user-facing. SafeStaticFiles
# 404s the sensitive patterns while serving everything else as before.
class SafeStaticFiles(StaticFiles):
    _BLOCKED_SUFFIXES = ("_metadata.json",)
    _BLOCKED_PREFIXES = ("source_",)

    async def get_response(self, path, scope):
        leaf = os.path.basename(path.replace("\\", "/"))
        if leaf.endswith(self._BLOCKED_SUFFIXES) or leaf.startswith(self._BLOCKED_PREFIXES):
            raise HTTPException(status_code=404, detail="Not found")
        return await super().get_response(path, scope)


app.mount("/videos", SafeStaticFiles(directory=OUTPUT_DIR), name="videos")

# Mount static files for serving thumbnails
THUMBNAILS_DIR = os.path.join(OUTPUT_DIR, "thumbnails")
os.makedirs(THUMBNAILS_DIR, exist_ok=True)
app.mount("/thumbnails", StaticFiles(directory=THUMBNAILS_DIR), name="thumbnails")

# Mount static files for serving fonts (used by subtitle preview in frontend)
app.mount("/fonts", StaticFiles(directory="fonts"), name="fonts")

# Config-family routes (keys, cookies, fonts, logo, zernio) live in their own
# router — they touch none of the job runtime state, so keeping them out of
# app.py lets this module stay focused on the job lifecycle.
app.include_router(config_router)


@app.get("/")
async def root():
    return {"status": "online", "message": "ClippyMe API is running"}

@app.get("/api/health")
async def health():
    return {"status": "healthy"}

@app.post("/api/process")
async def process_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None)
):
    # CSRF/origin gate so a malicious page can't trigger compute jobs against
    # a locally-running backend. Same trust model as the config endpoints.
    require_trusted_config_request(request)
    # ~20 single-job submissions/min per client; compute-heavy, so throttle.
    enforce_rate_limit(request, "process", capacity=20, refill_per_sec=20 / 60)
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
    aspect = None
    language = None
    no_zoom = False
    skip_analysis = False
    model = None
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
        aspect = validated.aspect
        language = validated.language
        no_zoom = bool(validated.no_zoom)
        skip_analysis = bool(validated.skip_analysis)
        model = validated.model

    # For multipart/form-data uploads, extract reframe_mode + language from form fields
    if "multipart/form-data" in content_type:
        form = await request.form()
        reframe_mode = form.get("reframe_mode", reframe_mode)
        aspect = form.get("aspect", aspect)
        language = form.get("language", language)
        # Also honour the optional instructions field in multipart mode
        # so drag-and-drop uploads can pass AI directives just like URL
        # submissions (was previously ignored).
        instructions = form.get("instructions", instructions)
        no_zoom = str(form.get("no_zoom", "")).lower() in {"1", "true", "yes"} or no_zoom
        skip_analysis = str(form.get("skip_analysis", "")).lower() in {"1", "true", "yes"} or skip_analysis
        model = form.get("model", model) or None
        # Validate the multipart values through the same schema for
        # consistency — we drop the url requirement since we're using
        # an uploaded file path.
        try:
            ProcessRequest.model_validate({
                "url": "https://upload.invalid/local",
                "reframe_mode": reframe_mode or None,
                "aspect": aspect or None,
                "language": language or None,
                "instructions": instructions or None,
                "no_zoom": no_zoom,
                "skip_analysis": skip_analysis,
                "model": model or None,
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
        allowed_ext = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
        if raw_ext not in allowed_ext:
            # Reject unknown extensions explicitly instead of silently
            # treating them as .mp4 (which produced confusing downstream
            # ffmpeg failures on non-video uploads).
            shutil.rmtree(job_output_dir, ignore_errors=True)
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type. Allowed: .mp4, .mov, .mkv, .webm, .m4v, .avi",
            )
        input_path = os.path.join(UPLOAD_DIR, f"{job_id}{raw_ext}")
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
            aspect=aspect,
            cookies_path=os.path.join("data", "cookies.txt"),
            language=language,
            no_zoom=no_zoom,
            skip_analysis=skip_analysis,
            model=model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Enqueue Job (QueueFullError propagates → 429 via the ClippyMeError handler)
    await submit_job(
        jobs=jobs, job_queue=job_queue, job_id=job_id,
        cmd=cmd, env=env, job_output_dir=job_output_dir,
        on_change=persist_jobs,
    )

    return {"job_id": job_id, "status": "queued"}


@app.post("/api/batch")
async def batch_process(req: BatchRequest, request: Request):
    """Submit multiple URLs for batch processing. Each URL becomes a separate job."""
    require_trusted_config_request(request)
    # Each batch can enqueue up to 20 jobs, so limit batch calls more tightly.
    enforce_rate_limit(request, "batch", capacity=10, refill_per_sec=10 / 60)
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
                aspect=getattr(req, "aspect", None),
                cookies_path=os.path.join("data", "cookies.txt"),
                language=getattr(req, "language", None),
                no_zoom=bool(getattr(req, "no_zoom", False)),
                skip_analysis=bool(getattr(req, "skip_analysis", False)),
                model=getattr(req, "model", None),
            )
        except ValueError as exc:
            # This item's output dir was already created above but it never
            # made it into `jobs` — clean it up so a bad URL can't orphan a dir.
            await asyncio.to_thread(shutil.rmtree, job_output_dir, True)
            raise HTTPException(status_code=400, detail=str(exc))

        env = os.environ.copy()
        env["GEMINI_API_KEY"] = api_key

        try:
            await submit_job(
                jobs=jobs, job_queue=job_queue, job_id=job_id,
                cmd=cmd, env=env, job_output_dir=job_output_dir, batch=True,
                on_change=persist_jobs,
            )
            batch_jobs.append({"url": url, "job_id": job_id})
        except QueueFullError:
            # Only the item that failed to enqueue was cleaned up (by
            # submit_job) — already enqueued jobs stay running. Stop adding
            # more; the queue is full. Mirrors the single /api/process path.
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
        "logs": job.get('logs', [])[-500:],
        "result": job.get('result')
    }

@app.post("/api/cancel/{job_id}")
async def cancel_job(job_id: str, request: Request):
    """Cancel a running job by killing its subprocess."""
    require_trusted_config_request(request)
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    result = await cancel_job_action(job_id, jobs[job_id])
    persist_jobs()
    return result


@app.post("/api/pause/{job_id}")
async def pause_job(job_id: str, request: Request):
    """Suspend a running job's process tree (SIGSTOP/SuspendThread via psutil)."""
    require_trusted_config_request(request)
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    if not job_control.can_pause(job['status']):
        raise HTTPException(status_code=400, detail="Job cannot be paused")

    proc = job.get('process')
    if not (proc and proc.poll() is None):
        raise HTTPException(status_code=409, detail="Job has no running process")

    n = await asyncio.to_thread(job_control.suspend_tree, proc.pid)
    job['status'] = 'paused'
    job['logs'].append(f"Job paused by user ({n} process(es) suspended).")
    logger.info("Job %s paused (%d procs)", job_id, n)
    persist_jobs()
    return {"success": True, "status": "paused"}


@app.post("/api/resume/{job_id}")
async def resume_job(job_id: str, request: Request):
    """Resume a paused job's process tree."""
    require_trusted_config_request(request)
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    if not job_control.can_resume(job['status']):
        raise HTTPException(status_code=400, detail="Job is not paused")

    proc = job.get('process')
    if not (proc and proc.poll() is None):
        raise HTTPException(status_code=409, detail="Job has no running process")

    n = await asyncio.to_thread(job_control.resume_tree, proc.pid)
    job['status'] = 'processing'
    job['logs'].append(f"Job resumed by user ({n} process(es) resumed).")
    logger.info("Job %s resumed (%d procs)", job_id, n)
    persist_jobs()
    return {"success": True, "status": "processing"}


@app.post("/api/stop/{job_id}")
async def stop_job(job_id: str, request: Request):
    """Graceful stop: kill the subprocess but KEEP finished clips.

    Unlike ``/api/cancel`` (hard discard), this promotes the partial result to
    final so the user can still view/edit/publish the clips already rendered.
    """
    require_trusted_config_request(request)
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    result = await stop_job_action(job_id, jobs[job_id])
    persist_jobs()
    return result

@app.post("/api/smartcut/{job_id}/{clip_index}")
async def smart_cut_clip(job_id: str, clip_index: int, request: Request):
    """Generate a smart-cut version of a clip (silences + filler words removed)."""
    require_trusted_config_request(request)
    enforce_rate_limit(request, "smartcut", capacity=20, refill_per_sec=20 / 60)
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    resolved = await asyncio.to_thread(resolve_clip, job_id, clip_index, OUTPUT_DIR)
    # Optional manual-trim spans (flycut-style interactive cut). Legacy callers
    # POST no body — tolerate that and fall back to pure auto Smart Cut.
    drop_ranges = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            drop_ranges = body.get("drop_ranges")
    except Exception:
        pass
    # This raw-body path bypasses Pydantic, so apply the same bound check the
    # ComposeRequest/PublishRequest schemas use — rejects an oversized or
    # malformed list before the engine iterates it (DoS gate).
    try:
        _validate_drop_ranges(drop_ranges)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid drop_ranges: {exc}")
    return await run_smart_cut(
        job_id=job_id,
        clip_index=clip_index,
        resolved=resolved,
        drop_ranges=drop_ranges,
    )


@app.get("/api/transcript/{job_id}/{clip_index}")
async def clip_transcript(job_id: str, clip_index: int, request: Request):
    """Per-clip transcript segments (clip-relative seconds) for the manual-trim
    UI. Each segment is {index, text, start, end}; the frontend lets the user
    mark segments to drop and posts the resulting spans as `drop_ranges`."""
    require_trusted_config_request(request)
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    resolved = await asyncio.to_thread(
        resolve_clip, job_id, clip_index, OUTPUT_DIR, require_file=False)
    transcript = resolved.metadata.get("transcript") or {}
    clip = resolved.clip_info
    start, end = clip.get("start", 0), clip.get("end", 0)
    from clippyme.domain.smartcut import clip_transcript_segments
    segments = clip_transcript_segments(transcript, start, end)
    return {
        "segments": segments,
        "duration": round(max(0.0, end - start), 3),
        "language": transcript.get("language", "en"),
    }


@app.post("/api/edit-ai/{job_id}/{clip_index}")
async def edit_clip_ai(
    job_id: str,
    clip_index: int,
    req: EditAIRequest,
    request: Request,
    api_key: Optional[str] = Header(None, alias="X-Gemini-Key"),
):
    """Conversational clip trim: a plain-English instruction → Gemini → the
    clip-relative spans to remove. The returned `drop_ranges` feed the SAME
    manual-trim machinery as the tap-to-cut UI (compose / publish honour them)."""
    require_trusted_config_request(request)
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    resolved = await asyncio.to_thread(
        resolve_clip, job_id, clip_index, OUTPUT_DIR, require_file=False)
    clip = resolved.clip_info
    start, end = clip.get("start", 0), clip.get("end", 0)
    duration = round(max(0.0, end - start), 3)

    transcript = resolved.metadata.get("transcript") or {}
    from clippyme.domain.smartcut import clip_transcript_segments
    segments = clip_transcript_segments(transcript, start, end)

    cfg = load_persistent_config() or {}
    key = api_key or os.environ.get("GEMINI_API_KEY") or cfg.get("GEMINI_API_KEY")
    model = req.model or cfg.get("GEMINI_MODEL") or "gemini-3.5-flash"
    if not key:
        raise HTTPException(status_code=400, detail="Gemini API key not configured")

    from clippyme.domain.clip_edit_ai import suggest_drops
    result = await asyncio.to_thread(
        suggest_drops,
        api_key=key,
        model=model,
        segments=segments,
        instruction=req.instruction,
        clip_duration=duration,
    )
    return {"drop_ranges": result["drops"], "explanation": result["explanation"]}


@app.post("/api/reframe/{job_id}/{clip_index}")
async def reframe_clip(job_id: str, clip_index: int, req: ReframeRequest, request: Request):
    """Switch a clip between reframe modes (auto / subject / disabled) after generation.

    Requires the per-clip 16:9 source slice (``source_<clip>.mp4``) to still
    exist on disk. Spawns ``main.py --reframe-only`` as a subprocess to reuse
    the exact same reframing / zoom / normalize / cover pipeline the initial
    run used. Updates metadata.json and the in-memory job state so the
    dashboard picks up the new video URL on the next poll.
    """
    require_trusted_config_request(request)
    enforce_rate_limit(request, "reframe", capacity=20, refill_per_sec=20 / 60)
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job_id")
    mode = (req.reframe_mode or "auto").strip().lower()
    if mode not in ("auto", "disabled", "subject", "object"):
        raise HTTPException(status_code=400, detail="reframe_mode must be 'auto', 'subject', or 'disabled'")
    # 'object' is the legacy name for 'subject' — normalize so the subprocess
    # argv + metadata are written with the canonical value.
    mode = canonical_reframe_mode(mode)

    # Everything from metadata resolution through the subprocess run lives in
    # the domain helper (thin-handler rule); ClippyMeError subclasses raised
    # there are mapped to HTTP responses by the app-level exception handler.
    return await run_reframe(
        job_id=job_id, clip_index=clip_index, mode=mode,
        output_root=OUTPUT_DIR, jobs=jobs,
    )


@app.get("/api/history")
async def list_history(request: Request):
    """Scan output/ for past jobs with metadata files."""
    require_trusted_config_request(request)
    return {"jobs": await asyncio.to_thread(scan_history, OUTPUT_DIR)}

@app.delete("/api/history/{job_id}")
async def delete_history(job_id: str, request: Request):
    """Delete a job's output directory and all its files."""
    require_trusted_config_request(request)
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    if not os.path.isdir(job_dir):
        raise HTTPException(status_code=404, detail="Job not found on disk")
    await asyncio.to_thread(shutil.rmtree, job_dir, True)
    if job_id in jobs:
        del jobs[job_id]
        persist_jobs()
    logger.info("Deleted job %s and all files", job_id)
    return {"success": True}

@app.post("/api/compose/{job_id}/{clip_index}")
async def compose_clip(job_id: str, clip_index: int, req: ComposeRequest, request: Request):
    """Compose a final video from active toggle layers (Smart Cut → Hook → Subtitles)."""
    require_trusted_config_request(request)
    enforce_rate_limit(request, "compose", capacity=30, refill_per_sec=30 / 60)
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")

    resolved = await asyncio.to_thread(resolve_clip, job_id, clip_index, OUTPUT_DIR)

    try:
        composed_filename = await compose_layers(
            base_clip=resolved.clip_path,
            job_dir=resolved.job_dir,
            clip_index=clip_index,
            metadata=resolved.metadata,
            clip_info=resolved.clip_info,
            toggles=req.toggles,
            hook_params=req.hook_params,
            subtitle_params=req.subtitle_params,
            logo_params=req.logo_params,
            grade_params=req.grade_params,
            banner_params=req.banner_params,
            drop_ranges=req.drop_ranges,
        )
        return {"composed_url": f"/videos/{job_id}/{composed_filename}"}
    except (HTTPException, ClippyMeError):
        raise
    except Exception as e:
        logger.error("Compose error for job %s clip %d: %s", job_id, clip_index, e)
        raise HTTPException(status_code=500, detail="Compose pipeline failed")


# ---------------------------------------------------------------------------
# Publish (Zernio) endpoints
# ---------------------------------------------------------------------------

@app.post("/api/publish/{job_id}/{clip_index}")
async def publish_clip_endpoint(job_id: str, clip_index: int, req: PublishRequest, request: Request):
    """Upload a clip to Zernio and create a post on the requested platforms.

    If req.compose_first is True, the clip is freshly composed (Smart Cut →
    Hook → Subtitles) using req.toggles before upload — same flow as
    /api/compose. Otherwise we look for an existing composed_clip_{i}.mp4
    on disk and fall back to the base clip.
    """
    require_trusted_config_request(request)
    # Throttle uploads so a runaway "publish all" can't exhaust Zernio quota.
    enforce_rate_limit(request, "publish", capacity=30, refill_per_sec=30 / 60)
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")

    # require_file=False: the base clip may be absent when a composed file
    # exists on disk — publish_clip_flow resolves the actual upload path.
    resolved = await asyncio.to_thread(
        resolve_clip, job_id, clip_index, OUTPUT_DIR, require_file=False)

    return await publish_clip_flow(
        job_id=job_id, clip_index=clip_index, resolved=resolved,
        req=req.model_dump(), zernio_cfg=load_zernio_config(),
    )


# ---------------------------------------------------------------------------
# Content-monitor endpoints (multi-platform, multi-channel)
# ---------------------------------------------------------------------------

@app.post("/api/live-monitor/start")
async def live_monitor_start(req: LiveMonitorStartRequest, request: Request):
    """Start a monitor for one platform:channel. Returns that monitor's status
    (incl. its ``id``). Starting a duplicate (platform, channel) → 409."""
    require_trusted_config_request(request)
    enforce_rate_limit(request, "livemonitor", capacity=10, refill_per_sec=10 / 60)
    # start() raises ValidationError/ConflictError (ClippyMeError) → mapped to HTTP.
    return live_monitor.start(req.model_dump())


@app.post("/api/live-monitor/stop")
async def live_monitor_stop(request: Request):
    """Stop one monitor (body ``{"monitor_id": "..."}``) or ALL monitors (no
    body). Lets in-flight publishes drain first."""
    require_trusted_config_request(request)
    monitor_id = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            monitor_id = body.get("monitor_id")
    except Exception:
        pass  # no/invalid body → stop all
    return await live_monitor.stop(monitor_id)


@app.post("/api/live-monitor/{monitor_id}/config")
async def live_monitor_update_config(monitor_id: str, request: Request):
    """Patch selected settings on a running monitor (body: partial dict of
    updatable fields — see ``validate_monitor_partial_update``). Applies to
    FUTURE segments/publishes only, never retroactively."""
    require_trusted_config_request(request)
    enforce_rate_limit(request, "livemonitor", capacity=10, refill_per_sec=10 / 60)
    partial = await request.json()
    return {"monitor": live_monitor.update_config(monitor_id, partial)}


@app.post("/api/live-monitor/{monitor_id}/publishing")
async def live_monitor_set_publishing(monitor_id: str, request: Request):
    """Pause/resume auto-publishing for a running monitor (body:
    ``{"enabled": bool}``). While paused, finished clips accumulate and are
    drained through the normal publish path on resume."""
    require_trusted_config_request(request)
    enforce_rate_limit(request, "livemonitor", capacity=10, refill_per_sec=10 / 60)
    body = await request.json()
    enabled = bool(body.get("enabled")) if isinstance(body, dict) else False
    return {"monitor": live_monitor.set_publishing(monitor_id, enabled)}


@app.get("/api/live-monitor/status")
async def live_monitor_status(request: Request, monitor_id: Optional[str] = None):
    """One monitor's status (``?monitor_id=``) or ``{"monitors": [...]}`` for all."""
    require_trusted_config_request(request)
    return live_monitor.status(monitor_id)


@app.post("/api/history/{job_id}/restore")
async def restore_job(job_id: str, request: Request):
    """Restore a past job into the in-memory jobs dict so edit/hook/subtitle endpoints work."""
    require_trusted_config_request(request)
    if not is_valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    job_entry = restore_job_from_disk(job_id, OUTPUT_DIR, job_dir)
    jobs[job_id] = job_entry
    logger.info("Restored job %s into memory (%d clips)", job_id, len(job_entry["result"]["clips"]))
    return {"success": True, "status": "completed", "result": job_entry["result"]}
