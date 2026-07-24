"""Security, atomicity and concurrency tests for hook/font rendering."""
import io
import os

import pytest

from clippyme.domain import hooks


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_download_capped_atomically_writes_valid_font(monkeypatch, tmp_path):
    payload = b"\x00\x01\x00\x00font-data"
    monkeypatch.setattr(hooks._FONT_OPENER, "open", lambda *a, **k: Response(payload))
    destination = tmp_path / "font.ttf"
    request = hooks.urllib.request.Request(hooks.FONT_URL)
    hooks._download_capped(request, str(destination))
    assert destination.read_bytes() == payload
    assert not list(tmp_path.glob(".font-*.tmp"))


def test_failed_download_preserves_existing_font(monkeypatch, tmp_path):
    destination = tmp_path / "font.ttf"
    destination.write_bytes(b"old-font")
    monkeypatch.setattr(hooks, "_FONT_MAX_BYTES", 5)
    monkeypatch.setattr(
        hooks._FONT_OPENER,
        "open",
        lambda *a, **k: Response(b"\x00\x01\x00\x00too-large"),
    )
    request = hooks.urllib.request.Request(hooks.FONT_URL)
    with pytest.raises(RuntimeError, match="size cap"):
        hooks._download_capped(request, str(destination))
    assert destination.read_bytes() == b"old-font"
    assert not list(tmp_path.glob(".font-*.tmp"))


def test_download_rejects_untrusted_host_before_network(monkeypatch, tmp_path):
    monkeypatch.setattr(
        hooks._FONT_OPENER,
        "open",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network must not run")),
    )
    for url in (
        "https://evil.example/font.ttf",
        "https://user@github.com/font.ttf",
        "https://github.com:444/font.ttf",
    ):
        request = hooks.urllib.request.Request(url)
        with pytest.raises(RuntimeError, match="untrusted"):
            hooks._download_capped(request, str(tmp_path / "font.ttf"))


def test_public_download_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("CLIPPYME_RUNTIME_FONT_DOWNLOAD", raising=False)
    monkeypatch.setattr(hooks, "FONT_DIR", str(tmp_path))
    monkeypatch.setattr(hooks, "FONT_PATH", str(tmp_path / "missing.ttf"))
    monkeypatch.setattr(
        hooks,
        "_download_capped",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network must stay disabled")),
    )
    hooks.download_font_if_needed()
    assert not (tmp_path / "missing.ttf").exists()


def test_font_name_cannot_escape_font_directories(monkeypatch, tmp_path):
    fallback = tmp_path / "fallback.ttf"
    fallback.write_bytes(b"not-used")
    outside = tmp_path / "secret.ttf"
    outside.write_bytes(b"secret")
    monkeypatch.setattr(hooks, "FONT_DIR", str(tmp_path / "fonts"))
    monkeypatch.setattr(hooks, "FONT_PATH", str(fallback))
    monkeypatch.setattr(hooks, "download_font_if_needed", lambda: None)

    assert hooks._resolve_hook_font_path("../secret") == str(fallback)
    assert hooks._resolve_hook_font_path(str(outside.with_suffix(""))) == str(fallback)


def test_overlong_word_is_wrapped_to_target_width(monkeypatch, tmp_path):
    monkeypatch.setattr(hooks, "_resolve_hook_font_path", lambda name: str(tmp_path / "missing.ttf"))
    output = tmp_path / "hook.png"
    _, width, height = hooks.create_hook_image(
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

    monkeypatch.setattr(hooks.subprocess, "check_output", lambda *a, **k: b"1080x1920")

    def fake_create(text, target_width, output_image_path, **kwargs):
        seen.append(output_image_path)
        assert os.path.exists(output_image_path)
        return output_image_path, 100, 50

    monkeypatch.setattr(hooks, "create_hook_image", fake_create)
    monkeypatch.setattr(hooks.subprocess, "run", lambda *a, **k: None)

    assert hooks.add_hook_to_video(str(video), "one", str(tmp_path / "out1.mp4")) is True
    assert hooks.add_hook_to_video(str(video), "two", str(tmp_path / "out2.mp4")) is True
    assert len(seen) == 2
    assert seen[0] != seen[1]
    assert all(not os.path.exists(path) for path in seen)
