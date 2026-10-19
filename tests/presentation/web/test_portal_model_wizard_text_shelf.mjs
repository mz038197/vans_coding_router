// Step 2 of the class model settings wizard: the text shelf (#74, #77).
// View state in (catalog, draft, filter, search, collapse), groups and counts out.
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
  const start = source.slice(at - 6, at) === "async " ? at - 6 : at;
  const brace = source.indexOf("{", at);
  let depth = 0;
  for (let i = brace; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    else if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error(`unclosed function ${name}`);
}

const NAMES = [
  "escapeHtml",
  "modelShelf",
  "modelIdPrefix",
  "modelWizardTextShelfView",
  "checkDraftTextModel",
  "defaultVcrouterModel",
  "clearShelfFlags",
  "applyShelf",
  "modelWizardTextShelfHtml",
  "modelWizardTextFieldsHtml",
  "onSessionChatModelField",
  "draftModelById",
  "documentFromDraft",
  "stencilDraftModel",
];

// The field handler reads the open draft from the page global and refreshes the step marks.
function sandbox() {
  const code = [
    portalHtml.match(/const VCROUTER_STENCIL = \{[\s\S]*?\n {4}\};/)[0],
    ...NAMES.map((name) => extractNamedFunction(portalHtml, name)),
  ].join("\n");
  const box = {
    sessionChatModelsDraft: { models: [], removed: {} },
    refreshModelWizardStatus: () => {},
    renderAutoTierBlock: () => {},
  };
  vm.runInNewContext(`${code}\n${NAMES.map((n) => `this.${n} = ${n};`).join("\n")}`, box);
  return box;
}

const plain = (value) => JSON.parse(JSON.stringify(value));

const CATALOG = [
  { id: "ollama_cloud@a:cloud", name: "Alpha", provider: "ollama_cloud" },
  { id: "ollama_cloud@b:cloud", name: "Beta", provider: "ollama_cloud" },
  { id: "openrouter@x/gamma", name: "Gamma", provider: "openrouter" },
  { id: "openrouter@x/delta", name: "Delta", provider: "openrouter" },
  { id: "openrouter@x/epsilon", name: "Epsilon", provider: "openrouter" },
  { id: "acme@zeta", name: "Zeta", provider: "acme" },
];
const PROVIDERS = ["ollama_cloud", "openrouter", "acme"];

function view(box, { draft = { models: [] }, ui = {} } = {}) {
  return plain(box.modelWizardTextShelfView({ catalog: CATALOG, providers: PROVIDERS, draft, ui }));
}

test("provider filters: 全部 first with every model, then each provider with its count", () => {
  const box = sandbox();
  const state = view(box);
  assert.deepEqual(
    state.filters.map((f) => [f.provider, f.label, f.count, f.active]),
    [
      ["", "全部", 6, true],
      ["ollama_cloud", "ollama_cloud", 2, false],
      ["openrouter", "openrouter", 3, false],
      ["acme", "acme", 1, false],
    ],
  );
  assert.deepEqual(state.groups.map((g) => g.provider), PROVIDERS);
});

test("a provider filter shows only that provider's group; counts stay whole", () => {
  const box = sandbox();
  const state = view(box, { ui: { filter: "openrouter" } });
  assert.deepEqual(state.groups.map((g) => g.provider), ["openrouter"]);
  assert.equal(state.filters.find((f) => f.provider === "openrouter").active, true);
  assert.equal(state.filters[0].count, 6);
});

// Beta and Delta checked on the text shelf; Epsilon on the decision shelf; an image model too.
function pickedDraft() {
  return {
    models: [
      { id: "openrouter@x/delta", name: "Delta 顯示名" },
      { id: "ollama_cloud@b:cloud", name: "Beta" },
      { id: "openrouter@x/epsilon", name: "Epsilon", decisionShelf: true },
      { id: "openai@gpt-image-2", name: "img", imageShelf: true },
    ],
    removed: {},
  };
}

