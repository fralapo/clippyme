"""Classic (SRT) subtitle geometry must mean what it means for karaoke.

The classic path renders an SRT with `force_style`. ffmpeg gives an SRT an ASS
script of 384x288 (unless force_style sets PlayResX/Y) and libass scales that
script to the frame: margins and font size by frame height / PlayResY (margins
L/R by width / PlayResX), the outline by width / PlayResX horizontally and
height / PlayResY vertically. The karaoke path writes all of these in a
1080x1920 script. These tests read the real force_style and map it back to
frame pixels on a 1080x1920 frame.
"""
import re

import pytest

from clippyme.editing import subtitles as subs

FRAME_W, FRAME_H = 1080, 1920


def _classic_force_style(tmp_path, monkeypatch, **kwargs):
    captured = {}

    class _Ok:
        returncode = 0
        stderr = b""

    monkeypatch.setattr(subs.subprocess, "run", lambda cmd, **k: captured.update(cmd=cmd) or _Ok())
    monkeypatch.setattr(subs, "effective_fonts_dir", lambda: str(tmp_path))
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    subs.burn_subtitles("in.mp4", str(srt), "out.mp4", **kwargs)
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    style = re.search(r"force_style='([^']*)'", vf).group(1)
    return dict(item.split("=", 1) for item in style.split(","))


def _frame_px(style, key, axis="y"):
    """A force_style value in frame pixels along `axis` (script size checked in Docker)."""
    script_w, script_h = int(style.get("PlayResX", 384)), int(style.get("PlayResY", 288))
    scale = FRAME_W / script_w if axis == "x" else FRAME_H / script_h
    return float(style[key]) * scale


@pytest.mark.parametrize("alignment", ["bottom", "top"])
def test_classic_vertical_margin_matches_karaoke_in_frame_pixels(tmp_path, monkeypatch, alignment):
    style = _classic_force_style(tmp_path, monkeypatch, alignment=alignment)
    assert _frame_px(style, "MarginV") == pytest.approx(350, abs=FRAME_H / 288)


def test_classic_offset_uses_the_karaoke_nudge_mapping(tmp_path, monkeypatch):
    style = _classic_force_style(tmp_path, monkeypatch, alignment="bottom", offset_y=10)
    # One Auto-size line, outline 2, in frame px like karaoke.
    expected = subs._nudge_margin_v("bottom", 350, 10, subs._CLASSIC_AUTO_FONTSIZE, 2)
    assert _frame_px(style, "MarginV") == pytest.approx(expected, abs=FRAME_H / 288)


@pytest.mark.parametrize("h_align, left, right", [
    ("center", subs._SUB_MARGIN_EDGE, subs._SUB_MARGIN_EDGE),
    ("left", subs._SUB_MARGIN_EDGE, subs._SUB_MARGIN_LEFT_RIGHT),
])
def test_classic_side_margins_match_karaoke_in_frame_pixels(tmp_path, monkeypatch, h_align, left, right):
    style = _classic_force_style(tmp_path, monkeypatch, h_align=h_align)
    assert _frame_px(style, "MarginL", "x") == pytest.approx(left, abs=FRAME_W / 384)
    assert _frame_px(style, "MarginR", "x") == pytest.approx(right, abs=FRAME_W / 384)


@pytest.mark.parametrize("font_size", [20, 40, 60])
def test_classic_font_size_is_frame_pixels_like_karaoke(tmp_path, monkeypatch, font_size):
    # The shared slider value is a 1080x1920 font size and both modes use it as
    # is. It used to be read in the 288-line script (40 rendered as 227 px, 6.7x
    # the karaoke size), then scaled by a 0.85 left over from that script.
    style = _classic_force_style(tmp_path, monkeypatch, fontsize=font_size)
    assert _frame_px(style, "Fontsize") == pytest.approx(font_size, abs=0.5)


def test_classic_auto_font_size_is_unchanged(tmp_path, monkeypatch):
    # No size chosen (the classic UI has no size control): the size classic
    # captions always had, ffmpeg's SRT default 16 * 0.85 = 13 script units.
    for kwargs in ({}, {"fontsize": None}, {"fontsize": 0}):
        style = _classic_force_style(tmp_path, monkeypatch, **kwargs)
        assert _frame_px(style, "Fontsize") == pytest.approx(13 * FRAME_H / 288, abs=0.1)


