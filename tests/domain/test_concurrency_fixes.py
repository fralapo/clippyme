"""Host-testable guards for the review-round concurrency / memory fixes.

Covers two pure (no cv2/ffmpeg) fixes:
  * ``job_worker.enqueue_output`` caps the per-job log buffer at
    ``MAX_LOG_LINES`` so a verbose/long job can't grow it without bound
    (the list is also returned verbatim on every 2s status poll).
  * ``smartcut._clip_lock`` is a reference-counted context manager: an entry
    survives exactly as long as some caller holds or waits on it, so eviction
    can never hand two callers different locks for one path (which would
    defeat the per-clip mutex and let two renders clobber one output file).
"""
import io
import os

import clippyme.jobs.job_worker as job_worker
from clippyme.editing.smartcut import _CLIP_LOCKS, _clip_lock


def test_enqueue_output_caps_log_buffer(monkeypatch):
    monkeypatch.setattr(job_worker, "MAX_LOG_LINES", 10)
    jobs = {"job1": {"logs": []}}
    # 100 lines in; only the last 10 should survive.
    payload = b"".join(f"line {i}\n".encode() for i in range(100))
    job_worker.enqueue_output(io.BytesIO(payload), "job1", jobs)
    logs = jobs["job1"]["logs"]
    assert len(logs) == 10
    assert logs[0] == "line 90"
    assert logs[-1] == "line 99"


def test_enqueue_output_unknown_job_is_noop():
    jobs = {}
    job_worker.enqueue_output(io.BytesIO(b"a\nb\n"), "missing", jobs)
    assert jobs == {}


def test_clip_lock_registry_identity_and_refcount():
    path = "/tmp/clip_identity.mp4"
    abs_path = os.path.abspath(path)
    with _clip_lock(path) as lock:
        entry = _CLIP_LOCKS.get(abs_path)
        assert entry is not None
        assert entry[0] is lock      # the yielded object is the registry lock
        assert entry[1] == 1         # exactly one holder counted
    # Refcount returns to zero after the `with` exits.
    entry = _CLIP_LOCKS.get(abs_path)
    if entry is not None:            # may have been evicted past the cap
        assert entry[1] == 0


def test_clip_lock_does_not_evict_held_entry():
    """While one path's lock is held, overflow the registry far past the 256
    cap with fresh free locks. The held entry must never be evicted — its
    lock object must stay identical on a re-check inside the `with`."""
    held_path = "/tmp/clip_held.mp4"
    abs_held = os.path.abspath(held_path)
    with _clip_lock(held_path) as held_lock:
        for i in range(400):
            # Each fresh path is acquired+released; with refcount back to 0 it
            # self-evicts once the registry is over the cap.
            with _clip_lock(f"/tmp/clip_overflow_{i}.mp4"):
                pass
        entry = _CLIP_LOCKS.get(abs_held)
        assert entry is not None         # held entry survived the eviction sweep
        assert entry[0] is held_lock     # same lock object — mutex intact
        assert entry[1] == 1
