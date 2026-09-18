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
    "showTab",
    "syncCourseSelect",
    "refresh",
    "reloadSessionViews",
  ];
  const code = [
    "const TEACHER_TAB_IDS = ['keyTab', 'classTab', 'monitorTab', 'probeTab', 'adminTab'];",
    ...names.map((name) => extractNamedFunction(portalHtml, name)),
  ].join("\n");
  return { code, names };
}

function makeSandbox({ activeTab = "keyTab", selectedCourseId = "7" } = {}) {
  const tabIds = ["keyTab", "classTab", "monitorTab", "probeTab", "adminTab"];
  const byId = {};
  for (const id of tabIds) {
    byId[id] = { classList: makeClassList(id === activeTab ? [] : ["hidden"]) };
  }
  const navButtons = tabIds.map((id) => ({
    dataset: { tab: id },
    classList: makeClassList(id === activeTab ? ["tab-active"] : []),
  }));
  byId.navWho = { innerHTML: "" };
  byId.student = { classList: makeClassList(["hidden"]) };
  byId.teacher = { classList: makeClassList(["hidden"]) };
  byId.adminBtn = { classList: makeClassList(["hidden"]) };
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

test("first teacher refresh still lands on personal API Key", async () => {
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

test("capability toggles do not start personal API Key", () => {
  for (const name of [
    "toggleSessionImageGen",
    "toggleSessionTts",
    "toggleSessionSpeechTranscription",
    "toggleSessionPromptLogging",
  ]) {
    const source = extractNamedFunction(portalHtml, name);
    assert.doesNotMatch(source, /showTab\s*\(/);
    assert.doesNotMatch(source, /\brefresh\s*\(/);
    assert.doesNotMatch(source, /\breloadSessionViews\s*\(/);
  }
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
