// Step 1 of the class model settings wizard: Classroom Model Choice moves into the editor (#74, #76).
// The mode is picked from two cards, saved with the document in one PATCH, and dropped on 取消.
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

const NAMES = [
  "escapeHtml",
  "modelShelf",
  "modelsFromDocument",
  "draftAutoSnapshot",
  "modelEditorState",
  "modelEditorIssues",
  "modelWizardModeHtml",
  "modelWizardTarget",
  "currentModelEditorState",
  "setModelWizardMode",
  "isSessionChatModelsDraftDirty",
  "sessionChatModelsSaveBody",
  "sessionModelChoiceLabel",
];

// Editor globals the wizard keeps between calls; the DOM refreshers are counted, not run.
const GLOBALS = `
  let sessionChatModelsContext = null;
  let sessionChatModelsMode = null;
  let sessionChatModelsDraft = { models: [], removed: {} };
  let sessionChatModelsAutoBaseline = '';
  let routerModelTemplate = [];
  let window = { __sessionById: {} };
  const refreshed = { visibility: 0, status: 0 };
  function renderModelWizardVisibility() { refreshed.visibility += 1; }
  function refreshModelWizardStatus() { refreshed.status += 1; }
`;

function sandbox() {
  const constants = [
    ...(portalHtml.match(/const AUTO_TIER_[A-Z_]+ = [^;]+;/g) || []),
    portalHtml.match(/const MODEL_WIZARD_STEPS = \[[\s\S]*?\n {4}\];/)[0],
    portalHtml.match(/const CLASSROOM_MODEL_CHOICE_LABELS = [^;]+;/)[0],
  ];
  const code = [GLOBALS, ...constants, ...NAMES.map((name) => extractNamedFunction(portalHtml, name))].join("\n");
  const box = {};
  vm.runInNewContext(
    `${code}\n${NAMES.map((n) => `this.${n} = ${n};`).join("\n")}
    this.editor = {
      open(context, mode, session) {
        sessionChatModelsContext = context;
        sessionChatModelsMode = mode;
        window.__sessionById = session ? { [session.id]: session } : {};
        sessionChatModelsDraft = { models: modelsFromDocument(session && session.session_chat_language_models), removed: {} };
        sessionChatModelsAutoBaseline = draftAutoSnapshot(sessionChatModelsDraft);
      },
      get mode() { return sessionChatModelsMode; },
      refreshed,
    };`,
    box,
  );
  return box;
}

const plain = (value) => JSON.parse(JSON.stringify(value));

function cards(html) {
  return [...html.matchAll(/<button[^>]*data-mode-card="(\w+)"[^>]*>/g)].map((m) => ({
    mode: m[1],
    checked: /aria-checked="true"/.test(m[0]),
    radio: /role="radio"/.test(m[0]),
  }));
}

function sitting(choice) {
  return {
    id: 7,
    classroom_model_choice: choice,
    session_chat_language_models: [
      { name: "VCRouter", vendor: "customendpoint", models: [{ id: "ollama_cloud@a:cloud", name: "A" }] },
    ],
  };
}

test("Step 1 offers 自動 and 學生自選 as two radio cards, the stored one checked", () => {
  const box = sandbox();
  const html = box.modelWizardModeHtml("session", "picked");
  assert.match(html, /role="radiogroup"/);
  assert.deepEqual(cards(html), [
    { mode: "automatic", checked: false, radio: true },
    { mode: "picked", checked: true, radio: true },
  ]);
  assert.match(html, /自動[\s\S]*?vcr-auto[\s\S]*?學生自選[\s\S]*?自己挑/);
  assert.match(html, /setModelWizardMode\('automatic'\)/);
  assert.doesNotMatch(html, /還沒設定模式/);
});

test("with no Classroom Model Choice stored neither card is checked and the mixed behavior is explained", () => {
  const box = sandbox();
  const html = box.modelWizardModeHtml("session", null);
  assert.deepEqual(cards(html).map((c) => c.checked), [false, false]);
  assert.match(html, /還沒設定模式/);
  assert.match(html, /vcr-auto[\s\S]*?也可以直接指定/);
});

