# One Classroom Model Choice for every student call

A Class Session has one Classroom Model Choice for chat, Responses, Image Generation, Speech, Speech Transcription, and Decision together. Picked Models accepts only a Model ID checked onto that call's shelf. Automatic Models accepts only `vcr-auto`. The student chat list stays the text shelf, and decision, speech, and speech-transcription ids stay off it. Speech, Speech Transcription, and Decision each have their own student list using that same chat-list rule: the shelf's Model IDs under Picked Models, and only `vcr-auto` under Automatic Models or when no choice is stored. Those three reads still succeed when the shelf is empty; the call stays off when none are checked. A sitting with no choice stored keeps mixed acceptance. A new Class Session starts as Automatic Models. Once set, the teacher switches only between the two choices.

## Considered Options

- **Change only the student chat list, and still accept a named Model ID under Automatic Models**: rejected. A class on Automatic Models would still run a hardcoded Model ID.
- **Limit the choice to chat and Responses**: rejected. Image Generation, Speech, Speech Transcription, and Decision follow the same choice.
- **Fail the speech, transcription, and decision list reads when the shelf is empty, as `GET /v1/images/models` does**: rejected. Those reads follow the classroom `GET /v1/models` rule and still succeed.
- **Put every shelf on `GET /v1/models`**: rejected. The chat list stays the text shelf.
- **Make existing sittings exclusive immediately**: rejected. A named Model ID already in use would stop before the teacher chooses.
- **Keep mixed acceptance as a third choice the teacher can select**: rejected. Mixed remains only on a sitting that has never been set.