def test_classic_compose_without_font_size_renders_the_auto_size(tmp_path, monkeypatch):
    import asyncio

    from clippyme.editing import compose

    captured = {}

    class _Ok:
        returncode = 0
        stderr = b""

    monkeypatch.setattr(subs.subprocess, "run", lambda cmd, **k: captured.update(cmd=cmd) or _Ok())
    monkeypatch.setattr(subs, "effective_fonts_dir", lambda: str(tmp_path))
    def _srt(transcript, start, end, path, *a):
        with open(path, "w", encoding="utf-8") as srt:
            srt.write("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
        return True

    monkeypatch.setattr(compose, "generate_srt", _srt)
    asyncio.run(compose._apply_subtitles(
        "in.mp4", str(tmp_path), 0, {"transcript": {}}, {"start": 0, "end": 5},
        {"mode": "classic", "font": "Montserrat-Black"}, []))
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    style = dict(i.split("=", 1) for i in re.search(r"force_style='([^']*)'", vf).group(1).split(","))
    assert _frame_px(style, "Fontsize") == pytest.approx(13 * FRAME_H / 288, abs=0.1)


def test_classic_tiny_font_size_is_clamped_not_zero(tmp_path, monkeypatch):
    style = _classic_force_style(tmp_path, monkeypatch, fontsize=1)
    assert _frame_px(style, "Fontsize") == pytest.approx(subs._SUB_FONTSIZE_MIN, abs=0.5)


@pytest.mark.parametrize("border_width, expected", [(0, 1), (1, 1), (2, 2), (6, 6)])
def test_classic_outline_is_frame_pixels_on_both_axes(tmp_path, monkeypatch, border_width, expected):
    # Karaoke's outline_width is 1080x1920 pixels on both axes. In the 384x288
    # script the default 2 rendered 5.6 px wide and 13.3 px tall. 0 keeps its
    # 1 px floor, as before.
    style = _classic_force_style(tmp_path, monkeypatch, border_width=border_width)
    assert _frame_px(style, "Outline", "x") == pytest.approx(expected, abs=0.05)
    assert _frame_px(style, "Outline", "y") == pytest.approx(expected, abs=0.05)


def test_classic_background_box_padding_matches_karaoke_box(tmp_path, monkeypatch):
    # BorderStyle 3 draws the box with Outline as padding; mrbeast_box uses 1.
    style = _classic_force_style(tmp_path, monkeypatch, bg_opacity=0.6)
    assert style["BorderStyle"] == "3"
    assert _frame_px(style, "Outline", "x") == pytest.approx(1, abs=0.05)
    assert _frame_px(style, "Outline", "y") == pytest.approx(1, abs=0.05)


@pytest.mark.parametrize("offset_y", [-50, -25, 0, 25, 45])
def test_classic_center_offset_moves_the_caption(tmp_path, monkeypatch, offset_y):
    # libass ignores MarginV for middle alignment (SSA 9/10/11), so the nudge was
    # a no-op. Like karaoke, every nudge (0 included) is a top anchor placed by
    # the shared center formula: one Auto-size line, outline 2.
    style = _classic_force_style(tmp_path, monkeypatch, alignment="center", offset_y=offset_y)
    assert style["Alignment"] == "6"
    assert int(style["MarginV"]) == subs._center_margin_v(offset_y, subs._CLASSIC_AUTO_FONTSIZE, 2)
    left = _classic_force_style(tmp_path, monkeypatch, alignment="center", offset_y=offset_y, h_align="left")
    assert left["Alignment"] == "5"


def test_classic_center_margin_centres_the_tallest_cue(tmp_path, monkeypatch):
    # One force_style MarginV serves every cue: it is set for the cue that wraps most.
    captured = {}

    class _Ok:
        returncode = 0
        stderr = b""

    monkeypatch.setattr(subs.subprocess, "run", lambda cmd, **k: captured.update(cmd=cmd) or _Ok())
    monkeypatch.setattr(subs, "effective_fonts_dir", lambda: str(tmp_path))
    long_cue = "When everybody told me this would never work I kept building anyway"
    srt = tmp_path / "s.srt"
    srt.write_text(f"1\n00:00:00,000 --> 00:00:01,000\nHi\n\n2\n00:00:01,000 --> 00:00:02,000\n{long_cue}\n",
                   encoding="utf-8")
    subs.burn_subtitles("in.mp4", str(srt), "out.mp4", alignment="center", font_name="Montserrat-Black")
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    style = dict(i.split("=", 1) for i in re.search(r"force_style='([^']*)'", vf).group(1).split(","))
    width_of = subs._text_width("Montserrat-Black", subs._CLASSIC_AUTO_FONTSIZE)
    lines = subs._wrapped_line_count(long_cue, width_of, FRAME_W - 2 * subs._SUB_MARGIN_EDGE)
    assert lines >= 3
    assert int(style["MarginV"]) == subs._center_margin_v(0, lines * subs._CLASSIC_AUTO_FONTSIZE, 2)


@pytest.mark.parametrize("alignment, code", [("bottom", "2"), ("top", "6")])
def test_classic_style_fields_are_unchanged(tmp_path, monkeypatch, alignment, code):
    style = _classic_force_style(tmp_path, monkeypatch, alignment=alignment, offset_y=10)
    assert style["Alignment"] == code
    assert style["Shadow"] == "0" and style["Bold"] == "1" and style["BorderStyle"] == "1"


def test_karaoke_margins_stay_in_frame_space(tmp_path):
    ass = tmp_path / "k.ass"
    transcript = {"segments": [{"words": [{"word": "hello", "start": 0.0, "end": 0.5}]}]}
    subs.generate_ass_karaoke(transcript, 0, 1, str(ass), preset="classic_white")
    text = ass.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in text and "PlayResY: 1920" in text
    fields = next(ln for ln in text.splitlines() if ln.startswith("Style: Viral,")).split(",")
    assert fields[-4:-1] == [str(subs._SUB_MARGIN_EDGE), str(subs._SUB_MARGIN_EDGE), "350"]
