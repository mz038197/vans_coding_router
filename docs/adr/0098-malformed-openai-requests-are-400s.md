# Malformed OpenAI-compatible requests are 400s in the OpenAI error shape

A request body that fails the router's own shape checks on an OpenAI-compatible path (chat, Responses, images, embeddings, speech, transcription, decisions, search) is refused with HTTP 400 and the OpenAI error body: `type` is `invalid_request_error`, `param` names the field, and `message` is one short Traditional Chinese sentence. The body never repeats the caller's input. Portal and other non-OpenAI paths keep their own errors.

Before this, chat, images, and speech used FastAPI's default: a 422 with `{"detail": [...]}` that copies the input back. VS Code Copilot BYOK reads any 422 as a Responsible AI content filter and prints the body verbatim. A student who sent an empty message saw "Filtered by Responsible AI Service" followed by their own conversation. A 400 is shown as "Request Failed: 400" with the body, so the body must stay short. OpenAI SDKs treat 400 and 422 alike: neither is retried.

## Considered Options

- **Keep 422, only switch to the OpenAI body**: rejected. Copilot still labels it a content filter.
- **Fix images only**: rejected. Chat has the same cause and is what students use most.
- **Validate each route by hand, as `/v1/search` does**: rejected. One handler for every OpenAI-compatible path keeps new routes from regressing.