test("已勾選 lists every text-shelf model in draft order with its provider", () => {
  const box = sandbox();
  const state = view(box, { draft: pickedDraft() });
  assert.equal(state.chosen.count, 2);
  assert.equal(state.chosen.collapsed, false);
  assert.deepEqual(
    state.chosen.models.map((m) => [m.id, m.name, m.provider]),
    [
      ["openrouter@x/delta", "Delta 顯示名", "openrouter"],
      ["ollama_cloud@b:cloud", "Beta", "ollama_cloud"],
    ],
  );
});

test("provider groups show 已選 x／y and leave out checked models", () => {
  const box = sandbox();
  const state = view(box, { draft: pickedDraft() });
  const byProvider = Object.fromEntries(state.groups.map((g) => [g.provider, g]));
  assert.deepEqual([byProvider.ollama_cloud.picked, byProvider.ollama_cloud.total], [1, 2]);
  assert.deepEqual([byProvider.openrouter.picked, byProvider.openrouter.total], [1, 3]);
  assert.deepEqual(byProvider.ollama_cloud.rows.map((r) => r.id), ["ollama_cloud@a:cloud"]);
  // Epsilon sits on another shelf, so it is not offered again here.
  assert.deepEqual(byProvider.openrouter.rows.map((r) => r.id), ["openrouter@x/gamma"]);
});

test("已勾選 ignores the provider filter and the search", () => {
  const box = sandbox();
  const state = view(box, { draft: pickedDraft(), ui: { filter: "acme", query: "zeta" } });
  assert.equal(state.chosen.count, 2);
  assert.equal(state.chosen.models.length, 2);
});

test("search matches a model name or its provider, case-insensitively", () => {
  const box = sandbox();
  const byName = view(box, { ui: { query: "  GAM " } });
  assert.deepEqual(byName.groups.flatMap((g) => g.rows.map((r) => r.id)), ["openrouter@x/gamma"]);
  const byProvider = view(box, { ui: { query: "acme" } });
  assert.deepEqual(byProvider.groups.flatMap((g) => g.rows.map((r) => r.id)), ["acme@zeta"]);
});

test("search does not change 已選 x／y", () => {
  const box = sandbox();
  const state = view(box, { draft: pickedDraft(), ui: { query: "gamma" } });
  const openrouter = state.groups.find((g) => g.provider === "openrouter");
  assert.deepEqual([openrouter.picked, openrouter.total], [1, 3]);
});

test("collapsed groups hide their rows; 已勾選 collapsed still reports its count", () => {
  const box = sandbox();
  const state = view(box, {
    draft: pickedDraft(),
    ui: { collapsed: { openrouter: true }, chosenCollapsed: true },
  });
  assert.equal(state.chosen.collapsed, true);
  assert.equal(state.chosen.count, 2);
  const openrouter = state.groups.find((g) => g.provider === "openrouter");
  assert.equal(openrouter.collapsed, true);
  assert.equal(state.groups.find((g) => g.provider === "acme").collapsed, false);
});

test("while searching every provider group opens, but 已勾選 keeps the teacher's collapse", () => {
  const box = sandbox();
  const state = view(box, {
    draft: pickedDraft(),
    ui: { query: "a", collapsed: { openrouter: true, acme: true }, chosenCollapsed: true },
  });
  assert.equal(state.groups.every((g) => g.collapsed === false), true);
  assert.equal(state.chosen.collapsed, true);
});

test("an empty group says why: no search match, or every model already checked", () => {
  const box = sandbox();
  const searching = view(box, { ui: { query: "gamma" } });
  assert.equal(searching.groups.find((g) => g.provider === "acme").empty, "沒有符合搜尋的模型");
  const draft = { models: [{ id: "acme@zeta", name: "Zeta" }], removed: {} };
  const allPicked = view(box, { draft });
  assert.equal(allPicked.groups.find((g) => g.provider === "acme").empty, "這家的模型都已經勾選");
  assert.equal(allPicked.groups.find((g) => g.provider === "openrouter").empty, "");
});

