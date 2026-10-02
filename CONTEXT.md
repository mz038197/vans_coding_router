# Vans Coding Router

OpenAI-compatible cloud provider router for Vans Coding classes. Students call the router with a classroom API key; the router forwards to teacher-configured upstream providers.

## Language

**Model ID**:
A request identity of the form `provider@upstream_model` (for example `ollama_cloud@kimi-k3:cloud`). The router uses the provider segment for routing and forwards the upstream segment to that provider.
_Avoid_: Bare model name, display name

**vcr-auto**:
The request Model ID `vcr-auto` on a Classroom API Key or a Personal API Key. It stands for the ordered Model IDs on that call's shelf — text for chat and Responses, otherwise the decision, image, speech, or speech-transcription shelf — tried from the top. The next Model ID is tried when Key Failover on the current one still ends in Extra Usage Exhaustion or Credit Exhaustion, when that provider's key pool has no free concurrency slot, or when that pool has no selectable key. A full pool does not wait out its queue while a later Model ID remains; the walk moves on immediately. When every Model ID on that shelf was passed over because its pool had no free slot, the call waits in the first Model ID's pool until that pool's queue timeout, then it is busy. That busy call has no model output. This holds for every provider. A later Model ID on the same provider shares that pool, so it adds no free slot. Model output ends the walk, including a stream that has already started, and an empty list refuses the call. The chat and Responses reply model string stays `vcr-auto`, including stream chunks. A Decision reply and an image reply keep the model string the upstream attached. When a Classroom API Key's Classroom Model Choice is Automatic Models, or that sitting has no Classroom Model Choice yet, the VS Code chat list written by the extension and by the Portal install script is a single model whose id and display name are `vcr-auto`; it does not include that sitting's Model IDs. That entry keeps image input, tool calling, and thinking switched on, fixed to the shipped text model's Copilot settings, including that model's token limits, router address, and authorization. Those settings do not follow the Model ID `vcr-auto` resolves. A Classroom API Key draws the Model IDs checked onto that shelf in the sitting's Session Chat Language Models; a Personal API Key draws that shelf in its holder's Router Model Template. When that Personal API Key shelf has at least one Model ID, its list names `vcr-auto` once, first, then those ids in document order. An empty shelf's list names nothing. Whether a Classroom API Key may name a Model ID on chat, Responses, Image Generation, Speech, Speech Transcription, or Decision is that sitting's Classroom Model Choice. A Personal API Key may name `vcr-auto` or a Model ID on that shelf, and any other id is refused.
_Avoid_: auto, Key Failover, round-robin, bare upstream name, first Model ID only, the only accepted request model, copying image, tool, or thinking switches from the resolved Model ID, rewriting a Decision or image reply model to vcr-auto, waiting out a full pool before the next Model ID, an immediate busy when every pool on the shelf is full, spillover limited to two providers, a Classroom API Key chat list that is always only vcr-auto, a live upstream list as a Personal API Key model list, forwarding a Personal API Key Model ID that is not on that shelf

**Upstream Refusal**:
A provider response that rejects the request before any model output is produced (for example Ollama Extra Usage exhausted). It is a billing or entitlement failure at the provider, not a router routing mistake.
_Avoid_: Copilot bug, no choices, model offline

**Extra Usage Exhaustion**:
An Upstream Refusal that means the upstream account cannot continue under its current Extra Usage or plan/session entitlement for that model (for example Extra Usage balance empty, or a session usage limit whose remedy is upgrade / add Extra Usage). Ollama may signal this with different HTTP statuses; it is not a generic rate-limit busy signal, not Credit Exhaustion, and not a router routing mistake.
_Avoid_: quota full (ambiguous), rate limit, UpstreamBusy, session usage limit (as a separate routing class), Credit Exhaustion

**Extra Usage Remaining**:
The remaining Extra Usage balance for one upstream key. It is a remaining-entitlement, not Extra Usage Exhaustion, Credit Exhaustion, Key Quarantine, Included Monthly Usage, or Account Credit Remaining. It is not shown on the Portal upstream-pool row.
_Avoid_: credits remaining, quota remaining, Extra Usage Exhaustion (as the displayed number), account balance, session usage, weekly usage, Included Monthly Usage, Account Credit Remaining

