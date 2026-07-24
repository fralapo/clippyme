from clippyme.pipeline.reframe_track import SmoothedCameraman, SpeakerTracker


def _face(x, y, mar, size=120):
    return {
        "box": [x, y, size, size],
        "score": size * size,
        "mar": mar,
    }


def test_tracker_keeps_identity_when_faces_cross_vertically(monkeypatch):
    monkeypatch.setenv("REFRAME_DIALOGUE_GROUP", "0")
    tracker = SpeakerTracker(cooldown_frames=2)
    # The talking face moves from upper-left toward lower-right while another
    # face crosses in the opposite direction. 2D matching should preserve it.
    target = None
    for frame in range(20):
        moving_x = 200 + frame * 45
        target = tracker.get_target([
            _face(moving_x, 100 + frame * 8, 0.1 if frame % 2 else 0.7),
            _face(1200 - frame * 35, 500 - frame * 8, 0.3),
        ], frame, 1920)
    assert target is not None
    assert target[1] < 300  # remains on the talking trajectory, not the crossing face


def test_ambiguous_dialogue_uses_group_box(monkeypatch):
    monkeypatch.setenv("REFRAME_DIALOGUE_GROUP", "1")
    monkeypatch.setenv("REFRAME_DIALOGUE_SCORE_RATIO", "0.80")
    tracker = SpeakerTracker(cooldown_frames=5)
    target = tracker.get_target([
        _face(200, 100, 0.3),
        _face(1500, 100, 0.3),
    ], 0, 1920)
    assert target[0] == 200
    assert target[2] > 1300  # union spans both dialogue participants


def test_wide_group_target_forces_camera_to_zoom_out():
    camera = SmoothedCameraman(608, 1080, 1920, 1080)
    camera.current_zoom = 1.5
    camera.update_target([200, 100, 1400, 200])
    assert camera.target_zoom == 1.0
