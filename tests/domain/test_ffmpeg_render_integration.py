"""Integration smoke tests for the NEW ffmpeg render paths added across the
8 improvements. Pure helpers are host-tested elsewhere; these prove the actual
ffmpeg invocations are VALID and produce a playable file (real ffmpeg needed →
`integration`-marked, runs in Docker).

Covers:
  #1  smartcut afade segment render (audio fades at concat boundaries)
  #4  grade.apply_grade colour pass
  #5  hooks.add_hook_to_video animated entrance (build_hook_overlay_filter)
"""
import os
import subprocess

import pytest

pytestmark = pytest.mark.integration


def _has_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False


def _make_clip(path, dur=2):
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={dur}:size=320x240:rate=25",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _streams(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", path]
    ).decode()
    return out.split()


@pytest.fixture()
def clip(tmp_path):
    if not _has_ffmpeg():
        pytest.skip("ffmpeg not available")
    p = str(tmp_path / "src.mp4")
    _make_clip(p)
    assert os.path.getsize(p) > 0
    return p


def test_grade_renders(clip, tmp_path):
    from clippyme.domain.grade import apply_grade

    out = str(tmp_path / "graded.mp4")
    assert apply_grade(clip, out, "warm_cinematic") is True
    assert os.path.getsize(out) > 0
    assert "video" in _streams(out)


def test_grade_none_is_noop(clip, tmp_path):
    from clippyme.domain.grade import apply_grade

    out = str(tmp_path / "none.mp4")
    assert apply_grade(clip, out, "none") is False
    assert not os.path.exists(out)


def test_animated_hook_renders(clip, tmp_path):
    from clippyme.domain.hooks import add_hook_to_video

    out = str(tmp_path / "hooked.mp4")
    ok = add_hook_to_video(clip, "HELLO WORLD", out, position="top",
                           style={"animate": True})
    assert ok is True
    assert os.path.getsize(out) > 0
    s = _streams(out)
    assert "video" in s and "audio" in s


def test_static_hook_still_renders(clip, tmp_path):
    from clippyme.domain.hooks import add_hook_to_video

    out = str(tmp_path / "hooked_static.mp4")
    assert add_hook_to_video(clip, "STATIC", out, style={"animate": False}) is True
    assert os.path.getsize(out) > 0


def test_smartcut_afade_segments_render(clip, tmp_path):
    from clippyme.domain.smartcut import _render_with_ffmpeg

    out = str(tmp_path / "cut.mp4")
    # Two kept segments → one internal concat boundary that must fade, not pop.
    ok = _render_with_ffmpeg(clip, [(0.0, 0.8), (1.2, 2.0)], out)
    assert ok is True
    assert os.path.getsize(out) > 0
    assert "audio" in _streams(out)
