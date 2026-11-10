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

function loadCourseCards() {
  const names = ["sessionInProgressAt", "courseCardDefaultOpenIds", "shouldAutoRefreshCourseCard"];
  const context = {};
  vm.createContext(context);
  vm.runInContext(names.map((name) => extractNamedFunction(portalHtml, name)).join("\n"), context);
  return context;
}

const NOW = Date.parse("2026-11-05T10:00:00Z");

// Newest first, as GET /teacher/classes/{id}/sessions returns them.
const tomorrow = { id: 14, session_at: "2026-11-06T09:00:00Z", expires_at: "2026-11-06T11:00:00Z" };
const live = { id: 13, session_at: "2026-11-05T09:00:00Z", expires_at: "2026-11-05T11:00:00Z" };
const lastWeek = { id: 12, session_at: "2026-10-29T09:00:00Z", expires_at: "2026-10-29T11:00:00Z" };
const older = { id: 11, session_at: "2026-10-22T09:00:00Z", expires_at: "2026-10-22T11:00:00Z" };

function openIds(sessions, options = {}) {
  const { courseCardDefaultOpenIds } = loadCourseCards();
  return Array.from(courseCardDefaultOpenIds(sessions, { courseStatus: "active", now: NOW, ...options }));
}

test("the in-progress Class Session's card opens by default", () => {
  assert.deepEqual(openIds([tomorrow, live, lastWeek]), [13]);
});

test("with nothing in progress, the most recent Class Session's card opens", () => {
  assert.deepEqual(openIds([lastWeek, older]), [12]);
});

test("with nothing in progress, the most recent sitting that has started opens, not an upcoming one", () => {
  assert.deepEqual(openIds([tomorrow, lastWeek, older]), [12]);
});

test("a sitting without session_at has started at its created_at", () => {
  const unscheduled = { id: 15, session_at: null, created_at: "2026-11-01T08:00:00Z", expires_at: "2026-11-01T09:00:00Z" };
  assert.deepEqual(openIds([tomorrow, unscheduled, lastWeek]), [15]);
});

test("when every sitting is upcoming, the top card opens", () => {
  const nextWeek = { id: 15, session_at: "2026-11-12T09:00:00Z", expires_at: "2026-11-12T11:00:00Z" };
  assert.deepEqual(openIds([nextWeek, tomorrow]), [15]);
});

test("once the course has ended nothing is in progress, so the most recent started sitting opens", () => {
  assert.deepEqual(openIds([tomorrow, live, lastWeek], { courseStatus: "ended" }), [13]);
});

test("cards saved in localStorage stay open alongside the default", () => {
  assert.deepEqual(openIds([tomorrow, live, lastWeek, older], { saved: [11, "12"] }), [13, 12, 11]);
});

test("saved cards for Class Sessions that no longer exist are dropped", () => {
  assert.deepEqual(openIds([live, lastWeek], { saved: [99, 12] }), [13, 12]);
});

test("a newly created Class Session's card opens", () => {
  assert.deepEqual(openIds([tomorrow, live, lastWeek], { createdId: 14 }), [14, 13]);
});

test("no Class Sessions means no open cards", () => {
  assert.deepEqual(openIds([], { saved: [12], createdId: 14 }), []);
});

function due(open, inProgress, focusedTag) {
  const { shouldAutoRefreshCourseCard } = loadCourseCards();
  return shouldAutoRefreshCourseCard({ open, inProgress, focusedTag });
}

test("an open, in-progress card refreshes when nothing is focused", () => {
  assert.equal(due(true, true, null), true);
  assert.equal(due(true, true, "BODY"), true);
  assert.equal(due(true, true, "BUTTON"), true);
});

test("an open, in-progress card pauses while an input, select or textarea has focus", () => {
  for (const tag of ["INPUT", "SELECT", "TEXTAREA", "input"]) {
    assert.equal(due(true, true, tag), false, tag);
  }
});

test("a closed card never auto-refreshes", () => {
  assert.equal(due(false, true, null), false);
  assert.equal(due(false, true, "INPUT"), false);
  assert.equal(due(false, false, null), false);
  assert.equal(due(false, false, "TEXTAREA"), false);
});

test("a card that is not in progress never auto-refreshes", () => {
  assert.equal(due(true, false, null), false);
  assert.equal(due(true, false, "SELECT"), false);
});

test("in progress means started, not expired, and the course not ended", () => {
  const { sessionInProgressAt } = loadCourseCards();
  assert.equal(sessionInProgressAt(live, "active", NOW), true);
  assert.equal(sessionInProgressAt(tomorrow, "active", NOW), false);
  assert.equal(sessionInProgressAt(lastWeek, "active", NOW), false);
  assert.equal(sessionInProgressAt(live, "ended", NOW), false);
  assert.equal(sessionInProgressAt({ id: 1, session_at: null, expires_at: null }, "active", NOW), true);
});

