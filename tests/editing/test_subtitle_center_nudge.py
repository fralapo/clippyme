"""Center position + vertical nudge: one continuous, bounded placement for both
subtitle paths.

The nudge slider runs -50..50, positive = down. At 0 the caption was centred
by libass (middle alignment, which ignores MarginV); any other value
re-anchored it to the top with MarginV = 960 + nudge, so 0 -> 1 jumped by half
a block and +50 put the block below the frame. Now 0 centres the block and
each unit moves it 1/50 of the room between the centre and a safe edge.

These tests read the real karaoke ASS / classic force_style and rebuild the
caption's line-box block in 1080x1920 frame pixels: libass stacks lines exactly
Fontsize apart, puts a top-anchored block's first line box at MarginV, a
bottom-anchored block's last one at 1920 - MarginV and centres a middle one.
"""
import re

import pytest

from clippyme.editing import subtitles as subs

FRAME_H = 1920
SERIES = (-50, -49, -40, -30, -25, -20, -11, -10, -2, -1, 0, 1, 2, 10, 11, 20, 25, 30, 40, 49, 50)


def _karaoke_block(tmp_path, offset_y, preset="classic_white", text="hi", **kwargs):
    """(top, bottom, pad) of a one-event karaoke caption block, frame px."""
    ass = tmp_path / "k.ass"
    words = [{"word": w, "start": 0.0, "end": 0.5} for w in text.split()]
    assert subs.generate_ass_karaoke({"segments": [{"words": words}]}, 0, 1, str(ass), preset=preset,
                                     position="center", offset_y=offset_y, **kwargs)
    lines = ass.read_text(encoding="utf-8").splitlines()
    style = next(ln for ln in lines if ln.startswith("Style: Viral,")).split(",")
    event = next(ln for ln in lines if ln.startswith("Dialogue:")).split(",")
    fontsize, outline, shadow, code = float(style[2]), float(style[16]), float(style[17]), int(style[18])
    margin_v = int(event[7]) or int(style[21])
    vertical = {7: "top", 8: "top", 9: "top", 4: "middle", 5: "middle", 6: "middle"}.get(code, "bottom")
    return _block(vertical, margin_v, fontsize) + (outline + shadow,)


def _classic_block(tmp_path, monkeypatch, offset_y, **kwargs):
    """(top, bottom, pad) of a one-line classic caption block, frame px."""
    captured = {}

    class _Ok:
        returncode = 0
        stderr = b""

    monkeypatch.setattr(subs.subprocess, "run", lambda cmd, **k: captured.update(cmd=cmd) or _Ok())
    monkeypatch.setattr(subs, "effective_fonts_dir", lambda: str(tmp_path))
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
    subs.burn_subtitles("in.mp4", str(srt), "out.mp4", alignment="center", offset_y=offset_y,
                        **{"font_name": "Montserrat-Black", **kwargs})
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    style = dict(i.split("=", 1) for i in re.search(r"force_style='([^']*)'", vf).group(1).split(","))
    assert (style["PlayResX"], style["PlayResY"]) == ("1080", "1920")
    code = int(style["Alignment"])  # legacy SSA: 1-3 bottom, 5-7 top, 9-11 middle
    vertical = "top" if code in (5, 6, 7) else "middle" if code in (9, 10, 11) else "bottom"
    return _block(vertical, int(style["MarginV"]), float(style["Fontsize"])) + (float(style["Outline"]),)


def _block(vertical, margin_v, line_height):
    if vertical == "top":
        top = margin_v
    elif vertical == "middle":
        top = FRAME_H / 2 - line_height / 2
    else:
        top = FRAME_H - margin_v - line_height
    return top, top + line_height


_KARAOKE_CASES = [pytest.param({"preset": p}, id=f"karaoke-{p}") for p in subs.SUBTITLE_PRESETS] + [
    pytest.param({"preset": "classic_white", "font_size": 120}, id="karaoke-size120"),
    pytest.param({"preset": "classic_white", "align": "left"}, id="karaoke-left"),
]
_CLASSIC_CASES = [
    pytest.param({}, id="classic-auto"),
    pytest.param({"fontsize": 60, "border_width": 6}, id="classic-slider60"),
    pytest.param({"bg_opacity": 0.6}, id="classic-box"),
    pytest.param({"h_align": "left"}, id="classic-left"),
]


