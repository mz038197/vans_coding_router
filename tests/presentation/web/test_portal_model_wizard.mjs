// Step wizard for class model settings and the Router Model Template (#74, #75).
// Editor state: draft + mode + target in, step marks and Step 6 issues out.
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
  "modelEditorState",
  "modelEditorIssues",
  "modelWizardStepperHtml",
  "modelWizardIssueAnchor",
  "modelWizardIssuesHtml",
  "modelWizardShelfChoices",
  "modelWizardAllModelsShelves",
  "modelWizardStepContentShown",
  "modelWizardModeHtml",
  "modelWizardOffNoteHtml",
];

function sandbox() {
  const constants = [
    ...(portalHtml.match(/const AUTO_TIER_[A-Z_]+ = [^;]+;/g) || []),
    portalHtml.match(/const MODEL_WIZARD_STEPS = \[[\s\S]*?\n {4}\];/)[0],
    portalHtml.match(/const MODEL_WIZARD_STEP_SHELVES = \{[\s\S]*?\n {4}\};/)[0],
    portalHtml.match(/const ALL_MODELS_ASSIGNABLE_SHELVES = [^;]+;/)[0],
    portalHtml.match(/const CLASSROOM_MODEL_CHOICE_LABELS = [^;]+;/)[0],
  ];
  const code = [...constants, ...NAMES.map((name) => extractNamedFunction(portalHtml, name))].join("\n");
  const box = {};
  vm.runInNewContext(`${code}\n${NAMES.map((n) => `this.${n} = ${n};`).join("\n")}`, box);
  return box;
}

const plain = (value) => JSON.parse(JSON.stringify(value));
const JEV = "openrouter@typesafe/jev-1.14";

// A draft that runs selection: two tiers in use, a selector, every text model tiered.
function readyDraft() {
  return {
    autoTiers: [
      { id: "light", name: "輕量", description: "小問題" },
      { id: "hard", name: "困難", description: "大問題" },
    ],
    selectorShelf: [JEV],
    models: [
      { id: "ollama_cloud@a:cloud", name: "A", autoTier: "light" },
      { id: "ollama_cloud@b:cloud", name: "B", autoTier: "hard" },
      { id: JEV, name: "jev", decisionShelf: true },
      { id: "openai@gpt-image-2", name: "img", imageShelf: true },
    ],
    removed: {},
  };
}

function marks(state) {
  return Object.fromEntries(state.steps.map((step) => [step.n, step.mark]));
}

function codes(state) {
  return plain(state.issues.map((issue) => issue.code));
}

test("a ready Automatic Models sitting marks every step ✓ and can save", () => {
  const box = sandbox();
  const state = box.modelEditorState({ draft: readyDraft(), mode: "automatic", target: "session" });
  assert.deepEqual(marks(state), { 1: "ok", 2: "ok", 3: "ok", 4: "ok", 5: "ok", 6: "ok" });
  assert.deepEqual(plain(state.steps).map((s) => s.title), [
    "模式", "學生可用的模型", "分配難度", "誰來判斷難度", "其他功能", "檢查與儲存",
  ]);
  assert.deepEqual(plain(state.issues), []);
  assert.equal(state.canSave, true);
  assert.equal(state.selectionActive, true);
});

test("each save-check rule is a blocker on Step 3, pointing at its tier", () => {
  const box = sandbox();
  const cases = [
    ["tier-count", (d) => { d.autoTiers = [d.autoTiers[0]]; d.models[1].autoTier = "light"; }, undefined],
    ["tier-count", (d) => {
      for (let i = 0; i < 5; i += 1) d.autoTiers.push({ id: `x${i}`, name: `多${i}`, description: "說明" });
    }, undefined],
    ["tier-name-blank", (d) => { d.autoTiers[1].name = "   "; }, "hard"],
    ["tier-name-duplicate", (d) => { d.autoTiers[1].name = "輕量"; }, "hard"],
    ["tier-name-long", (d) => { d.autoTiers[1].name = "一".repeat(21); }, "hard"],
    ["tier-description-blank", (d) => { d.autoTiers[0].description = " "; }, "light"],
    ["tier-description-long", (d) => { d.autoTiers[0].description = "字".repeat(301); }, "light"],
    ["model-tier-missing", (d) => { d.models[0].autoTier = "gone"; }, undefined],
    ["model-untiered", (d) => { delete d.models[0].autoTier; }, undefined],
  ];
  for (const [code, edit, tierId] of cases) {
    const draft = readyDraft();
    edit(draft);
    const state = box.modelEditorState({ draft, mode: "automatic", target: "session" });
    const issue = state.issues.find((item) => item.code === code);
    assert.ok(issue, `expected ${code}, got ${codes(state)}`);
    assert.equal(issue.block, true, code);
    assert.equal(issue.step, 3, code);
    assert.equal(issue.tierId, tierId, code);
    assert.equal(state.canSave, false, code);
    assert.equal(marks(state)[3], "warn", code);
    assert.equal(marks(state)[6], "warn", code);
    assert.equal(state.selectionActive, false, code);
  }
});

