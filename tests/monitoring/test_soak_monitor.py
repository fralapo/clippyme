"""Accelerated monitor soak validation without sleeping or network calls."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "soak_live_monitor.py"
spec = importlib.util.spec_from_file_location("clippyme_monitor_soak", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_soak_detects_disconnect_queue_growth_and_failed_publications():
    batches = [
        {"monitors": [{"id": "kick:channel", "running": True, "state": "recording",
                       "pending_publish": 1, "failed_publish": 0, "clips_published": 3}]},
        {"monitors": [{"id": "kick:channel", "running": False, "state": "disconnected",
                       "pending_publish": 60, "failed_publish": 1, "clips_published": 3}]},
    ]
    iter_batches = iter(batches)
    sleeps = []
    rows = mod.run_probe(lambda: next(iter_batches), samples=2, interval=5,
                         queue_limit=50, pause=sleeps.append)
    assert sleeps == [5]
    assert len(rows[1]["warnings"]) == 3
    assert any("stopped" in warning for warning in rows[1]["warnings"])


def test_normal_recovery_does_not_generate_false_warnings():
    before = [{"id": "twitch:user", "running": True, "state": "offline",
               "pending": 1, "failed": 0, "published": 0, "segments": 0}]
    after = [{**before[0], "state": "recording", "pending": 0, "published": 1}]
    assert mod.anomalies(before, after, queue_limit=50) == []
