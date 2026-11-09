# The operator decides when an old public signing key is removed

Status: accepted. Amends ADR 0059.

After the router's signing key is replaced, the old public key stays in the JWKS until the operator removes it. Removing it refuses every key it signed: students redeem again, and holders of a Personal API Key issue a new one, which Portal asks them to do. When the old private key has leaked, the operator removes the old public key at once.

## Considered Options

- **Keep the old public key until every key it signed has expired, as ADR 0059 said**: rejected. A Personal API Key has no expiry (ADR 0087), so that public key would never be removed, and keys forged with a leaked private key would stay valid.
- **Remove the old public key as soon as the new one is published**: rejected. Every class in progress would have to redeem at once even when nothing leaked.
