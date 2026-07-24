"""Tests for clippyme.domain.job_worker helpers.

The log-reader thread feeds the job's user-visible log list. It must survive
non-UTF-8 bytes on the subprocess stream: before the fix, one bad byte raised
UnicodeDecodeError, the outer except ended the read loop, and the job's log
froze for the rest of the run while the subprocess kept working.
"""
import io
import os

from clippyme.domain.job_worker import MAX_LOG_LINES, active_input_paths, enqueue_output


def _run(stream_bytes, job_id="j", jobs=None):
    jobs = jobs if jobs is not None else {job_id: {"logs": []}}
    enqueue_output(io.BytesIO(stream_bytes), job_id, jobs)
    return jobs


def test_plain_lines_are_appended():
    jobs = _run(b"line one\nline two\n")
    assert jobs["j"]["logs"] == ["line one", "line two"]


def test_invalid_utf8_does_not_kill_the_reader():
    jobs = _run(b"good\n\xff\xfe mangled\nafter\n")
    logs = jobs["j"]["logs"]
    assert "good" in logs
    assert "after" in logs, "reader died on the invalid-UTF-8 line"
    assert any("mangled" in line for line in logs)


def test_blank_lines_are_skipped():
    jobs = _run(b"\n   \nreal\n")
    assert jobs["j"]["logs"] == ["real"]


def test_log_list_is_trimmed_to_max():
    payload = b"".join(b"l%d\n" % i for i in range(MAX_LOG_LINES + 50))
    jobs = _run(payload)
    logs = jobs["j"]["logs"]
    assert len(logs) == MAX_LOG_LINES
    assert logs[-1] == "l%d" % (MAX_LOG_LINES + 49)


def test_unknown_job_id_is_ignored():
    jobs = _run(b"orphan line\n", job_id="missing", jobs={"other": {"logs": []}})
    assert jobs["other"]["logs"] == []


def test_active_input_paths_only_protects_non_terminal_jobs(tmp_path):
    queued = tmp_path / "queued.mp4"
    processing = tmp_path / "processing.mp4"
    paused = tmp_path / "paused.mp4"
    completed = tmp_path / "completed.mp4"
    jobs = {
        "q": {"status": "queued", "input_path": str(queued)},
        "p": {"status": "processing", "input_path": str(processing)},
        "z": {"status": "paused", "input_path": str(paused)},
        "c": {"status": "completed", "input_path": str(completed)},
        "n": {"status": "processing", "input_path": None},
    }

    assert active_input_paths(jobs) == {
        os.path.abspath(queued),
        os.path.abspath(processing),
        os.path.abspath(paused),
    }


def test_dispatcher_shutdown_cancels_and_awaits_active_jobs(tmp_path):
    import asyncio

    async def scenario():
        from clippyme.domain.job_worker import make_workers

        jobs = {"j": {"status": "queued"}}
        queue = asyncio.Queue()
        semaphore = asyncio.Semaphore(1)
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def run_job(job_id, job):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        _, process_queue, _ = make_workers(
            jobs=jobs,
            job_queue=queue,
            concurrency_semaphore=semaphore,
            run_job=run_job,
            output_dir=str(tmp_path / "output"),
            upload_dir=str(tmp_path / "uploads"),
            data_dir=str(tmp_path / "data"),
            job_retention_seconds=0,
            max_concurrent_jobs=1,
        )
        queue.put_nowait("j")
        dispatcher = asyncio.create_task(process_queue())
        await asyncio.wait_for(started.wait(), timeout=1)
        dispatcher.cancel()
        try:
            await dispatcher
        except asyncio.CancelledError:
            pass
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        await asyncio.wait_for(queue.join(), timeout=1)
        assert semaphore._value == 1

    asyncio.run(scenario())
