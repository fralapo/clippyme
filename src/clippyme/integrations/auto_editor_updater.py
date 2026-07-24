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
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from typing import Iterator, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

GITHUB_LATEST_API = "https://api.github.com/repos/WyattBlue/auto-editor/releases/latest"
GITHUB_DOWNLOAD_BASE = "https://github.com/WyattBlue/auto-editor/releases/latest/download"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects on the GitHub *API* JSON fetch.

    api.github.com does not legitimately 3xx this endpoint, so a redirect would
    only ever come from a MITM/hijack trying to bounce the request to an
    internal address (SSRF). The asset *download* still follows redirects (it
    must, to reach the objects.githubusercontent.com CDN) but is integrity-
    checked against the release's published SHA256 digest instead.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_API_OPENER = urllib.request.build_opener(_NoRedirectHandler)

UPDATE_DIR = "/app/data/bin"
UPDATE_BINARY = os.path.join(UPDATE_DIR, "auto-editor")
VERSION_CACHE = os.path.join(UPDATE_DIR, ".version")

CHECK_INTERVAL_SECONDS = 24 * 3600  # daily
HTTP_TIMEOUT = 15
MAX_RELEASE_JSON_BYTES = 2 * 1024 * 1024


def auto_update_enabled() -> bool:
    """Whether the runtime auto-updater is allowed to fetch + exec a new binary.

    OFF by default. The Dockerfile already installs a pinned, SHA256-verified
    binary at build time. The optional runtime updater also requires the SHA256
    digest published in GitHub release metadata, restricts download/redirect
    hosts, validates executable magic and runs a bounded ``--version`` check.
    It remains opt-in because executing newly published native code changes the
    deployment's reviewed supply-chain state without rebuilding the image.
    """
    return os.environ.get("AUTO_EDITOR_AUTO_UPDATE", "0") == "1"


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


def _fetch_latest_release() -> Optional[dict]:
    """Hit the GitHub API for the latest release. None on any failure.

    Returns ``{"tag": "30.5.0", "assets": {name: {"url": ..., "digest":
    "sha256:..."|None}}}``. The per-asset ``digest`` (published by GitHub for
    recent releases) is what lets us verify the binary's integrity after
    download, so a compromised CDN/mirror can't substitute a malicious payload.
    Uses the no-redirect opener so the JSON fetch can't be bounced internally.
    """
    try:
        req = urllib.request.Request(
            GITHUB_LATEST_API,
            headers={"User-Agent": "ClippyMe-AutoEditorUpdater/1.0"},
        )
        with _API_OPENER.open(req, timeout=HTTP_TIMEOUT) as resp:  # nosec B310: fixed official API URL, redirects disabled
            raw = resp.read(MAX_RELEASE_JSON_BYTES + 1)
        if len(raw) > MAX_RELEASE_JSON_BYTES:
            raise ValueError("GitHub release response exceeded size cap")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("GitHub release response was not an object")
    except Exception as e:
        logger.warning("auto-editor updater: GitHub API check failed: %s", e)
        return None
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not re.fullmatch(r"v?[0-9A-Za-z][0-9A-Za-z.+-]{0,63}", tag):
        return None
    asset_list = data.get("assets") or []
    if not isinstance(asset_list, list):
        return None
    assets: dict[str, dict] = {}
    for asset in asset_list:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        if not isinstance(name, str) or not name:
            continue
        url = asset.get("browser_download_url")
        digest = asset.get("digest")
        assets[name] = {
            "url": url if isinstance(url, str) else None,
            "digest": digest if isinstance(digest, str) else None,
        }
    return {"tag": tag.lstrip("v"), "assets": assets}


def _fetch_latest_release_tag() -> Optional[str]:
    """Thin wrapper: latest release tag only (back-compat)."""
    rel = _fetch_latest_release()
    return rel["tag"] if rel else None


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


def _verify_digest(path: str, expected_digest: Optional[str]) -> Optional[bool]:
    """Compare the SHA256 of ``path`` to a GitHub ``sha256:<hex>`` digest.

    Returns True if it matches, False on mismatch, and None when no digest was
    published (older releases) so the caller can decide policy. Pure-ish: only
    reads the file.
    """
    if not expected_digest:
        return None
    algo, _, want = expected_digest.partition(":")
    want = want.strip().lower()
    if algo.lower() != "sha256" or not re.fullmatch(r"[0-9a-f]{64}", want):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower() == want


