"""
auto_editor_updater — runtime auto-update for the auto-editor binary.

Background:
- ClippyMe ships an `auto-editor` Nim binary baked into the Docker image.
- The upstream project (WyattBlue/auto-editor) ships frequent v30.x releases
  to GitHub. We want users to get those without rebuilding the image.

Strategy:
- On app startup (and once every 24h thereafter), call the GitHub API for the
  latest release tag, compare to the version reported by the local binary,
  and if newer download the appropriate arch asset to `/app/data/bin/auto-editor`.
- The Dockerfile prepends `/app/data/bin` to PATH so the freshly-downloaded
  binary shadows the build-time install at `/usr/local/bin/auto-editor`.
- Failures are non-fatal: if GitHub is unreachable, the network is down, or
  arch detection fails, the existing binary keeps working.

This module is designed to be safe to import even if `auto-editor` isn't
installed at all (smartcut.py has its own FFmpeg fallback).
"""

import asyncio
import contextlib
import errno
import fcntl
import json
import logging
import os
import platform
import shutil
import subprocess
import tempfile
import time
import urllib.request
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

GITHUB_LATEST_API = "https://api.github.com/repos/WyattBlue/auto-editor/releases/latest"
GITHUB_DOWNLOAD_BASE = "https://github.com/WyattBlue/auto-editor/releases/latest/download"

UPDATE_DIR = "/app/data/bin"
UPDATE_BINARY = os.path.join(UPDATE_DIR, "auto-editor")
VERSION_CACHE = os.path.join(UPDATE_DIR, ".version")

CHECK_INTERVAL_SECONDS = 24 * 3600  # daily
HTTP_TIMEOUT = 15


