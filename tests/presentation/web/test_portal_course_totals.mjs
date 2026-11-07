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
  const brace = source.indexOf("{", source.indexOf(")", at));
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

function courseTotals(items) {
  const context = {};
  vm.createContext(context);
  vm.runInContext(extractNamedFunction(portalHtml, "courseUsageTotals"), context);
  return { ...context.courseUsageTotals(items) };
}

test("a course with no members has nothing to total", () => {
  assert.deepEqual(courseTotals([]), { totalTokens: 0, requestCount: 0, activeStudents: 0, memberCount: 0 });
});

test("missing usage items count as no members", () => {
  assert.deepEqual(courseTotals(undefined), { totalTokens: 0, requestCount: 0, activeStudents: 0, memberCount: 0 });
});

test("members who never used the router count toward y but not x", () => {
  const items = [
    { user_id: 1, email: "a@example.com", total_tokens: 0, request_count: 0, sessions: [] },
    { user_id: 2, email: "b@example.com", total_tokens: 0, request_count: 0, sessions: [] },
  ];
  assert.deepEqual(courseTotals(items), { totalTokens: 0, requestCount: 0, activeStudents: 0, memberCount: 2 });
});

test("the course totals add up every member's usage, and x counts members with tokens above 0", () => {
  const items = [
    { user_id: 1, email: "a@example.com", total_tokens: 1200, request_count: 3, sessions: [] },
    { user_id: 2, email: "b@example.com", total_tokens: 0, request_count: 0, sessions: [] },
    { user_id: 3, email: "c@example.com", total_tokens: 300, request_count: 2, sessions: [] },
  ];
  assert.deepEqual(courseTotals(items), { totalTokens: 1500, requestCount: 5, activeStudents: 2, memberCount: 3 });
});
