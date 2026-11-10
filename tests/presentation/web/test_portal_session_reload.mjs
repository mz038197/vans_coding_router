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

function loadReload({ selectedCourseId, elements, meKeys = [] }) {
  const calls = { teacher: [], admin: [], monitor: [], keyRows: [], api: [], refresh: 0 };
  const context = {
    selectedCourseId,
    async api(url) {
      calls.api.push(url);
      return { keys: meKeys };
    },
    async syncMonitorSessionSelect(classId) {
      calls.monitor.push(classId);
    },
    renderActiveKeysRows(keys) {
      calls.keyRows.push(keys);
    },
    document: {
      getElementById(id) {
        return elements[id] ?? null;
      },
    },
    async loadClassSessions(classId) {
      calls.teacher.push(classId);
    },
    async loadAdminClassSessions(classId) {
      calls.admin.push(classId);
    },
    async refresh() {
      calls.refresh += 1;
    },
  };
  vm.createContext(context);
  vm.runInContext(extractNamedFunction(portalHtml, "reloadSessionViews"), context);
  return { context, calls };
}

const visiblePanel = { classList: { contains: () => false } };

test("saving a session setting reloads only that course's sessions, not the whole page", async () => {
  const { context, calls } = loadReload({
    selectedCourseId: "7",
    elements: { "sessions-panel": visiblePanel },
  });
  await context.reloadSessionViews(7);
  assert.deepEqual(calls.teacher, [7]);
  assert.equal(calls.refresh, 0);
});

test("an open admin session list reloads in place too", async () => {
  const { context, calls } = loadReload({
    selectedCourseId: "",
    elements: { "admin-sessions-7": visiblePanel },
  });
  await context.reloadSessionViews(7);
  assert.deepEqual(calls.admin, [7]);
  assert.deepEqual(calls.teacher, []);
  assert.equal(calls.refresh, 0);
});

test("the Monitor 課堂 dropdown re-syncs when it shows the edited course", async () => {
  const { context, calls } = loadReload({
    selectedCourseId: "",
    elements: { monitorClassId: { value: "7" } },
  });
  await context.reloadSessionViews(7);
  assert.deepEqual(calls.monitor, [7]);
});

test("the Monitor 課堂 dropdown is left alone when it shows another course", async () => {
  const { context, calls } = loadReload({
    selectedCourseId: "",
    elements: { monitorClassId: { value: "8" } },
  });
  await context.reloadSessionViews(7);
  assert.deepEqual(calls.monitor, []);
});

test("the active key rows re-render from /auth/me so a renamed or ended sitting shows its new state", async () => {
  const keys = [{ id: 1, session_id: 3, session_name: "第二堂" }];
  const { context, calls } = loadReload({ selectedCourseId: "", elements: {}, meKeys: keys });
  await context.reloadSessionViews(7);
  assert.deepEqual(calls.api, ["/auth/me"]);
  assert.equal(calls.keyRows.length, 1);
  assert.equal(calls.keyRows[0][0].session_name, "第二堂");
});
