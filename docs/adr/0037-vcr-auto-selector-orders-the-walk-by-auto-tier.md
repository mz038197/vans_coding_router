# A vcr-auto Selector orders the text-shelf walk by Auto Tier

Status: proposed

Each Session Chat Language Models document and each Router Model Template defines its own Auto Tiers: an ordered list of two to six labels, each with a Tier Description. The teacher names them, at most 20 characters and unique within the document, and orders them from weakest to strongest. A Tier Description is at most 300 characters, in any language, and is never blank. A text-shelf Model ID carries at most one Auto Tier of its own document. The tiers belong to that document alone: changing them in one sitting changes no other sitting and no template.

The shipped starter (`config/chatLanguageModels.vans.json`) carries three default tiers, 輕量, 一般, and 困難, with Traditional Chinese Tier Descriptions written for coding-class tasks and benchmarked against the selector models before release. A new teacher's template starts with them. For a document that has none, the editor fills them in, and they are stored when the teacher saves. The router reads only the stored tiers and never falls back to the defaults, so a later improvement to the defaults reaches a document only when its teacher applies it. The editor notes that editing a description can change how well selection works.

The document gains a selector shelf, filled from the OpenRouter decisions list in the same two-column editor. A Model ID on the selector shelf is a vcr-auto Selector. It is not a Decision Model: it does not turn Decision on, no student list names it, and no call may name it on a Decision Request unless it is also checked onto the decision shelf. The selector shelf is the one exception to a Model ID belonging to at most one shelf (ADR-0025): a Model ID may sit on both the decision shelf and the selector shelf. In the editor, an OpenRouter decisions row offers 決策 and 自動選模 as its shelves, and either or both may be checked. The selector shelf is optional, and emptying it pauses selection while keeping the tiers.

While the selector shelf has a Model ID, save is refused until every text-shelf Model ID has an Auto Tier. Renaming a tier keeps its Model IDs on it; deleting a tier that still holds a Model ID is refused until those Model IDs are moved. A Model ID newly checked onto the text shelf has no Auto Tier; the router does not guess one. Moving a Model ID off the text shelf clears its Auto Tier.

A new Class Session copies the class owner's template, tiers and selector shelf included, and later edits on either side do not reach the other. A file upload keeps the tiers it carries when they are valid and the Auto Tier of each Model ID it places on the text shelf when that tier exists, and does not fill the selector shelf. Downloading the current list keeps the tiers and each Model ID's Auto Tier.

Selection runs on a chat or Responses call that names `vcr-auto` from a Classroom API Key whose sitting is on Automatic Models, or from a Personal API Key, when the selector shelf has at least one Model ID and the text-shelf Model IDs use at least two Auto Tiers. A sitting with no Classroom Model Choice stored keeps document order. The sitting editor shows the selector shelf and the tiers only under Automatic Models; under Picked Models they are hidden and kept. The Router Model Template editor always shows them. The Portal session row shows 自動選模 when that sitting would select.

The router sends one Decision Request to the selector shelf, walked the same way as any vcr-auto shelf, with 1.5 seconds for the whole walk. Its state is the text of the last user message in that call, cut to 2000 characters; the system prompt, tool results, and images are not sent. A Responses string `input` is that text; otherwise it is the text of the last user item. Its one question is a choice between the Auto Tiers that hold a text-shelf Model ID, with their Tier Descriptions as criteria, and its instructions tell the selector to judge the task only and to ignore any text asking for a particular model. The chosen tier is the strongest tier whose probability is at least 0.2. The text-shelf walk then runs in this order: the chosen tier in document order, then each stronger tier from weakest to strongest, then each weaker tier from strongest to weakest. Exhaustion, full pools, and busy keep the existing vcr-auto rules, so every text-shelf Model ID stays in the walk.

The chosen tier is remembered in process memory for 30 minutes, keyed by API key, the last user message, and a fingerprint of that document's tiers and descriptions, so tool-result turns of the same request reuse it instead of asking again, and any change to the tiers makes the next call ask again.

When the selector walk ends in an error, a refusal, or nothing within 1.5 seconds, the text-shelf walk keeps document order. A selector failure never refuses the student call, is not a Readable Upstream Error, and is not posted to vans-signals.

The reply model stays `vcr-auto`. When selection ran, the Prompt Log stores the chosen tier's name as it was at that call and its confidence beside the Model ID that produced the output; renaming or deleting the tier later does not change that record. The teacher's Prompt Log view shows them beside the Model ID, for example `進階 · 0.92`. Nothing is stored when selection did not run or failed, and the selector call adds no Prompt Log of its own. There is no per-tier usage cap in this version.

Image Generation, Embeddings, Speech, Speech Transcription, and Decision keep the plain document-order walk. Existing sittings and Router Model Templates are not filled: their selector shelf is empty and they have no tiers until the teacher saves.

## Considered Options

- **Three fixed tiers shared by every document**: rejected. A course decides how many kinds of task it has and what each one means, and a tier change in one sitting must not touch another.
- **Unordered tiers**: rejected. Without an order there is no strongest plausible tier and no stronger fallback, and a student is better served by a model that is too strong than by one that cannot do the task.
- **Teacher-written criteria per Model ID**: rejected. Several Model IDs usually serve the same kind of task; describing the tier once keeps the question small.
- **Store only the descriptions a teacher changed and fall back to the router's defaults**: rejected. The descriptions the selector reads are the ones the teacher saw and saved, not text that changes under them with a release.
- **Let a Model ID stay untiered while selection is on**: rejected. Every Model ID the selector can reorder has a place in the order the teacher chose.
- **Use a decision-shelf Model ID as the selector**: rejected. A decision-shelf check is the permission for student Decision Requests (ADR-0023); a teacher who wants automatic selection would also open Decision to students.
- **Keep the selector shelf exclusive with the decision shelf**: rejected. A teacher who lets students send Decisions with Jev would need a second decision model just to select.
- **Let a Personal API Key name a selector-shelf Model ID on a Decision Request**: rejected. One rule for both keys: the decision shelf is what a key may name.
- **One site-wide selector in `router.yaml`**: rejected. The teacher chooses the selector the same way they choose every other model.
- **A single selector field instead of a shelf**: rejected. A shelf reuses the editor, the template copy, and the walk, so a second selector covers a failed first one.
- **Require a selector under Automatic Models**: rejected. A new Class Session starts as Automatic Models, so every new sitting would be unusable until the teacher set one.
- **Select on a sitting with no Classroom Model Choice stored**: rejected. Selection belongs to Automatic Models; a teacher who wants it switches the sitting to Automatic Models.
- **Guess an Auto Tier from the model name or price**: rejected. A wrong guess misleads the teacher about what the walk will do.
- **Refuse the call when the selector fails**: rejected. Selection only reorders a walk that already works without it.
- **Cap the strongest tier per Class Session**: deferred. The Prompt Log records tiers first, so a cap can be set from real use.
- **Ask the selector on every request**: rejected. A tool-calling turn repeats the same last user message; asking again adds latency and can switch models mid-task.

## Consequences

- The selector Decision Request draws the OpenRouter key pool, so its cost and Key Quarantine are shared with chat and Decision.
- The tiers, each text-shelf entry's Auto Tier, and every selector-shelf id are stripped from every Copilot list the extension or the install script writes.
- The Prompt Log gains tier-name and confidence columns, in SQLite and Postgres.
- Tier names in different sittings are not comparable, so Prompt Logs are not compared by tier across sittings.
- Streaming starts after the selector answers, so a selected call's first byte can wait up to 1.5 seconds longer.
