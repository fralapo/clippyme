"""Tests for clippyme.domain.job_results.build_main_cmd.

build_main_cmd is the single chokepoint that turns user-controlled request
data (URL, upload path, instructions, language) into the argv of a spawned
`python -m clippyme.pipeline.main` subprocess. Its argv-injection guard and
input validation are security-relevant, so they get explicit coverage.
"""
import pytest

from clippyme.domain.job_results import build_main_cmd, MAX_INSTRUCTIONS_LEN


# --- happy path / flag assembly --------------------------------------------

def test_url_job_builds_expected_argv():
    cmd = build_main_cmd(url="https://youtu.be/abc", output_dir="output")
    assert cmd[:4] == ["python", "-u", "-m", "clippyme.pipeline.main"]
    assert "-u" in cmd and "https://youtu.be/abc" in cmd
    assert cmd[cmd.index("-o") + 1] == "output"


def test_input_path_job_uses_dash_i():
    cmd = build_main_cmd(input_path="uploads/clip.mp4", output_dir="output")
    assert "-i" in cmd and "uploads/clip.mp4" in cmd
    # '-u' in the prefix is python's unbuffered flag; the URL flag '-u'
    # must not appear among the job args.
    assert "-u" not in cmd[4:]


def test_cookies_appended_only_when_file_exists(tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# netscape")
    cmd = build_main_cmd(url="https://x.com/v", output_dir="o", cookies_path=str(cookies))
    assert "-c" in cmd and str(cookies) in cmd


def test_cookies_skipped_when_file_missing(tmp_path):
    missing = tmp_path / "nope.txt"
    cmd = build_main_cmd(url="https://x.com/v", output_dir="o", cookies_path=str(missing))
    assert "-c" not in cmd


def test_optional_flags_assembled():
    cmd = build_main_cmd(
        url="https://x.com/v", output_dir="o",
        instructions="focus on hooks", reframe_mode="disabled",
        language="it", no_zoom=True, skip_analysis=True,
    )
    assert cmd[cmd.index("--instructions") + 1] == "focus on hooks"
    assert cmd[cmd.index("--reframe-mode") + 1] == "disabled"
    assert cmd[cmd.index("--language") + 1] == "it"
    assert "--no-zoom" in cmd
    assert "--skip-analysis" in cmd


def test_reframe_mode_auto_is_omitted():
    # 'auto' is the default pipeline behaviour, so it is not forwarded.
    cmd = build_main_cmd(url="https://x.com/v", output_dir="o", reframe_mode="auto")
    assert "--reframe-mode" not in cmd


def test_language_multi_is_omitted():
    cmd = build_main_cmd(url="https://x.com/v", output_dir="o", language="multi")
    assert "--language" not in cmd


# --- validation ------------------------------------------------------------

def test_invalid_reframe_mode_rejected():
    with pytest.raises(ValueError, match="invalid reframe_mode"):
        build_main_cmd(url="https://x.com/v", output_dir="o", reframe_mode="zoomzoom")


def test_unsupported_language_rejected():
    with pytest.raises(ValueError, match="unsupported language"):
        build_main_cmd(url="https://x.com/v", output_dir="o", language="klingon")


def test_overlong_instructions_rejected():
    with pytest.raises(ValueError, match="instructions too long"):
        build_main_cmd(url="https://x.com/v", output_dir="o",
                       instructions="x" * (MAX_INSTRUCTIONS_LEN + 1))


# --- argv-injection guard (security) ---------------------------------------

def test_url_starting_with_dash_rejected():
    # A leading '-' would be parsed by argparse as a flag, not a positional.
    with pytest.raises(ValueError, match="url must not start with '-'"):
        build_main_cmd(url="--config=/etc/evil", output_dir="o")


def test_url_with_leading_whitespace_dash_rejected():
    # lstrip() defeats the obvious " --flag" bypass.
    with pytest.raises(ValueError, match="url must not start with '-'"):
        build_main_cmd(url="   --help", output_dir="o")


def test_input_path_starting_with_dash_rejected():
    with pytest.raises(ValueError, match="input_path must not start with '-'"):
        build_main_cmd(input_path="-rf", output_dir="o")
