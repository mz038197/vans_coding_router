// Step 3 of the class model settings wizard: edit Auto Tiers and assign each text-shelf
// model to one tier from a model x tier table (#74, #78).
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
  "draftFromDocument",
  "documentFromDraft",
  "stencilDraftModel",
  "addAutoTier",
  "autoTierHolders",
  "autoTierInUse",
  "removeAutoTier",
  "shiftAutoTier",
  "defaultForTier",
  "fillDefaultTierDescription",
  "setDraftModelTier",
  "autoTierBlockHtml",
  "modelTierTableHtml",
  "modelEditorIssues",
  "autoTierLabel",
  "modelEditorState",
  "modelWizardIssueAnchor",
  "modelWizardJumpAttrs",
  "modelWizardIssuesHtml",
];

function sandbox() {
  const constants = [
    portalHtml.match(/const VCROUTER_STENCIL = \{[\s\S]*?\n {4}\};/)[0],
    ...(portalHtml.match(/const AUTO_TIER_[A-Z_]+ = [^;]+;/g) || []),
    portalHtml.match(/const MODEL_WIZARD_STEPS = \[[\s\S]*?\n {4}\];/)[0],
  ];
  const code = [...constants, ...NAMES.map((name) => extractNamedFunction(portalHtml, name))].join("\n");
  const box = {};
  vm.runInNewContext(`${code}\n${NAMES.map((n) => `this.${n} = ${n};`).join("\n")}`, box);
  return box;
}

const plain = (value) => JSON.parse(JSON.stringify(value));

const DEFAULTS = [
  { id: "light", name: "輕量", description: "預設輕量" },
  { id: "standard", name: "一般", description: "預設一般" },
  { id: "hard", name: "困難", description: "預設困難" },
];
const JEV = "openrouter@typesafe/jev-1.14";

function draftOf(box, { tiers = plain(DEFAULTS), models, selector = [JEV] } = {}) {
  return box.draftFromDocument([{
    name: "VCRouter",
    autoTiers: tiers,
    selectorShelf: selector,
    models: models || [
      { id: "ollama_cloud@small:cloud", name: "Small", autoTier: "light" },
      { id: "ollama_cloud@mid:cloud", name: "Mid", autoTier: "standard" },
      { id: "ollama_cloud@big:cloud", name: "Big" },
      { id: JEV, name: "jev", decisionShelf: true },
    ],
  }]);
}

const tierIds = (draft) => draft.autoTiers.map((tier) => tier.id);

test("↑ 較弱 and ↓ 較強 move a tier one place and stop at either end", () => {
  const box = sandbox();
  const draft = draftOf(box);
  box.shiftAutoTier(draft, "hard", -1);
  assert.deepEqual(tierIds(draft), ["light", "hard", "standard"]);
  box.shiftAutoTier(draft, "light", -1);
  assert.deepEqual(tierIds(draft), ["light", "hard", "standard"]);
  box.shiftAutoTier(draft, "standard", 1);
  assert.deepEqual(tierIds(draft), ["light", "hard", "standard"]);
  box.shiftAutoTier(draft, "light", 1);
  assert.deepEqual(box.documentFromDraft(draft)[0].autoTiers.map((t) => t.id), ["hard", "light", "standard"]);
});

// One tier row: [name, buttons enabled by label] in screen order.
function tierRows(html) {
  return html.split('<div class="auto-tier-row"').slice(1).map((chunk) => chunk.split('class="auto-tier-add"')[0]).map((chunk) => [chunk, chunk.match(/data-tier-id="([^"]+)"/)[1]]).map((m) => ({
    id: m[1],
    number: (m[0].match(/class="auto-tier-num"[^>]*>(\d+)</) || [])[1],
    name: (m[0].match(/aria-label="難度名稱"[^>]*value="([^"]*)"/) || [])[1],
    count: (m[0].match(/data-tier-count="[^"]*">([^<]*)</) || [])[1],
    buttons: Object.fromEntries([...m[0].matchAll(/<button([^>]*)>([^<]+)<\/button>/g)].map((b) => [b[2].trim(), !/disabled/.test(b[1])])),
  }));
}

test("the tier block lists tiers weakest first with count, defaults, reorder, delete, and the accuracy note", () => {
  const box = sandbox();
  const draft = draftOf(box);
  draft.autoTiers[1].description = "𠀀字";
  const html = box.autoTierBlockHtml(draft, DEFAULTS);
  assert.match(html, /由上到下越來越強/);
  assert.match(html, /修改難度說明可能影響自動選模的準確度/);
  assert.match(html, /aria-label="難度說明"/);
  assert.doesNotMatch(html, /draggable/);
  assert.deepEqual(plain(tierRows(html)), [
    { id: "light", number: "1", name: "輕量", count: "4/300", buttons: { "填入預設": true, "↑ 較弱": false, "↓ 較強": true, "刪除": true } },
    { id: "standard", number: "2", name: "一般", count: "2/300", buttons: { "填入預設": true, "↑ 較弱": true, "↓ 較強": true, "刪除": true } },
    { id: "hard", number: "3", name: "困難", count: "4/300", buttons: { "填入預設": true, "↑ 較弱": true, "↓ 較強": false, "刪除": true } },
  ]);
  assert.match(html, /<button[^>]*onclick="onAddAutoTier\(\)"[^>]*>＋ 新增難度<\/button>/);
  assert.doesNotMatch(html, /role="alert"/);
});

