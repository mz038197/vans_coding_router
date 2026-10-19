# Teachers edit models in a six-step wizard

Status: accepted. Supersedes ADR-0032 and amends ADR-0037.

The teacher editor for Session Chat Language Models and the Router Model Template is one modal that walks six steps: 模型選擇 (the Classroom Model Choice), 學生可用的模型 (the text shelf), 分配難度 (Auto Tiers and each text-shelf Model ID's tier), 自動選模：誰來判斷難度 (the selector shelf), 其他功能 (the image, embeddings, speech, and speech-transcription shelves, and the decision shelf), and 檢查與儲存 (a plain-language review). A step list marks each step ✓, ⚠, or —; the teacher may open any step at any time, and 儲存 is on every step. The modal body is the one scroll area. The editor always opens on step 1.

The Classroom Model Choice moves into the editor. Step 1 shows 自動 and 學生自選 as two cards, and the choice is saved with the document in one PATCH when the teacher presses 儲存. 取消 leaves both unchanged, and a refused save changes neither. A sitting with no choice stored shows no card selected, and saving without picking one keeps it unset. The sitting row shows the choice as text, not a control. The Router Model Template is always Automatic Models and shows no cards.

Under 學生自選, and on a sitting with no choice stored, steps 3 and 4 are marked — and show a note in place of their settings, which stay kept. When a tier or selector problem would make the Portal save check refuse the document, steps 3 and 4 show their settings so the teacher can fix it there, and the step that holds the problem is marked ⚠. The decision shelf works in every mode, so it sits in step 5, not step 4. The Router Model Template editor always shows steps 3 and 4.

A blocked save and an unsaved-changes cancel open dialogs inside the editor: the first lists each blocker with a link to its spot, the second asks 繼續編輯 or 捨棄修改. A refusal from the server is shown in the same dialog in its own words. Upload, download template, download current list, and show Model IDs sit in a 更多 menu with text labels. Upload still lands on the text shelf.

The Router Model Template editor opens as 預設模型設定 from the course tab toolbar, and the 個人 API Key tab keeps a link to it. It wears a distinct frame and a banner saying new sittings copy it and the Personal API Key uses it.

## Considered Options

- **Keep the two-column editor (ADR-0032) and add the tiers above it**: rejected. Three nested scroll areas, tiers apart from the model each one holds, and the selector shelf hidden behind the 決策 filter.
- **A tier board with one column per Auto Tier**: rejected after the teacher compared both prototypes.
- **Keep the mode on the sitting row, saved at once**: rejected. The mode and the models it uses would be saved apart, and a refused model save could leave the mode changed.
- **Keep the decision shelf in step 4 beside the selector shelf**: rejected. Under 學生自選 step 4 reads —, yet the decision shelf still applies.
- **Use the browser's confirm and alert boxes**: rejected. They cannot list blockers with links, and they block the page.

## Consequences

- Step 2 hides a Model ID that sits on another shelf and leaves it out of each provider's 已選 x／y.
- Each step loads its own Upstream Model Catalog list once per opening; the shared candidate column and its provider and kind selects are gone.
- A Model ID's settings survive an uncheck and re-check while the editor is open.
