// Steps 4 and 5 of the class model settings wizard (#74, #79): who judges difficulty
// (the vcr-auto Selector shelf and the separate decision shelf) and the other-feature
// shelves (image, embeddings, speech, speech transcription).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const portalHtml = readFileSync(
  new URL("../../../src/presentation/fastapi/web/portal.html", import.meta.url),
  "utf8",
);

function extractNamedFunction(source, name) {
  const needle = `function ${name}(`;
  const at = source.indexOf(needle);
  if (at < 0) throw new Error(`missing function ${name}`);
  const brace = source.indexOf("{", at);
  let depth = 0;
  for (let i = brace; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    else if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(at, i + 1);
    }
  }
  throw new Error(`unclosed function ${name}`);
}

function extractConst(source, name) {
  const match = source.match(new RegExp(`const ${name} = [\\[{][\\s\\S]*?\\n {4}[\\]}];`));
  if (!match) throw new Error(`missing const ${name}`);
  return match[0];
}

const NAMES = [
  "escapeHtml",
  "modelShelf",
  "modelIdPrefix",
  "clearShelfFlags",
  "applyShelf",
  "defaultVcrouterModel",
  "toggleDraftSelector",
  "moveDraftSelectorEarlier",
  "selectorNote",
  "modelWizardSelectorView",
  "checkDraftShelfModel",
  "modelWizardExtrasView",
  "modelWizardExtraCatalog",
  "modelWizardExtraPickerView",
  "draftAutoSnapshot",
  "modelWizardSelectorHtml",
  "modelWizardExtrasHtml",
];

const CONSTS = ["VCROUTER_STENCIL", "SESSION_CHAT_MODEL_SHELVES", "SELECTOR_NOTES", "MODEL_WIZARD_EXTRA_KINDS"];

function sandbox() {
  const code = [
    ...CONSTS.map((name) => extractConst(portalHtml, name)),
    ...NAMES.map((name) => extractNamedFunction(portalHtml, name)),
  ].join("\n");
  const box = {};
  vm.runInNewContext(`${code}\n${NAMES.map((n) => `this.${n} = ${n};`).join("\n")}`, box);
  return box;
}

const plain = (value) => JSON.parse(JSON.stringify(value));

const JEV = "openrouter@typesafe/jev-1.14";
const MSD = "openrouter@microsoft/microsoft-decision-1";
const LUNA = "openrouter@openai/gpt-6-luna-decisions";
const PPLX = "openrouter@~perplexity/pplx-decider-latest";
const DECISIONS = [
  { id: JEV, name: "TypeSafe Jev 1.14", provider: "openrouter" },
  { id: MSD, name: "Microsoft Decision 1", provider: "openrouter" },
  { id: LUNA, name: "GPT-6 Luna Decisions", provider: "openrouter" },
  { id: PPLX, name: "Perplexity Decider", provider: "openrouter" },
  { id: "acme@decider", name: "Acme Decider", provider: "acme" },
];

function selector(box, draft) {
  return plain(box.modelWizardSelectorView({ catalog: DECISIONS, draft }));
}

test("step 4 lists only OpenRouter decision models, checked selectors first in shelf order", () => {
  const box = sandbox();
  const state = selector(box, { models: [], selectorShelf: [LUNA, JEV] });
  assert.deepEqual(
    state.selector.map((row) => [row.id, row.checked, row.badge, row.canMoveEarlier]),
    [
      [LUNA, true, "優先", false],
      [JEV, true, "備用 1", true],
      [MSD, false, "", false],
      [PPLX, false, "", false],
    ],
  );
});

