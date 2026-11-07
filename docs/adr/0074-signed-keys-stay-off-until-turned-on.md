# Signed Classroom API Keys stay off until an operator turns them on

The router and both MCP services deploy from the main branch. A router deploy that can already issue a signed Classroom API Key would hand students a ticket the MCP services cannot verify yet. Issuance stays off until an operator turns it on, after both MCP services can verify a ticket. The switch is an environment setting. Its default is off.

## Considered Options

- **Issue signed keys as soon as the router deploy is live**: rejected. The MCP services would not be able to verify them yet.
