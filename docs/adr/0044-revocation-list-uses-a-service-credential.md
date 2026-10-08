# The Revocation List is fetched with one service credential

vans-mcp-server and pokemon-world-mcp share one Revocation List Credential to fetch the list and to ask the router to check a legacy Classroom API Key. The legacy key is the request body, not the secret. A Classroom API Key cannot make either call, and neither can a Personal API Key. The public signing keys stay public. The list does not.

## Considered Options

- **Publish the list like the public keys**: rejected. The list says which students and sittings are refused.
- **Let the MCP services read the database**: rejected. That is the coupling this design removes.
- **A second service credential used only for the legacy check**: rejected. The transition does not need another secret.
- **A public legacy check**: rejected. Anyone who guessed a legacy key could ask the router whether it is still valid.
