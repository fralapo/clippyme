"""First tests for gemini_service.list_available_models (host tier).

The module is pure control flow around the genai SDK, so the client is
monkeypatched — no network. Pins: the missing-key short-circuit, the
generateContent/prefix filtering, the API-key redaction on errors, and the
request timeout (the one call that used to be unbounded and could pin the
Settings UI request thread forever).
"""
from types import SimpleNamespace

import clippyme.pipeline.gemini_service as gs


class _FakeClient:
    """Captures constructor kwargs; returns a canned model list."""

    last_kwargs = None
    models_to_return = []

    def __init__(self, **kwargs):
        _FakeClient.last_kwargs = kwargs
        self.models = SimpleNamespace(list=lambda: list(_FakeClient.models_to_return))


def _model(name, actions=("generateContent",), display=None):
    return SimpleNamespace(
        name=name,
        supported_actions=list(actions),
        display_name=display or name,
        description="",
    )


def test_missing_key_short_circuits_without_client(monkeypatch):
    def boom(**kwargs):
        raise AssertionError("client must not be constructed without a key")

    monkeypatch.setattr(gs.genai, "Client", boom)
    out = gs.list_available_models(None)
    assert out == {"models": [], "error": "API Key missing"}
    assert gs.list_available_models("") == {"models": [], "error": "API Key missing"}


def test_filters_by_action_and_prefix(monkeypatch):
    _FakeClient.models_to_return = [
        _model("models/gemini-3.5-flash"),
        _model("models/gemini-2.5-pro"),
        _model("models/gemini-1.5-pro"),                       # old generation
        _model("models/gemini-3.5-embed", actions=("embedContent",)),  # wrong action
        _model("models/imagen-4"),                             # wrong family
    ]
    monkeypatch.setattr(gs.genai, "Client", _FakeClient)
    out = gs.list_available_models("AIza" + "x" * 35)
    assert [m["name"] for m in out["models"]] == ["gemini-3.5-flash", "gemini-2.5-pro"]
    assert "error" not in out


def test_client_is_constructed_with_a_timeout(monkeypatch):
    # Regression: this was the only network call in the pipeline modules with
    # no bound — a hung endpoint blocked the Settings request thread forever.
    _FakeClient.models_to_return = []
    monkeypatch.setattr(gs.genai, "Client", _FakeClient)
    gs.list_available_models("AIza" + "x" * 35)
    http_options = _FakeClient.last_kwargs.get("http_options")
    assert http_options is not None
    assert http_options.timeout == gs.LIST_MODELS_TIMEOUT_MS > 0


def test_error_message_redacts_api_key(monkeypatch):
    key = "AIza" + "S" * 35

    def boom(**kwargs):
        raise RuntimeError(f"invalid api key: {key}")

    monkeypatch.setattr(gs.genai, "Client", boom)
    out = gs.list_available_models(key)
    assert out["models"] == []
    assert key not in out["error"]
    assert "***REDACTED***" in out["error"]


def test_legacy_supported_generation_methods_field(monkeypatch):
    # Older SDKs expose supported_generation_methods instead of
    # supported_actions — the module accepts either.
    legacy = SimpleNamespace(
        name="models/gemini-3.5-flash",
        supported_generation_methods=["generateContent"],
        display_name="Flash",
        description="",
    )
    _FakeClient.models_to_return = [legacy]
    monkeypatch.setattr(gs.genai, "Client", _FakeClient)
    out = gs.list_available_models("AIza" + "x" * 35)
    assert out["models"][0]["name"] == "gemini-3.5-flash"
