"""Behavioural tests for the config-family HTTP surface.

These routes (``/api/config`` + cookies/fonts/logo/zernio/models) were the one
state-changing surface with **zero** endpoint coverage. They are guarded by
``require_trusted_config_request`` and do their own upload validation
(magic-byte checks, size caps, name allow-lists), so a silent regression here
is a security regression.

The suite is deliberately import-module-agnostic: every route is exercised
through the composed ``app`` object, so it holds whether the handlers live in
``app.py`` or in an extracted ``config_routes`` router. Disk writes are
isolated by ``chdir`` into a tmp dir (every path these handlers touch is
relative: ``data/cookies.txt``, ``data/logo.png``, ``data/fonts/``), and the
masking test is a real save→load round-trip — no monkeypatching of the
persistence layer.

TestClient is used WITHOUT its context manager so the FastAPI lifespan
(workers, journal recovery) never starts — we only want the routing + handler
bodies.
"""
import base64
import os
import struct

import pytest
from fastapi.testclient import TestClient

import clippyme.api.app as app_module
import clippyme.api.config_routes as config_module

# A trusted browser origin (in the default allow-list) — the gate accepts it
# via its Origin branch without needing a private client IP.
ORIGIN = {"Origin": "http://localhost:5175"}

# Tiny structurally-valid sfnt and a real 1x1 PNG.
TTF_MAGIC = (
    b"\x00\x01\x00\x00" + struct.pack(">HHHH", 1, 0, 0, 0)
    + b"head" + b"\x00" * 4 + struct.pack(">II", 28, 4) + b"data"
)
PNG_MAGIC = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
NETSCAPE_COOKIES = b"# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t0\tk\tv\n"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A trusted-origin client whose disk writes land under a tmp dir."""
    monkeypatch.chdir(tmp_path)
    # Config POST mirrors saved settings into the process environment. Track
    # those names so a provider-setting test cannot affect later test modules.
    for key in config_module.load_persistent_config().keys():
        monkeypatch.setenv(key, os.environ.get(key, ""))
    return TestClient(app_module.app, headers=ORIGIN)


# --- trusted-client gate ----------------------------------------------------

def test_cross_site_request_rejected(client):
    r = client.get("/api/config", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_untrusted_origin_rejected(client):
    r = client.get("/api/config", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


# --- /api/config round-trip + secret masking --------------------------------

def test_config_roundtrip_masks_secrets(client):
    """POST then GET: secret keys come back masked, plain flags verbatim."""
    fake_gemini_key = "test" + "x" * 8 + "fake"
    fake_openai_key = "openai-test-" + "x" * 20
    r = client.post(
        "/api/config",
        json={"keys": {
            "GEMINI_API_KEY": fake_gemini_key,
            "OPENAI_API_KEY": fake_openai_key,
            "LLM_PROVIDER": "openai",
            "LLM_MODEL": "gpt-4.1",
            "GEMINI_MODEL": "gemini-3.5-flash",
        }},
    )
    assert r.status_code == 200 and r.json()["success"] is True

    got = client.get("/api/config").json()
    # Fake keys are composed at runtime, so no key-shaped literal lands in git.
    assert got["GEMINI_API_KEY"] == f"{fake_gemini_key[:4]}...{fake_gemini_key[-4:]}"
    assert fake_gemini_key[4:-4] not in got["GEMINI_API_KEY"]
    # Non-secret flag passes through untouched.
    assert got["GEMINI_MODEL"] == "gemini-3.5-flash"
    assert got["LLM_PROVIDER"] == "openai"
    assert got["LLM_MODEL"] == "gpt-4.1"
    assert got["OPENAI_API_KEY"] == f"{fake_openai_key[:4]}...{fake_openai_key[-4:]}"


def test_config_short_secret_fully_masked(client):
    client.post("/api/config", json={"keys": {"HF_TOKEN": "short"}})
    got = client.get("/api/config").json()
    assert got["HF_TOKEN"] == "********"


def test_config_rejects_unknown_key(client):
    response = client.post("/api/config", json={"keys": {"GEMNI_API_KEY": "typo"}})
    assert response.status_code == 422


def test_config_rejects_invalid_provider_and_model(client):
    assert client.post(
        "/api/config", json={"keys": {"TRANSCRIPTION_PROVIDER": "other"}}
    ).status_code == 422
    assert client.post(
        "/api/config", json={"keys": {"GEMINI_MODEL": "not-gemini"}}
    ).status_code == 422
    assert client.post(
        "/api/config", json={"keys": {"LLM_MODEL": "--inject"}}
    ).status_code == 422


# --- /api/config/models (network call stubbed) ------------------------------

def test_models_lists_via_provided_key(client, monkeypatch):
    captured = {}

    def list_models(provider, key, *, force_refresh=False):
        captured.update(provider=provider, key=key, force_refresh=force_refresh)
        return {"models": [{"name": "gpt-4.1", "display_name": "gpt-4.1"}], "cached": False}

    monkeypatch.setattr(config_module, "list_provider_models", list_models)
    r = client.get("/api/config/models?provider=openai&force_refresh=true",
                   headers={"X-Provider-Key": "dummy"})
    assert r.status_code == 200
    assert r.json() == {"provider": "openai", "models": [
        {"name": "gpt-4.1", "display_name": "gpt-4.1"}], "cached": False}
    assert captured == {"provider": "openai", "key": "dummy", "force_refresh": True}


def test_models_use_saved_provider_key_without_returning_it(client, monkeypatch):
    fake_openrouter_key = "openrouter-test-" + "x" * 20
    client.post("/api/config", json={"keys": {
        "OPENROUTER_API_KEY": fake_openrouter_key,
        "LLM_PROVIDER": "openrouter",
    }})
    captured = {}

    def list_models(provider, key, *, force_refresh=False):
        captured.update(provider=provider, key=key)
        return {"models": [], "cached": False}

    monkeypatch.setattr(config_module, "list_provider_models", list_models)
    response = client.get("/api/config/models?provider=openrouter")
    assert response.status_code == 200
    assert response.json()["provider"] == "openrouter"
    assert fake_openrouter_key not in response.text
    assert captured == {"provider": "openrouter", "key": fake_openrouter_key}


# --- cookies ----------------------------------------------------------------

def test_cookies_upload_status_delete(client):
    assert client.get("/api/config/cookies/status").json() == {"configured": False}

    r = client.post("/api/config/cookies", files={"cookies_file": ("cookies.txt", NETSCAPE_COOKIES)})
    assert r.status_code == 200
    assert client.get("/api/config/cookies/status").json() == {"configured": True}

    assert client.request("DELETE", "/api/config/cookies").status_code == 200
    assert client.get("/api/config/cookies/status").json() == {"configured": False}


def test_cookies_reject_non_netscape(client):
    r = client.post("/api/config/cookies", files={"cookies_file": ("c.txt", b"just some random text no tabs")})
    assert r.status_code == 400


def test_cookies_reject_non_utf8(client):
    r = client.post("/api/config/cookies", files={"cookies_file": ("c.txt", b"\xff\xfe\x00bad")})
    assert r.status_code == 400


def test_cookies_reject_oversize(client):
    big = b"# Netscape HTTP Cookie File\n" + b"a\t" * (6 * 1024 * 1024)
    r = client.post("/api/config/cookies", files={"cookies_file": ("c.txt", big)})
    assert r.status_code == 413


# --- fonts ------------------------------------------------------------------

def test_font_upload_and_delete(client):
    r = client.post("/api/config/fonts", files={"font_file": ("Stratos.ttf", TTF_MAGIC)})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Stratos"
    assert "Stratos" in body["fonts"]

    assert client.request("DELETE", "/api/config/fonts/Stratos").status_code == 200


def test_uploaded_font_preview_requires_trust_and_token(client, tmp_path, monkeypatch):
    folder = tmp_path / "private-fonts"
    monkeypatch.setattr(config_module, "_USER_FONTS_DIR", str(folder))
    response = client.post("/api/config/fonts", files={"font_file": ("MyFace.otf", TTF_MAGIC)})
    assert response.status_code == 200
    preview = client.get("/api/config/fonts/MyFace/preview")
    assert preview.status_code == 200
    assert preview.content == TTF_MAGIC
    assert preview.headers["cache-control"] == "no-store"
    assert client.get("/api/config/fonts/MyFace/preview", headers={
        "Origin": "https://untrusted.example",
    }).status_code == 403
    monkeypatch.setenv("CLIPPYME_API_TOKEN", "test-font-access-token")
    assert client.get("/api/config/fonts/MyFace/preview").status_code == 401
    assert client.get("/api/config/fonts/MyFace/preview", headers={
        "X-API-Token": "test-font-access-token",
    }).status_code == 200


def test_uploaded_font_preview_rejects_other_files_and_symlinks(client, tmp_path, monkeypatch):
    folder = tmp_path / "private-fonts"
    folder.mkdir()
    monkeypatch.setattr(config_module, "_USER_FONTS_DIR", str(folder))
    assert client.get("/api/config/fonts/DoesNotExist/preview").status_code == 404
    assert client.get("/api/config/fonts/BadName%20%2Fpass/preview").status_code in (400, 404)
    (folder / "Unrelated.txt").write_text("private")
    assert client.get("/api/config/fonts/Unrelated/preview").status_code == 404
    outside = tmp_path / "secret.txt"
    outside.write_text("private material")
    os.symlink(outside, folder / "Escape.ttf")
    assert client.get("/api/config/fonts/Escape/preview").status_code == 404


def test_font_reject_bad_extension(client):
    r = client.post("/api/config/fonts", files={"font_file": ("evil.exe", TTF_MAGIC)})
    assert r.status_code == 400


def test_font_reject_bad_name(client):
    r = client.post("/api/config/fonts", files={"font_file": ("../etc/passwd.ttf", TTF_MAGIC)})
    # basename strips the traversal; the resulting stem still fails the
    # allow-list or writes safely — either way it must never 200 with a path.
    assert r.status_code in (400, 200)
    if r.status_code == 200:
        assert "/" not in r.json()["name"]


def test_font_reject_non_font_bytes(client):
    r = client.post("/api/config/fonts", files={"font_file": ("fake.ttf", b"not a real font at all")})
    assert r.status_code == 400


def test_font_delete_missing_is_404(client):
    assert client.request("DELETE", "/api/config/fonts/DoesNotExist").status_code == 404


# --- logo -------------------------------------------------------------------

def test_logo_upload_status_delete(client):
    assert client.get("/api/config/logo/status").json() == {"configured": False}

    r = client.post("/api/config/logo", files={"logo_file": ("logo.png", PNG_MAGIC)})
    assert r.status_code == 200
    assert client.get("/api/config/logo/status").json() == {"configured": True}

    assert client.request("DELETE", "/api/config/logo").status_code == 200
    assert client.get("/api/config/logo/status").json() == {"configured": False}


def test_logo_reject_non_png(client):
    r = client.post("/api/config/logo", files={"logo_file": ("logo.png", b"GIF89a not a png")})
    assert r.status_code == 400


def test_logo_rejects_truncated_png(client):
    response = client.post(
        "/api/config/logo", files={"logo_file": ("logo.png", b"\x89PNG\r\n\x1a\n" + b"broken")}
    )
    assert response.status_code == 400


# --- zernio -----------------------------------------------------------------

def test_zernio_config_roundtrip(client):
    r = client.post(
        "/api/config/zernio",
        json={"api_key": "zk_test_secret_key", "accounts": {"tiktok": "acc1"}, "timezone": "Europe/Rome"},
    )
    assert r.status_code == 200
    status = r.json()
    # api_key must never echo verbatim.
    assert "zk_test_secret_key" not in str(status)

    got = client.get("/api/config/zernio")
    assert got.status_code == 200


def test_zernio_accounts_requires_key(client, monkeypatch):
    # No key configured (fresh tmp cwd) → 400 before any network call.
    monkeypatch.setattr(config_module, "load_zernio_config", lambda: {})
    r = client.get("/api/zernio/accounts")
    assert r.status_code == 400


def test_tiktok_creator_info_returns_only_validated_account_options(client, monkeypatch):
    monkeypatch.setattr(config_module, "load_zernio_config", lambda: {"api_key": "local-test-key"})

    class FakeZernioClient:
        def __init__(self, _api_key):
            pass

        def get_tiktok_creator_info(self, account_id):
            assert account_id == "creator_123"
            return {
                "creator": {"nickname": "Private nickname", "canPostMore": True},
                "privacyLevels": [
                    {"value": "FOLLOWER_OF_CREATOR", "label": "Followers"},
                    {"value": "", "label": "invalid"},
                    "invalid",
                ],
                "postingLimits": {
                    "maxVideoDurationSec": 600,
                    "interactionSettings": {"comment": True, "duet": False, "stitch": True, "unexpected": True},
                },
                "commercialContentTypes": ["private data not needed by the UI"],
            }

    monkeypatch.setattr("clippyme.integrations.social_publisher.ZernioClient", FakeZernioClient)
    response = client.get("/api/zernio/tiktok/creator-info?account_id=creator_123")
    assert response.status_code == 200
    assert response.json() == {
        "privacyLevels": [{"value": "FOLLOWER_OF_CREATOR", "label": "Followers"}],
        "interactionSettings": {"comment": True, "duet": False, "stitch": True},
        "canPostMore": True,
        "maxVideoDurationSec": 600,
    }


def test_tiktok_creator_info_rejects_unsafe_account_id_before_network(client, monkeypatch):
    monkeypatch.setattr(config_module, "load_zernio_config", lambda: {"api_key": "local-test-key"})
    response = client.get("/api/zernio/tiktok/creator-info?account_id=../accounts")
    assert response.status_code == 400
