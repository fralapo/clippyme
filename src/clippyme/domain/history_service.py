"""Disk-backed job history scanner."""
import glob
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import List

from clippyme.domain.clip_resolve import clip_filename_for
from clippyme.domain.errors import NotFoundError, ValidationError
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


def delete_history_clip(output_dir: str, job_id, clip_index, manual_publish_queue) -> dict:
    """Delete one History clip and its manual-publish queue artifact."""
    if not isinstance(clip_index, int) or isinstance(clip_index, bool) or clip_index < 0:
        raise ValidationError("Invalid clip index")
    project = _project_path(output_dir, job_id)
    try:
        metadata_path, metadata = load_job_metadata(job_id, output_dir)
    except FileNotFoundError as exc:
        raise NotFoundError("No metadata found") from exc
    clips = metadata.get("shorts")
    if not isinstance(clips, list) or clip_index >= len(clips):
        raise NotFoundError("Clip not found")

    clip_filename = clip_filename_for(metadata_path, clips[clip_index], clip_index)
    artifacts = _clip_artifacts(project, clip_filename, clip_index)
    manual_publish_queue.remove_clip(job_id, clip_index)
    remaining = len(clips) - 1
    if remaining == 0:
        manual_publish_queue.remove_job(job_id)
        shutil.rmtree(project)
        return {"project_deleted": True, "remaining": 0}

    for path in artifacts:
        if path.is_dir():
            raise ValidationError("Clip artifact is not a file")
        path.unlink(missing_ok=True)
    metadata["shorts"] = clips[:clip_index] + clips[clip_index + 1:]
    save_job_metadata(metadata_path, metadata)
    return {"project_deleted": False, "remaining": remaining}


def scan_history(output_dir: str) -> List[dict]:
    """Walk ``output_dir`` and build a history list of completed jobs.

    Returns a list sorted by directory mtime descending. Each entry has the
    shape expected by the frontend HistoryTab component.
    """
    results: List[dict] = []
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
