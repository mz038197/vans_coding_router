# 本機開發與 Portal 指引（Agent Runbook）

> **給 Cursor / AI Agent 用**：下次要在本機跑 Portal、改 UI、或設定 Google 登入，照這份文件做。  
> 正式部署見 [`DEPLOYMENT.md`](DEPLOYMENT.md)（含 **Stg 環境**）；OAuth 摘要見 [`OAUTH_AND_RENDER.md`](OAUTH_AND_RENDER.md)。

---

## 1. 專案速覽

| 項目 | 說明 |
|------|------|
| 後端 | FastAPI，`app.py` 入口 |
| 前端 | **單一檔案** [`src/presentation/fastapi/web/portal.html`](../src/presentation/fastapi/web/portal.html)（vanilla HTML/CSS/JS，無 npm） |
| Portal 路由 | `GET /portal` → 回傳 `portal.html`（[`portal_router.py`](../src/presentation/fastapi/routers/portal_router.py)） |
| 本機設定 | `%USERPROFILE%\.vans_coding_router\router.yaml`（**不在 git 內**） |
| 啟動腳本 | [`scripts/run-local.ps1`](../scripts/run-local.ps1) |

---

## 2. 一鍵啟動本機

```powershell
cd D:\Work\Python\vans_coding_router
powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1
```

腳本會：

1. 若無設定檔，從 `config/router.example.yaml` 複製到 `%USERPROFILE%\.vans_coding_router\router.yaml`
2. 設定 `VCR_CONFIG`、`PUBLIC_URL=http://127.0.0.1:8000`
3. **清掉佔用 8000 埠的舊程序**（避免多個 uvicorn 同時 listen）
4. 執行 `uv run uvicorn app:app --reload --host 127.0.0.1 --port 8000`

### 驗證

| URL | 預期 |
|-----|------|
| http://127.0.0.1:8000/ | 302 → `/portal` |
| http://127.0.0.1:8000/portal | 登入頁或主畫面 |
| http://127.0.0.1:8000/health | `ok: true` |
| http://127.0.0.1:8000/auth/config | 見下方 OAuth 一節 |

---

## 3. Portal UI 架構（2026-06 改版後）

### 3.1 設計方向

- 視覺參考：ProtoFlow / NeuralForge **深色玻璃擬態**（slate-950、indigo、glass-card、neural-grid）
- **單檔** `portal.html`，不引入 React / Vite / Tailwind build
- **無左側 sidebar**；登入後用垂直 section + 老師區水平 tabs

### 3.2 雙 Layout Shell（同一 HTML）

```
#loginShell（未登入）
  └─ 頂部 nav（品牌）
  └─ hero 置中 glass-card（Google / dev 登入）

#appShell（已登入，.hidden 切換）
  └─ 頂部 nav（品牌 + #navWho 姓名/角色 + 登出）
  └─ main.page-main
       ├─ details.api-config（BYOK snippet，#profileConfig）
       ├─ #student（學生：邀請碼、VS Code、有效 Key）
       └─ #teacher（老師 tabs：keyTab / classTab / monitorTab / adminTab）
```

### 3.3 關鍵 JS

| 函式 | 用途 |
|------|------|
| `showLoginShell()` / `showAppShell()` | 登入前後切換 shell |
| `refresh()` | 呼叫 `/auth/me`；成功 → app shell，失敗 → login shell |
| `showTab(id)` | 老師區 tab；含 `.tab-active` 高亮 |
| `initLogin()` | 讀 `/auth/config`，決定 OAuth 或 dev 登入 |

### 3.4 改 UI 時注意

- **只改** `portal.html` 即可；後端通常不用動
- 保留既有 `id`（`#invite`、`#teacher`、`#monitorClassId` 等），否則 JS 會斷
- 動態 HTML 字串沿用 `.tag`、`.hint`、`.error` 等 class，改 CSS 即可
- 不要拆成第二個 HTML；不要加 sidebar，除非使用者明確要求

---

## 4. 本機 Google OAuth

### 4.1 行為

- `auth.google_client_id` **與** `auth.google_client_secret` **都有值** → Portal 只顯示 Google 登入
- 任一為空 → 顯示「開發模式登入」（`POST /auth/google`，不驗證身份，**僅本機**）

Callback URL 由設定決定：

```text
{PUBLIC_URL}/auth/google/callback
```

本機應為：`http://127.0.0.1:8000/auth/google/callback`

### 4.2 建議設定方式（本機）

**憑證放在 `%USERPROFILE%\.vans_coding_router\router.yaml`**（勿 commit）：

```yaml
public_url: "http://127.0.0.1:8000"

auth:
  google_client_id: "xxx.apps.googleusercontent.com"
  google_client_secret: "GOCSPX-xxx"
  session_secret: "change-me-local"
  open_registration: true
```

憑證來源（擇一）：

1. 使用者本機已有 `client_secret_*.json`（Google Cloud 下載的 OAuth 用戶端 JSON）
2. 從 Render 環境變數複製 `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`（需使用者提供）

範本：`%USERPROFILE%\.vans_coding_router\secrets.env.example`（可選，見下節取捨）

### 4.3 Google Cloud Console（必做）

