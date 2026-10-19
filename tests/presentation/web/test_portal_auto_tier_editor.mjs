// Portal editor UI for Auto Tiers and the selector shelf (ADR-0037, #73).
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
  "modelsFromDocument",
  "draftFromDocument",
  "documentFromDraft",
  "stencilDraftModel",
  "modelShelf",
  "prefillAutoTiers",
  "addAutoTier",
  "removeAutoTier",
  "shiftAutoTier",
  "autoTierHolders",
  "defaultForTier",
  "fillDefaultTierDescription",
  "autoTierInUse",
  "toggleDraftSelector",
  "draftAutoSnapshot",
  "autoTierBlockHtml",
  "autoTierLabel",
  "sessionAutoSelectionBadge",
];

function sandbox() {
  const stencil = portalHtml.match(/const VCROUTER_STENCIL = \{[\s\S]*?\n {4}\};/)[0];
  const limits = portalHtml.match(/const AUTO_TIER_[A-Z_]+ = [^;]+;/g) || [];
  const code = [stencil, ...limits, ...NAMES.map((name) => extractNamedFunction(portalHtml, name))].join("\n");
  const box = {};
  vm.runInNewContext(`${code}\n${NAMES.map((n) => `this.${n} = ${n};`).join("\n")}`, box);
  return box;
}

const plain = (value) => JSON.parse(JSON.stringify(value));

// What a teacher reads: text between tags plus title and aria-label values.
function userFacingText(html) {
  const labels = [...html.matchAll(/(?:title|aria-label)="([^"]*)"/g)].map((m) => m[1]);
  return [html.replace(/<[^>]*>/g, " "), ...labels].join(" ");
}

const DEFAULTS = [
  { id: "light", name: "輕量", description: "預設輕量" },
  { id: "standard", name: "一般", description: "預設一般" },
  { id: "hard", name: "困難", description: "預設困難" },
];
const JEV = "openrouter@typesafe/jev-1.14";

function tieredDraft(box) {
  return box.draftFromDocument([{
    name: "VCRouter",
    autoTiers: [
      { id: "t-light", name: "輕量", description: "小問題" },
      { id: "t-hard", name: "困難", description: "大問題" },
    ],
    selectorShelf: [JEV],
    models: [
      { id: "ollama_cloud@light:cloud", name: "light", autoTier: "t-light" },
      { id: "ollama_cloud@strong:cloud", name: "strong" },
      { id: JEV, name: "jev", decisionShelf: true },
    ],
  }]);
}

test("a document without tiers opens with the default tiers; one with tiers keeps its own", () => {
  const box = sandbox();
  const empty = box.draftFromDocument([{ name: "VCRouter", models: [] }]);
  box.prefillAutoTiers(empty, DEFAULTS);
  assert.deepEqual(plain(empty.autoTiers), DEFAULTS);
  empty.autoTiers[0].name = "改過";
  assert.equal(DEFAULTS[0].name, "輕量");

  const tiered = tieredDraft(box);
  box.prefillAutoTiers(tiered, DEFAULTS);
  assert.deepEqual(plain(tiered.autoTiers).map((t) => t.id), ["t-light", "t-hard"]);
});

test("teacher adds, removes, and reorders tiers; the saved document keeps that order", () => {
  const box = sandbox();
  const draft = tieredDraft(box);
  const added = box.addAutoTier(draft);
  assert.equal(draft.autoTiers.length, 3);
  assert.equal(draft.autoTiers[2].id, added.id);
  assert.ok(!["t-light", "t-hard"].includes(added.id));

  box.shiftAutoTier(draft, added.id, -1);
  box.shiftAutoTier(draft, added.id, -1);
  assert.deepEqual(draft.autoTiers.map((t) => t.id), [added.id, "t-light", "t-hard"]);

  box.removeAutoTier(draft, added.id);
  const saved = box.documentFromDraft(draft);
  assert.deepEqual(saved[0].autoTiers.map((t) => t.id), ["t-light", "t-hard"]);
});

