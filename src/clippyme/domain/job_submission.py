"""Job-entry creation + enqueue, shared by /api/process and /api/batch.

Owns the queue-full rollback (pop the entry, rmtree the just-created output
dir) so a rejected submission can never orphan a directory. The API handlers
build ``cmd``/``env`` and call :func:`submit_job`.
"""
import asyncio
import json
import logging
import os
import shutil

from clippyme.domain.errors import ClippyMeError

logger = logging.getLogger("clippyme")

PUBLISHER_MODE_FILENAME = "publisher_mode.json"
_PUBLISHER_MODES = {"manual_queue", "zernio"}


class QueueFullError(ClippyMeError):
    """The job queue is at capacity (maps to 429)."""

    status_code = 429


def write_publisher_mode(job_output_dir: str, publisher_mode: str,
                         owner: str | None = None) -> None:
    """Persist the job's publish-destination choice as a sidecar (atomic write).

    Read back at completion time by ``job_runner`` (to decide whether to
    enqueue the finished clips into the manual publish queue) and by
    ``import_existing_clips`` (to skip jobs the user opted into Zernio-only
    publishing for). ``owner`` marks who is responsible for enqueueing the
    finished clips: the live monitor writes ``owner="live_monitor"`` so the
    job-completion hook defers to the monitor's composed enqueue (the startup
    importer still backstops a crash). Best-effort: a write failure is logged,
    never raised — the job submission itself must not fail over this.
    """
    mode = publisher_mode if publisher_mode in _PUBLISHER_MODES else "manual_queue"
    payload = {"publisher_mode": mode}
    if owner:
        payload["owner"] = str(owner)
    path = os.path.join(job_output_dir, PUBLISHER_MODE_FILENAME)
    tmp_path = path + ".tmp"
    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp_path, path)
    except OSError:
        logger.warning("Could not write publisher_mode sidecar for %s", job_output_dir, exc_info=True)
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def read_publisher_mode(job_output_dir: str) -> str:
    """Read the publisher_mode sidecar. Missing/corrupt → 'manual_queue'
    (legacy jobs predate this feature and default to the manual queue)."""
    path = os.path.join(job_output_dir, PUBLISHER_MODE_FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        mode = data.get("publisher_mode")
        return mode if mode in _PUBLISHER_MODES else "manual_queue"
    except (OSError, ValueError, AttributeError):
        return "manual_queue"


def read_publisher_owner(job_output_dir: str) -> str | None:
    """Read the sidecar's ``owner`` field. Missing/corrupt → None (no owner:
    the job-completion hook is free to enqueue)."""
    path = os.path.join(job_output_dir, PUBLISHER_MODE_FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        owner = data.get("owner")
        return owner if isinstance(owner, str) and owner else None
    except (OSError, ValueError, AttributeError):
        return None


async def submit_job(*, jobs: dict, job_queue: asyncio.Queue, job_id: str,
                     cmd: list, env: dict, job_output_dir: str,
                     batch: bool = False, on_change=None,
                     publisher_mode: str = "manual_queue",
                     publisher_owner: str | None = None) -> None:
    """Register a queued job entry and enqueue it.

    On ``asyncio.QueueFull`` the entry is rolled back (removed from ``jobs``,
    output dir deleted) and ``QueueFullError`` is raised — the single-job
    handler lets it propagate as a 429; the batch handler catches it to stop
    adding further items while keeping the already-enqueued ones.
    """
    jobs[job_id] = {
        'status': 'queued',
        'logs': [f"Job {job_id} queued (batch)." if batch else f"Job {job_id} queued."],
        'cmd': cmd,
        'env': env,
        'output_dir': job_output_dir,
    }
    write_publisher_mode(job_output_dir, publisher_mode, owner=publisher_owner)
    try:
        job_queue.put_nowait(job_id)
    except asyncio.QueueFull:
        jobs.pop(job_id, None)
        await asyncio.to_thread(shutil.rmtree, job_output_dir, True)
        raise QueueFullError("Server busy. Please try again later.")
    if on_change is not None:
        try:
            on_change()
        except Exception:
            logger.warning("job-journal on_change hook failed for %s", job_id, exc_info=True)
