"""Host tests for clippyme.domain.banner."""
import os
import sys
from types import SimpleNamespace

import pytest

from clippyme.domain import banner
from clippyme.domain.banner import (
    DEFAULT_BANNER_Y_PCT,
    banner_text,
    clamp_y_pct,
    letterbox_band_bottom,
    monitor_banner_params,
    sanitize_handle,
    suggest_banner,
)


@pytest.mark.parametrize("source, hint, expected", [
    ("https://kick.com/grenbaud", None, {"platform": "kick", "handle": "grenbaud"}),
    ("kick.com/GrenBaud", None, {"platform": "kick", "handle": "GrenBaud"}),
    ("https://twitch.tv/grenbaud", None, {"platform": "twitch", "handle": "grenbaud"}),
    ("https://www.youtube.com/@GrenBaudLounge", None,
     {"platform": "youtube", "handle": "GrenBaudLounge"}),
    ("https://youtube.com/channel/UC1234567890abcdefghABCD", None,
     {"platform": "youtube", "handle": "UC1234567890abcdefghABCD"}),
    ("https://youtube.com/c/SomeCustomName", None,
     {"platform": "youtube", "handle": "SomeCustomName"}),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", None,
     {"platform": "youtube", "handle": None}),
    ("https://youtu.be/dQw4w9WgXcQ", "@GrenBaudLounge",
     {"platform": "youtube", "handle": "GrenBaudLounge"}),
    ("kick", "grenbaud", {"platform": "kick", "handle": "grenbaud"}),
    ("youtube", "@Chan", {"platform": "youtube", "handle": "Chan"}),
    ("https://example.com/whatever", None, None),
    ("", None, None),
    ("just-a-handle", None, None),
])
def test_suggest_banner_table(source, hint, expected):
    assert suggest_banner(source, channel_hint=hint) == expected


def test_banner_text_per_platform():
    assert banner_text("kick", "grenbaud") == "kick.com/grenbaud"
    assert banner_text("twitch", "grenbaud") == "twitch.tv/grenbaud"
    assert banner_text("youtube", "GrenBaudLounge") == "youtube.com/@GrenBaudLounge"
    assert banner_text("youtube", "@GrenBaudLounge") == "youtube.com/@GrenBaudLounge"


def test_banner_text_unusable_returns_none():
    assert banner_text("kick", None) is None
    assert banner_text("kick", "") is None
    assert banner_text("bogus", "handle") is None


@pytest.mark.parametrize("raw, expected", [
    ("@grenbaud", "grenbaud"),
    ("@@grenbaud", "grenbaud"),
    ("https://kick.com/grenbaud", "grenbaud"),
    ("youtube.com/@Chan/videos", "Chan"),
    ("bad handle!!", "badhandle"),
    ("  spaced  ", "spaced"),
    ("a" * 80, "a" * 40),
    ("", None),
    ("@@@", None),
    (None, None),
])
def test_sanitize_handle(raw, expected):
    assert sanitize_handle(raw) == expected


def test_clamp_y_pct_bounds_and_default():
    assert clamp_y_pct(0.5) == 0.60
    assert clamp_y_pct(0.99) == 0.87
    assert clamp_y_pct(0.75) == 0.75
    assert clamp_y_pct(None) == DEFAULT_BANNER_Y_PCT
    assert clamp_y_pct("garbage") == DEFAULT_BANNER_Y_PCT


def test_letterbox_band_bottom_matches_4_3_crop():
    assert letterbox_band_bottom(1080, 1920) == 1365


def test_monitor_banner_params_auto_from_channel():
    params = monitor_banner_params("kick", "grenbaud", None)
    assert params == {
        "enabled": True,
        "platform": "kick",
        "handle": "grenbaud",
        "y_pct": DEFAULT_BANNER_Y_PCT,
    }


def test_monitor_banner_params_youtube_handle():
    params = monitor_banner_params("youtube", "@GrenBaudLounge", None)
    assert params["platform"] == "youtube"
    assert params["handle"] == "GrenBaudLounge"


def test_monitor_banner_params_disabled_override():
    assert monitor_banner_params("kick", "grenbaud", {"enabled": False}) is None


def test_monitor_banner_params_override_handle_and_ypct():
    params = monitor_banner_params(
        "kick", "grenbaud", {"handle": "otherchan", "y_pct": 0.99}
    )
    assert params["handle"] == "otherchan"
    assert params["y_pct"] == 0.87


def test_rasterized_logo_cache_is_written_atomically(monkeypatch, tmp_path):
    assets = tmp_path / "assets"
    cache = tmp_path / "cache"
    assets.mkdir()
    (assets / "kick_logo.svg").write_text("<svg/>")
    writes = []

    def fake_svg2png(*, url, write_to, output_height):
        writes.append(write_to)
        with open(write_to, "wb") as file:
            file.write(b"png")

    monkeypatch.setattr(banner, "_ASSETS_DIR", str(assets))
    monkeypatch.setattr(banner, "BANNER_CACHE_DIR", str(cache))
    monkeypatch.setitem(sys.modules, "cairosvg", SimpleNamespace(svg2png=fake_svg2png))

    result = banner._rasterize_logo("kick", 56)
    assert result == str(cache / "kick_56.png")
    assert (cache / "kick_56.png").read_bytes() == b"png"
    assert writes and writes[0] != result
    assert not list(cache.glob("*.tmp"))


def test_banner_renders_use_distinct_temp_files(monkeypatch, tmp_path):
    import subprocess
    from clippyme.pipeline import media_probe

    video = tmp_path / "clip_1.mp4"
    video.write_bytes(b"video")
    seen = []

    monkeypatch.setattr(media_probe, "probe_dimensions", lambda path: (1080, 1920))

    def fake_render(platform, handle, width, out_path):
        seen.append(out_path)
        assert os.path.exists(out_path)
        return out_path, 200, 60

    monkeypatch.setattr(banner, "render_banner_png", fake_render)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)

    params = {"platform": "kick", "handle": "creator"}
    assert banner.add_banner_to_video(str(video), params, str(tmp_path / "out1.mp4"))
    assert banner.add_banner_to_video(str(video), params, str(tmp_path / "out2.mp4"))
    assert len(seen) == 2 and seen[0] != seen[1]
    assert all(not os.path.exists(path) for path in seen)
