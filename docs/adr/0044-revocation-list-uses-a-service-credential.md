# The Revocation List is fetched with one service credential

vans-mcp-server and pokemon-world-mcp share one Revocation List Credential to fetch the list. A Classroom API Key cannot fetch it, and neither can a Personal API Key. The public signing keys stay public. The list does not.

## Considered Options

- **Publish the list like the public keys**: rejected. The list says which students and sittings are refused.
- **Let the MCP services read the database**: rejected. That is the coupling this design removes.
