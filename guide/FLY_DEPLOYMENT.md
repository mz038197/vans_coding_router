# Fly.io + Neon 部署指南

從 Render 遷移到 **Fly.io（App）+ Neon（PostgreSQL）**，避開 Render/Cloudflare WAF 擋 VS Code 的問題。

## 架構

```text
ai.vanscoding.com (Squarespace DNS)
        │
        ▼
   Fly.io (vans-coding-router)
        │
        ▼
   Neon PostgreSQL (DATABASE_URL)
```

Stg 可繼續用 Render `vans-coding-router-stg`，或另開 Fly app。

---

## 1. 事前準備

- [ ] [Fly.io](https://fly.io) 帳號
- [ ] [Neon](https://neon.tech) 帳號（免費 tier 即可）
- [ ] 本機安裝 flyctl：`winget install Fly-io.flyctl`
- [ ] 登入：`fly auth login`
- [ ] Render Postgres **External Database URL**（搬資料用）

---

## 2. Neon 建立資料庫

1. Neon Console → **New Project**（例：`vans-coding-router`）
2. 複製 **Connection string**（含 `?sslmode=require`）  
   格式：`postgresql://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require`
3. 先留著，稍後寫入 `fly.secrets.env` 的 `DATABASE_URL`

### 從 Render 搬資料（可選，保留學生 / API keys）

Render Dashboard → Postgres → **External Database URL**：

```powershell
# 需 PostgreSQL 16 client tools (pg_dump / pg_restore)
pg_dump "postgres://RENDER_URL" --no-owner --no-acl -F c -f vans_router.dump
pg_restore -d "postgresql://NEON_URL" --no-owner --no-acl --clean --if-exists vans_router.dump
```

若全新開始、不搬舊資料：跳過 dump，Fly 首次啟動會 `CREATE TABLE IF NOT EXISTS`。

---

## 3. 設定 Secrets

```powershell
Copy-Item config\fly.secrets.env.example "$HOME\.vans_coding_router\fly.secrets.env"
notepad "$HOME\.vans_coding_router\fly.secrets.env"
```

填入：

| 變數 | 說明 |
|------|------|
| `DATABASE_URL` | Neon connection string |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | 與 Render 相同 |
| `SESSION_SECRET` | **建議與 Render 相同**（已登入 session 可沿用） |
| `OLLAMA_CLOUD_API_KEY` | 必要 |
| `OPENROUTER_API_KEY` | 選填 |
| `OPENAI_API_KEY` | 選填 |

`PUBLIC_URL` 已在 `fly.toml` 設為 `https://ai.vanscoding.com`（Environment 覆蓋 yaml）。

---

## 4. 部署

```powershell
cd D:\Work\Python\vans_coding_router
powershell -ExecutionPolicy Bypass -File scripts\deploy-fly.ps1
```

腳本會：

1. 檢查 `fly auth`
2. 建立 app `vans-coding-router`（若不存在）
3. `fly secrets import` 從 `fly.secrets.env`
4. `fly deploy`（Docker build + 上線）

首次 deploy 約 3–5 分鐘。

### 驗證（Fly 預設網域）

```powershell
fly status --app vans-coding-router
fly logs --app vans-coding-router
```

瀏覽器開：`https://vans-coding-router.fly.dev/health` → `ok: true`

---

## 5. 自訂網域 ai.vanscoding.com

### 5.1 Fly 加憑證

```powershell
fly certs add ai.vanscoding.com --app vans-coding-router
fly certs show ai.vanscoding.com --app vans-coding-router
```

記下 Fly 顯示的 **CNAME 目標**（例：`vans-coding-router.fly.dev` 或 `xxx.fly.dev`）。

### 5.2 Squarespace DNS

| 類型 | 主機 | 值 |
|------|------|-----|
| CNAME | `ai` | Fly 給的目標 |

**移除** 指向 Render 的舊 CNAME/A 記錄。

### 5.3 Google OAuth

Google Console → OAuth Client → **Authorized redirect URIs** 保留：

```text
https://ai.vanscoding.com/auth/google/callback
```

（網域不變則不用改；若先用 `*.fly.dev` 測試，需加對應 callback。）

---

## 6. 切換流量 checklist

- [ ] Neon DB 有資料（或接受空庫）
- [ ] `https://vans-coding-router.fly.dev/health` OK
- [ ] `https://vans-coding-router.fly.dev/portal` 可 Google 登入
- [ ] VS Code 暫改 model URL 測 `*.fly.dev` Agent（確認無 WAF）
- [ ] DNS 切到 Fly
- [ ] `https://ai.vanscoding.com/health` OK
- [ ] Render prod **暫停或保留**作 rollback

---

## 7. 日常指令

```powershell
# 重新部署
fly deploy --app vans-coding-router

# 更新 secrets
powershell -ExecutionPolicy Bypass -File scripts\deploy-fly.ps1 -SecretsOnly

# 看 log
fly logs --app vans-coding-router

# SSH 進 machine（除錯）
fly ssh console --app vans-coding-router
```

---

## 7b. Push 自動 deploy（GitHub Actions，推薦）

Fly Dashboard 的「Connect GitHub」在 **CLI 建立的 app** 上常常找不到或要新 Launch UI。  
官方推薦改用 **GitHub Actions**（repo 已含 `.github/workflows/fly-deploy.yml`）。

### 一次性設定

**1. 產生 Fly deploy token（本機）：**

```powershell
flyctl tokens create deploy -x 999999h --app vans-coding-router
```

複製整段輸出（含開頭 `FlyV1 ` 和空格）。

**2. 加到 GitHub repo secret：**

GitHub → `mz038197/vans_coding_router` → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Name | Value |
|------|-------|
| `FLY_API_TOKEN` | 上一步複製的 token |

**3. Push workflow 檔（若尚未 push）：**

```powershell
git add .github/workflows/fly-deploy.yml
git commit -m "ci: add Fly deploy on push to master"
git push origin master
```

之後每次 `git push origin master` → GitHub **Actions** tab 會跑 `Fly Deploy` → 自動 `flyctl deploy`。

Secrets（`DATABASE_URL` 等）仍在 Fly，**不要**放 GitHub。

### Dashboard 路徑（若仍想用 Fly 內建 CD）

部分帳號：**App → Deployments → Settings → Auto deploy**。  
若沒有這選項，用上面 GitHub Actions 即可。

---

## 8. 與 Render 差異

| | Render | Fly.io |
|--|--------|--------|
| 設定檔 | Secret File `/etc/secrets/router.yaml` | Image 內 `config/router.prod.yaml` |
| DB | Render Postgres | Neon（`DATABASE_URL`） |
| WAF | Cloudflare 內建，擋 VS Code | 無同等 WAF |
| Blueprint | `render.yaml` | `fly.toml` + `Dockerfile` |

機密一律用 **`fly secrets`** / `fly.secrets.env`，不要 commit。

---

## 9. 故障排除

| 問題 | 處理 |
|------|------|
| Deploy 失敗 build | 本機 `docker build .` 測試；確認 Python 3.13 |
| `/health` 502 | `fly logs` 看 DATABASE_URL / API key |
| OAuth redirect 錯 | 確認 `PUBLIC_URL` 與 Google Console URI 一致 |
| 學生 key 失效 | 確認 `SESSION_SECRET` 與 DB 已 migrate |

---

## 相關檔案

- [`Dockerfile`](../Dockerfile)
- [`fly.toml`](../fly.toml)
- [`config/router.prod.yaml`](../config/router.prod.yaml)
- [`scripts/deploy-fly.ps1`](../scripts/deploy-fly.ps1)

Render 部署見 [`DEPLOYMENT.md`](DEPLOYMENT.md)。
