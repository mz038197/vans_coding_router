# A service role connects to its own database only

On 2026-10-08 the Neon project VCRouter-db had one production branch and one role, `neondb_owner`, owning both `neondb` and `vans_signals`. The router, vans-mcp-server, pokemon-world-mcp's connection to the router, and vans-signals all use that role. The game data is the other Neon project, `pokemon_world_db`.

`vans_mcp_server_app` can connect to `vans_mcp_server` and cannot connect to `neondb`. `vans_signals_app` can connect to `vans_signals` and cannot connect to `neondb`. `vans_coding_router_app` can connect to `neondb` and cannot connect to `vans_signals` or `vans_mcp_server`. A new role name is not enough. Neon may grant CONNECT to PUBLIC, and a role made in the console may be a member of `neon_superuser`. CONNECT is revoked from PUBLIC on these databases. Each service role is not a superuser. Acceptance for the two MCP-side and signals roles is a real connection attempt to `neondb` that is refused. Acceptance for the router role is a real connection attempt to `vans_signals` and to `vans_mcp_server`, both refused. `neondb_owner` stays an admin account and is not placed in a running service.

`vans_signals_app` goes live before the MCP services switch verification and before the table move. That step does not revoke `neondb_owner`'s connect to `neondb`. pokemon-world-mcp keeps the `neondb_owner` string already in its Fly secret until signature checks replace that read, then the connection is removed. It does not get a temporary role. The `pokemon_world_db` account is unchanged. When the router secret switches to `vans_coding_router_app` is not decided here.

Signed tickets start only after the MCP services can verify them. Until that cut, student connections stay on `neondb`. The table move comes after that. Once `vans_mcp_server` is serving reads and writes and an existing connection still works, `mcp_usage` and `mcp_oauth_connections` are dropped from `neondb`.

## Considered Options

- **Reuse `neondb_owner` and rely on the app not querying the other database**: rejected. That role owns every database on the branch.
- **Treat a second role name as the boundary**: rejected. PUBLIC CONNECT or a superuser membership would still open `neondb`.
- **Move the tables before the MCP services can verify a signature**: rejected. The auth path is proven while the connections still sit on `neondb`.
- **Leave the old tables on `neondb` after the move**: rejected. The token ciphertext would remain on the router database.
- **Leave the router on `neondb_owner`**: rejected. That credential could open the database that holds student connections.
- **A temporary neondb role for pokemon-world-mcp**: rejected. The transition ends when signature checks replace that read.
- **Switch vans-signals after the MCP table move, or in the same window**: rejected. The grant pattern is proven on the signals database first, while student connections still sit on `neondb`.
