"""Host-unit tests for the pure job-control transition guards.

The psutil ``suspend_tree``/``resume_tree`` helpers need a live process tree and
are covered by the Docker integration suite — only the I/O-free guards are
asserted here so they run under host ``pytest -m "not integration"``.
"""
import pytest

from clippyme.domain import job_control as jc


def test_can_pause_only_while_processing():
    assert jc.can_pause("processing") is True
    for s in ("queued", "paused", "completed", "failed", "cancelled", "stopped"):
        assert jc.can_pause(s) is False


def test_can_resume_only_while_paused():
    assert jc.can_resume("paused") is True
    for s in ("processing", "queued", "completed", "failed", "cancelled", "stopped"):
        assert jc.can_resume(s) is False


def test_can_stop_while_active():
    for s in ("processing", "paused", "queued"):
        assert jc.can_stop(s) is True
    for s in ("completed", "failed", "cancelled", "stopped"):
        assert jc.can_stop(s) is False


def test_can_cancel_while_active():
    for s in ("processing", "paused", "queued"):
        assert jc.can_cancel(s) is True
    for s in ("completed", "failed", "cancelled", "stopped"):
        assert jc.can_cancel(s) is False


def test_should_skip_dispatch_for_terminal_states():
    for s in jc.TERMINAL_STATES:
        assert jc.should_skip_dispatch(s) is True
    for s in ("queued", "processing", "paused"):
        assert jc.should_skip_dispatch(s) is False


def test_can_purge_blocks_active_jobs():
    # The retention sweep must never rmtree a live job's output dir: mtime
    # only updates on entry add/remove, so a long-paused job looks stale.
    for s in jc.ACTIVE_STATES:
        assert jc.can_purge(s) is False
    for s in jc.TERMINAL_STATES:
        assert jc.can_purge(s) is True
    assert jc.can_purge(None) is True  # unknown to the in-memory dict


def test_stopped_is_terminal_cancelled_discards():
    # Documents the contract relied on by run_job's post-loop handling.
    assert "stopped" in jc.TERMINAL_STATES
    assert "cancelled" in jc.TERMINAL_STATES
    assert "paused" in jc.ACTIVE_STATES
    assert "paused" not in jc.TERMINAL_STATES


def test_terminate_tree_escalates_survivors(monkeypatch):
    import sys
    from types import SimpleNamespace

    calls = []

    class NoSuchProcess(Exception):
        pass

    class AccessDenied(Exception):
        pass

    class Proc:
        def __init__(self, pid):
            self.pid = pid

        def children(self, recursive=True):
            return [child] if self.pid == 1 else []

        def resume(self):
            calls.append(("resume", self.pid))

        def terminate(self):
            calls.append(("terminate", self.pid))

        def kill(self):
            calls.append(("kill", self.pid))

    parent = Proc(1)
    child = Proc(2)
    waits = iter([([child], [parent]), ([parent], [])])
    fake = SimpleNamespace(
        Process=lambda pid: parent,
        NoSuchProcess=NoSuchProcess,
        AccessDenied=AccessDenied,
        wait_procs=lambda procs, timeout: next(waits),
    )
    monkeypatch.setitem(sys.modules, "psutil", fake)
    assert jc.terminate_tree(1, timeout=0.01) == 2
    assert calls.index(("terminate", 2)) < calls.index(("terminate", 1))
    assert ("kill", 1) in calls


def test_terminate_tree_raises_when_process_survives_kill(monkeypatch):
    import sys
    from types import SimpleNamespace

    class NoSuchProcess(Exception):
        pass

    class AccessDenied(Exception):
        pass

    class Proc:
        pid = 1

        def children(self, recursive=True):
            return []

        def resume(self):
            return None

        def terminate(self):
            return None

        def kill(self):
            return None

    proc = Proc()
    fake = SimpleNamespace(
        Process=lambda pid: proc,
        NoSuchProcess=NoSuchProcess,
        AccessDenied=AccessDenied,
        wait_procs=lambda procs, timeout: ([], [proc]),
    )
    monkeypatch.setitem(sys.modules, "psutil", fake)
    with pytest.raises(jc.ProcessTreeTerminationError):
        jc.terminate_tree(1, timeout=0.01)
