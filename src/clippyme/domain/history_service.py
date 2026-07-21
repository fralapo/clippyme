"""Disk-backed job history scanner."""
import glob
import json
import logging
import os
import re
import shutil
import threading
from pathlib import Path
from typing import List

from clippyme.domain.clip_resolve import clip_filename_for
from clippyme.domain.errors import ConflictError, NotFoundError, ValidationError
from clippyme.domain.job_artifacts import load_job_metadata, save_job_metadata

logger = logging.getLogger("clippyme")

# Strict UUID4 pattern: 8-4-4-4-12 hex with the version/variant nibbles
# fixed (4xxx and [89ab]xxx). Rejects degenerate values like 36 hyphens
# that the loose `[0-9a-fA-F-]{36}` regex used to accept.
# Lowercase-only: uuid.uuid4() always emits lowercase, so rejecting uppercase
# stops two case-variant IDs from mapping to the same directory on
# case-insensitive filesystems (macOS/Windows) and referencing another job.
_JOB_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
)
_TOMBSTONE_RE = re.compile(
    rf"^(?:history-{_JOB_ID_RE.pattern[1:-1]}-clip-[0-9]+|"
    rf"queue-{_JOB_ID_RE.pattern[1:-1]}-clip-[0-9]+)$"
)
_OUTPUT_LOCKS: dict[Path, threading.RLock] = {}
_OUTPUT_LOCKS_GUARD = threading.Lock()


def history_output_lock(output_dir) -> threading.RLock:
    """Return the shared reentrant mutation/cleanup lock for an output root."""
    output_root = Path(output_dir).resolve()
    with _OUTPUT_LOCKS_GUARD:
        return _OUTPUT_LOCKS.setdefault(output_root, threading.RLock())


def is_valid_job_id(job_id) -> bool:
    """Strict UUID v4 check — defensive against None/int/bytes input.

    The regex alone crashes on non-str input because ``re.match`` refuses
    to accept anything but str/bytes. Wrap the call so every call site
    can safely use the result as a boolean guard.
    """
    if not isinstance(job_id, str) or not job_id:
        return False
    return bool(_JOB_ID_RE.match(job_id))


def _project_path(output_dir: str, job_id: str) -> Path:
    if not is_valid_job_id(job_id):
        raise ValidationError("Invalid job ID")
    output_root = Path(output_dir).resolve()
    project = (output_root / job_id).resolve()
    if project.parent != output_root:
        raise ValidationError("Project path is outside output directory")
    if not project.is_dir():
        raise NotFoundError("Job not found")
    return project


def cleanup_history_tombstones(output_dir: str) -> None:
    with history_output_lock(output_dir):
        _cleanup_history_tombstones_locked(output_dir)


def _cleanup_history_tombstones_locked(output_dir: str) -> None:
    """Best-effort retry of known deletion records under ``output/.trash``."""
    output_root = Path(output_dir).resolve()
    trash = output_root / ".trash"
    if not trash.is_dir() or trash.is_symlink():
        return
    try:
        entries = list(trash.iterdir())
    except OSError as exc:
        logger.warning("Unable to scan History tombstones: %s", exc)
        return
    for entry in entries:
        try:
            if (
                not _TOMBSTONE_RE.fullmatch(entry.name)
                or entry.is_symlink()
                or not entry.is_dir()
                or entry.resolve().parent != trash
            ):
                continue
            shutil.rmtree(entry)
        except OSError as exc:
            logger.warning("History tombstone cleanup failed for %s: %s", entry, exc)


def _clip_artifacts(project: Path, clip_filename: str, clip_index: int):
    stem = Path(clip_filename).stem
    names = {
        clip_filename,
        f"source_{clip_filename}",
        f"{stem}_cover.jpg",
        f"source_{stem}_cover.jpg",
        f"composed_clip_{clip_index}.mp4",
    }
    patterns = (
        f"subtitle_clip_{clip_index}.*",
        f"subtitles_clip_{clip_index}.*",
        f"clip_{clip_index}_subtitle*",
        f"{stem}_smartcut_*",
    )
    paths = {project / name for name in names}
    for pattern in patterns:
        paths.update(project.glob(pattern))
    for path in paths:
        try:
            if path.resolve().parent != project:
                raise ValidationError("Clip artifact path is outside project directory")
        except OSError as exc:
            raise ValidationError("Invalid clip artifact path") from exc
    return paths