// The card summary row: its status tag and how a click on it decides whether to toggle.
function loadSummaryRow() {
  const names = [
    "isSessionExpired",
    "isSessionUpcoming",
    "isSessionActive",
    "sessionStatusCell",
    "onCourseCardSummaryClick",
  ];
  const toggled = [];
  const context = { toggled, toggleCourseCard: (classId, sessionId) => toggled.push([classId, sessionId]) };
  vm.createContext(context);
  vm.runInContext(names.map((name) => extractNamedFunction(portalHtml, name)).join("\n"), context);
  return context;
}

const HOUR = 3600 * 1000;
const isoFromNow = (ms) => new Date(Date.now() + ms).toISOString();
const running = { id: 21, session_at: isoFromNow(-HOUR), expires_at: isoFromNow(HOUR) };
const notStarted = { id: 22, session_at: isoFromNow(HOUR), expires_at: isoFromNow(2 * HOUR) };
const finished = { id: 23, session_at: isoFromNow(-3 * HOUR), expires_at: isoFromNow(-HOUR) };

test("the status tag of a running or upcoming sitting ends it; an ended one reopens it", () => {
  const { sessionStatusCell } = loadSummaryRow();
  const runningTag = sessionStatusCell(7, running, "active");
  assert.match(runningTag, /進行中/);
  assert.match(runningTag, /endSessionNow\(7, 21\)/);
  assert.match(runningTag, /data-session-status="21"/);
  const notStartedTag = sessionStatusCell(7, notStarted, "active");
  assert.match(notStartedTag, /未開始/);
  assert.match(notStartedTag, /endSessionNow\(7, 22\)/);
  const finishedTag = sessionStatusCell(7, finished, "active");
  assert.match(finishedTag, /已結束/);
  assert.match(finishedTag, /beginEditSessionExpires\(7, 23\)/);
});

test("once the course has ended, the status tag is plain text", () => {
  const { sessionStatusCell } = loadSummaryRow();
  const tag = sessionStatusCell(7, running, "ended");
  assert.match(tag, /^<span class="tag tag-ended"/);
  assert.doesNotMatch(tag, /onclick/);
});

function summaryClick({ onControl = false, renaming = false } = {}) {
  const context = loadSummaryRow();
  const event = {
    target: { closest: () => (onControl ? {} : null) },
    currentTarget: { querySelector: () => (renaming ? {} : null) },
  };
  context.onCourseCardSummaryClick(event, 7, 21);
  return context.toggled;
}

test("a click on empty summary-row space toggles the card", () => {
  assert.deepEqual(summaryClick(), [[7, 21]]);
});

test("a click on the pencil, the status tag or the rename input does not toggle the card", () => {
  assert.deepEqual(summaryClick({ onControl: true }), []);
});

test("while a rename is open, a click on the summary row does not toggle the card", () => {
  assert.deepEqual(summaryClick({ renaming: true }), []);
});

// A Course Card's latest logs: each log's meta row names the model that served it.
function loadCourseCardLogs() {
  const names = [
    "escapeHtml",
    "modelIdPrefix",
    "upstreamLogoHtml",
    "shortModelName",
    "courseCardLogModelTag",
    "renderCourseCardLogs",
  ];
  const context = {
    COURSE_CARD_LOG_LIMIT: 10,
    formatLogPreview: (item) => item.message_preview || "",
    formatLocalDateTime: () => "TIME",
    formatTokenCount: (value) => String(value),
    renderLogEndpointTag: () => "<span class=\"tag\">responses</span>",
  };
  vm.createContext(context);
  vm.runInContext(names.map((name) => extractNamedFunction(portalHtml, name)).join("\n"), context);
  return context;
}

const namedSession = {
  session_chat_language_models: [
    { provider: "openrouter", models: [{ id: "openrouter@z-ai/glm-5.3-flash", name: "GLM 5.3 Flash - OR" }] },
  ],
};

function logRow(model, extra = {}) {
  return { user_name: "Vans", message_preview: "hi", created_at: "x", total_tokens: 634, status: "ok", model, ...extra };
}

test("a log served by a model the teacher named shows its upstream logo and that name, full id on hover", () => {
  const { renderCourseCardLogs } = loadCourseCardLogs();
  const html = renderCourseCardLogs([logRow("openrouter@z-ai/glm-5.3-flash")], "", namedSession);
  assert.match(html, /upstream-logo-openrouter/);
  assert.match(html, />GLM 5\.3 Flash - OR</);
  assert.match(html, /title="openrouter@z-ai\/glm-5\.3-flash"/);
});

test("a log served by a model the teacher did not name shows the short form of its id", () => {
  const { renderCourseCardLogs } = loadCourseCardLogs();
  const html = renderCourseCardLogs(
    [logRow("ollama_cloud@deepseek-v4.1-flash:1017"), logRow("openrouter@minimax/minimax-m3")],
    "",
    namedSession,
  );
  assert.match(html, /upstream-logo-ollama[^]*>deepseek-v4\.1-flash 1017</);
  assert.match(html, /upstream-logo-openrouter[^]*>minimax-m3</);
});

test("a rejected log reached no model, so it has no model tag", () => {
  const { renderCourseCardLogs } = loadCourseCardLogs();
  const html = renderCourseCardLogs([logRow("vcr-auto", { status: "rejected" })], "", namedSession);
  assert.doesNotMatch(html, /course-card-log-model/);
  assert.match(html, /rejected/);
});
