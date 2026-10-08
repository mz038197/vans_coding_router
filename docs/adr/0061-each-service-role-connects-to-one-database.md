# A service role connects to its own database only

On 2026-10-08 the Neon project VCRouter-db had one production branch and one role, `neondb_owner`, owning both `neondb` and `vans_signals`. The router, vans-mcp-server, pokemon-world-mcp's connection to the router, and vans-signals all use that role. The game data is the other Neon project, `pokemon_world_db`.

vans-mcp-server gets a role that can connect to `vans_mcp_server` and cannot connect to `neondb`. vans-signals gets a role that can connect to `vans_signals` and cannot connect to `neondb`. A new role name is not enough. Neon may grant CONNECT to PUBLIC, and a role made in the console may be a member of `neon_superuser`. CONNECT is revoked from PUBLIC on these databases, and each service role is granted CONNECT only on its own database. The service role is not a superuser. Acceptance is a real connection attempt to `neondb` with that role, and the attempt is refused.

The role names, whether the router also leaves `neondb_owner`, which account pokemon-world-mcp uses while it still opens `neondb`, and where the vans-signals switch sits in the order, are not decided here.

Signed tickets start only after the MCP services can verify them. Until that cut, student connections stay on `neondb`. The table move comes after that. Once `vans_mcp_server` is serving reads and writes and an existing connection still works, `mcp_usage` and `mcp_oauth_connections` are dropped from `neondb`.

## Considered Options

- **Reuse `neondb_owner` and rely on the app not querying the other database**: rejected. That role owns every database on the branch.
- **Treat a second role name as the boundary**: rejected. PUBLIC CONNECT or a superuser membership would still open `neondb`.
- **Move the tables before the MCP services can verify a signature**: rejected. The auth path is proven while the connections still sit on `neondb`.
- **Leave the old tables on `neondb` after the move**: rejected. The token ciphertext would remain on the router database.
