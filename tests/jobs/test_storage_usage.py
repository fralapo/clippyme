"""Disk usage scan is read-only and never follows filesystem symlinks."""
import os

from clippyme.jobs.storage_usage import folder_bytes, storage_overview

JOB = "12345678-1234-4123-8123-1234567890ab"


def test_storage_counts_real_jobs_and_skips_external_symlinks(tmp_path):
    output = tmp_path / "output"
    data = tmp_path / "data"
    uploads = tmp_path / "uploads"
    job = output / JOB
    job.mkdir(parents=True)
    data.mkdir()
    uploads.mkdir()
    (job / "one.mp4").write_bytes(b"x" * 100)
    (data / "config.json").write_text("{}")
    (uploads / "source.mp4").write_bytes(b"abc")
    (output / "untracked").mkdir()
    (output / "untracked" / "other.mp4").write_bytes(b"a" * 9)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "secret").write_bytes(b"z" * 999)
    (job / "escape").symlink_to(elsewhere, target_is_directory=True)
    overview = storage_overview(str(output), str(data), str(uploads))
    assert overview["outputBytes"] == 109
    assert overview["dataBytes"] == 2
    assert overview["uploadsBytes"] == 3
    assert overview["jobs"] == [{"jobId": JOB, "bytes": 100}]
    assert overview["diskFreeBytes"] <= overview["diskTotalBytes"]
    assert folder_bytes(job / "escape") == 0


def test_storage_missing_roots_are_accepted(tmp_path):
    output = tmp_path / "output"
    overview = storage_overview(str(output), str(tmp_path / "data"),
                                str(tmp_path / "uploads"))
    assert overview["jobs"] == []
    assert overview["outputBytes"] == 0
