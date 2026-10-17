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

function makeClassList(initial = []) {
  const set = new Set(initial);
  return {
    contains: (name) => set.has(name),
    add: (name) => {
      set.add(name);
    },
    remove: (name) => {
      set.delete(name);
    },
    toggle(name, force) {
      if (force === true) {
        set.add(name);
        return true;
      }
      if (force === false) {
        set.delete(name);
        return false;
      }
      if (set.has(name)) {
        set.delete(name);
        return false;
      }
      set.add(name);
      return true;
    },
  };
}

function loadTeacherTabFns() {
  const names = [
    "filterCourses",
    "escapeHtml",
    "currentTeacherTabId",
    "placeClassroomInviteCard",
    "syncClassroomInviteCard",
    "showTab",
    "setTeacherMenuOpen",
    "syncCourseSelect",
    "refresh",
    "reloadSessionViews",
    "toggleDeviceSessions",
  ];
  const code = [
    "const TEACHER_TAB_IDS = ['inviteTab', 'keyTab', 'classTab', 'monitorTab', 'probeTab', 'adminTab'];",
    ...names.map((name) => extractNamedFunction(portalHtml, name)),
  ].join("\n");
  return { code, names };
}

function makeSandbox({ activeTab = "keyTab", selectedCourseId = "7" } = {}) {
  const tabIds = ["inviteTab", "keyTab", "classTab", "monitorTab", "probeTab", "adminTab"];
  const byId = {};
  const pageMain = {
    insertBefore(node) {
      node.parentNode = this;
      return node;
    },
  };
  for (const id of tabIds) {
    byId[id] = {
      classList: makeClassList(id === activeTab ? [] : ["hidden"]),
      appendChild(node) {
        node.parentNode = this;
        return node;
      },
    };
  }
  const navButtons = tabIds.map((id) => ({
    dataset: { tab: id },
    classList: makeClassList(id === activeTab ? ["tab-active"] : []),
  }));
  byId.navWho = { innerHTML: "" };
  byId.student = { classList: makeClassList(["hidden"]), parentNode: byId.inviteTab };
  byId.teacher = { classList: makeClassList(["hidden"]), parentNode: pageMain };
  byId.adminBtn = { classList: makeClassList(["hidden"]) };
  byId.appShell = { classList: makeClassList([]) };
  byId.teacherMenuButton = {
    setAttribute() {},
    querySelector() {
      return { className: "" };
    },
  };
  byId.teacherMenu = { inert: false };
  byId.deviceSessions = { classList: makeClassList(["hidden"]) };
  byId["sessions-panel"] = { classList: makeClassList([]) };
  byId.courseSelect = { value: selectedCourseId, innerHTML: "" };
  byId.courseStatusFilter = { value: "active" };
  byId.courseSearch = { value: "" };
  byId.courseDetail = { innerHTML: "" };

  const sandbox = {
    selectedCourseId,
    currentUserId: null,
    currentRoles: ["student"],
    teacherClasses: [],
    document: {
      getElementById(id) {
        return byId[id] ?? null;
      },
      querySelector(selector) {
        if (String(selector).includes("tab-active")) {
          return navButtons.find((btn) => btn.classList.contains("tab-active")) ?? null;
        }
        return null;
      },
      querySelectorAll(selector) {
        if (String(selector).includes("sidebar-nav-btn")) return navButtons;
        return [];
      },
    },
    async api(path) {
      if (path === "/auth/me") {
        return {
          id: 1,
          roles: ["teacher"],
          keys: [],
          classes: [{ id: 7, name: "Python 入門", status: "active", member_count: 2 }],
        };
      }
      return {};
    },
    showAppShell() {},
    window: {
      matchMedia() {
        return { matches: false };
      },
    },
    renderProfileLine() {
      return "";
    },
    renderActiveKeysSection() {},
    renderTeacherKeyMeta() {},
    renderCourseDetailPanel() {},
    syncMonitorCourseSelect() {},
    syncProbeApiKey() {},
    startUpstreamPoolsPoll() {},
    stopUpstreamPoolsPoll() {},
    enhancePortalWithWebMcp() {},
    async loadDeviceSessions() {},
    async loadClassSessions() {},
    async loadAdminClassSessions() {},
  };

  const { code } = loadTeacherTabFns();
  vm.runInNewContext(code, sandbox);
  return { sandbox, byId, navButtons };
}

function activeTab(navButtons) {
  const active = navButtons.find((btn) => btn.classList.contains("tab-active"));
  return active?.dataset.tab ?? null;
}

test("opening the teacher rail with no selected tab lands on 課堂邀請碼", () => {
  const { sandbox } = makeSandbox({ activeTab: "none" });
  assert.equal(sandbox.currentTeacherTabId(), "inviteTab");
});

