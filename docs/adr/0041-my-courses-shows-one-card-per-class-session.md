# 我的課程 shows one card per Class Session

Status: amended by ADR 0043 (upstream status moves to a sticky left rail; the 收合成一行 toggle is gone). The course column below is unchanged.

我的課程 is laid out as prototype variant F (課堂卡・卡內左右). From top to bottom: the upstream KPI dashboard, the course toolbar, the course header with 結束課程, the course totals row, the new-class form, then one card per Class Session, newest first. A card's header shows the sitting's name, status (未開始 / 進行中 / 已結束), time, seats and Token Usage. An open card holds the full session settings on its left half, rendered by the same code as before. Its right half lists each student's Token Usage for that sitting and its latest Prompt Logs in compact form. Clicking a student filters that card's logs, using the existing prompt-logs query with the sitting plus keyword = the student's Gmail. A log whose prompt mentions that Gmail can also match, and we accept that. When the sitting's prompt logging is off, the card still shows usage and says 「此課堂未記錄 Prompt 內容」 where the logs would be. On a narrow card the two halves stack.

Several cards may be open at once. By default the in-progress sittings are open. When none is in progress, the most recent sitting that has already started opens (latest `session_at`, or created time when unscheduled, at or before now), not an upcoming one; when none has started yet, the top card opens. The set saved in localStorage is merged in, and a newly created sitting opens. Open, in-progress cards refresh every 10 seconds, and pause while an input, select or textarea has focus. Other cards load once when opened. One usage fetch per course feeds every card and the totals row.

The prototype and its variants A to E are kept on the `prototype/usage-view` branch, page `/portal/prototype/usage-view?variant=F`.

## Considered Options

- **Keep the list + inspector and add usage to the inspector.** Rejected. Only one sitting is visible at a time, so a teacher cannot compare sittings. The inspector already holds a long column of settings, and usage and logs would push them off screen or need another tab inside the inspector.
- **A separate monitor page, as Prompt 監控 is today.** Rejected. A teacher in class switches between two pages: one to change a setting, the other to see whether students are using the router. That switch is the problem this change fixes.
- **Variants A to E** (inspector tabs, a course heat map with a drawer, a right-hand rail, two full-height columns, session tabs with a settings drawer). Rejected. Each either hides settings behind a tab or drawer, or splits a sitting's settings and usage into different parts of the page. F keeps both for one sitting inside one card.

## Consequences

The admin 課堂 list still uses the list + inspector, sharing the session settings rendering with the cards. The Prompt 監控 page is unchanged and remains the place for full log search, the prompt detail view and the course-wide student table. A card shows no prompt detail and no link out to Prompt 監控.

An open card fetches its own latest logs. A course with many open, in-progress sittings sends one usage request plus one prompt-logs request per such card every 10 seconds while 我的課程 is visible.
