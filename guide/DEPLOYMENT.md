# Vans Coding Router 部署指南

Production：**Fly.io（App）+ Neon（PostgreSQL）+ Squarespace DNS**。

## 快速連結

| 用途 | URL |
|------|-----|
| Portal | `https://ai.vanscoding.com/portal` |
| 健康檢查 | `https://ai.vanscoding.com/health` |
| OAuth 檢查 | `https://ai.vanscoding.com/auth/config` |
| 學生 API | `https://ai.vanscoding.com/v1/*` |
| Fly 預設網域 | `https://vans-coding-router.fly.dev` |

## 架構

```text
ai.vanscoding.com (Squarespace DNS)
        │
        ▼
   Fly.io (vans-coding-router, sin)
        │
        ▼
   Neon PostgreSQL (DATABASE_URL)
```

---

## 1. 事前準備

- [ ] [Fly.io](https://fly.io) 帳號 + `flyctl`（`winget install Fly-io.flyctl`）
- [ ] [Neon](https://neon.tech) 專案與 connection string
- [ ] Google Cloud OAuth Client
- [ ] Squarespace DNS（`ai.vanscoding.com`）
- [ ] GitHub repo secret：`FLY_API_TOKEN`（自動 deploy）

---

## 2. Neon 資料庫

1. Neon Console → **New Project**
2. 複製 connection string（含 `?sslmode=require`）
3. 寫入 `%USERPROFILE%\.vans_coding_router\fly.secrets.env` 的 `DATABASE_URL`

首次 deploy 會 `CREATE TABLE IF NOT EXISTS`。若要從舊 Postgres 搬資料：

```powershell
pg_dump "postgres://OLD..." --no-owner --no-acl -F c -f vans_router.dump
pg_restore -d "postgresql://NEON..." --no-owner --no-acl --clean --if-exists vans_router.dump
```

---

## 3. Fly Secrets

```powershell
Copy-Item config\fly.secrets.env.example "$HOME\.vans_coding_router\fly.secrets.env"
notepad "$HOME\.vans_coding_router\fly.secrets.env"
```

| 變數 | 說明 |
|------|------|
| `DATABASE_URL` | Neon connection string |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth |
| `SESSION_SECRET` | 強隨機字串 |
| `OLLAMA_CLOUD_API_KEY` | 必要 |
| `OPENROUTER_API_KEY` / `OPENAI_API_KEY` | 選填 |

非機密設定在 image 內 [`config/router.prod.yaml`](../config/router.prod.yaml)。`PUBLIC_URL` 在 [`fly.toml`](../fly.toml) 設為 `https://ai.vanscoding.com`。

套用 secrets：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy-fly.ps1 -SecretsOnly
```

---

## 4. 部署

### 手動

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy-fly.ps1
```

### 自動（已設定）

`git push origin master` → GitHub Actions [`.github/workflows/fly-deploy.yml`](../.github/workflows/fly-deploy.yml) → `flyctl deploy`。

一次性設定 deploy token：

```powershell
flyctl tokens create deploy -x 999999h --app vans-coding-router
```

GitHub → repo **Settings → Secrets → Actions** → `FLY_API_TOKEN`。

### 驗證

```powershell
fly status --app vans-coding-router
curl https://vans-coding-router.fly.dev/health
```

---

## 5. 自訂網域

```powershell
fly certs add ai.vanscoding.com --app vans-coding-router
fly certs setup ai.vanscoding.com --app vans-coding-router
```

Squarespace DNS（例）：

| 類型 | 主機 | 值 |
|------|------|-----|
| CNAME | `ai` | `125ld00.vans-coding-router.fly.dev`（以 `fly certs setup` 輸出為準） |

Google OAuth redirect URI：

```text
https://ai.vanscoding.com/auth/google/callback
```

詳見 [`guide/OAUTH.md`](OAUTH.md)。

---

## 6. 日常指令

```powershell
fly deploy --app vans-coding-router
fly logs --app vans-coding-router
fly secrets set KEY=value --app vans-coding-router
fly scale show --app vans-coding-router
```

改 region（例：對齊 Neon Singapore）：

```powershell
fly scale count 1 --region sin --app vans-coding-router --yes
fly scale count 0 --region nrt --app vans-coding-router --yes
```

---

## 7. 設定優先順序

程式先讀 `router.yaml`（`VCR_CONFIG`），再以環境變數覆蓋。

| 設定 | YAML | Fly secret / env |
|------|------|------------------|
| `PUBLIC_URL` | `public_url` | `PUBLIC_URL` |
| Google OAuth | 留空 | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| DB | 留空 | `DATABASE_URL` |
| API keys | `api_key_env` 參照 | `OLLAMA_CLOUD_API_KEY` 等 |

---

## 8. 故障排除

| 問題 | 處理 |
|------|------|
| GitHub Actions deploy 失敗 | 確認 `FLY_API_TOKEN`；看 Actions log |
| `/health` 502 | `fly logs`；檢查 `DATABASE_URL`、provider API keys |
| OAuth redirect 錯 | `PUBLIC_URL` 與 Google Console URI 一致 |
| 學生 key 無效 | Neon 是否有資料；Portal 重發 key |
| VS Code 401 | 非 WAF；查 key 與 `requestHeaders`（見 [`VSCODE_COPILOT_BYOK.md`](VSCODE_COPILOT_BYOK.md)） |

---

## 相關檔案

| 檔案 | 用途 |
|------|------|
| [`Dockerfile`](../Dockerfile) | Container build |
| [`fly.toml`](../fly.toml) | Fly app 設定 |
| [`config/router.prod.yaml`](../config/router.prod.yaml) | 非機密 production 設定 |
| [`scripts/deploy-fly.ps1`](../scripts/deploy-fly.ps1) | Secrets + deploy 腳本 |

本機開發見 [`LOCAL_DEV.md`](LOCAL_DEV.md)。