def _centre(block):
    return (block[0] + block[1]) / 2


def _unit(block):
    """One slider unit for this block: 1/50 of the room between centre and a safe edge."""
    top, bottom, pad = block
    return (FRAME_H - (bottom - top) - 2 * (subs._SUB_MARGIN_EDGE + pad)) / 100


@pytest.mark.parametrize("case", _KARAOKE_CASES)
def test_karaoke_center_nudge_zero_is_centred_and_continuous(tmp_path, case):
    blocks = {n: _karaoke_block(tmp_path, n, **case) for n in (-1, 0, 1, 10, 11)}
    centres = {n: _centre(b) for n, b in blocks.items()}
    assert centres[0] == pytest.approx(FRAME_H / 2, abs=1)
    for a, b in ((-1, 0), (0, 1), (10, 11)):
        assert centres[b] - centres[a] == pytest.approx(_unit(blocks[0]), abs=1), centres


@pytest.mark.parametrize("case", _CLASSIC_CASES)
def test_classic_center_nudge_zero_is_centred_and_continuous(tmp_path, monkeypatch, case):
    blocks = {n: _classic_block(tmp_path, monkeypatch, n, **case) for n in (-1, 0, 1, 10, 11)}
    centres = {n: _centre(b) for n, b in blocks.items()}
    assert centres[0] == pytest.approx(FRAME_H / 2, abs=1)
    for a, b in ((-1, 0), (0, 1), (10, 11)):
        assert centres[b] - centres[a] == pytest.approx(_unit(blocks[0]), abs=1), centres


def _assert_bounded_monotonic_series(blocks):
    edge = subs._SUB_MARGIN_EDGE
    tops = []
    for n, (top, bottom, pad) in blocks.items():
        # The whole block (outline / shadow / box padding included) stays inside
        # the frame edge safe zone the side margins already use.
        assert top - pad >= edge - 1 and bottom + pad <= FRAME_H - edge + 1, (n, top, bottom, pad)
        tops.append(top)
    steps = [b - a for a, b in zip(tops, tops[1:])]
    assert all(s >= 0 for s in steps), steps  # never moves backwards
    # Every step is the nudge distance: -50 / +50 are the safe edges.
    unit = _unit(blocks[0])
    for n0, n1, t0, t1 in zip(SERIES, SERIES[1:], tops, tops[1:]):
        assert t1 - t0 == pytest.approx((n1 - n0) * unit, abs=1), (n0, n1, t0, t1)


@pytest.mark.parametrize("case", _KARAOKE_CASES)
def test_karaoke_center_nudge_is_monotonic_and_stays_in_frame(tmp_path, case):
    _assert_bounded_monotonic_series({n: _karaoke_block(tmp_path, n, **case) for n in SERIES})


@pytest.mark.parametrize("case", _CLASSIC_CASES)
def test_classic_center_nudge_is_monotonic_and_stays_in_frame(tmp_path, monkeypatch, case):
    _assert_bounded_monotonic_series({n: _classic_block(tmp_path, monkeypatch, n, **case) for n in SERIES})


def test_center_nudge_extremes_mirror_each_other(tmp_path, monkeypatch):
    # -50 rests against the top safe edge exactly as +50 rests against the bottom.
    for block_at in (lambda n: _karaoke_block(tmp_path, n),
                     lambda n: _classic_block(tmp_path, monkeypatch, n)):
        (top, _, _), (_, bottom, _) = block_at(-50), block_at(50)
        assert top == pytest.approx(FRAME_H - bottom, abs=1), (top, bottom)
        assert block_at(-49)[0] >= top and block_at(49)[1] <= bottom


def test_karaoke_and_classic_share_the_nudge_function(tmp_path, monkeypatch):
    # Same line height -> same block for every nudge (the same size in both modes).
    for n in SERIES:
        k = _karaoke_block(tmp_path, n, preset="classic_white", font_size=48, outline_width=2)
        c = _classic_block(tmp_path, monkeypatch, n, fontsize=48, border_width=2)
        assert c[1] - c[0] == k[1] - k[0]
        assert c[0] == pytest.approx(k[0], abs=1), (n, k, c)


