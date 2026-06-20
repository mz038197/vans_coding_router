# OAuth and Render

Production URL:

```text
https://ai.vanscoding.com
```

Google OAuth redirect URI:

```text
https://ai.vanscoding.com/auth/google/callback
```

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
