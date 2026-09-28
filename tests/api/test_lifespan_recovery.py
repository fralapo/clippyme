"""The FastAPI lifespan wires restart recovery in the right order.

Startup: the job journal is recovered (queued jobs back in ``jobs`` and on the
queue) BEFORE the live monitors auto-resume — a monitor re-attaching to its
in-flight job must find it. Shutdown: the monitors stop BEFORE the worker
loops are cancelled, so their in-flight work unwinds first.

The real ``lifespan`` and ``recover_jobs`` run against a tmp journal; the
worker loops, the auto-editor updater and the monitor registry are stand-ins.
"""
import asyncio

from clippyme.api import app as app_module
from clippyme.domain import job_journal as jj
from clippyme.integrations import auto_editor_updater


def test_lifespan_recovers_jobs_before_monitors_and_stops_monitors_first(tmp_path, monkeypatch):
    out = tmp_path / "output"
    job_dir = out / "j1"
    job_dir.mkdir(parents=True)
    journal = tmp_path / "jobs_journal.json"
    jj.save_journal(str(journal), {"j1": {
        "status": "queued", "output_dir": str(job_dir),
        "cmd": ["python", "-m", "clippyme.pipeline.orchestrator", "-u", "https://x", "-o", str(job_dir)]}})
    jobs = {}
    events = []

    async def idle(name):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            events.append(f"{name} cancelled")
            raise

    def make_workers(**kwargs):
        return (lambda: idle("cleanup")), (lambda: idle("worker")), None

    class Monitors:
        async def auto_resume(self):
            events.append(("auto_resume sees", {k: v["status"] for k, v in jobs.items()}))

        async def shutdown(self):
            events.append("monitors shutdown")

    monkeypatch.setattr(app_module, "JOURNAL_PATH", str(journal))
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(out))
    monkeypatch.setattr(app_module, "jobs", jobs)
    monkeypatch.setattr(app_module, "make_workers", make_workers)
    monkeypatch.setattr(app_module, "live_monitor", Monitors())
    monkeypatch.setattr(auto_editor_updater, "background_updater_loop", lambda: idle("updater"))

    async def life():
        queue = asyncio.Queue()
        monkeypatch.setattr(app_module, "job_queue", queue)
        async with app_module.lifespan(app_module.app):
            assert queue.get_nowait() == "j1"
            await asyncio.sleep(0)  # yield once: the background loops start
            events.append("serving")

    asyncio.run(life())
    assert events[:3] == [("auto_resume sees", {"j1": "queued"}), "serving", "monitors shutdown"]
    assert sorted(events[3:]) == ["cleanup cancelled", "updater cancelled", "worker cancelled"]
