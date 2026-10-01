# Each teacher owns a Router Model Template

A Router Model Template belongs to one teacher. A new teacher receives a copy of the shipped text-shelf starter. The teacher checks, orders, and shelves Model IDs on that copy the same way as Session Chat Language Models, and save forces the VCRouter Stencil. Portal reads and writes only the logged-in teacher's template. A new Class Session copies the class owner's template once; later template edits do not change a sitting that already has Session Chat Language Models. A model-list read needs a Portal teacher session or a Classroom API Key. A Personal API Key `vcr-auto` walks the shelf on the holder's template. An empty shelf refuses that call. A Personal API Key that names a Model ID keeps its existing forwarding.

## Considered Options

- **Keep one shipped file as every teacher's template**: rejected. Teachers cannot check their own shelves, and a file edit would be the candidate list for every Personal API Key.
- **Copy the template into a sitting whenever the teacher saves**: rejected. A sitting that already has Session Chat Language Models stays as it was when the class started.
- **Offer the model list with no teacher session and no Classroom API Key**: rejected. The list is the logged-in teacher's template, or `vcr-auto` for a Classroom API Key.

## Consequences

- New teachers and teachers promoted later with no template yet start from the shipped text-shelf starter.
- Personal API Key `vcr-auto` uses that holder's template shelf, including moving on when the current provider is full or exhausted.
- `/v1/models` for a Personal API Key stays the live upstream shelf.
