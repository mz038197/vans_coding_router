# The key check answers legacy Classroom API Keys and Personal API Keys

Status: accepted. Amends ADR 0062.

The legacy check of ADR 0062 becomes the key check at `POST https://ai.vanscoding.com/internal/key-check`. A Partner Service calls it with its Service Credential in `Authorization`. The key to check is the request body. It answers a legacy Classroom API Key and a Personal API Key. A signed Classroom API Key is still checked by the Partner Service itself. While signed issuance stays off (ADR 0073), every Classroom API Key is a legacy key, so every Partner Service call goes through the key check until then.

An accepted Classroom API Key returns `kind: classroom`, `student_id`, `class_id`, and `class_session_id`. Those are the same integers a signed key carries (ADR 0071), so a Partner Service does not change its records when signing turns on. An accepted Personal API Key returns `kind: personal`, `user_id`, `is_admin`, and the `class_id` of every Class that user owns. Neither answer carries an email, a name, or the key id.

A refusal returns only a cause code. `vans-auth` turns the code into the notice, so the router and every Partner Service show the same words. The codes are the Key Refusals of ADR 0064 plus `not_started` (課堂尚未開始，請在開始時間後再使用), `expired` (API 金鑰已過期，請至 Portal 重新取得邀請碼), and `invalid` (無效的 API 金鑰). A Personal API Key that was replaced by a newer one is `invalid`.

A body the router cannot read gets a fixed 400 that does not repeat the input. No log line, Signal, or error response carries the whole key. A key check updates `last_used_at` at most once a minute per key.

## Considered Options

- **Keep the name legacy-key**: rejected. A Personal API Key is never signed (ADR 0049), so the endpoint outlives the last legacy key.
- **Return only the student id, as ADR 0062 did**: rejected. road-test groups students by Class and must tell a teacher or an admin from a student.
- **Return the Classroom Nickname**: rejected. A signed key carries no name, and road-test would lose it when signing turns on.
- **Validate the body with FastAPI's default 422**: rejected. That response repeats the input, which is the key.
