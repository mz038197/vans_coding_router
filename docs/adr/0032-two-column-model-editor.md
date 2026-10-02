# Teachers edit models in two columns

The teacher editor for Session Chat Language Models and the Router Model Template is one modal. The left column is the Upstream Model Catalog for the kind loaded when the modal opened or when the kind changed. In the editor that column is labeled 候選清單. That label is not the vcr-auto candidate list on a Personal API Key. The right column is the whole draft, grouped by shelf. Checking and unchecking moves a Model ID between the columns. Provider, kind, and search stay above the left list. A provider with no kind split also shows the assignment shelf on that row. The modal uses the screen width minus a margin and the height below navigation. The columns scroll on their own and stay side by side. Upload, download template, download current list, cancel, and save are icons on the title row. Upload arrives on the text shelf.

## Considered Options

- **One scrolling list of candidates and checked models**: rejected. The draft is hard to see apart from the catalog, and search hides models already checked.
- **Stack the columns when the window is narrow**: rejected. The teacher still needs both lists in view.
- **Refresh the open candidate list when the catalog memory refreshes**: rejected. A row the teacher is about to check would disappear.

## Consequences

- Collapse of a shelf lasts only while the modal is open.
- A Model ID already in the draft is omitted from the candidate list, on every shelf.
- A checked Model ID the current catalog does not list stays on the right, marked not listed.
