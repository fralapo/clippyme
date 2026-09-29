"""Classic (SRT) subtitle margins must land where the karaoke ones do.

The classic path renders an SRT with `force_style`. ffmpeg turns an SRT into an
ASS script with PlayRes 384x288 and libass scales that script to the frame, so
a margin written in the 1080x1920 frame space the karaoke path uses (MarginV
350) ends up 350 * 1920/288 = 2333 px from the bottom edge: off screen. These
tests read the real force_style and map it back to frame pixels.
"""
import re

import pytest

from clippyme.editing import subtitles as subs

FRAME_W, FRAME_H = 1080, 1920
SRT_PLAYRES_X, SRT_PLAYRES_Y = 384, 288  # what ffmpeg gives an SRT (checked in Docker)


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


def _frame_px(style, key):
    scale = FRAME_H / SRT_PLAYRES_Y if key == "MarginV" else FRAME_W / SRT_PLAYRES_X
    return int(style[key]) * scale


@pytest.mark.parametrize("alignment", ["bottom", "top"])
def test_classic_vertical_margin_matches_karaoke_in_frame_pixels(tmp_path, monkeypatch, alignment):
    style = _classic_force_style(tmp_path, monkeypatch, alignment=alignment)
    assert _frame_px(style, "MarginV") == pytest.approx(350, abs=FRAME_H / SRT_PLAYRES_Y)


def test_classic_offset_moves_caption_by_the_same_frame_distance_as_karaoke(tmp_path, monkeypatch):
    style = _classic_force_style(tmp_path, monkeypatch, alignment="bottom", offset_y=10)
    expected = subs._offset_margin("bottom", 350, 10)  # karaoke MarginV, frame px
    assert _frame_px(style, "MarginV") == pytest.approx(expected, abs=FRAME_H / SRT_PLAYRES_Y)


@pytest.mark.parametrize("h_align, left, right", [
    ("center", subs._SUB_MARGIN_EDGE, subs._SUB_MARGIN_EDGE),
    ("left", subs._SUB_MARGIN_EDGE, subs._SUB_MARGIN_LEFT_RIGHT),
])
def test_classic_side_margins_match_karaoke_in_frame_pixels(tmp_path, monkeypatch, h_align, left, right):
    style = _classic_force_style(tmp_path, monkeypatch, h_align=h_align)
    assert _frame_px(style, "MarginL") == pytest.approx(left, abs=FRAME_W / SRT_PLAYRES_X)
    assert _frame_px(style, "MarginR") == pytest.approx(right, abs=FRAME_W / SRT_PLAYRES_X)


def test_classic_font_size_and_style_fields_are_unchanged(tmp_path, monkeypatch):
    style = _classic_force_style(tmp_path, monkeypatch, fontsize=16, border_width=2)
    assert style["Fontsize"] == "13"  # int(16 * 0.85), as before
    assert style["Outline"] == "2" and style["Shadow"] == "0" and style["Bold"] == "1"
    assert style["Alignment"] == "2"


def test_karaoke_margins_stay_in_frame_space(tmp_path):
    ass = tmp_path / "k.ass"
    transcript = {"segments": [{"words": [{"word": "hello", "start": 0.0, "end": 0.5}]}]}
    subs.generate_ass_karaoke(transcript, 0, 1, str(ass), preset="classic_white")
    text = ass.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in text and "PlayResY: 1920" in text
    fields = next(ln for ln in text.splitlines() if ln.startswith("Style: Viral,")).split(",")
    assert fields[-4:-1] == [str(subs._SUB_MARGIN_EDGE), str(subs._SUB_MARGIN_EDGE), "350"]
