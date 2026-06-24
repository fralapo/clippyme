"""Host tests for subtitle horizontal alignment + karaoke stroke colour."""
import pytest

from clippyme.domain import subtitles
from clippyme.domain.subtitles import (
    normalize_h_align,
    ass_alignment_and_margins,
    generate_ass_karaoke,
    _SUB_MARGIN_EDGE,
    _SUB_MARGIN_LEFT_RIGHT,
)


def test_normalize_h_align_only_left_or_center():
    assert normalize_h_align("left") == "left"
    assert normalize_h_align("bandiera") == "left"
    assert normalize_h_align("center") == "center"
    assert normalize_h_align(None) == "center"
    # right is intentionally unsupported (social UI lives there) → center.
    assert normalize_h_align("right") == "center"
    assert normalize_h_align("garbage") == "center"


@pytest.mark.parametrize("vpos,center_an", [("top", 8), ("center", 5), ("bottom", 2)])
def test_alignment_center_uses_symmetric_edge_margins(vpos, center_an):
    an, ml, mr = ass_alignment_and_margins(vpos, "center")
    assert an == center_an
    assert ml == _SUB_MARGIN_EDGE and mr == _SUB_MARGIN_EDGE


@pytest.mark.parametrize("vpos,left_an", [("top", 7), ("center", 4), ("bottom", 1)])
def test_alignment_left_drops_one_and_widens_right_margin(vpos, left_an):
    an, ml, mr = ass_alignment_and_margins(vpos, "left")
    assert an == left_an
    # left keeps a small edge margin but a wider right margin so ragged-left text
    # stays clear of the right-edge social buttons.
    assert ml == _SUB_MARGIN_EDGE
    assert mr == _SUB_MARGIN_LEFT_RIGHT
    assert mr > ml


def _toy_transcript():
    return {"segments": [{"words": [
        {"word": "hello", "start": 0.0, "end": 0.4},
        {"word": "world", "start": 0.4, "end": 0.9},
    ]}]}


def _style_line(ass_path):
    with open(ass_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("Style: Viral,"):
                return line.strip()
    raise AssertionError("no Viral style line in .ass")


def test_karaoke_left_align_writes_left_an_and_margins(tmp_path):
    out = tmp_path / "k.ass"
    ok = generate_ass_karaoke(_toy_transcript(), 0.0, 2.0, str(out),
                              preset="hormozi_bold", position="bottom", align="left")
    assert ok
    fields = _style_line(str(out)).split(",")
    # …,Alignment,MarginL,MarginR,MarginV,Encoding  (last 5 fields)
    an, ml, mr, mv, enc = fields[-5:]
    assert an == "1"  # bottom-left
    assert int(ml) == _SUB_MARGIN_EDGE and int(mr) == _SUB_MARGIN_LEFT_RIGHT


def test_karaoke_center_align_is_symmetric(tmp_path):
    out = tmp_path / "k.ass"
    generate_ass_karaoke(_toy_transcript(), 0.0, 2.0, str(out),
                         preset="hormozi_bold", position="bottom", align="center")
    fields = _style_line(str(out)).split(",")
    an, ml, mr = fields[-5:][:3]
    assert an == "2"  # bottom-center
    assert int(ml) == int(mr) == _SUB_MARGIN_EDGE


def test_karaoke_outline_color_override_lands_in_ass(tmp_path):
    out = tmp_path / "k.ass"
    # classic_white ships a black outline; override it to red and confirm the
    # OutlineColour field changes (ASS BGR &HAABBGGRR → red = &H000000FF).
    generate_ass_karaoke(_toy_transcript(), 0.0, 2.0, str(out),
                         preset="classic_white", outline_color="#FF0000")
    line = _style_line(str(out))
    assert "&H000000FF" in line  # red in ASS &HAABBGGRR


def test_karaoke_rejects_bad_outline_color(tmp_path):
    out = tmp_path / "k.ass"
    with pytest.raises(ValueError):
        generate_ass_karaoke(_toy_transcript(), 0.0, 2.0, str(out),
                             outline_color="notacolor")
