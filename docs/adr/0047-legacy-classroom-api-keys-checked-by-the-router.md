# Legacy Classroom API Keys are checked by the router

During the transition the services accept both a signed Classroom API Key and a legacy key. Both are presented with the `vcr_sk_` prefix. A legacy key is the current HMAC of the sitting and the student, `vcr_sk_` plus 64 hex characters, stored as a hash. A signed key is `vcr_sk_` plus the Ed25519 token. Each service verifies a signed key itself. A legacy key is sent to the router, which does the hash check it already does. The MCP services do not read the router's tables for it. A new redeem issues a signed key. The legacy check is removed when the last legacy key that has not reached its own expiry has expired. There is no separate cutover date.

## Considered Options

- **Reject every legacy key on the day the signed key ships**: rejected. A class in progress would have to redeem again all at once.
- **Let the MCP services keep reading `api_keys` for legacy keys**: rejected. The table coupling would remain for the whole transition.
- **A fixed cutover date**: rejected. A sitting still inside its expiry would lose the legacy key before that expiry.
- **A signed value with no `vcr_sk_` prefix**: rejected. Existing checks that require the prefix would treat a signed key as the wrong credential, and the legacy key would be the only one with the prefix.
