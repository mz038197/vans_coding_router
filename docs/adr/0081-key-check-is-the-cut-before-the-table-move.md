# The key check is the cut before the table move

Status: accepted. Amends ADR 0073.

The key check replaces the MCP services' reads of `neondb` before the table move and the router role switch (ADR 0073). The order is:

1. `vans_signals_app` goes live.
2. The router serves the key check and reads `VCR_SERVICE_TOKENS`.
3. vans-mcp-server uses the key check and stops reading `api_keys`.
4. pokemon-world-mcp uses the key check, and its `neondb` connection is removed.
5. vans-mcp-server's tables move to `vans_mcp_server` (ADR 0071).
6. The router switches to `vans_coding_router_app`.

road-test can use the key check any time after step 2. Each step can be undone alone. At steps 3 and 4 the MCP services start refusing a sitting that has not started, as the router already does. Teachers are told before that deploy.

## Considered Options

- **Wait for a different verification scheme before any MCP change**: rejected. The table coupling and the copied validity rules would stay until then, and the copies have already drifted from the router (no `not_started` check, `users.role` instead of the role table).
