# A Classroom API Key is signed with Ed25519

The router signs a Classroom API Key with Ed25519. The private key stays on the router. The router publishes the public keys as a JWKS document, and the key names which public key signed it. During a rotation the previous public key stays published so keys already issued still verify.

## Considered Options

- **RS256**: rejected. The signed key is much longer, and the extension stores that string in the editor.
- **One public key baked into each service's environment**: rejected. A rotation would have to change the router and both MCP services together, and keys already issued would fail at the cut.
