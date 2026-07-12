"""Host tests for pipeline.run_ops — pure entrypoint helpers.

These pin logic that previously lived inline in main.py's __main__ block,
where no unit test could reach it.
"""
import os

from clippyme.pipeline.run_ops import build_cut_command, resolve_output_dir


# --- resolve_output_dir -------------------------------------------------------

def test_none_returns_default():
    assert resolve_output_dir(None, default="/d") == "/d"
    assert resolve_output_dir("", default="/d") == "/d"


def test_video_suffix_means_file_use_its_dirname(tmp_path):
    target = str(tmp_path / "out" / "final.mp4")
    assert resolve_output_dir(target, default="/d") == str(tmp_path / "out")


def test_video_suffix_without_dirname_falls_back_to_default():
    assert resolve_output_dir("final.mkv", default="/d") == "/d"


def test_new_directory_is_created_and_returned(tmp_path):
    # Regression: the old logic os.path.dirname'd a NEW directory path,
    # landing the output one level above the intended dir.
    target = str(tmp_path / "does-not-exist-yet")
    assert resolve_output_dir(target, default="/d") == target
    assert os.path.isdir(target)


def test_existing_directory_passthrough(tmp_path):
    assert resolve_output_dir(str(tmp_path), default="/d") == str(tmp_path)


# --- build_cut_command ---------------------------------------------------------

def test_cut_command_shape_and_precision():
    cmd = build_cut_command("/in/video.mp4", 12.3456, 47.9, "/out/source_clip.mp4")
    assert cmd[0] == "ffmpeg" and cmd[1] == "-y"
    # Fast input seek: -ss must come BEFORE -i.
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-ss") + 1] == "12.346"          # 3-decimal rounding
    assert cmd[cmd.index("-t") + 1] == f"{47.9 - 12.3456:.3f}"
    assert cmd[-1] == "/out/source_clip.mp4"
    # CFR + aac audio ride along for the persisted source slice.
    assert cmd[cmd.index("-vsync") + 1] == "cfr"
    assert cmd[cmd.index("-c:a") + 1] == "aac"


def test_cut_command_uses_shared_x264_settings():
    from clippyme.domain.encode import x264_video_args
    cmd = build_cut_command("/in.mp4", 0, 10, "/out.mp4")
    for arg in x264_video_args(faststart=False):
        assert arg in cmd
