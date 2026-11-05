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

function loadKpi() {
  const names = [
    "escapeHtml",
    "formatIncludedMonthlyUsage",
    "formatAccountCreditRemaining",
    "upstreamKpiStatus",
    "upstreamKpiQuarantineMinutes",
    "upstreamKpiUsedFraction",
    "upstreamKpiMonthlyUsageParts",
    "upstreamKpiCredit",
    "upstreamKpiSparkline",
    "upstreamKpiTilesHtml",
    "upstreamKpiLineHtml",
    "readUpstreamKpiCollapsed",
    "writeUpstreamKpiCollapsed",
    "upstreamKpiCollapseState",
  ];
  const context = {};
  vm.createContext(context);
  vm.runInContext(names.map((name) => extractNamedFunction(portalHtml, name)).join("\n"), context);
  return context;
}

const NOW = Date.parse("2026-11-05T00:00:00Z");
const IN_9_DAYS = "2026-11-14T00:00:00Z";

// Included Monthly Usage as the pool status reports it (src/domain/extra_usage.py).
function monthlyUsage(used, included) {
  const dollars = (n) => (Number.isInteger(n) ? String(n) : n.toFixed(2));
  return {
    used_usd: used,
    included_usd: included,
    resets_at: IN_9_DAYS,
    summary: `$${dollars(used)} of $${dollars(included)} used`,
    resets: "Resets in 9 days.",
  };
}

function ollamaKey(overrides = {}) {
  return {
    index: 0,
    label: "ollama_cloud#0",
    cap: 3,
    in_flight: 1,
    quarantined: false,
    quarantine_remaining_sec: null,
    included_monthly_usage: monthlyUsage(12.4, 60),
    ...overrides,
  };
}

function openrouterKey(overrides = {}) {
  return {
    index: 0,
    label: "openrouter#0",
    cap: 4,
    in_flight: 0,
    quarantined: false,
    quarantine_remaining_sec: null,
    account_credit_remaining: 23.5,
    ...overrides,
  };
}

function providers({ ollamaKeys = [ollamaKey()], openrouterKeys = [openrouterKey()], waiting = 0 } = {}) {
  return {
    ollama_cloud: { pool: { capacity: 6, in_flight_total: 1, waiting, keys: ollamaKeys } },
    openrouter: { pool: { capacity: 8, in_flight_total: 0, waiting: 0, keys: openrouterKeys } },
  };
}

function tiles(html) {
  return html.split('<div class="upstream-kpi').slice(1);
}

test("a healthy Ollama key tile shows $X of $Y used, a meter, Resets in … and its concurrency", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const html = upstreamKpiTilesHtml(providers(), [], NOW);
  const ollama = tiles(html)[0];

  assert.match(ollama, /Ollama #0/);
  assert.match(ollama, /\$12\.40 of \$60 used/);
  assert.match(ollama, /<div class="meter"><i style="width:21%"><\/i><\/div>/);
  assert.match(ollama, /Resets in 9 days\. · 併發 1\/3/);
  assert.doesNotMatch(ollama, /\d%<|月用量 \d|天後重置/);
  assert.doesNotMatch(ollama, /upstream-kpi-status/);
  assert.doesNotMatch(ollama, /meter warn/);
});

function statuses(tile) {
  return [
    ...tile.matchAll(
      /<span class="upstream-kpi-status"><i class="fas fa-[a-z-]+" aria-hidden="true"><\/i>([^<]+)<\/span>/g,
    ),
  ].map((m) => m[1]);
}

test("an Ollama key at 90% of Included Monthly Usage shows 快用完 with an icon and reset days", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const key = ollamaKey({ included_monthly_usage: monthlyUsage(54, 60) });
  const ollama = tiles(upstreamKpiTilesHtml(providers({ ollamaKeys: [key] }), [], NOW))[0];

  assert.deepEqual(statuses(ollama), ["快用完"]);
  assert.match(ollama, /\$54 of \$60 used/);
  assert.match(ollama, /Resets in 9 days\./);
  assert.match(ollama, /meter warn/);
});

