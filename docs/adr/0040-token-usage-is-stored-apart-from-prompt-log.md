# Token Usage is stored apart from Prompt Log

Token Usage has its own `token_usage` table. Each successful router call writes one row (user, Class, Class Session, model, API endpoint, prompt/completion/total tokens, created time) at the same point that decides prompt logging, before the prompt-logging check. A Personal API Key call writes a row with no Class or Class Session. A rejected call writes none. The teacher's course usage (`GET /teacher/classes/{id}/usage`) sums this table, not `prompt_logs`, and reports `request_count` next to the token totals, for each student and for each sitting in that student's breakdown. `token_usage` is never archived or auto-purged. The admin "delete Prompt Logs for users" path deletes those users' Token Usage too and reports it as `deleted_token_usage`.

Before this, usage was a sum over `prompt_logs` rows with `status='ok'`. That had two faults: a sitting with prompt logging off recorded nothing, so the teacher saw zero usage; and archiving moved rows out of `prompt_logs`, so reported usage shrank at Archive Age.

## Considered Options

- **Write a Prompt Log with empty content when logging is off.** Rejected. Empty rows show up in the teacher's Prompt Log list and the Prompt 監控 page, and every list, search and count would need a filter for them. They are also still archived at Archive Age, so usage still shrinks. It also blurs the rule that a Prompt Log exists only when the sitting stores content.
- **Keep summing Prompt Logs and add the archive into the sum.** Rejected. It does not help sittings with logging off, the SQLite archive lives in separate yearly files, and archived rows are purged at Delete Age.

## Consequences

When the table was introduced, a one-time backfill filled `token_usage` from `status='ok'` rows in `prompt_logs` and in the archive. That backfill has run on every database and is gone (#120); a new database starts with an empty `token_usage`. Both archives now store each row's prompt, completion and total tokens (#121); SQLite rows archived before that read 0. Sittings that had prompt logging off have no history to recover.

Token Usage is kept for good, so it grows with traffic; it is a narrow row with no content. Removing a user's data now means removing their Token Usage too, which the existing admin delete does.
