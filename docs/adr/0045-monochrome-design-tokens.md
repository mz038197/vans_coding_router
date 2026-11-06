# Portal uses monochrome design tokens

Status: accepted.

Every page that loads `portal.css` (Portal, Agent Lobby, the login page) now draws from the shadcn style in `.agents/skills/design-system/SKILL.md`: black, white and grays, with colour reserved for status. The token names stay the same, so pages did not change their markup; only the values changed.

- **Colour.** Light: white background, `#111827` text, `#4b5563` secondary text, `#111111` primary buttons with white text. Dark: `#0a0a0a` background, `#fafafa` text, `#a1a1aa` secondary text, `#fafafa` primary buttons with near-black text (`--accent-fg`). Teal `#007070` survives only as the logo badge. Dark Theme's indigo accent and the teal-to-yellow gradient title are gone; the title is plain text.
- **Status colour.** Green `#16a34a` and orange `#d97706` are 3.3:1 and 3.2:1 on white, so they are used only as fills (meters, dots, tinted tag backgrounds, through `--success-fill` / `--warning-fill`). Status text uses `#15803d` and `#b45309`, 5.0:1. Role, endpoint and personal tags, which carried decorative pastel colours that read at under 2:1 on white, are neutral gray.
- **Type.** The interface font is the system UI stack (San Francisco and PingFang on Apple, Segoe UI and Microsoft JhengHei on Windows); body text is 14px. Code and IDs use Fira Code 400/500. Inter, Noto Sans TC and JetBrains Mono are no longer loaded.
- **Shape.** One radius, `--radius: 6px`, replaces the 8, 10, 12 and 14px radii. Pills stay fully round. Cards, buttons and the nav lose their shadows and blur.
- The Theme toggle stays.

## Considered Options

- **Geist, as the spec names it.** Rejected. Geist has no Chinese glyphs, so every Chinese character would fall back to another font and mixed lines would not match.
- **Use the spec's green and orange for text too.** Rejected. They fail WCAG AA 4.5:1 for body text; the spec itself says accessibility wins when it conflicts with aesthetics.
- **Restyle only 我的課程.** Rejected. Two visual styles would sit side by side until every page was redone, and the shared tokens make the whole site cheap to switch at once.
- **Drop the Theme toggle and follow the system appearance only, as Apple's guidelines advise.** Rejected for now. Teachers already use the toggle, and removing it is not part of this change.

## Consequences

- Every font size in `portal.css` is on the 12/14/16/20/24/32 scale and every gap, padding and margin on the 4/8/12/16/24/32 scale; each old value went to the nearest step, a tie to the smaller one, and a non-zero gap never to 0. 1px hairlines and layout offsets above 32px (the header clearance) are exempt. A portal CSS test enforces both scales.
- The Router Model Template editor keeps its gold frame, because the frame is what tells it apart from a sitting's settings, not decoration.
- The login page's animated background shader is unchanged.
