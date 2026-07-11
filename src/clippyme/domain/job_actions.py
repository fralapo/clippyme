"""Cancel / graceful-stop action bodies (moved out of app.py handlers).

The handlers validate the job id + presence and delegate here; these functions
own the kill/rmtree/promote-partial mechanics and raise domain errors that the
app-level ``ClippyMeError`` handler maps to HTTP responses.
"""
import asyncio
import logging
import os
import shutil

from clippyme.domain import job_control
from clippyme.domain.errors import ConflictError, ValidationError
from clippyme.domain.job_results import load_partial_result

logger = logging.getLogger("clippyme")


async def cancel_job_action(job_id: str, job: dict) -> dict:
    """Hard cancel: kill the subprocess and DELETE all output."""
    if not job_control.can_cancel(job['status']):
        raise ValidationError("Job is not running")

    # If the subprocess has ALREADY exited, the job is completing right now —
    # run_job's 2s poll loop just hasn't observed the exit yet. Honouring the
    # cancel in that window would rmtree a fully-rendered job (silent,
    # unrecoverable data loss), so refuse and let the imminent
    # completed/failed status land instead. Queued jobs (no process handle)
    # remain cancellable via the pre-dispatch guard.
    proc = job.get('process')
    if proc is not None and proc.poll() is not None:
        raise ConflictError(
            "Job already finished processing; cancel refused to avoid discarding output")

    # A paused job's tree is suspended — resume it first so .kill() is delivered
    # and the OS can reap it (a stopped process can ignore signals on some OSes).
    if proc and proc.poll() is None:
        if job['status'] == 'paused':
            try:
                await asyncio.to_thread(job_control.resume_tree, proc.pid)
            except Exception:
                pass
        try:
            proc.kill()
            await asyncio.to_thread(lambda: proc.wait(timeout=5))
        except Exception:
            pass

    # Set status BEFORE rmtree so the run_job post-loop sees 'cancelled' and
    # skips the failed/completed branches.
    job['status'] = 'cancelled'
    job['logs'].append("Job cancelled by user.")
    logger.info("Job %s cancelled by user", job_id)

    # Cleanup output dir (discard all partial output).
    output_dir = job.get('output_dir', '')
    if output_dir and os.path.isdir(output_dir):
        await asyncio.to_thread(shutil.rmtree, output_dir, True)

    return {"success": True, "status": "cancelled"}


async def stop_job_action(job_id: str, job: dict) -> dict:
    """Graceful stop: kill the subprocess but KEEP finished clips."""
    if not job_control.can_stop(job['status']):
        raise ValidationError("Job is not running")

    # Set 'stopped' BEFORE killing so run_job's post-loop keeps the output
    # instead of marking the killed process as 'failed'.
    was_queued = job['status'] == 'queued'
    job['status'] = 'stopped'

    proc = job.get('process')
    if proc and proc.poll() is None:
        try:
            await asyncio.to_thread(job_control.resume_tree, proc.pid)  # ensure kill is delivered if paused
        except Exception:
            pass
        try:
            proc.kill()
            await asyncio.to_thread(lambda: proc.wait(timeout=5))
        except Exception:
            pass
        # Promote whatever finished to the final result immediately (the
        # post-loop will also do this, but do it here so the response is fresh).
        output_dir = job.get('output_dir', '')
        partial = await asyncio.to_thread(load_partial_result, job_id, output_dir)
        if partial:
            job['result'] = partial

    n = len((job.get('result') or {}).get('clips', []) or [])
    msg = "Job stopped before processing started." if was_queued else \
          f"Job stopped by user; kept {n} finished clip(s)."
    job['logs'].append(msg)
    logger.info("Job %s stopped by user (kept %d clips)", job_id, n)
    return {"success": True, "status": "stopped", "kept_clips": n}
