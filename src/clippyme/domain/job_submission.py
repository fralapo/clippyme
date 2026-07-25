"""Job-entry creation + enqueue, shared by /api/process and /api/batch.

Owns queue-full rollback and initializes the owner-only runtime state before the
job becomes visible to the worker. No environment values are persisted.
"""
import asyncio
import logging
import os
import shutil

from clippyme.domain.errors import ClippyMeError
from clippyme.domain.runtime_state import RuntimeState, runtime_result_fields

logger = logging.getLogger("clippyme")


class QueueFullError(ClippyMeError):
    """The job queue is at capacity (maps to 429)."""

    status_code = 429


def configured_max_attempts(env: dict[str, str] | None = None) -> int:
    """Return a bounded positive retry count despite malformed deployment env."""
    source = os.environ if env is None else env
    try:
        value = int(source.get("CLIPPYME_JOB_MAX_ATTEMPTS", "3") or 3)
    except (TypeError, ValueError):
        value = 3
    return max(1, min(value, 10))


async def submit_job(
    *,
    jobs: dict,
    job_queue: asyncio.Queue,
    job_id: str,
    cmd: list,
    env: dict,
    job_output_dir: str,
    batch: bool = False,
    on_change=None,
    cleanup_paths=(),
    input_path: str | None = None,
) -> None:
    """Register and enqueue a job, rolling every artefact back on queue-full."""
    max_attempts = configured_max_attempts()
    env["CLIPPYME_JOB_ID"] = job_id
    env["CLIPPYME_JOB_MAX_ATTEMPTS"] = str(max_attempts)

    runtime = RuntimeState(job_output_dir, job_id=job_id)
    runtime.data["max_attempts"] = max_attempts
    runtime.data["attempt"] = 0
    runtime.data["detail"] = "waiting for a worker"
    runtime.save()

    jobs[job_id] = {
        "status": "queued",
        "logs": [f"Job {job_id} queued (batch)." if batch else f"Job {job_id} queued."],
        "cmd": cmd,
        "env": env,
        "output_dir": job_output_dir,
        "input_path": input_path,
        "result": {"clips": [], **runtime_result_fields(job_output_dir)},
        "attempt": 0,
        "max_attempts": max_attempts,
    }
    try:
        job_queue.put_nowait(job_id)
    except asyncio.QueueFull:
        jobs.pop(job_id, None)
        await asyncio.to_thread(shutil.rmtree, job_output_dir, True)
        for path in cleanup_paths or ():
            if path:
                try:
                    await asyncio.to_thread(os.remove, path)
                except FileNotFoundError:
                    pass
                except OSError:
                    logger.warning(
                        "failed to remove rejected submission input %s",
                        path,
                        exc_info=True,
                    )
        raise QueueFullError("Server busy. Please try again later.")
    if on_change is not None:
        try:
            on_change()
        except Exception:
            logger.warning(
                "job-journal on_change hook failed for %s",
                job_id,
                exc_info=True,
            )
