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
    "upstreamLogoHtml",
    "formatIncludedMonthlyUsage",
    "formatAccountCreditRemaining",
    "upstreamKpiStatus",
    "upstreamKpiQuarantineMinutes",
    "upstreamKpiSpendFraction",
    "upstreamKpiUsedFraction",
    "upstreamKpiKeyLimitFraction",
    "upstreamKpiMeterHtml",
    "upstreamKpiResetsText",
    "upstreamKpiMonthlyUsageParts",
    "upstreamKpiUsageNearlyUsed",
    "upstreamKpiLowCredit",
    "upstreamKpiLightHtml",
    "upstreamKpiQuarantineText",
    "upstreamKpiCredit",
    "upstreamKpiTilesHtml",
  ];
  const context = {};
  vm.createContext(context);
  vm.runInContext(names.map((name) => extractNamedFunction(portalHtml, name)).join("\n"), context);
  return context;
}

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

// A tile's label as read aloud: the upstream logo's name, then the key number.
function label(tile) {
  const lbl = tile.match(/<div class="lbl">([\s\S]*?)<\/div>/)[1];
  const logo = lbl.match(/role="img" aria-label="([^"]*)"/)?.[1];
  const number = lbl.match(/<span>(#\d+)<\/span>/)?.[1];
  return `${logo} ${number}`;
}

test("a healthy Ollama key tile shows $X of $Y used, a meter and Resets in …", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const html = upstreamKpiTilesHtml(providers());
  const ollama = tiles(html)[0];

  assert.equal(label(ollama), "Ollama #0");
  assert.match(ollama, /\$12\.40 of \$60 used/);
  assert.match(ollama, /<div class="meter"><i style="width:21%"><\/i><\/div>/);
  assert.match(ollama, /<span>Resets in 9 days<\/span>/);
  assert.doesNotMatch(ollama, /\. ·/);
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
  const ollama = tiles(upstreamKpiTilesHtml(providers({ ollamaKeys: [key] })))[0];

  assert.deepEqual(statuses(ollama), ["快用完"]);
  assert.match(ollama, /\$54 of \$60 used/);
  assert.match(ollama, /Resets in 9 days</);
  assert.match(ollama, /meter warn/);
});

test("an Ollama key just under 90% has no warning", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const key = ollamaKey({ included_monthly_usage: monthlyUsage(53.9, 60) });
  const ollama = tiles(upstreamKpiTilesHtml(providers({ ollamaKeys: [key] })))[0];

  assert.deepEqual(statuses(ollama), []);
});

test("an Ollama key without Included Monthly Usage says it is unavailable instead of drawing numbers", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const key = ollamaKey({ included_monthly_usage: null });
  const ollama = tiles(upstreamKpiTilesHtml(providers({ ollamaKeys: [key] })))[0];

  assert.match(ollama, /月用量無法取得/);
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
  const ollama = tiles(upstreamKpiTilesHtml(providers({ ollamaKeys: [key] })))[0];

  assert.deepEqual(statuses(ollama), ["隔離中 31 分"]);
  assert.deepEqual(releaseButtons(ollama), ["ollama_cloud|1"]);
});

test("a quarantined OpenRouter key shows 隔離中 N 分 and a Quarantine Release button on its own tile", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [openrouterKey(), openrouterKey({ index: 1, quarantined: true, quarantine_remaining_sec: 60 })];
  const [, healthy, quarantined] = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys })));

  assert.deepEqual(statuses(quarantined), ["隔離中 1 分"]);
  assert.deepEqual(releaseButtons(quarantined), ["openrouter|1"]);
  assert.deepEqual(statuses(healthy), []);
  assert.deepEqual(releaseButtons(healthy), []);
});

test("a quarantined OpenRouter key low on credit shows both 隔離中 and 餘額偏低", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [openrouterKey({ quarantined: true, quarantine_remaining_sec: 60, account_credit_remaining: 1 })];
  const openrouter = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys })))[1];

  assert.deepEqual(statuses(openrouter), ["隔離中 1 分", "餘額偏低"]);
  assert.deepEqual(releaseButtons(openrouter), ["openrouter|0"]);
});

