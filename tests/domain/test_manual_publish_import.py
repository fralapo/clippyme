"""Tests for the idempotent existing-clip importer (Task 3b2).

Scans job dirs under a ManualPublishQueue's output_dir and enqueues any extant
final clip that has no successful ``published`` record and no existing
manual-queue entry, grouping it by platform/channel derived from the
download-time ``source_info`` sidecar (falling back to "unknown").
"""
import json
import os

import pytest

from clippyme.domain.manual_publish_queue import ManualPublishQueue, import_existing_clips

JOB_A = "11111111-1111-4111-8111-111111111111"
JOB_B = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def queue(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    return ManualPublishQueue(output, tmp_path / "data" / "manual_publish_queue.json")


def _make_job(queue, job_id, *, clips, source_info=None, base_name="video"):
    job_dir = queue.output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    meta = {"shorts": clips}
    if source_info is not None:
        meta["source_info"] = source_info
    (job_dir / f"{base_name}_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    for i in range(len(clips)):
        (job_dir / f"{base_name}_clip_{i + 1}.mp4").write_bytes(b"video")
    return job_dir


def test_imports_unpublished_clip_with_platform_channel_grouping(queue):
    _make_job(
        queue, JOB_A,
        clips=[{"start": 0, "end": 10, "video_title_for_youtube_short": "Hi"}],
        source_info={"channel_url": "https://kick.com/grenbaud", "uploader_id": "grenbaud"},
    )

    imported = import_existing_clips(queue)

    assert len(imported) == 1
    entry = imported[0]
    assert entry["job_id"] == JOB_A
    assert entry["clip_index"] == 0
    assert entry["source_platform"] == "kick"
    assert entry["source_channel"] == "grenbaud"
    assert entry["title"] == "Hi"
    pending = queue.list_entries("all")
    assert len(pending) == 1


def test_imports_with_unknown_fallback_when_no_source_info(queue):
    _make_job(queue, JOB_A, clips=[{"start": 0, "end": 10}])

    imported = import_existing_clips(queue)

    assert len(imported) == 1
    assert imported[0]["source_platform"] == "unknown"
    assert imported[0]["source_channel"] == "unknown"


def test_skips_clip_with_non_empty_published_list(queue):
    _make_job(queue, JOB_A, clips=[
        {"start": 0, "end": 10, "published": [{"platform": "tiktok"}]},
        {"start": 10, "end": 20},
    ])

    imported = import_existing_clips(queue)

    assert len(imported) == 1
    assert imported[0]["clip_index"] == 1


def test_skips_clip_already_in_queue(queue):
    _make_job(queue, JOB_A, clips=[{"start": 0, "end": 10}])
    source = queue.output_dir / JOB_A / "video_clip_1.mp4"
    queue.enqueue(
        job_id=JOB_A, clip_index=0, source_path=source, title="t", caption="c",
        source_platform="kick", source_channel="grenbaud", source_kind="live",
        project_title="Stream",
    )

    imported = import_existing_clips(queue)

    assert imported == []
    assert len(queue.list_entries("all")) == 1


def test_second_run_is_a_noop(queue):
    _make_job(queue, JOB_A, clips=[{"start": 0, "end": 10}])

    first = import_existing_clips(queue)
    second = import_existing_clips(queue)

    assert len(first) == 1
    assert second == []
    assert len(queue.list_entries("all")) == 1


def test_corrupt_metadata_for_one_job_does_not_abort_others(queue):
    bad_dir = queue.output_dir / JOB_A
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "video_metadata.json").write_text("{not json", encoding="utf-8")
    _make_job(queue, JOB_B, clips=[{"start": 0, "end": 10}])

    imported = import_existing_clips(queue)

    assert len(imported) == 1
    assert imported[0]["job_id"] == JOB_B


def test_skips_job_opted_into_zernio_via_sidecar(queue):
    from clippyme.domain.job_submission import write_publisher_mode

    job_dir = _make_job(queue, JOB_A, clips=[{"start": 0, "end": 10}])
    write_publisher_mode(str(job_dir), "zernio")
    _make_job(queue, JOB_B, clips=[{"start": 0, "end": 10}])

    imported = import_existing_clips(queue)

    assert len(imported) == 1
    assert imported[0]["job_id"] == JOB_B


def test_missing_sidecar_is_imported_as_legacy_default(queue):
    _make_job(queue, JOB_A, clips=[{"start": 0, "end": 10}])
    # No publisher_mode.json written at all — legacy job predating this feature.

    imported = import_existing_clips(queue)

    assert len(imported) == 1
    assert imported[0]["job_id"] == JOB_A


def test_missing_clip_file_is_not_imported(queue):
    job_dir = queue.output_dir / JOB_A
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "video_metadata.json").write_text(
        json.dumps({"shorts": [{"start": 0, "end": 10}]}), encoding="utf-8")
    # No clip mp4 written on disk.

    imported = import_existing_clips(queue)

    assert imported == []
