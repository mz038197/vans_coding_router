# vans-auth keeps an accepted key check for 60 seconds and refuses when the router cannot answer

Status: accepted. Amends ADR 0061.

`vans-auth` also holds the key check client. It keeps an accepted answer for 60 seconds, keyed by the hash of the key, never the key. When the answer is older, it asks the router again. If the router cannot answer and no fresh answer is kept, the call is refused with 驗證服務暫時無法使用，請稍後再試, and each failed key check sends one ERROR Signal. A kept answer is not extended while the router is down. That is the same stance as ADR 0055.

The development bypass key that both MCP services carry today moves into `vans-auth`. A process that sees a production environment, such as `FLY_APP_NAME`, refuses to start while the bypass key is set.

Each Partner Service installs `vans-auth`. When signing turns on, the package checks a signed key itself and still asks the key check for a legacy key or a Personal API Key. The Partner Services do not change their calls.

## Considered Options

- **Ask the router on every call**: rejected. A result page that polls every few seconds would wait on the router each time.
- **Keep a kept answer longer while the router is down**: rejected. A disabled student would keep working for the whole outage.
- **Drop the bypass key**: rejected. Local development would need a local router for every tool call.
