# Vans Coding Router

FastAPI router for Vans Coding classes. Students sign in with Google, redeem a class-session invite code, receive a short-lived `vcr_sk_...` API key, and call OpenAI-compatible cloud providers through `/v1/*`.

The router does not run or manage local Ollama. It forwards OpenAI-compatible requests to configured providers such as Ollama Cloud and OpenRouter.

**Full deployment runbook (Render, OAuth, DNS, troubleshooting):** [`guide/DEPLOYMENT.md`](guide/DEPLOYMENT.md)

**Fly.io + Neon (recommended for VS Code / no WAF):** [`guide/FLY_DEPLOYMENT.md`](guide/FLY_DEPLOYMENT.md)

**Local dev + Portal UI + Google OAuth (agent runbook):** [`guide/LOCAL_DEV.md`](guide/LOCAL_DEV.md)

## Quick Start

```powershell
cd D:\Work\Python\vans_coding_router
powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1
```

Open `http://127.0.0.1:8000/portal` (or `http://127.0.0.1:8000/` — root redirects to `/portal`).

If Google OAuth is not configured, the portal allows dev login through `POST /auth/google`. Once `google_client_id` and `google_client_secret` are configured, dev login is disabled.

## Configuration

Default config path: `~/.vans_coding_router/router.yaml`

Settings load from YAML first, then environment variables override matching fields. On Render, use the Secret File for structured config and Environment for secrets — do not duplicate the same value in both places with different values.

| Setting | Secret File (`router.yaml`) | Environment | Effective source |
|---------|----------------------------|-------------|------------------|
| Public URL | `public_url` | `PUBLIC_URL` | Environment |
| Google OAuth | leave empty | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Environment |
| Session secret | optional | `SESSION_SECRET` | Environment |
| API keys | use `api_key_env` | `OLLAMA_CLOUD_API_KEY`, `OPENROUTER_API_KEY` | Environment |
| Routing, admin emails, providers | primary source | — | YAML |

After Google login, users land on `{PUBLIC_URL}/portal`. Session cookies are not shared across different hostnames.

Environment overrides:

```bash
VCR_CONFIG=/path/to/router.yaml
PUBLIC_URL=https://ai.vanscoding.com
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxx
SESSION_SECRET=<strong-random-secret>
DATABASE_URL=<render-postgres-url>
OLLAMA_CLOUD_API_KEY=xxx
OPENROUTER_API_KEY=xxx
OPENAI_API_KEY=xxx
```

Provider routing uses **`provider@upstream_model`** model IDs. The part before `@` is the router provider name (`openrouter`, `ollama_cloud`, …); the part after `@` is forwarded unchanged to that provider.

```yaml
providers:
  ollama_cloud:
    type: openai_compatible
    base_url: "https://ollama.com/v1"
    api_key_env: "OLLAMA_CLOUD_API_KEY"

  openrouter:
    type: openai_compatible
    base_url: "https://openrouter.ai/api/v1"
    api_key_env: "OPENROUTER_API_KEY"

  openai:
    type: openai_compatible
    base_url: "https://api.openai.com/v1"
    api_key_env: "OPENAI_API_KEY"
    capabilities:
      - audio_speech
```

Examples:

| Model ID | Routes to | Upstream model |
|----------|-----------|----------------|
| `openrouter@anthropic/claude-sonnet-4` | openrouter | `anthropic/claude-sonnet-4` |
| `openrouter@openai/gpt-oss-120b:free` | openrouter | `openai/gpt-oss-120b:free` |
| `ollama_cloud@qwen3-coder-next` | ollama_cloud | `qwen3-coder-next` |

Bare names such as `qwen3-coder-next` are rejected with **400**. Use `GET /v1/models` to copy prefixed IDs.

## Student BYOK

After redeeming an invite code, students configure their client with:

```bash
OPENAI_BASE_URL=https://ai.vanscoding.com/v1
OPENAI_API_KEY=vcr_sk_xxxxxxxx
```

Use model IDs from `/v1/models` (for example `openrouter@anthropic/claude-sonnet-4`). See [guide/VSCODE_COPILOT_BYOK.md](guide/VSCODE_COPILOT_BYOK.md).

Supported endpoints:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/images` (OpenRouter image generation; model ID e.g. `openrouter@black-forest-labs/flux.2-pro`)
- `GET /v1/images/models`
- `POST /v1/audio/speech` (TTS via providers with `audio_speech` capability; model ID e.g. `openai@gpt-4o-mini-tts`)

`/v1/responses` is stateless in this router. Requests with `previous_response_id` are rejected.

Image generation for student session keys follows each class session's **生圖** toggle in Portal (default on). TTS follows each session's **語音** toggle (default on). Teacher long-lived keys are not restricted by session toggles.

## Portal Flow

- Admin emails receive `admin`, `teacher`, and `student` roles.
- Other new users receive `student`.
- Teachers create classes and class sessions.
- Class sessions can specify TTL at creation time.
- Teachers can patch a session expiry; issued session API keys are updated to the same expiry.
- Usage is recorded after upstream responses and surfaced per class/student/session.

## Render Deployment

Use Render Web Service + Render PostgreSQL.

**Step-by-step checklist:** [`guide/DEPLOYMENT.md`](guide/DEPLOYMENT.md) (Blueprint, Secret File, Environment, Google OAuth, DNS, verification, troubleshooting).

Render commands:

```bash
uv sync --frozen
uv run uvicorn app:app --host 0.0.0.0 --port $PORT
```

Note: **local dev defaults to SQLite** (`~/.vans_coding_router/router.db`). When `DATABASE_URL` is set (automatically on Render), the app uses **PostgreSQL** as the source of truth. Optional local Postgres verification:

```powershell
docker compose up -d
$env:DATABASE_URL = "postgresql://vcr:vcr@localhost:5432/vans_coding_router"
uv run uvicorn app:app --reload
```
