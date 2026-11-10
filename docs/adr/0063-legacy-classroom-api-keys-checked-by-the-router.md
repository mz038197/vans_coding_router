# Classroom API Keys are checked by the router

Status: accepted. Amended by ADR 0077 (the key check at /internal/key-check).

A Classroom API Key is `vcr_sk_` plus the HMAC of the sitting and the student, 64 hex characters, and the router stores only its hash. Only the router can verify it. A Partner Service that receives one sends it to the router with its Service Credential, and the key itself is the request body. The router does the hash check it already does for `/v1`. When it accepts the key, it returns that student's integer id and does not return an email, a name, or the key id. When it refuses, it returns only the notice. The Partner Services do not read the router's tables for it.

## Considered Options

- **Let the MCP services keep reading `api_keys`**: rejected. Every service would stay coupled to the router's tables.
- **An acceptance that carries no student id**: rejected. The MCP services find an existing connection or save by that integer, and they cannot read `users`.
- **An acceptance that also returns the email, the name, or the key id**: rejected. A Partner Service needs identity, not personal data or the router's row ids.
