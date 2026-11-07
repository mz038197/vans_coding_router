# Login brand panel dissolves into the login pane

Status: accepted.

Amends ADR 0048. The hard edge between the login brand panel and the login pane read as two pictures side by side. The Login Network now dissolves into the pane, and the brand words get a calm area behind them.

- **Dissolve.** The outer 30% of the brand panel, on the side that meets the login pane, goes transparent pixel by pixel. The same 4x4 Bayer table decides which pixels go. The edge follows a gentle wave that drifts over time. When the layout stacks on narrow screens, the bottom edge dissolves instead.
- **Magenta rim.** Inside the dissolve band, back-colour pixels next to a swirl arm turn `#5c1a3d` before they vanish. The rim follows the arms and turns with them. This keeps the dissolve visible on the dark Theme, where `#220011` pixels disappear against the pane.
- **Eye.** The swirl calms to the back colour inside an ellipse around "Vans Coding Router", so the white words sit on a quiet ground. The ellipse is measured from the words and follows them when they reflow.
- **Layout.** The panel widens to 1.35fr against the pane's 1fr. While the swirl draws, the panel is transparent and pads its pane side by about 30% of its width, so the words stay clear of the dissolve band. Without WebGL the panel keeps its solid `#220011` background, unpadded (silent degrade, as before).

Chosen from prototype variants on the `prototype/login-dissolve` branch: variant A2c-T1 (`/portal?variant=A2c-T1`).

## Considered Options

- **A CSS gradient mask.** Rejected. A smooth fade on pixel art looks blurred, and on the light Theme the dark purple fades through a muddy grey band.
- **Straight dissolve (A1).** It works, but the wave edge reads as flowing.
- **Cyan trail (A2b).** The back colour leaves first and only cyan pixels carry the dissolve. Clear on the dark Theme, but the edge reads sparse. Rejected in favour of the magenta rim.
- **Magenta rim as a flat band by distance.** Rejected. It looked like a static block. The rim now comes from the swirl's shape.
- **Hard pixel outline (T2) or a solid plate (T3) for the brand words.** Rejected. The outline makes the words heavy. The plate cuts the swirl like a sticker.
- **Holding the eye solid inside the dissolve band.** Rejected. Pixels that should dissolve stayed as a dark Bayer patch. Moving the words out of the band fixed the overlap instead.

## Consequences

- The Login Network has a third colour, `#5c1a3d`, used only on the dissolve rim.
- The brand words are no longer centred in the panel. They are centred in the part that does not dissolve.
