"""Enforce the CLAUDE.md "hard rule": the frontend faithful-preview preset
mirror (dashboard/src/lib/subtitlePresets.js) must stay 1:1 with the backend
source of truth (clippyme.domain.subtitles.SUBTITLE_PRESETS).

Previously this was a documented convention with nothing checking it, so a
backend fontsize/font change could silently desync the pixel-faithful preview
(a real past bug). This test fails CI the moment they drift.
"""
import os
import re

from clippyme.domain.subtitles import SUBTITLE_PRESETS as BACKEND

_JS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "dashboard", "src", "lib", "subtitlePresets.js",
)


def _parse_js_presets(text: str) -> dict:
    """Extract {id: {fontsize, font, outlineWidth}} from the JS preset object.

    Each preset is a flat (no nested braces) block ``<id>: { ... },`` so a
    non-greedy match to the first closing brace is unambiguous.
    """
    # Scope to the SUBTITLE_PRESETS object literal.
    body = text.split("SUBTITLE_PRESETS", 1)[1]
    out: dict = {}
    for m in re.finditer(r"(\w+):\s*\{(.*?)\}", body, re.DOTALL):
        key, block = m.group(1), m.group(2)
        fs = re.search(r"fontsize:\s*(\d+)", block)
        if not fs:
            continue  # not a preset block (e.g. a nested style helper)
        font = re.search(r"font:\s*'([^']+)'", block)
        ow = re.search(r"outlineWidth:\s*(\d+)", block)
        out[key] = {
            "fontsize": int(fs.group(1)),
            "font": font.group(1) if font else None,
            "outline_width": int(ow.group(1)) if ow else None,
        }
    return out


def test_js_mirror_matches_backend_presets():
    assert os.path.exists(_JS_PATH), f"missing JS mirror: {_JS_PATH}"
    with open(_JS_PATH, encoding="utf-8") as f:
        js = _parse_js_presets(f.read())

    # Same set of preset ids on both sides.
    assert set(js) == set(BACKEND), (
        f"preset id mismatch — backend={sorted(BACKEND)} js={sorted(js)}"
    )

    # Each shared field must agree (the hard rule).
    for pid, bp in BACKEND.items():
        jp = js[pid]
        assert jp["fontsize"] == bp["fontsize"], (
            f"{pid}: fontsize backend={bp['fontsize']} js={jp['fontsize']} — "
            f"update subtitlePresets.js to match subtitles.py"
        )
        assert jp["font"] == bp["font"], (
            f"{pid}: font backend={bp['font']!r} js={jp['font']!r}"
        )
        assert jp["outline_width"] == bp["outline_width"], (
            f"{pid}: outline_width backend={bp['outline_width']} js={jp['outline_width']}"
        )
