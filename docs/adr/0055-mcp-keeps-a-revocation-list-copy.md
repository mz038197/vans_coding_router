# MCP services keep a copy of the Revocation List

The router publishes a Revocation List of Classroom API Keys it refuses before expiry. vans-mcp-server and pokemon-world-mcp each keep a copy in memory and refresh it from the router. A student call to those services uses that copy and does not ask the router. The router's own `/v1/*` calls use its records, so a refusal applies there at once.

## Considered Options

- **Ask the router on every student call**: rejected. A student tool call would wait on the router for each request.
- **The router pushes each refusal**: rejected. Both services would need a live channel from the router.
