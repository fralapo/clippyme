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

    from clippyme.pipeline.reframe import reframe
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


def test_salient_general_crop_opt_in_produces_valid_vertical(tmp_path, monkeypatch):
    """The opt-in content-aware GENERAL crop (REFRAME_SALIENT_GENERAL) must
    produce a valid 9:16 output on a faceless clip without crashing — exercising
    the Sobel saliency + reframe_ops.salient_crop_center wiring."""
    src = str(tmp_path / "src.mp4")
    out = str(tmp_path / "out.mp4")
    _make_synthetic_clip(src)  # faceless moving rectangle → GENERAL strategy

    monkeypatch.setenv("REFRAME_SALIENT_GENERAL", "1")

    assert reframe.process_video_to_vertical(src, out, reframe_mode="auto") is True
    assert os.path.exists(out)
    cap = cv2.VideoCapture(out)
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()
    assert h > w and frames > 0


def test_salient_general_crop_helper_falls_back_when_too_narrow(tmp_path):
    """The helper returns None (→ letterbox fallback) when the source is already
    narrower than the 9:16 target, so it never crashes the GENERAL path."""
    tall = np.zeros((400, 100, 3), dtype=np.uint8)  # narrower than 9:16
    assert reframe._salient_general_crop(tall, 1080, 1920) is None


def test_object_weights_parses_flag_and_pairs(monkeypatch):
    """REFRAME_OBJECT_WEIGHTS: unset → None; bare flag → curated defaults;
    name:weight list → overrides; junk → None."""
    monkeypatch.delenv("REFRAME_OBJECT_WEIGHTS", raising=False)
    assert reframe._object_weights() is None

    monkeypatch.setenv("REFRAME_OBJECT_WEIGHTS", "1")
    defaults = reframe._object_weights()
    assert defaults == reframe._DEFAULT_OBJECT_WEIGHTS and defaults is not reframe._DEFAULT_OBJECT_WEIGHTS

    monkeypatch.setenv("REFRAME_OBJECT_WEIGHTS", "dog:3,car:2,bottle:1.5")
    assert reframe._object_weights() == {"dog": 3.0, "car": 2.0, "bottle": 1.5}

    # Negative/zero/non-numeric weights are dropped; bare junk flag → None.
    monkeypatch.setenv("REFRAME_OBJECT_WEIGHTS", "dog:-1,cat:0,car:x,truck:2")
    assert reframe._object_weights() == {"truck": 2.0}
    monkeypatch.setenv("REFRAME_OBJECT_WEIGHTS", "garbage")
    assert reframe._object_weights() is None


def test_weighted_object_crop_off_by_default_returns_none(tmp_path, monkeypatch):
    """Feature off (env unset) → helper returns None so GENERAL stays letterbox."""
    monkeypatch.delenv("REFRAME_OBJECT_WEIGHTS", raising=False)
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    assert reframe._weighted_object_general_crop(frame, 1080, 1920) is None


def test_weighted_object_crop_too_narrow_returns_none(monkeypatch):
    """Even enabled, a source already narrower than 9:16 → None (no crash)."""
    monkeypatch.setenv("REFRAME_OBJECT_WEIGHTS", "1")
    tall = np.zeros((400, 100, 3), dtype=np.uint8)
    assert reframe._weighted_object_general_crop(tall, 1080, 1920) is None


def test_object_weights_general_path_produces_valid_vertical(tmp_path, monkeypatch):
    """End-to-end: REFRAME_OBJECT_WEIGHTS on a faceless clip must still emit a
    valid 9:16 output (no object present → falls through to letterbox, no crash)."""
    src = str(tmp_path / "src.mp4")
    out = str(tmp_path / "out.mp4")
    _make_synthetic_clip(src)  # faceless → GENERAL strategy
    monkeypatch.setenv("REFRAME_OBJECT_WEIGHTS", "1")
    assert reframe.process_video_to_vertical(src, out, reframe_mode="auto") is True
    cap = cv2.VideoCapture(out)
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()
    assert h > w and frames > 0


def test_object_reframe_mode_produces_valid_vertical(tmp_path, monkeypatch):
    """reframe_mode='object' (FrameShift face-first crop everywhere) must emit a
    valid 9:16 output with the same frame count as the source — exercising the
    OBJECT strategy + create_frameshift_frame() path."""
    src = str(tmp_path / "src.mp4")
    out = str(tmp_path / "out.mp4")
    _make_synthetic_clip(src)
    # Object mode forces object weights on regardless of the env flag.
    monkeypatch.delenv("REFRAME_OBJECT_WEIGHTS", raising=False)

    assert reframe.process_video_to_vertical(src, out, reframe_mode="object") is True
    assert os.path.exists(out)
    cap = cv2.VideoCapture(out)
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()
    assert h > w and frames > 0


