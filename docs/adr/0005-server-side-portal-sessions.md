# Portal authentication uses server-side sessions

After verified Google login, the browser receives an opaque random Portal Session token only in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie. The server stores the token hash with its user, idle and absolute expiry, and revocation state; one user may hold multiple independently revocable Portal Sessions. Requests never accept a user ID as proof of login, and the legacy `session_user_id` cookie is rejected. We chose this over a signed self-contained cookie because individual revocation, a 12-hour idle limit, a seven-day absolute limit, and immediate invalidation matter more than avoiding a database lookup.

## Consequences

- Portal Sessions use the existing PostgreSQL production database and SQLite local database; no Redis dependency is introduced.
- Tokens contain at least 32 bytes of cryptographically secure randomness. The browser receives the raw token, while the database stores only its SHA-256 hash.
- Every authenticated request checks revocation and both expiry limits. Activity updates `last_seen_at` at most once every five minutes.
- Logout revokes the current Portal Session. Users can revoke all of their Portal Sessions, and administrator suspension or high-privilege role changes revoke all Portal Sessions for the affected user.
- State-changing Portal and lobby requests require an allowed `Origin` in addition to `SameSite=Lax`; lobby WebSocket connections also validate `Origin`.
- Session storage or lookup failure fails closed. The application never falls back to a user ID cookie or skips authentication.
- Production startup fails when Google OAuth configuration is incomplete. Unverified development login requires `DEV_AUTH_ENABLED=true`, is accepted only on loopback hosts, and is never enabled merely because credentials are missing.
- Session management records creation time, last activity time, and a normalized browser description. Full client IP addresses are not retained as Portal Session metadata.
- Expired and revoked Portal Session records cannot authenticate and are deleted automatically after a 30-day audit window.
- A user may hold at most ten active Portal Sessions. Creating an eleventh revokes the least recently active one.
- Ordinary Portal logout revokes only Portal Sessions and does not affect Classroom API Keys. Administrator suspension revokes every Portal Session and permanently disables the affected user's existing API Keys; reactivation requires new keys.
- Portal provides a signed-in device list with normalized browser description, creation time, and last activity time, plus controls to revoke one device or every other device.
- A valid Portal Session is sufficient for authorized high-risk Portal actions; the application does not require a separate recent Google reauthentication step.
- Automated lobby WebSocket keepalive, ping, and pong traffic does not refresh `last_seen_at`. Only meaningful authenticated user actions count as activity; an expired Portal Session causes the authenticated lobby connection to close.
- Production uses the host-only `__Host-vcr_portal_session` cookie with `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, and no `Domain`. A non-`Secure` development cookie is allowed only for an explicitly enabled loopback HTTP environment.
- Session security events record event type, time, user, actor, and revocation reason. They never contain the raw token and do not retain full client IP addresses.
