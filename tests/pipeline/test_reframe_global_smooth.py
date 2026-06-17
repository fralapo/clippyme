"""Integration test for the opt-in two-stage global-smoothing reframe path.

Heavy (imports cv2 + the reframe stack, writes/encodes video), so it is marked
`integration` and runs only in the Docker suite, not on the host.

We drive `process_video_to_vertical` end-to-end with REFRAME_GLOBAL_SMOOTH=1 on
a tiny synthetic 16:9 clip and assert it produces a valid 9:16 output without
crashing. This exercises the pass-1 trajectory recording, the savgol smoothing
glue (`build_smoothed_trajectory`), and the pass-2 render — the wiring that the
host-side pure-math tests in test_reframe_ops.py cannot reach.
"""
import os

import pytest

pytestmark = pytest.mark.integration

# reframe pulls cv2/scenedetect/mediapipe/torch at import time. The host often
# has a partial/broken CV runtime (e.g. a mediapipe wheel missing `solutions`),
# so guard the whole module behind the real import — it runs in the Docker
# backend image where the stack is complete.
try:
    import cv2
    import numpy as np

    from clippyme.pipeline import reframe
except Exception:  # pragma: no cover - host without the full CV runtime
    pytest.skip("heavy CV runtime unavailable", allow_module_level=True)


def _make_synthetic_clip(path, width=640, height=360, n_frames=45, fps=30):
    """A moving white rectangle on black — enough to drive scene detection and
    the frame loop without needing a real face."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (width, height))
    for i in range(n_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        x = int((width - 80) * (i / max(1, n_frames - 1)))
        cv2.rectangle(frame, (x, 120), (x + 80, 240), (255, 255, 255), -1)
        writer.write(frame)
    writer.release()


def test_global_smooth_path_produces_valid_vertical(tmp_path, monkeypatch):
    src = str(tmp_path / "src.mp4")
    out = str(tmp_path / "out.mp4")
    _make_synthetic_clip(src)

    monkeypatch.setenv("REFRAME_GLOBAL_SMOOTH", "1")
    monkeypatch.setattr(reframe, "ASPECT_RATIO", 9 / 16)

    ok = reframe.process_video_to_vertical(src, out, reframe_mode="auto")
    assert ok is True
    assert os.path.exists(out)

    cap = cv2.VideoCapture(out)
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()

    # Vertical (taller than wide) and non-empty.
    assert h > w
    assert frames > 0


def test_global_smooth_matches_singlepass_frame_count(tmp_path, monkeypatch):
    """The two-stage path must emit the same number of frames as the default
    single-pass path — i.e. it drops/duplicates nothing."""
    src = str(tmp_path / "src.mp4")
    _make_synthetic_clip(src)
    monkeypatch.setattr(reframe, "ASPECT_RATIO", 9 / 16)

    def _count(out_path, global_smooth):
        if global_smooth:
            monkeypatch.setenv("REFRAME_GLOBAL_SMOOTH", "1")
        else:
            monkeypatch.delenv("REFRAME_GLOBAL_SMOOTH", raising=False)
        assert reframe.process_video_to_vertical(src, out_path, reframe_mode="auto")
        cap = cv2.VideoCapture(out_path)
        try:
            return int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        finally:
            cap.release()

    single = _count(str(tmp_path / "single.mp4"), global_smooth=False)
    two = _count(str(tmp_path / "two.mp4"), global_smooth=True)
    assert single == two