test("a tier that a model still uses cannot be removed", () => {
  const box = sandbox();
  const draft = tieredDraft(box);
  assert.equal(box.autoTierInUse(draft, "t-light"), true);
  assert.equal(box.autoTierInUse(draft, "t-hard"), false);
  box.removeAutoTier(draft, "t-light");
  assert.deepEqual(draft.autoTiers.map((t) => t.id), ["t-light", "t-hard"]);
});

test("填入預設 puts the current default text back for that tier", () => {
  const box = sandbox();
  const draft = box.draftFromDocument([{ autoTiers: plain(DEFAULTS), models: [] }]);
  draft.autoTiers[1].description = "老師改過";
  box.fillDefaultTierDescription(draft, "standard", DEFAULTS);
  assert.equal(draft.autoTiers[1].description, "預設一般");
});

test("the tier block lists tiers weakest first with limits, defaults, and the accuracy hint", () => {
  const box = sandbox();
  const draft = tieredDraft(box);
  const html = box.autoTierBlockHtml(draft, DEFAULTS);
  assert.match(html, /由上到下越來越強/);
  assert.match(html, /修改難度說明可能影響自動選模的準確度/);
  assert.match(html, /填入預設/);
  assert.match(html, /新增難度/);
  assert.match(html, /aria-label="難度名稱"/);
  assert.match(html, /aria-label="難度說明"/);
  assert.doesNotMatch(userFacingText(html), /Tier/);
  assert.match(html, /maxlength="300"/);
  assert.match(html, /maxlength="20"/);
  assert.match(html, /3\/300/);
  assert.ok(html.indexOf("輕量") < html.indexOf("困難"));
});

test("the selector shelf toggles on its own and keeps the decision shelf as it was", () => {
  const box = sandbox();
  const draft = tieredDraft(box);
  box.toggleDraftSelector(draft, JEV, false);
  box.toggleDraftSelector(draft, "openrouter@other/judge", true);
  box.toggleDraftSelector(draft, "openrouter@other/judge", true);
  assert.deepEqual(plain(box.documentFromDraft(draft)[0].selectorShelf), ["openrouter@other/judge"]);
  assert.equal(draft.models.find((m) => m.id === JEV).decisionShelf, true);
});

test("unsaved-changes check covers tiers, model tiers, and the selector shelf", () => {
  const box = sandbox();
  const draft = tieredDraft(box);
  const before = box.draftAutoSnapshot(draft);
  draft.autoTiers[0].description = "改了";
  assert.notEqual(box.draftAutoSnapshot(draft), before);
  draft.autoTiers[0].description = "小問題";
  draft.models[1].autoTier = "t-hard";
  assert.notEqual(box.draftAutoSnapshot(draft), before);
  delete draft.models[1].autoTier;
  box.toggleDraftSelector(draft, JEV, false);
  assert.notEqual(box.draftAutoSnapshot(draft), before);
  box.toggleDraftSelector(draft, JEV, true);
  assert.equal(box.draftAutoSnapshot(draft), before);
  assert.match(extractNamedFunction(portalHtml, "isSessionChatModelsDraftDirty"), /draftAutoSnapshot/);
});

test("class list shows 「自動選模」 only when the row says selection runs", () => {
  const box = sandbox();
  assert.match(box.sessionAutoSelectionBadge({ auto_selection_active: true }), /自動選模/);
  assert.doesNotMatch(userFacingText(box.sessionAutoSelectionBadge({ auto_selection_active: true })), /Tier/);
  assert.equal(box.sessionAutoSelectionBadge({ auto_selection_active: false }), "");
  assert.equal(box.sessionAutoSelectionBadge({}), "");
  assert.match(extractNamedFunction(portalHtml, "sessionModelAllowlistCell"), /sessionAutoSelectionBadge\(session\)/);
});

test("a refused save shows the server's reason", () => {
  const save = extractNamedFunction(portalHtml, "saveSessionChatLanguageModels");
  assert.match(save, /modelWizardSaveDialogHtml\(state, err\?\.message/);
});
