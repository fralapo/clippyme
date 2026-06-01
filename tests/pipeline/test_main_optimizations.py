"""Tests for the main.py performance optimizations (Phase 2).

main.py imports cv2/scenedetect/mediapipe at module load, so this whole
module is skipped on hosts without the heavy CV runtime and runs inside the
Docker backend image.
"""
import pytest

pytest.importorskip("scenedetect")
pytestmark = pytest.mark.integration

from clippyme.pipeline import main as m


def test_whisper_model_is_cached_per_config(monkeypatch):
    """_get_whisper_model must construct a model once per (name, device,
    compute_type) and return the cached instance on subsequent calls."""
    calls = []

    class FakeModel:
        def __init__(self, name, device=None, compute_type=None):
            calls.append((name, device, compute_type))

    # faster_whisper is imported lazily inside _get_whisper_model.
    import faster_whisper
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    monkeypatch.setattr(m, "_whisper_models", {})

    a = m._get_whisper_model("base", "cpu", "int8")
    b = m._get_whisper_model("base", "cpu", "int8")
    assert a is b
    assert len(calls) == 1  # constructed exactly once

    # A different config constructs a second, distinct model.
    c = m._get_whisper_model("base", "cuda", "float16")
    assert c is not a
    assert len(calls) == 2


def _cam():
    return m.SmoothedCameraman(output_width=608, output_height=1080,
                               video_width=1920, video_height=1080)


def test_cameraman_drifts_to_center_when_subject_lost():
    """After the hold window with no fresh target, the camera must ease back
    toward the source center instead of freezing on the last position."""
    cam = _cam()
    cam.update_target((1750, 100, 120, 120))  # subject far right
    for _ in range(10):
        cam.get_crop_box()
    before = cam.current_center_x
    center = 1920 / 2
    # No targets for well past the hold window.
    for _ in range(500):
        cam.get_crop_box()
    after = cam.current_center_x
    assert abs(after - center) < abs(before - center)


def test_cameraman_holds_before_drifting():
    """Within the hold window the target center must not drift yet."""
    cam = _cam()
    cam.lost_hold_frames = 90
    cam.update_target((1750, 100, 120, 120))
    tx0 = cam.target_center_x
    for _ in range(80):  # still inside hold
        cam.get_crop_box()
    assert cam.target_center_x == tx0


def test_euro_smoother_opt_in(monkeypatch):
    monkeypatch.setenv("REFRAME_SMOOTHER", "euro")
    cam = _cam()
    assert cam._use_euro is True
    cam.update_target((1000, 500, 200, 200))
    box = cam.get_crop_box()
    assert len(box) == 4
