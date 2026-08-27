# Nickname Redeem is the Vans student path

Students often have no Google account or cannot finish Google login, but Classroom API Keys must stay per-student and die with the Class Session. Default student redeem on this router is Nickname Redeem: Invite Code plus a Classroom Nickname unique within a Class, from the VS Code extension only. Sign-in Handoff remains a secondary Google fallback; Portal web redeem stays Google-only; this path is not a `pegasi_router` contract.

## Considered Options

- **Shared class-wide API key**: one `vcr_sk_…` for the sitting; rejected — prompt logs, kick, and leak blast radius collapse.
- **Portal web Nickname Redeem** (with or without a Portal session): rejected — the stuck flow is the extension; website stays Google.
- **Email as identity or required field**: rejected — recreates the original blocker; student-typed email must not be `users.email` (admin role grant).
- **Session-scoped or global nickname identity**: rejected in favor of Class + Nickname, matching how Google students persist across sittings of the same Class.
- **Pegasi parity / Cursor Nickname Redeem**: rejected — Vans VS Code only; other Cursor behavior is unchanged.

## Consequences

- Identity comparison trims ends only; nicknames cannot be renamed or auto-merged with Google; teacher may disable, not split collisions.
- Each Class Session has a Session Seat Limit (default 60, teacher-changeable) counting distinct nicknames, not Google redemptions.
- `open_registration` does not gate Nickname Redeem; a valid Invite Code does.
- Glossary: `CONTEXT.md` (Class, Classroom Nickname, Nickname Redeem, Session Seat Limit).
