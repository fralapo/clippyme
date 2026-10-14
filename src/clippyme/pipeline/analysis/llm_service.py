"""Provider discovery and text generation for viral-moment analysis.

Provider catalogs are fetched from their first-party APIs when requested. This
module deliberately keeps credentials server-side and returns only catalog
metadata to the Settings UI.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests

PROVIDERS = ("gemini", "openai", "openrouter", "anthropic", "deepseek")
PROVIDER_KEYS = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}
CATALOG_TIMEOUT = 15
GENERATION_TIMEOUT = (10, 180)
_CACHE_SECONDS = 60
_catalog_cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class LLMResponse:
    text: str
    usage: dict[str, Any]


def _display_model(name: str, model_id: str) -> dict[str, str]:
    return {"name": model_id, "display_name": name or model_id}


def _openai_chat_model(model_id: str) -> bool:
    """Keep the live account catalog to text-generation model families."""
    value = model_id.lower()
    if not value.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-")):
        return False
    excluded = (
        "gpt-image", "gpt-audio", "gpt-realtime", "-transcribe", "-tts",
        "-search-preview", "codex", "moderation", "embedding",
    )
    return not any(part in value for part in excluded)


def _fetch_catalog(provider: str, api_key: str) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {api_key}"}
    if provider == "openai":
        response = requests.get(
            "https://api.openai.com/v1/models", headers=headers, timeout=CATALOG_TIMEOUT
        )
        response.raise_for_status()
        rows = response.json().get("data", [])
        rows = [row for row in rows if _openai_chat_model(str(row.get("id", "")))]
        rows.sort(key=lambda row: (row.get("created", 0), row.get("id", "")), reverse=True)
        return [_display_model(row.get("id", ""), row.get("id", "")) for row in rows]

    if provider == "openrouter":
        response = requests.get(
            "https://openrouter.ai/api/v1/models", headers=headers, timeout=CATALOG_TIMEOUT
        )
        response.raise_for_status()
        rows = response.json().get("data", [])
        models = []
        for row in rows:
            architecture = row.get("architecture") or {}
            modalities = architecture.get("input_modalities") or []
            outputs = architecture.get("output_modalities") or []
            parameters = row.get("supported_parameters") or []
            if "text" not in modalities or "text" not in outputs:
                continue
            if not ({"response_format", "structured_outputs"} & set(parameters)):
                continue
            model_id = str(row.get("id") or "")
            if model_id:
                models.append((row.get("created", 0), _display_model(row.get("name", ""), model_id)))
        models.sort(key=lambda item: (item[0], item[1]["display_name"]), reverse=True)
        return [model for _, model in models]

    if provider == "deepseek":
        response = requests.get(
            "https://api.deepseek.com/models", headers=headers, timeout=CATALOG_TIMEOUT
        )
        response.raise_for_status()
        rows = response.json().get("data", [])
        models = []
        for row in rows:
            inputs = row.get("input_modalities") or ["text"]
            outputs = row.get("output_modalities") or ["text"]
            model_id = str(row.get("id") or "")
            if model_id and "text" in inputs and "text" in outputs:
                models.append(_display_model(row.get("name", model_id), model_id))
        return models

    if provider == "anthropic":
        models: list[dict[str, str]] = []
        after_id = None
        # The provider currently exposes only a small catalog; still follow its
        # cursor contract so pagination remains correct as that catalog grows.
        for _ in range(20):
            params = {"limit": 1000, "lifecycle": "active"}
            if after_id:
                params["after_id"] = after_id
            response = requests.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                params=params,
                timeout=CATALOG_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            for row in payload.get("data", []):
                model_id = str(row.get("id") or "")
                if model_id:
                    models.append(_display_model(row.get("display_name", model_id), model_id))
            if not payload.get("has_more"):
                break
            after_id = payload.get("last_id")
            if not after_id:
                break
        return models

    raise ValueError(f"Unsupported LLM provider: {provider}")


def list_provider_models(provider: str, api_key: str, *, force_refresh: bool = False) -> dict:
    """List models currently visible to an API key, with a short local cache."""
    provider = (provider or "").strip().lower()
    if provider not in PROVIDERS:
        return {"models": [], "error": "Unsupported provider"}
    if not api_key:
        return {"models": [], "error": "API key not configured"}
    if provider == "gemini":
        from clippyme.pipeline.analysis.gemini_service import list_available_models

        return list_available_models(api_key)

    # Hashing keeps raw credentials out of cache keys and diagnostic output.
    import hashlib

    cache_key = (provider, hashlib.sha256(api_key.encode()).hexdigest())
    now = time.monotonic()
    with _cache_lock:
        cached = _catalog_cache.get(cache_key)
        if not force_refresh and cached and now - cached[0] < _CACHE_SECONDS:
            return {"models": list(cached[1]), "cached": True}
    try:
        models = _fetch_catalog(provider, api_key)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        return {"models": [], "error": f"{provider} model catalog returned HTTP {status}"}
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        # Never pass raw provider responses or request headers to the browser.
        return {"models": [], "error": f"{provider} model catalog unavailable ({type(exc).__name__})"}
    with _cache_lock:
        _catalog_cache[cache_key] = (now, list(models))
    return {"models": models, "cached": False}


def _provider_url(provider: str) -> str:
    return {
        "openai": "https://api.openai.com/v1/chat/completions",
        "openrouter": "https://openrouter.ai/api/v1/chat/completions",
        "deepseek": "https://api.deepseek.com/chat/completions",
    }[provider]


def generate_text(provider: str, model: str, prompt: str, api_key: str) -> LLMResponse:
    """Generate JSON-oriented text through the selected provider's official API."""
    provider = (provider or "").strip().lower()
    if provider not in PROVIDERS or provider == "gemini":
        raise ValueError("generate_text accepts OpenAI, OpenRouter, Anthropic or DeepSeek")
    if not api_key:
        raise RuntimeError(f"{provider} API key is not configured")

    if provider == "anthropic":
        # Use the same validation contract as the downstream parser, so JSON
        # validity is enforced by Claude's API rather than prompt wording only.
        from clippyme.core.clip_schema import ViralClipsResponse

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": model,
            "max_tokens": 8192,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": ViralClipsResponse.model_json_schema(),
                }
            },
        }
    else:
        url = _provider_url(provider)
        headers = {"Authorization": f"Bearer {api_key}", "content-type": "application/json"}
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        if provider == "openai":
            body["max_completion_tokens"] = 8192
        else:
            body["max_tokens"] = 8192

    try:
        response = requests.post(url, headers=headers, json=body, timeout=GENERATION_TIMEOUT)
    except requests.RequestException as exc:
        raise RuntimeError(f"{provider} request failed ({type(exc).__name__})") from None
    if not response.ok:
        raise RuntimeError(f"{provider} request failed (HTTP {response.status_code})")
    try:
        payload = response.json()
        if provider == "anthropic":
            text = "".join(
                block.get("text", "") for block in payload.get("content", [])
                if block.get("type") == "text"
            )
            raw_usage = payload.get("usage") or {}
            usage = {
                "prompt_tokens": raw_usage.get("input_tokens"),
                "completion_tokens": raw_usage.get("output_tokens"),
            }
        else:
            choice = (payload.get("choices") or [])[0]
            text = choice.get("message", {}).get("content") or ""
            raw_usage = payload.get("usage") or {}
            usage = {
                "prompt_tokens": raw_usage.get("prompt_tokens"),
                "completion_tokens": raw_usage.get("completion_tokens"),
            }
            if isinstance(raw_usage.get("cost"), (int, float)):
                usage["cost"] = float(raw_usage["cost"])
    except (ValueError, TypeError, IndexError, KeyError):
        raise RuntimeError(f"{provider} returned an invalid response") from None
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError(f"{provider} returned no text")
    return LLMResponse(text=text, usage=usage)


def model_id_is_safe(value: str) -> bool:
    """Provider model IDs are argv-safe and limited to the catalog ID alphabet."""
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}", value or ""))
