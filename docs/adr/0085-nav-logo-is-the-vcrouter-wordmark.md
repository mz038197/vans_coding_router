# The nav logo is the VCRouter wordmark

Status: accepted. Amends ADR 0084.

The top-left of the app nav shows the same wordmark as the login brand panel: the route V standing in for the V of "VCRouter", followed by "CRouter". The separate Brand Icon tile and the second, typed "VC" + "Router" are gone from the nav, so the V appears once.

- **One wordmark.** Portal, the Agent Lobby host and the session layout prototype all use it. The Lobby keeps its page name after the wordmark, behind a hairline: "(V)CRouter | Agent Lobby". A hidden "V" before the glyph makes screen readers read "VCRouter".
- **Black or white, one colour.** The V and "CRouter" are black `#000000` on the light Theme and white `#ffffff` on the dark one. The route node stays magenta `#ff3d9a` on both. The old gradient on "Router" is dropped.
- **Size and weight.** 20px, one step above the nav text, so the 12x14 V and its node stay legible. The word is semibold (600) in a Latin face first (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto`), as opencodex does: `system-ui` can resolve to a CJK face on zh-TW Windows whose Latin has no semibold, and the word looked thin. The login brand panel's "CRouter" uses the same face (`--font-wordmark`).
- **Static.** The nav V has no runner; only the login panel's V animates.
- **Brand Icon.** Still the favicon. It no longer appears in the nav.

## Considered Options

- **Keep the icon tile next to the name (ADR 0084).** It reads as two things, an icon and a name, and repeats the V.
- **Fixed gold `#ffc53d` on both Themes.** Ties the nav to the gold login swirl, but on the light Theme's white nav it was low in contrast and read as faded.
- **Animate the runner in the nav too.** Too busy at nav size, and always on screen.

## Consequences

- The route V now has three copies: the Brand Icon SVG, the animated login V and the static nav V, the nav V repeated in each nav page. A shape change means editing all of them.