def _indexed_artifacts(project: Path, clip_index: int) -> set[Path]:
    paths = {project / f"composed_clip_{clip_index}.mp4"}
    for pattern in (
        f"subtitle_clip_{clip_index}.*",
        f"subtitles_clip_{clip_index}.*",
        f"clip_{clip_index}_subtitle*",
    ):
        paths.update(project.glob(pattern))
    return {path for path in paths if path.exists()}


def _reindexed_path(path: Path, old_index: int, new_index: int) -> Path:
    name = path.name
    replacements = (
        (f"composed_clip_{old_index}", f"composed_clip_{new_index}"),
        (f"subtitle_clip_{old_index}", f"subtitle_clip_{new_index}"),
        (f"subtitles_clip_{old_index}", f"subtitles_clip_{new_index}"),
        (f"clip_{old_index}_subtitle", f"clip_{new_index}_subtitle"),
    )
    for old, new in replacements:
        if old in name:
            return path.with_name(name.replace(old, new, 1))
    raise ValidationError("Unsupported indexed clip artifact")


def _rollback_staged(staged: dict[Path, Path], installed: dict[Path, Path]) -> None:
    for destination, tomb_path in reversed(list(installed.items())):
        if destination.exists():
            os.replace(destination, tomb_path)
    for original, tomb_path in reversed(list(staged.items())):
        if tomb_path.exists():
            os.replace(tomb_path, original)


def delete_history_clip(output_dir: str, job_id, clip_index, manual_publish_queue) -> dict:
    with history_output_lock(output_dir):
        return _delete_history_clip_locked(
            output_dir, job_id, clip_index, manual_publish_queue,
        )


def _delete_history_clip_locked(output_dir, job_id, clip_index, manual_publish_queue) -> dict:
    """Delete one History clip and its manual-publish queue artifact."""
    if not isinstance(clip_index, int) or isinstance(clip_index, bool) or clip_index < 0:
        raise ValidationError("Invalid clip index")
    cleanup_history_tombstones(output_dir)
    project = _project_path(output_dir, job_id)
    try:
        metadata_path, metadata = load_job_metadata(job_id, output_dir)
    except FileNotFoundError as exc:
        raise NotFoundError("No metadata found") from exc
    clips = metadata.get("shorts")
    if not isinstance(clips, list) or clip_index >= len(clips):
        raise NotFoundError("Clip not found")

    clip_filename = clip_filename_for(metadata_path, clips[clip_index], clip_index)
    deleted_artifacts = {
        path for path in _clip_artifacts(project, clip_filename, clip_index)
        if path.exists()
    }
    reindex = {}
    for old_index in range(clip_index + 1, len(clips)):
        for path in _indexed_artifacts(project, old_index):
            reindex[path] = _reindexed_path(path, old_index, old_index - 1)
    mutation_paths = deleted_artifacts | set(reindex)
    for path in mutation_paths | set(reindex.values()):
        if path.parent.resolve() != project or (path.exists() and not path.is_file()):
            raise ValidationError("Invalid clip artifact target")

    trash = project.parent / ".trash"
    trash.mkdir(mode=0o700, exist_ok=True)
    tombstone = trash / f"history-{job_id}-clip-{clip_index}"
    if tombstone.exists():
        raise ConflictError("History cleanup is pending; retry deletion")
    tombstone.mkdir(mode=0o700)
    staged = {}
    installed = {}
    old_metadata = dict(metadata)
    old_metadata["shorts"] = list(clips)
    remaining = len(clips) - 1
    survivors = []
    for old_index, clip in enumerate(clips):
        if old_index == clip_index:
            continue
        stable = dict(clip)
        old_filename = clip_filename_for(metadata_path, clip, old_index)
        stable["video_url"] = f"/videos/{job_id}/{old_filename}"
        survivors.append(stable)
    compacted = dict(metadata)
    compacted["shorts"] = survivors
    staged_project = tombstone / "project"
    project_moved = False
    metadata_saved = False
    try:
        for number, path in enumerate(sorted(mutation_paths)):
            tomb_path = tombstone / f"{number}-{path.name}"
            os.replace(path, tomb_path)
            staged[path] = tomb_path
        for source, destination in reindex.items():
            tomb_path = staged[source]
            os.replace(tomb_path, destination)
            installed[destination] = tomb_path

        save_job_metadata(metadata_path, compacted)
        metadata_saved = True
        if remaining == 0:
            os.replace(project, staged_project)
            project_moved = True
            manual_publish_queue.remove_job(job_id)
        else:
            manual_publish_queue.remove_clip_and_reindex(job_id, clip_index)
    except Exception:
        try:
            if project_moved and staged_project.exists():
                os.replace(staged_project, project)
                project_moved = False
        except OSError as exc:
            logger.error("Failed to restore History project %s: %s", job_id, exc)
        try:
            if metadata_saved and project.exists():
                save_job_metadata(metadata_path, old_metadata)
        except Exception as exc:
            logger.error("Failed to restore History metadata %s: %s", job_id, exc)
        try:
            if project.exists():
                _rollback_staged(staged, installed)
        except OSError as exc:
            logger.error("Failed to restore History artifacts %s: %s", job_id, exc)
        shutil.rmtree(tombstone, ignore_errors=True)
        raise

    cleanup_history_tombstones(output_dir)
    return {"project_deleted": remaining == 0, "remaining": remaining}


