# Web Search is a capability switch, not a shelf

Status: built, not deployed. Design settled with the owner on 2026-10-12. The endpoint, the switch, and the brake are built on the `issue-21-web-search` branch. The comparison against Exa and the provider sign-off are still pending under mz038197/VansPod#26.

A class had no way to search the web. Codex's built-in search was refused, and the model fell back to fetching sites one by one from the student's shell: 27 tool calls and about a million input tokens in four minutes. The router gains Web Search: it runs the search for the key holder against a search API and answers with titles, links, and text excerpts.

Web Search is a boolean on the Class Session, off for new and existing sittings, set by the teacher the way prompt logging is. This departs from ADR-0025 and ADR-0035, where a capability is on when its shelf holds a Model ID. Web Search has no model to check, so a shelf would put a non-model in the model picker and make the search provider a classroom choice. The provider is the operator's choice.

A Classroom API Key may search only while that sitting's switch is on. A Personal API Key may always search: its holder is a teacher or admin, and a teacher has to try a search before deciding to open it to a class.

The call is `POST /v1/search` with one to three queries of at most 1000 characters each. It is the router's own shape. It is not Codex's `/v1/alpha/search` and not Anthropic's server-side search tool. VansPod translates both into this call, so a change in either client does not need a router deploy. Refusals use the OpenAI-compatible error shape: 403 `web_search_disabled` when the switch is off, 429 `web_search_rate_limited`, 503 `web_search_unavailable` when no search key is configured, and the existing upstream-failure shape when the search API fails.

The router searches only. It does not open a page the caller names, so it never fetches an arbitrary address for a student. Results carry text excerpts so that a second fetch is needed less often.

Each key may send ten searches a minute. The count is held in this process's memory and serves search only. It is a brake on a runaway agent, not a usage record. There is no quota and no billing.

A search writes no Prompt Log.

The search API is Tavily behind a port, with one key named in the config and held as a secret. The choice is confirmed against Exa with real Traditional Chinese queries before the build is finished.

## Considered Options

- **A search shelf with a checked provider**: rejected. Search is not a model. The teacher decides whether a class may search, not which vendor answers.
- **Implement Codex's `/v1/alpha/search` in the router**: rejected. That route has no published wire format. The router would need a deploy whenever Codex changed it, and Claude Code could not use it.
- **Let a model with a search tool answer**: rejected. It costs an order of magnitude more and uses a model outside the Session Model Allowlist.
- **Refuse a Personal API Key**: rejected. A teacher could not try search without joining a sitting.
- **Open pages for the caller**: not now. The router would fetch any address a student names. Revisit after real use shows how often excerpts are not enough.
- **Write a Prompt Log per search, as Embeddings does**: rejected for now. A Prompt Log needs a model, and a search has none. The question the student asked is already logged when prompt logging is on. ADR-0035 kept the log because the input is student text a teacher can read; the same argument applies here and may bring the log back.
- **A general per-key rate limiter**: rejected. Only search needs a brake today.
- **Count searches as usage, or give a sitting a quota**: rejected by the owner for now.

## Consequences

- The switch decides whether the router searches for a class. It does not take a student's computer offline. Claude Code's WebFetch and an agent's shell still reach the web from that computer.
- The per-minute count resets on deploy or restart, and holds only while the router runs as one machine.
- `pegasi_router` does not offer this call. ADR-0009 binds it to the Session Model Allowlist contract, which Web Search is not part of.
- A Tavily development key allows 100 requests a minute, which ten students at the limit would fill. A larger class needs a paid key.
