"""Bundled fonts in `fonts/` must be real, correctly named font files.

Subtitle presets and hooks name a font by its file stem (`Montserrat-Black`),
which reaches libass as the ASS `Fontname` and Pillow as a path. A file that
is not a font (for example a saved HTML download page) makes libass fall back
to a system font without any error, so the output silently uses the wrong
typeface. Stdlib + Pillow only: no Docker, no fontconfig cache.
"""
import struct
from pathlib import Path

import pytest
from PIL import ImageFont

FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"
FONT_EXTS = {".ttf", ".otf", ".ttc"}
SFNT_MAGICS = (b"\x00\x01\x00\x00", b"OTTO", b"true")

# Fonts that presets, defaults and hooks reference by name:
# file stem -> (family, style, OS/2 usWeightClass).
EXPECTED = {
    "Anton-Regular": ("Anton", "Regular", 400),
    "Bangers-Regular": ("Bangers", "Regular", 400),
    "Montserrat-Black": ("Montserrat", "Black", 900),
    "Montserrat-ExtraBold": ("Montserrat", "ExtraBold", 800),
    "NotoSerif-Bold": ("Noto Serif", "Bold", 700),
    "Poppins-Black": ("Poppins", "Black", 900),
    "Poppins-Medium": ("Poppins", "Medium", 500),
}


def _font_files():
    return sorted(p for p in FONTS_DIR.iterdir() if p.suffix.lower() in FONT_EXTS)


def _tables(data):
    """Parse the sfnt table directory; raise ValueError if it is not a font."""
    if data[:4] not in SFNT_MAGICS:
        raise ValueError(f"not an sfnt font, starts with {data[:16]!r}")
    (count,) = struct.unpack(">H", data[4:6])
    if not 1 <= count <= 4096 or len(data) < 12 + 16 * count:
        raise ValueError("truncated table directory")
    tables = {}
    for i in range(count):
        tag, _, offset, length = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        if offset + length > len(data):
            raise ValueError(f"table {tag!r} out of bounds")
        tables[tag.decode("latin-1")] = data[offset:offset + length]
    return tables


def _postscript_name(name_table):
    _, count, strings = struct.unpack(">HHH", name_table[:6])
    for i in range(count):
        platform, _, _, name_id, length, offset = struct.unpack(
            ">HHHHHH", name_table[6 + 12 * i:18 + 12 * i]
        )
        if name_id == 6:
            raw = name_table[strings + offset:strings + offset + length]
            return raw.decode("utf-16-be" if platform in (0, 3) else "latin-1")
    return None


def test_bundled_font_dir_is_not_empty():
    names = {p.stem for p in _font_files()}
    assert set(EXPECTED) <= names


@pytest.mark.parametrize("path", _font_files(), ids=lambda p: p.name)
def test_every_bundled_font_is_a_real_font_named_after_its_postscript_name(path):
    data = path.read_bytes()
    head = data[:512].lstrip().lower()
    assert not head.startswith((b"<!doctype", b"<html", b"<?xml")), f"{path.name} is HTML/XML, not a font"
    tables = _tables(data)
    for required in ("name", "cmap", "OS/2"):
        assert required in tables, f"{path.name} lacks the {required} table"
    assert _postscript_name(tables["name"]) == path.stem


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_referenced_font_has_expected_family_style_and_weight(stem):
    family, style, weight = EXPECTED[stem]
    path = FONTS_DIR / f"{stem}.ttf"
    tables = _tables(path.read_bytes())
    (us_weight,) = struct.unpack(">H", tables["OS/2"][4:6])
    assert us_weight == weight
    assert "fvar" not in tables, "presets expect static fonts, not a renamed variable font"
    assert ImageFont.truetype(str(path), 48).getname() == (family, style)
