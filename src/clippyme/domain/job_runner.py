"""The per-job subprocess runner (moved out of app.py — thin-handler rule).

``make_run_job`` follows the same closure-factory pattern as
``job_worker.make_workers``: shared state (the ``jobs`` dict, output root,
journal hook) stays owned by app.py and is bound once at startup.
"""
import asyncio
import glob
import logging
import os
import subprocess
import threading

from clippyme.domain import job_control
from clippyme.domain.job_artifacts import relocate_root_job_artifacts
from clippyme.domain.job_results import load_final_result, load_partial_result
from clippyme.domain.job_submission import read_publisher_mode, read_publisher_owner
from clippyme.domain.job_worker import enqueue_output
from clippyme.storage.config_store import load_persistent_config

logger = logging.getLogger("clippyme")


def merge_persistent_config(env: dict, persisted: dict | None) -> dict:
    """Overlay Settings values onto a job env, in place.

    Non-empty persisted values OVERRIDE the inherited process env: docker
    compose exports empty-string defaults (DEEPGRAM_API_KEY=, …) and a pinned
    TRANSCRIPTION_PROVIDER, which used to shadow the keys saved in Settings
    and silently drop every job to the Whisper fallback. Empty persisted
    values never clobber a real env value, so env-only deploys (no
    config.json) keep working. GEMINI_API_KEY is the one exception: the
    per-request X-Gemini-Key header (already in ``env``) wins, matching the
    reframe-endpoint behaviour.
    """
    for k, v in (persisted or {}).items():
        if v in (None, ""):
            continue
        if k == "GEMINI_API_KEY" and env.get(k):
            continue
        env[str(k)] = str(v)
    return env


def _enqueue_completed_job(manual_publish_queue, job_id: str, output_dir: str) -> None:
    """Enqueue a just-completed job's clips into the manual queue, if opted in.

    Non-fatal by design (called from a try/except-free thread offload, so the
    try/except lives here): a bad metadata read or a queue-state hiccup must
    never fail the job that already finished successfully.

    Monitor-owned jobs (sidecar ``owner == "live_monitor"``) are skipped: the
    live monitor is the single queue writer for its jobs — it enqueues the
    COMPOSED clip with template captions; enqueueing here would race it and
    land the raw clip first. The startup importer still backstops a crash
    between completion and the monitor's enqueue.
    """
    if read_publisher_mode(output_dir) != "manual_queue":
        return
    if read_publisher_owner(output_dir) == "live_monitor":
        return
    try:
        from clippyme.domain.manual_publish_queue import enqueue_job_clips
        enqueue_job_clips(manual_publish_queue, job_id)
    except Exception:
        logger.warning("manual-publish enqueue failed for completed job %s", job_id, exc_info=True)


