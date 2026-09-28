"""End-to-end restart lifecycle: graceful shutdown must leave a job resumable.

Drives the real runner, worker dispatcher, job journal and startup recovery
against a real subprocess that checkpoints through ``RuntimeState`` — the same
contract the pipeline orchestrator uses. Each "server life" is a separate
event loop with a fresh in-memory registry, exactly like a process restart;
only the journal file and the job directory survive between lives.
"""
import asyncio
import json
import os
import sys
import time

import psutil

from clippyme.domain import job_journal as jj
from clippyme.domain.job_runner import make_run_job
from clippyme.domain.job_worker import make_workers
from clippyme.domain.runtime_state import load_runtime_state

JOB_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"

# Stand-in for the orchestrator: three checkpointed stages; "transcribing"
# blocks until a release file exists so the test can shut the server down
# mid-stage. Every executed/skipped stage is appended to trace.log.
FAKE_PIPELINE = r'''
import json, os, sys, time
from clippyme.domain.runtime_state import RuntimeState

out = sys.argv[1]
state = RuntimeState(out, job_id=os.environ["CLIPPYME_JOB_ID"])
state.begin_attempt(int(os.environ["CLIPPYME_ATTEMPT"]),
                    int(os.environ["CLIPPYME_JOB_MAX_ATTEMPTS"]))


def trace(line):
    with open(os.path.join(out, "trace.log"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


for stage in ("acquiring", "transcribing", "rendering"):
    if state.completed(stage):
        trace("skip:" + stage)
        continue
    state.start(stage)
    trace("run:" + stage)
    if stage == "transcribing":
        while not os.path.exists(os.path.join(out, "release")):
            time.sleep(0.05)
    if stage == "rendering":
        with open(os.path.join(out, "demo_clip_1.mp4"), "wb") as fh:
            fh.write(b"\x00" * 16)
        with open(os.path.join(out, "demo_metadata.json"), "w", encoding="utf-8") as fh:
            json.dump({"shorts": [{"start": 0, "end": 5}]}, fh)
    state.complete_stage(stage)
state.finish()
'''


def _trace(output_dir):
    try:
        with open(os.path.join(output_dir, "trace.log"), encoding="utf-8") as fh:
            return [line.strip() for line in fh if line.strip()]
    except FileNotFoundError:
        return []


