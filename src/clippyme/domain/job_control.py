"""Job control: pause / resume / graceful-stop state machine + process-tree signalling.

Two layers:

* **Pure transition guards** (``can_pause`` / ``can_resume`` / ``can_stop`` /
  ``can_cancel`` / ``should_skip_dispatch``) — no I/O, host-unit-tested. They
  encode the one source of truth for which control action is legal in a given
  job status, so the FastAPI handlers stay thin (validate → guard → act).
* **psutil process-tree helpers** (``suspend_tree`` / ``resume_tree``) — need a
  live OS process tree, so they're exercised by the Docker integration suite,
  not host unit tests. ``psutil`` is already a dependency (hardware.py) and is
  cross-platform: ``suspend()``/``resume()`` map to SIGSTOP/SIGCONT on Linux
  and SuspendThread/ResumeThread on Windows — unlike ``os.kill(pid, SIGSTOP)``
  which does not exist on Windows.

Status vocabulary (stringly-typed on the in-memory ``jobs`` dict, matching the
rest of ``app.py``):

    queued → processing ⇄ paused → {completed, failed, cancelled, stopped}

``cancelled`` discards all output (hard kill + rmtree). ``stopped`` is the
graceful variant: kill the subprocess but KEEP whatever clips already rendered,
promoting the partial result to final so the user can view/edit them.
"""
import logging

logger = logging.getLogger("clippyme")

# Non-terminal states a job can be in while its subprocess is alive.
ACTIVE_STATES = ("queued", "processing", "paused")
# Terminal states. ``stopped`` is terminal-with-clips (graceful early stop).
TERMINAL_STATES = ("completed", "failed", "cancelled", "stopped")


def can_pause(status: str) -> bool:
    """Pause is only meaningful for a job actively running a subprocess."""
    return status == "processing"


def can_resume(status: str) -> bool:
    return status == "paused"


def can_stop(status: str) -> bool:
    """Graceful stop (keep finished clips) — valid while running or queued."""
    return status in ("processing", "paused", "queued")


def can_cancel(status: str) -> bool:
    """Hard cancel (discard output) — valid while running or queued."""
    return status in ("processing", "paused", "queued")


def should_skip_dispatch(status: str) -> bool:
    """True if a job pulled off the queue was already terminated while queued.

    Closes the race where ``POST /api/cancel`` (or ``/stop``) flips a still-
    ``queued`` job to a terminal state before the dispatcher launches it — the
    worker must NOT start a subprocess for an already-cancelled/stopped job.
    """
    return status in TERMINAL_STATES


def suspend_tree(pid: int) -> int:
    """Suspend the whole process tree rooted at ``pid``. Returns count suspended.

    Children first, then the parent, so the parent can't fork a fresh child in
    the window between us listing and suspending it. Best-effort per process —
    a child that already exited is skipped, not fatal.
    """
    import psutil

    parent = psutil.Process(pid)
    targets = parent.children(recursive=True) + [parent]
    suspended = 0
    for proc in targets:
        try:
            proc.suspend()
            suspended += 1
        except Exception as exc:  # already dead / access denied
            logger.warning("suspend pid=%s failed: %s", getattr(proc, "pid", "?"), exc)
    return suspended


def resume_tree(pid: int) -> int:
    """Resume the whole process tree rooted at ``pid``. Returns count resumed.

    Parent first, then children — the inverse order of :func:`suspend_tree`.
    """
    import psutil

    parent = psutil.Process(pid)
    targets = [parent] + parent.children(recursive=True)
    resumed = 0
    for proc in targets:
        try:
            proc.resume()
            resumed += 1
        except Exception as exc:
            logger.warning("resume pid=%s failed: %s", getattr(proc, "pid", "?"), exc)
    return resumed
