"""Security, atomicity and concurrency tests for hook/font rendering."""
import io
import os

import pytest

from clippyme.editing import hook_overlay


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_download_capped_atomically_writes_valid_font(monkeypatch, tmp_path):
    payload = b"\x00\x01\x00\x00font-data"
    monkeypatch.setattr(hook_overlay._FONT_OPENER, "open", lambda *a, **k: Response(payload))
    destination = tmp_path / "font.ttf"
    request = hook_overlay.urllib.request.Request(hook_overlay.FONT_URL)
    hook_overlay._download_capped(request, str(destination))
    assert destination.read_bytes() == payload
    assert not list(tmp_path.glob(".font-*.tmp"))


def test_failed_download_preserves_existing_font(monkeypatch, tmp_path):
    destination = tmp_path / "font.ttf"
    destination.write_bytes(b"old-font")
    monkeypatch.setattr(hook_overlay, "_FONT_MAX_BYTES", 5)
    monkeypatch.setattr(
        hook_overlay._FONT_OPENER,
        "open",
        lambda *a, **k: Response(b"\x00\x01\x00\x00too-large"),
    )
    request = hook_overlay.urllib.request.Request(hook_overlay.FONT_URL)
    with pytest.raises(RuntimeError, match="size cap"):
        hook_overlay._download_capped(request, str(destination))
    assert destination.read_bytes() == b"old-font"
    assert not list(tmp_path.glob(".font-*.tmp"))


def test_download_rejects_untrusted_host_before_network(monkeypatch, tmp_path):
    monkeypatch.setattr(
        hook_overlay._FONT_OPENER,
        "open",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network must not run")),
    )
    for url in (
        "https://evil.example/font.ttf",
        "https://user@github.com/font.ttf",
        "https://github.com:444/font.ttf",
    ):
        request = hook_overlay.urllib.request.Request(url)
        with pytest.raises(RuntimeError, match="untrusted"):
            hook_overlay._download_capped(request, str(tmp_path / "font.ttf"))


def test_public_download_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("CLIPPYME_RUNTIME_FONT_DOWNLOAD", raising=False)
    monkeypatch.setattr(hook_overlay, "FONT_DIR", str(tmp_path))
    monkeypatch.setattr(hook_overlay, "FONT_PATH", str(tmp_path / "missing.ttf"))
    monkeypatch.setattr(
        hook_overlay,
        "_download_capped",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network must stay disabled")),
    )
    hook_overlay.download_font_if_needed()
    assert not (tmp_path / "missing.ttf").exists()


def test_font_name_cannot_escape_font_directories(monkeypatch, tmp_path):
    fallback = tmp_path / "fallback.ttf"
    fallback.write_bytes(b"not-used")
    outside = tmp_path / "secret.ttf"
    outside.write_bytes(b"secret")
    monkeypatch.setattr(hook_overlay, "FONT_DIR", str(tmp_path / "fonts"))
    monkeypatch.setattr(hook_overlay, "FONT_PATH", str(fallback))
    monkeypatch.setattr(hook_overlay, "download_font_if_needed", lambda: None)

    assert hook_overlay._resolve_hook_font_path("../secret") == str(fallback)
    assert hook_overlay._resolve_hook_font_path(str(outside.with_suffix(""))) == str(fallback)


def test_deleted_uploaded_font_falls_back_to_default_font(monkeypatch, tmp_path):
    # Goal 30: the dashboard previews a hook font missing from the live font
    # list with HOOK_BACKEND_DEFAULT_FONT, because this resolver falls back to
    # FONT_PATH for a valid name that no longer exists in either directory.
    from clippyme.editing import subtitles

    fallback = tmp_path / "NotoSerif-Bold.ttf"
    fallback.write_bytes(b"fallback")
    user_dir = tmp_path / "user_fonts"
    user_dir.mkdir()
    uploaded = user_dir / "MyBrand-Bold.ttf"
    uploaded.write_bytes(b"uploaded")
    monkeypatch.setattr(hook_overlay, "FONT_DIR", str(tmp_path / "fonts"))
    monkeypatch.setattr(hook_overlay, "FONT_PATH", str(fallback))
    monkeypatch.setattr(hook_overlay, "download_font_if_needed", lambda: None)
    monkeypatch.setattr(subtitles, "USER_FONTS_DIR", str(user_dir))

    assert hook_overlay._resolve_hook_font_path("MyBrand-Bold") == str(uploaded)
    uploaded.unlink()
    assert hook_overlay._resolve_hook_font_path("MyBrand-Bold") == str(fallback)