**Included Monthly Usage** (Portal: 月用量):
The included monthly plan usage already consumed for the Ollama account of one upstream key, as the 0–1 fraction `limits.monthly.usage` on that key's usage document. Higher means more of the monthly cap is used. It is not Extra Usage Remaining, not session usage, not Extra Usage Exhaustion, and not Account Credit Remaining.
_Avoid_: Extra Usage Remaining, weekly usage, quota remaining, session usage, credits, Extra Usage Exhaustion, Account Credit Remaining, 餘額

**Account Credit Remaining** (Portal: 餘額):
The remaining prepaid credit, in dollars, on the OpenRouter account that one upstream key draws from. Every key on that account has the same Account Credit Remaining. Zero and a negative amount are still this balance. It is not Included Monthly Usage, not Extra Usage Remaining, not that key's own spend, and not a per-key spending cap.
_Avoid_: Credit Exhaustion, limit remaining, key usage, 月用量, credits (ambiguous), 餘額無法取得

**Credit Exhaustion**:
An Upstream Refusal that means the upstream account or that key has insufficient credits (account balance or per-key spending cap). It is not Extra Usage Exhaustion, not a rate-limit busy signal, and not Account Credit Remaining.
_Avoid_: Extra Usage Exhaustion, quota full, rate limit, payment required (as a routing class), Account Credit Remaining, 餘額

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
A Class Session lets a Classroom API Key call text-to-speech when its Session Chat Language Models include at least one speech-shelf Model ID. None checked means Speech is off for that key. A Personal API Key uses its holder's Router Model Template for this call. It is not a capability checkbox, not a separate chosen id, and does not grant chat, Image Generation, Speech Transcription, or Decision. A Speech call the Classroom Model Choice accepts is forwarded; the provider's refusal is the refusal. New sessions start with the speech shelf empty. An existing sitting is not filled from the old speech switch.
_Avoid_: Voice, 語音轉寫, transcription, tts_enabled, a capability checkbox, a provider capability flag that refuses a checked Speech Model

**Speech Model**:
A Model ID the teacher checked from the speech shelf into that sitting’s Session Chat Language Models. Which of them a Speech call may name depends on that sitting's Classroom Model Choice. A sitting with no choice stored may name any of them or `vcr-auto`. Comparison uses the Model ID on that request, exactly. A text-shelf model, an Image Generation Model, a Speech Transcription Model, or a Decision Model is not a Speech Model. The student speech list is not the chat list. Under Picked Models it names the speech-shelf Model IDs in document order. Under Automatic Models, and when no choice is stored, it names only `vcr-auto`. That read still succeeds when the speech shelf is empty. None checked still means the Speech call is off.
_Avoid_: a capability checkbox, a single chosen speech field, a text-shelf model, folding speech ids into the chat list, a list read that fails because the shelf is empty

**Speech Transcription** (Portal: 語音轉寫):
A Class Session lets a Classroom API Key call File Transcription or Realtime Transcription when its Session Chat Language Models include at least one speech-transcription-shelf Model ID. None checked means Speech Transcription is off for that key. Both calls share that one shelf. A Personal API Key uses its holder's Router Model Template for this call. It is not a capability checkbox, not a separate chosen id, and does not grant chat, Speech, Image Generation, or Decision. A File Transcription or Realtime Transcription call the Classroom Model Choice accepts is forwarded; the provider's refusal is the refusal. New sessions start with that shelf empty. An existing sitting is not filled from the old speech-transcription switch.
_Avoid_: Speech, 語音, TTS, a second shelf for realtime, a capability checkbox, a provider capability flag that refuses a checked Speech Transcription Model

**Speech Transcription Model**:
A Model ID the teacher checked from the speech-transcription shelf into that sitting’s Session Chat Language Models. Which of them a File Transcription or Realtime Transcription call may name depends on that sitting's Classroom Model Choice. A sitting with no choice stored may name any of them or `vcr-auto`. Comparison uses the Model ID on that request, exactly. A text-shelf model, a Speech Model, an Image Generation Model, or a Decision Model is not a Speech Transcription Model. The student speech-transcription list is not the chat list. Under Picked Models it names the speech-transcription-shelf Model IDs in document order. Under Automatic Models, and when no choice is stored, it names only `vcr-auto`. That read still succeeds when the shelf is empty. None checked still means the Speech Transcription call is off.
_Avoid_: a file-only shelf, a realtime-only shelf, a capability checkbox, folding those ids into the chat list, a list read that fails because the shelf is empty

