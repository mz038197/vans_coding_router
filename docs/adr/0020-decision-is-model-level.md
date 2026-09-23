# Decision is model-level, not a capability checkbox

The single optional Decision Model field is superseded by ADR-0023. Decision is on when the sitting has at least one decision-shelf Model ID checked into Session Chat Language Models, and off when none are. There is no separate chosen id.

Speech and Speech Transcription stay capability switches. Decision does not. Teachers do not get a 「學生用程式送決策」 checkbox beside the other capabilities.

A boolean plus a model list lets Decision look “on” with nothing selectable, or “off” with models still stored. The checked decision-shelf Model IDs are the permission. Existing sittings are not mapped from `decision_enabled` or the old shelf list; they start empty so the teacher reselects.

## Considered Options

- **Keep `decision_enabled` plus a model list**: rejected. Two fields disagree, and Decision then looks like 生圖／語音.
- **Default-map old Jev checks onto a Decision Model**: rejected. The option set is no longer the Decision Model Shelf; an automatic Jev pick would hide that the teacher must choose from this sitting’s OpenRouter models.
