"""Subtitle styling correctness: vertical offset sign, fontsize clamp, hex
validation, and preset-honouring uppercase.

Pure / file-only tests for ``clippyme.editing.subtitles`` — no ffmpeg, no model
load, host-runnable. These guard the customization flow fixes:

- ``_nudge_margin_v``: a POSITIVE offset_y moves the caption DOWN regardless of
  anchor (shared convention between the ASS karaoke and the SRT classic path).
- ``_clamp_fontsize``: out-of-range / garbage sizes never reach ffmpeg.
- ``generate_ass_karaoke``: invalid colours raise instead of silently going
  white; ``uppercase=None`` honours the preset's own casing.
"""
import pytest

from clippyme.editing.subtitles import (
    SUBTITLE_PRESETS,
    _clamp_fontsize,
    _nudge_margin_v,
    _SUB_MARGIN_EDGE,
    _SUB_FONTSIZE_MAX,
    _SUB_FONTSIZE_MIN,
    _text_width,
    _wrapped_line_count,
    generate_ass_karaoke,
)


def _transcript(*words):
    segs_words = []
    t = 0.0
    for w in words:
        segs_words.append({"word": w, "start": t, "end": t + 0.4})
        t += 0.4
    return {"segments": [{"words": segs_words}]}


# --- _nudge_margin_v: positive = DOWN, both anchors ------------------------
# A 40 px line with 4 px of outline: MarginV 114..1766 keeps it in the safe edge.

def test_offset_zero_is_identity():
    assert _nudge_margin_v("bottom", 350, 0, 40, 4) == 350
    assert _nudge_margin_v("top", 260, 0, 40, 4) == 260


def test_offset_positive_moves_down_bottom_anchor():
    # bottom anchor: MarginV is gap from bottom → smaller = lower
    assert _nudge_margin_v("bottom", 350, 10, 40, 4) < 350


def test_offset_positive_moves_down_top_anchor():
    # top anchor: MarginV is gap from top → larger = lower
    assert _nudge_margin_v("top", 260, 10, 40, 4) > 260


def test_offset_negative_moves_up_bottom_anchor():
    assert _nudge_margin_v("bottom", 350, -10, 40, 4) > 350


def test_offset_never_leaves_the_safe_edge():
    assert _nudge_margin_v("bottom", 100, 50, 40, 4) == _SUB_MARGIN_EDGE + 4


def test_offset_garbage_is_zero():
    assert _nudge_margin_v("bottom", 350, None, 40, 4) == 350
    assert _nudge_margin_v("bottom", 350, "abc", 40, 4) == 350


# --- _clamp_fontsize -------------------------------------------------------

def test_clamp_in_range_passthrough():
    assert _clamp_fontsize(40, 38) == 40


def test_clamp_too_big():
    assert _clamp_fontsize(100000, 38) == _SUB_FONTSIZE_MAX


def test_clamp_too_small():
    assert _clamp_fontsize(1, 38) == _SUB_FONTSIZE_MIN


def test_clamp_garbage_returns_default():
    assert _clamp_fontsize(None, 38) == 38
    assert _clamp_fontsize("xx", 38) == 38


# --- generate_ass_karaoke validation + casing ------------------------------

def test_invalid_font_color_raises(tmp_path):
    out = tmp_path / "x.ass"
    with pytest.raises(ValueError):
        generate_ass_karaoke(
            _transcript("hello", "world"), 0, 10, str(out),
            preset="classic_white", font_color="red; rm -rf",
        )


def test_invalid_highlight_color_raises(tmp_path):
    out = tmp_path / "x.ass"
    with pytest.raises(ValueError):
        generate_ass_karaoke(
            _transcript("hello", "world"), 0, 10, str(out),
            preset="classic_white", highlight_color="notahex",
        )


def test_uppercase_none_honours_preset_lowercase(tmp_path):
    # mrbeast_box preset has uppercase=False → with uppercase=None the words
    # must keep their original casing.
    out = tmp_path / "x.ass"
    ok = generate_ass_karaoke(
        _transcript("hello", "world"), 0, 10, str(out),
        preset="mrbeast_box", uppercase=None,
    )
    assert ok
    text = out.read_text(encoding="utf-8")
    assert "hello" in text and "HELLO" not in text


def test_uppercase_none_honours_preset_uppercase(tmp_path):
    # classic_white preset has uppercase=True → uppercase=None still uppercases.
    out = tmp_path / "x.ass"
    ok = generate_ass_karaoke(
        _transcript("hello", "world"), 0, 10, str(out),
        preset="classic_white", uppercase=None,
    )
    assert ok
    text = out.read_text(encoding="utf-8")
    assert "HELLO" in text


def test_uppercase_explicit_overrides_preset(tmp_path):
    out = tmp_path / "x.ass"
    generate_ass_karaoke(
        _transcript("hello", "world"), 0, 10, str(out),
        preset="mrbeast_box", uppercase=True,
    )
    assert "HELLO" in out.read_text(encoding="utf-8")


def _style_fields(ass_text):
    # "Style: Viral,<font>,<size>,...,<align>,<L>,<R>,<marginV>,1"
    for line in ass_text.splitlines():
        if line.startswith("Style: Viral,"):
            return line.split(",")
    raise AssertionError("no Viral style line")


@pytest.mark.parametrize("offset_y", [0, 10])
def test_center_is_top_anchored_from_the_frame_centre(tmp_path, offset_y):
    # libass ignores MarginV for \an5, so center is a top anchor (8) for every
    # nudge, 0 included: the 40 px line centred (940), each unit moving it down
    # 1/50 of the 826 px to the lowest safe top (1920 - 110 - 4 - 40).
    out = tmp_path / "x.ass"
    generate_ass_karaoke(
        _transcript("hi"), 0, 10, str(out), preset="classic_white", font_size=40,
        position="center", offset_y=offset_y,
    )
    f = _style_fields(out.read_text(encoding="utf-8"))
    align, margin_v = f[-5], f[-2]
    assert align == "8"
    assert int(margin_v) == round(940 + 826 * offset_y / 50)


def test_extreme_fontsize_clamped_in_output(tmp_path):
    out = tmp_path / "x.ass"
    generate_ass_karaoke(
        _transcript("hello"), 0, 10, str(out),
        preset="classic_white", font_size=100000,
    )
    # the Style line carries the clamped size, never the raw 100000
    text = out.read_text(encoding="utf-8")
    assert "100000" not in text
    assert f"Viral,Montserrat Black,{_SUB_FONTSIZE_MAX}," in text


@pytest.mark.parametrize("preset", sorted(SUBTITLE_PRESETS))
def test_preset_size_keeps_a_long_three_word_group_on_one_line(preset):
    # Karaoke shows three words at a time: a preset size must not wrap them.
    style = SUBTITLE_PRESETS[preset]
    text = "Questa è probabilmente"
    width_of = _text_width(style["font"], style["fontsize"])
    line = text.upper() if style["uppercase"] else text
    assert _wrapped_line_count(line, width_of, 1080 - 2 * _SUB_MARGIN_EDGE) == 1
