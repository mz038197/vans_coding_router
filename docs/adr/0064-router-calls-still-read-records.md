# A signed Classroom API Key still reads router records on /v1

On `/v1/*` the router verifies the signature, then reads its own records for usage, quota, the sitting's model rules, and a refusal. A refusal applies there at once, not when an MCP copy next refreshes. A Personal API Key stays an opaque secret checked by hash. Usage and model rules are not placed on the key.

## Considered Options

- **Treat a valid signature as enough for `/v1/*`**: rejected. The key does not carry usage or the sitting's model rules.
