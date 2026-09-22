# Decision is model-level, not a capability checkbox

Speech and Speech Transcription stay capability switches. Decision does not: a Class Session is on for Decision when it has a Decision Model, and off when that field is empty. Teachers do not get a 「學生用程式送決策」 checkbox beside the other capabilities.

A boolean plus a model list lets Decision look “on” with nothing selectable, or “off” with models still stored. One optional Model ID is the permission. Existing sittings are not mapped from `decision_enabled` or the old shelf list; they start empty so the teacher reselects.

## Considered Options

- **Keep `decision_enabled` plus a model list**: rejected. Two fields disagree, and Decision then looks like 生圖／語音.
- **Default-map old Jev checks onto a Decision Model**: rejected. The option set is no longer the Decision Model Shelf; an automatic Jev pick would hide that the teacher must choose from this sitting’s OpenRouter models.
