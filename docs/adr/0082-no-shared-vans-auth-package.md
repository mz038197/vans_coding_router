# No shared vans-auth package: each Partner Service calls the key check itself

Status: accepted. Supersedes ADR 0062. Amends ADRs 0076, 0077, 0079, and 0080. Amended by ADR 0086 (Partner Services check signed keys themselves).

There is no `vans-auth` package. The contract between the router and a Partner Service is the key check itself (ADR 0077). Each Partner Service keeps its own small key check client in its own repository, in its own language.

A refusal carries the notice as well as the cause code: `{"accepted": false, "reason": "<code>", "message": "<notice>"}`. The router owns every notice, so the router and every Partner Service still show the same words, and a Partner Service shows `message` as it is. The one notice the router cannot send is the one for an unreachable router, 驗證服務暫時無法使用，請稍後再試, which each client carries itself.

The rules of ADR 0079 stay and now bind every client: an accepted answer is kept for at most 60 seconds, keyed by the hash of the key and never the key; an unreachable router means a refusal and one ERROR Signal, and a kept answer is not extended during an outage; no log line holds the whole key; a development bypass key refuses to start when the process sees a production environment such as `FLY_APP_NAME`. Code review of each Partner Service checks these rules.

A Partner Service keeps only identity in its client. Service rules, such as road-test's groups or which MCP tools a student may call, stay in the service after the answer comes back.

The planned direction is an API gateway in front of the Partner Services that checks keys once and passes the identity on. When it arrives, each Partner Service replaces its client with a read of what the gateway passes. Until then the key check is the only path. Signed issuance stays off (ADR 0074), and whether a Partner Service ever checks a signed key itself is decided again with the gateway, not here.

## Considered Options

- **Keep `vans-auth` as a shared Python package**: rejected. Three repositories would track a package release for a client that the gateway replaces, and a Partner Service in another language, such as hex-island on Cloudflare Workers, could not install it.
- **Return only the cause code and let each client map it**: rejected. Every client would carry its own copy of the notices, which is the drift the package was meant to stop.
