# vans-mcp-server's database sits beside neondb

vans-mcp-server's tool-call records and student connections move to a new database in the existing Neon project VCRouter-db. That is the same arrangement as `vans_signals`: one project, a different database from the router's `neondb`. The service cannot read `neondb`. pokemon-world-mcp does not use that new database, and it does not open `neondb` either. The move copies both tables, pauses writes, copies the gap, then switches the service to the new database. Students do not authorize again.

## Considered Options

- **A new Neon project**: rejected. `vans_signals` already shows a second database inside VCRouter-db.
- **pokemon-world-mcp's game database**: rejected. Game saves are a different service.
- **Fly Postgres or another host**: rejected. The classroom databases already live in this Neon project.
- **Keep sharing `neondb` and only stop the auth queries**: rejected. The service must not be able to read the router's tables.
