# A Class Session is a start-to-end window, and its keys follow it

A teacher sets a Class Session by picking its start time and its end time, not a start time plus a lifetime in hours. The end time is the sitting's `expires_at`, and Portal calls it 結束時間. Creating a sitting requires both times. The Portal form, `POST /teacher/classes/{id}/sessions`, and the WebMCP `create_class_session` all take `session_at` and `expires_at`, and a request missing either one is refused. `ttl_hours` is gone. The Portal form prefills the start with now and the end with start plus 2 hours, and the end moves with the start until the teacher edits it. The Class's `api_key_ttl_hours` and the `student_default_ttl_hours` setting existed only to supply that lifetime, so both are removed: the column is dropped from both databases, and an old config file that still names the setting is ignored.

Both times stay editable after creation, in one editor that sends only the fields that changed. The end must be later than the start. Either time may lie in the past. Setting the end in the past ends the sitting.

Every Classroom API Key already issued for the sitting follows the sitting's current start and end, without a new redeem. Moving the end moves each key's expiry. Moving the start later makes those keys `not_started` until the new start. When the new start is later than now, the old start has passed, and at least one student has redeemed, Portal asks the teacher to confirm that those students' keys will pause until the new start.

Every sitting has a start time. A one-time migration sets a missing `session_at` to the sitting's `created_at`, the time Portal already showed for it. A start time cannot be cleared.

Issued keys used to be planned to keep the expiry written at issuance. That served the signed-key plan, which was dropped (de264c8). Partner Services ask the router through the Key Check, so they already see the sitting's current times. It replaces ADR 0039's rule that a sitting with no `session_at` has no start gate.

## Considered Options

- **Keep the lifetime in hours**: rejected. The teacher thinks in "9:00 to 11:00", and an editable end time already exists, so hours were a second way to say the same thing.
- **Fix each key's expiry at issuance**: rejected. Extending a sitting would make every student redeem again, and nothing outside the router reads the key's own expiry any more.
- **Lock the start time once the sitting has started**: rejected. The teacher may need to fix a wrong start. The confirmation covers the case that pauses students mid-class.
- **Keep `ttl_hours` on the API for old callers**: rejected. The only callers are Portal and its WebMCP tools, which ship in this repo and change with it.