test("limits count characters the way the server does, and allow exactly the limit", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.autoTiers[0].name = "😀".repeat(20);
  draft.autoTiers[0].description = "😀".repeat(300);
  const state = box.modelEditorState({ draft, mode: "automatic", target: "session" });
  assert.deepEqual(codes(state), []);
});

test("a document with no tiers yet is not refused for its tier count", () => {
  const box = sandbox();
  const draft = { models: [{ id: "ollama_cloud@a:cloud", name: "A" }], removed: {} };
  const state = box.modelEditorState({ draft, mode: "picked", target: "session" });
  assert.deepEqual(codes(state), []);
  assert.equal(state.canSave, true);
});

test("an untiered model only blocks while the selector shelf has a model", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.selectorShelf = [];
  draft.models.push({ id: "ollama_cloud@c:cloud", name: "C" });
  const state = box.modelEditorState({ draft, mode: "automatic", target: "session" });
  assert.deepEqual(codes(state), ["selector-empty"]);
  assert.equal(state.canSave, true);
});

test("reminders: an empty selector shelf (Step 4) and fewer than two tiers in use (Step 3)", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.selectorShelf = [];
  draft.models[1].autoTier = "light";
  const state = box.modelEditorState({ draft, mode: "automatic", target: "session" });
  assert.deepEqual(plain(state.issues).map((i) => [i.code, i.step, i.block]), [
    ["selector-empty", 4, false],
    ["tiers-used", 3, false],
  ]);
  assert.match(state.issues[1].text, /現在 1 個/);
  assert.equal(state.canSave, true);
  assert.equal(state.selectionActive, false);
  assert.deepEqual(marks(state), { 1: "ok", 2: "ok", 3: "warn", 4: "warn", 5: "ok", 6: "warn" });
});

test("a tier in use only counts when it holds a text-shelf model", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.models[1] = { id: "openai@tts", name: "tts", speechShelf: true, autoTier: "hard" };
  const state = box.modelEditorState({ draft, mode: "automatic", target: "session" });
  assert.deepEqual(codes(state), ["tiers-used"]);
});

test("Picked Models marks Steps 3 and 4 — and drops the selection reminders", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.selectorShelf = [];
  draft.models[1].autoTier = "light";
  const state = box.modelEditorState({ draft, mode: "picked", target: "session" });
  assert.deepEqual(marks(state), { 1: "ok", 2: "ok", 3: "off", 4: "off", 5: "ok", 6: "ok" });
  assert.deepEqual(codes(state), []);
  assert.equal(state.selectionActive, false);
  assert.equal(state.canSave, true);
});

test("a sitting with no Classroom Model Choice stored reads like Picked Models for selection", () => {
  const box = sandbox();
  const state = box.modelEditorState({ draft: readyDraft(), mode: null, target: "session" });
  assert.deepEqual(marks(state), { 1: "ok", 2: "ok", 3: "off", 4: "off", 5: "ok", 6: "ok" });
  assert.equal(state.selectionActive, false);
});

test("on Picked Models a broken tier still blocks saving and Step 3 shows ⚠", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.autoTiers[1].description = "";
  const state = box.modelEditorState({ draft, mode: "picked", target: "session" });
  assert.deepEqual(codes(state), ["tier-description-blank"]);
  assert.equal(state.canSave, false);
  assert.equal(marks(state)[3], "warn");
  assert.equal(marks(state)[4], "off");
  assert.equal(marks(state)[6], "warn");
});

