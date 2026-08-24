# Vans Coding Router

OpenAI-compatible cloud provider router for Vans Coding classes. Students call the router with a classroom API key; the router forwards to teacher-configured upstream providers.

## Language

**Model ID**:
A request identity of the form `provider@upstream_model` (for example `ollama_cloud@kimi-k3:cloud`). The router uses the provider segment for routing and forwards the upstream segment to that provider.
_Avoid_: Bare model name, display name

**Upstream Refusal**:
A provider response that rejects the request before any model output is produced (for example Ollama Extra Usage exhausted). It is a billing or entitlement failure at the provider, not a router routing mistake.
_Avoid_: Copilot bug, no choices, model offline

**Extra Usage Exhaustion**:
An Upstream Refusal that means the upstream account cannot continue under its current Extra Usage or plan/session entitlement for that model (for example Extra Usage balance empty, or a session usage limit whose remedy is upgrade / add Extra Usage). Ollama may signal this with different HTTP statuses; it is not a generic rate-limit busy signal, not Credit Exhaustion, and not a router routing mistake.
_Avoid_: quota full (ambiguous), rate limit, UpstreamBusy, session usage limit (as a separate routing class), Credit Exhaustion

**Credit Exhaustion**:
An Upstream Refusal that means the upstream account or that key has insufficient credits (account balance or per-key spending cap). It is not Extra Usage Exhaustion and not a rate-limit busy signal.
_Avoid_: Extra Usage Exhaustion, quota full, rate limit, payment required (as a routing class)

**Key Failover**:
On Extra Usage Exhaustion or Credit Exhaustion, trying the same student request against another key in that provider's key pool before returning to the client. The student still uses one Model ID; key choice stays inside the router.
_Avoid_: ollama2, provider switch, model fallback

**Key Quarantine**:
A temporary state where a key that returned Extra Usage Exhaustion or Credit Exhaustion is not selected for new requests until the quarantine ends or a teacher clears it in Portal. It does not delete the key from configuration.
_Avoid_: permanent disable, remove key, circuit breaker (generic)

**Quarantine Release**:
A teacher action in Portal that ends Key Quarantine for a key early so it can be selected again.
_Avoid_: delete key, reset pool, restart router

**Readable Upstream Error**:
The provider's refusal text surfaced to the client (chat choices content or Responses `output_text`) so the user can act on it.
_Avoid_: Generic "Upstream provider error", "Response contained no choices"

**Responses Reasoning Projection**:
A router rewrite of Responses API thinking so the student client always sees OpenAI reasoning summaries, even when the upstream placed that thinking in raw reasoning text. It does not change Model ID, provider, or whether the model thinks.
_Avoid_: include_reasoning, thinking toggle, OpenRouter-specific hack, client-side parser

**Speech** (Portal: 語音):
A class-session permission for text-to-speech. It does not grant speech-to-text.
_Avoid_: Voice, 語音轉寫, transcription

**Speech Transcription** (Portal: 語音轉寫):
A class-session permission for speech-to-text, covering both file transcription and realtime transcription. New sessions leave this off by default.
_Avoid_: Speech, 語音, TTS

**File Transcription**:
Speech-to-text over a completed audio upload, including optional streamed transcript output while that file is processed.
_Avoid_: Realtime transcription, live microphone session

**Realtime Transcription**:
Speech-to-text over a live audio stream in a persistent realtime session.
_Avoid_: File transcription, streamed file transcript

**Theme**:
A named Portal visual identity that changes colors and material treatment only. It does not change branding assets or page structure. The two Themes are Dark Theme and Light Theme. One Theme applies across Portal login, the signed-in Portal, and lobby host. The user's Theme choice is remembered on that browser. When no choice is stored, Light Theme is the default.
_Avoid_: Mode, skin, style, dark mode

**Dark Theme** (`dark`):
The original Vans Portal visual identity: dark glass surfaces with indigo accent.
_Avoid_: vans theme, indigo theme

**Light Theme** (`light`):
The school Portal visual identity aligned with pegasi_router: light surfaces with teal accent.
_Avoid_: school theme, pegasi theme, teal theme

