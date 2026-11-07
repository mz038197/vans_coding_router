# Embeddings are model-level

Embeddings follows Image Generation and Decision. It is on when that sitting’s Session Chat Language Models include at least one Model ID checked from OpenRouter’s embeddings list, and off when none are. The checked ids are the permission. There is no embeddings checkbox. Video, rerank, and audio output stay off the shelves. This reverses the catalog language that grouped embeddings with those non-shelves.

An Embeddings Request brings its input, a Model ID, and the rest of that embeddings body, and the router forwards that body. The reply is the upstream embeddings body, including its vectors and the model string the upstream attached. That string is not rewritten to `vcr-auto` and is not a Model ID. The call is not a stream and not a Decision Request. It draws the same upstream keys as chat for that provider, so Key Quarantine on one blocks the other. A provider refusal after the call was sent upstream is an Embeddings Refusal. A refusal before any upstream call, such as an empty embeddings shelf or a Model ID that is not on it, is not one.

Classroom Model Choice, the student embeddings list, and a Personal API Key’s embeddings list follow Image Generation as settled in ADR-0029 and ADR-0030. `vcr-auto` walks the embeddings shelf. Chat lists omit every embeddings-shelf id. A Model ID belongs to at most one shelf. Existing sittings and existing Router Model Templates are not filled, and the shipped text-shelf starter does not gain an Embeddings Model.

A call that produced output is a Prompt Log under the same switch as Image Generation. One call stores one log. String input is stored as those strings. Token and multimodal input, and the reply side, are short Traditional Chinese stand-ins. The vectors stay in the student reply.

## Considered Options

- **Leave embeddings off the shelves**: rejected. A class could not choose an embeddings model or call the endpoint under the same permission as Image Generation and Decision.
- **Shape the call as a Decision Request**: rejected. The embeddings body is its own request. Decision’s questions and answers are a different reply.
- **Skip the Prompt Log, as Decision does**: rejected. The input is student text a teacher can read, as with Image Generation. The vectors are not that text.
- **Store the vectors, or the raw token or multimodal payload, in the Prompt Log**: rejected. The teacher record would keep the embedding output, or a payload that is not the readable input.
- **Fill existing sittings, existing templates, or the shipped starter**: rejected. There is no old embeddings switch to migrate, and an automatic check would hide that the teacher must choose.
- **Add video or rerank shelves in the same change**: rejected. Only embeddings was required.