在 [OAuth 2.0 Client](https://console.cloud.google.com/apis/credentials?project=vans-coding-router) 的 **Authorized redirect URIs** 加入：

```text
http://127.0.0.1:8000/auth/google/callback
http://localhost:8000/auth/google/callback   # 可選
```

正式環境 URI 保留：

```text
https://ai.vanscoding.com/auth/google/callback
```

未加本機 URI 會出現 **`redirect_uri_mismatch`**。

Consent screen 若為 **Testing**，登入用的 Gmail 須在測試使用者名單內。

### 4.4 驗證 OAuth 已生效

```powershell
curl -s http://127.0.0.1:8000/auth/config
```

預期：

```json
{
  "oauth_enabled": true,
  "redirect_uri": "http://127.0.0.1:8000/auth/google/callback",
  "public_url": "http://127.0.0.1:8000"
}
```

若 `oauth_enabled: false`，見第 6 節故障排除。

### 4.5 環境變數 vs YAML（本機取捨）

| 方式 | Render 正式環境 | 本機 |
|------|-----------------|------|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` 環境變數 | **推薦** | 可用，但見下方陷阱 |
| 寫入 `router.yaml` | **不要**（Secret 進 YAML） | **推薦**（檔案在 home，不在 git） |
| `uv run --env-file secrets.env` | — | 單次 `uv run` 有效；搭配 `--reload` 子程序可能讀不到 |

**實務結論**：本機 Google 登入請寫入 `%USERPROFILE%\.vans_coding_router\router.yaml`，用 `scripts/run-local.ps1` 啟動。

---

## 5. 本機檔案位置

```text
%USERPROFILE%\.vans_coding_router\
├── router.yaml              # 主設定（本機 OAuth 放這裡）
├── router.db                # SQLite（無 DATABASE_URL 時）
├── secrets.env              # 可選；勿 commit
├── secrets.env.example      # 範本
└── client_secret_*.json     # Google 下載的 OAuth JSON（勿 commit）
```

**勿提交 git**：`.env`、`secrets.env`、`client_secret_*.json`、含 secret 的 `router.yaml`（repo 內的 `config/router.example.yaml` 維持空 google 欄位）。

---

## 6. 故障排除

### `oauth_enabled: false` 但 YAML 已有憑證

1. **多個 uvicorn 佔 8000** — 最常見。執行：
   ```powershell
   Get-NetTCPConnection -LocalPort 8000 -State Listen |
     ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
   ```
   再跑 `scripts/run-local.ps1`。

2. **`VCR_CONFIG` 未指向正確 yaml** — 確認：
   ```powershell
   $env:VCR_CONFIG="$HOME\.vans_coding_router\router.yaml"
   ```

3. **用 Python 直接驗證設定載入**：
   ```powershell
   $env:VCR_CONFIG="$HOME\.vans_coding_router\router.yaml"
   uv run python -c "from src.infrastructure.config import load_router_settings; s=load_router_settings(); print(bool(s.auth.google_client_id), bool(s.auth.google_client_secret))"
   ```
   應輸出 `True True`。

### Google 登入後 `redirect_uri_mismatch`

- 比對 `/auth/config` 的 `redirect_uri` 與 Google Console 的 Authorized redirect URIs **完全一致**（含 `http` vs `https`、127.0.0.1 vs localhost）

### Portal 仍顯示「開發模式登入」

- Google 憑證未載入 → 查 `/auth/config`
- 改完 `router.yaml` 後需 **重啟** uvicorn（`--reload` 不監看 home 目錄下的 yaml）

### 改 `portal.html` 沒反映

- 確認只跑 **一個** 本機 server
- 硬重新整理瀏覽器（Ctrl+F5）

---

## 7. Agent 常見任務 Checklist

### 啟動本機給使用者預覽

- [ ] `powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1`
- [ ] 確認 `/auth/config` 與 `/portal` 200
- [ ] 告知 URL：http://127.0.0.1:8000/portal

### 使用者要本機 Google 登入

- [ ] 確認 `%USERPROFILE%\.vans_coding_router\router.yaml` 有 `google_client_id` / `google_client_secret`
- [ ] 若只有 `client_secret_*.json`，從 JSON 的 `web.client_id` / `web.client_secret` 寫入 yaml
- [ ] 提醒使用者在 Google Console 加本機 redirect URI
- [ ] 重啟 server，驗證 `oauth_enabled: true`

### 改 Portal 視覺

- [ ] 只編輯 `src/presentation/fastapi/web/portal.html`
- [ ] 維持 `#loginShell` / `#appShell` 與既有 `id`
- [ ] 不要加 sidebar，除非使用者明确要求
- [ ] 本機 reload 後請使用者重新整理 `/portal`

### 不要做的事

- 不要把 Google secret 寫進 repo 內的 yaml 或 commit
- 不要為 Portal 加 React/npm 除非使用者明确要求
- 不要 force push、不要改 git config

---

## 8. 相關程式碼索引

| 用途 | 路徑 |
|------|------|
| Portal HTML | `src/presentation/fastapi/web/portal.html` |
| Portal API / 登入路由 | `src/presentation/fastapi/routers/portal_router.py` |
| 設定載入 | `src/infrastructure/config.py` → `load_router_settings()` |
| Google OAuth | `src/infrastructure/auth/google_oauth.py` |
| 設定範本 | `config/router.example.yaml` |
| 本機啟動 | `scripts/run-local.ps1` |

---

## 9. 修訂紀錄

| 日期 | 變更 |
|------|------|
| 2026-06-22 | 初版：Portal 深色玻璃 + 雙 shell、本機 OAuth、`run-local.ps1`、故障排除 |
