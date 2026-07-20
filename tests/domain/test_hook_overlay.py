"""Host-unit tests for the hook overlay filter builder (pure, #5 animated hooks)."""
from clippyme.domain.hooks import build_hook_overlay_filter


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
    from clippyme.domain.hooks import build_hook_logo_filter

    f = build_hook_logo_filter(10, 20, "scale=100:-1", "5", "7", enable_end=4)
    assert f == (
        "[0:v][1:v]overlay=10:20:enable='between(t,0,4)'[vh];"
        "[2:v]scale=100:-1[lg];[vh][lg]overlay=5:7"
    )
    # logo overlay part must stay untouched (no enable clause)
    assert "overlay=5:7" in f and "overlay=5:7:enable" not in f
