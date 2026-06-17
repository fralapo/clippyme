"""Unit tests for clippyme.integrations.auto_editor_updater.

Covers the pure/mockable helpers (no real GitHub calls, no real binary):
asset-name detection per platform, local-version parsing, latest-tag fetch
with the ``v`` prefix stripped, version equality, and graceful failure when
GitHub is unreachable.
"""
import subprocess

import pytest

# auto_editor_updater hard-imports fcntl (Unix-only) at module load for its
# file lock, so the whole module is unimportable on Windows. The binary it
# manages is Linux-only anyway; skip on platforms without fcntl (CI is Linux).
pytest.importorskip("fcntl")

import clippyme.integrations.auto_editor_updater as au  # noqa: E402


def test_versions_equal_strips_v_prefix():
    assert au._versions_equal("v30.1.0", "30.1.0") is True
    assert au._versions_equal("30.1.0", "30.1.0 ") is True
    assert au._versions_equal("30.1.0", "30.2.0") is False


def test_versions_equal_none_is_false():
    assert au._versions_equal(None, "30.1.0") is False
    assert au._versions_equal("30.1.0", None) is False


def test_detect_asset_name_linux_x86(monkeypatch):
    monkeypatch.setattr(au.platform, "system", lambda: "Linux")
    monkeypatch.setattr(au.platform, "machine", lambda: "x86_64")
    assert au._detect_asset_name() == "auto-editor-linux-x86_64"


def test_detect_asset_name_linux_arm(monkeypatch):
    monkeypatch.setattr(au.platform, "system", lambda: "Linux")
    monkeypatch.setattr(au.platform, "machine", lambda: "aarch64")
    assert au._detect_asset_name() == "auto-editor-linux-aarch64"


def test_detect_asset_name_macos_arm(monkeypatch):
    monkeypatch.setattr(au.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(au.platform, "machine", lambda: "arm64")
    assert au._detect_asset_name() == "auto-editor-macos-arm64"


def test_detect_asset_name_unsupported(monkeypatch):
    monkeypatch.setattr(au.platform, "system", lambda: "Windows")
    monkeypatch.setattr(au.platform, "machine", lambda: "amd64")
    assert au._detect_asset_name() is None


def test_read_local_version_no_binary(monkeypatch):
    monkeypatch.setattr(au.shutil, "which", lambda _: None)
    assert au._read_local_version() is None


def test_read_local_version_parses_last_token(monkeypatch):
    monkeypatch.setattr(au.shutil, "which", lambda _: "/usr/local/bin/auto-editor")
    monkeypatch.setattr(au.subprocess, "check_output", lambda *a, **k: b"auto-editor 30.1.0")
    assert au._read_local_version() == "30.1.0"


def test_read_local_version_handles_subprocess_error(monkeypatch):
    monkeypatch.setattr(au.shutil, "which", lambda _: "/usr/local/bin/auto-editor")

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="auto-editor", timeout=10)

    monkeypatch.setattr(au.subprocess, "check_output", _boom)
    assert au._read_local_version() is None


def test_fetch_latest_release_tag_strips_v(monkeypatch):
    import io
    import json as _json

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    payload = _Resp(_json.dumps({"tag_name": "v30.5.0"}).encode())
    monkeypatch.setattr(au.urllib.request, "urlopen", lambda *a, **k: payload)
    assert au._fetch_latest_release_tag() == "30.5.0"


def test_fetch_latest_release_tag_handles_network_failure(monkeypatch):
    def _boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(au.urllib.request, "urlopen", _boom)
    assert au._fetch_latest_release_tag() is None
