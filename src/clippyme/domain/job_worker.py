"""Background job queue worker and cleanup loop.

Uses a closure factory so shared state (``jobs``, queues, semaphores)
stays owned by ``app.py`` — avoiding circular imports and
module-level globals.
"""
import asyncio
import logging
import os
import shutil
import time
from typing import Awaitable, Callable, Dict

logger = logging.getLogger("clippyme")


def enqueue_output(out, job_id: str, jobs: Dict[str, Dict]) -> None:
    """Read lines from a subprocess stream and append them to the job's log list.

    Intended to run inside a background thread.
    """
    try:
        for line in iter(out.readline, b""):
            decoded_line = line.decode("utf-8").strip()
            if decoded_line:
                print(f"📝 [Job Output] {decoded_line}")
                if job_id in jobs:
                    jobs[job_id]["logs"].append(decoded_line)
    except Exception as e:
        logger.error("Error reading output for job %s: %s", job_id, e)
    finally:
        out.close()


def make_workers(
    *,
    jobs: Dict[str, Dict],
    job_queue: asyncio.Queue,
    concurrency_semaphore: asyncio.Semaphore,
    run_job: Callable[[str, Dict], Awaitable[None]],
    output_dir: str,
    upload_dir: str,
    data_dir: str,
    job_retention_seconds: int,
    max_concurrent_jobs: int,
):
    """Build the ``cleanup_jobs``, ``process_queue`` and ``run_job_wrapper``
    coroutines bound to the provided shared state.

    Returns a tuple ``(cleanup_jobs, process_queue, run_job_wrapper)``.
    """

    async def cleanup_jobs() -> None:
        """Background task to remove old jobs, uploads, and cache entries."""
        logger.info("Cleanup task started")
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                now = time.time()

                # Retention <= 0 disables auto-purge entirely — the user
                # is expected to delete clips explicitly from the
                # History tab. Skip both OUTPUT_DIR and UPLOAD_DIR
                # sweeps in that case so a stale mtime can't trigger
                # a bulk delete behind the user's back.
                if job_retention_seconds > 0:
                    from clippyme.domain.history_service import is_valid_job_id
                    # OUTPUT_DIR: purge stale job folders. Only ever delete
                    # directories whose name is a valid job id — never a
                    # symlink, the thumbnails dir, or a hand-placed folder.
                    for job_id in os.listdir(output_dir):
                        job_path = os.path.join(output_dir, job_id)
                        if not is_valid_job_id(job_id):
                            continue
                        if os.path.isdir(job_path) and not os.path.islink(job_path):
                            if now - os.path.getmtime(job_path) > job_retention_seconds:
                                logger.info("Purging old job: %s", job_id)
                                shutil.rmtree(job_path, ignore_errors=True)
                                jobs.pop(job_id, None)

                    # UPLOAD_DIR: purge stale uploads
                    for filename in os.listdir(upload_dir):
                        file_path = os.path.join(upload_dir, filename)
                        try:
                            if now - os.path.getmtime(file_path) > job_retention_seconds:
                                os.remove(file_path)
                        except Exception:
                            pass

                # Transcript cache (older than 7 days)
                cache_dir = os.path.join(data_dir, "cache")
                if os.path.isdir(cache_dir):
                    for filename in os.listdir(cache_dir):
                        cache_path = os.path.join(cache_dir, filename)
                        try:
                            if now - os.path.getmtime(cache_path) > 7 * 86400:
                                os.remove(cache_path)
                        except Exception:
                            pass

            except Exception as e:
                logger.warning("Cleanup error: %s", e)

    async def run_job_wrapper(job_id: str) -> None:
        """Run a single job and always release the concurrency slot."""
        try:
            job = jobs.get(job_id)
            if job:
                await run_job(job_id, job)
        except Exception as e:
            logger.error("Job wrapper error %s: %s", job_id, e)
        finally:
            concurrency_semaphore.release()
            job_queue.task_done()
            logger.info("Released slot for job: %s", job_id)

    async def process_queue() -> None:
        """Dispatch loop: pull jobs from the queue, respect concurrency limit."""
        logger.info("Job queue worker started with %d concurrent slots", max_concurrent_jobs)
        while True:
            try:
                job_id = await job_queue.get()
                await concurrency_semaphore.acquire()
                logger.info("Acquired slot for job: %s", job_id)
                asyncio.create_task(run_job_wrapper(job_id))
            except Exception as e:
                logger.error("Queue dispatch error: %s", e)
                await asyncio.sleep(1)

    return cleanup_jobs, process_queue, run_job_wrapper
