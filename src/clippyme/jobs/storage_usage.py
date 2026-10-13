"""Read-only disk accounting for the self-hosted output store.

Never follows symlinks: a user-controlled directory must not make us scan
outside the configured storage roots. Run in a worker thread from FastAPI.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from clippyme.jobs.history_service import is_valid_job_id


def folder_bytes(path: str | Path) -> int:
    """Count regular files under a directory; ignore symlinks and errors."""
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        return 0
    total = 0
    pending = [root]
    while pending:
        folder = pending.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def storage_overview(output_dir: str, data_dir: str = "data",
                     uploads_dir: str = "uploads") -> dict:
    """Return disk totals and per-job sizes without deleting anything."""
    root = Path(output_dir)
    jobs = []
    if root.is_dir() and not root.is_symlink():
        with os.scandir(root) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False) and is_valid_job_id(entry.name):
                    jobs.append({"jobId": entry.name, "bytes": folder_bytes(entry.path)})
    jobs.sort(key=lambda j: j["bytes"], reverse=True)
    usage = shutil.disk_usage(root if root.exists() else root.parent)
    free = usage.free
    return {
        "outputBytes": folder_bytes(root),
        "dataBytes": folder_bytes(data_dir),
        "uploadsBytes": folder_bytes(uploads_dir),
        "diskTotalBytes": usage.total,
        "diskFreeBytes": free,
        "lowSpace": free < max(1024 ** 3, int(usage.total * 0.05)),
        "jobs": jobs,
    }
