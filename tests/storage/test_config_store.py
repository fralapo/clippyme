"""Tests for clippyme.storage.config_store.

Covers core config round-trip, env-var fallback, HF_TOKEN aliasing, Zernio
namespace isolation, masking, and corrupt/missing-file resilience. All I/O is
redirected to a tmp file via monkeypatch so the real data/config.json is never
touched.
"""
import json
import os

import pytest

from clippyme.storage import config_store


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """Point config_store at an isolated tmp config file."""
    data_dir = tmp_path / "data"
    cfg = data_dir / "config.json"
    monkeypatch.setattr(config_store, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(config_store, "CONFIG_FILE", str(cfg))
    return cfg


def test_read_raw_missing_file_returns_empty(tmp_config):
    assert config_store._read_raw_config() == {}


def test_read_raw_corrupt_json_returns_empty(tmp_config):
    tmp_config.parent.mkdir(parents=True, exist_ok=True)
    tmp_config.write_text("{not valid json")
    assert config_store._read_raw_config() == {}


def test_save_and_load_core_keys(tmp_config, monkeypatch):
    # Clear env so file values are what we read back.
    for k in config_store.VALID_CONFIG_KEYS:
        monkeypatch.delenv(k, raising=False)
    assert config_store.save_persistent_config({"GEMINI_API_KEY": "g-key"}) is True
    loaded = config_store.load_persistent_config()
    assert loaded["GEMINI_API_KEY"] == "g-key"
    # File on disk only stores known keys.
    on_disk = json.loads(tmp_config.read_text())
    assert on_disk["GEMINI_API_KEY"] == "g-key"


def test_unknown_keys_are_dropped(tmp_config, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config_store.save_persistent_config({"GEMINI_API_KEY": "g", "BOGUS": "x"})
    on_disk = json.loads(tmp_config.read_text())
    assert "BOGUS" not in on_disk


def test_env_fallback_when_no_file(tmp_config, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    loaded = config_store.load_persistent_config()
    assert loaded["GEMINI_API_KEY"] == "from-env"


def test_hf_token_alias_normalization(tmp_config, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    config_store.save_persistent_config({"HUGGINGFACE_TOKEN": "hf-123"})
    loaded = config_store.load_persistent_config()
    assert loaded["HF_TOKEN"] == "hf-123"
    # Mirrored into the long form for libraries that only read it.
    assert os.environ.get("HUGGINGFACE_TOKEN") == "hf-123"


def test_clearing_key_with_empty_string(tmp_config, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config_store.save_persistent_config({"GEMINI_API_KEY": "g"})
    config_store.save_persistent_config({"GEMINI_API_KEY": ""})
    on_disk = json.loads(tmp_config.read_text())
    assert "GEMINI_API_KEY" not in on_disk


def test_zernio_namespace_isolated_from_core(tmp_config, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config_store.save_persistent_config({"GEMINI_API_KEY": "g"})
    config_store.save_zernio_config(api_key="sk_secretkey_1234", timezone="Europe/Rome")
    # Updating core config must NOT wipe the zernio namespace.
    config_store.save_persistent_config({"GEMINI_API_KEY": "g2"})
    z = config_store.load_zernio_config()
    assert z["api_key"] == "sk_secretkey_1234"
    assert z["timezone"] == "Europe/Rome"


def test_zernio_accounts_merge_and_clear(tmp_config):
    config_store.save_zernio_config(accounts={"tiktok": "tt1", "youtube": "yt1"})
    config_store.save_zernio_config(accounts={"youtube": ""})  # clear youtube only
    z = config_store.load_zernio_config()
    assert z["accounts"] == {"tiktok": "tt1"}


def test_zernio_status_masks_key(tmp_config):
    config_store.save_zernio_config(api_key="sk_abcdef_longenough_key")
    status = config_store.zernio_config_status()
    assert status["configured"] is True
    assert "..." in status["api_key_masked"]
    assert "longenough" not in status["api_key_masked"]


def test_zernio_status_unconfigured(tmp_config):
    status = config_store.zernio_config_status()
    assert status["configured"] is False
    assert status["api_key_masked"] == ""
