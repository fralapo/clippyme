"""Host-unit tests for the pure job-control transition guards.

The psutil ``suspend_tree``/``resume_tree`` helpers need a live process tree and
are covered by the Docker integration suite — only the I/O-free guards are
asserted here so they run under host ``pytest -m "not integration"``.
"""
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


def test_stopped_is_terminal_cancelled_discards():
    # Documents the contract relied on by run_job's post-loop handling.
    assert "stopped" in jc.TERMINAL_STATES
    assert "cancelled" in jc.TERMINAL_STATES
    assert "paused" in jc.ACTIVE_STATES
    assert "paused" not in jc.TERMINAL_STATES