test("the template always counts as Automatic Models", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.selectorShelf = [];
  const state = box.modelEditorState({ draft, mode: null, target: "template" });
  assert.deepEqual(codes(state), ["selector-empty"]);
  assert.equal(marks(state)[4], "warn");
  assert.equal(box.modelEditorState({ draft: readyDraft(), mode: null, target: "template" }).selectionActive, true);
});

test("Step 2 shows ⚠ when no text-shelf model is checked", () => {
  const box = sandbox();
  const draft = { models: [{ id: JEV, name: "jev", decisionShelf: true }], removed: {} };
  const state = box.modelEditorState({ draft, mode: "picked", target: "session" });
  assert.equal(marks(state)[2], "warn");
});

test("the step list shows each mark, the current step, and lets the teacher click any step", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.selectorShelf = [];
  const state = box.modelEditorState({ draft, mode: "automatic", target: "session" });
  const html = box.modelWizardStepperHtml(state, 4);
  assert.equal((html.match(/data-wizard-step="/g) || []).length, 6);
  assert.match(html, /data-wizard-step="4"[^>]*aria-current="step"/);
  assert.equal((html.match(/aria-current/g) || []).length, 1);
  assert.match(html, /誰來判斷難度[\s\S]*?⚠/);
  assert.match(html, /模式[\s\S]*?✓/);
  const picked = box.modelWizardStepperHtml(box.modelEditorState({ draft, mode: "picked", target: "session" }), 1);
  assert.match(picked, /分配難度[\s\S]*?—/);
});

test("Step 6 lists each issue with its blocker tag and a 去第 N 步修正 button", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.selectorShelf = [];
  draft.autoTiers[1].name = "";
  const state = box.modelEditorState({ draft, mode: "automatic", target: "session" });
  const html = box.modelWizardIssuesHtml(state);
  assert.match(html, /第 2 個難度還沒有名稱[\s\S]*?要先處理才能儲存[\s\S]*?去第 3 步修正/);
  assert.match(html, /data-wizard-jump="3" data-tier-id="hard"/);
  assert.match(html, /還沒選判斷難度的模型[\s\S]*?去第 4 步修正/);
  assert.equal((html.match(/要先處理才能儲存/g) || []).length, 1);
  const clean = box.modelEditorState({ draft: readyDraft(), mode: "automatic", target: "session" });
  assert.match(box.modelWizardIssuesHtml(clean), /沒有需要處理的問題/);
});

test("each step's catalog offers only that step's shelves", () => {
  const box = sandbox();
  const kindSplit = ["text", "decisions", "image", "embeddings", "speech", "speech_transcription"];
  assert.deepEqual(plain(box.modelWizardShelfChoices(2, kindSplit)), ["text"]);
  assert.deepEqual(plain(box.modelWizardShelfChoices(4, kindSplit)), ["decisions"]);
  assert.deepEqual(plain(box.modelWizardShelfChoices(5, kindSplit)), ["image", "embeddings", "speech", "speech_transcription"]);
  assert.deepEqual(plain(box.modelWizardShelfChoices(1, kindSplit)), []);
  assert.deepEqual(plain(box.modelWizardShelfChoices(6, kindSplit)), []);
});

test("an All Models provider lists in Step 2 onto text and in Step 5 onto speech shelves, not in Step 4", () => {
  const box = sandbox();
  assert.deepEqual(plain(box.modelWizardShelfChoices(2, ["all"])), ["all"]);
  assert.deepEqual(plain(box.modelWizardAllModelsShelves(2)), ["text"]);
  assert.deepEqual(plain(box.modelWizardShelfChoices(5, ["all"])), ["all"]);
  assert.deepEqual(plain(box.modelWizardAllModelsShelves(5)), ["speech", "speech_transcription"]);
  assert.deepEqual(plain(box.modelWizardShelfChoices(4, ["all"])), []);
});

test("Steps 3 and 4 hide their settings outside Automatic Models unless a blocker must be fixed there", () => {
  const box = sandbox();
  const picked = box.modelEditorState({ draft: readyDraft(), mode: "picked", target: "session" });
  assert.equal(box.modelWizardStepContentShown(picked, 3), false);
  assert.equal(box.modelWizardStepContentShown(picked, 4), false);
  assert.equal(box.modelWizardStepContentShown(picked, 2), true);
  const broken = readyDraft();
  delete broken.models[0].autoTier;
  const blocked = box.modelEditorState({ draft: broken, mode: "picked", target: "session" });
  assert.equal(box.modelWizardStepContentShown(blocked, 3), true);
  assert.equal(box.modelWizardStepContentShown(blocked, 4), true);
  const auto = box.modelEditorState({ draft: readyDraft(), mode: "automatic", target: "session" });
  assert.equal(box.modelWizardStepContentShown(auto, 3), true);
  const template = box.modelEditorState({ draft: readyDraft(), mode: null, target: "template" });
  assert.equal(box.modelWizardStepContentShown(template, 4), true);
});

test("Step 1 describes the mode; the template is always 自動", () => {
  const box = sandbox();
  assert.match(box.modelWizardModeHtml("template", null), /範本一律是「自動」/);
  assert.match(box.modelWizardModeHtml("session", "automatic"), /自動/);
  assert.match(box.modelWizardModeHtml("session", "picked"), /學生自選/);
  assert.match(box.modelWizardModeHtml("session", null), /還沒設定模式/);
});

test("the off note names the mode and links back to Step 1", () => {
  const box = sandbox();
  const html = box.modelWizardOffNoteHtml("picked");
  assert.match(html, /現在是「學生自選」，這一步用不到/);
  assert.match(html, /設定都保留著/);
  assert.match(html, /goToModelWizardStep\(1\)/);
  assert.match(box.modelWizardOffNoteHtml(null), /還沒設定模式/);
});

test("the editor shell: a labelled dialog, a step list, text header buttons, and a 更多 menu", () => {
  const modal = portalHtml.split('id="editSessionChatModelsModal"')[1].split("<script>")[0];
  assert.match(modal, /role="dialog" aria-modal="true"/);
  assert.match(modal, /id="modelWizardSteps" aria-label="步驟"/);
  assert.match(modal, />取消<\/button>/);
  assert.match(modal, />儲存<\/button>/);
  assert.match(modal, /aria-haspopup="menu" aria-expanded="false"[^>]*>更多/);
  for (const item of ["上傳清單…", "下載範本", "下載目前清單", "顯示模型 ID"]) {
    assert.match(modal, new RegExp(`role="menuitem"[^>]*>${item}<`));
  }
  assert.doesNotMatch(modal, /<svg/);
  for (let n = 1; n <= 6; n += 1) assert.match(modal, new RegExp(`data-wizard-panel="${n}"`));
  assert.match(modal, />上一步</);
  assert.match(modal, />下一步</);
});

test("儲存 refuses while a blocker remains and lists the blockers in a dialog", () => {
  const save = extractNamedFunction(portalHtml, "saveSessionChatLanguageModels");
  assert.match(save, /if \(!state\.canSave\) \{\s*openModelWizardDialog\(modelWizardSaveDialogHtml\(state, ''\)\);\s*return;/);
});

test("both editors open on Step 1", () => {
  const open = extractNamedFunction(portalHtml, "openModelWizard");
  assert.match(open, /modelWizardStep = 1;/);
  assert.match(extractNamedFunction(portalHtml, "beginEditRouterModelTemplate"), /openModelWizard\(/);
  assert.match(extractNamedFunction(portalHtml, "beginEditSessionChatLanguageModels"), /openModelWizard\(/);
});

test("issue text is escaped", () => {
  const box = sandbox();
  const draft = readyDraft();
  draft.autoTiers[1].name = "<b>x</b>";
  draft.autoTiers[1].description = "";
  const html = box.modelWizardIssuesHtml(box.modelEditorState({ draft, mode: "picked", target: "session" }));
  assert.doesNotMatch(html, /<b>x<\/b>/);
  assert.match(html, /&lt;b&gt;x&lt;\/b&gt;/);
});
