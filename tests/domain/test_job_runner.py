"""merge_persistent_config precedence: Settings vs inherited process env."""
from clippyme.domain.job_runner import merge_persistent_config


def test_settings_override_empty_env_values():
    # docker compose exports DEEPGRAM_API_KEY= (empty) — Settings must win.
    env = {"DEEPGRAM_API_KEY": "", "TRANSCRIPTION_PROVIDER": "deepgram"}
    merge_persistent_config(env, {
        "DEEPGRAM_API_KEY": "dg-key",
        "TRANSCRIPTION_PROVIDER": "elevenlabs",
    })
    assert env["DEEPGRAM_API_KEY"] == "dg-key"
    assert env["TRANSCRIPTION_PROVIDER"] == "elevenlabs"


def test_settings_override_nonempty_env_values():
    # A compose-pinned provider must not shadow the user's Settings choice.
    env = {"TRANSCRIPTION_PROVIDER": "deepgram"}
    merge_persistent_config(env, {"TRANSCRIPTION_PROVIDER": "whisper"})
    assert env["TRANSCRIPTION_PROVIDER"] == "whisper"


def test_empty_persisted_values_never_clobber_env():
    # Env-only deploy: nothing saved in Settings → env values survive.
    env = {"DEEPGRAM_API_KEY": "env-key", "HF_TOKEN": "hf-env"}
    merge_persistent_config(env, {"DEEPGRAM_API_KEY": "", "HF_TOKEN": None})
    assert env["DEEPGRAM_API_KEY"] == "env-key"
    assert env["HF_TOKEN"] == "hf-env"


def test_gemini_header_key_wins_over_settings():
    env = {"GEMINI_API_KEY": "header-key"}
    merge_persistent_config(env, {"GEMINI_API_KEY": "settings-key"})
    assert env["GEMINI_API_KEY"] == "header-key"


def test_gemini_settings_key_fills_missing_env():
    env = {}
    merge_persistent_config(env, {"GEMINI_API_KEY": "settings-key"})
    assert env["GEMINI_API_KEY"] == "settings-key"
