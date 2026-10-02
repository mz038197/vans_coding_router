# Keep the Upstream Model Catalog in process memory

Teachers check Model IDs from the Upstream Model Catalog. This process fetches the enabled providers before it accepts requests, keeps each portion in memory, and refreshes that memory every 30 minutes. A teacher catalog read serves the memory and does not call upstream again. OpenRouter is one fetch per kind (text, decisions, image, speech, transcription). A provider with no kind split is one fetch. Each fetch waits at most 30 seconds. A failed or timed-out fetch leaves that portion unavailable when it has never succeeded, and keeps the last successful snapshot on a later refresh. The refresh does not write Session Chat Language Models or a Router Model Template. A Personal API Key does not read this memory.

## Considered Options

- **Fetch upstream on every teacher catalog read**: rejected. A slow or failed fetch would sit on the teacher's check gesture, and a failure would look like an empty list.
- **Persist the catalog in the database**: rejected. The catalog is a cache of upstream lists. Stored Model IDs, shelves, and order already live on the sitting and the template, and a restart refills memory before accepting requests.
- **One OpenRouter fetch shared across kinds**: rejected. The kinds are separate upstream lists. One fetch cannot fill every shelf.

## Consequences

- Startup waits for the fetches, each capped at 30 seconds, and still accepts requests when a portion fails.
- A teacher read can be stale by up to 30 minutes.
- Student keyed lists and Personal API Key calls stay on their stored shelves.
