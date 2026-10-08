# A Classroom API Key is signed with Ed25519

The router signs a Classroom API Key with Ed25519. The private key stays on the router. The signed value is still presented with the `vcr_sk_` prefix. The router publishes the public keys at `https://ai.vanscoding.com/.well-known/jwks.json`. That document is public. The key names which public key signed it. During a rotation the previous public key stays published until every key signed with it is past its own expiry. It is not kept for an extra fixed period.

## Considered Options

- **RS256**: rejected. The signed key is much longer, and the extension stores that string in the editor.
- **One public key baked into each service's environment**: rejected. A rotation would have to change the router and both MCP services together, and keys already issued would fail at the cut.
- **Drop the previous public key after a fixed extra period, such as 7 days**: rejected. A key's expiry is already fixed at issuance, so the extra period only keeps a public key that no remaining key can use.
- **Drop the previous public key as soon as the new one is published**: rejected. Keys already issued would fail at the rotation.