_ALLOWED_DOWNLOAD_HOSTS = frozenset({
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})


def _allowed_download_url(url: str) -> bool:
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in _ALLOWED_DOWNLOAD_HOSTS


class _SafeAssetRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed_download_url(newurl):
            raise RuntimeError("auto-editor asset redirected to an untrusted host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_ASSET_OPENER = urllib.request.build_opener(_SafeAssetRedirectHandler)


def _download_binary(url: str, target_path: str, expected_digest: Optional[str] = None) -> bool:
    """Atomically download the binary from ``url`` to ``target_path``.

    Verifies the SHA256 against ``expected_digest`` (from the release metadata)
    before the binary is ever made executable. Missing, malformed, or mismatched
    digests abort the update; the updater never executes an unverified asset.
    Returns True on success.
    """
    if not _allowed_download_url(url):
        logger.warning("auto-editor updater: refusing untrusted download URL: %r", url)
        return False
    if not expected_digest:
        logger.error("auto-editor updater: release asset has no SHA256 digest; refusing update")
        return False
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix="ae-", dir=os.path.dirname(target_path))
    os.close(fd)
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ClippyMe-AutoEditorUpdater/1.0"}
        )
        total = 0
        with _ASSET_OPENER.open(req, timeout=HTTP_TIMEOUT * 4) as resp:  # nosec B310: HTTPS host and redirects are allowlisted
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BINARY_BYTES:
                        raise RuntimeError("download exceeded size cap")
                    f.write(chunk)
                f.flush()
                os.fsync(f.fileno())
        # Integrity gate: a published digest MUST match before we trust the file.
        verdict = _verify_digest(tmp_path, expected_digest)
        if verdict is not True:
            logger.error(
                "auto-editor updater: missing/invalid SHA256 or digest mismatch — rejecting asset"
            )
            os.remove(tmp_path)
            return False
        # Reject anything that isn't a native executable before we chmod +x it.
        with open(tmp_path, "rb") as f:
            head = f.read(4)
        if not any(head.startswith(m) for m in _EXEC_MAGICS):
            logger.warning("auto-editor updater: downloaded file is not an executable (magic=%r)", head)
            os.remove(tmp_path)
            return False
        os.chmod(tmp_path, 0o700)
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
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
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
        logger.warning("auto-editor updater: lock acquisition failed; skipping update (%s)", e)
        yield False
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
              "github_unreachable", "download_failed", "locked", "disabled"}
    """
    if not auto_update_enabled():
        return {"action": "disabled", "current": _read_local_version(), "latest": None,
                "message": "Runtime auto-update disabled (set AUTO_EDITOR_AUTO_UPDATE=1 to enable)"}

    asset = _detect_asset_name()
    if asset is None:
        return {"action": "unsupported", "current": None, "latest": None,
                "message": f"Unsupported platform {platform.system()}/{platform.machine()}"}

    current = _read_local_version()
    release = _fetch_latest_release()
    if release is None:
        return {"action": "github_unreachable", "current": current, "latest": None,
                "message": "Could not reach GitHub releases API"}
    latest = release["tag"]
    asset_meta = (release.get("assets") or {}).get(asset) or {}
    download_url = asset_meta.get("url")
    expected_digest = asset_meta.get("digest")

    if current and _versions_equal(current, latest):
        return {"action": "up_to_date", "current": current, "latest": latest,
                "message": f"auto-editor {current} is current"}
    if not download_url or not expected_digest:
        return {
            "action": "download_failed",
            "current": current,
            "latest": latest,
            "message": "Release asset is missing a trusted URL or SHA256 digest",
        }

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
        ok = _download_binary(download_url, UPDATE_BINARY, expected_digest)
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
    if not auto_update_enabled():
        logger.info(
            "auto-editor updater: runtime auto-update disabled "
            "(AUTO_EDITOR_AUTO_UPDATE != 1); using the pinned build-time binary"
        )
        return
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
