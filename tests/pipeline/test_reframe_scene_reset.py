"""Source-level guard: tracker state must reset at every scene boundary.

SpeakerTracker / DetectionSmoother carry face identities, MAR history and box
histories. Without a reset at a hard cut, a face in the new scene that lands
near a previous scene's track inherits the old active-speaker sticky bonus +
switch cooldown and gets box-averaged with stale frames from an unrelated
shot — and under comfort mode (default) the polluted early targets skew the
whole scene's collapsed median crop.

``reframe.py`` imports cv2/mediapipe/YOLO, which the host tier doesn't have,
so this guard PARSES the source instead of importing it (the import-based
variant lives in the Docker-only integration suite via test_reframe_mar's
pattern). Behavioural coverage runs in Docker; this pins the wiring.
"""
import ast
from pathlib import Path

REFRAME_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "clippyme" / "pipeline" / "reframe.py"
)


def _source():
    return REFRAME_PATH.read_text(encoding="utf-8")


def test_both_trackers_define_reset():
    tree = ast.parse(_source())
    classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    for cls_name in ("SpeakerTracker", "DetectionSmoother"):
        assert cls_name in classes, f"{cls_name} class missing"
        methods = {m.name for m in classes[cls_name].body
                   if isinstance(m, ast.FunctionDef)}
        assert "reset" in methods, f"{cls_name}.reset() missing"


def test_every_scene_advance_resets_both_trackers():
    """Each `current_scene_index += 1` (streaming loop + global-smooth pass 1)
    must be followed, within its handful of lines, by both tracker resets."""
    lines = _source().splitlines()
    advance_lines = [i for i, line in enumerate(lines)
                     if line.strip() == "current_scene_index += 1"]
    assert advance_lines, "scene-advance sites not found — did the loop change?"
    for i in advance_lines:
        window = "\n".join(lines[i:i + 12])
        assert "speaker_tracker.reset(" in window, \
            f"scene advance at line {i + 1} does not reset SpeakerTracker"
        assert "detection_smoother.reset(" in window, \
            f"scene advance at line {i + 1} does not reset DetectionSmoother"


def test_short_scene_sampling_is_clamped():
    """analyze_scenes_strategy must not sample frames outside [s_frame, e_frame)
    on short scenes (the unclamped s_frame+2 / e_frame-2 read the neighbour)."""
    src = _source()
    assert "min(s_frame + 2, e_frame - 1)" in src
    assert "max(e_frame - 2, s_frame)" in src
