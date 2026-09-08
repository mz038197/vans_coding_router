# Session Seat Limit counts every redeem identity

Session Seat Limit is the sitting’s student cap, not a Nickname Redeem quota. Occupancy is one `session_redemptions` row per user in that Class Session, whether the student arrived by Nickname Redeem, Sign-in Handoff, or Portal Google redeem. Nickname and Google identities stay unmerged, so two paths are two seats. This supersedes the ADR 0004 consequence that the limit counted nicknames and ignored Google.

## Considered Options

- **Keep a nickname-only cap**: rejected — teachers set a class size, not an extension-only queue; Google could otherwise overflow the room.
- **Merge nickname and Google into one person for seating**: rejected — Classroom Nickname is never merged with a Google user.
- **Disable frees a seat / lowering the limit evicts**: rejected — disable is revocation, not drop/add; lowering the limit is a gate, not a clear-out.
- **Couple the cap to `open_registration`**: rejected — login is not redeem.

## Consequences

- Portal copy is 課堂座位 (`occupied / limit`); occupied is `redemption_count`. The 已領取 column is gone; the seat cell (except the limit pencil) opens the roster.
- Full sitting rejects every new identity with `此課堂座位已滿，無法領取`. Rejoin of an already-seated identity still succeeds.
- `nickname_seat_count` is removed from session list payloads and WebMCP session fields.
