# A Classroom API Key expires at issuance

The expiry of a Classroom API Key is the Class Session's `expires_at` at the moment the router issues that key. A later change to the sitting's expiry does not change keys already issued. Extending the sitting leaves those keys on the old expiry; the student redeems again for a key that carries the new one, still under the two-key limit. This replaces `_apply_session_expires` rewriting every `api_keys.expires_at` for the sitting. ADR 0010 still applies once a key's own expiry has passed.

Moving the sitting's expiry earlier does not shorten a key already issued. ADR 0037 decides what ends a key before that expiry.

## Considered Options

- **Keys follow the sitting's expiry**: rejected. Other services would have to learn the sitting's current expiry from the router, and the check would depend on that shared mutable state again.
