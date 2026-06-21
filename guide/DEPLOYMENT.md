# Vans Coding Router 部署與設定完整指南

這份文件整理從本機開發到 Render 上線的完整流程，含 Google OAuth、Secret File、環境變數與常見問題。下次部署照此 checklist 逐步執行即可。

## 快速連結

| 用途 | URL |
|------|-----|
| Portal（管理／登入） | `https://ai.vanscoding.com/portal` |
| 根路徑（自動導向 Portal） | `https://ai.vanscoding.com/` |
| 健康檢查 | `https://ai.vanscoding.com/health` |
| OAuth 設定檢查 | `https://ai.vanscoding.com/auth/config` |
| 學生 API | `https://ai.vanscoding.com/v1/*` |
| Render 測試網址 | `https://vans-coding-router.onrender.com` |

正式網域尚未就緒時，將上表 `ai.vanscoding.com` 替換為 `vans-coding-router.onrender.com`。

---

## 1. 事前準備

開始前請準備：

- [ ] GitHub 帳號與 repo（本專案：`mz038197/vans_coding_router`）
- [ ] [Render](https://render.com) 帳號
- [ ] [Google Cloud Console](https://console.cloud.google.com/) 專案（OAuth）
- [ ] Squarespace DNS（若使用 `ai.vanscoding.com`）
- [ ] `OLLAMA_CLOUD_API_KEY`（必要）
- [ ] `OPENROUTER_API_KEY`（路由 Claude/GPT 時需要）

---

## 2. 本機開發

### 2.1 安裝與設定

```powershell
cd D:\Work\Python\vans_coding_router

New-Item -ItemType Directory -Force -Path "$HOME\.vans_coding_router"
Copy-Item config\router.example.yaml "$HOME\.vans_coding_router\router.yaml"

$env:VCR_CONFIG="$HOME\.vans_coding_router\router.yaml"
uv run uvicorn app:app --reload
```

### 2.2 本機驗證

| 網址 | 預期 |
|------|------|
| `http://127.0.0.1:8000/` | 302 → `/portal` |
| `http://127.0.0.1:8000/portal` | 登入頁 |
| `http://127.0.0.1:8000/health` | JSON `ok: true` |

### 2.3 本機登入模式

- **未設定** Google OAuth → Portal 顯示「開發模式登入」（僅本機用，不驗證身份）
- **已設定** `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` → 只顯示 Google 登入，dev login 關閉

本機可選用 `.env` 或 PowerShell 環境變數：

```powershell
$env:GOOGLE_CLIENT_ID="xxx.apps.googleusercontent.com"
$env:GOOGLE_CLIENT_SECRET="xxx"
$env:PUBLIC_URL="http://127.0.0.1:8000"
```

---

## 3. 推送到 GitHub

```powershell
cd D:\Work\Python\vans_coding_router

git add .
git commit -m "your message"
git push origin master
```

Render 從 GitHub 拉程式部署，**必须先 push**。

---

## 4. Render 部署（Blueprint）

專案含 [`render.yaml`](../render.yaml)，可一鍵建立 Web Service + PostgreSQL。

### 4.1 建立服務

1. Render Dashboard → **New** → **Blueprint**
2. 連接 GitHub repo：`vans_coding_router`
3. 確認預覽資源：
   - Web Service：`vans-coding-router`
   - PostgreSQL：`vans-coding-router-db`（plan: `basic-256mb`）
4. 按 **Apply**

### 4.2 Build / Start 指令（Blueprint 已含）

```bash
# Build
uv sync --frozen

# Start
uv run uvicorn app:app --host 0.0.0.0 --port $PORT
```

Health check path：`/health`

### 4.3 第一次 Deploy 後

第一次常因 Secret File 或 env 未填而 unhealthy，屬正常。完成第 5、6 步後 **Manual Deploy**。

---

## 5. Secret File（router.yaml）

### 5.1 在哪設定

Render → Web Service `vans-coding-router` → **Environment** → **Secret Files** → **Add Secret File**

| 欄位 | 值 |
|------|-----|
| Filename | `router.yaml` |
| Mount path | `/etc/secrets/router.yaml`（Blueprint 已設 `VCR_CONFIG` 指向此路徑） |

### 5.2 建議內容（正式環境）

以 [`config/router.example.yaml`](../config/router.example.yaml) 為底。**機密不要寫進 yaml**。

```yaml
public_url: "https://ai.vanscoding.com"
student_default_ttl_hours: 2

auth:
  teacher_domain: ""
  admin_emails:
    - "mz038197@gmail.com"
  google_client_id: ""
  google_client_secret: ""
  open_registration: true

database:
  path: "/tmp/router.db"
  archive_dir: "/tmp/archive"
  url: ""

prompt_logs:
  retention_days: 30

providers:
  ollama_cloud:
    type: openai_compatible
    base_url: "https://ollama.com/v1"
    api_key_env: "OLLAMA_CLOUD_API_KEY"
    enabled: true

  openrouter:
    type: openai_compatible
    base_url: "https://openrouter.ai/api/v1"
    api_key_env: "OPENROUTER_API_KEY"
    enabled: true
    extra_headers:
      HTTP-Referer: "https://ai.vanscoding.com"
      X-Title: "Vans Coding Router"

routing:
  default_provider: ollama_cloud
  rules:
    - match: "claude-*"
      provider: openrouter
    - match: "anthropic/*"
      provider: openrouter
    - match: "gpt-*"
      provider: openrouter
    - match: "llama*"
      provider: ollama_cloud
```

### 5.3 Secret File 放什麼、不放什麼

| 放 Secret File | 不放 Secret File（改 Environment） |
|----------------|-----------------------------------|
| `admin_emails`、路由規則、providers | Google Client ID / Secret |
| `student_default_ttl_hours` | API keys |
| `open_registration` | `SESSION_SECRET`（建議 env） |

---

## 6. Environment Variables

Render → Web Service → **Environment**

| 變數 | 值 | 必填 |
|------|-----|------|
| `VCR_CONFIG` | `/etc/secrets/router.yaml` | Blueprint 已設 |
| `PUBLIC_URL` | `https://ai.vanscoding.com` | 是 |
| `GOOGLE_CLIENT_ID` | Google OAuth Client ID | 是 |
| `GOOGLE_CLIENT_SECRET` | Google OAuth Secret | 是 |
| `SESSION_SECRET` | 強隨機字串 | Blueprint 可自動產生 |
| `OLLAMA_CLOUD_API_KEY` | Ollama Cloud key | 是 |
| `OPENROUTER_API_KEY` | OpenRouter key | 選填 |
| `DATABASE_URL` | Postgres 連線 | Blueprint 自動帶入 |

改完 env 或 Secret File 後 → **Save** → **Manual Deploy → Deploy latest commit**。

---

## 7. 設定優先順序（Environment vs Secret File）

程式先讀 yaml，再用環境變數覆蓋。**兩邊不是要你填兩份，而是同一設定的兩種來源；Environment 優先。**

| 設定 | Secret File | Environment | 生效來源 |
|------|-------------|-------------|----------|
| 公開網址 | `public_url` | `PUBLIC_URL` | **Environment** |
| Google OAuth | 留空 | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | **Environment** |
| Session | 可寫 | `SESSION_SECRET` | **Environment** |
| API keys | 用 `api_key_env` 指到 env | `OLLAMA_*`, `OPENROUTER_*` | **Environment** |
| 路由、admin、providers | 主要來源 | — | **Secret File** |

**實務規則：Render 上每個欄位只填一個來源；兩邊都填時以 Environment 為準。**

---

## 8. `PUBLIC_URL` / `public_url` 到底填什麼

`PUBLIC_URL` 是 **OAuth 用的主網址**（不是「使用者從哪進站」的開關）。

填：**使用者正式對外使用的根網址**，不含路徑、不含尾端 `/`。

```text
https://ai.vanscoding.com
```

Google OAuth callback 固定為：

```text
{PUBLIC_URL}/auth/google/callback
```

登入成功後回到：

```text
{PUBLIC_URL}/portal
```

### 測試階段只用 onrender

若 DNS 尚未就緒，**三處全部改成 onrender**（不要混用）：

| 位置 | 值 |
|------|-----|
| Environment `PUBLIC_URL` | `https://vans-coding-router.onrender.com` |
| Secret File `public_url` | 同上 |
| Google redirect URI | `https://vans-coding-router.onrender.com/auth/google/callback` |

### 正式上線

改回 `https://ai.vanscoding.com`，redeploy，Google Console 保留兩條 redirect URI 亦可（見下節）。

---

## 9. Google OAuth 設定

### 9.1 OAuth 同意畫面

1. Google Cloud Console → **APIs & Services** → **OAuth consent screen**
2. User type：**External**
3. 填 App name、support email
4. Scopes：預設 `openid email profile` 即可
5. **Test users**：加入每位要登入的 Gmail（Testing 模式必填）

### 9.2 OAuth Client ID

1. **Credentials** → **Create Credentials** → **OAuth client ID**
2. Type：**Web application**
3. **Authorized redirect URIs**（可同時加多條）：

```text
https://ai.vanscoding.com/auth/google/callback
https://vans-coding-router.onrender.com/auth/google/callback
```

4. 複製 Client ID、Client Secret → 填入 Render Environment
5. **Redeploy**

### 9.3 驗證 OAuth 已生效

開 `{PUBLIC_URL}/auth/config`：

```json
{
  "oauth_enabled": true,
  "redirect_uri": "https://ai.vanscoding.com/auth/google/callback"
}
```

- `oauth_enabled: true` → Google 憑證有效
- `redirect_uri` 必須與 Google Console 其中一條完全一致

Portal 應**只**顯示「使用 Google 帳號登入」，不應再有「開發模式登入」。

### 9.4 雙網域行為（重要）

| 行為 | 說明 |
|------|------|
| `/` → `/portal` | 從哪個 host 進來，就留在哪個 host |
| Google 登入 callback | **永遠**走 `PUBLIC_URL` 那個網域 |
| 登入成功後 | 回到 `{PUBLIC_URL}/portal` |
| Session cookie | **不跨網域共用** |

例：`PUBLIC_URL=https://ai.vanscoding.com` 時，從 onrender 開 Portal 登入 Google，完成後會到 `ai.vanscoding.com/portal`。

---

## 10. 自訂網域（Squarespace DNS）

### 10.1 Render

Web Service → **Settings** → **Custom Domains** → 新增 `ai.vanscoding.com`

### 10.2 Squarespace DNS

| Host | Type | Value |
|------|------|-------|
| `ai` | CNAME | Render 提供的 hostname |

### 10.3 切換正式網域

DNS 生效後：

1. `PUBLIC_URL` → `https://ai.vanscoding.com`
2. Secret File `public_url` → 同上
3. Redeploy
4. 確認 `/auth/config` 的 `redirect_uri` 正確

---

## 11. 上線後驗證 Checklist

- [ ] `GET /` → 302 到 `/portal`
- [ ] `GET /health` → 200
- [ ] `GET /auth/config` → `oauth_enabled: true`，`redirect_uri` 正確
- [ ] Portal Google 登入成功
- [ ] Admin email 登入後角色含 `admin`
- [ ] 建立 class / session、學生 redeem invite code 可取得 `vcr_sk_...`
- [ ] `POST /v1/chat/completions` 帶 API key 可打通 upstream

---

## 12. 學生 BYOK 設定

學生 redeem 邀請碼後，在 VS Code / Copilot / 其他 OpenAI 相容 client 設定：

```bash
OPENAI_BASE_URL=https://ai.vanscoding.com/v1
OPENAI_API_KEY=vcr_sk_xxxxxxxx
```

詳見 [`guide/VSCODE_COPILOT_BYOK.md`](VSCODE_COPILOT_BYOK.md)。

---

## 13. 常見問題

| 現象 | 原因 | 處理 |
|------|------|------|
| `/` 顯示 Not Found | 舊版未 deploy | push 含 root redirect 的版本並 redeploy |
| Portal 仍有「開發模式登入」 | Google env 未設或未 redeploy | 填 `GOOGLE_CLIENT_*`，redeploy，查 `/auth/config` |
| `redirect_uri_mismatch` | `PUBLIC_URL` 與 Google Console 不一致 | 三處對齊後 redeploy |
| Access blocked（Testing） | 該 Gmail 不在 Test users | OAuth consent screen 加 Test user |
| 登入成功但不是 admin | `admin_emails` 未含該 Gmail | 改 Secret File，redeploy |
| 改 Secret File 沒效果 | 未 redeploy 或 env 覆蓋 | Save + Manual Deploy |
| 改 yaml 的 Google 沒效果 | Environment 優先 | 改 Environment 而非 yaml |
| Deploy 後資料消失 | `DATABASE_URL` 未生效或仍走 SQLite | 確認 Render Environment 有 `DATABASE_URL`；redeploy 後 users/classes 應保留 |
| Blueprint Postgres `starter` 錯誤 | 舊 plan 名稱 | 使用 `basic-256mb`（已修正於 render.yaml） |

---

## 14. 已知限制

- **資料庫**：本地預設 SQLite；Render 上 Blueprint 會注入 `DATABASE_URL`，app 自動使用 PostgreSQL。Prompt log archive 在 Postgres 存於同庫 `prompt_logs_archive` 表（SQLite 仍用 yearly `.db` 檔）。
- **雙網域 OAuth**：未實作依 Host 動態切換 callback；OAuth 以單一 `PUBLIC_URL` 為準。
- **Free tier**：Render 免費服務可能休眠，首請求較慢。

---

## 15. 日常更新流程

程式有變更時：

```powershell
git add .
git commit -m "..."
git push origin master
```

Render 若開 automatic deploy 會自動建置；否則 **Manual Deploy**。

只改 Render 設定（env / Secret File）時：**不必 push**，Save 後 Manual Deploy 即可。

---

## 16. 相關文件

| 文件 | 內容 |
|------|------|
| [`README.md`](../README.md) | 專案概覽與 API |
| [`guide/OAUTH_AND_RENDER.md`](OAUTH_AND_RENDER.md) | OAuth 與 Render 設定摘要 |
| [`guide/VSCODE_COPILOT_BYOK.md`](VSCODE_COPILOT_BYOK.md) | 學生端 Copilot 設定 |
| [`config/router.example.yaml`](../config/router.example.yaml) | 本機設定範本 |
| [`render.yaml`](../render.yaml) | Render Blueprint |