test("an Ollama key just under 90% has no warning", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const key = ollamaKey({ included_monthly_usage: monthlyUsage(53.9, 60) });
  const ollama = tiles(upstreamKpiTilesHtml(providers({ ollamaKeys: [key] }), [], NOW))[0];

  assert.deepEqual(statuses(ollama), []);
});

test("an Ollama key without Included Monthly Usage says it is unavailable instead of drawing numbers", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const key = ollamaKey({ included_monthly_usage: null });
  const ollama = tiles(upstreamKpiTilesHtml(providers({ ollamaKeys: [key] }), [], NOW))[0];

  assert.match(ollama, /月用量無法取得/);
  assert.match(ollama, /併發 1\/3/);
  assert.doesNotMatch(ollama, /NaN|null|undefined/);
  assert.doesNotMatch(ollama, /class="meter/);
});

function releaseButtons(tile) {
  return [
    ...tile.matchAll(
      /<button type="button" class="btn-secondary upstream-quarantine-release" data-provider="([^"]+)" data-index="(\d+)">解除隔離<\/button>/g,
    ),
  ].map((m) => `${m[1]}|${m[2]}`);
}

test("a quarantined Ollama key shows 隔離中 N 分 with an icon and a Quarantine Release button", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const key = ollamaKey({
    index: 1,
    quarantined: true,
    quarantine_remaining_sec: 1840,
    included_monthly_usage: monthlyUsage(58, 60),
  });
  const ollama = tiles(upstreamKpiTilesHtml(providers({ ollamaKeys: [key] }), [], NOW))[0];

  assert.deepEqual(statuses(ollama), ["隔離中 31 分"]);
  assert.deepEqual(releaseButtons(ollama), ["ollama_cloud|1"]);
});

test("a quarantined OpenRouter key shows 隔離中 N 分 and a Quarantine Release button on the credit tile", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [openrouterKey(), openrouterKey({ index: 1, quarantined: true, quarantine_remaining_sec: 60 })];
  const openrouter = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys }), [], NOW))[1];

  assert.deepEqual(statuses(openrouter), ["#1 隔離中 1 分"]);
  assert.deepEqual(releaseButtons(openrouter), ["openrouter|1"]);
});

test("OpenRouter Account Credit Remaining at $5 or more is shared credit with no warning", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [openrouterKey({ account_credit_remaining: 5 }), openrouterKey({ index: 1, account_credit_remaining: 5 })];
  const openrouter = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys }), [], NOW))[1];

  assert.match(openrouter, /餘額 \$5\.00/);
  assert.match(openrouter, /2 把 key/);
  assert.match(openrouter, /帳號共用額度/);
  assert.deepEqual(statuses(openrouter), []);
});

test("an OpenRouter tile with no Account Credit Remaining says it is unavailable", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [openrouterKey({ account_credit_remaining: null })];
  const openrouter = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys }), [], NOW))[1];

  assert.match(openrouter, /餘額無法取得/);
  assert.doesNotMatch(openrouter, /NaN|null|undefined|—/);
});

test("OpenRouter Account Credit Remaining below $5 shows 餘額偏低 with an icon", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [openrouterKey({ account_credit_remaining: 4.3 })];
  const openrouter = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys }), [], NOW))[1];

  assert.match(openrouter, /餘額 \$4\.30/);
  assert.deepEqual(statuses(openrouter), ["餘額偏低"]);
});

test("the concurrency tile shows in-flight / capacity and 無排隊 when nothing waits", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const concurrency = tiles(upstreamKpiTilesHtml(providers(), [], NOW))[2];

  assert.match(concurrency, /併發/);
  assert.match(concurrency, /1<small>\/ 14<\/small>/);
  assert.match(concurrency, /無排隊/);
  assert.match(concurrency, /Ollama 1\/6 · OpenRouter 0\/8/);
  assert.deepEqual(statuses(concurrency), []);
});

test("the concurrency tile shows 排隊 N with an icon when requests wait", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const concurrency = tiles(upstreamKpiTilesHtml(providers({ waiting: 3 }), [], NOW))[2];

  assert.deepEqual(statuses(concurrency), ["排隊 3"]);
});

