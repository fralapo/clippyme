"""Crash-safe journal for the in-memory job queue.

The journal stores only non-secret process metadata.  Queued jobs are requeued;
interrupted checkpoint-capable jobs are killed and safely requeued from their
last durable phase; legacy/non-resumable jobs retain the previous fail-safe
behaviour.
"""
import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field

from clippyme.domain.job_control import ACTIVE_STATES, terminate_tree
from clippyme.domain.runtime_state import is_resumable, runtime_result_fields

logger = logging.getLogger("clippyme")

JOURNAL_FILENAME = "jobs_journal.json"
_JOURNAL_LOCK = threading.RLock()


def snapshot(jobs: dict) -> dict:
    """Journal every active job without secrets, handles, logs or results."""
    records = {}
    for job_id, job in jobs.items():
        status = job.get("status")
        if status not in ACTIVE_STATES:
            continue
        records[job_id] = {
            "status": status,
            "cmd": list(job.get("cmd") or []),
            "output_dir": job.get("output_dir", ""),
            "input_path": job.get("input_path"),
            "pid": job.get("pid"),
            "attempt": int(job.get("attempt") or 0),
            "max_attempts": int(job.get("max_attempts") or 0),
            "updated_at": time.time(),
        }
    return records


def save_journal(path: str, records: dict) -> None:
    """Durably and atomically replace the owner-only job journal."""
    directory = os.path.dirname(path) or "."
    with _JOURNAL_LOCK:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".jobs-journal-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(records, file)
                file.flush()
                os.fsync(file.fileno())
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            os.replace(tmp_path, path)
            tmp_path = None
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            try:
                directory_fd = os.open(directory, os.O_RDONLY)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
                finally:
                    os.close(directory_fd)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


def load_journal(path: str) -> dict:
    """Read the journal; return ``{}`` for missing or corrupt files."""
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("Job journal unreadable (%s) — starting empty: %s", path, exc)
        return {}


def make_journal_writer(*, jobs: dict, path: str):
    """Return a best-effort snapshot writer suitable for lifecycle hooks."""

    def persist() -> None:
        try:
            save_journal(path, snapshot(jobs))
        except Exception as exc:
            logger.warning("Could not persist job journal: %s", exc)

    return persist


@dataclass
class RecoveryPlan:
    requeue: list = field(default_factory=list)
    mark_failed: list = field(default_factory=list)


def plan_recovery(records: dict) -> RecoveryPlan:
    """Pure initial classification; disk checkpoints are inspected later."""
    plan = RecoveryPlan()
    for job_id, record in records.items():
        status = (record or {}).get("status")
        if status == "queued":
            plan.requeue.append((job_id, record))
        elif status in ("processing", "paused"):
            plan.mark_failed.append((job_id, record))
    return plan


def _command_matches(actual, expected) -> bool:
    """Require the full recorded argv, allowing only executable path changes."""
    actual = [str(value) for value in (actual or [])]
    expected = [str(value) for value in (expected or [])]
    if not actual or len(actual) != len(expected):
        return False

    def executable_name(value: str) -> str:
        name = os.path.basename(value).casefold()
        return name[:-4] if name.endswith(".exe") else name

    return executable_name(actual[0]) == executable_name(expected[0]) and actual[1:] == expected[1:]


def kill_stale_tree(pid, expected_cmd) -> bool:
    """Kill a recorded process tree only when its complete argv still matches."""
    if not pid:
        return False
    try:
        import psutil

        process = psutil.Process(int(pid))
        if not _command_matches(process.cmdline(), expected_cmd):
            return False
        terminate_tree(int(pid), timeout=5.0)
        return True
    except Exception:
        return False


def _recovered_entry(job_id: str, record: dict, message: str) -> dict:
    output_dir = record.get("output_dir", "")
    max_attempts = int(record.get("max_attempts") or os.environ.get("CLIPPYME_JOB_MAX_ATTEMPTS", "3") or 3)
    env = os.environ.copy()
    env["CLIPPYME_JOB_ID"] = job_id
    env["CLIPPYME_JOB_MAX_ATTEMPTS"] = str(max(1, max_attempts))
    return {
        "status": "queued",
        "logs": [message],
        "cmd": record.get("cmd") or [],
        "env": env,
        "output_dir": output_dir,
        "input_path": record.get("input_path"),
        "attempt": int(record.get("attempt") or 0),
        "max_attempts": max(1, max_attempts),
        "result": {"clips": [], **runtime_result_fields(output_dir)},
    }


def recover_jobs(*, journal_path: str, jobs: dict, job_queue, output_root: str) -> dict:
    """Recover queued, completed-on-disk, and checkpoint-resumable jobs."""
    from clippyme.domain.clip_endpoints import restore_job_from_disk
    from clippyme.domain.errors import ClippyMeError
    from clippyme.domain.job_results import load_final_result

    plan = plan_recovery(load_journal(journal_path))
    counts = {"requeued": 0, "resumed": 0, "failed": 0, "restored": 0}

    for job_id, record in plan.requeue:
        try:
            jobs[job_id] = _recovered_entry(job_id, record, "Re-enqueued after server restart.")
            job_queue.put_nowait(job_id)
            counts["requeued"] += 1
        except Exception as exc:
            jobs.pop(job_id, None)
            logger.warning("Could not re-enqueue job %s after restart: %s", job_id, exc)

    for job_id, record in plan.mark_failed:
        output_dir = record.get("output_dir", "")
        final = None
        try:
            final = load_final_result(job_id, output_dir)
        except Exception:
            final = None
        if final:
            try:
                jobs[job_id] = restore_job_from_disk(
                    job_id, output_root, os.path.join(output_root, job_id)
                )
                counts["restored"] += 1
                continue
            except ClippyMeError:
                pass

        killed = kill_stale_tree(record.get("pid"), record.get("cmd"))
        if killed:
            logger.info(
                "Killed orphaned pipeline tree for interrupted job %s (pid=%s)",
                job_id,
                record.get("pid"),
            )

        if is_resumable(
            output_dir,
            input_path=record.get("input_path"),
            cmd=record.get("cmd"),
        ):
            try:
                jobs[job_id] = _recovered_entry(
                    job_id,
                    record,
                    "Server restarted; resuming from the last durable checkpoint.",
                )
                job_queue.put_nowait(job_id)
                counts["resumed"] += 1
                continue
            except Exception as exc:
                jobs.pop(job_id, None)
                logger.warning("Could not resume interrupted job %s: %s", job_id, exc)

        jobs[job_id] = {
            "status": "failed",
            "logs": ["Job interrupted by server restart."],
            "cmd": record.get("cmd") or [],
            "env": {},
            "output_dir": output_dir,
            "input_path": record.get("input_path"),
            "result": {"clips": [], **runtime_result_fields(output_dir)},
        }
        counts["failed"] += 1

    try:
        save_journal(journal_path, snapshot(jobs))
    except Exception as exc:
        logger.warning("Could not rewrite job journal after recovery: %s", exc)

    if any(counts.values()):
        logger.info(
            "Job recovery: %d re-enqueued, %d resumed, %d restored, %d failed",
            counts["requeued"],
            counts["resumed"],
            counts["restored"],
            counts["failed"],
        )
    return counts
