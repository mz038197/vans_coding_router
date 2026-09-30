# A shelf check qualifies a Decision Model and an Image Generation Model

A Decision Model is a Model ID the teacher checked onto the decision shelf. An Image Generation Model is a Model ID the teacher checked onto the image shelf. The `openrouter@` prefix is not part of either qualification. Save accepts the check. Routing and the Portal session indicators for 決策 and 生圖 read the check. A checked Image Generation Model is forwarded to that Model ID's provider; the provider's refusal is the refusal.

The Portal catalog is unchanged. The decision shelf and the image shelf stay on providers whose upstream list has a kind split (today OpenRouter). A check from All Models still cannot place a Model ID on either shelf.

## Considered Options

- **Keep rejecting a non-OpenRouter id that carries `decisionShelf` or `imageShelf`**: rejected. The teacher's check is the qualification. The prefix made a text-shelf OpenRouter id sound like a Decision Model and refused a check the document already recorded.
- **Open the decision shelf and the image shelf on All Models**: rejected. Those providers have no kind split. All Models still places a check on the text shelf, the speech shelf, or the speech-transcription shelf.
- **Keep the router refusal that tells the client to use `openrouter@` for image generation**: rejected. A checked Image Generation Model is forwarded, the same way a checked Speech Model is. A provider with no image API answers with its own refusal.

## Consequences

- `is_decision_shelf_model` and `is_image_shelf_model` match on the shelf flag, not on an OpenRouter prefix.
- One Model ID still belongs to at most one shelf (ADR 0025). The catalog UI in ADR 0023 stays the OpenRouter decision shelf; this ADR only drops the prefix gate on a check that is already stored.