test("checking a model moves it into 已勾選 on the text shelf; unchecking sends it back", () => {
  const box = sandbox();
  const draft = pickedDraft();
  box.checkDraftTextModel(draft, "openrouter@x/gamma", true, "Gamma");
  let state = view(box, { draft });
  assert.deepEqual(state.chosen.models.map((m) => m.id), [
    "openrouter@x/delta",
    "ollama_cloud@b:cloud",
    "openrouter@x/gamma",
  ]);
  let openrouter = state.groups.find((g) => g.provider === "openrouter");
  assert.deepEqual([openrouter.picked, openrouter.rows.length], [2, 0]);
  const added = draft.models.find((m) => m.id === "openrouter@x/gamma");
  assert.equal(added.name, "Gamma");
  assert.equal(box.modelShelf(added), "text");

  box.checkDraftTextModel(draft, "openrouter@x/delta", false);
  state = view(box, { draft });
  assert.deepEqual(state.chosen.models.map((m) => m.id), ["ollama_cloud@b:cloud", "openrouter@x/gamma"]);
  openrouter = state.groups.find((g) => g.provider === "openrouter");
  assert.deepEqual(openrouter.rows.map((r) => r.id), ["openrouter@x/delta"]);
});

test("re-checking a model brings back the settings it had before it was unchecked", () => {
  const box = sandbox();
  const draft = pickedDraft();
  draft.models[0].maxOutputTokens = 1234;
  box.checkDraftTextModel(draft, "openrouter@x/delta", false);
  box.checkDraftTextModel(draft, "openrouter@x/delta", true, "Delta");
  const back = draft.models.find((m) => m.id === "openrouter@x/delta");
  assert.equal(back.name, "Delta 顯示名");
  assert.equal(back.maxOutputTokens, 1234);
});

function html(box, { draft = pickedDraft(), ui = {} } = {}) {
  const state = box.modelWizardTextShelfView({ catalog: CATALOG, providers: PROVIDERS, draft, ui });
  return box.modelWizardTextShelfHtml(state, draft, ui);
}

test("the filter row shows 全部 and each provider with its count, the active one pressed", () => {
  const box = sandbox();
  const out = html(box, { ui: { filter: "openrouter" } });
  assert.match(out, /data-text-filter=""[^>]*aria-pressed="false"[^>]*>全部 \(6\)</);
  assert.match(out, /data-text-filter="openrouter"[^>]*aria-pressed="true"[^>]*>openrouter \(3\)</);
});

test("已勾選 header shows N 個模型 and its expanded state; collapsed it hides the rows", () => {
  const box = sandbox();
  const open = html(box);
  assert.match(open, /data-text-group="__chosen__"[^>]*aria-expanded="true"[\s\S]*?已勾選[\s\S]*?2 個模型/);
  assert.match(open, /value="openrouter@x\/delta" checked/);
  const shut = html(box, { ui: { chosenCollapsed: true } });
  assert.match(shut, /data-text-group="__chosen__"[^>]*aria-expanded="false"[\s\S]*?2 個模型/);
  assert.doesNotMatch(shut, /value="openrouter@x\/delta" checked/);
});

test("a provider group header shows 已選 x／y; collapsed it hides the rows", () => {
  const box = sandbox();
  const open = html(box);
  assert.match(open, /data-text-group="openrouter"[^>]*aria-expanded="true"[\s\S]*?已選 1／3/);
  assert.match(open, /value="openrouter@x\/gamma"/);
  const shut = html(box, { ui: { collapsed: { openrouter: true } } });
  assert.match(shut, /data-text-group="openrouter"[^>]*aria-expanded="false"/);
  assert.doesNotMatch(shut, /value="openrouter@x\/gamma"/);
});

