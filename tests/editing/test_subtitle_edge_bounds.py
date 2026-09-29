"""Top / bottom position + vertical nudge: the whole caption block stays in frame.

The nudge is a percentage of the 1920 px frame, positive = down. Top anchors
the first line box at MarginV (260 karaoke, 350 classic) plus the nudge; bottom
anchors the last one at 1920 - MarginV, MarginV 350 minus the nudge. Nothing
bounded the block: top below about -13 drew it above the frame (gone at -50)
and bottom from about +18 put it flush against the frame's bottom edge.

These tests read the real karaoke ASS / classic force_style and rebuild each
caption's line-box block in 1080x1920 frame pixels (libass stacks lines
exactly Fontsize apart).
"""
import re

import pytest

from clippyme.editing import subtitles as subs

FRAME_H = 1920
STEP = FRAME_H / 100  # one slider unit
EDGE = subs._SUB_MARGIN_EDGE
SERIES = (-50, -40, -30, -25, -20, -14, -13, -8, -7, -5, -1, 0, 1, 5, 10, 12, 13, 14, 20, 25, 30, 40, 50)
_LONG = "When everybody told me this would never work I kept building anyway"
# Base MarginV at nudge 0, per path and anchor.
_BASE = {("karaoke", "top"): 260, ("karaoke", "bottom"): 350, ("classic", "top"): 350, ("classic", "bottom"): 350}


def _block(position, margin_v, height):
    top = margin_v if position == "top" else FRAME_H - margin_v - height
    return top, top + height


def _karaoke(tmp_path, position, offset_y, text="hi", preset="classic_white", **kwargs):
    """(style MarginV, [(top, bottom, pad) per event]) of a karaoke caption, frame px."""
    ass = tmp_path / "k.ass"
    words = [{"word": w, "start": 0.0, "end": 0.5} for w in text.split()]
    assert subs.generate_ass_karaoke({"segments": [{"words": words}]}, 0, 1, str(ass), preset=preset,
                                     mode="full_line", position=position, offset_y=offset_y, **kwargs)
    lines = ass.read_text(encoding="utf-8").splitlines()
    style = next(ln for ln in lines if ln.startswith("Style: Viral,")).split(",")
    fontsize, pad, code = float(style[2]), float(style[16]) + float(style[17]), int(style[18])
    assert code in ((7, 8) if position == "top" else (1, 2)), code
    width_of = subs._text_width(subs.SUBTITLE_PRESETS[preset]["font"], fontsize)
    blocks = []
    for event in (ln.split(",", 9) for ln in lines if ln.startswith("Dialogue:")):
        text_lines = subs._wrapped_line_count(re.sub(r"{[^}]*}", "", event[9]), width_of,
                                              1080 - int(style[19]) - int(style[20]))
        blocks.append(_block(position, int(event[7]) or int(style[21]), text_lines * fontsize) + (pad,))
    return int(style[21]), blocks


def _classic(tmp_path, monkeypatch, position, offset_y, cue="Hi", **kwargs):
    """(MarginV, (top, bottom, pad)) of a classic caption whose cue has hard breaks only, frame px."""
    captured = {}

    class _Ok:
        returncode = 0
        stderr = b""

    monkeypatch.setattr(subs.subprocess, "run", lambda cmd, **k: captured.update(cmd=cmd) or _Ok())
    monkeypatch.setattr(subs, "effective_fonts_dir", lambda: str(tmp_path))
    srt = tmp_path / "s.srt"
    srt.write_text(f"1\n00:00:00,000 --> 00:00:01,000\n{cue}\n", encoding="utf-8")
    subs.burn_subtitles("in.mp4", str(srt), "out.mp4", alignment=position, offset_y=offset_y,
                        **{"font_name": "Montserrat-Black", **kwargs})
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    style = dict(i.split("=", 1) for i in re.search(r"force_style='([^']*)'", vf).group(1).split(","))
    assert int(style["Alignment"]) in ((5, 6) if position == "top" else (1, 2)), style
    height = len(cue.split("\n")) * float(style["Fontsize"])
    return int(style["MarginV"]), _block(position, int(style["MarginV"]), height) + (float(style["Outline"]),)


