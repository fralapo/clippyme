"""Gemini API service helpers."""
from typing import List, Optional

from google import genai

ALLOWED_MODEL_PREFIXES = ("gemini-2.5-", "gemini-3")


def list_available_models(api_key: Optional[str]) -> dict:
    """Return current-generation Gemini models that support content generation.

    Result shape: ``{"models": [...], "error": "..."}``.
    """
    if not api_key:
        return {"models": [], "error": "API Key missing"}

    try:
        client = genai.Client(api_key=api_key)
        models: List[dict] = []
        for model in client.models.list():
            if "generateContent" not in model.supported_generation_methods:
                continue
            clean_name = model.name.replace("models/", "")
            if not any(clean_name.startswith(p) for p in ALLOWED_MODEL_PREFIXES):
                continue
            models.append(
                {
                    "name": clean_name,
                    "display_name": model.display_name,
                    "description": model.description,
                }
            )
        return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}