test("teacher refresh keeps the invite card on 課堂邀請碼 only", async () => {
  const { sandbox, byId, navButtons } = makeSandbox({ activeTab: "inviteTab" });
  await sandbox.refresh();
  assert.equal(activeTab(navButtons), "inviteTab");
  assert.equal(byId.student.parentNode, byId.inviteTab);
  assert.equal(byId.student.classList.contains("hidden"), false);
  assert.equal(byId.inviteTab.classList.contains("hidden"), false);
  sandbox.showTab("keyTab");
  assert.equal(byId.inviteTab.classList.contains("hidden"), true);
  assert.equal(byId.keyTab.classList.contains("hidden"), false);
  assert.equal(byId.student.parentNode, byId.inviteTab);
});

test("a student without the teacher rail still gets the centered invite card", async () => {
  const { sandbox, byId } = makeSandbox({ activeTab: "inviteTab" });
  sandbox.api = async (path) => {
    if (path === "/auth/me") return { id: 2, roles: ["student"], keys: [], classes: [] };
    return {};
  };
  await sandbox.refresh();
  assert.equal(byId.teacher.classList.contains("hidden"), true);
  assert.equal(byId.student.classList.contains("hidden"), false);
  assert.equal(byId.student.parentNode, byId.teacher.parentNode);
  assert.notEqual(byId.student.parentNode, byId.inviteTab);
  await sandbox.toggleDeviceSessions();
  assert.equal(byId.student.classList.contains("hidden"), true);
  await sandbox.toggleDeviceSessions();
  assert.equal(byId.student.classList.contains("hidden"), false);
});

test("登入裝置 hides the invite card until it closes", async () => {
  const { sandbox, byId } = makeSandbox({ activeTab: "inviteTab" });
  await sandbox.refresh();
  await sandbox.toggleDeviceSessions();
  assert.equal(byId.deviceSessions.classList.contains("hidden"), false);
  assert.equal(byId.inviteTab.classList.contains("hidden"), true);
  await sandbox.toggleDeviceSessions();
  assert.equal(byId.deviceSessions.classList.contains("hidden"), true);
  assert.equal(byId.inviteTab.classList.contains("hidden"), false);
  assert.equal(byId.student.parentNode, byId.inviteTab);
});

test("teacher refresh keeps 個人 API Key when it is current", async () => {
  const { sandbox, byId, navButtons } = makeSandbox({ activeTab: "keyTab" });
  await sandbox.refresh();
  assert.equal(activeTab(navButtons), "keyTab");
  assert.equal(byId.keyTab.classList.contains("hidden"), false);
  assert.equal(byId.classTab.classList.contains("hidden"), true);
});

test("session-settings reload keeps 我的課程 when it is current", async () => {
  const { sandbox, byId, navButtons } = makeSandbox({ activeTab: "classTab" });
  await sandbox.reloadSessionViews(7);
  assert.equal(activeTab(navButtons), "classTab");
  assert.equal(byId.classTab.classList.contains("hidden"), false);
  assert.equal(byId.keyTab.classList.contains("hidden"), true);
  assert.equal(sandbox.selectedCourseId, "7");
  assert.equal(byId.courseSelect.value, "7");
});

