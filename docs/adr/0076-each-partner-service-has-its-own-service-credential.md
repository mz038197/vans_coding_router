# Each Partner Service has its own Service Credential

Status: accepted. Amends ADR 0060. Amended by ADR 0082.

A Partner Service is a separately deployed service registered with this router that accepts `vcr_sk_` keys from its own callers. Today they are vans-mcp-server, pokemon-world-mcp, and road-test. Each one has its own Service Credential. That credential replaces the single Revocation List Credential of ADR 0060. It fetches the Revocation List and calls the key check of ADR 0077. It is not a Classroom API Key or a Personal API Key, and it grants no `/v1/*` call.

The router reads the credentials from one Fly secret, `VCR_SERVICE_TOKENS`. It is a JSON object that maps the SHA-256 hex of each credential to the Partner Service it names, the same shape as vans-signals' `SIGNALS_TOKENS`. A missing or invalid value refuses to start. During a rotation one Partner Service may be named by two hashes. Each Partner Service is limited to 600 calls a minute, and the limit is a setting. A call over the limit gets 429 and sends one ERROR Signal.

Where ADRs 0055 to 0062, 0065, and 0069 say vans-mcp-server and pokemon-world-mcp, the rule applies to every Partner Service. A new service that needs router identity, such as hex-island's city server, becomes a Partner Service with its own credential and calls the key check itself (ADR 0082).

## Considered Options

- **Keep one shared credential**: rejected. road-test is a third caller. A leak from any one service would force all three to rotate, and the router could not tell which service called or limit one of them.
- **Keep the map in the database with a Portal page**: rejected. There are three services and they rarely change. A page would add screens, permissions, and tests for no gain.
- **Ask the router to vouch for vans-signals tokens too**: rejected. vans-signals must accept a Signal while the router is down, including the Signal that says so. Each receiver keeps its own map, and one credential is valid at one receiver only.