def _detect_asset_name() -> Optional[str]:
    """Map (system, machine) → GitHub release asset filename. None if unsupported."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        if machine in ("x86_64", "amd64"):
            return "auto-editor-linux-x86_64"
        if machine in ("aarch64", "arm64"):
            return "auto-editor-linux-aarch64"
    elif system == "darwin":
        if machine in ("x86_64", "amd64"):
            return "auto-editor-macos-x86_64"
        if machine in ("arm64", "aarch64"):
            return "auto-editor-macos-arm64"
    return None


def _read_local_version() -> Optional[str]:
    """Run `auto-editor --version` and return the version string, or None."""
    binary = shutil.which("auto-editor")
    if not binary:
        return None
    try:
        out = subprocess.check_output(
            [binary, "--version"],
            stderr=subprocess.STDOUT,
            timeout=10,
        ).decode().strip()
        # auto-editor outputs e.g. "30.1.0" or "auto-editor 30.1.0" depending on version
        return out.split()[-1] if out else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _fetch_latest_release_tag() -> Optional[str]:
    """Hit the GitHub API for the latest release tag. None on any failure."""
    try:
        req = urllib.request.Request(
            GITHUB_LATEST_API,
            headers={"User-Agent": "ClippyMe-AutoEditorUpdater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = json.load(resp)
        tag = data.get("tag_name")
        return tag.lstrip("v") if tag else None
    except Exception as e:
        logger.warning("auto-editor updater: GitHub API check failed: %s", e)
        return None


def _versions_equal(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    return a.strip().lstrip("v") == b.strip().lstrip("v")


# Upper bound on the downloaded binary — the real asset is ~30-50 MB; this
# stops a hijacked/compromised mirror from streaming an unbounded payload.
MAX_BINARY_BYTES = 200 * 1024 * 1024
# Executable magic numbers we accept (Linux ELF, macOS Mach-O variants).
_EXEC_MAGICS = (
    b"\x7fELF",
    b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",  # Mach-O 64/32 LE
    b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",  # Mach-O 64/32 BE
    b"\xca\xfe\xba\xbe",                        # Mach-O universal (fat)
)


def _download_binary(asset_name: str, target_path: str) -> bool:
    """Atomically download the binary to `target_path`. Returns True on success."""
    url = f"{GITHUB_DOWNLOAD_BASE}/{asset_name}"
    if not url.lower().startswith("https://"):
        logger.warning("auto-editor updater: refusing non-https download URL")
        return False
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix="ae-", dir=os.path.dirname(target_path))
    os.close(fd)
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ClippyMe-AutoEditorUpdater/1.0"}
        )
        total = 0
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT * 4) as resp:
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BINARY_BYTES:
                        raise RuntimeError("download exceeded size cap")
                    f.write(chunk)
        # Reject anything that isn't a native executable before we chmod +x it.
        with open(tmp_path, "rb") as f:
            head = f.read(4)
        if not any(head.startswith(m) for m in _EXEC_MAGICS):
            logger.warning("auto-editor updater: downloaded file is not an executable (magic=%r)", head)
            os.remove(tmp_path)
            return False
        os.chmod(tmp_path, 0o755)
        # Sanity check: must be executable and report a version
        try:
            check = subprocess.check_output(
                [tmp_path, "--version"], stderr=subprocess.STDOUT, timeout=10
            ).decode().strip()
            if not check:
                raise RuntimeError("empty --version output")
        except Exception as e:
            logger.warning("auto-editor updater: downloaded binary failed sanity check: %s", e)
            os.remove(tmp_path)
            return False

        os.replace(tmp_path, target_path)
        return True
    except Exception as e:
        logger.warning("auto-editor updater: download failed (%s): %s", url, e)
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False


@contextlib.contextmanager
def _update_lock() -> Iterator[bool]:
    """Best-effort exclusive lock so concurrent workers don't double-download.

    Yields True if the caller acquired the lock, False if another process
    already holds it (in which case the caller should skip the update).
    Lockfile is non-blocking; on any OS error we fall through and yield True
    so the updater still tries (failure-tolerant rather than deadlock-prone).
    """
    os.makedirs(UPDATE_DIR, exist_ok=True)
    lock_path = os.path.join(UPDATE_DIR, ".update.lock")
    fd = None
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                logger.debug("auto-editor updater: another worker holds the lock, skipping")
                yield False
                return
            raise
        yield True
    except OSError as e:
        logger.debug("auto-editor updater: lock acquisition fell through (%s)", e)
        yield True
    finally:
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass


def check_and_update_once() -> dict:
    """Synchronous one-shot update check. Safe to call from any context.

    Returns a dict with keys: action, current, latest, message.
    action ∈ {"updated", "up_to_date", "skipped", "unsupported", "no_local",
              "github_unreachable", "download_failed", "locked"}
    """
    asset = _detect_asset_name()
    if asset is None:
        return {"action": "unsupported", "current": None, "latest": None,
                "message": f"Unsupported platform {platform.system()}/{platform.machine()}"}

    current = _read_local_version()
    latest = _fetch_latest_release_tag()
    if latest is None:
        return {"action": "github_unreachable", "current": current, "latest": None,
                "message": "Could not reach GitHub releases API"}

    if current and _versions_equal(current, latest):
        return {"action": "up_to_date", "current": current, "latest": latest,
                "message": f"auto-editor {current} is current"}

    with _update_lock() as acquired:
        if not acquired:
            return {"action": "locked", "current": current, "latest": latest,
                    "message": "Another worker is already updating"}

        # Re-check version inside the lock — another worker may have updated
        # while we were blocked at the GitHub API call.
        current_after = _read_local_version()
        if current_after and _versions_equal(current_after, latest):
            return {"action": "up_to_date", "current": current_after, "latest": latest,
                    "message": f"auto-editor {current_after} is current (after lock)"}

        logger.info(
            "auto-editor updater: %s available (have %s) — downloading %s",
            latest, current_after or "none", asset,
        )
        ok = _download_binary(asset, UPDATE_BINARY)
        if not ok:
            return {"action": "download_failed", "current": current_after, "latest": latest,
                    "message": "Download or sanity check failed; keeping existing binary"}

        try:
            with open(VERSION_CACHE, "w") as f:
                f.write(f"{latest}\n{int(time.time())}\n")
        except OSError:
            pass

        return {"action": "updated", "current": current_after, "latest": latest,
                "message": f"auto-editor updated {current_after or 'none'} → {latest}"}


async def background_updater_loop():
    """Background asyncio task: runs check_and_update_once on startup, then
    every CHECK_INTERVAL_SECONDS. Designed to be launched from FastAPI lifespan.
    Cancellation-safe: catches CancelledError and exits cleanly.
    """
    while True:
        try:
            result = await asyncio.to_thread(check_and_update_once)
            logger.info("auto-editor updater: %s — %s", result["action"], result["message"])
        except asyncio.CancelledError:
            logger.info("auto-editor updater: background loop cancelled")
            return
        except Exception as e:
            logger.warning("auto-editor updater: unexpected error: %s", e)

        try:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            return