**Image Generation** (Portal: 生圖):
A Class Session lets a Classroom API Key call image generation when its Session Chat Language Models include at least one image-shelf Model ID. None checked means Image Generation is off for that key. A Personal API Key uses its holder's Router Model Template for this call. It is not a capability checkbox, not a separate chosen id, and does not grant chat, Speech, Speech Transcription, or Decision. An image generation call the Classroom Model Choice accepts is forwarded; the provider's refusal is the refusal. New sessions start with the image shelf empty. An existing sitting is not filled from the old image-generation switch.
_Avoid_: image_generation_enabled, a capability checkbox, 生圖開關, a provider capability flag that refuses a checked Image Generation Model

**Image Generation Model**:
A Model ID the teacher checked from the image shelf into that sitting’s Session Chat Language Models. Which of them an image generation call may name depends on that sitting's Classroom Model Choice. A sitting with no choice stored may name any of them or `vcr-auto`, and its image model list names only `vcr-auto`. Comparison uses the Model ID on that request, exactly. Under Automatic Models the image model list names only `vcr-auto`. Under Picked Models the image model list names the image-shelf Model IDs in document order. A Personal API Key's image list names `vcr-auto` once, first, then the image-shelf Model IDs in that holder's Router Model Template, in document order, when that shelf has at least one Model ID. An empty shelf's list names nothing. A text-shelf model, a Speech Model, a Speech Transcription Model, or a Decision Model is not an Image Generation Model.
_Avoid_: OpenRouter prefix as the qualification, a capability checkbox, a single chosen image field, the live image catalog as the classroom permission, a live image shelf as the Personal API Key image list, a student list of unchecked image models

**File Transcription**:
Speech-to-text over a completed audio upload, including optional streamed transcript output while that file is processed.
_Avoid_: Realtime transcription, live microphone session

**Realtime Transcription**:
Speech-to-text over a live audio stream in a persistent realtime session.
_Avoid_: File transcription, streamed file transcript

**Decision** (Portal: 決策):
A Class Session lets a Classroom API Key submit a Decision Request when its Session Chat Language Models include at least one decision-shelf Model ID. None checked means Decision is off for that key. A Personal API Key uses its holder's Router Model Template for this call. It is not a capability checkbox, not a separate chosen id, and does not grant chat, Speech, Image Generation, or Speech Transcription. New sessions start empty. Ending the sitting expires it with the Classroom API Key.
_Avoid_: Session Chat Language Model, Jev as a chat model, Copilot model, 聊天, decision_enabled, 學生用程式送決策, a single Decision Model field

**Decision Request**:
One call that brings only its own state, its own typed questions, and a Model ID. Anything else is not part of the call. The questions belong to that call, not to the Class Session. The reply is the upstream decision body for that call, including its answers and the model and usage it attaches, not assistant text. That model string is not a Model ID. It draws the same upstream keys as chat for that provider, so Key Quarantine on one blocks the other.
_Avoid_: chat completion, a session-owned rubric, a fixed router questionnaire, assistant message, a second key pool per capability, provider preferences, trace, session id, user

**Decision Refusal**:
The provider refusal of a Decision Request that was sent upstream, returned to the student as that refusal. It is not Readable Upstream Error. A router refusal before any upstream call, such as no decision-shelf Model ID checked or a Model ID that is not one of them, is not a Decision Refusal.
_Avoid_: Readable Upstream Error, chat choice, assistant message, hiding the provider refusal behind a generic router error

