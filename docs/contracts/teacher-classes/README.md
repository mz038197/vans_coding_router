# Teacher Classes contract (ADR 0094)

A Partner Service asks which Classes a user may manage, answered the way the Key Check answers a
Personal API Key. A teacher surface signs in with `openid teacher`, learns the user id from the ID
token, and asks this instead of holding the teacher's key.

Request: `POST {ROUTER_URL}/internal/teacher-classes`
  headers `Authorization: Bearer <Service Credential>`, `Content-Type: application/json`
  body `{"user_id": 42}`

- 200 `accepted.json`: the user holds the teacher or admin role (role table, ADR 0078) and is active.
  `is_admin: true` lists every Class, ended ones included; otherwise the Classes the user owns.
- 200 `refused.json`: the user is unknown, disabled, or holds neither the teacher nor the admin role.
- 400 `bad-request.json`: the body is not a JSON object with an integer `user_id`.
- 401 `unauthorized.json`: the Service Credential is missing or wrong, the same answer the Key Check gives.

The answer carries no email, no Google subject, and no key.
