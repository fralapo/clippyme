"""Captions parked in the black band of a reframe-OFF (letterbox) clip."""
from clippyme.editing.banner import letterbox_band_bottom
from clippyme.editing.compose import CAPTION_BAND_PAD, _letterbox_caption_band_top
from clippyme.editing.subtitles import generate_ass_karaoke


def _toy_transcript():
    return {"segments": [{"words": [
        {"word": "hello", "start": 0.0, "end": 0.4},
        {"word": "world", "start": 0.4, "end": 0.9},
    ]}]}


def _style_fields(ass_path):
    with open(ass_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("Style: Viral,"):
                return line.strip().split(",")
    raise AssertionError("no Viral style line in .ass")


def test_band_top_only_for_bannerless_letterbox_bottom_captions(monkeypatch):
    monkeypatch.setattr(
        "clippyme.media.media_probe.probe_dimensions", lambda _p: (1080, 1920))
    letterbox = {"reframe_mode": "disabled"}
    subs = {"position": "bottom"}

    expected = letterbox_band_bottom(1080, 1920) + CAPTION_BAND_PAD
    assert _letterbox_caption_band_top("c.mp4", letterbox, subs, False) == expected
    # A banner already fills the black band — leave the captions where they were.
    assert _letterbox_caption_band_top("c.mp4", letterbox, subs, True) is None
    # Cropped modes have no band at all.
    assert _letterbox_caption_band_top(
        "c.mp4", {"reframe_mode": "auto"}, subs, False) is None
    # An explicit top/center position is the user's own choice.
    assert _letterbox_caption_band_top(
        "c.mp4", letterbox, {"position": "top"}, False) is None


def test_band_top_anchors_the_caption_to_the_top(tmp_path):
    out = tmp_path / "k.ass"
    generate_ass_karaoke(_toy_transcript(), 0.0, 2.0, str(out),
                         preset="hormozi_bold", position="bottom", align="left",
                         band_top=1389)
    an, _ml, _mr, mv, _enc = _style_fields(str(out))[-5:]
    assert an == "7"          # top-left anchor, so MarginV counts from the top
    assert int(mv) == 1389