**Decision Model**:
A Model ID the teacher checked from the decision shelf into that sitting’s Session Chat Language Models. Which of them a Decision Request may name depends on that sitting's Classroom Model Choice. A sitting with no choice stored may name any of them or `vcr-auto`. Chat and Responses with that id are refused, and student-facing chat model lists omit every one. The student decision list is not the chat list. Under Picked Models it names the decision-shelf Model IDs in document order. Under Automatic Models, and when no choice is stored, it names only `vcr-auto`. That read still succeeds when the decision shelf is empty. None checked still means the Decision call is off. Comparison uses the Model ID on that request, exactly; the reply’s model string does not authorize a later request. A text-shelf model, an Image Generation Model, a Speech Model, a Speech Transcription Model, a file upload, or a previously stored single choice is not a Decision Model.
_Avoid_: OpenRouter prefix as the qualification, Decision Model Shelf, Decision Model Allowlist, Session Model Allowlist, capability checkbox, fixed Jev shelf, a text-shelf OpenRouter model, a single chosen field, a dropdown that picks one, a student keyed chat-picker entry, folding decision ids into the chat list, a list read that fails because the shelf is empty, treating the reply model as permission, promoting an uploaded id or an old single choice

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

**Class**:
A teacher-owned classroom grouping that outlives one sitting. Class Sessions belong to a Class; a Classroom Nickname is unique within one Class, not across Classes.
_Avoid_: Class Session, Course Catalog as the class itself

**Classroom Nickname**:
The student identity string typed at Nickname Redeem, unique within one Class. Comparison trims leading and trailing whitespace only; remaining characters must match exactly (letter case counts). Empty after trim is not a nickname. The same nickname in the same Class is the same student across sessions and cannot be renamed; a different string is a different student. It is never merged with a Google user. A teacher may disable that student; collided nicknames are not split.
_Avoid_: Guest, Guest User, login name, email as identity, 學號 as a separate identity, auto-merge with Google, 拆開撞名, folding case or inner whitespace

**Nickname Redeem**:
The exchange of an Invite Code plus a Classroom Nickname for a Classroom API Key bound to that Class Session. It is offered only in the Vans classroom extension Router Lane on VS Code, not on the Portal website and not for Cursor. Every Class Session on this router allows it, up to the Session Seat Limit; the gate is a valid Invite Code, not Portal open registration. It does not use Google or Sign-in Handoff. It does not exist on `pegasi_router`.
_Avoid_: Guest redeem, shared class-wide API key, teacher long-lived key, dev login, 連線登入 as the name of this path, Pegasi parity for this path, Portal web Nickname Redeem, Cursor Nickname Redeem

**Session Seat Limit** (Portal: 課堂座位):
A teacher-set maximum of distinct student identities that may redeem a Classroom API Key into one Class Session, by Nickname Redeem, Sign-in Handoff, or Portal Google redeem. Default 60; the teacher may change it. Occupancy is one redemption per user in that sitting. Rejoin with an already-redeemed identity does not take a new seat. A disabled student still occupies a seat. Lowering the limit does not evict. When the limit is reached, new identities are rejected on every redeem path.
_Avoid_: 暱稱座位, nickname-only cap, capping only Nickname Redeem, treating disable as freeing a seat, coupling this limit to open_registration

**Sign-in Handoff**:
A short-lived, single-use proof issued after Google login for the classroom extension. Delivered via `vscode://` / `cursor://` deep link or a one-time paste code. It authorizes one Invite Code redeem only; it is not a long-lived Portal session and must never carry a Classroom API Key. On this router it is a secondary Google fallback in the VS Code extension, not the default student path.
_Avoid_: session cookie as extension auth, API key in URI, reusable bearer for Portal admin APIs, requiring handoff for Nickname Redeem, a primary Google button beside Nickname Redeem

**Portal Session**:
A browser login state established after verified Google authentication, authorizing one user's Portal and lobby access until expiry or revocation. One user may hold multiple Portal Sessions; it is distinct from a Class Session and Sign-in Handoff.
_Avoid_: session cookie, login cookie, Class Session, Sign-in Handoff

**Invite Code**:
A teacher-issued class-session code redeemed for a Classroom API Key (`vcr_sk_…`). In the Vans VS Code extension the default redeem is Nickname Redeem; Google users may still redeem with Sign-in Handoff (extension, secondary) or a Portal session (website). Portal web redeem stays Google-only.
_Avoid_: handoff token, Google OAuth code, Classroom Nickname

