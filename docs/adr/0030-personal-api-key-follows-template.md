# A Personal API Key follows its holder's Router Model Template

A Personal API Key answers chat, image, speech, speech-transcription, and decision model-list reads from that key holder's Router Model Template. When that call's shelf has at least one Model ID, the list names `vcr-auto` once, first, then those ids in document order. An empty shelf's list names nothing. A call is accepted only when it names `vcr-auto` or a Model ID on that shelf. `vcr-auto` walks that shelf. Any other id is refused, and an empty shelf refuses the call, including `vcr-auto`. These lists do not read the Upstream Model Catalog. A Classroom API Key is unchanged: Automatic Models still names only `vcr-auto`, and Picked Models still names that sitting's shelf ids in document order.

This amends ADR 0028, which kept `/v1/models` on the live upstream shelf and forwarded a named Model ID. It also amends the ADR 0025 sentence that a Personal API Key sees the live image shelf and skips the shelf gate.

## Considered Options

- **Keep the live upstream shelf as the Personal API Key list**: rejected. The list would offer Model IDs the call then refuses, and it would change when the catalog changes rather than when the teacher saves the template.
- **Accept `vcr-auto` on an empty shelf**: rejected. There is no Model ID to walk.
- **Apply Classroom Model Choice to a Personal API Key**: rejected. That key is not bound to a sitting.

## Consequences

- A Personal API Key chat list is the text shelf. Image Generation, Speech, Speech Transcription, and Decision each use their own shelf.
- A named Model ID off that shelf is refused before any upstream call.
