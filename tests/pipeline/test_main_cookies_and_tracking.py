"""Regression tests for bugs identified in main.py review.

Each test is tagged with the bug number from the plan so failures are
traceable. Run inside the Docker backend image (host typically lacks
the cv2/mediapipe/yt-dlp runtime deps).
"""
import os
import pytest

# main.py pulls cv2/scenedetect/mediapipe at import time; skip the whole module
# on hosts that lack the heavy CV runtime (it runs in the Docker backend image).
pytest.importorskip("scenedetect")
pytestmark = pytest.mark.integration

from clippyme.pipeline.main import _resolve_cookies_path


def test_bug1_cookie_path_points_at_repo_root_data_dir(tmp_path, monkeypatch):
    repo_root = tmp_path
    data_dir = repo_root / "data"
    data_dir.mkdir()
    (data_dir / "cookies.txt").write_text("# netscape cookies")
    monkeypatch.chdir(repo_root)
    monkeypatch.delenv("YOUTUBE_COOKIES", raising=False)
    resolved = _resolve_cookies_path(explicit=None)
    assert resolved == str(data_dir / "cookies.txt")


def test_bug1_cookie_explicit_override_wins(tmp_path):
    explicit = tmp_path / "my_cookies.txt"
    explicit.write_text("x")
    assert _resolve_cookies_path(explicit=str(explicit)) == str(explicit)


def test_bug1_cookie_env_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YOUTUBE_COOKIES", "# cookies from env")
    resolved = _resolve_cookies_path(explicit=None)
    assert resolved is not None
    assert os.path.exists(resolved)


def test_bug1_cookie_none_when_nothing_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YOUTUBE_COOKIES", raising=False)
    assert _resolve_cookies_path(explicit=None) is None


def test_bug2_person_box_targets_head_zone_not_above_head():
    """Bug #2: full person bbox fed to cameraman must center Y at
    y + 0.15*h, not at y + 0.15*0.4*h."""
    from clippyme.pipeline.main import SmoothedCameraman
    cam = SmoothedCameraman(output_width=1080, output_height=1920,
                            video_width=1920, video_height=1080)
    cam.update_target([800, 200, 300, 800], is_person_box=True)
    # Head zone = y + h*0.15 = 200 + 120 = 320 px
    assert cam.target_center_y == pytest.approx(320, abs=1)


def test_bug5_cooldown_blocks_switch_even_when_old_speaker_offscreen():
    from clippyme.pipeline.main import SpeakerTracker
    st = SpeakerTracker(cooldown_frames=45)
    box_a = {'box': [100, 100, 200, 200], 'score': 40000, 'mar': 0.3}
    st.get_target([box_a], frame_number=0, width=1920)
    active_before = st.active_speaker_id
    box_b = {'box': [1500, 100, 200, 200], 'score': 40000, 'mar': 0.3}
    st.get_target([box_b], frame_number=5, width=1920)
    assert st.active_speaker_id == active_before, \
        "cooldown was bypassed when old speaker left the frame"


def test_bug6_detection_smoother_prunes_stale_tracks():
    from clippyme.pipeline.main import DetectionSmoother
    s = DetectionSmoother(window_size=5)
    s.smooth([{'box': [0, 0, 100, 100], 'score': 10000}], frame_number=0)
    assert len(s.histories) == 1
    s.smooth([{'box': [800, 0, 100, 100], 'score': 10000}], frame_number=200)
    assert len(s.histories) == 1, \
        f"old track should be pruned, got {list(s.histories.keys())}"