**Personal API Key** (Portal: 個人 API Key):
A long-lived key held by one teacher or admin and bound to no Class Session. It has no Classroom Model Choice. A call may name `vcr-auto` or a Model ID on that call's shelf in the holder's Router Model Template. Any other id is refused. An empty shelf refuses that call. When that shelf has at least one Model ID, its list names `vcr-auto` once, first, then those ids in document order. An empty shelf's list names nothing. It is not a Classroom API Key.
_Avoid_: admin key, 老師個人金鑰, teacher long-lived key, dev key, upstream key, a provider capability list as its speech permission, forwarding a model id that is not on that shelf, an empty shelf still accepting the call

**Class Session**:
A teacher-managed classroom instance under a Class: invite lifecycle, Session Seat Limit, Session Chat Language Models, Classroom Model Choice, capability switches, and the optional Course Catalog for that sitting. Decision, Speech, Image Generation, and Speech Transcription are carried by the shelf Model IDs inside Session Chat Language Models. Prompt logging stays a capability switch. It is not the student project folder and not a materials CMS beyond the catalog attachment. Ending the sitting expires Classroom API Keys: students cannot read Course Catalog or keyed `GET /extension/chat-language-models`, same as they cannot call `/v1`.
_Avoid_: lesson plan, curriculum repo, student workspace

**Session Chat Language Models**:
A Copilot-shaped document owned by one Class Session, same array shape as the Router Model Template. It may hold decision-shelf, image-shelf, speech-shelf, and speech-transcription-shelf Model IDs checked the same way as text-shelf models. A Model ID belongs to at most one shelf in that sitting. Checking it onto a shelf removes it from every other shelf. It stays on that shelf until the teacher unchecks it. An id already on the text shelf stays there until the teacher checks it onto another shelf. A file upload arrives on the text shelf and does not check those shelves. Student-facing chat listings omit every decision-shelf, image-shelf, speech-shelf, and speech-transcription-shelf id in the document.
_Avoid_: live Template file as the student list, a second model-list GET, Course Catalog YAML, Decision Model Shelf, reclassifying a checked id from a later upstream list

**Upstream Model Catalog**:
The live model lists teachers check into Session Chat Language Models. OpenRouter filters of that one list are the text shelf, the decision shelf, the image shelf, the speech shelf, and the speech-transcription shelf. Audio output, video, embeddings, rerank, and an unfiltered mix are not shelves. A provider whose upstream list has no kind split offers All Models in place of a per-shelf list. A per-model capability tag is not that split. Same upstream on two providers is two rows. It is not the student keyed GET and is not stored in Course Catalog YAML. An image generation call does not consult this catalog.
_Avoid_: hardcoded two-vendor picker, a separate image-model catalog, audio output as the speech shelf, video, embeddings, rerank, an unfiltered mix as a shelf, a per-shelf list for a provider with no kind split, Ollama capability tags as shelves, treating a fetch failure as an empty document, Decision Model Shelf, one OpenRouter shelf that mixes text and decision models, a fixed Jev shelf

**All Models** (Portal: 全部):
The catalog filter for a provider whose upstream model list has no kind split: every model on that list, and not itself a shelf. A check from it places that Model ID on exactly one of the text shelf, the speech shelf, or the speech-transcription shelf, named by the teacher for that check.
_Avoid_: a shelf, 全部 as a permission, auto-assigning the whole list to the text shelf, image shelf, decision shelf

**Session Model Allowlist**:
The text-shelf Model IDs inside that session’s Session Chat Language Models. Decision-shelf, image-shelf, speech-shelf, and speech-transcription-shelf ids in the same document are not on it. It is the chat allowlist only, not a second chat list beside that document.
_Avoid_: a second chat-model id list, Decision Model Allowlist, counting a Decision Model as a chat id, unset-means-no-filter after the sitting has a document, stuffing the allowlist into Course Catalog YAML

**Classroom Model Choice** (Portal: 模型選擇):
One Class Session setting for chat, Responses, Image Generation, Speech, Speech Transcription, and Decision together. The two choices are Picked Models and Automatic Models. A sitting with no choice stored keeps today's mixed rule on each of those calls: `vcr-auto` and a Model ID checked onto that call's shelf are both accepted, and the student chat, image, speech, speech-transcription, and decision lists name only `vcr-auto`. A new Class Session starts as Automatic Models. Once the teacher sets a choice, the sitting stays on one of the two, and the next call uses it. A Personal API Key has no Classroom Model Choice.
_Avoid_: Chat Model Choice, 聊天模型, allow list mode, a Class-wide switch, a separate choice per shelf, a third choice the teacher can select, returning a sitting to the mixed rule

