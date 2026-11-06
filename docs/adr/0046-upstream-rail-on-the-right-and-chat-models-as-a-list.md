# Upstream rail moves right and shrinks; chat models show as a grouped list

Status: accepted. Amended by ADR 0047 (in-flight light beside the label).

Amends ADR 0043. On 我的課程 the upstream status rail now sits right of the course column instead of left, and is narrower: 208px instead of 260px. Its tiles are tighter (8px padding, 12px label, 16px headline, 4px meter) so the course column, which is what teachers work in, gets the room. It still sticks below the site header. Below 1100px wide it still moves above the course column and scrolls sideways. In the markup it stays before the course column, so it comes first when the page stacks.

Each tile names its upstream with that upstream's logo instead of the word, followed by the key number (`#0`). The logo is announced and shown on hover as `Ollama` or `OpenRouter`. The logos are vendored SVGs from `@lobehub/icons-static-svg` (MIT), drawn through a CSS mask so they take the text colour in light and dark.

On a Class Session card, 對話模型 is no longer a box of pills that scrolls past 60px. It is a list with one row per model, in as many columns as fit, grouped by upstream (the part of the model id before `@`). Each row starts with the upstream logo. Every model shows, so the teacher sees the whole allowlist at a glance. A teacher-given model name shows as written. A model without a name shows a short form of its upstream model id (`openrouter@anthropic/claude-sonnet-4.5` shows `claude-sonnet-4.5`, `ollama_cloud@qwen3-coder:480b-cloud` shows `qwen3-coder 480b`). The full id shows on hover. An upstream with no logo is named in text.

The course toolbar lost its top margin, so the gap above it matches the gap beside it.

Chosen from prototype variants on the `prototype/upstream-rail-right` branch: rail variant B and model variant 3 (`/portal?variant=B&models=L`).

## Considered Options

- **Keep the rail on the left at 260px (rail A).** Rejected. It pushed the course column right and took more width than the tiles need.
- **Right rail as one list panel (rail C) or as one-line rows with details on hover (rail D).** Rejected. C loses the per-key card that makes each key's state easy to see. D hides the meter and reset date behind hover.
- **Grouped by upstream on one wrapping line per upstream, full or short names (models 1, 1+2).** Rejected for the scannable one-model-per-row list. The row form also gives each model its own hover target.
- **A count with an expand control.** Rejected. It hides the allowlist, and the point is to see it all.

## Consequences

The model list grows with the allowlist instead of scrolling inside a fixed box, so a session with many models has a taller card.
