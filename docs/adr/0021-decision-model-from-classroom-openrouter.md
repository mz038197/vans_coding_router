# Decision Model options are the sitting’s OpenRouter chat models

Superseded by ADR-0023. A Decision Model must be checked from the OpenRouter decision shelf, not from any OpenRouter id in the sitting.

The Decision Model picker lists the OpenRouter Model IDs already in that Class Session’s Session Chat Language Models. It is not the fixed Decision Model Shelf (`openrouter@typesafe/jev-1.13`, `openrouter@~typesafe/jev-latest`). The Upstream Model Catalog no longer omits those ids as a special class.

Decision is an OpenRouter sitting concern. When the teacher’s 課堂模型 provider/context is not OpenRouter, hide the picker and keep the stored Decision Model. If that id later leaves the sitting’s OpenRouter Session Chat Language Models, treat it as empty (Decision off) and tell the teacher on save.

## Considered Options

- **Keep the Decision Model Shelf**: rejected. Teachers already curate OpenRouter chat models per sitting; a second Jev-only shelf cannot track that list.
- **Clear the Decision Model when the catalog provider leaves OpenRouter**: rejected. Provider filter is editor context, not a save of Decision. Clearing on tab switch would drop a valid choice the teacher never unset.
