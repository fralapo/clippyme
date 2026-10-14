# LLM provider integration

ClippyMe supports Gemini, OpenAI, OpenRouter, Anthropic (Claude) and DeepSeek
for viral-moment analysis. This page records the provider API contracts and
the local integration choices. Provider catalogs are fetched when Settings
opens, when the provider or its key changes, and when the user presses
**Refresh**. The backend keeps a 60-second in-memory cache per provider and
credential fingerprint; refresh bypasses it. API keys remain in the local
backend configuration and are never included in catalog responses.

## Catalogs and requests

| Provider | Live catalog | Generation | Authentication / output |
| --- | --- | --- | --- |
| Gemini | Google `models.list` | Existing Gemini `generateContent` service | Google GenAI SDK; existing Gemini JSON prompt and fallback chain |
| OpenAI | `GET https://api.openai.com/v1/models` | `POST /v1/chat/completions` | Bearer key; JSON response mode |
| OpenRouter | `GET https://openrouter.ai/api/v1/models` | `POST /api/v1/chat/completions` | Bearer key; JSON response mode |
| Anthropic | `GET https://api.anthropic.com/v1/models` | `POST https://api.anthropic.com/v1/messages` | `x-api-key` and `anthropic-version`; native JSON Schema output using ClippyMe's clip schema |
| DeepSeek | `GET https://api.deepseek.com/models` | `POST https://api.deepseek.com/chat/completions` | Bearer key; JSON response mode |

The OpenAI-compatible request shape is shared only where provider docs support
it. Anthropic uses its native Messages API. The downstream parser continues to
validate the same `{"shorts": [...]}` payload for every provider.

## Selection policy

Catalogs are account-specific: the list is fetched using the saved key and
contains models visible to that account. OpenAI publishes model IDs and basic
metadata rather than a complete capability matrix, so ClippyMe narrows the
list to known chat/reasoning ID families and excludes image, audio,
transcription, embedding, moderation, search and coding-only IDs. OpenRouter
has richer metadata, so ClippyMe includes text-input/text-output models that
advertise `response_format` or `structured_outputs`. DeepSeek's text catalog is
used directly. Anthropic's paginated catalog is requested with active lifecycle
models. Gemini keeps its existing generation-capability discovery.

The Settings control is a select list, never a free-text model field. New jobs
use the selected provider and model. When there is no provider selection yet,
existing Gemini installations keep their previous model. A non-Gemini provider
does not inherit a Gemini model ID. Catalog failures leave the saved selection
visible and report the provider error; the user can retry or correct the key.

## Pricing and failure behavior

Only Gemini has ClippyMe's local price table and preflight estimator. Other
providers may bill differently by model, region, cached input, reasoning
tokens, or routing. ClippyMe therefore reports unknown cost unless the
provider response supplies a cost, and the configured maximum-cost gate rejects
an analysis when price cannot be established. The UI must not present unknown
cost as zero. Requests have bounded timeouts; provider errors are sanitized
before returning to the UI or job log, so response bodies and credentials are
not leaked.

## Official references

- [Gemini Models API](https://ai.google.dev/api/models) and
  [GenerateContent API](https://ai.google.dev/api/generate-content)
- [OpenAI list models](https://platform.openai.com/docs/api-reference/models/list)
  and [Chat Completions](https://platform.openai.com/docs/api-reference/chat/create)
- [OpenRouter models API](https://openrouter.ai/docs/api/api-reference/models/get-models)
  and [Chat Completions](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request)
- [Anthropic list models](https://platform.claude.com/docs/en/api/models/list)
  and [Messages API](https://platform.claude.com/docs/en/api/messages/create)
- [DeepSeek list models](https://api-docs.deepseek.com/api/list-models/)
  and [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)

Model catalogs and API capabilities can change. The provider's current catalog
and API response remain authoritative; this document is an implementation
record, not a promise that every account can use every listed model.
