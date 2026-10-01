"""The vertical nudge slider (-50..50, positive = down) spans the room the caption has.

0 keeps each position's base (top 260 karaoke / 350 classic, center, bottom
350, the letterbox band); -50 puts the block against the top safe edge and +50
against the bottom one, linearly in between, one step size per half. The nudge
used to be a fixed 19.2 px per unit, so the clamp froze the caption over long
stretches of the slider (top from -8, bottom from +13, center from about -43
and +43 for one line, sooner for taller blocks) while the other direction never
reached the frame edge.

These tests read the real karaoke ASS / classic force_style and rebuild each
caption's line-box block in 1080x1920 frame pixels (libass stacks lines exactly
Fontsize apart; center and top are top anchors, bottom a bottom anchor).
"""
import re

import pytest

from clippyme.editing import subtitles as subs

FRAME_H = 1920
EDGE = subs._SUB_MARGIN_EDGE
NUDGES = range(-50, 51)
_LONG = "When everybody told me this would never work I kept building anyway"
POSITIONS = ("top", "center", "bottom")


def _block(code, margin_v, height, pad):
    """(top, bottom, pad) of a line-box block; SSA/ASS bottom codes are 1-3."""
    top = FRAME_H - margin_v - height if code in (1, 2, 3) else margin_v
    return top, top + height, pad


def _karaoke(tmp_path, position, offset_y, text="hi", preset="classic_white", **kwargs):
    """(style MarginV, [block per event]) of a karaoke caption, frame px."""
    ass = tmp_path / "k.ass"
    words = [{"word": w, "start": 0.0, "end": 0.5} for w in text.split()]
    assert subs.generate_ass_karaoke({"segments": [{"words": words}]}, 0, 1, str(ass), preset=preset,
                                     mode="full_line", position=position, offset_y=offset_y, **kwargs)
    lines = ass.read_text(encoding="utf-8").splitlines()
    style = next(ln for ln in lines if ln.startswith("Style: Viral,")).split(",")
    fontsize, pad, code = float(style[2]), float(style[16]) + float(style[17]), int(style[18])
    width_of = subs._text_width(subs.SUBTITLE_PRESETS[preset]["font"], fontsize)
    blocks = []
    for event in (ln.split(",", 9) for ln in lines if ln.startswith("Dialogue:")):
        count = subs._wrapped_line_count(re.sub(r"{[^}]*}", "", event[9]), width_of,
                                         1080 - int(style[19]) - int(style[20]))
        blocks.append(_block(code, int(event[7]) or int(style[21]), count * fontsize, pad))
    return int(style[21]), blocks


def _classic(tmp_path, monkeypatch, position, offset_y, cues=("Hi",), **kwargs):
    """(MarginV, block of the tallest cue) of a classic caption whose cues have hard breaks only."""
    captured = {}

    class _Ok:
        returncode = 0
        stderr = b""

    monkeypatch.setattr(subs.subprocess, "run", lambda cmd, **k: captured.update(cmd=cmd) or _Ok())
    monkeypatch.setattr(subs, "effective_fonts_dir", lambda: str(tmp_path))
    srt = tmp_path / "s.srt"
    srt.write_text("".join(f"{i}\n00:00:0{i},000 --> 00:00:0{i},900\n{cue}\n\n" for i, cue in enumerate(cues, 1)),
                   encoding="utf-8")
    subs.burn_subtitles("in.mp4", str(srt), "out.mp4", alignment=position, offset_y=offset_y,
                        **{"font_name": "Montserrat-Black", **kwargs})
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    style = dict(i.split("=", 1) for i in re.search(r"force_style='([^']*)'", vf).group(1).split(","))
    height = max(len(c.split("\n")) for c in cues) * float(style["Fontsize"])
    margin = int(style["MarginV"])
    return margin, _block(int(style["Alignment"]), margin, height, float(style["Outline"]))


_KARAOKE_CASES = [pytest.param({"preset": p}, id=f"karaoke-{p}") for p in subs.SUBTITLE_PRESETS] + [
    pytest.param({"text": _LONG, "font_size": 120}, id="karaoke-multiline"),
    pytest.param({"align": "left"}, id="karaoke-left"),
]
_CLASSIC_CASES = [
    pytest.param({}, id="classic-auto"),
    pytest.param({"cues": ("One\nTwo",)}, id="classic-2-lines"),
    pytest.param({"cues": ("One\nTwo\nThree",)}, id="classic-3-lines"),
    pytest.param({"cues": ("One\nTwo\nThree\nFour",)}, id="classic-4-lines"),
    pytest.param({"fontsize": 60, "border_width": 6}, id="classic-slider60"),
    pytest.param({"bg_opacity": 0.6, "cues": ("One\nTwo\nThree",)}, id="classic-box"),
    pytest.param({"h_align": "left"}, id="classic-left"),
] + [pytest.param({"font_name": f, "cues": ("One\nTwo",)}, id=f"classic-{f}")
     for f in ("Anton-Regular", "Bangers-Regular", "Poppins-Black", "Poppins-Medium")]


