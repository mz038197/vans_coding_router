# Keep the Upstream Model Catalog in process memory

Teachers check Model IDs from the Upstream Model Catalog. This process fetches the enabled providers before it accepts requests, keeps each portion in memory, and refreshes that memory every 30 minutes. A teacher catalog read serves the memory and does not call upstream again. OpenRouter is one fetch per kind (text, decisions, image, speech, transcription). A provider with no kind split is one fetch. Each fetch attempt waits at most 30 seconds. A transient failure (a transport error, a timeout, a 5xx, or a 429) is tried again up to two more times in the same round, 2 and then 5 seconds apart, within 45 seconds of the first attempt. Any other failure is not tried again. A fetch that still fails leaves that portion unavailable when it has never succeeded, and keeps the last successful snapshot on a later refresh. The refresh does not write Session Chat Language Models or a Router Model Template. A Personal API Key does not read this memory.

## Considered Options

- **Fetch upstream on every teacher catalog read**: rejected. A slow or failed fetch would sit on the teacher's check gesture, and a failure would look like an empty list.
- **Persist the catalog in the database**: rejected. The catalog is a cache of upstream lists. Stored Model IDs, shelves, and order already live on the sitting and the template, and a restart refills memory before accepting requests.
- **One OpenRouter fetch shared across kinds**: rejected. The kinds are separate upstream lists. One fetch cannot fill every shelf.

## Consequences

- Startup waits for the fetches, each capped at 45 seconds including retries, and still accepts requests when a portion fails.
- A round that still fails logs one ERROR. It names each upstream that did not update, with the last HTTP status and upstream body (cut to 500 characters), or the exception stack, of its first failed portion. A retried attempt logs only a WARNING.
- A teacher read can be stale by up to 30 minutes.
- Student keyed lists and Personal API Key calls stay on their stored shelves.
