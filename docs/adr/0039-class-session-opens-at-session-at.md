# A Class Session opens at its start time

A Class Session's `session_at` is now the start of its window, as well as the base its `expires_at` is computed from. Before that time the Invite Code cannot be redeemed, by Nickname Redeem, Sign-in Handoff, or Portal Google redeem. Redemption fails with "課堂尚未開始…". A Classroom API Key bound to that sitting is refused as `not_started` everywhere a live key is required: `/v1` answers 403 with code `api_key_not_started`, and the keyed `GET /extension/course-catalog` and `GET /extension/chat-language-models` answer 403 with "課堂尚未開始，請在開始時間後再使用".

The key check covers keys that already exist on a sitting scheduled later, such as keys redeemed before this rule shipped. New keys cannot appear before the start, because redemption is refused.

There is no early-entry grace period. A teacher who wants students to set up before class sets the start time earlier. A sitting with no `session_at` (legacy rows) has no start gate. 403 rather than 401 keeps the extension from treating a valid key as one to replace. The key still works when the class starts. `/v1/realtime` also refuses such a key, but it closes with `invalid_api_key`, the same as an expired key does there. The Portal labels such a sitting and its keys 未開始 instead of 進行中.