_KARAOKE_CASES = [pytest.param({"preset": p}, id=f"karaoke-{p}") for p in subs.SUBTITLE_PRESETS] + [
    pytest.param({"preset": "classic_white", "text": _LONG, "font_size": 120}, id="karaoke-multiline"),
    pytest.param({"preset": "classic_white", "align": "left"}, id="karaoke-left"),
]
_CLASSIC_CASES = [
    pytest.param({}, id="classic-auto"),
    pytest.param({"cue": "One\nTwo\nThree\nFour"}, id="classic-4-lines"),
    pytest.param({"fontsize": 60, "border_width": 6}, id="classic-slider60"),
    pytest.param({"bg_opacity": 0.6, "cue": "One\nTwo\nThree"}, id="classic-box"),
    pytest.param({"h_align": "left"}, id="classic-left"),
]


def _assert_bounded_monotonic(blocks_by_nudge):
    """Every block inside the edge safe zone; blocks move down with the nudge,
    by the nudge distance except where one rests against an edge."""
    tops = []
    for n, (top, bottom, pad) in blocks_by_nudge:
        assert top - pad >= EDGE - 0.5 and bottom + pad <= FRAME_H - EDGE + 0.5, (n, top, bottom, pad)
        tops.append(top)
    assert all(b >= a for a, b in zip(tops, tops[1:])), tops
    for (n0, _), (n1, _), t0, t1 in zip(blocks_by_nudge, blocks_by_nudge[1:], tops, tops[1:]):
        if all(abs(t - tops[0]) > 1 and abs(t - tops[-1]) > 1 for t in (t0, t1)):
            assert t1 - t0 == pytest.approx((n1 - n0) * STEP, abs=1), (n0, n1, t0, t1)


@pytest.mark.parametrize("position", ["top", "bottom"])
@pytest.mark.parametrize("case", _KARAOKE_CASES)
def test_karaoke_edge_nudge_is_bounded_and_monotonic(tmp_path, case, position):
    per_nudge = {n: _karaoke(tmp_path, position, n, **case)[1] for n in SERIES}
    for event in range(len(per_nudge[0])):
        _assert_bounded_monotonic([(n, blocks[event]) for n, blocks in per_nudge.items()])


@pytest.mark.parametrize("position", ["top", "bottom"])
@pytest.mark.parametrize("case", _CLASSIC_CASES)
def test_classic_edge_nudge_is_bounded_and_monotonic(tmp_path, monkeypatch, case, position):
    _assert_bounded_monotonic([(n, _classic(tmp_path, monkeypatch, position, n, **case)[1]) for n in SERIES])


def test_multiline_karaoke_events_are_bounded_one_by_one(tmp_path):
    # A wrapped event needs more room than the one-line style margin allows.
    for position, nudge in (("top", 50), ("bottom", -50), ("top", -50), ("bottom", 50)):
        _, blocks = _karaoke(tmp_path, position, nudge, text=_LONG, font_size=120)
        assert max(b[1] - b[0] for b in blocks) >= 240, blocks
        for top, bottom, pad in blocks:
            assert top - pad >= EDGE and bottom + pad <= FRAME_H - EDGE, (position, nudge, blocks)


@pytest.mark.parametrize("position", ["top", "bottom"])
def test_edge_extremes_rest_on_the_safe_edge_in_both_paths(tmp_path, monkeypatch, position):
    """-50 top and +50 bottom rest against the same safe edge center uses, in both paths."""
    nudge = -50 if position == "top" else 50
    _, [(k_top, k_bottom, k_pad)] = _karaoke(tmp_path, position, nudge)
    _, (c_top, c_bottom, c_pad) = _classic(tmp_path, monkeypatch, position, nudge)
    if position == "top":
        assert (k_top - k_pad, c_top - c_pad) == (EDGE, EDGE)
    else:
        assert (k_bottom + k_pad, c_bottom + c_pad) == (FRAME_H - EDGE, FRAME_H - EDGE)