test("empty groups and an empty 已勾選 show their message", () => {
  const box = sandbox();
  const out = html(box, { draft: { models: [], removed: {} }, ui: { query: "gamma" } });
  assert.match(out, /還沒有勾選任何模型/);
  assert.match(out, /沒有符合搜尋的模型/);
});

test("names are escaped", () => {
  const box = sandbox();
  const draft = { models: [{ id: "acme@zeta", name: "<b>x</b>" }], removed: {} };
  const out = html(box, { draft });
  assert.doesNotMatch(out, /<b>x<\/b>/);
  assert.match(out, /&lt;b&gt;x&lt;\/b&gt;/);
});

test("進階設定 edits on a checked model land in the saved document", () => {
  const box = sandbox();
  const draft = pickedDraft();
  box.sessionChatModelsDraft = draft;
  const out = html(box, { draft, ui: { advancedOpen: { "openrouter@x/delta": true } } });
  assert.match(out, /<details[^>]*data-advanced="openrouter@x\/delta"[^>]*open/);
  assert.match(out, /<summary>進階設定<\/summary>/);
  const fields = [...out.matchAll(/data-model-id="openrouter@x\/delta" data-field="(\w+)"/g)].map((m) => m[1]);
  assert.deepEqual(fields.sort(), ["maxInputTokens", "maxOutputTokens", "name", "thinking"]);
  const fire = (field, value) => box.onSessionChatModelField({
    type: "input",
    target: {
      value,
      checked: value,
      getAttribute: (key) => ({ "data-model-id": "openrouter@x/delta", "data-field": field })[key],
    },
  });
  fire("name", "Delta 新名");
  fire("thinking", false);
  fire("maxInputTokens", "4096");
  fire("maxOutputTokens", "512");
  const saved = plain(box.documentFromDraft(box.sessionChatModelsDraft))[0].models
    .find((m) => m.id === "openrouter@x/delta");
  assert.equal(saved.name, "Delta 新名");
  assert.equal(saved.thinking, false);
  assert.equal(saved.maxInputTokens, 4096);
  assert.equal(saved.maxOutputTokens, 512);
});

test("the search box sits outside the re-rendered list, so typing keeps the caret", () => {
  const panel = portalHtml.match(/<section class="wizard-panel" data-wizard-panel="2"[\s\S]*?<\/section>/)[0];
  const search = panel.indexOf('id="modelWizardTextSearch"');
  const list = panel.indexOf('id="modelWizardTextShelf"');
  assert.ok(search > 0 && list > search, "search input precedes the list container");
  assert.doesNotMatch(panel.slice(list), /modelWizardTextSearch/);
  const box = sandbox();
  assert.doesNotMatch(html(box), /type="search"/);
  // Typing re-renders only the list container.
  const onSearch = extractNamedFunction(portalHtml, "onModelWizardTextSearch");
  assert.match(onSearch, /renderModelWizardTextShelf\(\)/);
  assert.doesNotMatch(onSearch, /renderSessionChatModelsList|renderModelWizardVisibility/);
});

test("Step 2 no longer parks the shared catalog columns", () => {
  const panel = portalHtml.match(/<section class="wizard-panel" data-wizard-panel="2"[\s\S]*?<\/section>/)[0];
  assert.doesNotMatch(panel, /data-wizard-slot/);
});

test("a checked model the catalog does not list is still in 已勾選, marked missing", () => {
  const box = sandbox();
  const draft = { models: [{ id: "openrouter@gone/model", name: "Gone" }], removed: {} };
  const state = view(box, { draft });
  assert.deepEqual(state.chosen.models.map((m) => [m.id, m.missing]), [["openrouter@gone/model", true]]);
});

