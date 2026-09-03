# Session owns Session Chat Language Models

A Class Session stores its own Copilot-shaped document instead of filtering the live Router Model Template. New sittings copy the Template at create; existing sittings get that copy once at ship, not when a student GETs. Session Model Allowlist is the ids in that document. This amends ADR 0009. Pegasi may keep the older Template-only allowlist.

## Considered Options

- **Filter the live Template by a teacher-edited id list (ADR 0009)**: rejected — later Template deploys change a sitting, and teachers cannot add a Model ID without republishing the router.
- **Copy the Template on student GET when the document is missing**: rejected — that binds the sitting to whatever Template is live when a student first connects, and later deploys still leak in for unmigrated sessions.
