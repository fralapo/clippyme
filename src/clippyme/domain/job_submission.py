"""Job-entry creation + enqueue, shared by /api/process and /api/batch.

Owns the queue-full rollback (pop the entry, rmtree the just-created output
dir) so a rejected submission can never orphan a directory. The API handlers
build ``cmd``/``env`` and call :func:`submit_job`.
"""
import asyncio
import logging
import shutil

from clippyme.domain.errors import ClippyMeError

logger = logging.getLogger("clippyme")


class QueueFullError(ClippyMeError):
    """The job queue is at capacity (maps to 429)."""

    status_code = 429


async def submit_job(*, jobs: dict, job_queue: asyncio.Queue, job_id: str,
                     cmd: list, env: dict, job_output_dir: str,
                     batch: bool = False, on_change=None) -> None:
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
