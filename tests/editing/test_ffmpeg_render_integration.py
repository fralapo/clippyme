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