# Handoff: classroom session layout

A fresh agent can continue from `master` at `6148517`. The working tree was clean when this note was written.

## Decided

The teacher portal course screen uses layout D for Class Sessions, plus the full-height teacher menu and the compact course toolbar from the prototype.

- Wide course pane (about 700px and up; stays wide until below 640px): list of sittings plus an inspector.
- Narrow pane: one summary row per sitting; expand for the same settings. Collapsing a row stays collapsed. The same sitting stays selected across the switch.
- Chat models show display names. Classroom Model Choice sits on that same header with the edit control.
- Teacher or admin: menu is a left rail under the top bar. Below 900px it is a hamburger drawer (backdrop, Escape, choosing a section, or Agent Lobby closes it). Students keep the previous centered page.
- Course toolbar: search, status, course select, and ＋ 課程 (name field, Enter creates, Escape closes). New sitting is one row: name, time, hours, button. 結束課程 is on the course title row and stays admin-only (`PATCH /admin/classes/{id}`).

Do not reopen A/B/C as the product layout unless the user asks.

## Where to look

- Product: `src/presentation/fastapi/web/portal.html`, `src/presentation/fastapi/web/portal.css`
- Throwaway comparison UI (not the product): `src/presentation/fastapi/web/session_layout_prototype.html`, `src/presentation/fastapi/web/session_layout_prototype.js`
- Routes for that page: `src/presentation/fastapi/routers/portal_router.py` (`GET /portal/prototype/session-layout`, `GET /portal/static/session_layout_prototype.js`)
- Local URL: `http://127.0.0.1:8000/portal/prototype/session-layout?variant=D`
- Commits: `b2fc149` (session list D), `6148517` (menu and course toolbar)
- Contracts: `tests/presentation/fastapi/test_portal_router.py` (`test_portal_teacher_menu_is_a_full_height_rail_and_a_hamburger`, `test_portal_course_toolbar_matches_the_compact_prototype`, `test_portal_session_list_uses_wide_inspector_and_narrow_rows`), `tests/presentation/web/test_portal_teacher_tab.mjs`

No ADR was written. Domain terms stay in `CONTEXT.md`. This layout is not a new glossary term.

## Verify

`uv run pytest -q` passed at `6148517` (572 passed, 5 skipped). There is no project typechecker. The logged-in `/portal` screen was not browser-checked after the menu and course-toolbar commit; the prototype page was.

## Suggested skills

- `/implement` if the user wants another slice of this UI in the product
- `/tdd` at the existing portal HTML and `test_portal_teacher_tab.mjs` seams; do not invent a new seam without asking
- `/code-review` against `6148517` or `b2fc149` before changing the layout again
- `/prototype` only if the user wants another throwaway variant; do not treat the prototype files as production
- `/grill-with-docs` if a new domain term shows up; do not put layout details in `CONTEXT.md`
