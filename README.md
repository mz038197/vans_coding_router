# Vans Coding Router

FastAPI router for Vans Coding classes. Students sign in with Google, redeem a class-session invite code, receive a short-lived `vcr_sk_...` API key, and call OpenAI-compatible cloud providers through `/v1/*`.

The router does not run or manage local Ollama. It forwards OpenAI-compatible requests to configured providers such as Ollama Cloud and OpenRouter.

## Quick Start

```powershell
cd D:\Work\Python\vans_coding_router
Copy-Item config\router.example.yaml $HOME\.vans_coding_router\router.yaml
$env:VCR_CONFIG="$HOME\.vans_coding_router\router.yaml"
uv run uvicorn app:app --reload
```

Open `http://127.0.0.1:8000/portal`.

If Google OAuth is not configured, the portal allows dev login through `POST /auth/google`. Once `google_client_id` and `google_client_secret` are configured, dev login is disabled.

## Configuration

Default config path: `~/.vans_coding_router/router.yaml`

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
```

Provider routing is configured in `providers` and `routing`:

```yaml
providers:
  ollama_cloud:
    type: openai_compatible
    base_url: "https://ollama.com/v1"
    api_key_env: "OLLAMA_CLOUD_API_KEY"

routing:
  default_provider: ollama_cloud
  rules:
    - match: "anthropic/*"
      provider: openrouter
```

## Student BYOK

After redeeming an invite code, students configure their client with:

```bash
OPENAI_BASE_URL=https://ai.vanscoding.com/v1
OPENAI_API_KEY=vcr_sk_xxxxxxxx
```

Supported endpoints:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`

`/v1/responses` is stateless in this router. Requests with `previous_response_id` are rejected.

## Portal Flow

- Admin emails receive `admin`, `teacher`, and `student` roles.
- Other new users receive `student`.
- Teachers create classes and class sessions.
- Class sessions can specify TTL at creation time.
- Teachers can patch a session expiry; issued session API keys are updated to the same expiry.
- Usage is recorded after upstream responses and surfaced per class/student/session.

## Render Deployment

Use Render Web Service + Render PostgreSQL.

1. Create a Web Service from this repo.
2. Create a PostgreSQL instance.
3. Set env vars listed above.
4. Add custom domain `ai.vanscoding.com`.
5. In Squarespace DNS, add CNAME host `ai` to the Render-provided hostname.
6. In Google Cloud Console, add authorized redirect URI:

```text
https://ai.vanscoding.com/auth/google/callback
```

Render commands:

```bash
uv sync --frozen
uv run uvicorn app:app --host 0.0.0.0 --port $PORT
```

Note: the current local repository implementation is SQLite-first. `DATABASE_URL` is parsed for deployment configuration and documented for the Render target; a production PostgreSQL repository should be enabled before using Render PostgreSQL as the source of truth.
