"""Crash-safe pipeline runtime state, checkpoints, and operational metrics.

The backend process and the heavy video subprocess have different lifetimes. This
module gives them one small, owner-only JSON contract inside each job directory:

* the pipeline records phase transitions, completed stages, artefacts, attempts,
  estimates and QA reports;
* the worker periodically reads that file and exposes it through the existing
  ``/api/status`` result object;
* restart recovery can decide whether an interrupted job is safe to resume.

The file is hidden *and* has a ``.json`` suffix, so ``SafeStaticFiles`` blocks it
from the public ``/videos`` mount. Every write is atomic and fsync'd.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from copy import deepcopy
from typing import Any

RUNTIME_FILENAME = ".clippyme_runtime.json"
CHECKPOINT_DIRNAME = ".clippyme_checkpoint"
SCHEMA_VERSION = 1

STAGE_ORDER = (
    "queued",
    "acquiring",
    "preflight",
    "transcribing",
    "analyzing",
    "cutting",
    "reframing",
    "quality",
    "finalizing",
    "completed",
)
STAGE_PROGRESS = {
    "queued": 2,
    "acquiring": 10,
    "preflight": 18,
    "transcribing": 35,
    "analyzing": 52,
    "cutting": 62,
    "reframing": 82,
    "quality": 92,
    "finalizing": 97,
    "completed": 100,
    "failed": 100,
    "cancelled": 100,
    "stopped": 100,
}

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: str) -> threading.RLock:
    key = os.path.abspath(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def runtime_path(output_dir: str) -> str:
    return os.path.join(output_dir, RUNTIME_FILENAME)


def checkpoint_dir(output_dir: str) -> str:
    return os.path.join(output_dir, CHECKPOINT_DIRNAME)


def _default_state(job_id: str | None = None) -> dict[str, Any]:
    now = time.time()
    return {
        "schema": SCHEMA_VERSION,
        "job_id": job_id,
        "stage": "queued",
        "progress": STAGE_PROGRESS["queued"],
        "detail": "waiting for a worker",
        "attempt": 0,
        "max_attempts": 1,
        "started_at": now,
        "updated_at": now,
        "stage_started_at": now,
        "completed_stages": [],
        "stage_durations": {},
        "artifacts": {},
        "clips": {"ready": 0, "total": 0, "failed": 0},
        "preflight": None,
        "qa": {"ok": 0, "warnings": 0, "failed": 0, "reports": {}},
        "last_error": None,
        "resumable": True,
    }


def _atomic_json(path: str, payload: dict[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".runtime-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        tmp = ""
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def load_runtime_state(output_dir: str) -> dict[str, Any] | None:
    """Return a defensive copy of the persisted runtime state, or ``None``."""
    path = runtime_path(output_dir)
    try:
        with _lock_for(path):
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
            return None
        return deepcopy(data)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return None


def _has_orchestrator_url_arg(cmd: list | None) -> bool:
    """Recognize ``-u/--url`` only after the orchestrator module argument.

    Every Python subprocess already contains ``python -u`` for unbuffered output;
    treating that interpreter flag as a source URL would incorrectly make a
    missing-upload job resumable.
    """
    argv = [str(item) for item in (cmd or [])]
    try:
        module_index = argv.index("clippyme.pipeline.orchestrator")
    except ValueError:
        return False
    return any(arg in {"-u", "--url"} for arg in argv[module_index + 1:])


def is_resumable(output_dir: str, *, input_path: str | None = None, cmd: list | None = None) -> bool:
    """Conservative restart-recovery predicate.

    URL jobs can reacquire their source from argv. Upload jobs are resumable only
    while their original upload still exists. A valid runtime state is required
    in both cases so old jobs created before checkpoint support stay fail-safe.
    """
    state = load_runtime_state(output_dir)
    if not state or not state.get("resumable", False):
        return False
    if state.get("stage") in {"completed", "cancelled", "stopped"}:
        return False
    if input_path:
        try:
            return os.path.isfile(input_path) and os.path.getsize(input_path) > 0
        except OSError:
            return False
    return _has_orchestrator_url_arg(cmd)


class RuntimeState:
    """Small atomic state machine used by the pipeline orchestrator."""

    def __init__(self, output_dir: str, *, job_id: str | None = None):
        self.output_dir = os.path.abspath(output_dir)
        self.path = runtime_path(self.output_dir)
        self.checkpoint_dir = checkpoint_dir(self.output_dir)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        try:
            os.chmod(self.checkpoint_dir, 0o700)
        except OSError:
            pass
        self.data = load_runtime_state(self.output_dir) or _default_state(job_id)
        if job_id and not self.data.get("job_id"):
            self.data["job_id"] = job_id
        self.save()

    def save(self) -> dict[str, Any]:
        self.data["updated_at"] = time.time()
        with _lock_for(self.path):
            _atomic_json(self.path, self.data)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self.data)

    def begin_attempt(self, attempt: int, max_attempts: int) -> None:
        self.data["attempt"] = max(1, int(attempt))
        self.data["max_attempts"] = max(1, int(max_attempts))
        self.data["last_error"] = None
        self.save()

    def start(self, stage: str, detail: str | None = None, *, progress: int | None = None) -> None:
        now = time.time()
        previous = self.data.get("stage")
        previous_started = self.data.get("stage_started_at")
        if previous and previous != stage and previous_started:
            elapsed = max(0.0, now - float(previous_started))
            durations = self.data.setdefault("stage_durations", {})
            durations[previous] = round(float(durations.get(previous, 0.0)) + elapsed, 3)
        self.data["stage"] = stage
        self.data["stage_started_at"] = now
        self.data["progress"] = int(progress if progress is not None else STAGE_PROGRESS.get(stage, 0))
        if detail is not None:
            self.data["detail"] = str(detail)
        self.save()

    def progress(self, value: int, detail: str | None = None) -> None:
        self.data["progress"] = max(0, min(100, int(value)))
        if detail is not None:
            self.data["detail"] = str(detail)
        self.save()

    def complete_stage(
        self,
        stage: str,
        *,
        artifacts: dict[str, Any] | None = None,
        detail: str | None = None,
    ) -> None:
        completed = self.data.setdefault("completed_stages", [])
        if stage not in completed:
            completed.append(stage)
        if artifacts:
            safe = {str(key): value for key, value in artifacts.items() if value is not None}
            self.data.setdefault("artifacts", {}).update(safe)
        if detail is not None:
            self.data["detail"] = str(detail)
        self.save()

    def completed(self, stage: str) -> bool:
        return stage in set(self.data.get("completed_stages") or [])

    def artifact(self, name: str) -> Any:
        return (self.data.get("artifacts") or {}).get(name)

    def set_preflight(self, report: dict[str, Any]) -> None:
        self.data["preflight"] = deepcopy(report)
        self.save()

    def set_clip_total(self, total: int) -> None:
        self.data.setdefault("clips", {})["total"] = max(0, int(total))
        self.save()

    def mark_clip(self, index: int, status: str, report: dict[str, Any] | None = None) -> None:
        qa = self.data.setdefault(
            "qa",
            {"ok": 0, "warnings": 0, "failed": 0, "reports": {}},
        )
        reports = qa.setdefault("reports", {})
        key = str(int(index))
        previous = reports.get(key, {}).get("status") if isinstance(reports.get(key), dict) else None
        payload = {"status": status, "updated_at": time.time()}
        if report:
            payload["report"] = deepcopy(report)
        reports[key] = payload

        clips = self.data.setdefault("clips", {"ready": 0, "total": 0, "failed": 0})
        terminal = {"ready", "warning", "failed"}
        if previous in terminal:
            if previous == "failed":
                clips["failed"] = max(0, int(clips.get("failed", 0)) - 1)
            else:
                clips["ready"] = max(0, int(clips.get("ready", 0)) - 1)
        if status in {"ready", "warning"}:
            clips["ready"] = int(clips.get("ready", 0)) + 1
        elif status == "failed":
            clips["failed"] = int(clips.get("failed", 0)) + 1

        qa["ok"] = sum(1 for value in reports.values() if value.get("status") == "ready")
        qa["warnings"] = sum(1 for value in reports.values() if value.get("status") == "warning")
        qa["failed"] = sum(1 for value in reports.values() if value.get("status") == "failed")
        self.save()

    def fail(self, error: str, *, resumable: bool = True) -> None:
        self.data["stage"] = "failed"
        self.data["progress"] = 100
        self.data["detail"] = "pipeline failed"
        self.data["last_error"] = str(error)[-2000:]
        self.data["resumable"] = bool(resumable)
        self.save()

    def finish(self, detail: str = "pipeline completed") -> None:
        self.start("completed", detail, progress=100)
        self.data["resumable"] = False
        self.complete_stage("completed")


def runtime_result_fields(output_dir: str) -> dict[str, Any]:
    """Fields merged into job results without exposing internal artifact paths."""
    state = load_runtime_state(output_dir)
    if not state:
        return {}
    public = {
        key: deepcopy(state.get(key))
        for key in (
            "stage",
            "progress",
            "detail",
            "attempt",
            "max_attempts",
            "started_at",
            "updated_at",
            "stage_durations",
            "clips",
            "preflight",
            "qa",
            "last_error",
        )
    }
    return {"operations": public}


def collect_runtime_metrics(pid: int | None, output_dir: str) -> dict[str, Any]:
    """Best-effort process-tree and host metrics; never raises."""
    metrics: dict[str, Any] = {}
    try:
        import psutil

        metrics["cpu"] = round(float(psutil.cpu_percent(interval=None)), 1)
        memory = psutil.virtual_memory()
        metrics["memory_percent"] = round(float(memory.percent), 1)
        disk = psutil.disk_usage(output_dir or ".")
        metrics["disk_free_gb"] = round(float(disk.free) / (1024 ** 3), 2)
        if pid:
            try:
                root = psutil.Process(int(pid))
                processes = [root, *root.children(recursive=True)]
                rss = 0
                for process in processes:
                    try:
                        rss += int(process.memory_info().rss)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                metrics["rss_mb"] = round(rss / (1024 ** 2), 1)
                metrics["processes"] = len(processes)
            except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                pass
    except Exception:
        try:
            usage = os.statvfs(output_dir or ".")
            metrics["disk_free_gb"] = round(
                (usage.f_bavail * usage.f_frsize) / (1024 ** 3),
                2,
            )
        except OSError:
            pass
    return metrics


def estimate_eta(state: dict[str, Any]) -> int | None:
    """Coarse ETA from completed progress and elapsed wall time."""
    progress = float(state.get("progress") or 0)
    started = float(state.get("started_at") or 0)
    if progress < 5 or progress >= 100 or started <= 0:
        return None
    elapsed = max(0.0, time.time() - started)
    total = elapsed * 100.0 / progress
    return max(0, int(total - elapsed))


def format_runtime_log(state: dict[str, Any], metrics: dict[str, Any] | None = None) -> str:
    """Stable key=value line parsed by the frontend operational panel."""
    metrics = metrics or {}
    clips = state.get("clips") or {}
    eta = estimate_eta(state)
    fields = [
        "[runtime]",
        f"stage={state.get('stage') or 'unknown'}",
        f"progress={int(state.get('progress') or 0)}",
        f"attempt={int(state.get('attempt') or 0)}/{int(state.get('max_attempts') or 1)}",
        f"clips={int(clips.get('ready') or 0)}/{int(clips.get('total') or 0)}",
    ]
    if eta is not None:
        fields.append(f"eta_s={eta}")
    for key in ("cpu", "rss_mb", "memory_percent", "disk_free_gb", "processes"):
        if key in metrics:
            fields.append(f"{key}={metrics[key]}")
    return " ".join(fields)


def upsert_runtime_log(logs: list[str], line: str) -> None:
    """Keep exactly one live telemetry row in a bounded job log."""
    for index in range(len(logs) - 1, -1, -1):
        if str(logs[index]).startswith("[runtime]"):
            logs[index] = line
            return
    logs.append(line)
