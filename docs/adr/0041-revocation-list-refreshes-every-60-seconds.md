# The Revocation List refreshes every 60 seconds

vans-mcp-server and pokemon-world-mcp refresh their Revocation List copy from the router every 60 seconds. The router keeps the published list in memory and rebuilds it only when the refusals change. A caller that already has that list gets an unchanged response. A refusal still applies at once on the router's own calls.

## Considered Options

- **Every 5 minutes**: rejected. A closed sitting or a key ended by a newer one would keep working on MCP for too long.
- **Only at startup**: rejected. The copy would not learn a later refusal.
- **Return the full list on every refresh**: rejected. The list usually has not changed, and the database is read only when a refusal changes.