test("checking a selector adds it last as the next 備用; 往前 swaps it with the one before", () => {
  const box = sandbox();
  const draft = { models: [], selectorShelf: [] };
  box.toggleDraftSelector(draft, JEV, true);
  box.toggleDraftSelector(draft, MSD, true);
  box.toggleDraftSelector(draft, LUNA, true);
  assert.deepEqual(plain(draft.selectorShelf), [JEV, MSD, LUNA]);
  box.moveDraftSelectorEarlier(draft, LUNA);
  assert.deepEqual(plain(draft.selectorShelf), [JEV, LUNA, MSD]);
  box.moveDraftSelectorEarlier(draft, LUNA);
  box.moveDraftSelectorEarlier(draft, LUNA);
  assert.deepEqual(plain(draft.selectorShelf), [LUNA, JEV, MSD]);
  assert.deepEqual(
    selector(box, draft).selector.slice(0, 3).map((row) => [row.id, row.badge]),
    [[LUNA, "優先"], [JEV, "備用 1"], [MSD, "備用 2"]],
  );
  box.toggleDraftSelector(draft, LUNA, false);
  assert.deepEqual(plain(draft.selectorShelf), [JEV, MSD]);
});

test("each selector row carries a short note; an unmeasured model says so", () => {
  const box = sandbox();
  const notes = Object.fromEntries(selector(box, { models: [] }).selector.map((row) => [row.id, row.note]));
  assert.match(notes[JEV], /0\.5 秒/);
  assert.match(notes[LUNA], /準確率最高/);
  assert.equal(notes[PPLX], "未經過難度實測");
});

test("a stored selector the decisions list no longer shows stays listed and removable", () => {
  const box = sandbox();
  const gone = "openrouter@typesafe/jev-1.13";
  const state = selector(box, { models: [], selectorShelf: [gone, JEV] });
  assert.deepEqual(
    state.selector.slice(0, 2).map((row) => [row.id, row.checked, row.badge, row.listed]),
    [[gone, true, "優先", false], [JEV, true, "備用 1", true]],
  );
});

test("the decision shelf is checked on its own; one Model ID can sit on both shelves", () => {
  const box = sandbox();
  const draft = { models: [], removed: {}, selectorShelf: [JEV] };
  box.checkDraftShelfModel(draft, JEV, true, "TypeSafe Jev 1.14", "decisions");
  let state = selector(box, draft);
  assert.equal(state.selector.find((row) => row.id === JEV).checked, true);
  assert.deepEqual(state.decision.filter((row) => row.checked).map((row) => row.id), [JEV]);
  assert.equal(plain(draft.models).find((m) => m.id === JEV).decisionShelf, true);
  assert.equal(draft.models[0].name, "TypeSafe Jev 1.14");

  // Turning the selector off leaves the decision shelf alone, and the reverse.
  box.toggleDraftSelector(draft, JEV, false);
  state = selector(box, draft);
  assert.equal(state.selector.find((row) => row.id === JEV).checked, false);
  assert.equal(state.decision.find((row) => row.id === JEV).checked, true);
  box.toggleDraftSelector(draft, JEV, true);
  box.checkDraftShelfModel(draft, JEV, false, "", "decisions");
  state = selector(box, draft);
  assert.equal(state.selector.find((row) => row.id === JEV).checked, true);
  assert.equal(state.decision.find((row) => row.id === JEV).checked, false);
  assert.deepEqual(plain(draft.models), []);
  assert.deepEqual(plain(draft.selectorShelf), [JEV]);
});

const EXTRA_CATALOGS = {
  image: [
    { id: "openai@gpt-image-2", name: "GPT Image 2", provider: "openai" },
    { id: "openrouter@black-forest-labs/flux-3-pro", name: "FLUX 3 Pro", provider: "openrouter" },
    { id: "openrouter@google/imagen-5", name: "Imagen 5", provider: "openrouter" },
  ],
  embeddings: [{ id: "openai@text-embedding-4-small", name: "Text Embedding 4 Small", provider: "openai" }],
  speech: [{ id: "openai@gpt-6-tts", name: "GPT-6 TTS", provider: "openai" }],
  speech_transcription: [{ id: "openai@gpt-6-transcribe", name: "GPT-6 Transcribe", provider: "openai" }],
  all: [
    { id: "ollama_cloud@kokoro:cloud", name: "Kokoro", provider: "ollama_cloud" },
    { id: "ollama_cloud@minimax-m3:cloud", name: "MiniMax M3", provider: "ollama_cloud" },
  ],
};

