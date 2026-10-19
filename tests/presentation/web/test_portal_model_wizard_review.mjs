// Step 6 of the class model settings wizard (#74, #80): the plain-words review of what
// students get, and the in-page dialogs for a blocked save and for unsaved changes.
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
  const asyncPrefix = "async ";
  const start =
    at >= asyncPrefix.length && source.slice(at - asyncPrefix.length, at) === asyncPrefix
      ? at - asyncPrefix.length
      : at;
  const brace = source.indexOf("{", start);
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
  "modelEditorState",
  "modelEditorIssues",
  "modelWizardIssueAnchor",
  "modelWizardIssuesHtml",
  "modelWizardSummaryHtml",
  "modelWizardDialogShell",
  "modelWizardSaveDialogHtml",
  "modelWizardDiscardDialogHtml",
];

function sandbox() {
  const constants = [
    ...(portalHtml.match(/const AUTO_TIER_[A-Z_]+ = [^;]+;/g) || []),
    portalHtml.match(/const MODEL_WIZARD_STEPS = \[[\s\S]*?\n {4}\];/)[0],
    portalHtml.match(/const CLASSROOM_MODEL_CHOICE_LABELS = [^;]+;/)[0],
    portalHtml.match(/const MODEL_WIZARD_EXTRA_LABELS = \{[\s\S]*?\};/)[0],
  ];
  const code = [...constants, ...NAMES.map((name) => extractNamedFunction(portalHtml, name))].join("\n");
  const box = {};
  vm.runInNewContext(`${code}\n${NAMES.map((n) => `this.${n} = ${n};`).join("\n")}`, box);
  return box;
}

// What a teacher reads: tags dropped, whitespace collapsed.
function text(html) {
  return html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

const JEV = "openrouter@typesafe/jev-1.14";
const JEV_BACKUP = "openrouter@typesafe/jev-mini";
const NAMES_BY_ID = { [JEV]: "Jev 1.14", [JEV_BACKUP]: "Jev mini" };
const nameOf = (id) => NAMES_BY_ID[id];

// Three tiers, weakest first; the text shelf in document order is A, C, B, D.
function readyDraft() {
  return {
    autoTiers: [
      { id: "light", name: "輕量", description: "小問題" },
      { id: "standard", name: "一般", description: "一般問題" },
      { id: "hard", name: "困難", description: "大問題" },
    ],
    selectorShelf: [JEV, JEV_BACKUP],
    models: [
      { id: "ollama_cloud@a:cloud", name: "A", autoTier: "light" },
      { id: "ollama_cloud@c:cloud", name: "C", autoTier: "hard" },
      { id: "ollama_cloud@b:cloud", name: "B", autoTier: "light" },
      { id: "ollama_cloud@d:cloud", name: "D", autoTier: "hard" },
      { id: "openrouter@decide", name: "決策一號", decisionShelf: true },
      { id: "openai@gpt-image-2", name: "img", imageShelf: true },
      { id: "openai@tts", name: "tts", speechShelf: true },
    ],
    removed: {},
  };
}

function summary(box, input) {
  const full = { nameOf, ...input };
  return box.modelWizardSummaryHtml(full, box.modelEditorState(full));
}

test("Automatic Models with selection running says who judges and which models each tier starts on", () => {
  const box = sandbox();
  const said = text(summary(box, { draft: readyDraft(), mode: "automatic", target: "session" }));
  assert.match(said, /自動選模會啟用/);
  assert.match(said, /學生只看到 vcr-auto/);
  assert.match(said, /Jev 1\.14 會先判斷題目難度/);
  assert.match(said, /Jev 1\.14 失敗時改用 Jev mini/);
  assert.match(said, /「輕量」的題目會先用 A，不行再用 B/);
  assert.match(said, /「困難」的題目會先用 C，不行再用 D/);
  assert.doesNotMatch(said, /「一般」的題目/);
  assert.match(said, /選中的難度沒有額度時，會先試更強的難度，再試更弱的/);
  assert.doesNotMatch(said, /還不會啟用/);
  assert.doesNotMatch(said, /去第 \d 步修正/);
});

test("Automatic Models without selection says list order and lists every reason with its step", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.selectorShelf = [];
  draft.autoTiers[0].description = "";
  const html = summary(box, { draft, mode: "automatic", target: "session" });
  const said = text(html);
  assert.match(said, /自動選模還不會啟用/);
  assert.match(said, /學生還是只看到 vcr-auto，會照清單順序用模型：A → C → B → D/);
  assert.doesNotMatch(said, /會先判斷題目難度/);
  assert.match(said, /還沒選判斷難度的模型 去第 4 步修正/);
  assert.match(said, /「輕量」還沒有難度說明 要先處理才能儲存 去第 3 步修正/);
  assert.match(html, /data-wizard-jump="3" data-tier-id="light"/);
});

