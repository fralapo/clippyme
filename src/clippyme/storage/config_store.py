"""Persistent configuration loader/saver for ClippyMe."""
import json
import logging
import os

logger = logging.getLogger("clippyme")

DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
VALID_CONFIG_KEYS = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "YOUTUBE_COOKIES",
    "HF_TOKEN",
    "DEEPGRAM_API_KEY",
    "TRANSCRIPTION_PROVIDER",  # "whisper" (default) or "deepgram"
)

# Zernio config lives in a separate namespace under the same config.json file
# so existing config flows aren't disturbed. Stored as a sub-object:
#   { "zernio": { "api_key": "sk_...", "accounts": {...}, "timezone": "..." } }
ZERNIO_CONFIG_NAMESPACE = "zernio"


def _read_raw_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Error reading config.json: %s", e)
        return {}


def _write_raw_config(data: dict) -> bool:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        # Write with mode 0o600 so the file (which holds Gemini, Deepgram and
        # Zernio API keys) is not world-readable under the default Docker umask.
        fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=4)
        return True
    except OSError as e:
        logger.error("Error writing config.json: %s", e)
        return False


def load_zernio_config() -> dict:
    """Return persisted Zernio settings (or an empty dict)."""
    raw = _read_raw_config()
    z = raw.get(ZERNIO_CONFIG_NAMESPACE) or {}
    return {
        "api_key": z.get("api_key", ""),
        "accounts": z.get("accounts", {}),
        "timezone": z.get("timezone", "Europe/Rome"),
    }


def save_zernio_config(api_key: str = None, accounts: dict = None, timezone: str = None) -> bool:
    """Merge-update Zernio settings. Pass None to leave a field unchanged.
    Pass empty string for api_key to clear it.
    """
    raw = _read_raw_config()
    current = raw.get(ZERNIO_CONFIG_NAMESPACE) or {}
    if api_key is not None:
        if api_key == "":
            current.pop("api_key", None)
        else:
            current["api_key"] = api_key
    if accounts is not None:
        # Merge so partial updates work
        merged = current.get("accounts") or {}
        for k, v in accounts.items():
            if v in (None, ""):
                merged.pop(k, None)
            else:
                merged[k] = v
        current["accounts"] = merged
    if timezone is not None:
        current["timezone"] = timezone
    raw[ZERNIO_CONFIG_NAMESPACE] = current
    return _write_raw_config(raw)


def zernio_config_status() -> dict:
    """Mask the API key for safe display in UI / logs."""
    cfg = load_zernio_config()
    api_key = cfg.get("api_key", "")
    masked = f"{api_key[:6]}...{api_key[-4:]}" if api_key and len(api_key) > 10 else ""
    return {
        "configured": bool(api_key),
        "api_key_masked": masked,
        "accounts": cfg.get("accounts", {}),
        "timezone": cfg.get("timezone", "Europe/Rome"),
    }


def load_persistent_config() -> dict:
    """Load core API keys, falling back to env vars."""
    config = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        "GEMINI_MODEL": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        "YOUTUBE_COOKIES": os.environ.get("YOUTUBE_COOKIES", ""),
        "HF_TOKEN": os.environ.get("HF_TOKEN", ""),
        "DEEPGRAM_API_KEY": os.environ.get("DEEPGRAM_API_KEY", ""),
        "TRANSCRIPTION_PROVIDER": os.environ.get("TRANSCRIPTION_PROVIDER", "deepgram"),
    }
    raw = _read_raw_config()
    filtered = {k: v for k, v in raw.items() if k in VALID_CONFIG_KEYS}
    config.update(filtered)
    return config


def save_persistent_config(new_config: dict) -> bool:
    """Save core API keys to JSON file and mirror into os.environ.

    Preserves any non-core namespaces (like 'zernio') so the Zernio settings
    aren't wiped when the user updates the Gemini key.
    """
    raw = _read_raw_config()
    sanitized = {k: new_config.get(k) for k in VALID_CONFIG_KEYS if k in new_config}
    for key, value in sanitized.items():
        if value in (None, ""):
            raw.pop(key, None)
            os.environ.pop(key, None)
        else:
            raw[key] = value
            os.environ[key] = str(value)
    return _write_raw_config(raw)