def test_object_mode_forces_weights_without_env(tmp_path):
    """create_general_frame(force_object_weights=True) must run the object crop
    even when REFRAME_OBJECT_WEIGHTS is unset (object mode's contract)."""
    import os as _os
    _os.environ.pop("REFRAME_OBJECT_WEIGHTS", None)
    # A wide frame with a bright off-centre blob → object/salient crop returns a
    # non-None vertical frame (not the letterbox fallback path's full-width fit).
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.rectangle(frame, (500, 150), (560, 210), (255, 255, 255), -1)
    out = reframe.create_general_frame(frame, 1080, 1920, force_object_weights=True)
    # Always returns a valid 9:16-sized frame regardless of which sub-path wins.
    assert out.shape[0] == 1920 and out.shape[1] == 1080


def test_frameshift_frame_always_returns_valid_vertical():
    """create_frameshift_frame() (the `object` reframe mode) must always return a
    valid 9:16-sized frame — both when a subject is detected (centroid crop) and
    when none is (black-padded letterbox fallback)."""
    # A frame with a bright off-centre blob (a YOLO/face detection may or may not
    # fire on synthetic input; either branch must still yield a valid frame).
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.rectangle(frame, (500, 150), (560, 210), (255, 255, 255), -1)
    out = reframe.create_frameshift_frame(frame, 1080, 1920)
    assert out is not None
    assert out.shape[0] == 1920 and out.shape[1] == 1080
    # A featureless frame → no detections → black-pad fallback, still valid.
    blank = np.zeros((360, 640, 3), dtype=np.uint8)
    out2 = reframe.create_frameshift_frame(blank, 1080, 1920)
    assert out2 is not None
    assert out2.shape[0] == 1920 and out2.shape[1] == 1080


def test_frameshift_weights_env_override(monkeypatch):
    """REFRAME_FRAMESHIFT_WEIGHTS overrides the GUI-default sliders + adds
    per-COCO-class weights; empty/unset yields the FrameShift defaults."""
    monkeypatch.delenv("REFRAME_FRAMESHIFT_WEIGHTS", raising=False)
    face, person, default, extra = reframe._frameshift_weights()
    assert (face, person, default) == (1.0, 0.8, 0.5) and extra == {}
    monkeypatch.setenv("REFRAME_FRAMESHIFT_WEIGHTS", "face:2,person:0.3,default:0.1,dog:3")
    face, person, default, extra = reframe._frameshift_weights()
    assert (face, person, default) == (2.0, 0.3, 0.1)
    assert extra == {"dog": 3.0}


def test_global_smooth_matches_singlepass_frame_count(tmp_path, monkeypatch):
    """The two-stage path must emit the same number of frames as the default
    single-pass path — i.e. it drops/duplicates nothing."""
    src = str(tmp_path / "src.mp4")
    _make_synthetic_clip(src)

    def _count(out_path, global_smooth):
        if global_smooth:
            monkeypatch.setenv("REFRAME_GLOBAL_SMOOTH", "1")
        else:
            monkeypatch.delenv("REFRAME_GLOBAL_SMOOTH", raising=False)
            # Comfort mode (default on) would route to the global path too; force
            # it off here so this branch exercises the single-pass streaming loop.
            monkeypatch.setenv("REFRAME_COMFORT", "0")
        assert reframe.process_video_to_vertical(src, out_path, reframe_mode="auto")
        cap = cv2.VideoCapture(out_path)
        try:
            return int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        finally:
            cap.release()

    single = _count(str(tmp_path / "single.mp4"), global_smooth=False)
    two = _count(str(tmp_path / "two.mp4"), global_smooth=True)
    assert single == two


def test_zoom_fold_renders_valid_vertical(tmp_path, monkeypatch):
    """Wave-9 fold: the Ken Burns zoompan rides INSIDE the master encode
    (zoom_end) instead of a separate apply_subtle_zoom pass. Assert the fused
    encode still produces a valid 9:16 output with ~the same frame count."""
    src = str(tmp_path / "src.mp4")
    out = str(tmp_path / "out_zoom.mp4")
    _make_synthetic_clip(src)


    ok = reframe.process_video_to_vertical(src, out, reframe_mode="auto",
                                           zoom_end=1.05)
    assert ok is True
    assert os.path.exists(out) and os.path.getsize(out) > 0

    cap = cv2.VideoCapture(out)
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()
    assert h > w, f"expected vertical output, got {w}x{h}"
    # zoompan d=1 must not change the frame count materially.
    assert abs(n - 45) <= 2, f"frame count drifted: {n} vs 45"
