# Session Model Allowlist is a Class Session field, not Course Catalog

Teachers curate which Router Model Template ids a Class Session may use. Unset means the full Template on the keyed GET and no extra API filter. An explicit empty list means zero models. The same `GET /extension/chat-language-models` stays public without a key (precheck and teacher candidates) and returns the filtered Template when authorized with a Classroom API Key. Portal install scripts embed that same filtered Template and sync (drop extra VCRouter models). Chat completions and responses reject Model IDs off the list. This does not belong in Course Catalog YAML. `pegasi_router` must keep the same contract.

## Considered Options

- **Allowlist in Course Catalog YAML**: Catalog is Install Actions and Lesson Snippets. Rejected.
- **A second model-list GET or stuffing the list into redeem**: The extension already GETs this path on redeem, activate, and retry. Rejected.
- **Only Copilot picker, no API reject**: The Classroom API Key would still call disallowed models. Rejected.
