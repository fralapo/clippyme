"""Disk-backed job history scanner."""
import glob
import json
import logging
import os
import re
from typing import List

from clippyme.domain.clip_resolve import clip_filename_for

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
                for i, clip in enumerate(clips):
                    clip_filename = clip_filename_for(meta_files[0], clip, i)
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
