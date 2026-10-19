// The Router Model Template editor's entry and look (#74, #81): opened as 預設模型設定 from the
// course tab toolbar and from the 個人 API Key tab, styled apart from a sitting's editor, with a
// banner saying what the template is for.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const portalHtml = readFileSync(
  new URL("../../../src/presentation/fastapi/web/portal.html", import.meta.url),
  "utf8",
);
const portalCss = readFileSync(
  new URL("../../../src/presentation/fastapi/web/portal.css", import.meta.url),
  "utf8",
);

function extractNamedFunction(source, name) {
  const needle = `function ${name}(`;
  const at = source.indexOf(needle);
  if (at < 0) throw new Error(`missing function ${name}`);
  const start = source.slice(Math.max(0, at - 6), at) === "async " ? at - 6 : at;
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

// The markup between `<div id="${id}"` and the next top-level tab panel.
function tabMarkup(id) {
  const after = portalHtml.split(`<div id="${id}"`)[1];
  assert.ok(after, `missing tab ${id}`);
  return after.split(/<div id="\w+Tab"/)[0];
}

function onclickOf(markup, label) {
  const button = [...markup.matchAll(/<button[^>]*>([^<]*)<\/button>/g)].find((m) => m[1].trim() === label);
  assert.ok(button, `no button labelled ${label}`);
  const onclick = button[0].match(/onclick="([^"]+)"/);
  assert.ok(onclick, `button ${label} has no onclick`);
  return onclick[1];
}

// Real entry and open path; the catalog loaders, the API, and the per-step renderers that the
// open path calls are stubbed, while the shell's visibility, Step 1, and the step list run.
const REAL = [
  "beginEditRouterModelTemplate",
  "beginEditSessionChatLanguageModels",
  "openModelWizard",
  "renderModelWizardVisibility",
  "modelWizardModeHtml",
  "modelWizardOffNoteHtml",
  "modelWizardStepContentShown",
  "modelWizardStepperHtml",
  "modelWizardTarget",
  "currentModelEditorState",
  "modelEditorState",
  "modelEditorIssues",
  "autoTierLabel",
  "modelShelf",
  "modelsFromDocument",
  "draftFromDocument",
  "draftAutoSnapshot",
  "escapeHtml",
];

const STUBS = `
  let sessionChatModelsContext = null;
  let sessionChatModelsMode = null;
  let sessionChatModelsDraft = { models: [], removed: {} };
  let sessionChatModelsAutoBaseline = '';
  let sessionChatModelsLocked = false;
  let sessionChatModelsCollapsed = {};
  let routerModelTemplate = [];
  let autoTierRefusal = null;
  let modelWizardStep = 1;
  let modelWizardShowIds = false;
  let modelWizardExtraUi = null;
  let modelWizardDecisionCatalog = null;
  let modelWizardExtraCatalogs = null;
  let modelWizardTextUi = null;
  let window = { __sessionById: {} };
  const calls = [];
  async function api(path) { calls.push(path); return apiReplies[path]; }
  function ensureSessionChatModelsUploadBound() {}
  function prefillAutoTiers() {}
  async function loadAutoTierDefaults() { return null; }
  async function loadSessionChatModelsCatalog() {}
  async function loadModelWizardTextCatalog() {}
  function freshModelWizardExtraUi() { return {}; }
  function freshModelWizardTextUi() { return {}; }
  function renderModelWizardIds() {}
  function closeModelWizardMenu() {}
  function setSessionChatModelsMsg() {}
  function sessionDisplayName(session) { return session.name; }
  // Step 6 belongs to its own ticket; the status refresh here only redraws the step list.
  function refreshModelWizardStatus() {
    document.getElementById('modelWizardSteps').innerHTML = modelWizardStepperHtml(currentModelEditorState(), modelWizardStep);
  }
  function renderSessionChatModelsList() { renderModelWizardVisibility(); refreshModelWizardStatus(); }
`;

// Just enough DOM for the open path: elements found by id, hidden, classList, innerHTML.
function fakeDom(ids, panels) {
  const make = (id, attrs = {}) => {
    const classes = new Set();
    return {
      id,
      attrs,
      hidden: false,
      innerHTML: "",
      textContent: "",
      value: "",
      getAttribute: (name) => attrs[name] ?? null,
      classList: {
        add: (c) => classes.add(c),
        remove: (c) => classes.delete(c),
        contains: (c) => classes.has(c),
        toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
      },
    };
  };
  const byId = Object.fromEntries(ids.map((id) => [id, make(id)]));
  const panelEls = panels.map((n) => make(`panel${n}`, { "data-wizard-panel": String(n) }));
  return {
    byId,
    panelEls,
    getElementById: (id) => byId[id] || null,
    querySelector: () => null,
    querySelectorAll: (selector) => (selector.includes("[data-wizard-panel]") ? panelEls : []),
  };
}

function sandbox() {
  const shellIds = [...portalHtml.split('id="editSessionChatModelsModal"')[1].split("<script>")[0].matchAll(/ id="(\w+)"/g)]
    .map((m) => m[1]);
  const dom = fakeDom(["editSessionChatModelsModal", ...shellIds], [1, 2, 3, 4, 5, 6]);
  const constants = [
    ...(portalHtml.match(/const AUTO_TIER_[A-Z_]+ = [^;]+;/g) || []),
    portalHtml.match(/const MODEL_WIZARD_STEPS = \[[\s\S]*?\n {4}\];/)[0],
    portalHtml.match(/const CLASSROOM_MODEL_CHOICE_LABELS = [^;]+;/)[0],
  ];
  const box = { document: dom, apiReplies: {} };
  const code = [STUBS, ...constants, ...REAL.map((name) => extractNamedFunction(portalHtml, name))].join("\n");
  vm.runInNewContext(
    `${code}
    this.run = (source) => eval(source);
    this.state = () => JSON.stringify({ step: modelWizardStep, target: modelWizardTarget(), calls });
    this.setSessions = (sessions) => { window.__sessionById = sessions; };`,
    box,
  );
  return { box, dom };
}

