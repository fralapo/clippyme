"""Helpers for /api/history/restore endpoint logic and restart recovery."""
import glob
import json
import os

from clippyme.clips.clip_resolve import clip_filename_for
from clippyme.core.errors import ConflictError, NotFoundError
from clippyme.jobs.job_control import ACTIVE_STATES


def restore_finished_job(jobs: dict, job_id: str, output_dir: str) -> dict:
    """Rebuild a finished job from disk into ``jobs`` and return the entry.

    Refuses (409) while the worker still owns the job: the rebuilt
    ``completed`` entry would make the dispatcher skip a queued job, hide the
    running process from stop/cancel/pause and drop the job from the crash
    journal. Sync on purpose — called on the event loop, the check and the
    swap cannot interleave with the runner's own status updates.
    """
    if (jobs.get(job_id) or {}).get("status") in ACTIVE_STATES:
        raise ConflictError("Job is still active; restore it once it has finished")
    entry = restore_job_from_disk(job_id, output_dir, os.path.join(output_dir, job_id))
    jobs[job_id] = entry
    return entry


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
