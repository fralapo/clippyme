"""Per-job subprocess runner bound to the shared in-memory job registry."""
import asyncio
import glob
import logging
import os
import subprocess
import threading

from clippyme.domain import job_control
from clippyme.domain.job_artifacts import relocate_root_job_artifacts
from clippyme.domain.job_results import load_final_result, load_partial_result
from clippyme.domain.job_worker import enqueue_output
from clippyme.storage.config_store import load_persistent_config

logger = logging.getLogger("clippyme")


def merge_persistent_config(env: dict, persisted: dict | None) -> dict:
    """Overlay non-empty persisted settings onto a job environment."""
    for key, value in (persisted or {}).items():
        if value in (None, ""):
            continue
        if key == "GEMINI_API_KEY" and env.get(key):
            continue
        env[str(key)] = str(value)
    return env


def make_run_job(*, jobs: dict, output_root: str, on_change=None):
    """Build the ``run_job`` coroutine bound to shared application state."""

    def _notify() -> None:
        if on_change is not None:
            try:
                on_change()
            except Exception:
                logger.warning("job-journal on_change hook failed", exc_info=True)

    async def _stop_process_tree(job_id: str, process) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            await asyncio.to_thread(job_control.terminate_tree, process.pid, 5.0)
            await asyncio.to_thread(lambda: process.wait(timeout=5))
            if process.poll() is None:
                raise RuntimeError("process tree still running after termination")
        except Exception:
            logger.warning("could not terminate process tree for job %s", job_id, exc_info=True)
            try:
                process.kill()
                await asyncio.to_thread(lambda: process.wait(timeout=5))
            except Exception:
                logger.error("could not kill orphaned process for job %s", job_id, exc_info=True)

    async def run_job(job_id, job_data):
        """Execute one pipeline subprocess and continuously expose partial results."""
        cmd = job_data["cmd"]
        env = job_data["env"]
        output_dir = job_data["output_dir"]
        process = None
        log_thread = None

        try:
            try:
                persisted = await asyncio.to_thread(load_persistent_config)
                merge_persistent_config(env, persisted)
            except Exception as exc:
                logger.warning(
                    "Could not merge persistent config into job env for %s: %s",
                    job_id,
                    exc,
                )

            if job_control.should_skip_dispatch(jobs[job_id].get("status", "")):
                logger.info(
                    "Skipping dispatch for already-terminated job %s (%s)",
                    job_id,
                    jobs[job_id].get("status"),
                )
                return

            jobs[job_id]["status"] = "processing"
            jobs[job_id]["logs"].append("Job started by worker.")
            jobs[job_id]["process"] = None
            logger.info("Executing job %s: %s", job_id, " ".join(cmd))
            _notify()

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=os.getcwd(),
            )
            jobs[job_id]["process"] = process
            jobs[job_id]["pid"] = process.pid
            jobs[job_id].pop("env", None)
            _notify()

            log_thread = threading.Thread(
                target=enqueue_output,
                args=(process.stdout, job_id, jobs),
                daemon=True,
                name=f"clippyme-log-{job_id}",
            )
            log_thread.start()

            while process.poll() is None:
                await asyncio.sleep(2)
                partial = await asyncio.to_thread(load_partial_result, job_id, output_dir)
                if partial:
                    jobs[job_id]["result"] = partial

            returncode = process.returncode
            status = jobs[job_id]["status"]
            if status == "cancelled":
                jobs[job_id]["logs"].append("Process terminated (cancelled).")
            elif status == "stopped":
                partial = await asyncio.to_thread(load_partial_result, job_id, output_dir)
                if partial:
                    jobs[job_id]["result"] = partial
                count = len((jobs[job_id].get("result") or {}).get("clips", []) or [])
                jobs[job_id]["logs"].append(
                    f"Process stopped by user; kept {count} finished clip(s)."
                )
            elif returncode == 0:
                jobs[job_id]["status"] = "completed"
                jobs[job_id]["logs"].append("Process finished successfully.")
                if not glob.glob(os.path.join(output_dir, "*_metadata.json")):
                    await asyncio.to_thread(
                        relocate_root_job_artifacts, job_id, output_dir, output_root
                    )
                final = await asyncio.to_thread(load_final_result, job_id, output_dir)
                if final:
                    jobs[job_id]["result"] = final
                else:
                    jobs[job_id]["status"] = "failed"
                    jobs[job_id]["logs"].append("No metadata file generated.")
            else:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["logs"].append(f"Process failed with exit code {returncode}")

        except asyncio.CancelledError:
            await _stop_process_tree(job_id, process)
            job = jobs.get(job_id)
            if job and job.get("status") not in job_control.TERMINAL_STATES:
                job["status"] = "failed"
                job["logs"].append("Job interrupted by server shutdown.")
            raise
        except Exception as exc:
            job = jobs.get(job_id)
            if job is not None:
                job["status"] = "failed"
                job["logs"].append(f"Execution error: {exc}")
            logger.exception("run_job failed for job_id=%s", job_id)
            await _stop_process_tree(job_id, process or (job or {}).get("process"))
        finally:
            if log_thread is not None and log_thread.is_alive():
                await asyncio.to_thread(log_thread.join, 5)
            _notify()

    return run_job