**Picked Models** (Portal: 學生自選):
The Classroom Model Choice where a call must name a Model ID checked onto that call's shelf. `vcr-auto` is refused. The student chat list is that sitting's Session Model Allowlist, in document order. The student image, speech, speech-transcription, and decision lists name that shelf's Model IDs, in document order. Decision-shelf, speech-shelf, and speech-transcription-shelf ids stay off the chat list.
_Avoid_: Picked Chat Models, a second stored allowlist, listing decision-shelf ids on the chat list, accepting `vcr-auto` beside the picked models

**Automatic Models** (Portal: 自動):
The Classroom Model Choice where chat, Responses, Image Generation, Speech, Speech Transcription, and Decision accept only `vcr-auto`. A request that names a Model ID is refused. The student chat, image, speech, speech-transcription, and decision lists name only `vcr-auto`.
_Avoid_: Automatic Chat, a list that hides Model IDs while still accepting them, Key Failover

**Router Model Template**:
The ordered shelf document owned by one teacher, checked from the Upstream Model Catalog the same way as Session Chat Language Models, including shelf and order. Save forces the VCRouter Stencil. That teacher's Personal API Key uses it as its vcr-auto candidate list and as the chat, image, speech, speech-transcription, and decision lists for that key. A new teacher starts from the shipped text-shelf starter. A new Class Session copies the class owner's template once at create into Session Chat Language Models; later edits to the template do not change a sitting that already has its own document. It is not a site-wide file and not the student keyed list. There is no model-list read without a teacher: Portal reads the logged-in teacher's template.
_Avoid_: one shared template for every teacher, an empty template for a new teacher, rewriting an existing sitting when the template changes, a second curated catalog, picking a whole upstream by provider name only, treating the template as the student keyed GET, a live upstream model list as that key's chat or image list, a model list with no teacher

**VCRouter Stencil**:
The locked classroom provider identity and routing fields for Session Chat Language Models: `VCRouter` / `customendpoint` / `responses` / router url / `Authorization: Bearer ${apiKey}`. Teacher save and upload force these fields; display name, thinking, and token limits may differ.
_Avoid_: letting upload keep a foreign provider, teacher-edited url or headers

**Portal Copy**:
Teacher- and student-visible Portal UI wording uses Traditional Chinese characters only.
_Avoid_: Simplified glyphs in Portal copy (e.g. 校验／注册／保存), mixed zh-CN/zh-TW Portal strings

**Course Catalog**:
The curated list of Install Actions and Lesson Snippets attached to one Class Session, stored as YAML (same shape as `classroom-installs.yaml`). Top-level `actions` is required; top-level `snippets` is optional (`[]` or omitted means none). Invalid `snippets` rejects the whole catalog on save. Save-time normalize must round-trip `snippets` (must not dump only `actions`) and dump multiline Lesson Snippet bodies as block scalars. Teachers open a Catalog modal from the session row in Portal and edit Install Actions and Lesson Snippets as structured fields; YAML is import/export only (optional `.yaml`/`.yml` upload into the draft, template download, and download of the current draft), not the primary edit surface. New sessions start with an empty catalog (`actions: []`); invalid YAML is rejected on save. Students fetch via a dedicated extension GET authorized by a live Classroom API Key (on redeem success, on extension startup when a key already exists, and on manual reload). An expired, disabled, or suspended key fails this GET, same as `/v1`. The extension keeps the fetched catalog in memory only and does not write it into the student workspace file. Same concept as in the classroom-one-click-install context. **Parity requirement:** Install Action catalog API remains shared with `pegasi_router`. Lesson Snippet save/normalize ships here first; Pegasi parity is deferred (Pegasi save still drops `snippets`). Nickname Redeem is a Vans-only exception and is not part of that shared Router contract.
_Avoid_: install-vscode-models script, BYOK model list, Session Model Allowlist stored in YAML, lobby workspace on the server, per-action file-hosting CDN as catalog storage, first-class file-asset install API in this router, draft-invalid catalogs that break every student's Course Lane, bundling catalog only inside redeem with no reload GET, requiring the extension to persist catalog into `classroom-installs.yaml`, inline expandable catalog row as the primary edit surface, editable YAML textarea as the primary Catalog editor, dumping only `actions` and dropping `snippets`