**Brand Logo**:
The fixed Vans character image mark shown in Portal navigation chrome. It does not change with Theme. Navigation presents it on a Theme-aware light badge plate; the image asset itself stays a transparent character cutout.
_Avoid_: Icon, favicon, nav icon, school logo

**Login Network**:
The decorative animated atmosphere on the Portal login hero only. It is not navigation or content. It does not appear on the signed-in Portal or lobby host. Neural Grid (static background dots) is a separate surface treatment.
_Avoid_: Neural Grid, particle background, login animation, constellation, Shader Lines

**Sign-in Handoff**:
A short-lived, single-use proof issued after Google login for the classroom extension. Delivered via `vscode://` / `cursor://` deep link or a one-time paste code. It authorizes one Invite Code redeem only; it is not a long-lived Portal session and must never carry a Classroom API Key.
_Avoid_: session cookie as extension auth, API key in URI, reusable bearer for Portal admin APIs

**Invite Code**:
A teacher-issued class-session code a signed-in student redeems for a Classroom API Key (`vcr_sk_…`).
_Avoid_: handoff token, Google OAuth code

**Class Session**:
A teacher-managed classroom instance under a Class: invite lifecycle, capability switches, and the optional Course Catalog for that sitting. It is not the student project folder and not a materials CMS beyond the catalog attachment. After the sitting ends, the last saved Course Catalog remains readable for students who still hold a key for that session.
_Avoid_: lesson plan, curriculum repo, student workspace

**Portal Copy**:
Teacher- and student-visible Portal UI wording uses Traditional Chinese characters only.
_Avoid_: Simplified glyphs in Portal copy (e.g. 校验／注册／保存), mixed zh-CN/zh-TW Portal strings

**Course Catalog**:
The curated list of Install Actions and Lesson Snippets attached to one Class Session, stored as YAML (same shape as `classroom-installs.yaml`). Top-level `actions` is required; top-level `snippets` is optional (`[]` or omitted means none). Invalid `snippets` rejects the whole catalog on save. Save-time normalize must round-trip `snippets` (must not dump only `actions`) and dump multiline Lesson Snippet bodies as block scalars. Teachers open a Catalog modal from the session row in Portal and edit Install Actions and Lesson Snippets as structured fields; YAML is import/export only (optional `.yaml`/`.yml` upload into the draft, template download, and download of the current draft), not the primary edit surface. New sessions start with an empty catalog (`actions: []`); invalid YAML is rejected on save. Students fetch via a dedicated extension GET authorized by Classroom API Key (on redeem success, on extension startup when a key already exists, and on manual reload), including after the session has ended (last saved version). The extension keeps the fetched catalog in memory only and does not write it into the student workspace file. Same concept as in the classroom-one-click-install context. **Parity requirement:** Install Action catalog API remains shared with `pegasi_router`. Lesson Snippet save/normalize ships here first; Pegasi parity is deferred (Pegasi save still drops `snippets`).
_Avoid_: install-vscode-models script, BYOK model list, lobby workspace on the server, per-action file-hosting CDN as catalog storage, first-class file-asset install API in this router, draft-invalid catalogs that break every student's Course Lane, bundling catalog only inside redeem with no reload GET, requiring the extension to persist catalog into `classroom-installs.yaml`, inline expandable catalog row as the primary edit surface, editable YAML textarea as the primary Catalog editor, dumping only `actions` and dropping `snippets`

**Install Action**:
A Course Catalog item that names an extension-run install command. Its kind is skill, package, or mcp. It is not a Lesson Snippet and not a file hosted by this router.
_Avoid_: install script, package list, MCP config blob

**Lesson Snippet**:
A piece of lesson program text attached to a Course Catalog, for the student to paste into their workspace. An optional paste hint is a suggested filename. It is not an Install Action and not a file in the student workspace.
_Avoid_: code block, template, install-list code, snippet 區塊

**Client Setup Card**:
The Portal surface shown after a successful Invite Code redeem. It presents the Classroom API Key and Router Base URL a student needs to configure a client, plus class-session context for confirmation.
_Avoid_: redeem result dump, key display blob, redemption receipt
