"""Host tests for clippyme.domain.job_submission — enqueue + queue-full rollback."""
import asyncio

import pytest

from clippyme.domain.job_submission import QueueFullError, submit_job

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


def test_queue_full_removes_extra_cleanup_paths(tmp_path):
    async def run():
        jobs, queue = {}, asyncio.Queue(maxsize=1)
        accepted = tmp_path / "accepted"
        rejected = tmp_path / "rejected"
        upload = tmp_path / "upload.mp4"
        accepted.mkdir()
        rejected.mkdir()
        upload.write_bytes(b"partial")
        await submit_job(
            jobs=jobs, job_queue=queue, job_id=JOB_A,
            cmd=["x"], env={}, job_output_dir=str(accepted),
        )
        with pytest.raises(QueueFullError):
            await submit_job(
                jobs=jobs, job_queue=queue, job_id=JOB_B,
                cmd=["y"], env={}, job_output_dir=str(rejected),
                cleanup_paths=(str(upload),), input_path=str(upload),
            )
        return jobs, rejected, upload

    jobs, rejected, upload = asyncio.run(run())
    assert JOB_B not in jobs
    assert not rejected.exists()
    assert not upload.exists()


def test_submit_persists_input_path(tmp_path):
    async def run():
        jobs, queue = {}, asyncio.Queue(maxsize=1)
        output = tmp_path / JOB_A
        output.mkdir()
        upload = str(tmp_path / "input.mp4")
        await submit_job(
            jobs=jobs, job_queue=queue, job_id=JOB_A,
            cmd=["x"], env={}, job_output_dir=str(output), input_path=upload,
        )
        return jobs

    assert asyncio.run(run())[JOB_A]["input_path"].endswith("input.mp4")
