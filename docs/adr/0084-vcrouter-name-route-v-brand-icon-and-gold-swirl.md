# VCRouter: short name, route V Brand Icon, gold swirl

Status: accepted (the short name is tentative). Amends ADR 0048 and ADR 0049.

The Portal now presents the product as **VCRouter**, marks it with the **Brand Icon**, a route V, and draws the Login Network in gold.

- **Name.** Portal chrome shows "VCRouter": the page title, the app nav (`VC` + gradient `Router`) and the lobby host title. "Vans Coding Router" stays the full name in the repository, the API, its error messages, the OpenAPI docs, the upstream `X-Title` header and the guides. The short name is tentative; widening it to those places is a later decision.
- **Brand Icon.** A V on a 12x14 pixel grid. Two 3x3 destination blocks sit at the top, one empty row above each arm so they read as nodes, not serifs. The arms are 2 px wide and close on a 4x4 magenta (`#ff3d9a`) route node with a 2x2 hole: one request in, routed to a destination. As the icon (`/portal/static/brand-icon.svg`, favicon and app nav), the V is deep purple `#220011` on a white tile with a thin `#5c1a3d` edge.
- **The V of VCRouter.** In the login brand panel, the same V is drawn inline in the words' white and stands in for the letter V: "(V)CRouter". It is a touch taller than the capitals (0.86em). A magenta runner climbs one arm from the node, lights that destination, then does the same on the other arm, in a 2.88 s loop. Under reduced motion the runner is hidden and the V is still. Nothing else animates it; the favicon and the nav icon are static.
- **No character logo.** The Vans character image (`brand-logo.png`) is removed. The login brand panel no longer has a separate mark above the words; the V in the words carries it. The nav icon drops its badge plate, since the Brand Icon brings its own tile.
- **Gold.** The swirl's front colour changes from `#00ffff` to gold `#ffc53d`, on both Themes. The dither accent above 歡迎回來 and the sign-in button's focus ring on the dark Theme follow it. The back colour `#220011` and the dissolve rim `#5c1a3d` stay.
- **Brand words.** One line instead of two, so they shrink to `clamp(32px, 4.5vw, 64px)`. They remain the one size exempt from ADR 0045's type scale.

Chosen from prototype variants at commit `cf03ce8` on the local branch `prototype/brand-icon`: variant R3 with `?swirl=gold` (`/portal?variant=R3&swirl=gold`). Earlier variants are in that branch's history up to `0a71700`.

## Considered Options

- **Split V with a magenta point (A).** A clean V, but the routing read came only from its name.
- **Pixel swirl (B).** Matches the login page, but it smears into a blob at 16 and 32 px.
- **Route node, left to right (C), and turned 90° left (C2).** The clearest routing picture, but it read as a generic network or org-chart icon. Its colourings were tried: lit path, plain, one colour per model, inverted, white tile. Dropping the middle branch turned it into the V this ADR keeps.
- **The plain V (V-1).** Lost the routing feel: no node, the destination blocks looked like serifs. R1 brought back the node and separated the blocks.
- **An incoming tail under the node (R2).** It says "something comes in", but in the words it hangs below the baseline.
- **Pure yellow `#ffff00`.** Too loud on large areas; reads as a warning sign. Gold keeps the warmth.
- **Keep cyan.** Cyan is clearer where the dissolve meets the white pane on the light Theme. Gold was chosen for warmth and its fit with the magenta rim and node.

## Consequences

- On the light Theme, gold pixels fade more than cyan did where the panel dissolves into the white pane; the purple and magenta pixels carry the edge there.
- The Brand Icon is one SVG file; the inline V in `portal.html` repeats its shapes in the words' colour, with the runner. A change to the shape means editing both.
