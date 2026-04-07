"""Job result loading helpers extracted from app.py run_job."""
import glob
import json
import os
from typing import Any


def _build_clips(data: dict, base_name: str, job_id: str, output_dir: str, only_ready: bool) -> list:
    clips = data.get('shorts', [])
    result = []
    for i, clip in enumerate(clips):
        clip_filename = f"{base_name}_clip_{i+1}.mp4"
        clip_path = os.path.join(output_dir, clip_filename)
        exists = os.path.exists(clip_path) and os.path.getsize(clip_path) > 0
        if only_ready and not exists:
            continue
        clip['video_url'] = f"/videos/{job_id}/{clip_filename}"
        result.append(clip)
    return result


def load_partial_result(job_id: str, output_dir: str) -> dict | None:
    """Read metadata + return result dict for clips already on disk. None if nothing ready."""
    try:
        json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
        if not json_files:
            return None
        target_json = json_files[0]
        if os.path.getsize(target_json) <= 0:
            return None
        with open(target_json, 'r') as f:
            data = json.load(f)
        base_name = os.path.basename(target_json).replace('_metadata.json', '')
        ready = _build_clips(data, base_name, job_id, output_dir, only_ready=True)
        if not ready:
            return None
        return {'clips': ready, 'cost_analysis': data.get('cost_analysis')}
    except Exception:
        return None


def load_final_result(job_id: str, output_dir: str) -> dict | None:
    """Read metadata + return result with all clips. None if no metadata file."""
    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
    if not json_files:
        return None
    target_json = json_files[0]
    with open(target_json, 'r') as f:
        data = json.load(f)
    base_name = os.path.basename(target_json).replace('_metadata.json', '')
    clips = _build_clips(data, base_name, job_id, output_dir, only_ready=False)
    return {'clips': clips, 'cost_analysis': data.get('cost_analysis')}
