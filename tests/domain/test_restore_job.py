"""restore_job_from_disk: only clips whose rendered file exists are restored.

A job stopped/cancelled mid-render leaves a metadata file listing every Gemini
moment while only the finished clips exist on disk. Restoring the phantom ones
put dead 404 video tiles in the grid — these tests lock the filter that drops
them.
"""
import json
import os

import pytest

from clippyme.domain.clip_endpoints import restore_job_from_disk
from clippyme.domain.errors import NotFoundError


def _write_job(tmp_path, job_id, shorts, present_indices):
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    base = f"{job_id}"
    meta = {"shorts": shorts, "cost_analysis": {"total_cost": 0.1}}
    (job_dir / f"{base}_metadata.json").write_text(json.dumps(meta))
    for i in present_indices:
        fname = f"{base}_clip_{i + 1}.mp4"
        (job_dir / fname).write_bytes(b"\x00")
    return str(job_dir)


def test_restore_filters_missing_clip_files(tmp_path):
    job_id = "11111111-1111-1111-1111-111111111111"
    shorts = [
        {"video_url": f"/videos/{job_id}/{job_id}_clip_{i + 1}.mp4", "title": f"c{i}"}
        for i in range(3)
    ]
    # Only clip 1 + 2 rendered to disk; clip 3 was never written.
    job_dir = _write_job(tmp_path, job_id, shorts, present_indices=[0, 1])

    entry = restore_job_from_disk(job_id, str(tmp_path), job_dir)
    clips = entry["result"]["clips"]
    assert len(clips) == 2
    assert all(os.path.basename(c["video_url"]).endswith(".mp4") for c in clips)
    # The phantom clip_3 must be gone.
    assert not any("clip_3" in c["video_url"] for c in clips)


def test_restore_all_present(tmp_path):
    job_id = "22222222-2222-2222-2222-222222222222"
    shorts = [
        {"video_url": f"/videos/{job_id}/{job_id}_clip_{i + 1}.mp4"} for i in range(2)
    ]
    job_dir = _write_job(tmp_path, job_id, shorts, present_indices=[0, 1])
    entry = restore_job_from_disk(job_id, str(tmp_path), job_dir)
    assert len(entry["result"]["clips"]) == 2


def test_restore_resolves_title_based_clip_filename(tmp_path):
    # New-format metadata (task 4): clip_filename is the sanitized-title
    # basename, and the file on disk is named that way, not positionally.
    job_id = "44444444-4444-4444-4444-444444444444"
    job_dir = os.path.join(str(tmp_path), job_id)
    os.makedirs(job_dir)
    shorts = [{"clip_filename": "epic_moment_clip_1.mp4", "title": "epic"}]
    with open(os.path.join(job_dir, f"{job_id}_metadata.json"), "w") as f:
        json.dump({"shorts": shorts, "cost_analysis": {"total_cost": 0.1}}, f)
    open(os.path.join(job_dir, "epic_moment_clip_1.mp4"), "wb").close()

    entry = restore_job_from_disk(job_id, str(tmp_path), job_dir)
    clips = entry["result"]["clips"]
    assert len(clips) == 1
    assert clips[0]["video_url"] == f"/videos/{job_id}/epic_moment_clip_1.mp4"


def test_restore_no_clips_on_disk_raises(tmp_path):
    job_id = "33333333-3333-3333-3333-333333333333"
    shorts = [{"video_url": f"/videos/{job_id}/{job_id}_clip_1.mp4"}]
    job_dir = _write_job(tmp_path, job_id, shorts, present_indices=[])
    with pytest.raises(NotFoundError):
        restore_job_from_disk(job_id, str(tmp_path), job_dir)
