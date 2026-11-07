# The ticket uses the router's integer ids

The Class Session on a Classroom API Key is `class_sessions.id`. The Class is `classes.id`. The key's own identity is the `api_keys.id` of the row created when the key is issued. A Revocation List entry uses those same integers, and the student integer already decided. A new tool-call record stores that key id. The MCP services do not open `neondb` to interpret them.

## Considered Options

- **A separate key identity that is not `api_keys.id`**: rejected. The router already creates that row, and a second id would make the usage record a different name for the same key.
- **New public ids for the sitting, the class, and the key**: rejected. The student is already the existing integer, and the list has to match the ticket.
