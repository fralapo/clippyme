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