test("the concurrency sparkline draws recent samples with the latest point in the accent line", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const concurrency = tiles(upstreamKpiTilesHtml(providers(), [0, 2, 4], NOW))[2];

  const lines = [...concurrency.matchAll(/<polyline( class="now")? points="([^"]+)"/g)];
  assert.equal(lines.length, 2);
  assert.equal(lines[0][1], undefined);
  assert.equal(lines[0][2].split(" ").length, 3);
  assert.equal(lines[1][1], ' class="now"');
  assert.equal(lines[1][2], "50.0,13.0 98.0,3.0");
});

test("the concurrency sparkline is left out with fewer than two samples", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const concurrency = tiles(upstreamKpiTilesHtml(providers(), [1], NOW))[2];

  assert.doesNotMatch(concurrency, /<svg/);
});

test("the collapsed line summarizes usage, credit and concurrency with no warnings when healthy", () => {
  const { upstreamKpiLineHtml } = loadKpi();
  const line = upstreamKpiLineHtml(providers(), NOW);

  assert.match(line, /Ollama #0 \$12\.40 of \$60 used/);
  assert.doesNotMatch(line, /\d%/);
  assert.match(line, /OpenRouter 餘額 \$23\.50/);
  assert.match(line, /併發 1\/14/);
  assert.deepEqual(statuses(line), []);
});

test("the collapsed line keeps every warning as an icon plus text", () => {
  const { upstreamKpiLineHtml } = loadKpi();
  const line = upstreamKpiLineHtml(
    providers({
      waiting: 2,
      ollamaKeys: [
        ollamaKey({ included_monthly_usage: monthlyUsage(57, 60) }),
        ollamaKey({ index: 1, quarantined: true, quarantine_remaining_sec: 600 }),
      ],
      openrouterKeys: [openrouterKey({ account_credit_remaining: 1 })],
    }),
    NOW,
  );

  assert.deepEqual(statuses(line), ["Ollama #0 快用完", "Ollama #1 隔離中 10 分", "餘額偏低", "排隊 2"]);
});

test("collapse state round-trips through storage", () => {
  const { readUpstreamKpiCollapsed, writeUpstreamKpiCollapsed } = loadKpi();
  const store = new Map();
  const storage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };

  assert.equal(readUpstreamKpiCollapsed(storage), false);
  writeUpstreamKpiCollapsed(storage, true);
  assert.equal(readUpstreamKpiCollapsed(storage), true);
  writeUpstreamKpiCollapsed(storage, false);
  assert.equal(readUpstreamKpiCollapsed(storage), false);
});

test("a failing storage leaves the dashboard expanded and does not throw", () => {
  const { readUpstreamKpiCollapsed, writeUpstreamKpiCollapsed } = loadKpi();
  const broken = {
    getItem() {
      throw new Error("SecurityError");
    },
    setItem() {
      throw new Error("QuotaExceededError");
    },
  };

  assert.equal(readUpstreamKpiCollapsed(broken), false);
  assert.equal(readUpstreamKpiCollapsed(undefined), false);
  assert.doesNotThrow(() => writeUpstreamKpiCollapsed(broken, true));
});

test("the collapse toggle still works for the session when storage writes fail", () => {
  const { upstreamKpiCollapseState } = loadKpi();
  const broken = {
    getItem() {
      throw new Error("SecurityError");
    },
    setItem() {
      throw new Error("QuotaExceededError");
    },
  };
  const state = upstreamKpiCollapseState(broken);

  assert.equal(state.collapsed, false);
  assert.equal(state.toggle(), true);
  assert.equal(state.collapsed, true);
  assert.equal(state.toggle(), false);
});

test("the collapse state starts from storage and writes each toggle back", () => {
  const { upstreamKpiCollapseState } = loadKpi();
  const store = new Map([["vcr_upstream_kpi_collapsed", "1"]]);
  const storage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
  const state = upstreamKpiCollapseState(storage);

  assert.equal(state.collapsed, true);
  state.toggle();
  assert.equal(store.get("vcr_upstream_kpi_collapsed"), "0");
});