# Nudges whose block already sits inside the safe edge: output must not move.
_UNCLAMPED = {"top": (-7, -5, -1, 0, 1, 5, 10, 25, 50), "bottom": (-50, -25, -10, -1, 0, 1, 5, 10, 12)}


@pytest.mark.parametrize("position", ["top", "bottom"])
def test_edge_placement_is_unchanged_where_it_fits(tmp_path, monkeypatch, position):
    for nudge in _UNCLAMPED[position]:
        style_margin, blocks = _karaoke(tmp_path, position, nudge)
        assert style_margin == subs._offset_margin(position, _BASE["karaoke", position], nudge), nudge
        margin, _ = _classic(tmp_path, monkeypatch, position, nudge)
        assert margin == subs._offset_margin(position, _BASE["classic", position], nudge), nudge
    # Nudge 0 stays byte-identical: one-line events keep MarginV 0 (= the style's).
    ass = tmp_path / "k.ass"
    subs.generate_ass_karaoke({"segments": [{"words": [{"word": "hi", "start": 0.0, "end": 0.5}]}]}, 0, 1,
                              str(ass), preset="classic_white", position=position, offset_y=0)
    assert ",Viral,,0,0,0,," in ass.read_text(encoding="utf-8")


@pytest.mark.parametrize("position", ["top", "bottom"])
def test_clamp_enters_exactly_where_the_block_would_cross_the_edge(tmp_path, position):
    # classic_white: one 40 px line, pad 4 -> the margin may not go below 114.
    raw = {n: subs._offset_margin(position, _BASE["karaoke", position], n) for n in range(-50, 51)}
    margins = {n: _karaoke(tmp_path, position, n)[0] for n in raw}
    for n, value in raw.items():
        assert margins[n] == max(value, EDGE + 4), (n, value, margins[n])
    assert any(margins[n] != raw[n] for n in raw)


def test_letterbox_band_caption_is_bounded(tmp_path):
    """Reframe-off clips anchor bottom captions under the video (a top anchor at
    the band); the band placement keeps its value until the block would leave."""
    for nudge, expected in ((0, 1290), (10, 1290 + 192), (50, FRAME_H - EDGE - 4 - 40)):
        ass = tmp_path / "k.ass"
        subs.generate_ass_karaoke({"segments": [{"words": [{"word": "hi", "start": 0.0, "end": 0.5}]}]}, 0, 1,
                                  str(ass), preset="classic_white", position="bottom", offset_y=nudge,
                                  band_top=1290)
        style = next(ln for ln in ass.read_text(encoding="utf-8").splitlines() if ln.startswith("Style:"))
        assert int(style.split(",")[21]) == expected, (nudge, style)


# --- The shared clamp ---------------------------------------------------------

@pytest.mark.parametrize("lines", [1, 2, 3, 6])
@pytest.mark.parametrize("fontsize, pad", [(35, 2), (40, 5), (86.67, 1), (120, 20)])
def test_bounded_margin_keeps_the_block_inside_the_safe_edge(lines, fontsize, pad):
    height = lines * fontsize
    for margin in (-700, 0, 113, 114, 350, 1310, 1920, 2250):
        bounded = subs._bounded_margin_v(margin, height, pad)
        assert bounded - pad >= EDGE and bounded + height + pad <= FRAME_H - EDGE + 0.5, (margin, bounded)
        if EDGE + pad <= margin <= FRAME_H - EDGE - pad - height:
            assert bounded == margin


def test_center_margin_is_the_bounded_centre():
    # Center keeps its formula: the block centre at 960 + nudge, then the same clamp.
    for n in SERIES:
        for height, pad in ((40, 4), (260.01, 1), (720, 20)):
            assert subs._center_margin_v(n, height, pad) == subs._bounded_margin_v(
                FRAME_H / 2 + STEP * n - height / 2, height, pad)