def make_run_job(*, jobs: dict, output_root: str, on_change=None, manual_publish_queue=None):
    """Build the ``run_job(job_id, job_data)`` coroutine bound to shared state.

    ``on_change`` (optional, sync, never raises out) is invoked after every
    status transition so the job journal stays current on disk.

    ``manual_publish_queue`` (optional) is checked on successful completion:
    when the job's ``publisher_mode.json`` sidecar says "manual_queue" (or is
    missing — legacy default), the finished clips are enqueued for manual
    review. Monitor-owned jobs (sidecar ``owner == "live_monitor"``) are
    skipped — the monitor enqueues its own composed clips a few seconds after
    completion, and enqueueing here first would land the raw clip with the
    wrong caption. Enqueue is idempotent (dedup by job_id+clip_index) against
    an import scan. Never fatal — a failure here is logged and the job still
    completes normally.
    """

    def _notify():
        if on_change is not None:
            try:
                on_change()
            except Exception:
                logger.warning("job-journal on_change hook failed", exc_info=True)

    async def run_job(job_id, job_data):
        """Executes the subprocess for a specific job."""
        cmd = job_data['cmd']
        env = job_data['env']
        output_dir = job_data['output_dir']

        # Merge the LATEST persisted config into the job env at run time (not
        # at enqueue time). Fixes a race where the user updates a key
        # (Deepgram / HF / Gemini model / transcription provider) in Settings
        # between submit and dispatch: without this, the worker would use the
        # stale values captured at enqueue. Precedence rules live in
        # merge_persistent_config.
        try:
            merge_persistent_config(env, load_persistent_config())
        except Exception as exc:
            logger.warning("Could not merge persistent config into job env for %s: %s", job_id, exc)

        # Pre-dispatch guard: a job cancelled/stopped while still ``queued`` must
        # never launch its subprocess (closes the race noted in job_control).
        if job_control.should_skip_dispatch(jobs[job_id].get('status', '')):
            logger.info("Skipping dispatch for already-terminated job %s (%s)",
                        job_id, jobs[job_id].get('status'))
            return

        jobs[job_id]['status'] = 'processing'
        jobs[job_id]['logs'].append("Job started by worker.")
        jobs[job_id]['process'] = None  # Will hold Popen reference for cancel
        logger.info("Executing job %s: %s", job_id, ' '.join(cmd))
        _notify()

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=os.getcwd()
            )
            jobs[job_id]['process'] = process
            # The journal can't persist a Popen handle across restarts — record
            # the pid so startup recovery can kill an orphaned pipeline tree.
            jobs[job_id]['pid'] = process.pid
            # The env (with the Gemini API key) is now captured by the child
            # process; drop it from the in-memory job dict so the secret doesn't
            # linger in application state for the lifetime of the job.
            jobs[job_id].pop('env', None)
            _notify()

            # We need to capture logs in a thread because Popen isn't async
            t_log = threading.Thread(target=enqueue_output, args=(process.stdout, job_id, jobs))
            t_log.daemon = True
            t_log.start()

            # Async wait for process with incremental partial-result updates.
            # The partial-result load touches disk, so run it off the event loop
            # to avoid stalling other handlers while a batch of jobs polls.
            while process.poll() is None:
                await asyncio.sleep(2)
                partial = await asyncio.to_thread(load_partial_result, job_id, output_dir)
                if partial:
                    jobs[job_id]['result'] = partial

            returncode = process.returncode

            if jobs[job_id]['status'] == 'cancelled':
                jobs[job_id]['logs'].append("Process terminated (cancelled).")
            elif jobs[job_id]['status'] == 'stopped':
                # Graceful early stop: the subprocess was killed but we KEEP whatever
                # clips finished rendering. Promote the partial result to final so
                # the UI shows them as a normal (editable/publishable) result set.
                partial = await asyncio.to_thread(load_partial_result, job_id, output_dir)
                if partial:
                    jobs[job_id]['result'] = partial
                n = len((jobs[job_id].get('result') or {}).get('clips', []) or [])
                jobs[job_id]['logs'].append(f"Process stopped by user; kept {n} finished clip(s).")
            elif returncode == 0:
                jobs[job_id]['status'] = 'completed'
                jobs[job_id]['logs'].append("Process finished successfully.")
                # Backward-compat rescue if outputs were written to output root
                if not glob.glob(os.path.join(output_dir, "*_metadata.json")):
                    await asyncio.to_thread(relocate_root_job_artifacts, job_id, output_dir, output_root)
                final = await asyncio.to_thread(load_final_result, job_id, output_dir)
                if final:
                    jobs[job_id]['result'] = final
                    if manual_publish_queue is not None:
                        await asyncio.to_thread(
                            _enqueue_completed_job, manual_publish_queue, job_id, output_dir)
                else:
                    jobs[job_id]['status'] = 'failed'
                    jobs[job_id]['logs'].append("No metadata file generated.")
            else:
                jobs[job_id]['status'] = 'failed'
                jobs[job_id]['logs'].append(f"Process failed with exit code {returncode}")

        except Exception as e:
            jobs[job_id]['status'] = 'failed'
            jobs[job_id]['logs'].append(f"Execution error: {str(e)}")
            # Surface the full traceback server-side — the user-facing log only gets
            # str(e), so without this a crash in result-loading/relocation is
            # invisible to anyone reading the backend logs.
            logger.exception("run_job failed for job_id=%s", job_id)
            # A crash between Popen and the loop's natural exit (e.g. an unexpected
            # error from a result loader) must not leave the pipeline subprocess
            # running: status is now 'failed', so can_cancel() refuses and the
            # orphan would burn CPU/GPU unkillable via the API — while its
            # concurrency slot is already released to the next job.
            proc = jobs.get(job_id, {}).get('process')
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                    await asyncio.to_thread(lambda: proc.wait(timeout=5))
                    jobs[job_id]['logs'].append("Pipeline process killed after execution error.")
                except Exception:
                    logger.warning("Could not kill orphaned process for job %s", job_id)
        finally:
            _notify()

    return run_job