// Drives the real open / step-change path. Every page function not listed in REAL is a
// recording stub, so the test only cares that Step 2 loads its catalog and renders.
function wiredPage() {
  const REAL = [
    "openModelWizard",
    "goToModelWizardStep",
    "renderSessionChatModelsList",
    "renderModelWizardTextShelf",
    "freshModelWizardTextUi",
    "modelWizardTextShelfView",
    "modelWizardTextShelfHtml",
    "modelWizardTextFieldsHtml",
    "escapeHtml",
    "modelShelf",
    "modelIdPrefix",
  ];
  const builtins = new Set(["Math", "Number", "String", "Array", "Set", "Map", "JSON", "Object", "Promise", "Boolean", "undefined"]);
  const calls = [];
  const elements = {};
  const element = (id) => {
    elements[id] ||= {
      id, value: "", innerHTML: "", textContent: "", hidden: false, disabled: false, scrollTop: 0,
      classList: { toggle() {}, add() {}, remove() {} },
      setAttribute() {},
    };
    return elements[id];
  };
  const store = {
    calls,
    elements,
    document: { getElementById: element, querySelector: () => null, querySelectorAll: () => [] },
    sessionChatModelsContext: { classId: 1, sessionId: 2 },
    sessionChatModelsDraft: { models: [{ id: "openrouter@x/delta", name: "Delta" }], removed: {} },
    MODEL_WIZARD_STEPS: [1, 2, 3, 4, 5, 6],
    MODEL_WIZARD_STEP_SHELVES: { 2: ["text"], 3: ["text"], 4: ["decisions"], 5: ["image"] },
    modelWizardStep: 3,
    modelWizardTextUi: { filter: "acme", query: "stale", collapsed: { openrouter: true }, chosenCollapsed: true, advancedOpen: {} },
    modelWizardTextCatalog: { models: [], unavailable: false },
    allTeacherProviders: () => PROVIDERS,
    loadModelWizardTextCatalog: async () => {
      calls.push("loadModelWizardTextCatalog");
      store.modelWizardTextCatalog = { models: CATALOG, unavailable: false };
    },
  };
  const scope = new Proxy(store, {
    has: (target, name) => typeof name === "string" && !REAL.includes(name) && !builtins.has(name),
    get: (target, name) => {
      if (name === Symbol.unscopables) return undefined;
      if (name in target) return target[name];
      return () => { calls.push(name); return undefined; };
    },
    set: (target, name, value) => { target[name] = value; return true; },
  });
  const code = REAL.map((name) => extractNamedFunction(portalHtml, name)).join("\n");
  const fns = vm.runInNewContext(
    `(function (scope) { with (scope) { ${code}\n return { ${REAL.join(", ")} }; } })`,
    {},
  )(scope);
  return { store, fns };
}

test("opening the editor loads Step 2's catalog and forgets the last filter, search and collapse", async () => {
  const { store, fns } = wiredPage();
  store.document.getElementById("modelWizardTextSearch").value = "stale";
  await fns.openModelWizard("課堂模型設定");
  assert.ok(store.calls.includes("loadModelWizardTextCatalog"));
  assert.deepEqual(plain(store.modelWizardTextUi), {
    filter: "", query: "", collapsed: {}, chosenCollapsed: false, advancedOpen: {},
  });
  assert.equal(store.elements.modelWizardTextSearch.value, "");
});

test("going to Step 2 renders the text shelf from the loaded catalog", async () => {
  const { store, fns } = wiredPage();
  await fns.openModelWizard("預設模型設定");
  await fns.goToModelWizardStep(2);
  const shelf = store.elements.modelWizardTextShelf.innerHTML;
  assert.match(shelf, /value="openrouter@x\/gamma"/);
  assert.match(shelf, /value="openrouter@x\/delta" checked/);
  assert.match(shelf, /已選 1／3/);
});

test("a draft change re-renders the text shelf while Step 2 is on screen", async () => {
  const { store, fns } = wiredPage();
  await fns.openModelWizard("課堂模型設定");
  await fns.goToModelWizardStep(2);
  store.sessionChatModelsDraft.models.push({ id: "openrouter@x/gamma", name: "Gamma" });
  fns.renderSessionChatModelsList();
  assert.match(store.elements.modelWizardTextShelf.innerHTML, /value="openrouter@x\/gamma" checked/);
});