test("step 5 shows one card per kind with its models, or 未開啟 when it has none", () => {
  const box = sandbox();
  const draft = {
    models: [
      { id: "openrouter@google/imagen-5", name: "Imagen 5 顯示名", imageShelf: true },
      { id: "ollama_cloud@kokoro:cloud", name: "Kokoro", speechShelf: true },
      { id: "ollama_cloud@minimax-m3:cloud", name: "MiniMax M3" },
    ],
  };
  const cards = plain(box.modelWizardExtrasView(draft));
  assert.deepEqual(cards.map((card) => [card.shelf, card.label]), [
    ["image", "生圖"], ["embeddings", "嵌入"], ["speech", "語音"], ["speech_transcription", "語音轉寫"],
  ]);
  assert.deepEqual(cards.map((card) => card.models.map((m) => [m.id, m.name, m.provider])), [
    [["openrouter@google/imagen-5", "Imagen 5 顯示名", "openrouter"]],
    [],
    [["ollama_cloud@kokoro:cloud", "Kokoro", "ollama_cloud"]],
    [],
  ]);
  assert.deepEqual(cards.map((card) => card.status), ["已開啟 1 個", "未開啟", "已開啟 1 個", "未開啟"]);
});

test("removing an extra-feature model takes it off only that shelf", () => {
  const box = sandbox();
  const draft = {
    models: [
      { id: "openai@gpt-image-2", name: "GPT Image 2", imageShelf: true },
      { id: "ollama_cloud@minimax-m3:cloud", name: "MiniMax M3" },
    ],
    removed: {},
  };
  box.checkDraftShelfModel(draft, "openai@gpt-image-2", false, "", "image");
  box.checkDraftShelfModel(draft, "ollama_cloud@minimax-m3:cloud", false, "", "speech");
  assert.deepEqual(plain(draft.models).map((m) => m.id), ["ollama_cloud@minimax-m3:cloud"]);
  assert.deepEqual(plain(box.modelWizardExtrasView(draft))[0].models, []);
  // Adding it back restores what it had.
  box.checkDraftShelfModel(draft, "openai@gpt-image-2", true, "GPT Image 2", "image");
  assert.equal(plain(draft.models).find((m) => m.id === "openai@gpt-image-2").imageShelf, true);
});

function picker(box, ui, draft = { models: [] }) {
  return plain(box.modelWizardExtraPickerView({ catalogs: EXTRA_CATALOGS, draft, ...ui }));
}

test("the add list switches kinds, and each kind lists its own catalog", () => {
  const box = sandbox();
  const image = picker(box, { shelf: "image" });
  assert.equal(image.title, "加入生圖模型");
  assert.deepEqual(image.kinds.map((k) => [k.shelf, k.label, k.active]), [
    ["image", "生圖", true], ["embeddings", "嵌入", false], ["speech", "語音", false], ["speech_transcription", "語音轉寫", false],
  ]);
  assert.deepEqual(image.rows.map((r) => r.id), EXTRA_CATALOGS.image.map((m) => m.id));
  const embeddings = picker(box, { shelf: "embeddings" });
  assert.deepEqual(embeddings.rows.map((r) => r.id), ["openai@text-embedding-4-small"]);
});

test("speech and speech transcription also list the All Models providers' whole lists", () => {
  const box = sandbox();
  assert.deepEqual(picker(box, { shelf: "speech" }).rows.map((r) => r.id), [
    "openai@gpt-6-tts", "ollama_cloud@kokoro:cloud", "ollama_cloud@minimax-m3:cloud",
  ]);
  assert.deepEqual(picker(box, { shelf: "speech_transcription" }).rows.map((r) => r.id), [
    "openai@gpt-6-transcribe", "ollama_cloud@kokoro:cloud", "ollama_cloud@minimax-m3:cloud",
  ]);
  assert.equal(picker(box, { shelf: "image" }).rows.some((r) => r.provider === "ollama_cloud"), false);
});

