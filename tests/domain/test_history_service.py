"""Tests for clippyme.domain.history_service.

Covers strict UUID validation and disk scanning (valid/invalid dirs, missing
metadata, corrupt JSON, mtime-descending sort). Uses tmp_path so no real
output dir is read.
"""
import json
import os

import pytest

from clippyme.domain import history_service as hs
from clippyme.domain.clip_resolve import resolve_clip
from clippyme.domain.errors import NotFoundError, ValidationError
from clippyme.domain.manual_publish_queue import ManualPublishQueue

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


def test_scan_history_surfaces_title_matching_source(tmp_path):
    _make_job(str(tmp_path), VALID_UUID, clips=[{"start": 0, "end": 10}])
    out = hs.scan_history(str(tmp_path))
    assert out[0]["title"] == out[0]["source"] == "myvideo"


def test_scan_history_surfaces_published_records(tmp_path):
    clips = [
        {"start": 0, "end": 10, "published": [{"platforms": ["tiktok"], "post_id": "p1"}]},
        {"start": 11, "end": 20},
    ]
    _make_job(str(tmp_path), VALID_UUID, clips=clips)
    out = hs.scan_history(str(tmp_path))
    assert out[0]["clips"][0]["published"] == [{"platforms": ["tiktok"], "post_id": "p1"}]
    assert out[0]["clips"][1]["published"] == []
    assert out[0]["publishedCount"] == 1


def test_delete_history_clip_removes_artifacts_and_keeps_survivor_addressable(tmp_path):
    output = tmp_path / "output"
    job_dir = output / VALID_UUID
    job_dir.mkdir(parents=True)
    metadata_path = job_dir / "video_metadata.json"
    metadata_path.write_text(json.dumps({"shorts": [
        {"video_url": f"/videos/{VALID_UUID}/video_clip_1.mp4", "title": "gone"},
        {"video_url": f"/videos/{VALID_UUID}/video_clip_2.mp4", "title": "kept"},
    ]}), encoding="utf-8")
    deleted = [
        job_dir / "video_clip_1.mp4",
        job_dir / "source_video_clip_1.mp4",
        job_dir / "video_clip_1_cover.jpg",
        job_dir / "composed_clip_0.mp4",
        job_dir / "subtitle_clip_0.ass",
    ]
    for path in deleted:
        path.write_bytes(b"x")
    survivor = job_dir / "video_clip_2.mp4"
    survivor.write_bytes(b"kept")
    queue = ManualPublishQueue(output, tmp_path / "data" / "manual_publish_queue.json")
    queued = queue.enqueue(
        job_id=VALID_UUID, clip_index=0, source_path=deleted[0], title="gone",
        caption="caption", source_platform="kick", source_channel="channel",
        source_kind="live", project_title="project",
    )

    result = hs.delete_history_clip(str(output), VALID_UUID, 0, queue)

    assert result == {"project_deleted": False, "remaining": 1}
    assert all(not path.exists() for path in deleted)
    assert not (output.parent / queued["artifact"]).exists()
    assert queue.list_entries("all") == []
    assert not metadata_path.with_suffix(metadata_path.suffix + ".tmp").exists()
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["shorts"] == [
        {"video_url": f"/videos/{VALID_UUID}/video_clip_2.mp4", "title": "kept"}
    ]
    assert resolve_clip(VALID_UUID, 0, str(output)).clip_path == str(survivor)


def test_delete_last_history_clip_removes_only_exact_project_and_all_job_queue_records(tmp_path):
    output = tmp_path / "output"
    job_dir = output / VALID_UUID
    other_dir = output / VALID_UUID_2
    job_dir.mkdir(parents=True)
    other_dir.mkdir(parents=True)
    (job_dir / "video_metadata.json").write_text(
        json.dumps({"shorts": [{"video_url": f"/videos/{VALID_UUID}/video_clip_1.mp4"}]}),
        encoding="utf-8",
    )
    clip = job_dir / "video_clip_1.mp4"
    clip.write_bytes(b"x")
    (other_dir / "sentinel").write_text("safe", encoding="utf-8")
    queue = ManualPublishQueue(output, tmp_path / "data" / "manual_publish_queue.json")
    queue.enqueue(
        job_id=VALID_UUID, clip_index=0, source_path=clip, title="one", caption="caption",
        source_platform="kick", source_channel="channel", source_kind="live",
        project_title="project",
    )

    assert hs.delete_history_clip(str(output), VALID_UUID, 0, queue) == {
        "project_deleted": True, "remaining": 0,
    }
    assert not job_dir.exists()
    assert (other_dir / "sentinel").read_text(encoding="utf-8") == "safe"
    assert queue.list_entries("all") == []


@pytest.mark.parametrize("job_id", ["../escape", VALID_UUID.upper(), None])
def test_delete_history_clip_rejects_invalid_job_id(tmp_path, job_id):
    queue = ManualPublishQueue(tmp_path / "output", tmp_path / "queue.json")
    with pytest.raises(ValidationError):
        hs.delete_history_clip(str(tmp_path / "output"), job_id, 0, queue)


@pytest.mark.parametrize("clip_index", [-1, True, "0"])
def test_delete_history_clip_rejects_invalid_clip_index(tmp_path, clip_index):
    queue = ManualPublishQueue(tmp_path / "output", tmp_path / "queue.json")
    with pytest.raises(ValidationError):
        hs.delete_history_clip(str(tmp_path / "output"), VALID_UUID, clip_index, queue)


def test_delete_history_clip_rejects_missing_clip(tmp_path):
    output = tmp_path / "output"
    _make_job(str(output), VALID_UUID, clips=[])
    queue = ManualPublishQueue(output, tmp_path / "queue.json")
    with pytest.raises(NotFoundError):
        hs.delete_history_clip(str(output), VALID_UUID, 0, queue)
