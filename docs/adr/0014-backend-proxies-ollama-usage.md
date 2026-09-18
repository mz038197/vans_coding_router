# Backend proxies Ollama usage; keys never leave the server

Teachers need Extra Usage Remaining on Portal without exposing Fly env keys. The router fetches `https://ollama.com/api/usage` server-side with `OLLAMA_CLOUD_API_KEY` and optional `OLLAMA_CLOUD_API_KEY_2`, then returns only sanitized Extra Usage Remaining on the existing teacher upstream-pools path. The browser never receives provider keys.

## Considered Options

- **Browser calls Ollama with a teacher-visible token**: rejected. It would send keys to the client and bypass the existing teacher-only upstream pools monitor permission.
- **Separate Portal usage endpoint with its own poll**: rejected. Extra Usage Remaining belongs on the same poll cycle as in-flight and Key Quarantine so the row stays one fact.

## Consequences

- Successful usage responses may be short-TTL cached (about 30–60s). Failures must not be long-cached; the next poll may retry.
- A 401, timeout, or other error for one key marks Extra Usage Remaining unavailable on that row only and must not hide in-flight counts or fail the whole monitor page.
