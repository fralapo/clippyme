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


def test_auto_update_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AUTO_EDITOR_AUTO_UPDATE", raising=False)
    assert au.auto_update_enabled() is False


def test_auto_update_enabled_via_env(monkeypatch):
    monkeypatch.setenv("AUTO_EDITOR_AUTO_UPDATE", "1")
    assert au.auto_update_enabled() is True


def test_check_and_update_once_short_circuits_when_disabled(monkeypatch):
    # With the flag off, no network / asset detection must happen — the
    # function returns 'disabled' before touching GitHub (H1 regression).
    monkeypatch.delenv("AUTO_EDITOR_AUTO_UPDATE", raising=False)

    def _boom(*a, **k):
        raise AssertionError("network/asset access must not happen when disabled")

    monkeypatch.setattr(au, "_fetch_latest_release_tag", _boom)
    monkeypatch.setattr(au, "_detect_asset_name", _boom)
    monkeypatch.setattr(au, "_read_local_version", lambda: "30.1.0")
    result = au.check_and_update_once()
    assert result["action"] == "disabled"


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
    # The API fetch now goes through the no-redirect opener (M2), so patch that.
    monkeypatch.setattr(au._API_OPENER, "open", lambda *a, **k: payload)
    assert au._fetch_latest_release_tag() == "30.5.0"


def test_fetch_latest_release_parses_asset_digests(monkeypatch):
    import io
    import json as _json

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    body = {
        "tag_name": "v30.5.0",
        "assets": [
            {"name": "auto-editor-linux-x86_64",
             "browser_download_url": "https://example.test/dl/ae",
             "digest": "sha256:abc123"},
            {"name": "noname-skip"},
        ],
    }
    monkeypatch.setattr(au._API_OPENER, "open", lambda *a, **k: _Resp(_json.dumps(body).encode()))
    rel = au._fetch_latest_release()
    assert rel["tag"] == "30.5.0"
    assert rel["assets"]["auto-editor-linux-x86_64"]["digest"] == "sha256:abc123"
    assert rel["assets"]["auto-editor-linux-x86_64"]["url"] == "https://example.test/dl/ae"


def test_fetch_latest_release_tag_handles_network_failure(monkeypatch):
    def _boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(au._API_OPENER, "open", _boom)
    assert au._fetch_latest_release_tag() is None


def test_fetch_latest_release_rejects_oversized_response(monkeypatch):
    import io

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(au, "MAX_RELEASE_JSON_BYTES", 16)
    monkeypatch.setattr(au._API_OPENER, "open", lambda *a, **k: _Resp(b"{" + b"x" * 32))
    assert au._fetch_latest_release() is None


def test_verify_digest_match_mismatch_and_absent(tmp_path):
    import hashlib

    p = tmp_path / "bin"
    p.write_bytes(b"\x7fELFpayload")
    good = "sha256:" + hashlib.sha256(b"\x7fELFpayload").hexdigest()
    assert au._verify_digest(str(p), good) is True
    assert au._verify_digest(str(p), "sha256:" + "0" * 64) is False
    assert au._verify_digest(str(p), "sha256:deadbeef") is None
    # No digest / unsupported algo → None (caller installs with sanity-only).
    assert au._verify_digest(str(p), None) is None
    assert au._verify_digest(str(p), "md5:whatever") is None


def test_download_binary_refuses_missing_digest_before_network(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(au._ASSET_OPENER, "open", lambda *a, **k: called.append(1))
    target = tmp_path / "auto-editor"
    assert au._download_binary(
        "https://github.com/WyattBlue/auto-editor/releases/download/v1/asset",
        str(target),
        expected_digest=None,
    ) is False
    assert called == []
    assert not target.exists()


def test_check_update_refuses_release_asset_without_digest(monkeypatch):
    monkeypatch.setenv("AUTO_EDITOR_AUTO_UPDATE", "1")
    monkeypatch.setattr(au, "_detect_asset_name", lambda: "auto-editor-linux-x86_64")
    monkeypatch.setattr(au, "_read_local_version", lambda: "30.0.0")
    monkeypatch.setattr(
        au,
        "_fetch_latest_release",
        lambda: {
            "tag": "31.0.0",
            "assets": {
                "auto-editor-linux-x86_64": {
                    "url": "https://github.com/WyattBlue/auto-editor/releases/download/v31/asset",
                    "digest": None,
                }
            },
        },
    )
    monkeypatch.setattr(
        au,
        "_download_binary",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not download")),
    )
    result = au.check_and_update_once()
    assert result["action"] == "download_failed"
    assert "SHA256" in result["message"]
