# Teachers author Session Chat Language Models from the Upstream Model Catalog

Class owner or admin edits a sitting’s Session Chat Language Models in a session-row modal. Import/export matches Course Catalog (upload, download current draft, download Router Model Template as sample). The main surface is the Upstream Model Catalog: switch provider, search, check, and expand display name / thinking / token limits. Save and upload force the VCRouter Stencil. A live catalog is a shelf; stored rows stay if the catalog omits them or fails to load. This does not belong in Course Catalog YAML.

## Considered Options

- **Keep a teacher-edited id list over the live Template (ADR 0009)**: rejected — teachers cannot add a Model ID the same day, and routing fields would still come from the live file.
- **JSON textarea as the primary editor**: rejected — same authoring failure mode as the old Course Catalog YAML box; routing locks are easy to break.
- **Drop stored rows missing from the live catalog**: rejected — an upstream delist or timeout would zero the sitting.