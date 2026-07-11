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
from clippyme.domain.job_runner import make_run_job
from clippyme.domain.job_submission import QueueFullError, submit_job
from clippyme.domain.publish_service import publish_clip_flow
from clippyme.api.schemas import (
    BatchRequest,
    ComposeRequest,
    ConfigUpdateRequest,
    EditAIRequest,
    ProcessRequest,
    PublishRequest,
    ReframeRequest,
    ZernioConfigRequest,
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
    save_zernio_config,
    zernio_config_status,
)
from clippyme.domain.job_worker import make_workers
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
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "2048"))
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

# The per-job subprocess runner, bound to the shared jobs dict (thin-handler
# rule: the body lives in clippyme.domain.job_runner).
run_job = make_run_job(jobs=jobs, output_root=OUTPUT_DIR)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    return await asyncio.to_thread(list_available_models, api_key or os.environ.get("GEMINI_API_KEY"))

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

    return await cancel_job_action(job_id, jobs[job_id])


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

    return await stop_job_action(job_id, jobs[job_id])

@app.get("/api/config")
async def get_config(request: Request):
    """Return current active configuration (keys are partially masked for safety)."""
    require_trusted_config_request(request)
    config = load_persistent_config()
    # Secret keys are never returned verbatim — even short values are masked so
    # a brief key can't leak. Non-secret flags (model/provider) pass through.
    secret_keys = {"GEMINI_API_KEY", "HF_TOKEN", "DEEPGRAM_API_KEY", "ELEVENLABS_API_KEY", "YOUTUBE_COOKIES"}
    masked = {}
    for k, v in config.items():
        if k in secret_keys and v:
            masked[k] = f"{v[:4]}...{v[-4:]}" if len(v) > 8 else "********"
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


# --- Custom fonts (e.g. a licensed Stratos TTF the client needs) -----------
from clippyme.domain.subtitles import (
    list_available_fonts as _list_fonts,
    USER_FONTS_DIR as _USER_FONTS_DIR,
    _FONT_NAME_RE as _FONT_NAME_RE,
    _FONT_EXTS as _FONT_EXTS,
)

FONT_MAX_BYTES = 20 * 1024 * 1024  # 20 MB hard cap per face
# sfnt magic numbers: TrueType (0x00010000 / 'true'), OpenType ('OTTO'),
# TrueType collection ('ttcf'). Reject anything that isn't a real font file.
_FONT_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf")


@app.get("/api/config/fonts")
async def list_fonts(request: Request):
    """List every font face available for burn-in (bundled + user-uploaded)."""
    require_trusted_config_request(request)
    return {"fonts": _list_fonts()}


@app.post("/api/config/fonts")
async def upload_font(request: Request, font_file: UploadFile = File(...)):
    """Upload and persist a .ttf/.otf font so it appears in the subtitle font
    picker and resolves at burn time."""
    require_trusted_config_request(request)
    raw_name = os.path.basename(font_file.filename or "")
    stem, ext = os.path.splitext(raw_name)
    if ext.lower() not in _FONT_EXTS:
        raise HTTPException(status_code=400, detail="Font must be .ttf, .otf or .ttc")
    # The stem becomes the libass font name and is injected into an ASS style /
    # ffmpeg filter, so it must pass the same strict allow-list as font_name.
    if not _FONT_NAME_RE.match(stem):
        raise HTTPException(status_code=400, detail="Invalid font name (use letters, digits, space, _ or -)")

    chunks: list[bytes] = []
    total = 0
    while chunk := await font_file.read(64 * 1024):
        total += len(chunk)
        if total > FONT_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Font file too large (max 20 MB)")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content.startswith(_FONT_MAGIC):
        raise HTTPException(status_code=400, detail="File is not a valid TrueType/OpenType font")

    os.makedirs(_USER_FONTS_DIR, exist_ok=True)
    dest = os.path.join(_USER_FONTS_DIR, f"{stem}{ext.lower()}")
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return {"status": "ok", "name": stem, "fonts": _list_fonts()}


@app.delete("/api/config/fonts/{name}")
async def delete_font(name: str, request: Request):
    """Remove an uploaded font face by name. Bundled faces cannot be deleted."""
    require_trusted_config_request(request)
    if not _FONT_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid font name")
    removed = False
    for ext in _FONT_EXTS:
        p = os.path.join(_USER_FONTS_DIR, f"{name}{ext}")
        if os.path.exists(p):
            os.remove(p)
            removed = True
    if not removed:
        raise HTTPException(status_code=404, detail="Font not found")
    return {"status": "ok", "fonts": _list_fonts()}


# --- Brand logo / watermark overlay ----------------------------------------
LOGO_MAX_BYTES = 10 * 1024 * 1024  # 10 MB hard cap
_LOGO_PATH = os.path.join("data", "logo.png")
# PNG signature only — the overlay pipeline assumes RGBA PNG for clean alpha.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@app.get("/api/config/logo/status")
async def logo_status(request: Request):
    """Check whether a brand logo has been uploaded."""
    require_trusted_config_request(request)
    return {"configured": os.path.exists(_LOGO_PATH)}


@app.post("/api/config/logo")
async def upload_logo(request: Request, logo_file: UploadFile = File(...)):
    """Upload and persist a transparent PNG logo used by the compose logo layer."""
    require_trusted_config_request(request)
    chunks: list[bytes] = []
    total = 0
    while chunk := await logo_file.read(64 * 1024):
        total += len(chunk)
        if total > LOGO_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Logo file too large (max 10 MB)")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content.startswith(_PNG_MAGIC):
        raise HTTPException(status_code=400, detail="Logo must be a PNG (transparent recommended)")
    os.makedirs("data", exist_ok=True)
    fd = os.open(_LOGO_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return {"status": "ok", "message": "Logo saved"}


@app.delete("/api/config/logo")
async def delete_logo(request: Request):
    """Remove the persisted brand logo."""
    require_trusted_config_request(request)
    if os.path.exists(_LOGO_PATH):
        os.remove(_LOGO_PATH)
    return {"status": "ok", "message": "Logo removed"}


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
