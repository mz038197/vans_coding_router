# OAuth and Render

Production URL:

```text
https://ai.vanscoding.com
```

Root path `/` redirects to `/portal` on whichever hostname the user visits. Google OAuth still uses a single canonical `PUBLIC_URL` for the callback.

Google OAuth redirect URI:

```text
https://ai.vanscoding.com/auth/google/callback
```

You may register additional redirect URIs in Google Cloud Console (for example the Render default hostname), but the app sends only one callback URL per login: `{PUBLIC_URL}/auth/google/callback`.

After a successful Google login, users return to:

```text
{PUBLIC_URL}/portal
```

If a user opens Portal on `vans-coding-router.onrender.com` but `PUBLIC_URL` is `https://ai.vanscoding.com`, Google login completes on the custom domain.

## Secret File vs Environment

Render uses both a Secret File (`router.yaml` via `VCR_CONFIG`) and Environment variables. Environment wins when both are set.

| Setting | Secret File | Environment | Use on Render |
|---------|-------------|-------------|---------------|
| Public URL | `public_url` | `PUBLIC_URL` | Environment |
| Google OAuth | leave empty | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Environment only |
| Session secret | optional | `SESSION_SECRET` | Environment |
| Routing, admin, providers | primary | — | Secret File |

Do not put Google client secrets in the Secret File. Keep `auth.google_client_id` and `auth.google_client_secret` empty in YAML.

Render environment variables:

```bash
PUBLIC_URL=https://ai.vanscoding.com
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxx
SESSION_SECRET=<strong-random-secret>
OLLAMA_CLOUD_API_KEY=xxx
OPENROUTER_API_KEY=xxx
DATABASE_URL=<Render Postgres Internal URL>
```

When `PUBLIC_URL` starts with `https://`, portal session and OAuth state cookies are set with `secure=True`.

Squarespace DNS:

| Host | Type | Value |
|------|------|-------|
| `ai` | CNAME | Render custom domain target |

Google OAuth consent screen can stay in Testing mode for a small class, but every student Gmail must be added as a test user. Switch to Production when the domain and app consent text are ready.
