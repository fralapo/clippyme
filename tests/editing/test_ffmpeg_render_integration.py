"""Integration smoke tests for the NEW ffmpeg render paths added across the
8 improvements. Pure helpers are host-tested elsewhere; these prove the actual
ffmpeg invocations are VALID and produce a playable file (real ffmpeg needed →
`integration`-marked, runs in Docker).

Covers:
  #1  smartcut afade segment render (audio fades at concat boundaries)
  #4  grade.apply_grade colour pass
  #5  hooks.add_hook_to_video animated entrance (build_hook_overlay_filter)
  libass font selection: every subtitle preset renders its bundled font
"""
import os
import subprocess

import pytest

pytestmark = pytest.mark.integration


def _has_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False


def _make_clip(path, dur=2):
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={dur}:size=320x240:rate=25",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _streams(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", path]
    ).decode()
    return out.split()


@pytest.fixture()
def clip(tmp_path):
    if not _has_ffmpeg():
        pytest.skip("ffmpeg not available")
    p = str(tmp_path / "src.mp4")
    _make_clip(p)
    assert os.path.getsize(p) > 0
    return p


def test_grade_renders(clip, tmp_path):
    from clippyme.editing.grade import apply_grade

    out = str(tmp_path / "graded.mp4")
    assert apply_grade(clip, out, "warm_cinematic") is True
    assert os.path.getsize(out) > 0
    assert "video" in _streams(out)


def test_grade_none_is_noop(clip, tmp_path):
    from clippyme.editing.grade import apply_grade

    out = str(tmp_path / "none.mp4")
    assert apply_grade(clip, out, "none") is False
    assert not os.path.exists(out)


def test_animated_hook_renders(clip, tmp_path):
    from clippyme.editing.hook_overlay import add_hook_to_video

    out = str(tmp_path / "hooked.mp4")
    ok = add_hook_to_video(clip, "HELLO WORLD", out, position="top",
                           style={"animate": True})
    assert ok is True
    assert os.path.getsize(out) > 0
    s = _streams(out)
    assert "video" in s and "audio" in s


def test_static_hook_still_renders(clip, tmp_path):
    from clippyme.editing.hook_overlay import add_hook_to_video

    out = str(tmp_path / "hooked_static.mp4")
    assert add_hook_to_video(clip, "STATIC", out, style={"animate": False}) is True
    assert os.path.getsize(out) > 0


def test_smartcut_afade_segments_render(clip, tmp_path):
    from clippyme.editing.smartcut import _render_with_ffmpeg

    out = str(tmp_path / "cut.mp4")
    # Two kept segments → one internal concat boundary that must fade, not pop.
    ok = _render_with_ffmpeg(clip, [(0.0, 0.8), (1.2, 2.0)], out)
    assert ok is True
    assert os.path.getsize(out) > 0
    assert "audio" in _streams(out)


def _make_logo_png(path):
    from PIL import Image
    Image.new("RGBA", (64, 64), (255, 0, 0, 200)).save(path)


def test_hook_plus_logo_single_pass_renders(clip, tmp_path):
    """Wave-5 fusion: hook + brand logo composited in ONE encode."""
    from clippyme.editing.hook_overlay import add_hook_to_video

    logo_png = str(tmp_path / "logo.png")
    _make_logo_png(logo_png)
    out = str(tmp_path / "hook_logo.mp4")
    ok = add_hook_to_video(
        clip, "BRANDED", out, position="top", style={"animate": False},
        logo={"path": logo_png, "position": "top-right",
              "scale": 0.2, "opacity": 0.9, "margin": 0.04},
    )
    assert ok is True
    assert os.path.getsize(out) > 0
    s = _streams(out)
    assert "video" in s and "audio" in s