def test_verdana_has_no_hook_font_file_and_falls_back_to_noto_serif(monkeypatch, tmp_path):
    # Goal 31: the dashboard no longer offers Verdana for hooks and previews a
    # saved one with HOOK_BACKEND_DEFAULT_FONT, because no bundled or uploaded
    # Verdana file exists and this resolver never searches system fonts.
    from clippyme.editing import subtitles

    monkeypatch.setattr(subtitles, "USER_FONTS_DIR", str(tmp_path))
    monkeypatch.setattr(hook_overlay, "download_font_if_needed", lambda: None)

    assert hook_overlay._resolve_hook_font_path("Verdana") == hook_overlay.FONT_PATH
    assert os.path.basename(hook_overlay.FONT_PATH) == "NotoSerif-Bold.ttf"



def test_explicit_noto_serif_and_empty_font_resolve_to_the_same_hook_font(monkeypatch, tmp_path):
    # Goal 32: the dashboard hides the explicit NotoSerif-Bold hook choice as a
    # duplicate of "Default (serif)" ('') but keeps a saved explicit value, since
    # both resolve to the bundled FONT_PATH file.
    from clippyme.editing import subtitles

    monkeypatch.setattr(subtitles, "USER_FONTS_DIR", str(tmp_path))
    monkeypatch.setattr(hook_overlay, "download_font_if_needed", lambda: None)

    explicit = hook_overlay._resolve_hook_font_path("NotoSerif-Bold")
    default = hook_overlay._resolve_hook_font_path("")
    assert os.path.isfile(explicit)
    assert os.path.samefile(explicit, default)
    assert os.path.samefile(default, hook_overlay.FONT_PATH)

def test_overlong_word_is_wrapped_to_target_width(monkeypatch, tmp_path):
    monkeypatch.setattr(hook_overlay, "_resolve_hook_font_path", lambda name: str(tmp_path / "missing.ttf"))
    output = tmp_path / "hook.png"
    _, width, height = hook_overlay.create_hook_image(
        "A" * 1000,
        300,
        str(output),
        style={"shadow": False},
    )
    assert output.exists()
    assert width <= 340  # target width + the 20px canvas margin on both sides
    assert height > 40


def test_concurrent_hook_renders_use_distinct_temp_files(monkeypatch, tmp_path):
    video = tmp_path / "clip_1.mp4"
    video.write_bytes(b"video")
    seen = []

    monkeypatch.setattr(hook_overlay.subprocess, "check_output", lambda *a, **k: b"1080x1920")

    def fake_create(text, target_width, output_image_path, **kwargs):
        seen.append(output_image_path)
        assert os.path.exists(output_image_path)
        return output_image_path, 100, 50

    monkeypatch.setattr(hook_overlay, "create_hook_image", fake_create)
    monkeypatch.setattr(hook_overlay.subprocess, "run", lambda *a, **k: None)

    assert hook_overlay.add_hook_to_video(str(video), "one", str(tmp_path / "out1.mp4")) is True
    assert hook_overlay.add_hook_to_video(str(video), "two", str(tmp_path / "out2.mp4")) is True
    assert len(seen) == 2
    assert seen[0] != seen[1]
    assert all(not os.path.exists(path) for path in seen)


def test_montserrat_extrabold_resolves_to_its_own_bundled_hook_font(monkeypatch, tmp_path):
    # Goal 33: the dashboard previews the Montserrat-ExtraBold hook choice with
    # fonts/Montserrat-ExtraBold.ttf, so the renderer must burn that same file,
    # not the FONT_PATH fallback and not the Montserrat-Black file.
    from clippyme.editing import subtitles

    monkeypatch.setattr(subtitles, "USER_FONTS_DIR", str(tmp_path))
    monkeypatch.setattr(hook_overlay, "download_font_if_needed", lambda: None)

    extra_bold = hook_overlay._resolve_hook_font_path("Montserrat-ExtraBold")
    assert os.path.basename(extra_bold) == "Montserrat-ExtraBold.ttf"
    assert os.path.samefile(os.path.dirname(extra_bold), hook_overlay.FONT_DIR)
    assert not os.path.samefile(extra_bold, hook_overlay.FONT_PATH)
    assert not os.path.samefile(extra_bold, hook_overlay._resolve_hook_font_path("Montserrat-Black"))