@pytest.mark.parametrize("position", ["top", "bottom"])
def test_top_and_bottom_karaoke_output_is_unchanged(tmp_path, position):
    # The center fix must not touch the other anchors: same style line, events keep margin 0.
    ass = tmp_path / "k.ass"
    words = [{"word": "hi", "start": 0.0, "end": 0.5}]
    subs.generate_ass_karaoke({"segments": [{"words": words}]}, 0, 1, str(ass), preset="classic_white",
                              font_size=40, position=position, offset_y=10)
    text = ass.read_text(encoding="utf-8")
    style = next(ln for ln in text.splitlines() if ln.startswith("Style: Viral,")).split(",")
    expected = (8, subs._nudge_margin_v("top", 260, 10, 40, 4)) if position == "top" else (
        2, subs._nudge_margin_v("bottom", 350, 10, 40, 4))
    assert (int(style[18]), int(style[21])) == expected
    assert ",Viral,,0,0,0,," in text


# --- The shared helpers ------------------------------------------------------

_LONG = "When everybody told me this would never work I kept building anyway"


@pytest.mark.parametrize("lines", [1, 2, 3, 6])
@pytest.mark.parametrize("fontsize, pad", [(35, 2), (40, 5), (86.67, 1), (120, 20)])
def test_center_margin_bounds_the_whole_block(lines, fontsize, pad):
    height = lines * fontsize
    tops = [subs._center_margin_v(n, height, pad) for n in SERIES]
    edge = subs._SUB_MARGIN_EDGE
    for n, top in zip(SERIES, tops):
        assert top - pad >= edge and top + height + pad <= FRAME_H - edge + 0.5, (n, top)
    assert all(b >= a for a, b in zip(tops, tops[1:])), tops
    assert tops[SERIES.index(0)] + height / 2 == pytest.approx(FRAME_H / 2, abs=0.5)


def test_center_margin_garbage_nudge_is_centred():
    assert subs._center_margin_v(None, 40, 2) == subs._center_margin_v("x", 40, 2) == 940


def test_wrapped_line_count_follows_the_font():
    width_of = subs._text_width("Montserrat-Black", 40)
    assert subs._wrapped_line_count("HI", width_of, 860) == 1
    assert subs._wrapped_line_count("HI\nTHERE", width_of, 860) == 2
    assert subs._wrapped_line_count(_LONG.upper(), width_of, 860) == 2
    assert subs._wrapped_line_count(_LONG.upper(), subs._text_width("Montserrat-Black", 120), 860) >= 5
    # Narrow display faces fit more per line than wide ones.
    assert subs._text_width("Anton-Regular", 40)(_LONG) < width_of(_LONG)


def test_unknown_font_width_is_estimated():
    width_of = subs._text_width("Verdana", 50)
    assert width_of("abcd") == pytest.approx(4 * 50 * subs._FALLBACK_CHAR_WIDTH)


def test_karaoke_event_margin_centres_its_wrapped_block(tmp_path):
    ass = tmp_path / "k.ass"
    words = [{"word": w, "start": 0.0, "end": 0.5} for w in _LONG.split()]
    subs.generate_ass_karaoke({"segments": [{"words": words}]}, 0, 1, str(ass), preset="classic_white",
                              mode="full_line", position="center", font_size=120)
    text = ass.read_text(encoding="utf-8")
    style = next(ln for ln in text.splitlines() if ln.startswith("Style: Viral,")).split(",")
    width_of = subs._text_width("Montserrat-Black", 120)
    counts = []
    for event in (ln.split(",", 9) for ln in text.splitlines() if ln.startswith("Dialogue:")):
        counts.append(subs._wrapped_line_count(re.sub(r"{[^}]*}", "", event[9]), width_of, 860))
        assert int(event[7]) == subs._center_margin_v(0, counts[-1] * 120, 4), (event, counts)
    assert max(counts) >= 2 and int(style[21]) == subs._center_margin_v(0, 120, 4)
