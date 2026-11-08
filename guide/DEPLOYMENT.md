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
| `DATABASE_URL` | Neon 專案 `VCRouter-db` 的 database `neondb`。執行中的服務用 role `vans_coding_router_app`，不是 `neondb_owner`。這組 role 在 `neondb` 的 `public` 可以建物件、讀和寫；不能連 `vans_signals` 或 `vans_mcp_server`，也不是 superuser。驗收是那兩個庫都連不上。換這組 secret 排在最後：`vans_signals_app` 已上線、驗票已切換、表已搬完、`vans-mcp-server` 已用 `vans_mcp_server_app`。`neondb_owner` 只留作管理帳號 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth |
| `SESSION_SECRET` | 強隨機字串 |
| `OLLAMA_CLOUD_API_KEY` | 必要（Ollama Cloud 帳號 A） |
| `OLLAMA_CLOUD_API_KEY_2` | 選填（帳號 B；與 A 為不同訂閱時可內部分流） |
| `OPENROUTER_API_KEY` | 選填（OpenRouter 帳號 A） |
| `OPENROUTER_API_KEY_2` | 選填（帳號 B；與 A 為不同帳號時可內部分流） |
| `OPENAI_API_KEY` | 選填 |
| `TAVILY_API_KEY` | 選填（Web Search；未設定時 `POST /v1/search` 回 503 `web_search_unavailable`） |
| `VCR_SERVICE_TOKENS` | 必要（正式環境沒設定或格式錯誤時 router 拒絕啟動）。每個 Partner Service 的 Service Credential，JSON 物件 `{"<credential 的 SHA-256 小寫 hex>": "<Partner Service 名稱>"}`，格式跟 vans-signals 的 `SIGNALS_TOKENS` 相同。產生和輪換見下方〈Service Credential〉 |
| `VANS_SIGNALS_URL` / `VANS_SIGNALS_TOKEN` | 正式環境才設。把 `src` 的 ERROR 日誌送到 vans-signals。網址是服務根位址（例如 `https://vans-signals.fly.dev`），權杖是該服務發給 `vans-coding-router` 的 bearer。少一項就完全不送，本機與 staging 維持空白 |

`ollama_cloud` 在 [`config/router.prod.yaml`](../config/router.prod.yaml) 使用 `api_key_envs` 掛兩把 key：學生仍用同一把 `vcr_sk_` 與 `ollama_cloud@...`，router 以 least-in-flight 分流，並以 `max_concurrent_per_key`（預設 3）在打上游前排隊，降低 Ollama Cloud rate limit。只設第一把 key 時行為與單帳號相同。

`openrouter` 同樣走 UpstreamKeyPool 與 `api_key_envs`（`OPENROUTER_API_KEY`、`OPENROUTER_API_KEY_2`），`max_concurrent_per_key` 為 6。兩把鑰應來自不同 OpenRouter 帳號才有額度分流；只設第一把時行為與單帳號相同。Credit Exhaustion（帳號或該鑰 credit 不夠）時 Key Failover；一般 429 rate limit 不換鑰。

非機密設定在 image 內 [`config/router.prod.yaml`](../config/router.prod.yaml)。`PUBLIC_URL` 在 [`fly.toml`](../fly.toml) 設為 `https://ai.vanscoding.com`。

套用 secrets：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy-fly.ps1 -SecretsOnly
```

### Service Credential（Key Check）

Partner Service（vans-mcp-server、pokemon-world-mcp、road-test）用自己的 Service Credential 呼叫 `POST https://ai.vanscoding.com/internal/key-check`（ADR 0076、0077）。每個服務一組，互不共用。router 只存 credential 的 SHA-256，不存原文。

**產生一組新的 credential**（Git Bash）：

```bash
CRED=$(openssl rand -hex 32)                          # 1. 產生
fly secrets set VCR_SERVICE_CREDENTIAL="$CRED" --app road-test   # 2. 存成該 Partner Service 的 secret
printf '%s' "$CRED" | sha256sum | cut -d' ' -f1       # 3. 算 SHA-256（不要多一個換行）
```

把第 3 步的雜湊加進 router 的 `VCR_SERVICE_TOKENS`，三個服務放在同一個 JSON 物件裡，每次設定都要寫出完整的物件：

```bash
fly secrets set --app vans-coding-router VCR_SERVICE_TOKENS='{"<mcp 的雜湊>":"vans-mcp-server","<pokemon 的雜湊>":"pokemon-world-mcp","<road-test 的雜湊>":"road-test"}'
```

JSON 帶雙引號，請用 Git Bash 的 `fly secrets set` 直接設，不要放進 `fly.secrets.env` 經 `deploy-fly.ps1` 傳（PowerShell 傳給原生程式時會吃掉雙引號）。新設定在 router 重新部署或重啟後生效。

**輪換**（不中斷服務）：

1. 照上面產生新 credential，**先**把新雜湊加進 `VCR_SERVICE_TOKENS`（同一個服務名稱暫時對應新舊兩個雜湊），部署 router。
2. 換掉該 Partner Service 的 `VCR_SERVICE_CREDENTIAL`，部署那個服務。確認它的 Key Check 正常。
3. 最後從 `VCR_SERVICE_TOKENS` 刪掉舊雜湊，部署 router。

某個服務的 credential 外洩時，只換那一組；其他服務的雜湊不動。

**沒設定時**：正式環境（有 `FLY_APP_NAME`）沒設 `VCR_SERVICE_TOKENS` 會拒絕啟動，所以第一次上線 Key Check 前要先設好。本機沒設定時照常啟動，Key Check 一律回 401。

**限流**：每個 Partner Service 每分鐘最多呼叫 Key Check 600 次（各自計算，互不影響），超過的呼叫回 429。一個服務超過時送一筆 ERROR Signal，只寫服務名稱；同一次超量期間不重複送，等它再有呼叫被放行後又超過才再送。要調整時在 `router.yaml` 加：

```yaml
key_check:
  calls_per_minute_per_service: 600
```

數字必須是正整數，否則 router 拒絕啟動。計數在記憶體裡，重啟歸零。

**回應合約**：通過、拒絕和 400 的範例在 [`docs/contracts/key-check/`](../docs/contracts/key-check/)，router 的測試會斷言真實回應符合這些範例；Partner Service 的測試直接讀這些檔案（或複製一份並註明來源 commit）。

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
