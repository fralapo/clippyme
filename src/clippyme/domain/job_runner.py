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
from clippyme.domain.job_worker import enqueue_output
from clippyme.storage.config_store import load_persistent_config

logger = logging.getLogger("clippyme")


def make_run_job(*, jobs: dict, output_root: str, on_change=None):
    """Build the ``run_job(job_id, job_data)`` coroutine bound to shared state.

    ``on_change`` (optional, sync, never raises out) is invoked after every
    status transition so the job journal stays current on disk.
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
        # stale values captured at enqueue. Keys already present in `env`
        # (e.g. GEMINI_API_KEY set from the X-Gemini-Key header) win over the
        # persistent config, matching the reframe-endpoint behaviour.
        try:
            for k, v in (load_persistent_config() or {}).items():
                if v is not None and k not in env:
                    env[str(k)] = str(v)
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
