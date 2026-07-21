"""Persistent queue of frozen MP4 artifacts for manual publishing."""

from __future__ import annotations

import json
import os
import shutil
import stat
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from clippyme.domain.errors import ConflictError, NotFoundError, ValidationError
from clippyme.domain.history_service import is_valid_job_id


_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_STATUSES = {"pending", "completed"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _lock_for(path: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, threading.RLock())


class ManualPublishQueue:
    def __init__(self, output_dir: Path, state_path: Path):
        self.output_dir = Path(output_dir).resolve()
        self.state_path = Path(state_path).resolve()
        self._lock = _lock_for(self.state_path)

    def enqueue(
        self,
        *,
        job_id,
        clip_index,
        source_path,
        title,
        caption,
        source_platform,
        source_channel,
        source_kind,
        project_title,
        monitor_id=None,
    ) -> dict:
        job_dir = self._job_dir(job_id)
        source = self._inside_output(source_path, "Source")
        if not source.is_file() or not source.is_relative_to(job_dir):
            raise ValidationError("Source video must exist inside the job directory")
        if not isinstance(clip_index, int) or isinstance(clip_index, bool) or clip_index < 0:
            raise ValidationError("Invalid clip index")

        entry_id = str(uuid.uuid4())
        artifact = job_dir / "manual_queue" / f"{entry_id}.mp4"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        try:
            try:
                os.link(source, artifact)
            except OSError:
                shutil.copy2(source, artifact)
        except Exception:
            artifact.unlink(missing_ok=True)
            raise

        entry = {
            "id": entry_id,
            "status": "pending",
            "job_id": job_id,
            "clip_index": clip_index,
            "monitor_id": monitor_id,
            "artifact": artifact.relative_to(self.output_dir.parent).as_posix(),
            "title": str(title),
            "caption": str(caption),
            "source_platform": str(source_platform),
            "source_channel": str(source_channel),
            "source_kind": str(source_kind),
            "project_title": str(project_title),
            "created_at": _utc_now(),
            "completed_at": None,
        }
        try:
            with self._lock:
                entries = self._load()
                entries.append(entry)
                self._save(entries)
        except Exception:
            artifact.unlink(missing_ok=True)
            raise
        return dict(entry)

    def list_entries(self, status="pending"):
        if status not in {*_STATUSES, "all"}:
            raise ValidationError("Status must be pending, completed, or all")
        with self._lock:
            entries = self._load()
            return [
                dict(entry)
                for entry in entries
                if (status == "all" or entry.get("status") == status)
                and self._artifact_path(entry) is not None
            ]

    def complete(self, entry_id):
        return self._transition(entry_id, expected="pending", target="completed")

    def restore(self, entry_id):
        return self._transition(entry_id, expected="completed", target="pending")

    def remove_job(self, job_id):
        self._job_dir(job_id)
        return self._remove(lambda entry: entry.get("job_id") == job_id)

    def remove_clip(self, job_id, clip_index):
        self._job_dir(job_id)
        return self._remove(
            lambda entry: entry.get("job_id") == job_id
            and entry.get("clip_index") == clip_index
        )

    def resolve_video(self, entry_id) -> BinaryIO:
        entry_id = self._entry_id(entry_id)
        with self._lock:
            entry = next((e for e in self._load() if e.get("id") == entry_id), None)
            if entry is None:
                raise NotFoundError("Manual publish entry not found")
            artifact = self._artifact_path(entry)
            if artifact is None:
                raise NotFoundError("Manual publish artifact not found")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(artifact, flags)
            except (FileNotFoundError, NotADirectoryError, OSError) as exc:
                raise NotFoundError("Manual publish artifact not found") from exc
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise NotFoundError("Manual publish artifact is not a regular file")
                return os.fdopen(descriptor, "rb")
            except Exception:
                os.close(descriptor)
                raise

    def _transition(self, entry_id, *, expected, target):
        entry_id = self._entry_id(entry_id)
        with self._lock:
            entries = self._load()
            entry = next((e for e in entries if e.get("id") == entry_id), None)
            if entry is None:
                raise NotFoundError("Manual publish entry not found")
            if self._artifact_path(entry) is None:
                raise NotFoundError("Manual publish artifact not found")
            if entry.get("status") != expected:
                raise ConflictError(f"Entry is not {expected}")
            entry["status"] = target
            entry["completed_at"] = _utc_now() if target == "completed" else None
            self._save(entries)
            return dict(entry)

    def _remove(self, predicate):
        with self._lock:
            entries = self._load()
            removed = [entry for entry in entries if predicate(entry)]
            if not removed:
                return 0
            for entry in removed:
                artifact = self._artifact_path(entry, require_file=False)
                if artifact is not None:
                    try:
                        artifact.unlink(missing_ok=True)
                    except OSError as exc:
                        raise ConflictError(
                            "Manual publish artifact is currently in use; retry removal"
                        ) from exc
            # Commit logical removal only after every artifact is gone. If the
            # state write fails, records remain discoverable and a retry is
            # safe because unlink(missing_ok=True) is idempotent.
            self._save([entry for entry in entries if not predicate(entry)])
            return len(removed)

    def _load(self):
        if not self.state_path.exists():
            return []
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("Manual publish queue state is invalid") from exc
        entries = payload.get("entries", []) if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ValidationError("Manual publish queue state is invalid")
        for entry in entries:
            self._validate_entry(entry)
        return entries

    def _validate_entry(self, entry):
        if not isinstance(entry, dict):
            raise ValidationError("Manual publish queue entry is invalid")
        required_text = (
            "title",
            "caption",
            "source_platform",
            "source_channel",
            "source_kind",
            "project_title",
            "created_at",
        )
        if any(not isinstance(entry.get(field), str) for field in required_text):
            raise ValidationError("Manual publish queue entry is invalid")
        if entry.get("status") not in _STATUSES:
            raise ValidationError("Manual publish queue entry has invalid status")
        monitor_id = entry.get("monitor_id")
        if monitor_id is not None and not isinstance(monitor_id, str):
            raise ValidationError("Manual publish queue entry is invalid")
        clip_index = entry.get("clip_index")
        if not isinstance(clip_index, int) or isinstance(clip_index, bool) or clip_index < 0:
            raise ValidationError("Manual publish queue entry has invalid clip index")
        entry_id = self._entry_id(entry.get("id"))
        job_dir = self._job_dir(entry.get("job_id"))
        expected = job_dir / "manual_queue" / f"{entry_id}.mp4"
        expected_stored = expected.relative_to(self.output_dir.parent).as_posix()
        if entry.get("artifact") != expected_stored:
            raise ValidationError("Manual publish queue entry has invalid artifact path")
        try:
            stored = (self.output_dir.parent / entry["artifact"]).resolve()
        except OSError as exc:
            raise ValidationError("Manual publish queue entry has invalid artifact path") from exc
        if stored != expected:
            raise ValidationError("Manual publish queue entry has invalid artifact path")
        completed_at = entry.get("completed_at")
        if entry["status"] == "pending" and completed_at is not None:
            raise ValidationError("Pending entry cannot have completed_at")
        if entry["status"] == "completed" and not isinstance(completed_at, str):
            raise ValidationError("Completed entry must have completed_at")

    def _save(self, entries):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"entries": entries}, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.state_path)
            os.chmod(self.state_path, 0o600)
        finally:
            tmp.unlink(missing_ok=True)

    def _job_dir(self, job_id):
        if not isinstance(job_id, str) or not is_valid_job_id(job_id):
            raise ValidationError("Invalid job ID")
        return self._inside_output(self.output_dir / job_id, "Job")

    def _inside_output(self, path, label):
        try:
            resolved = Path(path).resolve()
            resolved.relative_to(self.output_dir)
        except (OSError, ValueError) as exc:
            raise ValidationError(f"{label} path is outside output directory") from exc
        return resolved

    def _artifact_path(self, entry, *, require_file=True):
        try:
            artifact = (self.output_dir.parent / entry["artifact"]).resolve()
            job_dir = self._job_dir(entry["job_id"])
            expected = job_dir / "manual_queue" / f"{self._entry_id(entry['id'])}.mp4"
            if artifact != expected or not artifact.is_relative_to(self.output_dir):
                return None
            if require_file and not artifact.is_file():
                return None
            return artifact
        except (KeyError, TypeError, OSError, ValidationError):
            return None

    @staticmethod
    def _entry_id(entry_id):
        try:
            parsed = uuid.UUID(str(entry_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError("Invalid manual publish entry ID") from exc
        if str(parsed) != str(entry_id):
            raise ValidationError("Invalid manual publish entry ID")
        return str(parsed)
