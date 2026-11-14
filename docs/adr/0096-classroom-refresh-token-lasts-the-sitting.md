# A classroom refresh token lasts the sitting

Status: accepted. Amends ADR 0094 (which issued no refresh token for `classroom`).

MiTAC Agent Builder treats a W1 OAuth server that answers without a `refresh_token` as a failed consent ("OAuth provider did not issue refresh_token"). Its switch for providers without one (`supports_refresh`) is rejected by its own back end, so a student could never finish authorizing. The `classroom` token answer therefore also carries a `refresh_token`.

The refresh token is a signed payload naming the OAuth Client, the student and the sitting by integer id, and it expires when the sitting does. It never carries a key. At the token endpoint, `grant_type=refresh_token` with the same client's authentication returns the same Classroom API Key again, with `expires_in` up to the sitting's expiry and a refresh token. The key is checked as on the first exchange, so a sitting the teacher ended early, a disabled key or a removed student is refused with `invalid_grant`. A refresh token from another client, a forged one, or an authorization code is refused the same way. So is any refresh once the client's registration no longer allows `classroom`. `openid teacher` still gets no refresh token.

Nothing is stored: there is no rotation and no revocation list. A refresh token can do nothing its key cannot already do, and it stops working when the sitting or the key does.

## Considered Options

- **Wait for MiTAC to accept `supports_refresh: false`**: kept as the cleaner fix, but not in our hands and not certain before the 2026-12-09 class.
- **A refresh token that outlives the sitting**: rejected. It would let a student's access continue past the class, the one thing ADR 0094 sets out to prevent.
- **Stored, rotating refresh tokens**: rejected. Rotation guards against a long-lived token being replayed; this one renews only the same key for at most one sitting.

## Consequences

- A client may keep a student's refresh token for the length of a sitting; it is worth exactly the Classroom API Key it renews.
- Discovery lists `refresh_token` in `grant_types_supported`.
- A refresh token keeps the sitting's expiry from when it was issued. If a teacher extends the sitting, the client gets the later expiry from its next refresh before the old one runs out, or authorizes again.
