# The nav logo is the VCRouter wordmark

Status: accepted. Amends ADR 0084.

The top-left of the app nav shows the same wordmark as the login brand panel: the route V standing in for the V of "VCRouter", followed by "CRouter". The separate Brand Icon tile and the second, typed "VC" + "Router" are gone from the nav, so the V appears once.

- **One wordmark.** Portal, the Agent Lobby host and the session layout prototype all use it. The Lobby keeps its page name after the wordmark, behind a hairline: "(V)CRouter | Agent Lobby". A hidden "V" before the glyph makes screen readers read "VCRouter".
- **Black or white, one colour.** The V and "CRouter" are black `#000000` on the light Theme and white `#ffffff` on the dark one. The route node stays magenta `#ff3d9a` on both. The old gradient on "Router" is dropped.
- **Size.** 20px in the nav, one step above the nav text, so the 12x14 V and its node stay legible.
- **Face and weight.** "CRouter" is Segoe UI bold (700), in the nav and in the login brand panel (`--font-wordmark`). Not the Portal's `system-ui`: on zh-TW Windows that resolves to Microsoft JhengHei UI, which has only regular and bold, so 600, 700 and 900 render the same, and its bold Latin still reads thin.
- **V height.** The V is as tall as the C: 0.72em, where the top of the C sits in Segoe UI bold (its flat capitals stop at 0.70em; the round C overshoots them). Amends ADR 0084's "a touch taller than the capitals (0.86em)".
- **Thicker V.** In the wordmark, nav and login alike, the V's arms are 3 px wide instead of 2, to stand beside the bold word; the login runner widens with them. The Brand Icon (favicon) keeps its 2 px arms.
- **Static.** The nav V has no runner; only the login panel's V animates.
- **Brand Icon.** Still the favicon. It no longer appears in the nav.

## Considered Options

- **Keep the icon tile next to the name (ADR 0084).** It reads as two things, an icon and a name, and repeats the V.
- **Fixed gold `#ffc53d` on both Themes.** Ties the nav to the gold login swirl, but on the light Theme's white nav it was low in contrast and read as faded.
- **Animate the runner in the nav too.** Too busy at nav size, and always on screen.

## Consequences

- Off Windows, Segoe UI is usually missing and the wordmark falls back to the platform's UI face (San Francisco, Roboto); the 0.72em V then only roughly matches the C.

- The route V now has three copies: the Brand Icon SVG, the animated login V and the static nav V, the nav V repeated in each nav page. The two inline Vs have 3 px arms, the Brand Icon 2 px. A shape change means editing all of them.