test("the template shows no mode cards: it is always 自動", () => {
  const box = sandbox();
  const html = box.modelWizardModeHtml("template", null);
  assert.deepEqual(cards(html), []);
  assert.match(html, /範本一律是「自動」/);
});

test("picking a card updates the step marks at once", () => {
  const box = sandbox();
  box.editor.open({ classId: 1, sessionId: 7 }, "automatic", sitting("automatic"));
  box.setModelWizardMode("picked");
  assert.equal(box.editor.mode, "picked");
  const marks = Object.fromEntries(box.currentModelEditorState().steps.map((s) => [s.n, s.mark]));
  assert.equal(marks[3], "off");
  assert.equal(marks[4], "off");
  assert.ok(box.editor.refreshed.visibility >= 1, "Steps 3 and 4 swap to the off note");
  assert.ok(box.editor.refreshed.status >= 1, "the step list follows");
  box.setModelWizardMode("automatic");
  assert.notEqual(box.currentModelEditorState().steps[2].mark, "off");
});

test("only the two modes can be picked, and never on the template", () => {
  const box = sandbox();
  box.editor.open({ classId: 1, sessionId: 7 }, null, sitting(null));
  box.setModelWizardMode("mixed");
  assert.equal(box.editor.mode, null);
  box.editor.open({ mode: "template" }, null, null);
  box.setModelWizardMode("picked");
  assert.equal(box.editor.mode, null);
});

test("a mode change alone counts as an unsaved change", () => {
  const box = sandbox();
  box.editor.open({ classId: 1, sessionId: 7 }, "automatic", sitting("automatic"));
  assert.equal(box.isSessionChatModelsDraftDirty(), false);
  box.setModelWizardMode("picked");
  assert.equal(box.isSessionChatModelsDraftDirty(), true);
  box.setModelWizardMode("automatic");
  assert.equal(box.isSessionChatModelsDraftDirty(), false);
  box.editor.open({ classId: 1, sessionId: 7 }, null, sitting(null));
  assert.equal(box.isSessionChatModelsDraftDirty(), false);
});

test("儲存 sends the mode and the document in one body; no mode picked sends no mode", () => {
  const box = sandbox();
  const doc = [{ name: "VCRouter", models: [] }];
  assert.deepEqual(plain(box.sessionChatModelsSaveBody(doc, "picked")), {
    session_chat_language_models: doc,
    classroom_model_choice: "picked",
  });
  const unset = plain(box.sessionChatModelsSaveBody(doc, null));
  assert.deepEqual(unset, { session_chat_language_models: doc });
  assert.equal("classroom_model_choice" in unset, false);
});

test("the sitting save PATCHes that body once", () => {
  const save = extractNamedFunction(portalHtml, "saveSessionChatLanguageModels");
  assert.match(save, /sessionChatModelsSaveBody\(documentFromDraft\(sessionChatModelsDraft\), sessionChatModelsMode\)/);
  assert.equal((save.match(/method: 'PATCH'/g) || []).length, 1);
});

test("the sitting row shows the mode as text, not a dropdown that saves at once", () => {
  const box = sandbox();
  assert.equal(box.sessionModelChoiceLabel(sitting("automatic")), "自動");
  assert.equal(box.sessionModelChoiceLabel(sitting("picked")), "學生自選");
  assert.equal(box.sessionModelChoiceLabel(sitting(null)), "未設定");
  const cell = extractNamedFunction(portalHtml, "sessionModelAllowlistCell");
  assert.doesNotMatch(cell, /<select/);
  assert.match(cell, /sessionModelChoiceLabel\(session\)/);
  assert.match(cell, />模型設定</);
  assert.doesNotMatch(portalHtml, /setClassroomModelChoice|sessionModelChoiceControl/);
});