def test_hook_plus_logo_animated_renders(clip, tmp_path):
    from clippyme.editing.hook_overlay import add_hook_to_video

    logo_png = str(tmp_path / "logo.png")
    _make_logo_png(logo_png)
    out = str(tmp_path / "hook_logo_anim.mp4")
    ok = add_hook_to_video(
        clip, "ANIMATED", out, position="top", style={"animate": True},
        logo={"path": logo_png, "position": "bottom-right", "scale": 0.15},
    )
    assert ok is True
    assert os.path.getsize(out) > 0


def test_burn_subtitles_with_grade_prevf_renders(clip, tmp_path):
    """Wave-5 fusion: grade chain rides as pre_vf on the subtitle burn."""
    from clippyme.editing.grade import build_grade_filter
    from clippyme.editing.subtitles import burn_subtitles

    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,500\nHello grade\n",
                   encoding="utf-8")
    out = str(tmp_path / "graded_subs.mp4")
    ok = burn_subtitles(clip, str(srt), out,
                        pre_vf=build_grade_filter("warm_cinematic"))
    assert ok is True
    assert os.path.getsize(out) > 0
    assert "video" in _streams(out)


def _libass_picks(stderr):
    """Fonts libass selected, from ffmpeg's verbose `fontselect:` lines. A font
    loaded from fontsdir shows its PostScript name; a fallback shows a path."""
    import re
    return [m.strip() for m in re.findall(r"fontselect: \([^)]*\) -> ([^,]+),", stderr)]


def _verbose_ffmpeg(monkeypatch, subs):
    logs = []
    real_run = subprocess.run

    def run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "ffmpeg":
            cmd = ["ffmpeg", "-v", "verbose", *cmd[1:]]
        result = real_run(cmd, *args, **kwargs)
        logs.append(result.stderr.decode(errors="replace"))
        return result

    monkeypatch.setattr(subs.subprocess, "run", run)
    return logs


def test_libass_renders_every_preset_with_its_bundled_font(clip, tmp_path, monkeypatch):
    """Presets name fonts by file stem; libass must load that file, not fall
    back to a system font (it used to render every preset in DejaVu Sans)."""
    from clippyme.editing import subtitles as subs

    monkeypatch.setattr(subs, "USER_FONTS_DIR", str(tmp_path / "user_fonts"))
    transcript = {"segments": [{"words": [{"word": "Hello", "start": 0.0, "end": 1.0}]}]}
    logs = _verbose_ffmpeg(monkeypatch, subs)
    for preset, style in subs.SUBTITLE_PRESETS.items():
        ass = str(tmp_path / f"{preset}.ass")
        assert subs.generate_ass_karaoke(transcript, 0, 1.5, ass, preset=preset)
        assert subs.burn_subtitles(clip, ass, str(tmp_path / f"{preset}.mp4")) is True
        picks = _libass_picks(logs[-1])
        assert picks and set(picks) == {style["font"]}, (preset, picks)


@pytest.mark.parametrize("font", ["Montserrat-Black", "Montserrat-ExtraBold", "Poppins-Black"])
def test_srt_force_style_renders_the_chosen_bundled_font(clip, tmp_path, monkeypatch, font):
    from clippyme.editing import subtitles as subs

    monkeypatch.setattr(subs, "USER_FONTS_DIR", str(tmp_path / "user_fonts"))
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,500\nHello\n", encoding="utf-8")
    logs = _verbose_ffmpeg(monkeypatch, subs)
    assert subs.burn_subtitles(clip, str(srt), str(tmp_path / "out.mp4"), font_name=font) is True
    assert set(_libass_picks(logs[-1])) == {font}


def _dark_clip(path, size):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={size}:d=1.5:r=25",
                    "-pix_fmt", "yuv420p", path], check=True)


def _caption_box(video, png):
    """(frame size, bounding box of the bright caption pixels) at t=0.5 s."""
    from PIL import Image
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", video, "-frames:v", "1", png], check=True)
    image = Image.open(png).convert("L")
    return image.size, image.point(lambda v: 255 if v > 60 else 0).getbbox()


_LONG_CAPTION = "When everybody told me this would never work I kept building anyway"


