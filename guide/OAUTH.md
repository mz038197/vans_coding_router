# Google OAuth

Production URL：

```text
https://ai.vanscoding.com
```

Redirect URI（Google Cloud Console）：

```text
https://ai.vanscoding.com/auth/google/callback
```

登入成功後導向 `{PUBLIC_URL}/portal`。`PUBLIC_URL` 由 Fly secret / `fly.toml` 設定，須與使用者實際造訪的網域一致。

## Fly 環境變數

```bash
PUBLIC_URL=https://ai.vanscoding.com
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxx
SESSION_SECRET=<strong-random-secret>
```

不要把 Google client secret 寫進 `router.yaml` 或 commit。

## 本機

```text
http://127.0.0.1:8000/auth/google/callback
```

Google Console 需加此 URI；本機 `PUBLIC_URL=http://127.0.0.1:8000`。

## DNS

| Host | Type | Value |
|------|------|-------|
| `ai` | CNAME | Fly 提供的 target（`fly certs setup ai.vanscoding.com`） |

OAuth consent screen 小班可維持 Testing，每位學生 Gmail 加為 test user。

完整部署見 [`DEPLOYMENT.md`](DEPLOYMENT.md)。