test("each OpenRouter key gets its own tile with its own Account Credit Remaining", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [openrouterKey({ account_credit_remaining: 13.13 }), openrouterKey({ index: 1, account_credit_remaining: 41 })];
  const [, first, second] = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys })));

  assert.equal(label(first), "OpenRouter #0");
  assert.match(first, /餘額 \$13\.13/);
  assert.equal(label(second), "OpenRouter #1");
  assert.match(second, /餘額 \$41\.00/);
  for (const tile of [first, second]) {
    assert.doesNotMatch(tile, /帳號共用額度|把 key/);
    assert.deepEqual(statuses(tile), []);
  }
});

test("an OpenRouter tile with no Account Credit Remaining says it is unavailable", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [openrouterKey({ account_credit_remaining: null })];
  const openrouter = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys })))[1];

  assert.match(openrouter, /餘額無法取得/);
  assert.doesNotMatch(openrouter, /NaN|null|undefined|—/);
});

test("OpenRouter Account Credit Remaining below $5 shows 餘額偏低 with an icon", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [openrouterKey({ account_credit_remaining: 4.3 })];
  const openrouter = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys })))[1];

  assert.match(openrouter, /餘額 \$4\.30/);
  assert.deepEqual(statuses(openrouter), ["餘額偏低"]);
});

test("a low balance on the second OpenRouter account warns on that key's tile only", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [openrouterKey({ account_credit_remaining: 23.5 }), openrouterKey({ index: 1, account_credit_remaining: 2 })];
  const [, first, second] = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys })));

  assert.deepEqual(statuses(first), []);
  assert.deepEqual(statuses(second), ["餘額偏低"]);
});

// A tile's in-flight light: [state class, count shown beside it, spoken label].
function light(tile) {
  const lbl = tile.match(/<div class="lbl">([\s\S]*?)<\/div>/)[1];
  const m = lbl.match(/<span class="upstream-kpi-load">(?:<span aria-hidden="true">([^<]*)<\/span>)?<i class="upstream-kpi-light( is-[a-z]+)?" role="img" aria-label="([^"]*)"/);
  return m && [m[2]?.trim() ?? "", m[1] ?? "", m[3]];
}

test("a key with requests in flight breathes next to its label and shows in-flight/cap there", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const [ollama, openrouter] = tiles(
    upstreamKpiTilesHtml(providers({ ollamaKeys: [ollamaKey({ in_flight: 1 })], openrouterKeys: [openrouterKey({ in_flight: 2 })] })),
  );

  assert.deepEqual(light(ollama), ["is-active", "1/3", "工作中 1/3"]);
  assert.deepEqual(light(openrouter), ["is-active", "2/4", "工作中 2/4"]);
});

test("an idle key shows a quiet light and no count", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const openrouter = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: [openrouterKey({ in_flight: 0 })] })))[1];

  assert.deepEqual(light(openrouter), ["", "", "閒置"]);
});

test("a key at its concurrency cap shows a steady full light", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const ollama = tiles(upstreamKpiTilesHtml(providers({ ollamaKeys: [ollamaKey({ in_flight: 3 })] })))[0];

  assert.deepEqual(light(ollama), ["is-full", "3/3", "滿載 3/3"]);
  assert.match(ollama, /--load:1\.00/);
});

test("a key without a concurrency cap counts its requests but is never full", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const ollama = tiles(upstreamKpiTilesHtml(providers({ ollamaKeys: [ollamaKey({ cap: null, in_flight: 5 })] })))[0];

  assert.deepEqual(light(ollama), ["is-active", "5", "工作中 5"]);
  assert.match(ollama, /--load:0\.00/);
});

test("concurrency is no longer repeated in a tile's sub line", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const html = upstreamKpiTilesHtml(
    providers({ openrouterKeys: [openrouterKey({ in_flight: 2 }), openrouterKey({ index: 1, key_monthly_limit: keyMonthlyLimit(1, 20) })] }),
  );

  assert.doesNotMatch(html, /併發/);
});

// Key Monthly Limit as the pool status reports it (src/domain/extra_usage.py).
function keyMonthlyLimit(used, limit) {
  const dollars = (n) => (Number.isInteger(n) ? String(n) : n.toFixed(2));
  return {
    used_usd: used,
    limit_usd: limit,
    resets_at: IN_9_DAYS,
    summary: `$${dollars(used)} of $${dollars(limit)} used`,
    resets: "Resets in 9 days.",
  };
}