async def _wait_for(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not reached before timeout")


class _Server:
    """One server life: shared registry + dispatcher, like app.lifespan."""

    def __init__(self, root, journal):
        self.root = root
        self.journal = journal
        self.jobs = {}
        self.queue = asyncio.Queue(maxsize=10)
        persist = jj.make_journal_writer(jobs=self.jobs, path=journal)
        run_job = make_run_job(jobs=self.jobs, output_root=root, on_change=persist)
        _, process_queue, _ = make_workers(
            jobs=self.jobs, job_queue=self.queue,
            concurrency_semaphore=asyncio.Semaphore(1), run_job=run_job,
            output_dir=root, upload_dir=root, data_dir=root,
            job_retention_seconds=0, max_concurrent_jobs=1,
        )
        self.persist = persist
        self._process_queue = process_queue
        self.worker = None

    def recover(self):
        return jj.recover_jobs(journal_path=self.journal, jobs=self.jobs,
                               job_queue=self.queue, output_root=self.root)

    def boot(self):
        self.worker = asyncio.create_task(self._process_queue())

    async def graceful_shutdown(self):
        # Mirrors app.lifespan teardown: cancel the dispatcher, which cancels
        # and awaits every in-flight job task.
        self.worker.cancel()
        try:
            await self.worker
        except asyncio.CancelledError:
            pass


def _setup(tmp_path):
    root = tmp_path / "output"
    output_dir = root / JOB_ID
    output_dir.mkdir(parents=True)
    script = tmp_path / "fake_pipeline.py"
    script.write_text(FAKE_PIPELINE, encoding="utf-8")
    upload = tmp_path / "upload.mp4"
    upload.write_bytes(b"source")
    return str(root), str(output_dir), str(script), str(upload), str(tmp_path / "jobs_journal.json")


def _assert_resumable_in_journal(journal, output_dir):
    record = jj.load_journal(journal).get(JOB_ID)
    assert record is not None, "graceful shutdown dropped the job from the journal"
    assert record["status"] == "processing"
    assert record["attempt"] == 0, "shutdown must not consume the retry budget"
    assert record["pid"] is None
    state = load_runtime_state(output_dir)
    assert state["resumable"] is True and state["stage"] == "transcribing"


def test_graceful_shutdown_twice_then_resume_to_completion(tmp_path):
    root, output_dir, script, upload, journal = _setup(tmp_path)
    pids = []

    async def first_life():
        server = _Server(root, journal)
        server.jobs[JOB_ID] = {
            "status": "queued", "logs": [], "result": None,
            "cmd": [sys.executable, "-u", script, output_dir],
            "env": dict(os.environ), "output_dir": output_dir,
            "input_path": upload,
            # One attempt only: any shutdown charged against the budget would
            # make the final life fail with "Retry budget already exhausted".
            "max_attempts": 1,
        }
        server.persist()
        server.queue.put_nowait(JOB_ID)
        server.boot()
        await _wait_for(lambda: _trace(output_dir).count("run:transcribing") == 1
                        and server.jobs[JOB_ID].get("pid"))
        pids.append(psutil.Process(server.jobs[JOB_ID]["pid"]))
        await server.graceful_shutdown()
        assert server.jobs[JOB_ID]["status"] == "processing"

    async def interrupted_life(expected_runs):
        server = _Server(root, journal)
        assert server.recover() == {"requeued": 0, "resumed": 1, "failed": 0, "restored": 0}
        assert server.jobs[JOB_ID]["status"] == "queued"
        server.boot()
        await _wait_for(lambda: _trace(output_dir).count("run:transcribing") == expected_runs
                        and server.jobs[JOB_ID].get("pid"))
        pids.append(psutil.Process(server.jobs[JOB_ID]["pid"]))
        await server.graceful_shutdown()

    async def final_life():
        server = _Server(root, journal)
        assert server.recover()["resumed"] == 1
        server.boot()
        await _wait_for(lambda: server.jobs[JOB_ID]["status"] in ("completed", "failed"))
        job = server.jobs[JOB_ID]
        await server.graceful_shutdown()
        return job

    asyncio.run(first_life())
    _assert_resumable_in_journal(journal, output_dir)

    asyncio.run(interrupted_life(expected_runs=2))
    _assert_resumable_in_journal(journal, output_dir)

    (tmp_path / "output" / JOB_ID / "release").write_text("go")
    job = asyncio.run(final_life())

    assert job["status"] == "completed", job["logs"]
    assert [clip["video_url"] for clip in job["result"]["clips"]] == [
        f"/videos/{JOB_ID}/demo_clip_1.mp4"
    ]
    # Resumed from the checkpoint: acquisition ran once, the interrupted stage
    # re-ran, rendering (the output-producing stage) ran exactly once.
    assert _trace(output_dir) == [
        "run:acquiring", "run:transcribing",
        "skip:acquiring", "run:transcribing",
        "skip:acquiring", "run:transcribing", "run:rendering",
    ]
    state = load_runtime_state(output_dir)
    assert state["stage"] == "completed" and state["resumable"] is False
    assert json.loads((tmp_path / "output" / JOB_ID / "demo_metadata.json").read_text()) == {
        "shorts": [{"start": 0, "end": 5}]
    }
    # Terminal jobs leave the journal; no pipeline process survived any life.
    assert jj.load_journal(journal) == {}
    # is_running() also compares create_time, so a recycled pid can't fool it.
    assert len(pids) == 2
    assert not any(p.is_running() and p.status() != psutil.STATUS_ZOMBIE for p in pids)