@pytest.mark.parametrize("size", ["1080x1920", "720x1280"])
@pytest.mark.parametrize("text", ["Hello there", _LONG_CAPTION], ids=["short", "long"])
def test_classic_and_karaoke_captions_sit_in_the_same_bottom_safe_area(tmp_path, monkeypatch, size, text):
    """Classic captions used to render 2333 px above the bottom edge (off
    screen): MarginV 350 is frame space, the SRT script is 384x288."""
    from clippyme.editing import subtitles as subs

    monkeypatch.setattr(subs, "USER_FONTS_DIR", str(tmp_path / "user_fonts"))
    video = str(tmp_path / "in.mp4")
    _dark_clip(video, size)
    srt = tmp_path / "s.srt"
    srt.write_text(f"1\n00:00:00,000 --> 00:00:01,500\n{text}\n", encoding="utf-8")
    words = [{"word": w, "start": 0.0, "end": 1.5} for w in text.split()]
    ass = str(tmp_path / "k.ass")
    assert subs.generate_ass_karaoke({"segments": [{"words": words}]}, 0, 1.5, ass,
                                     preset="classic_white", mode="full_line")
    renders = {
        "classic": subs.burn_subtitles(video, str(srt), str(tmp_path / "c.mp4"), font_name="Montserrat-Black"),
        "karaoke": subs.burn_subtitles(video, ass, str(tmp_path / "k.mp4")),
    }
    assert all(ok is True for ok in renders.values())
    for name in renders:
        (w, h), box = _caption_box(str(tmp_path / f"{name[0]}.mp4"), str(tmp_path / f"{name}.png"))
        assert box, f"{name} caption is not in the frame"
        x0, y0, x1, y1 = box
        # Side safe zone: margins of 110 px per 1080 (a little less for glyph overhang).
        assert x0 >= 0.09 * w and w - x1 >= 0.09 * w, (name, box)
        # Bottom gap: MarginV 350 of 1920 plus the line's descent.
        assert 0.17 * h <= h - y1 <= 0.22 * h, (name, box)
        assert y0 > 0, (name, box)

# --- Classic caption scale: same frame-space meaning as karaoke --------------

def _grey_clip(path, size):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x808080:s={size}:d=1.5:r=25",
                    "-pix_fmt", "yuv420p", path], check=True)


def _ink_and_fill(video, png):
    """Bounding boxes on a grey frame: text + outline, and the white fill only."""
    from PIL import Image
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", video, "-frames:v", "1", png], check=True)
    image = Image.open(png).convert("L")
    ink = image.point(lambda v: 255 if abs(v - 128) > 40 else 0).getbbox()
    fill = image.point(lambda v: 255 if v > 200 else 0).getbbox()
    return image.size, ink, fill


def _render_classic(subs, tmp_path, size, text, name, **kwargs):
    video = str(tmp_path / f"grey{size}.mp4")
    if not os.path.exists(video):
        _grey_clip(video, size)
    srt = tmp_path / "s.srt"
    srt.write_text(f"1\n00:00:00,000 --> 00:00:01,500\n{text}\n", encoding="utf-8")
    out = str(tmp_path / f"{name}.mp4")
    assert subs.burn_subtitles(video, str(srt), out, **{"font_name": "Montserrat-Black", **kwargs}) is True
    return _ink_and_fill(out, str(tmp_path / f"{name}.png"))


def _render_karaoke(subs, tmp_path, size, text, name, **kwargs):
    video = str(tmp_path / f"grey{size}.mp4")
    if not os.path.exists(video):
        _grey_clip(video, size)
    words = [{"word": w, "start": 0.0, "end": 1.5} for w in text.split()]
    ass = str(tmp_path / f"{name}.ass")
    assert subs.generate_ass_karaoke({"segments": [{"words": words}]}, 0, 1.5, ass,
                                     **{"preset": "classic_white", "mode": "full_line", **kwargs})
    out = str(tmp_path / f"{name}.mp4")
    assert subs.burn_subtitles(video, ass, out) is True
    return _ink_and_fill(out, str(tmp_path / f"{name}.png"))