const state = (box) => JSON.parse(box.state());

const TEMPLATE = [
  { name: "VCRouter", vendor: "customendpoint", models: [{ id: "ollama_cloud@a:cloud", name: "A" }] },
];

test("the course tab toolbar has a 預設模型設定 button that opens the template editor", async () => {
  const toolbar = tabMarkup("classTab").split('class="course-toolbar"')[1].split("</div>")[0];
  const onclick = onclickOf(toolbar, "預設模型設定");
  const { box, dom } = sandbox();
  box.apiReplies["/teacher/router-model-template"] = TEMPLATE;
  await box.run(onclick);
  assert.ok(dom.byId.editSessionChatModelsModal.classList.contains("show"));
  assert.ok(dom.byId.modelWizard.classList.contains("is-template"));
  assert.equal(state(box).target, "template");
  assert.equal(state(box).step, 1);
  assert.deepEqual(state(box).calls, ["/teacher/router-model-template"]);
});

test("the 個人 API Key tab keeps a 預設模型設定 button that opens the same editor", async () => {
  const onclick = onclickOf(tabMarkup("keyTab"), "預設模型設定");
  const { box, dom } = sandbox();
  box.apiReplies["/teacher/router-model-template"] = TEMPLATE;
  await box.run(onclick);
  assert.ok(dom.byId.editSessionChatModelsModal.classList.contains("show"));
  assert.equal(state(box).target, "template");
});

function bannerMarkup() {
  const modal = portalHtml.split('id="editSessionChatModelsModal"')[1].split("<script>")[0];
  const banner = modal.match(/<div[^>]*id="modelWizardTemplateBanner"[\s\S]*?<\/div>/);
  assert.ok(banner, "the editor has no template banner");
  return banner[0];
}

test("the template banner says new sittings copy it, the Personal API Key uses it, and sittings are unaffected", () => {
  const banner = bannerMarkup();
  assert.match(banner, /role="note"/);
  assert.match(banner, /新課堂建立時會複製這份設定/);
  assert.match(banner, /個人 API Key/);
  assert.match(banner, /不會影響已經建立的課堂/);
});

test("opening the template shows the banner; opening a sitting hides it again", async () => {
  const { box, dom } = sandbox();
  box.apiReplies["/teacher/router-model-template"] = TEMPLATE;
  await box.run("beginEditRouterModelTemplate()");
  assert.equal(dom.byId.modelWizardTemplateBanner.hidden, false);
  box.setSessions({ 7: { id: 7, name: "第一堂", classroom_model_choice: "picked", session_chat_language_models: TEMPLATE } });
  await box.run("beginEditSessionChatLanguageModels(3, 7)");
  assert.equal(dom.byId.modelWizardTemplateBanner.hidden, true);
  assert.equal(dom.byId.modelWizard.classList.contains("is-template"), false);
});

function stepMarks(html) {
  return Object.fromEntries(
    [...html.matchAll(/data-wizard-step="(\d)"[\s\S]*?wizard-step-mark is-(\w+)/g)].map((m) => [m[1], m[2]]),
  );
}

test("the template's Step 1 explains it is always 自動 and why, with no mode cards", async () => {
  const { box, dom } = sandbox();
  box.apiReplies["/teacher/router-model-template"] = TEMPLATE;
  await box.run("beginEditRouterModelTemplate()");
  const step1 = dom.byId.modelWizardMode.innerHTML;
  assert.match(step1, /範本一律是「自動」/);
  assert.match(step1, /個人 API Key 呼叫 vcr-auto/);
  assert.match(step1, /新課堂建立後，可以在課堂裡改成「學生自選」/);
  assert.doesNotMatch(step1, /data-mode-card/);
  assert.equal(dom.panelEls[0].hidden, false);
});

test("the template shows Steps 3 and 4 as real steps, never —", async () => {
  const { box, dom } = sandbox();
  box.apiReplies["/teacher/router-model-template"] = TEMPLATE;
  await box.run("beginEditRouterModelTemplate()");
  const marks = stepMarks(dom.byId.modelWizardSteps.innerHTML);
  assert.deepEqual(Object.keys(marks), ["1", "2", "3", "4", "5", "6"]);
  assert.notEqual(marks["3"], "off");
  assert.notEqual(marks["4"], "off");
  // A picked sitting, by contrast, reads — on both.
  box.setSessions({ 7: { id: 7, name: "第一堂", classroom_model_choice: "picked", session_chat_language_models: TEMPLATE } });
  await box.run("beginEditSessionChatLanguageModels(3, 7)");
  const sitting = stepMarks(dom.byId.modelWizardSteps.innerHTML);
  assert.equal(sitting["3"], "off");
  assert.equal(sitting["4"], "off");
});

test("the template editor is styled apart from a sitting's: its own frame, header, and banner", () => {
  assert.match(portalCss, /\.model-wizard\.is-template\s*\{[^}]*box-shadow/);
  assert.match(portalCss, /\.model-wizard\.is-template \.model-editor-header\s*\{/);
  assert.match(portalCss, /\.wizard-template-banner\s*\{/);
  assert.match(portalCss, /\.wizard-template-banner\[hidden\]\s*\{\s*display:\s*none/);
});
