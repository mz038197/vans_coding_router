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

function loadEndCourse({ userId, roles, classes = [], confirmAnswer = true }) {
  const calls = { confirm: [], api: [], refresh: 0 };
  const context = {
    currentUserId: userId,
    currentRoles: roles,
    teacherClasses: classes,
    window: {
      confirm(message) {
        calls.confirm.push(message);
        return confirmAnswer;
      },
    },
    async api(url, options) {
      calls.api.push({ url, options });
      return {};
    },
    async refresh() {
      calls.refresh += 1;
    },
  };
  vm.createContext(context);
  for (const name of ["endCourseButtonHtml", "endCourse"]) {
    vm.runInContext(extractNamedFunction(portalHtml, name), context);
  }
  return { context, calls };
}

const ownCourse = { id: 7, name: "AI 入門", status: "active", teacher_id: 1 };

test("the course owner sees 結束課程", () => {
  const { context } = loadEndCourse({ userId: 1, roles: ["teacher"] });
  assert.match(context.endCourseButtonHtml(ownCourse), /結束課程/);
});

test("an admin sees 結束課程", () => {
  const { context } = loadEndCourse({ userId: 99, roles: ["admin"] });
  assert.match(context.endCourseButtonHtml(ownCourse), /結束課程/);
});

test("another teacher does not see 結束課程", () => {
  const { context } = loadEndCourse({ userId: 2, roles: ["teacher"] });
  assert.equal(context.endCourseButtonHtml(ownCourse), "");
});

test("an ended course shows no 結束課程", () => {
  const { context } = loadEndCourse({ userId: 1, roles: ["teacher"] });
  assert.equal(context.endCourseButtonHtml({ ...ownCourse, status: "ended" }), "");
});

test("declining the confirm sends nothing", async () => {
  const { context, calls } = loadEndCourse({
    userId: 1,
    roles: ["teacher"],
    classes: [ownCourse],
    confirmAnswer: false,
  });
  await context.endCourse(7);
  assert.equal(calls.confirm.length, 1);
  assert.match(calls.confirm[0], /結束後學生無法再用邀請碼加入，只有管理員能重新開啟/);
  assert.deepEqual(calls.api, []);
});

test("the owner's confirmed end goes to the teacher endpoint", async () => {
  const { context, calls } = loadEndCourse({
    userId: 1,
    roles: ["teacher"],
    classes: [ownCourse],
  });
  await context.endCourse(7);
  assert.equal(calls.api.length, 1);
  assert.equal(calls.api[0].url, "/teacher/classes/7");
  assert.equal(calls.api[0].options.method, "PATCH");
  assert.deepEqual(JSON.parse(calls.api[0].options.body), { status: "ended" });
  assert.equal(calls.refresh, 1);
});

test("an admin ending someone else's course goes to the admin endpoint", async () => {
  const { context, calls } = loadEndCourse({
    userId: 99,
    roles: ["admin"],
    classes: [ownCourse],
  });
  await context.endCourse(7);
  assert.equal(calls.api[0].url, "/admin/classes/7");
});
