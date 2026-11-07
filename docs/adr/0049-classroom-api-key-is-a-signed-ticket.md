# Classroom API Key is a signed ticket

A Classroom API Key is a ticket the router signs for one student and one Class Session. vans-mcp-server and pokemon-world-mcp check that issuance themselves, and they do not read the router's key table to decide it is genuine. A Personal API Key stays an opaque secret: only the router verifies its hash, and those two MCP services reject it.

## Considered Options

- **Introspection of an opaque key**: rejected. Every MCP call would depend on the router being up, and the two services would still not own the check.
- **Keep each MCP reading `api_keys`**: rejected. Validity is already implemented three times, and a router table change breaks the MCP services.
- **Sign Personal API Keys the same way**: rejected. A Personal API Key has no Class Session. It stays a router-only secret.
