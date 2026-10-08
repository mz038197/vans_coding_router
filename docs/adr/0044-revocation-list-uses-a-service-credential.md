# The Revocation List is fetched with one service credential

vans-mcp-server and pokemon-world-mcp share one Revocation List Credential to fetch the list at `https://ai.vanscoding.com/internal/revocation-list` and to ask the router to check a legacy Classroom API Key at `POST https://ai.vanscoding.com/internal/legacy-key`. The legacy key is the request body, not the secret. The router answers that check with the same acceptance, expiry notice, or Key Refusal a signed key would get, including the same order when more than one cause applies. A Classroom API Key cannot make either call, and neither can a Personal API Key. The public signing keys stay public. The list does not.

## Considered Options

- **Publish the list like the public keys**: rejected. The list says which students and sittings are refused.
- **Let the MCP services read the database**: rejected. That is the coupling this design removes.
- **A second service credential used only for the legacy check**: rejected. The transition does not need another secret.
- **A public legacy check**: rejected. Anyone who guessed a legacy key could ask the router whether it is still valid.
- **Serve the list on the same URL as the public keys**: rejected. The list is not public.
- **Use one URL for both the list and the legacy check**: rejected. A list refresh and a check of one key are different calls.
- **Answer the legacy check with only valid or invalid**: rejected. A legacy key would then hide the cause that a signed key shows.
