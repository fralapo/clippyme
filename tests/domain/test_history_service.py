"""Tests for clippyme.domain.history_service.

Covers strict UUID validation and disk scanning (valid/invalid dirs, missing
metadata, corrupt JSON, mtime-descending sort). Uses tmp_path so no real
output dir is read.
"""
import json
import os

from clippyme.domain import history_service as hs

VALID_UUID = "12345678-1234-4123-8123-1234567890ab"
VALID_UUID_2 = "abcdef01-2345-4678-9abc-def012345678"


def test_is_valid_job_id_accepts_uuid4():
    assert hs.is_valid_job_id(VALID_UUID) is True


def test_is_valid_job_id_rejects_non_str():
    assert hs.is_valid_job_id(None) is False
    assert hs.is_valid_job_id(12345) is False
    assert hs.is_valid_job_id(b"bytes") is False


def test_is_valid_job_id_rejects_loose_garbage():
    # The old loose regex accepted 36 hyphens / wrong version nibble.
    assert hs.is_valid_job_id("-" * 36) is False
    assert hs.is_valid_job_id("12345678-1234-1123-8123-1234567890ab") is False  # v1, not v4
    assert hs.is_valid_job_id("not-a-uuid") is False


def _make_job(output_dir, job_id, *, clips, mtime=None):
    job_dir = os.path.join(output_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)
    meta = os.path.join(job_dir, "myvideo_metadata.json")
    with open(meta, "w") as f:
        json.dump({"shorts": clips, "cost_analysis": {"total_cost": 0.42}}, f)
    # Create the referenced clip files so they count.
    for i, _ in enumerate(clips):
        open(os.path.join(job_dir, f"myvideo_clip_{i + 1}.mp4"), "wb").close()
    if mtime is not None:
        os.utime(job_dir, (mtime, mtime))
    return job_dir


def test_scan_history_empty_dir(tmp_path):
    assert hs.scan_history(str(tmp_path)) == []


def test_scan_history_skips_invalid_job_dirs(tmp_path):
    os.makedirs(os.path.join(str(tmp_path), "not-a-uuid"))
    _make_job(str(tmp_path), VALID_UUID, clips=[{"start": 0, "end": 10}])
    out = hs.scan_history(str(tmp_path))
    assert len(out) == 1
    assert out[0]["jobId"] == VALID_UUID


def test_scan_history_skips_dir_without_metadata(tmp_path):
    os.makedirs(os.path.join(str(tmp_path), VALID_UUID))  # no metadata file
    assert hs.scan_history(str(tmp_path)) == []


def test_scan_history_tolerates_corrupt_metadata(tmp_path):
    job_dir = os.path.join(str(tmp_path), VALID_UUID)
    os.makedirs(job_dir)
    with open(os.path.join(job_dir, "x_metadata.json"), "w") as f:
        f.write("{broken")
    # Corrupt JSON is swallowed per-entry, not raised.
    assert hs.scan_history(str(tmp_path)) == []


def test_scan_history_sorted_by_mtime_desc(tmp_path):
    _make_job(str(tmp_path), VALID_UUID, clips=[{"start": 0, "end": 10}], mtime=1000)
    _make_job(str(tmp_path), VALID_UUID_2, clips=[{"start": 0, "end": 10}], mtime=2000)
    out = hs.scan_history(str(tmp_path))
    assert [e["jobId"] for e in out] == [VALID_UUID_2, VALID_UUID]


def test_scan_history_reports_clip_count_and_cost(tmp_path):
    _make_job(str(tmp_path), VALID_UUID, clips=[{"start": 0, "end": 10}, {"start": 11, "end": 20}])
    out = hs.scan_history(str(tmp_path))
    assert out[0]["clipCount"] == 2
    assert out[0]["cost"] == 0.42
