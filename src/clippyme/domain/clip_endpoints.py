"""Helpers for /api/smartcut and /api/history/restore endpoint logic."""
import asyncio
import glob
import json
import logging
import os

from clippyme.domain.errors import ClippyMeError, NotFoundError, ValidationError
from clippyme.domain.smartcut import smart_cut
from clippyme.domain.url_utils import filename_from_video_url

logger = logging.getLogger(__name__)


def _resolve_clip_path(metadata_path: str, clip_data: dict, clip_index: int, output_dir: str) -> tuple[str, str]:
    """Return (filename, full_path) for a clip referenced by metadata."""
    filename = filename_from_video_url(clip_data.get("video_url"))
    if not filename:
        base_name = os.path.basename(metadata_path).replace("_metadata.json", "")
        filename = f"{base_name}_clip_{clip_index + 1}.mp4"
    return filename, os.path.join(output_dir, filename)


async def run_smart_cut(
    *, job_id: str, clip_index: int, output_dir: str, metadata_path: str, data: dict
) -> dict:
    """Execute smart_cut for a single clip. Returns endpoint response payload.

    Raises HTTPException for client/server errors.

    Idempotency: calling this twice on the same clip is safe. ``smart_cut``
    computes a stable hash over (input path, keep-segments, encoder flags)
    and short-circuits when the cached result on disk matches — so repeated
    clicks from the dashboard never re-render the same plan. The only cost
    of a repeat call is a transcript walk to produce the plan hash.
    """
    transcript = data.get("transcript")
    if not transcript:
        raise ValidationError("Transcript not found in metadata.")

    clips = data.get("shorts", [])
    if clip_index >= len(clips):
        raise NotFoundError("Clip not found")

    clip_data = clips[clip_index]
    filename, clip_path = _resolve_clip_path(metadata_path, clip_data, clip_index, output_dir)
    if not os.path.exists(clip_path):
        raise NotFoundError(f"Clip file not found: {filename}")

    try:
        loop = asyncio.get_event_loop()
        result_path, stats = await loop.run_in_executor(
            None,
            smart_cut,
            clip_path,
            transcript,
            clip_data["start"],
            clip_data["end"],
            transcript.get("language", "en"),
        )
        if result_path is None:
            return {
                "success": False,
                "message": "No significant silences or fillers found to remove.",
                "stats": stats,
            }
        smartcut_filename = os.path.basename(result_path)
        return {
            "success": True,
            "new_video_url": f"/videos/{job_id}/{smartcut_filename}",
            "stats": stats,
        }
    except ClippyMeError:
        raise
    except Exception as e:
        logger.error("Smart cut error: %s", e)
        raise ClippyMeError(str(e), status_code=500)


def restore_job_from_disk(job_id: str, output_dir: str, job_dir: str) -> dict:
    """Read metadata + rebuild a completed job entry. Returns the job dict
    (caller is responsible for inserting it into the global jobs map)."""
    if not os.path.isdir(job_dir):
        raise NotFoundError("Job not found on disk")
    meta_files = glob.glob(os.path.join(job_dir, "*_metadata.json"))
    if not meta_files:
        raise NotFoundError("No metadata found for this job")
    # Newest-by-mtime, consistent with job_results._pick_latest_metadata.
    meta_files.sort(key=os.path.getmtime, reverse=True)

    with open(meta_files[0], "r") as f:
        data = json.load(f)
    clips = data.get("shorts", [])
    base_name = os.path.basename(meta_files[0]).replace("_metadata.json", "")
    present = []
    for i, clip in enumerate(clips):
        clip_filename = filename_from_video_url(clip.get("video_url"))
        if not clip_filename:
            clip_filename = f"{base_name}_clip_{i+1}.mp4"
        # Only restore clips whose rendered file actually made it to disk. When a
        # job is stopped/cancelled mid-render the metadata still lists every
        # Gemini moment (e.g. 15 shorts) while only the clips that finished
        # rendering exist on disk (e.g. 5 mp4s). Restoring the phantom ones would
        # fill the grid with dead 404 video tiles.
        if not os.path.exists(os.path.join(job_dir, clip_filename)):
            continue
        # Store the clean URL back — strip any stale ?v= cache-bust so
        # downstream consumers (publish, smartcut, compose) never have to
        # defensively split on `?` again.
        clip["video_url"] = f"/videos/{job_id}/{clip_filename}"
        present.append(clip)

    if not present:
        raise NotFoundError("Job has no rendered clips on disk")

    return {
        "status": "completed",
        "logs": ["Restored from disk."],
        "cmd": [],
        "env": {},
        "output_dir": job_dir,
        "result": {"clips": present, "cost_analysis": data.get("cost_analysis")},
    }
