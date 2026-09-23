# Decision Model is omitted from student chat model lists

Widened by ADR-0023. Student chat lists omit every decision-shelf Model ID in the sitting’s document, not only the selected Decision Model.

A selected Decision Model is for Decision Requests only. APIs that list models for students to pick for chat (keyed `GET /extension/chat-language-models`, and `GET /v1/models` when that list is the classroom chat picker) omit that Model ID. Chat completions and Responses with that id are refused the same way as a Model ID off the Session Model Allowlist.

The id may still live in the teacher-owned Session Chat Language Models document so the Decision picker can offer it. Teacher catalog and session-row editors keep showing it; students do not.

## Considered Options

- **Leave the Decision Model in student chat lists**: rejected. Students would treat a Decision Model as a normal Session Chat Language Model.
- **Forbid the Decision Model from Session Chat Language Models entirely**: rejected. Options come from that OpenRouter list (ADR-0021); stripping the id from the stored document would delete the picker source.
