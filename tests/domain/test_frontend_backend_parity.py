"""Cross-file parity: the frontend constant tables must mirror the backend.

dashboard/src/redesign/data.js declares preset/position/size ids and hook-style
defaults whose values MUST match the backend dicts (its own comments say so),
but nothing enforced it — a renamed backend preset id silently became a no-op
layer or a 4xx in the UI, and the hook-style defaults have drifted before
(see the hook-default-sync incident). test_subtitle_preset_parity.py already
covers SUBTITLE_PRESETS; this file covers the rest: grade presets, logo
positions/sizes, and HOOK_STYLE_DEFAULT.

The JS side is parsed textually (no node dependency in the Python suite);
parsing failures fail loudly rather than passing vacuously.
"""
import json
import os
import re

from clippyme.domain.compose import _LOGO_SIZE_MAP
from clippyme.domain.grade import GRADE_PRESETS as BACKEND_GRADES
from clippyme.domain.hooks import HOOK_STYLE_DEFAULTS
from clippyme.domain.logo import _POSITIONS as BACKEND_LOGO_POSITIONS

_JS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "dashboard", "src", "redesign", "data.js",
)


def _js_source() -> str:
    with open(_JS_PATH, encoding="utf-8") as f:
        return f.read()


def _js_block(name: str) -> str:
    """The source text of `export const <name> = ...;` up to the closer."""
    src = _js_source()
    # The value's own opening bracket picks the branch: arrays close at `];`,
    # object literals at a line-start `};` (a lone alternation on the whole
    # pattern would let an array block run on until the NEXT object's closer).
    m = re.search(rf"export const {name} = (\[.*?\];|\{{.*?^\}};?$)",
                  src, re.S | re.M)
    assert m, f"could not locate {name} in data.js — parser needs updating"
    return m.group(0)


def test_grade_preset_ids_match_backend():
    block = _js_block("GRADE_PRESETS")
    js_ids = set(re.findall(r"id:\s*'([^']+)'", block))
    assert js_ids, "no grade ids parsed from data.js"
    # 'none' is represented in the UI by the toggle being off, not as an id.
    backend_ids = {k for k in BACKEND_GRADES if k != "none"}
    assert js_ids == backend_ids, (
        f"grade preset drift — backend={sorted(backend_ids)} data.js={sorted(js_ids)}"
    )


def test_logo_positions_and_sizes_match_backend():
    pos_block = _js_block("LOGO_POSITIONS")
    js_positions = set(re.findall(r"\['([a-z-]+)'", pos_block))
    assert js_positions == set(BACKEND_LOGO_POSITIONS), (
        f"logo position drift — backend={sorted(BACKEND_LOGO_POSITIONS)} "
        f"data.js={sorted(js_positions)}"
    )

    size_block = _js_block("LOGO_SIZES")
    js_sizes = set(re.findall(r"\['([A-Z])'", size_block))
    assert js_sizes == set(_LOGO_SIZE_MAP), (
        f"logo size drift — backend={sorted(_LOGO_SIZE_MAP)} data.js={sorted(js_sizes)}"
    )


def _parse_hook_style_default() -> dict:
    block = _js_block("HOOK_STYLE_DEFAULT")
    out = {}
    for key, raw in re.findall(r"^\s*(\w+):\s*([^,\n]+),?\s*$", block, re.M):
        raw = raw.strip().rstrip(",")
        if raw in ("true", "false"):
            out[key] = raw == "true"
        elif raw.startswith("'") or raw.startswith('"'):
            out[key] = raw.strip("'\"")
        else:
            try:
                out[key] = json.loads(raw)
            except ValueError:
                continue
    return out


def test_hook_style_defaults_match_backend():
    """Every key data.js declares must equal hooks.py HOOK_STYLE_DEFAULTS.

    (data.js intentionally omits corner_radius/shadow — those have no UI
    control — so only the shared keys are compared, but at least the core
    set must be present on the JS side.)
    """
    js = _parse_hook_style_default()
    required = {"bg_enabled", "bg_color", "bg_opacity", "text_color",
                "outline_width", "outline_color", "font", "animate"}
    assert required <= set(js), f"data.js HOOK_STYLE_DEFAULT missing keys: {required - set(js)}"
    for key, js_val in js.items():
        assert key in HOOK_STYLE_DEFAULTS, f"data.js declares unknown hook style key {key!r}"
        assert js_val == HOOK_STYLE_DEFAULTS[key], (
            f"hook style default drift on {key!r}: data.js={js_val!r} "
            f"backend={HOOK_STYLE_DEFAULTS[key]!r} — change BOTH sides together "
            f"(data.js + hooks.py) or the WYSIWYG preview diverges from the render"
        )
