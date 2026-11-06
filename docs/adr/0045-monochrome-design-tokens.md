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

- Spacing and font sizes outside 我的課程's upstream rail still use their old values (rem sizes, 6px and 10px gaps); they draw from the new colours and radius but are not yet snapped to the 4/8/12/16/24/32 and 12/14/16/20/24 scales.
- The Router Model Template editor keeps its gold frame, because the frame is what tells it apart from a sitting's settings, not decoration.
- The login page's animated background shader is unchanged.
