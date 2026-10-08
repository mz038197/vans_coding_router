# MCP services do not open the router database

vans-mcp-server and pokemon-world-mcp accept a Classroom API Key from its signature and the Revocation List. A legacy key is sent to the router at `POST /internal/legacy-key`. Neither service opens this router's database. The tool-call records and the Google and Discord connections that vans-mcp-server keeps today on this database move to a database that service owns. Connections that already work must still work after the move. That database is a new one in the Neon project VCRouter-db, beside `neondb` and `vans_signals`, and it is not `neondb`. The move copies the tables, pauses writes, copies what arrived during the pause, then vans-mcp-server writes only there. The student on the ticket, and the id kept on the moved rows, is the integer `users.id`.

## Considered Options

- **Leave `mcp_usage` and `mcp_oauth_connections` on this database and only stop the auth reads**: rejected. Both MCP services stop opening this database altogether.
