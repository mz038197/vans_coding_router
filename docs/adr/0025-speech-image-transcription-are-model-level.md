# Speech, Image Generation, and Speech Transcription are model-level

Speech, Image Generation, and Speech Transcription follow Decision. Each is on when that sitting’s Session Chat Language Models include at least one Model ID checked from its shelf, and off when none are. The checked ids are the permission. A Classroom API Key call must name one of them, exactly, or the router refuses before any upstream call. A Personal API Key is outside the sitting, so this gate does not apply to it. Prompt logging stays a capability switch.

The shelves live in that same document: an image shelf, a speech shelf, and one speech-transcription shelf shared by File Transcription and Realtime Transcription. A Model ID belongs to at most one shelf in the sitting. Checking it onto a shelf removes it from every other shelf, including the text shelf and the decision shelf. An id already on the text shelf stays there until the teacher checks it onto another shelf. A file upload still arrives on the text shelf and does not check these shelves. Student chat listings omit every id on these shelves. There is no student list of Speech Models or Speech Transcription Models. For a Classroom API Key, the image model list is the checked Image Generation Models; none checked means that list is refused. A Personal API Key sees the live image shelf.

New sittings start with these three shelves empty. Existing sittings are not filled from `image_generation_enabled`, `tts_enabled`, or `speech_transcription_enabled`. Sittings that had Image Generation or Speech on become off until the teacher checks models. This supersedes the ADR-0020 sentence that Speech and Speech Transcription stay capability switches.

## Considered Options

- **Keep the capability checkboxes, or a checkbox plus a model list**: rejected. The tag can read on with nothing selectable, or off while models remain. That is the disagreement Decision already refused.
- **Leave existing “on” sittings open to every model of that capability until the teacher checks one**: rejected. The old switch and the checked ids would disagree until the first save.
- **Let one Model ID sit on more than one shelf**: rejected. A student chat list would then offer an id that is also an Image Generation Model, Speech Model, or Speech Transcription Model.
- **Return the live image catalog to a Classroom API Key**: rejected. The student would see models this sitting does not allow.
- **Add student lists for Speech and Speech Transcription**: rejected. Decision has no student catalog of its models; these two follow that.
