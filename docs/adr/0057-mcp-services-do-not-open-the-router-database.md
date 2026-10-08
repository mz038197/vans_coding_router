# MCP services do not open the router database

vans-mcp-server and pokemon-world-mcp accept a Classroom API Key from its signature and the Revocation List. A legacy key is sent to the router at `POST /internal/legacy-key`. Neither service opens this router's database. The tool-call records and the Google and Discord connections that vans-mcp-server keeps today on this database move to a database that service owns. Connections that already work must still work after the move. Where that database lives, whether the move pauses writes, and which student identifier the moved rows keep, are not decided here.

## Considered Options

- **Leave `mcp_usage` and `mcp_oauth_connections` on this database and only stop the auth reads**: rejected. Both MCP services stop opening this database altogether.
