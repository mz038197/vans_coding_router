# Legacy Classroom API Keys are checked by the router

During the transition the services accept both a signed Classroom API Key and a legacy key. A legacy key is the current `vcr_sk_` HMAC of the sitting and the student, stored as a hash. Each service verifies a signed key itself. A legacy key is sent to the router, which does the hash check it already does. The MCP services do not read the router's tables for it. A new redeem issues a signed key. The legacy check is removed once those keys are gone.

## Considered Options

- **Reject every legacy key on the day the signed key ships**: rejected. A class in progress would have to redeem again all at once.
- **Let the MCP services keep reading `api_keys` for legacy keys**: rejected. The table coupling would remain for the whole transition.
