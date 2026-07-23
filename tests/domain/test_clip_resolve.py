"""Host tests for clippyme.domain.clip_resolve — the shared job/clip resolver.

Pins the resolution chain every per-clip endpoint depends on: job dir →
latest-by-mtime metadata → clip entry → filename (video_url first, positional
fallback) → optional file-existence gate.
"""
import json
import os
import time

import pytest

from clippyme.domain.clip_resolve import (
    clip_filename_for, composed_clip_basename, resolve_clip,
)
from clippyme.domain.errors import NotFoundError


def test_composed_clip_basename_title_based():
    assert composed_clip_basename(
        {"video_title_for_youtube_short": "Litigio shock! in villa"}, 0
    ) == "Litigio shock! in villa.mp4"
    # falls back to positional when no usable title
    assert composed_clip_basename({"start": 0}, 2) == "composed_clip_2.mp4"
    assert composed_clip_basename({"video_title_for_youtube_short": "***"}, 1) == "composed_clip_1.mp4"
    # honours legacy "title" key
    assert composed_clip_basename({"title": "Ciao mondo"}, 0) == "Ciao mondo.mp4"

JOB_ID = "33333333-3333-4333-8333-333333333333"


def _write_meta(job_dir, name, shorts):
    path = job_dir / name
    with open(path, "w") as f:
        json.dump({"shorts": shorts}, f)
    return path


@pytest.fixture
def job_dir(tmp_path):
    d = tmp_path / JOB_ID
    d.mkdir()
    return d


def test_missing_job_dir_404(tmp_path):
    with pytest.raises(NotFoundError, match="Job not found"):
        resolve_clip(JOB_ID, 0, str(tmp_path))


def test_missing_metadata_404(tmp_path, job_dir):
    with pytest.raises(NotFoundError, match="No metadata found"):
        resolve_clip(JOB_ID, 0, str(tmp_path))


def test_bad_clip_index_404(tmp_path, job_dir):
    _write_meta(job_dir, "vid_metadata.json", [{"start": 0, "end": 5}])
    for idx in (-1, 1, 99):
        with pytest.raises(NotFoundError, match="Clip not found"):
            resolve_clip(JOB_ID, idx, str(tmp_path))


def test_filename_from_video_url(tmp_path, job_dir):
    _write_meta(job_dir, "vid_metadata.json",
                [{"video_url": f"/videos/{JOB_ID}/custom_name.mp4?v=123"}])
    (job_dir / "custom_name.mp4").write_bytes(b"\x00")
    r = resolve_clip(JOB_ID, 0, str(tmp_path))
    assert r.clip_filename == "custom_name.mp4"
    assert r.clip_path == str(job_dir / "custom_name.mp4")
    assert r.job_dir == str(job_dir)


def test_positional_fallback_when_no_video_url(tmp_path, job_dir):
    _write_meta(job_dir, "vid_metadata.json", [{"start": 0, "end": 5}])
    (job_dir / "vid_clip_1.mp4").write_bytes(b"\x00")
    r = resolve_clip(JOB_ID, 0, str(tmp_path))
    assert r.clip_filename == "vid_clip_1.mp4"  # 1-indexed convention


def test_missing_file_404_only_when_required(tmp_path, job_dir):
    _write_meta(job_dir, "vid_metadata.json", [{"start": 0, "end": 5}])
    with pytest.raises(NotFoundError, match="Clip file not found"):
        resolve_clip(JOB_ID, 0, str(tmp_path))
    # require_file=False resolves the path without demanding the file exists
    r = resolve_clip(JOB_ID, 0, str(tmp_path), require_file=False)
    assert r.clip_filename == "vid_clip_1.mp4"
    assert not os.path.exists(r.clip_path)


# --- clip_filename_for: task 4b preference chain ---------------------------

def test_clip_filename_for_prefers_clip_filename_key():
    filename = clip_filename_for(
        "vid_metadata.json",
        {"clip_filename": "My Viral Title_clip_1.mp4",
         "video_url": "/videos/x/legacy_clip_1.mp4"},
        0,
    )
    assert filename == "My Viral Title_clip_1.mp4"


@pytest.mark.parametrize("bad", [
    "../../etc/passwd",
    "sub/dir_clip_1.mp4",
    "sub\\dir_clip_1.mp4",
    "",
    123,
    None,
])
def test_clip_filename_for_ignores_tampered_clip_filename(bad):
    filename = clip_filename_for(
        "vid_metadata.json",
        {"clip_filename": bad, "video_url": "/videos/x/legacy_clip_1.mp4"},
        0,
    )
    assert filename == "legacy_clip_1.mp4"


def test_clip_filename_for_positional_fallback_unaffected():
    # No clip_filename, no video_url → byte-identical legacy behaviour.
    filename = clip_filename_for("vid_metadata.json", {"start": 0, "end": 5}, 2)
    assert filename == "vid_clip_3.mp4"


def test_resolve_clip_end_to_end_with_new_format_metadata(tmp_path, job_dir):
    _write_meta(job_dir, "vid_metadata.json",
                [{"clip_filename": "Best Moment Ever_clip_1.mp4"}])
    (job_dir / "Best Moment Ever_clip_1.mp4").write_bytes(b"\x00")
    r = resolve_clip(JOB_ID, 0, str(tmp_path))
    assert r.clip_filename == "Best Moment Ever_clip_1.mp4"
    assert r.clip_path == str(job_dir / "Best Moment Ever_clip_1.mp4")


def test_latest_metadata_by_mtime_wins(tmp_path, job_dir):
    _write_meta(job_dir, "old_metadata.json", [{"start": 0, "end": 1}])
    time.sleep(0.02)
    newer = _write_meta(job_dir, "new_metadata.json",
                        [{"start": 0, "end": 2}, {"start": 2, "end": 4}])
    (job_dir / "new_clip_2.mp4").write_bytes(b"\x00")
    r = resolve_clip(JOB_ID, 1, str(tmp_path))
    assert r.metadata_path == str(newer)
    assert r.clip_info == {"start": 2, "end": 4}
