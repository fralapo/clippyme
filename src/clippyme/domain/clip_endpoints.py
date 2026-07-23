"""Helpers for /api/smartcut and /api/history/restore endpoint logic."""
import asyncio
import glob
import json
import logging
import os

from clippyme.domain.clip_resolve import ResolvedClip, clip_filename_for
from clippyme.domain.errors import ClippyMeError, NotFoundError, ValidationError
from clippyme.domain.smartcut import smart_cut

logger = logging.getLogger(__name__)


async def run_smart_cut(
    *, job_id: str, clip_index: int, resolved: ResolvedClip, drop_ranges=None,
) -> dict:
    """Execute smart_cut for a single clip. Returns endpoint response payload.

    ``resolved`` comes from ``clip_resolve.resolve_clip`` (metadata, clip entry
    and on-disk path already validated).

    Idempotency: calling this twice on the same clip is safe. ``smart_cut``
    computes a stable hash over (input path, keep-segments, encoder flags)
    and short-circuits when the cached result on disk matches — so repeated
    clicks from the dashboard never re-render the same plan. The only cost
    of a repeat call is a transcript walk to produce the plan hash.
    """
    transcript = resolved.metadata.get("transcript")
    if not transcript:
        raise ValidationError("Transcript not found in metadata.")

    clip_data = resolved.clip_info
    clip_path = resolved.clip_path

    try:
        result_path, stats = await asyncio.to_thread(
            smart_cut,
            clip_path,
            transcript,
            clip_data["start"],
            clip_data["end"],
            transcript.get("language", "en"),
            drop_ranges,
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
    present = []
    for i, clip in enumerate(clips):
        # Mirror job_results._build_clips: never resurface a clip deleted
        # after a confirmed publish, and keep `original_index` as the
        # ABSOLUTE position in `shorts` (not the post-skip array position) so
        # per-clip endpoints resolve the right clip even when a gap exists.
        if clip.get('deleted_after_publish'):
            continue
        clip_filename = clip_filename_for(meta_files[0], clip, i)
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
        clip["original_index"] = i
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
