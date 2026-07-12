"""Gemini API service helpers."""
import re
from typing import List, Optional

from google import genai
from google.genai import types as genai_types

ALLOWED_MODEL_PREFIXES = ("gemini-2.5-", "gemini-3")

# models.list() serves the Settings UI synchronously — an unbounded call
# against a hung endpoint would pin the request thread forever. Milliseconds.
LIST_MODELS_TIMEOUT_MS = 15_000

# Google API keys look like ``AIza`` + 35 url-safe chars. Redact any such token
# from an error string before it is returned to the client / written to logs,
# so a malformed-key SDK error can't echo the key back.
_API_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")


def _redact_key(text: str) -> str:
    return _API_KEY_RE.sub("***REDACTED***", text or "")


def list_available_models(api_key: Optional[str]) -> dict:
    """Return current-generation Gemini models that support content generation.

    Result shape: ``{"models": [...], "error": "..."}``.
    """
    if not api_key:
        return {"models": [], "error": "API Key missing"}

    try:
        client = genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(timeout=LIST_MODELS_TIMEOUT_MS),
        )
        models: List[dict] = []
        for model in client.models.list():
            # The new google-genai SDK (>=1.0) renamed the old
            # `supported_generation_methods` field to `supported_actions`.
            # Accept either so this module keeps working if the SDK is
            # pinned to an older version or drifts again in the future.
            actions = (
                getattr(model, "supported_actions", None)
                or getattr(model, "supported_generation_methods", None)
                or []
            )
            if "generateContent" not in actions:
                continue
            clean_name = (model.name or "").replace("models/", "")
            if not any(clean_name.startswith(p) for p in ALLOWED_MODEL_PREFIXES):
                continue
            models.append(
                {
                    "name": clean_name,
                    "display_name": getattr(model, "display_name", clean_name),
                    "description": getattr(model, "description", ""),
                }
            )
        return {"models": models}
    except Exception as e:
        return {"models": [], "error": _redact_key(str(e))}
