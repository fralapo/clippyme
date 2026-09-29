"""Host-unit tests for the hook overlay filter builder (pure, #5 animated hooks)."""
from clippyme.editing.hook_overlay import build_hook_overlay_filter


def test_static_is_legacy_byte_identical():
    assert build_hook_overlay_filter(12, 340) == "[0:v][1:v]overlay=12:340"


def test_static_coerces_ints():
    assert build_hook_overlay_filter(12.9, 340.2) == "[0:v][1:v]overlay=12:340"


def test_animate_has_fade_and_eased_slide():
    f = build_hook_overlay_filter(10, 200, animate=True)
    assert "fade=t=in:st=0:d=0.4:alpha=1" in f
    assert "format=yuva420p" in f
    # ease-out-cubic via pow(1-p,3), commas escaped for the filtergraph parser.
    assert "pow(1-min(t/0.4\\,1)\\,3)" in f
    assert f.startswith("[1:v]")
    assert "overlay=10:200+40*pow" in f


def test_animate_custom_params():
    f = build_hook_overlay_filter(0, 0, animate=True, dur=0.6, slide_px=80)
    assert "d=0.6" in f
    assert "overlay=0:0+80*pow" in f


# --- hook visibility window (first-4s hook, whole-clip when reframe disabled) --

def test_static_enable_window_applied():
    f = build_hook_overlay_filter(12, 340, enable_end=4)
    assert f == "[0:v][1:v]overlay=12:340:enable='between(t,0,4)'"


def test_static_no_enable_window_when_none():
    f = build_hook_overlay_filter(12, 340, enable_end=None)
    assert "enable" not in f


def test_animate_enable_window_applied():
    f = build_hook_overlay_filter(10, 200, animate=True, enable_end=4)
    assert f.endswith(":enable='between(t,0,4)'")


def test_logo_filter_enable_window_only_on_hook():
    from clippyme.editing.hook_overlay import build_hook_logo_filter

    f = build_hook_logo_filter(10, 20, "scale=100:-1", "5", "7", enable_end=4)
    assert f == (
        "[0:v][1:v]overlay=10:20:enable='between(t,0,4)'[vh];"
        "[2:v]scale=100:-1[lg];[vh][lg]overlay=5:7"
    )
    # logo overlay part must stay untouched (no enable clause)
    assert "overlay=5:7" in f and "overlay=5:7:enable" not in f


# --- animated hooks need a looped image input ---------------------------------

def _argv_for(monkeypatch, tmp_path, animate):
    """Run add_hook_to_video with every subprocess stubbed; return the ffmpeg argv."""
    import subprocess

    from clippyme.editing import hook_overlay

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00")
    monkeypatch.setattr(hook_overlay, "create_hook_image",
                        lambda *a, **k: (str(tmp_path / "hook.png"), 400, 120))
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: b"1080x1920")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    hook_overlay.add_hook_to_video(str(video), "hi", str(tmp_path / "out.mp4"),
                            style={"animate": animate})
    return seen["cmd"]


def test_animated_hook_loops_the_png_and_ends_with_the_video(monkeypatch, tmp_path):
    cmd = _argv_for(monkeypatch, tmp_path, animate=True)
    # A single-frame PNG + fade = alpha 0 forever (the hook never showed up).
    assert cmd[cmd.index("-loop") + 1] == "1"
    assert cmd.index("-loop") < cmd.index("-i", cmd.index("-loop"))
    assert "-shortest" in cmd  # else the looped image would never end the output


def test_static_hook_argv_unchanged(monkeypatch, tmp_path):
    cmd = _argv_for(monkeypatch, tmp_path, animate=False)
    assert "-loop" not in cmd and "-shortest" not in cmd