test("Picked Models lists the models students see and no selection reasons", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.selectorShelf = [];
  const said = text(summary(box, { draft, mode: "picked", target: "session" }));
  assert.match(said, /學生會在 VS Code 的模型清單看到 4 個模型：A、C、B、D，自己挑/);
  assert.doesNotMatch(said, /vcr-auto/);
  assert.doesNotMatch(said, /還沒選判斷難度的模型/);
});

test("Picked Models still lists a save blocker", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.autoTiers[1].name = "";
  const said = text(summary(box, { draft, mode: "picked", target: "session" }));
  assert.match(said, /第 2 個難度還沒有名稱 要先處理才能儲存 去第 3 步修正/);
});

test("no stored mode explains the mixed behavior", () => {
  const box = sandbox();
  const said = text(summary(box, { draft: readyDraft(), mode: null, target: "session" }));
  assert.match(said, /還沒設定模式/);
  assert.match(said, /VS Code 只列出 vcr-auto，但學生也可以直接指定：A、C、B、D/);
  assert.match(said, /去第 1 步/);
});

test("the review also sums up extra features and the decision shelf", () => {
  const box = sandbox();
  const said = text(summary(box, { draft: readyDraft(), mode: "automatic", target: "session" }));
  assert.match(said, /其他功能：生圖、語音 已開啟/);
  assert.match(said, /學生自己呼叫決策模型：決策一號/);
  const bare = readyDraft();
  bare.models = bare.models.filter((model) => !model.imageShelf && !model.speechShelf && !model.decisionShelf);
  const none = text(summary(box, { draft: bare, mode: "picked", target: "session" }));
  assert.match(none, /其他功能：都沒開/);
  assert.match(none, /學生自己呼叫決策模型：關閉/);
});

test("model names are escaped", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.models[0].name = "<b>A</b>";
  const html = summary(box, { draft, mode: "picked", target: "session" });
  assert.doesNotMatch(html, /<b>A<\/b>/);
});

test("a blocked save lists each blocker, each a jump to its spot, and no reminders", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.autoTiers[1].name = "";
  delete draft.models[0].autoTier;
  const html = box.modelWizardSaveDialogHtml(box.modelEditorState({ draft, mode: "automatic", target: "session" }), "");
  const said = text(html);
  assert.match(html, /role="alertdialog"/);
  assert.match(html, /aria-modal="true"/);
  assert.match(said, /還不能儲存/);
  assert.match(said, /有 2 個地方要先處理/);
  const jumps = [...html.matchAll(/<button([^>]*)>([^<]*)<\/button>/g)]
    .filter((m) => /data-wizard-jump/.test(m[1]))
    .map((m) => ({ text: m[2], step: m[1].match(/data-wizard-jump="(\d)"/)[1], attrs: m[1] }));
  assert.equal(jumps.length, 2);
  assert.match(jumps[0].text, /第 2 個難度還沒有名稱/);
  assert.match(jumps[0].attrs, /data-tier-id="standard"/);
  assert.match(jumps[1].text, /還有 1 個模型沒分難度/);
  assert.match(jumps[1].attrs, /data-wizard-anchor="assign"/);
  assert.ok(jumps.every((jump) => jump.step === "3"));
  assert.match(said, /知道了/);
});

test("a server refusal shows in the same dialog in its own words", () => {
  const box = sandbox();
  const state = box.modelEditorState({ draft: readyDraft(), mode: "automatic", target: "session" });
  const html = box.modelWizardSaveDialogHtml(state, "難度名稱 <x> 重複");
  const said = text(html);
  assert.match(html, /role="alertdialog"/);
  assert.match(said, /沒有儲存/);
  assert.match(html, /難度名稱 &lt;x&gt; 重複/);
  assert.doesNotMatch(html, /data-wizard-jump/);
});

test("the unsaved-changes dialog offers 繼續編輯 and 捨棄修改", () => {
  const box = sandbox();
  const html = box.modelWizardDiscardDialogHtml();
  assert.match(html, /role="alertdialog"/);
  assert.match(text(html), /有尚未儲存的修改/);
  assert.match(html, /<button[^>]*onclick="closeModelWizardDialog\(\)"[^>]*>繼續編輯<\/button>/);
  assert.match(html, /<button[^>]*onclick="discardModelWizardChanges\(\)"[^>]*>捨棄修改<\/button>/);
});

test("the wizard never falls back to browser popups", () => {
  for (const name of ["requestCloseSessionChatModelsModal", "saveSessionChatLanguageModels"]) {
    const body = extractNamedFunction(portalHtml, name);
    assert.doesNotMatch(body, /window\.(confirm|alert|prompt)/, name);
  }
  assert.match(extractNamedFunction(portalHtml, "requestCloseSessionChatModelsModal"), /modelWizardDiscardDialogHtml\(\)/);
  assert.match(extractNamedFunction(portalHtml, "saveSessionChatLanguageModels"), /modelWizardSaveDialogHtml\(/);
});

test("the template counts as Automatic Models even with no mode", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.selectorShelf = [];
  const said = text(summary(box, { draft, mode: null, target: "template" }));
  assert.match(said, /自動選模還不會啟用/);
});
