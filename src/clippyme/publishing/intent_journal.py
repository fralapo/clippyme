"""Crash-safe receipt ledger for manual Zernio publication intents.

No secrets or media URLs; exclusively owner-only JSON outside static media.
The clip asyncio lock is acquired by publish_service before calling us.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from clippyme.core.errors import ConflictError

FILENAME = ".clippyme_publish_intents.json"
REPLAY_WINDOW_GUARD_SECONDS = 23 * 60 * 60
_LOCK = threading.RLock()


def _read(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as handle:
            doc = json.load(handle)
        if isinstance(doc, dict) and isinstance(doc.get("entries"), dict):
            return doc
    except FileNotFoundError:
        return {"version": 1, "entries": {}}
    except (OSError, ValueError):
        # Fail closed: do not issue another publish if the receipt ledger is
        # corrupt; doing so could duplicate an already-accepted remote post.
        raise ConflictError("Publication receipt ledger is unreadable; recover it before retrying")
    raise ConflictError("Publication receipt ledger is malformed")


def _write(path: Path, doc: dict) -> None:
    fd, temp = tempfile.mkstemp(prefix=".publish-intent-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        temp = ""
    finally:
        if temp:
            try:
                os.remove(temp)
            except OSError:
                pass


def _key(clip_index: int, intent_id: str) -> str:
    return f"{int(clip_index)}:{intent_id}"


def read_intent(job_dir: str, clip_index: int, intent_id: str) -> dict | None:
    with _LOCK:
        return _read(Path(job_dir) / FILENAME)["entries"].get(_key(clip_index, intent_id))


def begin_intent(job_dir: str, clip_index: int, intent_id: str,
                 now: float | None = None) -> dict:
    stamp = time.time() if now is None else now
    path = Path(job_dir) / FILENAME
    with _LOCK:
        doc = _read(path)
        entry = doc["entries"].get(_key(clip_index, intent_id))
        if entry:
            if entry.get("state") == "pending" and stamp - entry.get("started_at", 0) >= REPLAY_WINDOW_GUARD_SECONDS:
                raise ConflictError(
                    "Publication outcome is uncertain and Zernio's replay window may have expired. "
                    "Check the post in Zernio before manually creating a new publication intent."
                )
            return entry
        entry = {"state": "pending", "started_at": stamp}
        doc["entries"][_key(clip_index, intent_id)] = entry
        _write(path, doc)
        return entry


def confirm_intent(job_dir: str, clip_index: int, intent_id: str, result: dict) -> None:
    path = Path(job_dir) / FILENAME
    with _LOCK:
        doc = _read(path)
        key = _key(clip_index, intent_id)
        old = doc["entries"].get(key) or {}
        doc["entries"][key] = {
            "state": "confirmed",
            "started_at": old.get("started_at", time.time()),
            "result": {key: result.get(key) for key in ("post_id", "status", "scheduled_for", "schedule_mode")},
        }
        _write(path, doc)


def reject_intent(job_dir: str, clip_index: int, intent_id: str) -> None:
    """Remove a definitely rejected request; never remove ambiguous attempts."""
    path = Path(job_dir) / FILENAME
    with _LOCK:
        doc = _read(path)
        if doc["entries"].pop(_key(clip_index, intent_id), None) is not None:
            _write(path, doc)
