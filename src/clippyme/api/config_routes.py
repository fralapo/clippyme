"""Config-family HTTP routes: keys, cookies, custom fonts, brand logo, Zernio.

Split out of ``app.py`` (which is meant to be a thin FastAPI layer) because
these handlers form one cohesive surface that touches **none** of the job
runtime state (``jobs`` dict, queue, semaphores) — only ``config_store``, the
subtitle font helpers, and their own upload validation. Keeping them here lets
``app.py`` stay focused on the job lifecycle.

Every route is trusted-origin gated via ``require_trusted_config_request`` and
does its own magic-byte / size / name-allow-list validation on uploads. The
bodies are unchanged from their previous inline form in ``app.py``.
"""
import asyncio
import os
from typing import Optional

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile

from clippyme.api.schemas import ConfigUpdateRequest, ZernioConfigRequest
from clippyme.api.security import require_trusted_config_request
from clippyme.pipeline.gemini_service import list_available_models
from clippyme.storage.config_store import (
    load_persistent_config,
    load_zernio_config,
    save_persistent_config,
    save_zernio_config,
    zernio_config_status,
)

# Custom fonts (e.g. a licensed Stratos TTF the client needs).
from clippyme.domain.subtitles import (
    list_available_fonts as _list_fonts,
    USER_FONTS_DIR as _USER_FONTS_DIR,
    _FONT_NAME_RE as _FONT_NAME_RE,
    _FONT_EXTS as _FONT_EXTS,
)

router = APIRouter()


@router.get("/api/config/models")
async def list_gemini_models(
    request: Request,
    api_key: Optional[str] = Header(None, alias="X-Gemini-Key"),
):
    """List available Gemini models using the provided API key."""
    require_trusted_config_request(request)
    return await asyncio.to_thread(list_available_models, api_key or os.environ.get("GEMINI_API_KEY"))


@router.get("/api/config")
async def get_config(request: Request):
    """Return current active configuration (keys are partially masked for safety)."""
    require_trusted_config_request(request)
    config = load_persistent_config()
    # Secret keys are never returned verbatim — even short values are masked so
    # a brief key can't leak. Non-secret flags (model/provider) pass through.
    secret_keys = {"GEMINI_API_KEY", "HF_TOKEN", "DEEPGRAM_API_KEY", "ELEVENLABS_API_KEY",
                   "YOUTUBE_COOKIES", "TWITCH_CLIENT_SECRET"}
    masked = {}
    for k, v in config.items():
        if k in secret_keys and v:
            masked[k] = f"{v[:4]}...{v[-4:]}" if len(v) > 8 else "********"
        else:
            masked[k] = v
    return masked


@router.post("/api/config")
async def update_config(req: ConfigUpdateRequest, request: Request):
    """Update and persist API keys."""
    require_trusted_config_request(request)
    if save_persistent_config(req.keys):
        return {"success": True, "message": "Configuration updated and persisted."}
    else:
        raise HTTPException(status_code=500, detail="Failed to save configuration.")


COOKIES_MAX_BYTES = 10 * 1024 * 1024  # 10 MB hard cap


@router.post("/api/config/cookies")
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


@router.get("/api/config/cookies/status")
async def cookies_status(request: Request):
    """Check if a cookies file is configured."""
    require_trusted_config_request(request)
    cookies_path = os.path.join("data", "cookies.txt")
    return {"configured": os.path.exists(cookies_path)}


@router.delete("/api/config/cookies")
async def delete_cookies(request: Request):
    """Remove the persisted cookies file."""
    require_trusted_config_request(request)
    cookies_path = os.path.join("data", "cookies.txt")
    if os.path.exists(cookies_path):
        os.remove(cookies_path)
    return {"status": "ok", "message": "Cookies removed"}


FONT_MAX_BYTES = 20 * 1024 * 1024  # 20 MB hard cap per face
# sfnt magic numbers: TrueType (0x00010000 / 'true'), OpenType ('OTTO'),
# TrueType collection ('ttcf'). Reject anything that isn't a real font file.
_FONT_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf")


@router.get("/api/config/fonts")
async def list_fonts(request: Request):
    """List every font face available for burn-in (bundled + user-uploaded)."""
    require_trusted_config_request(request)
    return {"fonts": _list_fonts()}


@router.post("/api/config/fonts")
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


@router.delete("/api/config/fonts/{name}")
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


@router.get("/api/config/logo/status")
async def logo_status(request: Request):
    """Check whether a brand logo has been uploaded."""
    require_trusted_config_request(request)
    return {"configured": os.path.exists(_LOGO_PATH)}


@router.post("/api/config/logo")
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


@router.delete("/api/config/logo")
async def delete_logo(request: Request):
    """Remove the persisted brand logo."""
    require_trusted_config_request(request)
    if os.path.exists(_LOGO_PATH):
        os.remove(_LOGO_PATH)
    return {"status": "ok", "message": "Logo removed"}


@router.get("/api/config/zernio")
async def get_zernio_config(request: Request):
    """Return persisted Zernio settings (api_key masked)."""
    require_trusted_config_request(request)
    return zernio_config_status()


@router.post("/api/config/zernio")
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


@router.get("/api/zernio/accounts")
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
