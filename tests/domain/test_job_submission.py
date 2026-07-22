"""Host tests for clippyme.domain.job_submission — enqueue + queue-full rollback."""
import asyncio
import json

import pytest

from clippyme.domain.job_submission import (
    QueueFullError,
    read_publisher_mode,
    submit_job,
    write_publisher_mode,
)

JOB_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
JOB_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_submit_registers_entry_and_enqueues(tmp_path):
    async def run():
        jobs, q = {}, asyncio.Queue(maxsize=2)
        out = tmp_path / JOB_A
        out.mkdir()
        await submit_job(jobs=jobs, job_queue=q, job_id=JOB_A,
                         cmd=["x"], env={"K": "v"}, job_output_dir=str(out))
        return jobs, q

    jobs, q = asyncio.run(run())
    assert jobs[JOB_A]["status"] == "queued"
    assert jobs[JOB_A]["cmd"] == ["x"]
    assert q.get_nowait() == JOB_A


def test_batch_flag_changes_log_line(tmp_path):
    async def run():
        jobs, q = {}, asyncio.Queue(maxsize=2)
        out = tmp_path / JOB_A
        out.mkdir()
        await submit_job(jobs=jobs, job_queue=q, job_id=JOB_A,
                         cmd=["x"], env={}, job_output_dir=str(out), batch=True)
        return jobs

    jobs = asyncio.run(run())
    assert "(batch)" in jobs[JOB_A]["logs"][0]


def test_queue_full_rolls_back_entry_and_output_dir(tmp_path):
    async def run():
        jobs, q = {}, asyncio.Queue(maxsize=1)
        out_a, out_b = tmp_path / JOB_A, tmp_path / JOB_B
        out_a.mkdir()
        out_b.mkdir()
        await submit_job(jobs=jobs, job_queue=q, job_id=JOB_A,
                         cmd=["x"], env={}, job_output_dir=str(out_a))
        with pytest.raises(QueueFullError):
            await submit_job(jobs=jobs, job_queue=q, job_id=JOB_B,
                             cmd=["y"], env={}, job_output_dir=str(out_b))
        return jobs, out_a, out_b

    jobs, out_a, out_b = asyncio.run(run())
    # The rejected job was fully rolled back; the accepted one is untouched.
    assert JOB_B not in jobs
    assert not out_b.exists()
    assert jobs[JOB_A]["status"] == "queued"
    assert out_a.exists()


def test_queue_full_maps_to_429():
    assert QueueFullError("busy").status_code == 429


def test_on_change_hook_called_after_enqueue(tmp_path):
    calls = []

    async def run():
        jobs, q = {}, asyncio.Queue(maxsize=1)
        out = tmp_path / JOB_A
        out.mkdir()
        await submit_job(jobs=jobs, job_queue=q, job_id=JOB_A,
                         cmd=["x"], env={}, job_output_dir=str(out),
                         on_change=lambda: calls.append(1))

    asyncio.run(run())
    assert calls == [1]


def test_submit_writes_manual_queue_sidecar_by_default(tmp_path):
    async def run():
        jobs, q = {}, asyncio.Queue(maxsize=1)
        out = tmp_path / JOB_A
        out.mkdir()
        await submit_job(jobs=jobs, job_queue=q, job_id=JOB_A,
                         cmd=["x"], env={}, job_output_dir=str(out))
        return out

    out = asyncio.run(run())
    payload = json.loads((out / "publisher_mode.json").read_text(encoding="utf-8"))
    assert payload == {"publisher_mode": "manual_queue"}


def test_submit_writes_zernio_sidecar_when_requested(tmp_path):
    async def run():
        jobs, q = {}, asyncio.Queue(maxsize=1)
        out = tmp_path / JOB_A
        out.mkdir()
        await submit_job(jobs=jobs, job_queue=q, job_id=JOB_A,
                         cmd=["x"], env={}, job_output_dir=str(out),
                         publisher_mode="zernio")
        return out

    out = asyncio.run(run())
    assert read_publisher_mode(str(out)) == "zernio"


def test_submit_sidecar_atomic_write_leaves_no_tmp_file(tmp_path):
    out = tmp_path / JOB_A
    out.mkdir()
    write_publisher_mode(str(out), "manual_queue")
    assert not (out / "publisher_mode.json.tmp").exists()
    assert (out / "publisher_mode.json").exists()


def test_read_publisher_mode_defaults_when_sidecar_missing(tmp_path):
    out = tmp_path / JOB_A
    out.mkdir()
    assert read_publisher_mode(str(out)) == "manual_queue"


def test_read_publisher_mode_defaults_when_sidecar_corrupt(tmp_path):
    out = tmp_path / JOB_A
    out.mkdir()
    (out / "publisher_mode.json").write_text("{not json", encoding="utf-8")
    assert read_publisher_mode(str(out)) == "manual_queue"


def test_write_publisher_mode_rejects_unknown_value_as_manual_queue(tmp_path):
    out = tmp_path / JOB_A
    out.mkdir()
    write_publisher_mode(str(out), "dropbox")
    assert read_publisher_mode(str(out)) == "manual_queue"
