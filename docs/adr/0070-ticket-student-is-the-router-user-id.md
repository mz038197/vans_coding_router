# The student on a Classroom API Key is the router's integer user id

The student a Classroom API Key names is that student's `users.id`. vans-mcp-server stores Google and Discord connections under that same integer. Moving those rows does not rewrite it, and the service does not read `users` to find them. A second public id would rename a student who already has a connection.

## Considered Options

- **A new public student id, rewritten onto the moved rows**: rejected. Every connection would change identity, and one student would have two names.
- **A student roster copied into vans-mcp-server**: rejected. It would go stale when a new student redeems.
