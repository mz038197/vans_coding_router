# Vans Coding Router

OpenAI-compatible cloud provider router for Vans Coding classes. Students call the router with a classroom API key; the router forwards to teacher-configured upstream providers.

## Language

**Model ID**:
A request identity of the form `provider@upstream_model` (for example `ollama_cloud@kimi-k3:cloud`). The router uses the provider segment for routing and forwards the upstream segment to that provider.
_Avoid_: Bare model name, display name

**Upstream Refusal**:
A provider response that rejects the request before any model output is produced (for example Ollama Extra Usage exhausted). It is a billing or entitlement failure at the provider, not a router routing mistake.
_Avoid_: Copilot bug, no choices, model offline

**Readable Upstream Error**:
The provider's refusal text surfaced to the client (chat choices content or Responses `output_text`) so the user can act on it.
_Avoid_: Generic "Upstream provider error", "Response contained no choices"

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
The animated field of moving dots and connecting lines on the Portal login hero only. It is decorative atmosphere, not navigation or content. It does not appear on the signed-in Portal or lobby host. Neural Grid (static background dots) is a separate surface treatment.
_Avoid_: Neural Grid, particle background, login animation, constellation

**Sign-in Handoff**:
A short-lived, single-use proof issued after Google login for the classroom extension. Delivered via `vscode://` / `cursor://` deep link or a one-time paste code. It authorizes one Invite Code redeem only; it is not a long-lived Portal session and must never carry a Classroom API Key.
_Avoid_: session cookie as extension auth, API key in URI, reusable bearer for Portal admin APIs

**Invite Code**:
A teacher-issued class-session code a signed-in student redeems for a Classroom API Key (`vcr_sk_…`).
_Avoid_: handoff token, Google OAuth code