def _assert_uses_the_whole_slider(position, blocks):
    """blocks: {nudge: (top, bottom, pad)} for -50..50, one caption."""
    tops = [blocks[n][0] for n in NUDGES]
    for n in NUDGES:
        top, bottom, pad = blocks[n]
        assert top - pad >= EDGE - 0.5 and bottom + pad <= FRAME_H - EDGE + 0.5, (position, n, blocks[n])
    # Every slider step moves the caption down: no dead stretch, no reversal.
    assert all(b > a for a, b in zip(tops, tops[1:])), (position, tops)
    # -50 / +50 rest against the top / bottom safe edge.
    top, _, pad = blocks[-50]
    assert top - pad == pytest.approx(EDGE, abs=1), (position, blocks[-50])
    _, bottom, pad = blocks[50]
    assert bottom + pad == pytest.approx(FRAME_H - EDGE, abs=1), (position, blocks[50])
    # Linear on each side of 0: equal steps (1 px rounding), so -1 -> 0 -> 1 has no jump.
    for half in (tops[:51], tops[50:]):
        steps = [b - a for a, b in zip(half, half[1:])]
        assert max(steps) - min(steps) <= 1 + 1e-6, (position, steps)


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("case", _KARAOKE_CASES)
def test_karaoke_slider_spans_the_usable_range(tmp_path, case, position):
    per_nudge = {n: _karaoke(tmp_path, position, n, **case)[1] for n in NUDGES}
    for event in range(len(per_nudge[0])):  # each event by its own block
        _assert_uses_the_whole_slider(position, {n: blocks[event] for n, blocks in per_nudge.items()})


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("case", _CLASSIC_CASES)
def test_classic_slider_spans_the_usable_range(tmp_path, monkeypatch, case, position):
    _assert_uses_the_whole_slider(position, {n: _classic(tmp_path, monkeypatch, position, n, **case)[1]
                                             for n in NUDGES})


def test_nudge_zero_keeps_the_base_positions(tmp_path, monkeypatch):
    # The 01fdd29 placement: top 260 karaoke / 350 classic, bottom 350, the
    # block centred, karaoke one-line events on the style margin (MarginV 0).
    for position, style_margin in (("top", 260), ("bottom", 350), ("center", 940)):
        margin, [(top, bottom, _)] = _karaoke(tmp_path, position, 0, font_size=40)
        assert margin == style_margin, position
        ass = (tmp_path / "k.ass").read_text(encoding="utf-8")
        assert ",Viral,,0,0,0,," in ass if position != "center" else ",Viral,,0,0,940,," in ass
    for position, expected in (("top", 350), ("bottom", 350)):
        assert _classic(tmp_path, monkeypatch, position, 0)[0] == expected
    _, (top, bottom, _) = _classic(tmp_path, monkeypatch, "center", 0, cues=("One\nTwo\nThree\nFour",))
    assert (top + bottom) / 2 == pytest.approx(FRAME_H / 2, abs=0.5)


def test_classic_one_margin_is_sized_for_the_tallest_cue(tmp_path, monkeypatch):
    """One MarginV serves every cue: the 4-line cue reaches the safe edges, a
    shorter cue in the same file stops short of the far edge by the difference."""
    cues = ("Hi", "One\nTwo\nThree\nFour")
    for position in POSITIONS:
        _, (top, _, pad) = _classic(tmp_path, monkeypatch, position, -50, cues=cues)
        assert top - pad == pytest.approx(EDGE, abs=1), position
        _, (_, bottom, pad) = _classic(tmp_path, monkeypatch, position, 50, cues=cues)
        assert bottom + pad == pytest.approx(FRAME_H - EDGE, abs=1), position


def test_letterbox_band_caption_spans_the_usable_range(tmp_path):
    """Reframe off: a bottom caption is a top anchor at the band (1290 at 0)."""
    blocks = {}
    for n in NUDGES:
        margin, [block] = _karaoke(tmp_path, "bottom", n, band_top=1290)
        blocks[n] = block
        if n == 0:
            assert margin == 1290
    _assert_uses_the_whole_slider("band", blocks)


# --- The shared mapping --------------------------------------------------------

@pytest.mark.parametrize("anchor", ["top", "bottom"])
@pytest.mark.parametrize("base", [-400, 0, 260, 350, 940, 1290, 1800, 2500])
@pytest.mark.parametrize("height, pad", [(40, 4), (86.67, 1), (346.68, 2), (360, 20), (1800, 5)])
def test_nudge_margin_maps_the_slider_onto_the_safe_range(anchor, base, height, pad):
    low, high = EDGE + pad, FRAME_H - EDGE - pad - height
    margins = [subs._nudge_margin_v(anchor, base, n, height, pad) for n in NUDGES]
    # Always inside the safe edge (a block taller than the room sits on the top one).
    for m in margins:
        assert low <= m <= max(low, high + 0.5), (m, low, high)
    # 0 is the base, clamped as before; +/-50 are the ends; monotonic in screen terms.
    assert margins[50] == subs._bounded_margin_v(base, height, pad)
    if high >= low:
        up, down = (margins[0], margins[-1]) if anchor == "top" else (margins[-1], margins[0])
        assert (up, down) == (round(low), round(high))
    ordered = margins if anchor == "top" else margins[::-1]
    assert all(b >= a for a, b in zip(ordered, ordered[1:]))
    # Beyond the slider and garbage values behave like the ends / 0.
    assert subs._nudge_margin_v(anchor, base, 80, height, pad) == margins[-1]
    assert subs._nudge_margin_v(anchor, base, -80, height, pad) == margins[0]
    for junk in (None, "abc", float("nan")):
        assert subs._nudge_margin_v(anchor, base, junk, height, pad) == margins[50]
