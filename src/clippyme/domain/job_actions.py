"""Cancel / graceful-stop action bodies shared by the API handlers."""
import asyncio
import logging
import os
import shutil

from clippyme.domain import job_control
from clippyme.domain.errors import ConflictError, ValidationError
from clippyme.domain.job_results import load_partial_result

logger = logging.getLogger("clippyme")


async def _terminate_job_process(job_id: str, proc) -> None:
    """Stop the complete subprocess tree or raise without deleting output."""
    if proc is None or proc.poll() is not None:
        return
    try:
        await asyncio.to_thread(job_control.terminate_tree, proc.pid, 5.0)
        await asyncio.to_thread(lambda: proc.wait(timeout=5))
    except job_control.ProcessTreeTerminationError as exc:
        logger.error("process tree survived termination for job %s", job_id, exc_info=True)
        raise ConflictError(
            "Could not stop the complete process tree; output was left untouched"
        ) from exc
    except Exception as exc:
        logger.warning("tree termination failed for job %s: %s", job_id, exc, exc_info=True)
        try:
            proc.kill()
            await asyncio.to_thread(lambda: proc.wait(timeout=5))
        except Exception as fallback_exc:
            logger.error(
                "could not stop pipeline process for job %s: %s",
                job_id,
                fallback_exc,
                exc_info=True,
            )
            raise ConflictError("Could not stop the running process; output was left untouched") from fallback_exc
    if proc.poll() is None:
        raise ConflictError("Could not stop the running process; output was left untouched")


async def cancel_job_action(job_id: str, job: dict) -> dict:
    """Hard cancel: stop the process tree and delete all output."""
    if not job_control.can_cancel(job["status"]):
        raise ValidationError("Job is not running")

    proc = job.get("process")
    if proc is not None and proc.poll() is not None:
        raise ConflictError(
            "Job already finished processing; cancel refused to avoid discarding output"
        )

    previous_status = job["status"]
    # Publish the terminal intent before signalling the tree so the worker's
    # poll loop cannot race the kill and overwrite the transition as "failed".
    job["status"] = "cancelled"
    try:
        await _terminate_job_process(job_id, proc)
    except Exception:
        job["status"] = previous_status
        raise

    job["logs"].append("Job cancelled by user.")
    logger.info("Job %s cancelled by user", job_id)

    cleanup_error = None
    output_dir = job.get("output_dir", "")
    if output_dir and os.path.islink(output_dir):
        cleanup_error = RuntimeError("refusing to remove symbolic-link output directory")
        logger.error("job %s output directory is a symbolic link; cleanup refused", job_id)
    elif output_dir and os.path.isdir(output_dir):
        try:
            await asyncio.to_thread(shutil.rmtree, output_dir)
        except OSError as exc:
            cleanup_error = exc
            logger.error("job %s cancelled but output cleanup failed", job_id, exc_info=True)

    input_path = job.get("input_path")
    if input_path:
        try:
            await asyncio.to_thread(os.remove, input_path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("failed to remove cancelled upload %s", input_path, exc_info=True)

    if cleanup_error is not None:
        raise ConflictError(
            "Job was cancelled, but its output directory could not be removed"
        ) from cleanup_error
    return {"success": True, "status": "cancelled"}


async def stop_job_action(job_id: str, job: dict) -> dict:
    """Graceful stop: stop the process tree but keep finished clips."""
    if not job_control.can_stop(job["status"]):
        raise ValidationError("Job is not running")

    previous_status = job["status"]
    was_queued = previous_status == "queued"
    proc = job.get("process")
    if proc is not None and proc.poll() is not None:
        raise ConflictError(
            "Job already finished processing; stop refused while completion is being recorded"
        )
    job["status"] = "stopped"

    try:
        await _terminate_job_process(job_id, proc)
    except Exception:
        job["status"] = previous_status
        raise

    if proc is not None:
        output_dir = job.get("output_dir", "")
        partial = await asyncio.to_thread(load_partial_result, job_id, output_dir)
        if partial:
            job["result"] = partial

    n = len((job.get("result") or {}).get("clips", []) or [])
    msg = (
        "Job stopped before processing started."
        if was_queued
        else f"Job stopped by user; kept {n} finished clip(s)."
    )
    job["logs"].append(msg)
    logger.info("Job %s stopped by user (kept %d clips)", job_id, n)
    return {"success": True, "status": "stopped", "kept_clips": n}
