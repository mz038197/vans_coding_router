# Decision Model comes from the OpenRouter decision shelf

OpenRouter’s Upstream Model Catalog has two teacher shelves because upstream lists text models and decision models separately. The same check-into-Session-Chat-Language-Models gesture fills both. Every Model ID checked from the decision shelf is a Decision Model, and a Decision Request may use any of them. None checked means Decision is off. There is no separate single-choice field. A text-shelf model cannot be a Decision Model. Student-facing chat model lists omit every decision-shelf Model ID in that sitting’s document. Teachers still see those ids on the decision shelf.

A Model ID checked from the decision shelf stays a decision-shelf id in that sitting until the teacher unchecks it. A later upstream list does not turn it into a text chat model or put it back on student chat lists. Chat and Responses with a Decision Model id are refused the same way as a Model ID off the Session Model Allowlist. A file upload arrives on the text shelf. A previously stored single choice is not a Decision Model and is not checked onto the decision shelf; the teacher rechecks.

This supersedes ADR-0021 and widens ADR-0022.

## Considered Options

- **Any checked OpenRouter id can be the Decision Model** (ADR-0021): rejected. The text shelf does not list decision models, so it cannot supply a Decision Model.
- **Omit only the selected Decision Model from student lists** (ADR-0022): rejected. Another decision-shelf id checked into the same document would still appear as a chat model.
- **Reclassify a checked id from the latest upstream list**: rejected. A catalog miss or a modality change would show a decision model to students, or drop a Decision Model the teacher never unchecked.
- **Keep one chosen Decision Model beside the checked list**: rejected. The check is the permission, same as text models for chat. A second field can disagree with what is checked.
- **Hide Decision Models from student lists but still allow chat**: rejected. A student who knows the Model ID would use a Decision Model as a chat model.
- **Carry the old single choice or an uploaded id onto the decision shelf**: rejected. Neither record says the teacher checked it from the decision shelf.