def _stroke(ink, fill):
    """Outline thickness per side, horizontal and vertical, in pixels."""
    return ((ink[2] - ink[0]) - (fill[2] - fill[0])) / 2, ((ink[3] - ink[1]) - (fill[3] - fill[1])) / 2


@pytest.fixture()
def subs_module(tmp_path, monkeypatch):
    if not _has_ffmpeg():
        pytest.skip("ffmpeg not available")
    from clippyme.editing import subtitles as subs
    monkeypatch.setattr(subs, "USER_FONTS_DIR", str(tmp_path / "user_fonts"))
    return subs


@pytest.mark.parametrize("font", ["Montserrat-Black", "Bangers-Regular", "Anton-Regular",
                                  "Poppins-Black", "Poppins-Medium"])
def test_classic_font_size_renders_like_karaoke(subs_module, tmp_path, font):
    """Slider 40 used to render classic glyphs 6.7x taller than karaoke 40.
    Classic keeps its 0.85 factor, so it must match karaoke at int(40 * 0.85)."""
    _, _, classic = _render_classic(subs_module, tmp_path, "1080x1920", "HELLO", "c", font_name=font, fontsize=40)
    _, _, karaoke = _render_karaoke(subs_module, tmp_path, "1080x1920", "hello", "k", font_name=font,
                                    font_size=int(40 * 0.85), outline_width=1)
    assert abs((classic[3] - classic[1]) - (karaoke[3] - karaoke[1])) <= 2, (font, classic, karaoke)


def test_classic_font_size_slider_is_monotonic_and_proportional(subs_module, tmp_path):
    heights = []
    for size in (20, 40, 60):
        _, _, fill = _render_classic(subs_module, tmp_path, "1080x1920", "HI", f"fs{size}", fontsize=size)
        heights.append(fill[3] - fill[1])
    assert heights[0] < heights[1] < heights[2], heights
    assert heights[2] / heights[0] == pytest.approx(int(60 * 0.85) / int(20 * 0.85), rel=0.1), heights


@pytest.mark.parametrize("border_width", [2, 6])
def test_classic_outline_renders_like_karaoke(subs_module, tmp_path, border_width):
    """The classic outline was drawn in the 384x288 SRT script: 2 became 5.6 px
    wide and 13.3 px tall on a 1080x1920 frame. It must match karaoke's stroke."""
    _, ink, fill = _render_classic(subs_module, tmp_path, "1080x1920", "HELLO", "c",
                                   fontsize=60, border_width=border_width)
    _, k_ink, k_fill = _render_karaoke(subs_module, tmp_path, "1080x1920", "hello", "k",
                                       font_size=int(60 * 0.85), outline_width=border_width)
    (cx, cy), (kx, ky) = _stroke(ink, fill), _stroke(k_ink, k_fill)
    assert abs(cx - kx) <= 1 and abs(cy - ky) <= 1, ((cx, cy), (kx, ky))


@pytest.mark.parametrize("kwargs", [{}, {"fontsize": 40, "border_width": 4}], ids=["auto", "explicit"])
def test_classic_caption_scale_is_resolution_independent(subs_module, tmp_path, kwargs):
    ratios = []
    for size in ("720x1280", "1080x1920", "1440x2560"):
        (_, h), ink, fill = _render_classic(subs_module, tmp_path, size, "HELLO", f"r{size}", **kwargs)
        ratios.append(((fill[3] - fill[1]) / h, _stroke(ink, fill)[0] / h, _stroke(ink, fill)[1] / h))
    for glyph, stroke_x, stroke_y in ratios[1:]:
        assert glyph == pytest.approx(ratios[0][0], abs=0.002), ratios
        assert stroke_x == pytest.approx(ratios[0][1], abs=0.0015), ratios
        assert stroke_y == pytest.approx(ratios[0][2], abs=0.0015), ratios


