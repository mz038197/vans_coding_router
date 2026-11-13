"""Server-rendered Authorization Page (ADR 0094), in the Portal's monochrome tokens (ADR 0045).

Every value from a request is HTML-escaped. No page carries a key.
"""

from __future__ import annotations

from html import escape

from src.application.use_cases.oauth_use_case import AuthorizationRequest

_STYLE = """
:root {
  --font-ui: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang TC", "Noto Sans TC", "Microsoft JhengHei", sans-serif;
  --font-wordmark: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
  --radius: 6px;
  --bg-base: #ffffff; --bg-card: #ffffff; --bg-muted: #f3f4f6;
  --border: #e5e7eb; --border-strong: #d1d5db;
  --text-primary: #111827; --text-muted: #4b5563;
  --accent: #111111; --accent-fg: #ffffff; --accent-hover: #2b2b2b;
  --focus-ring: rgba(17, 24, 39, 0.3);
  --error-fg: #b91c1c; --error-bg: rgba(220, 38, 38, 0.08); --error-border: rgba(220, 38, 38, 0.3);
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg-base: #0a0a0a; --bg-card: #0a0a0a; --bg-muted: #18181b;
    --border: #27272a; --border-strong: #3f3f46;
    --text-primary: #fafafa; --text-muted: #a1a1aa;
    --accent: #fafafa; --accent-fg: #0a0a0a; --accent-hover: #e4e4e7;
    --focus-ring: rgba(250, 250, 250, 0.35);
    --error-fg: #fca5a5; --error-bg: rgba(248, 113, 113, 0.1); --error-border: rgba(248, 113, 113, 0.35);
    color-scheme: dark;
  }
}
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
  padding: 24px 16px; background: var(--bg-base); color: var(--text-primary);
  font-family: var(--font-ui); line-height: 1.5; }
main { width: 100%; max-width: 400px; background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 12px; padding: 32px 28px; }
.wordmark { font-family: var(--font-wordmark); font-weight: 700; letter-spacing: -0.01em; font-size: 15px; margin: 0 0 24px; }
h1 { font-size: 22px; font-weight: 650; margin: 0 0 8px; }
p { margin: 0 0 16px; }
.muted { color: var(--text-muted); font-size: 14px; }
label { display: block; font-size: 14px; font-weight: 550; margin: 16px 0 6px; }
input[type=text] { width: 100%; height: 40px; padding: 0 12px; font: inherit; font-size: 16px;
  color: var(--text-primary); background: var(--bg-card); border: 1px solid var(--border-strong); border-radius: var(--radius); }
input[type=text]:focus-visible, button:focus-visible, a:focus-visible { outline: 3px solid var(--focus-ring); outline-offset: 1px; }
.code { font-family: "Fira Code", ui-monospace, "SF Mono", Consolas, monospace; text-transform: uppercase; letter-spacing: 0.08em; }
button, .button { display: flex; align-items: center; justify-content: center; width: 100%; height: 42px; margin-top: 20px;
  font: inherit; font-size: 15px; font-weight: 600; border-radius: var(--radius); cursor: pointer; text-decoration: none; }
.primary { background: var(--accent); color: var(--accent-fg); border: 1px solid var(--accent); }
.primary:hover { background: var(--accent-hover); }
.secondary { background: transparent; color: var(--text-primary); border: 1px solid var(--border-strong); }
.secondary:hover { background: var(--bg-muted); }
.divider { display: flex; align-items: center; gap: 12px; margin: 20px 0 0; color: var(--text-muted); font-size: 13px; }
.divider::before, .divider::after { content: ""; flex: 1; border-top: 1px solid var(--border); }
.divider + button { margin-top: 12px; }
.error { color: var(--error-fg); background: var(--error-bg); border: 1px solid var(--error-border);
  border-radius: var(--radius); padding: 10px 12px; font-size: 14px; margin: 0 0 16px; }
.hint { color: var(--text-muted); font-size: 13px; margin: 8px 0 0; }
"""


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="referrer" content="same-origin" />
  <title>{escape(title)} · VCRouter</title>
  <style>{_STYLE}</style>
</head>
<body>
  <main>
    <p class="wordmark">VCRouter</p>
{body}
  </main>
</body>
</html>
"""


def _error(message: str | None) -> str:
    if not message:
        return ""
    return f'    <p class="error" role="alert">{escape(message)}</p>\n'


def _hidden(request: AuthorizationRequest) -> str:
    return "\n".join(
        f'      <input type="hidden" name="{escape(name)}" value="{escape(value)}" />'
        for name, value in request.parameters().items()
    )


def classroom_page(
    request: AuthorizationRequest,
    *,
    error: str | None = None,
    invite_code: str = "",
    nickname: str = "",
) -> str:
    client = escape(request.client_name)
    body = f"""    <h1>加入課堂</h1>
    <p class="muted">「{client}」要取得你在這堂課的 Classroom API Key。請輸入老師給的邀請碼，再用暱稱加入。</p>
{_error(error)}    <form method="post" action="/oauth/authorize">
{_hidden(request)}
      <label for="invite_code">邀請碼</label>
      <input id="invite_code" class="code" type="text" name="invite_code" value="{escape(invite_code)}"
        autocomplete="off" autocapitalize="characters" spellcheck="false" required />
      <label for="nickname">暱稱</label>
      <input id="nickname" type="text" name="nickname" value="{escape(nickname)}" maxlength="64"
        autocomplete="nickname" spellcheck="false" />
      <p class="hint">同一堂課用同一個暱稱，就是同一位學生。大小寫不同就是不同的暱稱。</p>
      <button class="primary" type="submit" name="method" value="nickname">以暱稱加入</button>
      <div class="divider">或</div>
      <button class="secondary" type="submit" name="method" value="google" formnovalidate>改用 Google 帳號加入</button>
      <p class="hint">暱稱和 Google 帳號是兩位不同的學生，請每次用同一種方式加入。</p>
    </form>"""
    return _page("加入課堂", body)


def teacher_page(request: AuthorizationRequest, *, error: str | None = None) -> str:
    client = escape(request.client_name)
    body = f"""    <h1>教師登入</h1>
    <p class="muted">「{client}」要確認你是 VCRouter 的教師。只有教師或管理員帳號可以登入。</p>
{_error(error)}    <form method="post" action="/oauth/authorize">
{_hidden(request)}
      <button class="primary" type="submit" name="method" value="google">以 Google 帳號登入</button>
    </form>"""
    return _page("教師登入", body)


def teacher_only_page(request: AuthorizationRequest, display_name: str, back_url: str) -> str:
    who = f"「{escape(display_name)}」" if display_name else "這個帳號"
    body = f"""    <h1>此登入僅限教師</h1>
    <p class="error" role="alert">你登入的 Google 帳號{who}不是 VCRouter 的教師或管理員，無法登入「{escape(request.client_name)}」。</p>
    <p class="muted">若你是教師，請改用學校的教師 Google 帳號，或請管理員為你開通教師身分。</p>
    <a class="button secondary" href="{escape(back_url)}">返回「{escape(request.client_name)}」</a>"""
    return _page("此登入僅限教師", body)


def refusal_page(message: str) -> str:
    body = f"""    <h1>無法完成授權</h1>
    <p class="error" role="alert">{escape(message)}</p>
    <p class="muted">請回到原本的應用程式重新開始；若一直看到這個畫面，請告訴老師。</p>"""
    return _page("無法完成授權", body)
