# The router is the OAuth authorization server for Partner Service surfaces

Status: accepted (authorization server: `/oauth/authorize`, `/oauth/token`, discovery, JWKS, OAuth Client registry; Partner Service class lookup: `POST /internal/teacher-classes`). Amends ADR 0004 (Nickname Redeem is no longer extension-only).

MiTAC Agent Builder lets a whole class share one space, but an API tool or MCP Server there holds one setting for everyone, so a single key would make every student the same person. Both kinds of tool accept "OAuth 2.0 (user authorization)": each platform user links once and the platform keeps that user's token. The router becomes that authorization server, so club-booking-board and vans-mcp-server learn who the student is without either one running its own login.

The router serves `/oauth/authorize`, `/oauth/token`, and OpenID Connect discovery with its signing keys. Each OAuth Client is registered in router config with its redirect URIs and the scopes it may ask for. The scope of a request decides what the Authorization Page asks and what the router returns:

- **`classroom`**: the page asks for an Invite Code, then a Classroom Nickname (Nickname Redeem, the default) or Google (Portal Session redeem, secondary). Every rule of those redeems holds: Session Seat Limit, not started, nickname and Google never merged. The access token is that student's Classroom API Key for the sitting, the same key a second redeem returns, with `expires_in` up to the sitting's expiry and no refresh token (amended by ADR 0096: a refresh token that lasts the sitting). A Partner Service checks it through the Key Check as it checks any key.
- **`openid teacher`**: Google only, and only for a holder with the teacher or admin role. The router returns an ID token naming the user id and Display Name, and no key.

A Partner Service with its Service Credential may ask which Classes a user may manage, answered the way the Key Check answers a Personal API Key (`classes`). A teacher surface signs in with `openid teacher` and asks this, instead of holding the teacher's key.

The authorization code is short-lived, single-use, bound to PKCE, and is never a key. No key travels in a URL.

## Considered Options

- **A new access-token kind (`vcr_at_`) in place of the Classroom API Key**: rejected. The Key Check and every Partner Service client would change, and the key already ends with its sitting.
- **Give a teacher surface the teacher's Personal API Key**: rejected. A long-lived key would leave the router and sit in another service's store.
- **Each Partner Service runs its own authorization**: rejected. Nickname Redeem would be copied into every service.
- **Let the client alone decide which key it gets**: rejected in favor of scopes, which OAuth defines for this; the client registration only limits which scopes it may ask for.
- **Per-student Agent Builder spaces, a booking claim code, or one class-wide MCP account**: rejected once the platform showed per-user OAuth for both API tools and MCP Servers.

## Consequences

- Agent Builder stores each student's Classroom API Key for the sitting. A student who knows the Invite Code and a classmate's nickname can obtain that classmate's key here, exactly as in the extension.
- The Agent Builder callback must be a URL students can reach, not the `localhost` the platform shows by default; that is the platform operator's setting.
- Glossary: `CONTEXT.md` (Authorization Page, OAuth Client, Nickname Redeem, Invite Code).
