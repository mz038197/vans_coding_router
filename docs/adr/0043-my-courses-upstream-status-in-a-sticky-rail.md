# 我的課程 keeps upstream status in a sticky left rail

Status: accepted. Amended by ADR 0046 (rail on the right, 208px).

Amends ADR 0041. 我的課程 is now two columns. The left column (260px) is the upstream status: one compact tile per key, stacked, under the heading 上游狀態. It sticks below the site header while the page scrolls, and scrolls on its own when there are more keys than fit. The right column is everything ADR 0041 describes, unchanged: course toolbar, course header with 結束課程, totals, new-class form, then one card per Class Session. The two columns share one top edge and nothing spans above them, so the page has no part that juts out to one side.

Below 1100px wide the rail moves above the course column, stops sticking, and its tiles sit in one row that scrolls sideways.

The 收合成一行 toggle and its collapsed one-line summary are gone, with the localStorage key that remembered it. A rail that is always beside the content has nothing to collapse.

The layout was chosen from prototype variants A to D on the `prototype/portal-redesign` branch, page `/portal/prototype/redesign?variant=D`.

## Considered Options

- **Keep the full-width upstream board above the course (ADR 0041, prototype A).** Rejected. The board scrolls away once a teacher opens a card, which is exactly when a key running out matters.
- **A course rail on the left with the upstream board above it (prototype B).** Rejected. The full-width board sits over a narrower column, so the left side juts out, and courses are already chosen from the toolbar.
- **Courses as tabs with upstream status in a collapsible line (prototype C).** Rejected. It hides key warnings behind a click.

## Consequences

The course column is 284px narrower on wide screens. Course cards already stack their two halves when narrow (ADR 0041), so nothing else moves.
