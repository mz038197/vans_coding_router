# The nav logo is the gold VCRouter wordmark

Status: accepted. Amends ADR 0084.

The top-left of the app nav shows the same wordmark as the login brand panel: the route V standing in for the V of "VCRouter", followed by "CRouter". The separate Brand Icon tile and the second, typed "VC" + "Router" are gone from the nav, so the V appears once.

- **One wordmark.** Portal, the Agent Lobby host and the session layout prototype all use it. The Lobby keeps its page name after the wordmark, behind a hairline: "(V)CRouter | Agent Lobby". A hidden "V" before the glyph makes screen readers read "VCRouter".
- **Fixed gold, one colour.** The V and "CRouter" are gold `#ffc53d`, the swirl's front colour, on both Themes. The route node stays magenta `#ff3d9a`. The old gradient on "Router" is dropped.
- **Static.** The nav V has no runner; only the login panel's V animates.
- **Brand Icon.** Still the favicon. It no longer appears in the nav.

## Considered Options

- **Keep the icon tile next to the name (ADR 0084).** It reads as two things, an icon and a name, and repeats the V.
- **V in the text colour.** Follows the Theme, but loses the tie to the gold login panel.
- **Animate the runner in the nav too.** Too busy at nav size, and always on screen.

## Consequences

- Gold on the light Theme's white nav is low in contrast. It is a logo, not body text, and the magenta node still marks it; revisit if it reads as faded.
- The route V now has three copies: the Brand Icon SVG, the animated login V and the static nav V, the nav V repeated in each nav page. A shape change means editing all of them.