def delete_history_project(output_dir: str, job_id, manual_publish_queue) -> None:
    """Coordinate whole-project queue and filesystem deletion with cleanup."""
    with history_output_lock(output_dir):
        project = _project_path(output_dir, job_id)
        manual_publish_queue.remove_job(job_id)
        shutil.rmtree(project)
        cleanup_history_tombstones(output_dir)


def scan_history(output_dir: str) -> List[dict]:
    """Walk ``output_dir`` and build a history list of completed jobs.

    Returns a list sorted by directory mtime descending. Each entry has the
    shape expected by the frontend HistoryTab component.
    """
    results: List[dict] = []
    cleanup_history_tombstones(output_dir)
    try:
        for entry in os.listdir(output_dir):
            job_dir = os.path.join(output_dir, entry)
            if not os.path.isdir(job_dir) or not is_valid_job_id(entry):
                continue
            meta_files = glob.glob(os.path.join(job_dir, "*_metadata.json"))
            if not meta_files:
                continue
            # Newest-by-mtime so a reprocessed job lists its latest metadata,
            # consistent with job_results._pick_latest_metadata.
            meta_files.sort(key=os.path.getmtime, reverse=True)
            try:
                with open(meta_files[0], "r") as f:
                    data = json.load(f)
                clips = data.get("shorts", [])
                clip_files = []
                from clippyme.domain.url_utils import filename_from_video_url
                for i, clip in enumerate(clips):
                    clip_filename = filename_from_video_url(clip.get("video_url"))
                    if not clip_filename:
                        base_name = os.path.basename(meta_files[0]).replace("_metadata.json", "")
                        clip_filename = f"{base_name}_clip_{i + 1}.mp4"
                    clip_path = os.path.join(job_dir, clip_filename)
                    if os.path.exists(clip_path):
                        clip_files.append(
                            {
                                "video_url": f"/videos/{entry}/{clip_filename}",
                                "title": clip.get("video_title_for_youtube_short", ""),
                                "start": clip.get("start", 0),
                                "end": clip.get("end", 0),
                                "published": clip.get("published", []),
                            }
                        )
                dir_mtime = os.path.getmtime(job_dir)
                cost_analysis = data.get("cost_analysis") or {}
                # No top-level source-video title lives in metadata today, so
                # derive one from the filename the same way `source` already
                # does — additive alias for the frontend, not new data.
                source = (
                    os.path.basename(meta_files[0])
                    .replace("_metadata.json", "")
                    .replace("_", " ")
                )
                published_count = sum(1 for c in clip_files if c["published"])
                results.append(
                    {
                        "jobId": entry,
                        "timestamp": int(dir_mtime * 1000),
                        "clipCount": len(clip_files),
                        "clips": clip_files,
                        "cost": cost_analysis.get("total_cost"),
                        "source": source,
                        "title": source,
                        "publishedCount": published_count,
                    }
                )
            except Exception:
                continue
    except Exception as e:
        logger.warning("Error scanning history: %s", e)
    results.sort(key=lambda x: x["timestamp"], reverse=True)
    return results
