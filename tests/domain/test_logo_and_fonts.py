"""Logo overlay geometry + custom-font discovery (host-safe, no ffmpeg)."""
import os

from clippyme.domain.logo import logo_overlay_xy, DEFAULT_POSITION, _POSITIONS


def test_logo_corners_use_margin():
    x, y = logo_overlay_xy("top-left", 40)
    assert x == "40" and y == "40"
    x, y = logo_overlay_xy("bottom-right", 25)
    assert x == "main_w-overlay_w-25"
    assert y == "main_h-overlay_h-25"


def test_logo_center_ignores_margin():
    x, y = logo_overlay_xy("center", 99)
    assert x == "(main_w-overlay_w)/2"
    assert y == "(main_h-overlay_h)/2"


def test_logo_unknown_position_falls_back():
    assert logo_overlay_xy("nonsense", 10) == logo_overlay_xy(DEFAULT_POSITION, 10)


def test_logo_negative_margin_clamped_to_zero():
    x, y = logo_overlay_xy("top-left", -50)
    assert x == "0" and y == "0"


def test_all_positions_have_expressions():
    for pos in _POSITIONS:
        x, y = logo_overlay_xy(pos, 12)
        assert x and y


def test_list_available_fonts_includes_user_upload(tmp_path, monkeypatch):
    import clippyme.domain.subtitles as subs
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    bundled.mkdir()
    user.mkdir()
    (bundled / "Anton-Regular.ttf").write_bytes(b"\x00\x01\x00\x00")
    (user / "Stratos-Medium.otf").write_bytes(b"OTTO")
    (user / "notafont.txt").write_text("nope")
    monkeypatch.setattr(subs, "FONTS_DIR", str(bundled))
    monkeypatch.setattr(subs, "USER_FONTS_DIR", str(user))
    names = subs.list_available_fonts()
    assert "Anton-Regular" in names
    assert "Stratos-Medium" in names
    assert "notafont" not in names


def test_effective_fonts_dir_seeds_user_dir(tmp_path, monkeypatch):
    import clippyme.domain.subtitles as subs
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    bundled.mkdir()
    (bundled / "Anton-Regular.ttf").write_bytes(b"\x00\x01\x00\x00")
    monkeypatch.setattr(subs, "FONTS_DIR", str(bundled))
    monkeypatch.setattr(subs, "USER_FONTS_DIR", str(user))
    out = subs.effective_fonts_dir()
    assert out == str(user)
    assert os.path.exists(os.path.join(str(user), "Anton-Regular.ttf"))
