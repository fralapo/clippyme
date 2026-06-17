"""Smoke tests for clippyme.pipeline.postprocess (cv2-free, host-runnable).

These verify the module imports and that both stages fail safe (swallow errors,
leave no temp file) when ffmpeg/ffprobe can't process the input — without
asserting on real transcoding, which belongs in the Docker integration tier.
"""
import os

from clippyme.pipeline import postprocess as pp


def test_module_exposes_public_api():
    assert callable(pp.normalize_audio)
    assert callable(pp.apply_subtle_zoom)


def test_normalize_audio_failsafe_on_missing_input(tmp_path):
    missing = str(tmp_path / "nope.mp4")
    # Must not raise even if ffmpeg is absent or the file doesn't exist.
    pp.normalize_audio(missing)
    assert not os.path.exists(missing + ".norm.mp4")


def test_apply_subtle_zoom_failsafe_on_missing_input(tmp_path):
    missing = str(tmp_path / "nope.mp4")
    pp.apply_subtle_zoom(missing)
    assert not os.path.exists(missing + ".zoom.mp4")
