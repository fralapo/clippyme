"""Keep the live Create-tab subtitle preview honest.

The old pixel-faithful mirror (dashboard/src/lib/subtitlePresets.js) was deleted
with the legacy SubtitleModal component tree — nothing live rendered it. The
UI's preset grid is a CSS mirror in dashboard/src/lib/uiOptions.js (no
fontsize) whose data-bearing fields are the `hi` highlight colour and the
`font` it previews with (the bundled face, loaded via @font-face). This test
enforces that:

  1. the preview lists exactly the backend preset ids,
  2. each preview `hi` equals the backend `highlight_color`, and
  3. each preview `font` equals the backend `font`

so the colour and typeface a user sees in the picker match what burns in.
Fontsize parity is intentionally NOT asserted — the preview does not carry it
(the real render uses the backend preset directly).
"""
import os
import re

from clippyme.editing.subtitles import SUBTITLE_PRESETS as BACKEND

_JS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "dashboard", "src", "lib", "uiOptions.js",
)


def _parse_preview_presets(text: str) -> dict:
    """Extract {id: hi_hex_upper} from the uiOptions.js SUBTITLE_PRESETS array."""
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
            f"update uiOptions.js SUBTITLE_PRESETS `hi` to match subtitles.py"
        )


def test_preview_fonts_match_backend():
    with open(_JS_PATH, encoding="utf-8") as f:
        body = f.read().split("SUBTITLE_PRESETS", 1)[1]
    # Each entry: { id: 'hormozi_bold', label: …, hi: …, font: 'Bangers-Regular', style: … }
    preview = dict(re.findall(r"id:\s*'([^']+)'[^}]*?font:\s*'([^']+)'", body))

    assert set(preview) == set(BACKEND), (
        f"preset id mismatch — backend={sorted(BACKEND)} preview fonts={sorted(preview)}"
    )
    for pid, bp in BACKEND.items():
        assert preview[pid] == bp["font"], (
            f"{pid}: font backend={bp['font']} preview={preview[pid]} — "
            f"update uiOptions.js SUBTITLE_PRESETS `font` to match subtitles.py"
        )


def test_karaoke_presets_burn_without_tracking(tmp_path):
    """The preview shows natural advances (no letter-spacing, Goal 37), which
    is only honest while every karaoke style burns with ASS Spacing=0."""
    from clippyme.editing.subtitles import generate_ass_karaoke

    words = [{"word": w, "start": 0.0, "end": 0.5} for w in ("WORD", "UP")]
    for pid in BACKEND:
        ass = tmp_path / f"{pid}.ass"
        assert generate_ass_karaoke({"segments": [{"words": words}]}, 0, 1, str(ass), preset=pid)
        lines = ass.read_text(encoding="utf-8").splitlines()
        fields = next(ln for ln in lines if ln.startswith("Format: Name,")).split(": ", 1)[1].split(", ")
        style = next(ln for ln in lines if ln.startswith("Style: Viral,")).split(": ", 1)[1].split(",")
        assert dict(zip(fields, style))["Spacing"] == "0", pid
