"""Host tests for clippyme.domain.banner — pure logic only.

The render/ffmpeg/cairosvg paths are imported lazily inside their functions, so
importing this module (and everything tested here) needs no PIL / cairosvg /
ffmpeg. Rendering is exercised by the Docker integration suite.
"""
import pytest

from clippyme.domain.banner import (
    DEFAULT_BANNER_Y_PCT,
    banner_text,
    clamp_y_pct,
    letterbox_band_bottom,
    monitor_banner_params,
    sanitize_handle,
    suggest_banner,
)


# --- suggest_banner URL-parsing table --------------------------------------

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
    # watch URLs carry no handle → None unless a hint supplies one
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", None,
     {"platform": "youtube", "handle": None}),
    ("https://youtu.be/dQw4w9WgXcQ", "@GrenBaudLounge",
     {"platform": "youtube", "handle": "GrenBaudLounge"}),
    # bare platform name + hint (the monitor path)
    ("kick", "grenbaud", {"platform": "kick", "handle": "grenbaud"}),
    ("youtube", "@Chan", {"platform": "youtube", "handle": "Chan"}),
    # unknown / junk → None
    ("https://example.com/whatever", None, None),
    ("", None, None),
    ("just-a-handle", None, None),
])
def test_suggest_banner_table(source, hint, expected):
    assert suggest_banner(source, channel_hint=hint) == expected


# --- banner_text -----------------------------------------------------------

def test_banner_text_per_platform():
    assert banner_text("kick", "grenbaud") == "kick.com/grenbaud"
    assert banner_text("twitch", "grenbaud") == "twitch.tv/grenbaud"
    # youtube ensures a single '@'
    assert banner_text("youtube", "GrenBaudLounge") == "youtube.com/@GrenBaudLounge"
    assert banner_text("youtube", "@GrenBaudLounge") == "youtube.com/@GrenBaudLounge"


def test_banner_text_unusable_returns_none():
    assert banner_text("kick", None) is None
    assert banner_text("kick", "") is None
    assert banner_text("bogus", "handle") is None


# --- handle sanitization ---------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("@grenbaud", "grenbaud"),
    ("@@grenbaud", "grenbaud"),
    ("https://kick.com/grenbaud", "grenbaud"),
    ("youtube.com/@Chan/videos", "Chan"),
    ("bad handle!!", "badhandle"),
    ("  spaced  ", "spaced"),
    ("a" * 80, "a" * 40),           # length cap
    ("", None),
    ("@@@", None),
    (None, None),
])
def test_sanitize_handle(raw, expected):
    assert sanitize_handle(raw) == expected


# --- clamp_y_pct -----------------------------------------------------------

def test_clamp_y_pct_bounds_and_default():
    assert clamp_y_pct(0.5) == 0.60      # clamped up
    assert clamp_y_pct(0.99) == 0.87     # clamped down
    assert clamp_y_pct(0.75) == 0.75     # in range
    assert clamp_y_pct(None) == DEFAULT_BANNER_Y_PCT
    assert clamp_y_pct("garbage") == DEFAULT_BANNER_Y_PCT


# --- letterbox geometry ----------------------------------------------------

def test_letterbox_band_bottom_matches_4_3_crop():
    # disabled reframe = 4:3 crop scaled to full width → band height W*3/4,
    # centered. For 1080x1920 the band bottom is (1920 + 810)/2 = 1365.
    assert letterbox_band_bottom(1080, 1920) == 1365


# --- monitor banner default injection --------------------------------------

def test_monitor_banner_params_auto_from_channel():
    bp = monitor_banner_params("kick", "grenbaud", None)
    assert bp == {"enabled": True, "platform": "kick", "handle": "grenbaud",
                  "y_pct": DEFAULT_BANNER_Y_PCT}


def test_monitor_banner_params_youtube_handle():
    bp = monitor_banner_params("youtube", "@GrenBaudLounge", None)
    assert bp["platform"] == "youtube"
    assert bp["handle"] == "GrenBaudLounge"


def test_monitor_banner_params_disabled_override():
    assert monitor_banner_params("kick", "grenbaud", {"enabled": False}) is None


def test_monitor_banner_params_override_handle_and_ypct():
    bp = monitor_banner_params("kick", "grenbaud",
                               {"handle": "otherchan", "y_pct": 0.99})
    assert bp["handle"] == "otherchan"
    assert bp["y_pct"] == 0.87  # clamped