**Install Action**:
A Course Catalog item that names an extension-run install command. Its kind is skill, package, or mcp. It is not a Lesson Snippet and not a file hosted by this router.
_Avoid_: install script, package list, MCP config blob

**Lesson Snippet**:
A piece of lesson program text attached to a Course Catalog, for the student to paste into their workspace. An optional paste hint is a suggested filename. It is not an Install Action and not a file in the student workspace.
_Avoid_: code block, template, install-list code, snippet 區塊

**Client Setup Card**:
The Portal surface shown after a successful Google-session Invite Code redeem. It presents the Classroom API Key and Router Base URL a student needs to configure a client, plus class-session context for confirmation. Nickname Redeem does not show this card; the extension Copy Classroom API Key is the copy path for that flow.
_Avoid_: redeem result dump, key display blob, redemption receipt, Client Setup Card after Nickname Redeem

**WebMCP**:
The browser-side agent interface of the Vans Portal. It exposes domain-intent tools that act on behalf of the currently authenticated Portal user and reuse the same Portal authorization as human Portal actions. It is a Presentation interface, not a provider-routing feature and not a remote MCP server.
_Avoid_: DOM automation, browser scraping API, provider MCP, Remote MCP, a second authorization system

**Portal Working Context**:
The Class and optional Class Session currently selected by the Portal UI, used as the default target when a WebMCP request omits an explicit target. It is interaction context only and never grants authorization; an authorized WebMCP action may explicitly target another Class Session.
_Avoid_: authorization scope, Agent identity, WebMCP-owned session state, permission boundary

**Agent Capability**:
A canonical domain-intent operation exposed to an agent, such as listing Class Sessions, creating a Class Session, updating session capabilities, reading usage, or releasing Key Quarantine. The same domain intent should keep the same capability vocabulary across WebMCP and any future Remote MCP adapter even when transport and authentication differ.
_Avoid_: HTTP endpoint, UI click, DOM action, transport-specific tool name

**Agent Action Audit**:
A backend record of a successful agent-initiated domain mutation, including the acting Portal user, action, target, arguments or relevant change data, invocation channel, and time. Client-supplied invocation metadata may describe the channel but never grants additional authorization.
_Avoid_: browser console log, frontend-only audit, authorization token, trusting an invocation header for permissions

**Prompt Log** (Portal: 對話紀錄):
One stored conversation from a student router call for a Class. The stored model is the Model ID that produced the output, not `vcr-auto`. A walk that produced no output does not add another Prompt Log. The teacher of that Class can read it after the Class has ended, until it reaches Archive Age, unless it has already been archived. It is not authorization.
_Avoid_: removing it because the Class ended, treating a Prompt Log as user authorization, storing the string vcr-auto as the model

**Archive Age** (Portal: 歸檔天數):
How old a Prompt Log must be, counting from when it was created, before it is archived. Ending a Class is not Archive Age.
_Avoid_: class end, session end, Delete Age

**Delete Age** (Portal: 刪除天數):
How old a Prompt Log must be, counting from when it was created, before its conversation is gone. It is longer than Archive Age.
_Avoid_: Archive Age, days since the log was archived

**Prompt Log Archive** (Portal: 封存):
A Prompt Log that has been archived. New archives happen only at Archive Age. It does not return to the teacher list, even when it is younger than Archive Age. Its conversation still exists until Delete Age, and the teacher conversation list does not include it.
_Avoid_: ended-class cleanup, a second teacher history, restoring an archived log

**Page Content Is Data**:
The rule that Portal-visible or tool-returned content may inform an agent but cannot by itself authorize or initiate a state-changing action. WebMCP writes require explicit user intent and remain subject to normal Portal authorization.
_Avoid_: treating Prompt Logs, Course Catalog text, model output, or page copy as user authorization

**Remote MCP**:
A possible future non-browser MCP adapter that may expose the same Agent Capability vocabulary as WebMCP but has its own transport and authentication boundary. Its authentication design is intentionally outside the WebMCP v1 scope and must not depend on Portal cookies.
_Avoid_: WebMCP, Portal Session transport, browser cookie MCP, assuming Remote MCP authentication is already decided
