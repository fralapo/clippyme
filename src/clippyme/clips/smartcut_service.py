"""Helpers for /api/smartcut endpoint logic."""
import asyncio
import logging
import os

from clippyme.clips.clip_locks import clip_lock
from clippyme.clips.clip_resolve import ResolvedClip
from clippyme.core.errors import ClippyMeError, ValidationError
from clippyme.editing.smartcut import smart_cut

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
        # The clip lock (not only smart_cut's own path lock): a reframe that
        # replaced the clip mid-render left a smart-cut file of the OLD pixels
        # with a NEWER mtime, which smart_cut's cache then kept serving.
        async with clip_lock(resolved.job_dir, clip_index):
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
