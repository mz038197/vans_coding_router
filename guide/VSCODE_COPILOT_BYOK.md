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
| `ollama_cloud@minimax-m3:cloud` | Ollama Cloud | `minimax-m3:cloud` |

Copy IDs from `GET /v1/models`. Bare names (without `@`) return **400**.

For **`ollama_cloud` only**, the router adds Ollama cloud inference suffixes (`:cloud` or `-cloud` on tagged models) to listed IDs and when forwarding requests. Use the ID exactly as returned by `/v1/models`.

Do not invent model suffixes for other providers unless they appear in `/v1/models`.

## VS Code `chatLanguageModels.json` examples

### Ollama Cloud (Copilot Agent — Responses API)

Recommended for VS Code Copilot Agent / Edit workflows:

```json
[
  {
    "name": "VSRouter",
    "vendor": "customendpoint",
    "apiKey": "",
    "apiType": "responses",
    "models": [
      {
        "id": "ollama_cloud@minimax-m3:cloud",
        "name": "minimax-m3",
        "url": "https://ai.vanscoding.com/v1",
        "toolCalling": true,
        "vision": true,
        "supportsReasoningEffort": ["none", "low", "medium", "high"],
        "zeroDataRetentionEnabled": true,
        "maxInputTokens": 128000,
        "maxOutputTokens": 16000
      }
    ]
  }
]
```

| Field | Required | Notes |
|-------|----------|-------|
| `apiType` | Yes | `"responses"` for Copilot Agent |
| `url` | Yes | Full path `/v1/responses`, not just `/v1` |
| `thinking` | Yes | Enables reasoning UI |
| `reasoningEffortFormat` | Yes | Set `"responses"` |
| `zeroDataRetentionEnabled` | Strongly recommended | Omits `previous_response_id` (router rejects it) |
| `requestHeaders` | **Required for stable BYOK auth** | Set `Authorization: Bearer ${apiKey}` so VS Code does not fall back to the Copilot token (which triggers `token expired or invalid: 403`) |

Each bundled model includes:

```json
"requestHeaders": {
  "Authorization": "Bearer ${apiKey}"
}
```

Re-run `install-vscode-models.cmd` (or the Portal download) to patch this onto existing `chatLanguageModels.json` entries without overwriting your API key.

Copilot may still send some sub-requests to `/v1/chat/completions` (Edit / Inline Fix). The router normalizes those streams so Copilot does not fail with `Response contained no choices`.

### OpenRouter (Chat Completions)

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

## Portal one-click install (Windows)

Logged-in students should download **`install-vscode-models.cmd`** from the Portal **課堂邀請碼** section and double-click it.

The `.cmd` file is self-contained (no separate `.ps1` required). It runs PowerShell with `-ExecutionPolicy Bypass` and merges the bundled **VSRouter** models.

Advanced/manual option: download `install-vscode-models.ps1` and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-vscode-models.ps1
```

The script merges the bundled **VSRouter** provider from [`config/chatLanguageModels.vans.json`](../config/chatLanguageModels.vans.json) into:

| VS Code | Path |
|---------|------|
| Stable | `%APPDATA%\Code\User\chatLanguageModels.json` |
| Insiders | `%APPDATA%\Code - Insiders\User\chatLanguageModels.json` |

Merge rules:

- Existing providers and models are **not overwritten**
- Missing VSRouter models are appended
- Existing `apiKey` values are preserved
- A timestamped `.bak` backup is created before writing

After running the script:

1. **Developer: Reload Window**
2. **Chat: Manage Language Models** → set API Key to your `vcr_sk_...`
3. Pick a **VSRouter** model in Copilot (avoid **Auto**)

## Troubleshooting: `token expired or invalid: 403`

VS Code maps **any HTTP 403** to this message, even when the router never saw the request.

**Check the Copilot log first** (`Help` → `Toggle Developer Tools` → `Output` → **GitHub Copilot Chat**, or `%APPDATA%\Code\logs\...\GitHub Copilot Chat.log`):

| Log body | Real cause |
|----------|------------|
| JSON like `invalid_api_key` / `wrong_credential_type` | Router auth — fix API key or `requestHeaders` below |
| HTML with `403 - Forbidden` and **web application firewall (WAF)** | **Render/Cloudflare edge** blocked VS Code’s Electron request before it reached the router |

When the log shows the WAF HTML page, curl/Python tests against the same URL can still return **200** — that is expected. The router and API key are fine; VS Code’s fetch fingerprint or Agent payload triggers the edge firewall.

**WAF workaround (production on Render):**

1. Open [Render Dashboard](https://dashboard.render.com) → **vans-coding-router** → **Networking** → confirm **Inbound IP Restrictions** includes `0.0.0.0/0` (allow all).
2. Reproduce once in VS Code, then copy the **Request ID** from the WAF HTML in the Copilot log (e.g. `a10ca6f9cadda9af`) and open a Render support ticket: ask to allow BYOK API traffic to `/v1/*` from VS Code/Electron clients.
3. Until Render adjusts the edge rules: run the router locally (`uv run uvicorn app:app`) and point `chatLanguageModels.json` model URLs to `http://127.0.0.1:8000/v1`, or use Cursor/other clients that are not blocked.

Common router-side causes (JSON 401/502, not WAF HTML):

| Cause | Fix |
|-------|-----|
| API key not set in VS Code | **Chat: Manage Language Models** → **VSRouter** → **Update API Key** → paste `vcr_sk_...` from Portal |
| VS Code sent Copilot token instead of `vcr_sk_` | Ensure each model has `requestHeaders.Authorization: Bearer ${apiKey}` (re-run install script) |
| Session invite key expired | Portal → rejoin class with invite code → update API key in VS Code |
| Upstream provider auth failed | Contact teacher; router returns **502** (not 403) after this fix |

After updating config or API key: **Developer: Reload Window**.

Optional parameter: `-Edition Stable|Insiders|Both` (default `Both`).

## Endpoints

- Chat: `POST /v1/chat/completions`
- Copilot Agent (Responses API): `POST /v1/responses`

The router rejects `previous_response_id`; send the full conversation context each request. Set `zeroDataRetentionEnabled: true` for Agent mode.