def test_classic_auto_font_size_is_unchanged(subs_module, tmp_path):
    """No size chosen: glyphs keep the height they always had (~2.1% of the frame)."""
    for size in ("720x1280", "1080x1920", "1440x2560"):
        (_, h), _, fill = _render_classic(subs_module, tmp_path, size, "HELLO WORLD", f"a{size}")
        assert (fill[3] - fill[1]) / h == pytest.approx(0.0207, abs=0.001), (size, fill)


@pytest.mark.parametrize("size", ["720x1280", "1080x1920", "1440x2560"])
def test_classic_center_offset_moves_the_caption(subs_module, tmp_path, size):
    """libass ignores MarginV for middle alignment: every nudge rendered at the
    exact centre. Like karaoke, the caption now moves (positive = down)."""
    tops = {}
    for offset in (-50, -25, 0, 25, 45):
        (_, h), ink, _ = _render_classic(subs_module, tmp_path, size, "HELLO WORLD", f"o{offset}",
                                         alignment="center", offset_y=offset)
        assert ink and ink[1] >= 0 and ink[3] <= h, (offset, ink)
        tops[offset] = ink[1] / h
    assert tops[-50] < tops[-25] < tops[0] < tops[25] < tops[45], tops
    # +/-25% of the height from the centre: the line moves by half the frame.
    assert tops[25] - tops[-25] == pytest.approx(0.5, abs=0.01), tops
    # -50 rests against the top safe edge (110 px of 1920) instead of the frame edge.
    assert 0.05 <= tops[-50] <= 0.08, tops


@pytest.mark.parametrize("size", ["720x1280", "1080x1920", "1440x2560"])
@pytest.mark.parametrize("kwargs", [{}, {"fontsize": 60}], ids=["auto", "slider60"])
def test_classic_long_caption_wraps_inside_the_safe_area(subs_module, tmp_path, size, kwargs):
    for vpos in ("bottom", "top"):
        (w, h), ink, _ = _render_classic(subs_module, tmp_path, size, _LONG_CAPTION, vpos, alignment=vpos, **kwargs)
        x0, y0, x1, y1 = ink
        assert x0 >= 0.09 * w and w - x1 >= 0.09 * w, (vpos, ink)
        if vpos == "bottom":
            assert 0.17 * h <= h - y1 <= 0.22 * h, (vpos, ink)
        else:
            assert 0.17 * h <= y0 <= 0.2 * h, (vpos, ink)


# --- Center position + vertical nudge: continuous and inside the frame ------

_MANY_LINES = "When everybody told me this would never work I kept building anyway every single day"
# One karaoke event (full_line groups up to 60 characters): 2 lines at 40, 3 at 90.
_KARAOKE_LINES = "When everybody told me this would never work I kept going"
_CENTER_CASES = [
    pytest.param("karaoke", "HELLO WORLD", {}, id="karaoke-1-line"),
    pytest.param("karaoke", _KARAOKE_LINES, {}, id="karaoke-2-lines"),
    pytest.param("karaoke", _KARAOKE_LINES, {"font_size": 90}, id="karaoke-3-lines"),
    pytest.param("classic", "HELLO WORLD", {}, id="classic-1-line"),
    pytest.param("classic", _MANY_LINES, {}, id="classic-4-lines"),
]


def _render_nudged(subs, tmp_path, mode, size, text, nudge, position="center", **kwargs):
    """(frame height, ink bbox) of a caption at `position` nudged by `nudge`."""
    name = f"{mode}{position}{nudge}"
    if mode == "karaoke":
        (_, h), ink, _ = _render_karaoke(subs, tmp_path, size, text, name, position=position,
                                         offset_y=nudge, **kwargs)
    else:
        (_, h), ink, _ = _render_classic(subs, tmp_path, size, text, name, alignment=position,
                                         offset_y=nudge, **kwargs)
    return h, ink


def _assert_inside(h, ink, what):
    # Whole caption (outline, shadow, box) visible and clear of the frame edge.
    assert ink, f"{what}: caption is not in the frame"
    assert ink[1] >= 0.05 * h and ink[3] <= 0.95 * h, (what, ink)


