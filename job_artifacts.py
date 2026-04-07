"""Filesystem helpers for relocating job artifacts written by main.py."""
import glob
import os
import shutil


def relocate_root_job_artifacts(job_id: str, job_output_dir: str, output_dir: str) -> bool:
    """Backward-compat rescue.

    If ``main.py`` accidentally wrote metadata/clips into ``output_dir`` root
    (e.g. ``output/<jobid>_...``), move them into ``output/<job_id>/`` so the
    API can find and serve them.
    """
    try:
        os.makedirs(job_output_dir, exist_ok=True)
        pattern = os.path.join(output_dir, f"{job_id}_*_metadata.json")
        meta_candidates = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if not meta_candidates:
            return False

        # Move the newest metadata and its associated clips.
        metadata_path = meta_candidates[0]
        base_name = os.path.basename(metadata_path).replace("_metadata.json", "")

        # Move metadata
        dest_metadata = os.path.join(job_output_dir, os.path.basename(metadata_path))
        if os.path.abspath(metadata_path) != os.path.abspath(dest_metadata):
            shutil.move(metadata_path, dest_metadata)

        # Move any clips that match the same base_name into the job folder
        clip_pattern = os.path.join(output_dir, f"{base_name}_clip_*.mp4")
        for clip_path in glob.glob(clip_pattern):
            dest_clip = os.path.join(job_output_dir, os.path.basename(clip_path))
            if os.path.abspath(clip_path) != os.path.abspath(dest_clip):
                shutil.move(clip_path, dest_clip)

        # Also move any temp_ clips that might remain
        temp_clip_pattern = os.path.join(output_dir, f"temp_{base_name}_clip_*.mp4")
        for clip_path in glob.glob(temp_clip_pattern):
            dest_clip = os.path.join(job_output_dir, os.path.basename(clip_path))
            if os.path.abspath(clip_path) != os.path.abspath(dest_clip):
                shutil.move(clip_path, dest_clip)

        return True
    except Exception:
        return False
