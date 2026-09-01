# Agent instructions

Read `CONTEXT.md` before changing domain language. Record durable design decisions in `docs/adr/`.

## Agent skills

Skills live in `.agents/skills/` (Matt Pocock's set). Invoke them with `/skill-name` (for example `/grill-with-docs`, `/tdd`, `/ask-matt`).

### Issue tracker

GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` plus `docs/adr/`. See `docs/agents/domain.md`.
