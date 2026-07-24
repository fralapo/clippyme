"""Per-job subprocess runner with bounded checkpoint retries and telemetry."""
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
from clippyme.domain.runtime_state import (
    collect_runtime_metrics,
    estimate_eta,
    format_runtime_log,
    load_runtime_state,
    runtime_result_fields,
    upsert_runtime_log,
)
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


def _merge_runtime_result(job: dict, output_dir: str, metrics: dict | None = None) -> None:
    """Expose runtime state even before the first clip metadata file exists."""
    fields = runtime_result_fields(output_dir)
    if not fields:
        return
    result = job.get("result") if isinstance(job.get("result"), dict) else {"clips": []}
    result.setdefault("clips", [])
    result.update(fields)
    operations = result.get("operations")
    if isinstance(operations, dict):
        operations["metrics"] = dict(metrics or {})
        operations["eta_seconds"] = estimate_eta(operations)
    job["result"] = result


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

    async def _refresh(job_id: str, output_dir: str, process) -> None:
        job = jobs.get(job_id)
        if job is None:
            return
        partial = await asyncio.to_thread(load_partial_result, job_id, output_dir)
        if partial:
            job["result"] = partial
        state = await asyncio.to_thread(load_runtime_state, output_dir)
        metrics = await asyncio.to_thread(
            collect_runtime_metrics,
            process.pid if process and process.poll() is None else None,
            output_dir,
        )
        _merge_runtime_result(job, output_dir, metrics)
        if state:
            upsert_runtime_log(job["logs"], format_runtime_log(state, metrics))

    async def run_job(job_id, job_data):
        """Execute a checkpointed subprocess, retrying transient failures."""
        cmd = list(job_data["cmd"])
        env = dict(job_data["env"])
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

            try:
                max_attempts = max(1, int(
                    job_data.get("max_attempts")
                    or env.get("CLIPPYME_JOB_MAX_ATTEMPTS")
                    or os.environ.get("CLIPPYME_JOB_MAX_ATTEMPTS", "3")
                ))
            except (TypeError, ValueError):
                max_attempts = 3

            jobs[job_id]["status"] = "processing"
            jobs[job_id]["max_attempts"] = max_attempts
            jobs[job_id]["logs"].append("Job started by worker.")
            jobs[job_id]["process"] = None
            _notify()

            for attempt in range(1, max_attempts + 1):
                status = jobs[job_id].get("status")
                if job_control.should_skip_dispatch(status):
                    break

                jobs[job_id]["attempt"] = attempt
                child_env = dict(env)
                child_env["CLIPPYME_JOB_ID"] = job_id
                child_env["CLIPPYME_ATTEMPT"] = str(attempt)
                child_env["CLIPPYME_JOB_MAX_ATTEMPTS"] = str(max_attempts)
                jobs[job_id]["logs"].append(
                    f"Pipeline attempt {attempt}/{max_attempts} started."
                )
                logger.info("Executing job %s attempt %d/%d: %s", job_id, attempt, max_attempts, " ".join(cmd))
                _notify()

                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=child_env,
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
                    name=f"clippyme-log-{job_id}-{attempt}",
                )
                log_thread.start()

                while process.poll() is None:
                    await asyncio.sleep(2)
                    await _refresh(job_id, output_dir, process)

                if log_thread.is_alive():
                    await asyncio.to_thread(log_thread.join, 5)
                await _refresh(job_id, output_dir, process)

                returncode = process.returncode
                status = jobs[job_id]["status"]
                if status == "cancelled":
                    jobs[job_id]["logs"].append("Process terminated (cancelled).")
                    break
                if status == "stopped":
                    partial = await asyncio.to_thread(load_partial_result, job_id, output_dir)
                    if partial:
                        jobs[job_id]["result"] = partial
                    count = len((jobs[job_id].get("result") or {}).get("clips", []) or [])
                    jobs[job_id]["logs"].append(
                        f"Process stopped by user; kept {count} finished clip(s)."
                    )
                    break
                if returncode == 0:
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
                    break

                # The orchestrator reserves exit 2 for deterministic validation or
                # preflight rejection. Retrying cannot change those inputs.
                retryable = returncode != 2 and attempt < max_attempts
                if retryable:
                    delay = min(30, 2 ** (attempt - 1))
                    jobs[job_id]["logs"].append(
                        f"Attempt {attempt} failed with exit code {returncode}; "
                        f"resuming from checkpoints in {delay}s."
                    )
                    jobs[job_id]["process"] = None
                    jobs[job_id].pop("pid", None)
                    _notify()
                    await asyncio.sleep(delay)
                    continue

                jobs[job_id]["status"] = "failed"
                reason = "non-retryable input/preflight error" if returncode == 2 else "retry limit reached"
                jobs[job_id]["logs"].append(
                    f"Process failed with exit code {returncode} ({reason})."
                )
                break

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
            job = jobs.get(job_id)
            if job is not None:
                job["process"] = None
                job.pop("pid", None)
                _merge_runtime_result(job, output_dir)
            _notify()

    return run_job
