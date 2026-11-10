# The key check answers legacy Classroom API Keys and Personal API Keys

Status: accepted. Amends ADR 0063. Amended by ADRs 0082 and 0083 (Personal API Key answers with `classes`).

The legacy check of ADR 0063 becomes the key check at `POST https://ai.vanscoding.com/internal/key-check`. A Partner Service calls it with its Service Credential in `Authorization`. The key to check is the request body. It answers a Classroom API Key and a Personal API Key, so every Partner Service call goes through the key check.

An accepted Classroom API Key returns `kind: classroom`, `student_id`, `class_id`, and `class_session_id`. They are the router's integer ids (ADR 0072). An accepted Personal API Key returns `kind: personal`, `user_id`, `is_admin`, and the `class_id` of every Class that user owns. Neither answer carries an email, a name, or the key id.

A refusal returns a cause code and the notice for it in `message` (ADR 0082), so the router and every Partner Service show the same words. The codes are `disabled` and `invalid` (無效的 API 金鑰), `not_started` (課堂尚未開始，請在開始時間後再使用), and `expired` (API 金鑰已過期，請至 Portal 重新取得邀請碼). A Personal API Key that was replaced by a newer one is `invalid`.

A body the router cannot read gets a fixed 400 that does not repeat the input. No log line, Signal, or error response carries the whole key. A key check updates `last_used_at` at most once a minute per key.

## Considered Options

- **Keep the name legacy-key**: rejected. The endpoint answers Personal API Keys too, so it is not about legacy keys.
- **Return only the student id, as ADR 0063 did**: rejected. road-test groups students by Class and must tell a teacher or an admin from a student.
- **Return the Classroom Nickname**: rejected. The answer carries identity, not a name a Partner Service would then store.
- **Validate the body with FastAPI's default 422**: rejected. That response repeats the input, which is the key.
