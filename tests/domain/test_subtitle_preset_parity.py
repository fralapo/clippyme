"""Keep the live Create-tab subtitle preview honest.

The old pixel-faithful mirror (dashboard/src/lib/subtitlePresets.js) was deleted
with the legacy SubtitleModal component tree — nothing live rendered it. The
redesign's preset grid is a *cosmetic* CSS mirror in dashboard/src/redesign/
data.js (system fonts, no fontsize) whose ONLY data-bearing field is the `hi`
highlight colour. This test enforces that:

  1. the preview lists exactly the backend preset ids, and
  2. each preview `hi` equals the backend `highlight_color`

so the colour a user sees on the "UP" word in the picker matches what burns in.
Full fontsize/font parity is intentionally NOT asserted — the cosmetic mirror
does not carry those (the real render uses the backend preset directly).
"""
import os
import re

from clippyme.domain.subtitles import SUBTITLE_PRESETS as BACKEND

_JS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "dashboard", "src", "redesign", "data.js",
)


def _parse_preview_presets(text: str) -> dict:
    """Extract {id: hi_hex_upper} from the data.js SUBTITLE_PRESETS array."""
    body = text.split("SUBTITLE_PRESETS", 1)[1]
    out: dict = {}
    # Each entry: { id: 'classic_white', label: 'Classic', hi: '#FFFF00', ... }
    for m in re.finditer(r"id:\s*'([^']+)'[^}]*?hi:\s*'(#[0-9A-Fa-f]{3,6})'", body):
        hx = m.group(2).upper()
        if len(hx) == 4:  # #RGB shorthand → #RRGGBB
            hx = "#" + "".join(c * 2 for c in hx[1:])
        out[m.group(1)] = hx
    return out


def test_preview_highlight_colors_match_backend():
    assert os.path.exists(_JS_PATH), f"missing preview mirror: {_JS_PATH}"
    with open(_JS_PATH, encoding="utf-8") as f:
        preview = _parse_preview_presets(f.read())

    assert set(preview) == set(BACKEND), (
        f"preset id mismatch — backend={sorted(BACKEND)} preview={sorted(preview)}"
    )

    for pid, bp in BACKEND.items():
        assert preview[pid] == bp["highlight_color"].upper(), (
            f"{pid}: highlight backend={bp['highlight_color']} preview={preview[pid]} — "
            f"update data.js SUBTITLE_PRESETS `hi` to match subtitles.py"
        )