test("＋ 新增難度 stops at six tiers", () => {
  const box = sandbox();
  const draft = draftOf(box);
  box.addAutoTier(draft);
  box.addAutoTier(draft);
  box.addAutoTier(draft);
  assert.equal(draft.autoTiers.length, 6);
  assert.equal(box.addAutoTier(draft), null);
  assert.equal(draft.autoTiers.length, 6);
  assert.match(box.autoTierBlockHtml(draft, DEFAULTS), /<button[^>]*disabled[^>]*>＋ 新增難度<\/button>/);
});

test("填入預設 restores the shipped text; a tier with no default has the button off", () => {
  const box = sandbox();
  const draft = draftOf(box);
  draft.autoTiers[2].description = "改過";
  box.fillDefaultTierDescription(draft, "hard", DEFAULTS);
  assert.equal(draft.autoTiers[2].description, "預設困難");
  const custom = draftOf(box, { tiers: [
    { id: "a", name: "A", description: "a" },
    { id: "b", name: "B", description: "b" },
  ] });
  const rows = tierRows(box.autoTierBlockHtml(custom, []));
  assert.deepEqual(rows.map((row) => row.buttons["填入預設"]), [false, false]);
});

// The table as a teacher reads it: headers, then per row the model, its tag, and which radio is on.
function table(html) {
  const headers = [...(html.match(/<thead>([\s\S]*?)<\/thead>/) || ["", ""])[1].matchAll(/<th[^>]*>([^<]*)<\/th>/g)].map((m) => m[1]);
  const rows = [...html.matchAll(/<tr([^>]*)>([\s\S]*?)<\/tr>/g)].filter((m) => /type="radio"/.test(m[2])).map((m) => {
    const radios = [...m[2].matchAll(/<input[^>]*type="radio"[^>]*>/g)].map((r) => r[0]);
    return {
      model: m[2].match(/<strong>([^<]*)<\/strong>/)[1],
      red: /is-untiered/.test(m[1]),
      tag: (m[2].match(/class="wizard-problem-tag">([^<]*)</) || [])[1] || null,
      picked: radios.map((r) => /checked/.test(r)),
      group: new Set(radios.map((r) => r.match(/name="([^"]*)"/)[1])).size,
    };
  });
  return { headers, rows };
}

test("the table has one row per checked text model and one radio per tier; rows with no tier are red", () => {
  const box = sandbox();
  const draft = draftOf(box);
  const view = table(box.modelTierTableHtml(draft));
  assert.deepEqual(view.headers, ["模型", "輕量", "一般", "困難"]);
  assert.deepEqual(plain(view.rows), [
    { model: "Small", red: false, tag: null, picked: [true, false, false], group: 1 },
    { model: "Mid", red: false, tag: null, picked: [false, true, false], group: 1 },
    { model: "Big", red: true, tag: "還沒分難度", picked: [false, false, false], group: 1 },
  ]);
  assert.match(box.modelTierTableHtml(draft), /aria-label="Big 分到 困難"/);
});

test("a model whose tier no longer exists is red too", () => {
  const box = sandbox();
  const draft = draftOf(box, { models: [{ id: "ollama_cloud@a:cloud", name: "A", autoTier: "gone" }] });
  const [row] = table(box.modelTierTableHtml(draft)).rows;
  assert.deepEqual(plain(row), { model: "A", red: true, tag: "難度已經不存在", picked: [false, false, false], group: 1 });
});

test("with no text model checked the table points to Step 2", () => {
  const box = sandbox();
  const draft = draftOf(box, { models: [{ id: JEV, name: "jev", decisionShelf: true }] });
  const html = box.modelTierTableHtml(draft);
  assert.equal(table(html).rows.length, 0);
  assert.match(html, /還沒有勾選學生可用的模型/);
  assert.match(html, /<button[^>]*onclick="goToModelWizardStep\(2\)"[^>]*>去第 2 步加模型<\/button>/);
});

test("picking a radio assigns the tier; the step marks and Step 6 follow at once", () => {
  const box = sandbox();
  const draft = draftOf(box);
  const before = box.modelEditorState({ draft, mode: "automatic", target: "session" });
  assert.equal(before.steps[2].mark, "warn");
  assert.ok(before.issues.some((issue) => issue.code === "model-untiered"));
  assert.equal(before.canSave, false);

  box.setDraftModelTier(draft, "ollama_cloud@big:cloud", "hard");
  const after = box.modelEditorState({ draft, mode: "automatic", target: "session" });
  assert.equal(after.steps[2].mark, "ok");
  assert.deepEqual(plain(after.issues), []);
  assert.equal(after.canSave, true);
  assert.deepEqual(table(box.modelTierTableHtml(draft)).rows[2].picked, [false, false, true]);
  const saved = box.documentFromDraft(draft)[0].models.find((m) => m.id === "ollama_cloud@big:cloud");
  assert.equal(saved.autoTier, "hard");
});

test("a decision-shelf model cannot be given a tier from the table", () => {
  const box = sandbox();
  const draft = draftOf(box);
  box.setDraftModelTier(draft, JEV, "hard");
  assert.equal(draft.models.find((m) => m.id === JEV).autoTier, undefined);
});

test("renaming a tier keeps its models in it", () => {
  const box = sandbox();
  const draft = draftOf(box);
  draft.autoTiers[0].name = "入門";
  const view = table(box.modelTierTableHtml(draft));
  assert.deepEqual(view.headers, ["模型", "入門", "一般", "困難"]);
  assert.deepEqual(view.rows[0].picked, [true, false, false]);
  const saved = box.documentFromDraft(draft)[0];
  assert.equal(saved.autoTiers[0].name, "入門");
  assert.equal(saved.models.find((m) => m.id === "ollama_cloud@small:cloud").autoTier, "light");
});

test("a tier edit refreshes the Step 6 issues: blank names block saving in every mode", () => {
  const box = sandbox();
  const draft = draftOf(box, { selector: [] });
  draft.autoTiers[1].name = "  ";
  for (const mode of ["automatic", "picked", null]) {
    const state = box.modelEditorState({ draft, mode, target: "session" });
    assert.equal(state.canSave, false, String(mode));
    assert.equal(state.steps[2].mark, "warn");
    const issue = state.issues.find((i) => i.code === "tier-name-blank");
    assert.deepEqual({ step: issue.step, tierId: issue.tierId, block: issue.block }, { step: 3, tierId: "standard", block: true });
  }
});

test("去第 3 步修正 points at the tier row, the tier list, or the table", () => {
  const box = sandbox();
  const draft = draftOf(box, {
    tiers: [{ id: "only", name: "", description: "x" }],
    models: [{ id: "ollama_cloud@a:cloud", name: "A" }],
  });
  const state = box.modelEditorState({ draft, mode: "automatic", target: "session" });
  const jumps = [...box.modelWizardIssuesHtml(state).matchAll(/<button([^>]*)>去第 (\d) 步修正<\/button>/g)].map((m) => ({
    step: m[2],
    tier: (m[1].match(/data-tier-id="([^"]*)"/) || [])[1] || null,
    anchor: (m[1].match(/data-wizard-anchor="([^"]*)"/) || [])[1] || null,
  }));
  const byCode = Object.fromEntries(state.issues.map((issue, i) => [issue.code, jumps[i]]));
  assert.deepEqual(byCode["tier-count"], { step: "3", tier: null, anchor: "tiers" });
  assert.deepEqual(byCode["tier-name-blank"], { step: "3", tier: "only", anchor: null });
  assert.deepEqual(byCode["model-untiered"], { step: "3", tier: null, anchor: "assign" });
  assert.deepEqual(byCode["tiers-used"], { step: "3", tier: null, anchor: "assign" });
  assert.deepEqual(byCode["selector-empty"], undefined);
});

test("deleting a tier that still holds models is refused and names those models", () => {
  const box = sandbox();
  const draft = draftOf(box, {
    models: [
      { id: "ollama_cloud@small:cloud", name: "Small", autoTier: "light" },
      { id: "ollama_cloud@tiny:cloud", autoTier: "light" },
      { id: "ollama_cloud@mid:cloud", name: "Mid", autoTier: "standard" },
    ],
  });
  const refused = box.removeAutoTier(draft, "light");
  assert.deepEqual(plain(refused), { removed: false, holders: ["Small", "ollama_cloud@tiny:cloud"] });
  assert.deepEqual(tierIds(draft), ["light", "standard", "hard"]);

  const html = box.autoTierBlockHtml(draft, DEFAULTS, { tierId: "light", holders: refused.holders });
  const notice = html.match(/<p[^>]*role="alert"[^>]*>([\s\S]*?)<\/p>/);
  assert.ok(notice, "the refusal is announced");
  assert.match(notice[1], /輕量[\s\S]*Small、ollama_cloud@tiny:cloud/);

  const done = box.removeAutoTier(draft, "hard");
  assert.deepEqual(plain(done), { removed: true, holders: [] });
  assert.deepEqual(tierIds(draft), ["light", "standard"]);
});
