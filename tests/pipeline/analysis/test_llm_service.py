"""Offline contract tests for provider model discovery and generation."""
import requests

from clippyme.pipeline.analysis import llm_service as service


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            error = requests.HTTPError("provider failure")
            error.response = self
            raise error


def test_openai_catalog_filters_to_newest_text_models(monkeypatch):
    captured = {}

    def get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeResponse({"data": [
            {"id": "gpt-4o-mini", "created": 1},
            {"id": "gpt-4.1", "created": 5},
            {"id": "gpt-image-1", "created": 99},
            {"id": "text-embedding-3-large", "created": 100},
            {"id": "whisper-1", "created": 101},
        ]})

    monkeypatch.setattr(service.requests, "get", get)
    result = service.list_provider_models("openai", "secret", force_refresh=True)

    assert [item["name"] for item in result["models"]] == ["gpt-4.1", "gpt-4o-mini"]
    assert captured["url"] == "https://api.openai.com/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert result["cached"] is False


def test_openrouter_catalog_returns_text_capable_json_models(monkeypatch):
    monkeypatch.setattr(service.requests, "get", lambda *a, **k: FakeResponse({"data": [
        {"id": "vendor/vision", "name": "Vision", "architecture": {
            "input_modalities": ["text", "image"], "output_modalities": ["text"]},
         "supported_parameters": ["response_format"]},
        {"id": "vendor/plain", "name": "Plain", "architecture": {
            "input_modalities": ["text"], "output_modalities": ["text"]},
         "supported_parameters": []},
        {"id": "vendor/json", "name": "JSON", "created": 2, "architecture": {
            "input_modalities": ["text"], "output_modalities": ["text"]},
         "supported_parameters": ["structured_outputs"]},
    ]}))

    result = service.list_provider_models("openrouter", "secret", force_refresh=True)

    assert result["models"] == [
        {"name": "vendor/json", "display_name": "JSON"},
        {"name": "vendor/vision", "display_name": "Vision"},
    ]


def test_anthropic_catalog_uses_required_headers_and_follows_cursor(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            return FakeResponse({"data": [{"id": "claude-new", "display_name": "Claude New"}],
                                 "has_more": True, "last_id": "claude-new"})
        return FakeResponse({"data": [{"id": "claude-next", "display_name": "Claude Next"}],
                             "has_more": False})

    monkeypatch.setattr(service.requests, "get", get)
    result = service.list_provider_models("anthropic", "secret", force_refresh=True)

    assert [item["name"] for item in result["models"]] == ["claude-new", "claude-next"]
    assert calls[0][1]["headers"] == {
        "x-api-key": "secret", "anthropic-version": "2023-06-01"
    }
    assert calls[1][1]["params"]["after_id"] == "claude-new"


def test_deepseek_catalog_uses_first_party_models_endpoint(monkeypatch):
    captured = {}

    def get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeResponse({"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]})

    monkeypatch.setattr(service.requests, "get", get)
    result = service.list_provider_models("deepseek", "secret", force_refresh=True)

    assert [item["name"] for item in result["models"]] == ["deepseek-chat", "deepseek-reasoner"]
    assert captured["url"] == "https://api.deepseek.com/models"


def test_catalog_errors_do_not_expose_credentials_or_provider_body(monkeypatch):
    def get(*args, **kwargs):
        response = FakeResponse({"error": "secret leaked"}, status_code=401)
        raise requests.HTTPError("secret token leaked", response=response)

    monkeypatch.setattr(service.requests, "get", get)
    result = service.list_provider_models("openai", "top-secret", force_refresh=True)
    assert result == {"models": [], "error": "openai model catalog returned HTTP 401"}


def test_chat_completion_uses_json_mode_and_normalizes_usage(monkeypatch):
    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeResponse({"choices": [{"message": {"content": '{"shorts": []}'}}],
                             "usage": {"prompt_tokens": 123, "completion_tokens": 45, "cost": 0.01}})

    monkeypatch.setattr(service.requests, "post", post)
    response = service.generate_text("deepseek", "deepseek-chat", "return JSON", "secret")

    assert response.text == '{"shorts": []}'
    assert response.usage == {"prompt_tokens": 123, "completion_tokens": 45, "cost": 0.01}
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["json"]["response_format"] == {"type": "json_object"}


def test_openai_and_openrouter_use_their_chat_completion_apis(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse({"choices": [{"message": {"content": '{"shorts": []}'}}], "usage": {}})

    monkeypatch.setattr(service.requests, "post", post)
    for provider, model in (("openai", "gpt-5.1"), ("openrouter", "openai/gpt-5.1")):
        response = service.generate_text(provider, model, "return JSON", "secret")
        assert response.text == '{"shorts": []}'
    assert [call[0] for call in calls] == [
        "https://api.openai.com/v1/chat/completions",
        "https://openrouter.ai/api/v1/chat/completions",
    ]
    assert calls[0][1]["json"]["max_completion_tokens"] == 8192
    assert calls[1][1]["json"]["max_tokens"] == 8192


def test_anthropic_messages_uses_native_request_and_usage_shape(monkeypatch):
    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeResponse({"content": [{"type": "text", "text": '{"shorts": []}'}],
                             "usage": {"input_tokens": 12, "output_tokens": 8}})

    monkeypatch.setattr(service.requests, "post", post)
    response = service.generate_text("anthropic", "claude-latest", "return JSON", "secret")

    assert response.text == '{"shorts": []}'
    assert response.usage == {"prompt_tokens": 12, "completion_tokens": 8}
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "secret"
    assert captured["json"]["output_config"]["format"]["type"] == "json_schema"
    assert captured["json"]["output_config"]["format"]["schema"]["properties"]["shorts"]


def test_generation_failure_is_sanitized(monkeypatch):
    def post(*args, **kwargs):
        response = FakeResponse({}, status_code=403)
        return response

    monkeypatch.setattr(service.requests, "post", post)
    try:
        service.generate_text("openai", "gpt-4.1", "prompt", "secret")
    except RuntimeError as exc:
        assert str(exc) == "openai request failed (HTTP 403)"
        assert "secret" not in str(exc)
    else:
        raise AssertionError("expected provider failure")
