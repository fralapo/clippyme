"""Host-testable guards for the review-round concurrency / memory fixes.

Covers two pure (no cv2/ffmpeg) fixes:
  * ``job_worker.enqueue_output`` caps the per-job log buffer at
    ``MAX_LOG_LINES`` so a verbose/long job can't grow it without bound
    (the list is also returned verbatim on every 2s status poll).
  * ``smartcut._clip_lock`` never evicts a lock that another caller may
    still hold — handing two callers different locks for one path would
    defeat the per-clip mutex and let two renders clobber one output file.
"""
import io
import threading

import clippyme.domain.job_worker as job_worker
from clippyme.domain.smartcut import _CLIP_LOCKS, _clip_lock


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


def test_clip_lock_same_path_same_object():
    a = _clip_lock("/tmp/clip_same.mp4")
    b = _clip_lock("/tmp/clip_same.mp4")
    assert a is b


def test_clip_lock_does_not_evict_held_lock():
    """Overflow the registry while one path's lock is held; the held lock
    must remain the *same* object on a re-fetch (eviction skipped it)."""
    held_path = "/tmp/clip_held.mp4"
    held = _clip_lock(held_path)
    with held:  # lock is now busy → must never be evicted
        # Force the registry well past the 256 cap with fresh free locks.
        for i in range(400):
            _clip_lock(f"/tmp/clip_overflow_{i}.mp4")
        # Same path must still map to the same held lock object.
        assert _clip_lock(held_path) is held
    # Registry stays bounded after the held lock is released.
    assert len(_CLIP_LOCKS) <= 256 + 1