test("the add list filters by vendor with counts and searches name or vendor", () => {
  const box = sandbox();
  const all = picker(box, { shelf: "image" });
  assert.deepEqual(all.vendors.map((v) => [v.provider, v.label, v.count, v.active]), [
    ["", "全部廠商", 3, true], ["openai", "openai", 1, false], ["openrouter", "openrouter", 2, false],
  ]);
  const openrouter = picker(box, { shelf: "image", vendor: "openrouter" });
  assert.deepEqual(openrouter.rows.map((r) => r.id), [
    "openrouter@black-forest-labs/flux-3-pro", "openrouter@google/imagen-5",
  ]);
  assert.equal(openrouter.vendors.find((v) => v.provider === "openrouter").active, true);
  assert.deepEqual(picker(box, { shelf: "image", query: " IMAGEN " }).rows.map((r) => r.id), ["openrouter@google/imagen-5"]);
  assert.deepEqual(picker(box, { shelf: "image", query: "openai" }).rows.map((r) => r.id), ["openai@gpt-image-2"]);
  const none = picker(box, { shelf: "image", vendor: "openai", query: "flux" });
  assert.deepEqual(none.rows, []);
  assert.equal(none.empty, "找不到符合的模型");
  // A vendor the new kind does not have falls back to 全部廠商.
  assert.equal(picker(box, { shelf: "embeddings", vendor: "openrouter" }).rows.length, 1);
});

test("adding from the list puts the model on that kind's card; a model on another shelf is not offered twice", () => {
  const box = sandbox();
  const draft = { models: [{ id: "ollama_cloud@minimax-m3:cloud", name: "MiniMax M3" }], removed: {} };
  box.checkDraftShelfModel(draft, "openrouter@google/imagen-5", true, "Imagen 5", "image");
  box.checkDraftShelfModel(draft, "ollama_cloud@kokoro:cloud", true, "Kokoro", "speech");
  const cards = plain(box.modelWizardExtrasView(draft));
  assert.deepEqual(cards[0].models.map((m) => m.id), ["openrouter@google/imagen-5"]);
  assert.deepEqual(cards[2].models.map((m) => m.id), ["ollama_cloud@kokoro:cloud"]);
  const image = picker(box, { shelf: "image" }, draft);
  assert.equal(image.rows.find((r) => r.id === "openrouter@google/imagen-5").checked, true);
  assert.equal(image.rows.find((r) => r.id === "openai@gpt-image-2").checked, false);
  const transcription = picker(box, { shelf: "speech_transcription" }, draft);
  const kokoro = transcription.rows.find((r) => r.id === "ollama_cloud@kokoro:cloud");
  assert.deepEqual([kokoro.checked, kokoro.takenBy], [false, "語音"]);
  const minimax = transcription.rows.find((r) => r.id === "ollama_cloud@minimax-m3:cloud");
  assert.deepEqual([minimax.checked, minimax.takenBy], [false, "文字"]);
});

test("reordering the selector shelf counts as an unsaved change", () => {
  const box = sandbox();
  const before = box.draftAutoSnapshot({ models: [], selectorShelf: [JEV, LUNA] });
  const after = box.draftAutoSnapshot({ models: [], selectorShelf: [LUNA, JEV] });
  assert.notEqual(after, before);
});

test("step 4 HTML: 往前 only on backups; step 5 HTML: 未開啟 and a remove button per model", () => {
  const box = sandbox();
  const html = box.modelWizardSelectorHtml(box.modelWizardSelectorView({ catalog: DECISIONS, draft: { models: [], selectorShelf: [JEV, MSD] } }));
  assert.equal((html.match(/data-selector-earlier=/g) || []).length, 1);
  assert.match(html, /data-selector-earlier="openrouter@microsoft\/microsoft-decision-1"/);
  assert.match(html, /優先/);
  const cards = box.modelWizardExtrasHtml(box.modelWizardExtrasView({ models: [{ id: "openai@gpt-image-2", name: "GPT Image 2", imageShelf: true }] }));
  assert.equal((cards.match(/>未開啟</g) || []).length, 3);
  assert.match(cards, /aria-label="移除 GPT Image 2"/);
  assert.match(cards, /＋ 加入語音轉寫模型/);
});
