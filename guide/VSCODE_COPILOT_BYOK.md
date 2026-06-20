# VS Code BYOK

Use the API key issued by the Vans Coding Router portal.

```text
Base URL: https://ai.vanscoding.com/v1
API Key:  vcr_sk_xxxxxxxx
```

The router forwards OpenAI-compatible requests to cloud providers configured by the teacher. Students do not receive upstream provider keys.

Recommended endpoints:

- Chat clients: `POST /v1/chat/completions`
- Copilot BYOK clients that require Responses API: `POST /v1/responses`

The router rejects `previous_response_id`; send the full conversation context for each request.