test("an OpenRouter key with a monthly cap leads with its balance and shows the cap, a meter and Resets in … below", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [openrouterKey({ in_flight: 1, key_monthly_limit: keyMonthlyLimit(8.2, 20) })];
  const openrouter = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys })))[1];

  assert.equal(label(openrouter), "OpenRouter #0");
  assert.match(openrouter, /<div class="val">餘額 \$23\.50<\/div>/);
  assert.match(openrouter, /<div class="meter"><i style="width:41%"><\/i><\/div>/);
  assert.match(openrouter, /<span>月上限 \$8\.20 of \$20 used · Resets in 9 days<\/span>/);
  assert.deepEqual(statuses(openrouter), []);
});

test("an OpenRouter key at 90% of its monthly cap shows 快用完, and a low balance still warns", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [
    openrouterKey({ key_monthly_limit: keyMonthlyLimit(18, 20) }),
    openrouterKey({ index: 1, account_credit_remaining: 3, key_monthly_limit: keyMonthlyLimit(1, 20) }),
  ];
  const [, nearlyUsed, lowCredit] = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys })));

  assert.deepEqual(statuses(nearlyUsed), ["快用完"]);
  assert.match(nearlyUsed, /meter warn/);
  assert.match(nearlyUsed, /<div class="val">餘額 \$23\.50<\/div>/);
  assert.match(nearlyUsed, /月上限 \$18 of \$20 used · Resets in 9 days</);
  assert.deepEqual(statuses(lowCredit), ["餘額偏低"]);
  assert.doesNotMatch(lowCredit, /meter warn/);
});

test("a quarantined OpenRouter key with a monthly cap keeps its balance, cap and reset beside 隔離中", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [
    openrouterKey({ quarantined: true, quarantine_remaining_sec: 60, key_monthly_limit: keyMonthlyLimit(18, 20) }),
  ];
  const openrouter = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys })))[1];

  assert.deepEqual(statuses(openrouter), ["隔離中 1 分"]);
  assert.deepEqual(releaseButtons(openrouter), ["openrouter|0"]);
  assert.match(openrouter, /<div class="val">餘額 \$23\.50<\/div>/);
  assert.match(openrouter, /月上限 \$18 of \$20 used · Resets in 9 days</);
});

test("an OpenRouter key without a monthly cap keeps the balance tile and draws no meter", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const keys = [openrouterKey({ key_monthly_limit: null })];
  const openrouter = tiles(upstreamKpiTilesHtml(providers({ openrouterKeys: keys })))[1];

  assert.match(openrouter, /<div class="val">餘額 \$23\.50<\/div>/);
  assert.doesNotMatch(openrouter, /class="meter|used|月用量無法取得/);
});

test("the dashboard has no pool-wide concurrency tile", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const html = upstreamKpiTilesHtml(providers({ waiting: 3 }));

  assert.equal(tiles(html).length, 2);
  assert.doesNotMatch(html, /<svg|無排隊|排隊 3|\/ 14/);
});


function anthropicKey(overrides = {}) {
  return {
    index: 0,
    label: "ANTHROPIC 1",
    cap: 10,
    in_flight: 2,
    quarantined: false,
    quarantine_remaining_sec: null,
    ...overrides,
  };
}

test("each Anthropic key gets a tile with its in-flight light and no money meter", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const html = upstreamKpiTilesHtml({
    anthropic: { pool: { capacity: 20, in_flight_total: 2, waiting: 0, keys: [anthropicKey(), anthropicKey({ index: 1, in_flight: 0 })] } },
  });
  const [busy, idle] = tiles(html);

  assert.equal(tiles(html).length, 2);
  assert.match(busy, /anthropic/);
  assert.match(busy, /<span>#0<\/span>/);
  assert.match(busy, /<span aria-hidden="true">2\/10<\/span>/);
  assert.match(idle, /<span>#1<\/span>/);
  for (const tile of [busy, idle]) {
    assert.doesNotMatch(tile, /class="meter|\$|餘額|月上限|月用量|NaN|null|undefined/);
    assert.deepEqual(statuses(tile), []);
    assert.deepEqual(releaseButtons(tile), []);
  }
});

test("a quarantined Anthropic key shows 隔離中 N 分 and a Quarantine Release button", () => {
  const { upstreamKpiTilesHtml } = loadKpi();
  const html = upstreamKpiTilesHtml({
    anthropic: { pool: { keys: [anthropicKey({ index: 1, in_flight: 0, quarantined: true, quarantine_remaining_sec: 120 })] } },
  });
  const [tile] = tiles(html);

  assert.deepEqual(statuses(tile), ["隔離中 2 分"]);
  assert.deepEqual(releaseButtons(tile), ["anthropic|1"]);
});
