"""Host tests for pipeline.run_ops — pure entrypoint helpers.

These pin logic that previously lived inline in main.py's __main__ block,
where no unit test could reach it.
"""
import os

from clippyme.pipeline.run_ops import build_cut_command, clip_output_basename, resolve_output_dir


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


# --- clip_output_basename -----------------------------------------------------

def test_basename_uses_sanitized_title():
    assert clip_output_basename("My Viral Clip", 0, "source") == "My Viral Clip_clip_1"


def test_forbidden_chars_stripped():
    assert clip_output_basename('a<b>c:d"e/f\\g|h?i*j', 0, "source") == "abcdefghij_clip_1"


def test_control_chars_stripped():
    assert clip_output_basename("hello\x00\x1fworld", 0, "source") == "helloworld_clip_1"


def test_leading_trailing_dots_and_spaces_stripped():
    assert clip_output_basename("  ..title..  ", 0, "source") == "title_clip_1"


def test_whitespace_runs_collapsed_but_spaces_kept():
    # tabs/newlines are ASCII control chars (0-31) and get stripped outright;
    # only literal space runs collapse to a single space.
    assert clip_output_basename("a   b    c", 0, "source") == "a b c_clip_1"


def test_reserved_names_fall_back():
    for name in ("CON", "con", "PRN", "AUX", "NUL", "COM1", "com9", "LPT1", "lpt9"):
        assert clip_output_basename(name, 2, "source") == "source_clip_3"


def test_empty_or_none_falls_back():
    assert clip_output_basename(None, 4, "source") == "source_clip_5"
    assert clip_output_basename("", 4, "source") == "source_clip_5"
    assert clip_output_basename("   ", 4, "source") == "source_clip_5"


def test_only_forbidden_chars_falls_back():
    assert clip_output_basename('<>:"/\\|?*', 0, "source") == "source_clip_1"


def test_long_title_truncated_at_boundary():
    title = "word " * 40  # 200 chars, well over max_len
    result = clip_output_basename(title, 1, "source", max_len=80)
    stem = result.removesuffix("_clip_2")
    assert len(stem) <= 80
    assert result.endswith("_clip_2")
    # cut on a word boundary, not mid-word
    assert stem == stem.strip()
    assert "word" in stem and not stem.endswith("wor")


def test_suffix_always_matches_index():
    assert clip_output_basename("Title", 0, "source").endswith("_clip_1")
    assert clip_output_basename("Title", 9, "source").endswith("_clip_10")
    assert clip_output_basename(None, 9, "source").endswith("_clip_10")


def test_unicode_preserved():
    assert clip_output_basename("Café Émoji 🎬 Clip", 0, "source") == "Café Émoji 🎬 Clip_clip_1"
