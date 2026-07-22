"""Post-hoc reframe orchestration for POST /api/reframe/{job_id}/{clip_index}.

Extracted from the app.py handler (which had grown to ~165 lines against the
thin-handler rule). The endpoint keeps validation + trust/rate-limit checks;
everything from metadata resolution through the subprocess run and metadata
persistence lives here. Raises ClippyMeError subclasses — app.py's exception
handler maps them to HTTP responses.
"""
import asyncio
import logging
import os
import sys
import time

from clippyme.domain.clip_locks import clip_lock
from clippyme.domain.clip_resolve import clip_filename_for
from clippyme.domain.errors import ClippyMeError, NotFoundError
from clippyme.domain.job_artifacts import load_job_metadata, save_job_metadata
from clippyme.storage.config_store import load_persistent_config

logger = logging.getLogger(__name__)


async def run_reframe(*, job_id: str, clip_index: int, mode: str,
                      output_root: str, jobs: dict) -> dict:
    """Re-render one clip with a different reframe mode via ``main.py
    --reframe-only`` and update metadata + in-memory job state.

    ``mode`` must already be canonical ('auto' / 'subject' / 'disabled').
    Returns the endpoint response payload (cache-busted ``new_video_url``).
    """
    output_dir = os.path.join(output_root, job_id)
    if not os.path.isdir(output_dir):
        raise NotFoundError("Job output dir not found")

    try:
        metadata_path, data = load_job_metadata(job_id, output_root)
    except FileNotFoundError:
        raise NotFoundError("Metadata not found")

    clips = data.get("shorts", [])
    if clip_index < 0 or clip_index >= len(clips):
        raise NotFoundError("Clip not found")

    clip_data = clips[clip_index]

    # Target path = the ORIGINAL reframed clip path (we overwrite it in place
    # so all downstream references — subtitle/hook/compose — keep working).
    # Routes through clip_resolve so title-based (clip_filename) and legacy
    # (video_url / positional) metadata both resolve to the real on-disk name.
    original_clip_filename = clip_filename_for(metadata_path, clip_data, clip_index)
    target_path = os.path.join(output_dir, original_clip_filename)
    source_path = os.path.join(output_dir, f"source_{original_clip_filename}")

    if not os.path.exists(source_path):
        raise ClippyMeError(
            "Source slice not available for this clip — this job was "
            "generated before the post-hoc reframe feature landed. "
            "Re-process the source to enable mode switching.",
            status_code=409,
        )

    cmd = [
        sys.executable,
        "-m",
        "clippyme.pipeline.main",
        "--reframe-only",
        "-i", source_path,
        "-o", target_path,
        "--reframe-mode", mode,
    ]

    # Re-render at the job's ORIGINAL aspect (persisted in metadata at process
    # time). Omitting this defaults main.py to 9:16 and squashes a 1:1/16:9 clip
    # when the user flips reframe mode post-run. Validate against the same
    # allow-list main.py's argparse accepts so a tampered metadata value can't
    # inject an arbitrary argv token.
    job_aspect = data.get("aspect")
    if job_aspect in ("9:16", "1:1", "16:9"):
        cmd += ["--aspect", job_aspect]

    logger.info("Reframe subprocess: %s", " ".join(cmd))

    # Propagate persisted config (Deepgram / HF / Gemini keys, transcription
    # provider, etc.) into the subprocess env. Without this, the reframe-only
    # path could silently fall back to Whisper when the user expects Deepgram,
    # or fail transcription entirely if the keys live only in data/config.json.
    reframe_env = os.environ.copy()
    try:
        for k, v in (load_persistent_config() or {}).items():
            if v is not None and k not in reframe_env:
                reframe_env[str(k)] = str(v)
    except Exception as exc:
        logger.warning("Could not merge persistent config into reframe env: %s", exc)

    # Serialise per clip: main.py --reframe-only writes a DETERMINISTIC tmp
    # path (<target>.reframe.tmp.mp4), so two concurrent requests for the same
    # clip (double-clicked "Apply & reprocess", two tabs) would race the
    # os.replace and both report success over a nondeterministic result. The
    # same lock also serialises against compose_layers, which reads the clip
    # file this subprocess overwrites.
    async with clip_lock(output_dir, clip_index):
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=reframe_env,
            )
            stdout_data, _ = await proc.communicate()
        except Exception as e:
            logger.error("Reframe subprocess launch failed: %s", e)
            raise ClippyMeError(f"Failed to launch reframe: {e}", status_code=500)

        output_text = (stdout_data or b"").decode(errors="replace")
        if proc.returncode != 0:
            # Full subprocess output is logged server-side only — never returned to
            # the client, which would leak filesystem paths / tracebacks / env.
            logger.error("Reframe failed (code %s):\n%s", proc.returncode, output_text[-2000:])
            raise ClippyMeError(
                "Reframe failed. Check server logs for details.", status_code=500)

        # Cache-busting suffix so the <video> element reloads.
        # CRITICAL: the query string MUST NOT end up in the stored video_url —
        # the publish endpoint (and any future consumer) resolves the clip
        # file on disk via `video_url.split("/")[-1]`, so a trailing `?v=...`
        # would produce `clip_1.mp4?v=1234` and a "clip file not found" error
        # on upload. Keep the clean path in metadata and append cache-bust
        # only in the HTTP response, which is what the <video> element sees.
        cache_bust = int(time.time())
        clean_video_url = f"/videos/{job_id}/{original_clip_filename}"
        new_video_url = f"{clean_video_url}?v={cache_bust}"

        # Update in-memory metadata structures with the CLEAN url, then persist.
        clips[clip_index]["video_url"] = clean_video_url
        clips[clip_index]["reframe_mode"] = mode
        data["shorts"] = clips

        # A persistence failure must NOT silently succeed: the clip on disk has
        # already been re-rendered with the new mode, so if metadata.json still
        # carries the OLD reframe_mode/video_url the divergence is invisible until
        # a restart reloads stale state. Update in-memory job state regardless
        # (so the live session is correct), but surface the save failure as a 500.
        save_failed = None
        try:
            save_job_metadata(metadata_path, data)
        except Exception as e:
            logger.error("Failed to persist metadata.json after reframe: %s", e)
            save_failed = e

        if (
            job_id in jobs
            and "result" in jobs[job_id]
            and "clips" in jobs[job_id]["result"]
            and clip_index < len(jobs[job_id]["result"]["clips"])
        ):
            # In-memory state also gets the clean URL — the frontend applies
            # its own cache-bust via `new_video_url` below on the <video> tag.
            jobs[job_id]["result"]["clips"][clip_index]["video_url"] = clean_video_url
            jobs[job_id]["result"]["clips"][clip_index]["reframe_mode"] = mode

        if save_failed is not None:
            raise ClippyMeError(
                "Reframe succeeded but metadata persistence failed; reload may show stale state",
                status_code=500,
            )

    return {
        "success": True,
        "new_video_url": new_video_url,
        "reframe_mode": mode,
    }
