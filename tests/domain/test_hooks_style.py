"""Hook text styling: hex parsing + Instagram-Stories-style render (Pillow)."""
import os
import tempfile

import pytest

from clippyme.domain.hooks import _hex_to_rgba, HOOK_STYLE_DEFAULTS


def test_hex_to_rgba_valid():
    assert _hex_to_rgba("#FDE700", 255) == (253, 231, 0, 255)
    assert _hex_to_rgba("#581BBA", 128) == (88, 27, 186, 128)


def test_hex_to_rgba_bad_falls_back():
    assert _hex_to_rgba("not-a-color", 200, default=(1, 2, 3)) == (1, 2, 3, 200)
    assert _hex_to_rgba(None, 255, default=(9, 9, 9)) == (9, 9, 9, 255)


def test_hook_style_defaults_match_frontend():
    # Bannerless white Anton with a thin black outline — kept in sync with the
    # frontend HOOK_STYLE_DEFAULT (dashboard/src/redesign/data.js).
    assert HOOK_STYLE_DEFAULTS["bg_enabled"] is False
    assert HOOK_STYLE_DEFAULTS["text_color"] == "#FFFFFF"
    assert HOOK_STYLE_DEFAULTS["outline_width"] == 4
    assert HOOK_STYLE_DEFAULTS["outline_color"] == "#000000"
    assert HOOK_STYLE_DEFAULTS["font"] == "Anton-Regular"


def test_create_hook_image_styled_renders_png():
    PIL = pytest.importorskip("PIL")  # noqa: F841
    from clippyme.domain.hooks import create_hook_image
    out = os.path.join(tempfile.gettempdir(), "hook_style_test.png")
    p, w, h = create_hook_image(
        "THIS changed everything", 972, out, font_scale=1.0,
        style={"text_color": "#FDE700", "bg_enabled": True, "bg_color": "#581BBA",
               "bg_opacity": 0.6, "outline_width": 4, "outline_color": "#000000"},
    )
    assert os.path.exists(p) and w > 0 and h > 0
    with open(p, "rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"


def test_create_hook_image_bannerless_renders():
    pytest.importorskip("PIL")
    from clippyme.domain.hooks import create_hook_image
    out = os.path.join(tempfile.gettempdir(), "hook_nobanner_test.png")
    p, w, h = create_hook_image(
        "NO BANNER", 972, out,
        style={"bg_enabled": False, "text_color": "#FFFFFF", "outline_width": 8},
    )
    assert os.path.exists(p) and w > 0 and h > 0
