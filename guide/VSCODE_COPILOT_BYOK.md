# VS Code BYOK

Use the API key issued by the Vans Coding Router portal.

```text
Base URL: https://ai.vanscoding.com/v1
API Key:  vcr_sk_xxxxxxxx
```

The router forwards OpenAI-compatible requests to cloud providers configured by the teacher. Students do not receive upstream provider keys.

## Model ID format

All requests must use **`provider@upstream_model`**:

| Example | Provider | Upstream |
|---------|----------|----------|
| `openrouter@anthropic/claude-sonnet-4` | OpenRouter | `anthropic/claude-sonnet-4` |
| `openrouter@openai/gpt-oss-120b:free` | OpenRouter | `openai/gpt-oss-120b:free` |
| `ollama_cloud@qwen3-coder-next` | Ollama Cloud | `qwen3-coder-next` |

Copy IDs from `GET /v1/models`. Bare names (without `@`) return **400**.

## VS Code `chatLanguageModels.json` example

OpenRouter (Chat Completions):

```json
[
  {
    "name": "Vans Coding Router",
    "vendor": "customendpoint",
    "apiKey": "",
    "apiType": "chat-completions",
    "models": [
      {
        "id": "openrouter@anthropic/claude-sonnet-4",
        "name": "Claude Sonnet 4",
        "url": "https://ai.vanscoding.com/v1/chat/completions",
        "apiType": "chat-completions",
        "toolCalling": true,
        "zeroDataRetentionEnabled": true,
        "maxInputTokens": 128000,
        "maxOutputTokens": 16384
      }
    ]
  }
]
```

Set the API key via **Chat: Manage Language Models** → **Update API Key** (`vcr_sk_...`).

## Endpoints

- Chat: `POST /v1/chat/completions`
- Copilot Agent (Responses API): `POST /v1/responses`

The router rejects `previous_response_id`; send the full conversation context each request. Set `zeroDataRetentionEnabled: true` for Agent mode.