@pytest.mark.parametrize("size", ["720x1280", "1080x1920", "1440x2560"])
@pytest.mark.parametrize("mode, text, kwargs", _CENTER_CASES)
def test_center_nudge_extremes_keep_the_caption_in_frame(subs_module, tmp_path, mode, text, kwargs, size):
    """+50 used to put the caption below the frame and -50 flush against the top."""
    for nudge in (-50, -49, 49, 50):
        h, ink = _render_nudged(subs_module, tmp_path, mode, size, text, nudge, **kwargs)
        _assert_inside(h, ink, (mode, size, nudge))


@pytest.mark.parametrize("size", ["720x1280", "1080x1920", "1440x2560"])
@pytest.mark.parametrize("mode, text, kwargs", _CENTER_CASES)
def test_center_nudge_is_centred_at_zero_and_continuous(subs_module, tmp_path, mode, text, kwargs, size):
    """0 was centred by libass and +/-1 top-anchored: the caption jumped by half its height."""
    centres = {}
    for nudge in (-1, 0, 1, 10, 11):
        h, ink = _render_nudged(subs_module, tmp_path, mode, size, text, nudge, **kwargs)
        centres[nudge] = (ink[1] + ink[3]) / 2 / h
    # Glyphs sit a little off their line boxes' centre (ascent vs descent).
    assert centres[0] == pytest.approx(0.5, abs=0.006), centres
    for a, b in ((-1, 0), (0, 1), (10, 11)):
        assert centres[b] - centres[a] == pytest.approx(0.01, abs=0.003), centres


@pytest.mark.parametrize("mode, text, kwargs", _CENTER_CASES)
def test_center_nudge_moves_monotonically(subs_module, tmp_path, mode, text, kwargs):
    nudges = (-50, -40, -30, -20, -10, -1, 0, 1, 10, 20, 30, 40, 50)
    tops = [_render_nudged(subs_module, tmp_path, mode, "1080x1920", text, n, **kwargs)[1][1] for n in nudges]
    assert all(b >= a for a, b in zip(tops, tops[1:])), tops  # rests at the edges, never moves back
    middle = tops[nudges.index(-20):nudges.index(20) + 1]
    assert all(b > a for a, b in zip(middle, middle[1:])), tops


@pytest.mark.parametrize("preset", ["classic_white", "hormozi_bold", "neon_glow", "mrbeast_box",
                                    "minimal_clean", "fire_impact"])
def test_center_nudge_every_karaoke_preset_stays_in_frame(subs_module, tmp_path, preset):
    for font_size in (None, 90):
        for nudge in (-50, 0, 50):
            h, ink = _render_nudged(subs_module, tmp_path, "karaoke", "1080x1920", _KARAOKE_LINES, nudge,
                                    preset=preset, font_size=font_size)
            _assert_inside(h, ink, (preset, font_size, nudge))


@pytest.mark.parametrize("font", ["Montserrat-Black", "Bangers-Regular", "Anton-Regular",
                                  "Poppins-Black", "Poppins-Medium"])
def test_center_nudge_every_classic_font_stays_in_frame(subs_module, tmp_path, font):
    for nudge in (-50, 0, 50):
        h, ink = _render_nudged(subs_module, tmp_path, "classic", "1080x1920", _MANY_LINES, nudge, font_name=font)
        _assert_inside(h, ink, (font, nudge))


def test_center_nudge_keeps_the_classic_background_box_in_frame(subs_module, tmp_path):
    for nudge in (-50, 50):
        h, ink = _render_nudged(subs_module, tmp_path, "classic", "1080x1920", _MANY_LINES, nudge, bg_opacity=1.0)
        _assert_inside(h, ink, nudge)


# --- Top / bottom position + vertical nudge: whole block inside the frame ---

