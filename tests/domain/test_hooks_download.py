"""Security and atomicity tests for optional runtime font downloads."""
import io

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
    request = hooks.urllib.request.Request("https://evil.example/font.ttf")
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