test("prompt logging toggle does not start personal API Key", () => {
  const source = extractNamedFunction(portalHtml, "toggleSessionPromptLogging");
  assert.doesNotMatch(source, /showTab\s*\(/);
  assert.doesNotMatch(source, /\brefresh\s*\(/);
  assert.doesNotMatch(source, /\breloadSessionViews\s*\(/);
});

test("課堂設定 has a 網路搜尋 switch that patches web_search_enabled", () => {
  const cell = extractNamedFunction(portalHtml, "sessionCapabilitiesCell");
  assert.match(cell, /網路搜尋/);
  assert.match(cell, /toggleSessionWebSearch\(/);
  const source = extractNamedFunction(portalHtml, "toggleSessionWebSearch");
  assert.match(source, /method:\s*'PATCH'/);
  assert.match(source, /web_search_enabled:\s*enabled/);
  assert.doesNotMatch(source, /showTab\s*\(/);
  assert.doesNotMatch(source, /\brefresh\s*\(/);
  assert.doesNotMatch(source, /\breloadSessionViews\s*\(/);
  const state = extractNamedFunction(portalHtml, "sessionWebSearchEnabled");
  assert.match(state, /return value === true/);
});

test("我的課程 mutations do not hard-switch to personal API Key", () => {
  for (const name of ["createClass", "createSession", "disableClass", "disableClassMember"]) {
    const source = extractNamedFunction(portalHtml, name);
    assert.doesNotMatch(source, /showTab\s*\(\s*['"]keyTab['"]\s*\)/);
  }
});

test("failed class-settings saves do not switch tab", () => {
  for (const name of [
    "saveEditExpiresModal",
    "saveEditCatalogModal",
    "saveSessionChatLanguageModels",
    "beginEditSessionName",
    "beginEditSessionSeatLimit",
    "endSessionNow",
  ]) {
    const source = extractNamedFunction(portalHtml, name);
    assert.doesNotMatch(source, /showTab\s*\(/);
  }
});

test("Prompt Log model cell shows the tier name and confidence only when stored", () => {
  const code = ["escapeHtml", "renderLogModel"].map((name) => extractNamedFunction(portalHtml, name)).join("\n");
  const sandbox = {};
  vm.runInNewContext(`${code}\nthis.renderLogModel = renderLogModel;`, sandbox);
  const tiered = sandbox.renderLogModel({ model: "openrouter@vendor/strong", tier_name: "進階", tier_confidence: 0.92 });
  assert.match(tiered, /openrouter@vendor\/strong/);
  assert.match(tiered, /進階 · 0\.92/);
  const untiered = sandbox.renderLogModel({ model: "openrouter@vendor/light", tier_name: null, tier_confidence: null });
  assert.equal(untiered, "openrouter@vendor/light");
  assert.equal(sandbox.renderLogModel({ model: "x", tier_name: "<b>", tier_confidence: 1 }).includes("<b>"), false);
  assert.match(extractNamedFunction(portalHtml, "renderPromptLogs"), /renderLogModel\(item\)/);
});

function modelEditorSandbox(extra = {}) {
  const stencil = portalHtml.match(/const VCROUTER_STENCIL = \{[\s\S]*?\n {4}\};/)[0];
  const code = [
    stencil,
    ...["modelsFromDocument", "draftFromDocument", "documentFromDraft", "stencilDraftModel",
      "uploadedSessionChatModelsDraft"].map((name) => extractNamedFunction(portalHtml, name)),
  ].join("\n");
  const sandbox = { ...extra };
  vm.runInNewContext(
    `${code}\nthis.draftFromDocument = draftFromDocument;\nthis.documentFromDraft = documentFromDraft;\n` +
      "this.uploadedSessionChatModelsDraft = uploadedSessionChatModelsDraft;",
    sandbox,
  );
  return sandbox;
}

const TIERED_DOCUMENT = [{
  name: "VCRouter",
  vendor: "customendpoint",
  autoTiers: [{ id: "t-light", name: "輕量", description: "小問題" }, { id: "t-hard", name: "困難", description: "大問題" }],
  selectorShelf: ["openrouter@typesafe/jev-1.14"],
  models: [{ id: "ollama_cloud@light:cloud", name: "light", autoTier: "t-light" }],
}];

test("下載目前清單 carries the draft's tiers, selector shelf, and model tiers", () => {
  const sandbox = modelEditorSandbox();
  const out = JSON.parse(JSON.stringify(sandbox.documentFromDraft(sandbox.draftFromDocument(TIERED_DOCUMENT))));
  assert.deepEqual(out[0].autoTiers, TIERED_DOCUMENT[0].autoTiers);
  assert.deepEqual(out[0].selectorShelf, TIERED_DOCUMENT[0].selectorShelf);
  assert.equal(out[0].models[0].autoTier, "t-light");
  assert.match(extractNamedFunction(portalHtml, "downloadCurrentSessionChatModels"), /documentFromDraft\(sessionChatModelsDraft\)/);
});

test("upload asks the Portal to merge the file into the open draft", async () => {
  const calls = [];
  const sandbox = modelEditorSandbox({
    api: async (path, options) => {
      calls.push({ path, options });
      return TIERED_DOCUMENT;
    },
  });
  const draft = sandbox.draftFromDocument([]);
  const next = await sandbox.uploadedSessionChatModelsDraft(JSON.stringify(TIERED_DOCUMENT), draft);
  assert.equal(calls[0].path, "/teacher/session-chat-language-models/upload");
  assert.equal(calls[0].options.method, "POST");
  const body = JSON.parse(calls[0].options.body);
  assert.deepEqual(body.uploaded, TIERED_DOCUMENT);
  assert.equal(body.current[0].models.length, 0);
  assert.deepEqual(JSON.parse(JSON.stringify(next.autoTiers)), TIERED_DOCUMENT[0].autoTiers);
  assert.equal(next.models[0].autoTier, "t-light");

  await assert.rejects(sandbox.uploadedSessionChatModelsDraft("{", draft), /JSON 無法解析/);
  assert.equal(calls.length, 1);
});