_EDGE_CASES = [
    pytest.param("karaoke", "HELLO WORLD", {}, id="karaoke-1-line"),
    pytest.param("karaoke", _KARAOKE_LINES, {}, id="karaoke-2-lines"),
    pytest.param("karaoke", _KARAOKE_LINES, {"font_size": 90}, id="karaoke-3-lines"),
    pytest.param("classic", "HELLO WORLD", {}, id="classic-1-line"),
    pytest.param("classic", _MANY_LINES, {}, id="classic-4-lines"),
]


@pytest.mark.parametrize("size", ["720x1280", "1080x1920", "1440x2560"])
@pytest.mark.parametrize("position", ["top", "bottom"])
@pytest.mark.parametrize("mode, text, kwargs", _EDGE_CASES)
def test_edge_nudge_keeps_the_caption_in_frame(subs_module, tmp_path, mode, text, kwargs, position, size):
    """Top below about -13 drew the caption above the frame (gone at -50);
    bottom from about +13 pushed it against the frame's bottom edge."""
    for nudge in (-50, -25, -14, 14, 25, 50):
        h, ink = _render_nudged(subs_module, tmp_path, mode, size, text, nudge, position, **kwargs)
        _assert_inside(h, ink, (mode, position, size, nudge))


@pytest.mark.parametrize("position", ["top", "bottom"])
@pytest.mark.parametrize("mode, text, kwargs", _EDGE_CASES)
def test_edge_nudge_moves_monotonically(subs_module, tmp_path, mode, text, kwargs, position):
    nudges = (-50, -40, -30, -20, -10, -5, 0, 5, 10, 20, 30, 40, 50)
    tops = []
    for n in nudges:
        h, ink = _render_nudged(subs_module, tmp_path, mode, "1080x1920", text, n, position, **kwargs)
        _assert_inside(h, ink, (mode, position, n))
        tops.append(ink[1])
    assert all(b >= a for a, b in zip(tops, tops[1:])), tops  # rests at the edges, never moves back
    middle = tops[nudges.index(-5):nudges.index(10) + 1]
    assert all(b > a for a, b in zip(middle, middle[1:])), tops


@pytest.mark.parametrize("preset", ["classic_white", "hormozi_bold", "neon_glow", "mrbeast_box",
                                    "minimal_clean", "fire_impact"])
def test_edge_nudge_every_karaoke_preset_stays_in_frame(subs_module, tmp_path, preset):
    for position in ("top", "bottom"):
        for font_size in (None, 90):
            for nudge in (-50, 50):
                h, ink = _render_nudged(subs_module, tmp_path, "karaoke", "1080x1920", _KARAOKE_LINES, nudge,
                                        position, preset=preset, font_size=font_size)
                _assert_inside(h, ink, (preset, position, font_size, nudge))


@pytest.mark.parametrize("font", ["Montserrat-Black", "Bangers-Regular", "Anton-Regular",
                                  "Poppins-Black", "Poppins-Medium"])
def test_edge_nudge_every_classic_font_stays_in_frame(subs_module, tmp_path, font):
    for position in ("top", "bottom"):
        for nudge in (-50, 50):
            h, ink = _render_nudged(subs_module, tmp_path, "classic", "1080x1920", _MANY_LINES, nudge,
                                    position, font_name=font)
            _assert_inside(h, ink, (font, position, nudge))


def test_edge_nudge_keeps_the_classic_background_box_in_frame(subs_module, tmp_path):
    for position in ("top", "bottom"):
        for nudge in (-50, 50):
            h, ink = _render_nudged(subs_module, tmp_path, "classic", "1080x1920", _MANY_LINES, nudge,
                                    position, bg_opacity=1.0)
            _assert_inside(h, ink, (position, nudge))


def test_letterbox_band_caption_nudge_stays_in_frame(subs_module, tmp_path):
    """Reframe-off clips park bottom captions under the video (a top anchor at
    the band): +50 used to push them below the frame."""
    for nudge in (-50, 0, 50):
        h, ink = _render_nudged(subs_module, tmp_path, "karaoke", "1080x1920", _KARAOKE_LINES, nudge,
                                "bottom", band_top=1290)
        _assert_inside(h, ink, nudge)
