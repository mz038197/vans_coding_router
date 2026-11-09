# Partner Services check signed keys themselves, with or without a gateway

Status: accepted. Amends ADRs 0080 and 0082.

Each Partner Service checks a signed key itself: the signature against the public keys the router publishes, then its own copy of the Revocation List. It asks the Key Check only about a legacy key, and about a signed Personal API Key when it needs that holder's admin standing or Classes (ADR 0087). This holds even if an API gateway is later placed in front of the Partner Services. A Partner Service does not accept a caller's identity because a gateway passed it on. Today the Partner Services are vans-mcp-server, pokemon-world-mcp, and road-test. hex-island sends a teacher's key to the router's `/v1` and accepts no keys itself, so it is not one.

ADR 0082 still holds: there is no shared package. Each Partner Service keeps its own check in its own repository. The router keeps an example JWKS and an example Revocation List, and every Partner Service tests against them, so the three checks share one contract.

## Considered Options

- **Wait for the gateway, as ADR 0082 said**: rejected. Every student call would keep waiting on the router, and the decision about who checks keys would stay open.
- **The gateway checks the key and passes the identity on in a header**: rejected. Each Partner Service is reachable on its own public address, so anyone could send that header, and one broken service could speak for any user.
- **The gateway exchanges the key for a short token per service**: rejected. It needs a gateway that does not exist yet. A student's key can already carry its own signature.
