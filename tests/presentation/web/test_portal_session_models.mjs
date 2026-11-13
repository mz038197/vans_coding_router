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

function load() {
  const names = ["escapeHtml", "modelIdPrefix", "upstreamLogoHtml", "shortModelName", "modelLabelHtml", "sessionModelListHtml"];
  const context = {};
  vm.createContext(context);
  vm.runInContext(names.map((name) => extractNamedFunction(portalHtml, name)).join("\n"), context);
  return context;
}

// One rendered row per model: [upstream logo label, shown name, full id in title].
function rows(html) {
  return [...html.matchAll(/<div class="session-model-row" title="([^"]*)">([\s\S]*?)<\/div>/g)].map(([, title, inner]) => {
    const logo = inner.match(/aria-label="([^"]*)"/)?.[1] ?? inner.match(/session-model-upstream">([^<]*)</)?.[1];
    const name = inner.match(/<span class="model-label-name">([^<]*)<\/span>/)?.[1];
    return [logo, name, title];
  });
}

test("every model gets its own row with its upstream logo, its name, and the full id on hover", () => {
  const { sessionModelListHtml } = load();
  const html = sessionModelListHtml([
    { id: "ollama_cloud@minimax-m3:cloud", name: "minimax-m3" },
    { id: "openrouter@minimax/minimax-m3", name: "minimax-m3-backup" },
  ]);
  assert.match(html, /^<div class="session-model-list">/);
  assert.deepEqual(rows(html), [
    ["Ollama", "minimax-m3", "ollama_cloud@minimax-m3:cloud"],
    ["OpenRouter", "minimax-m3-backup", "openrouter@minimax/minimax-m3"],
  ]);
});

test("rows are grouped by upstream, in the order each upstream first appears", () => {
  const { sessionModelListHtml } = load();
  const html = sessionModelListHtml([
    { id: "openrouter@openai/gpt-5", name: "gpt-5" },
    { id: "ollama_cloud@glm-4.6:cloud", name: "glm-4.6" },
    { id: "openrouter@google/gemini-2.5-pro", name: "gemini-2.5-pro" },
  ]);
  assert.deepEqual(rows(html).map(([logo, name]) => `${logo} ${name}`), [
    "OpenRouter gpt-5",
    "OpenRouter gemini-2.5-pro",
    "Ollama glm-4.6",
  ]);
});

test("a model without a name shows a short form of its upstream model id", () => {
  const { sessionModelListHtml } = load();
  const html = sessionModelListHtml([
    { id: "openrouter@anthropic/claude-sonnet-4.5" },
    { id: "ollama_cloud@qwen3-coder:480b-cloud" },
    { id: "ollama_cloud@kimi-k2.7-code:cloud" },
  ]);
  assert.deepEqual(rows(html).map(([, name]) => name), ["claude-sonnet-4.5", "qwen3-coder 480b", "kimi-k2.7-code"]);
});

test("a teacher-given name is shown as written", () => {
  const { sessionModelListHtml } = load();
  const html = sessionModelListHtml([{ id: "openrouter@anthropic/claude-sonnet-4.5", name: "anthropic/claude 備用" }]);
  assert.deepEqual(rows(html).map(([, name]) => name), ["anthropic/claude 備用"]);
});

test("OpenAI and Anthropic models show their upstream logo", () => {
  const { sessionModelListHtml } = load();
  const html = sessionModelListHtml([
    { id: "openai@gpt-image-1", name: "gpt-image-1" },
    { id: "anthropic@claude-haiku-5-5", name: "Claude Haiku 5.5" },
  ]);
  assert.deepEqual(rows(html), [
    ["OpenAI", "gpt-image-1", "openai@gpt-image-1"],
    ["Anthropic", "Claude Haiku 5.5", "anthropic@claude-haiku-5-5"],
  ]);
  assert.match(html, /class="upstream-logo upstream-logo-openai"/);
});

test("an upstream without a logo is named in text", () => {
  const { sessionModelListHtml } = load();
  const html = sessionModelListHtml([{ id: "someprovider@model-x", name: "model-x" }]);
  assert.deepEqual(rows(html), [["someprovider", "model-x", "someprovider@model-x"]]);
});

test("a model id without an upstream is grouped under 其他", () => {
  const { sessionModelListHtml } = load();
  const html = sessionModelListHtml([{ id: "local-model", name: "local-model" }]);
  assert.deepEqual(rows(html), [["其他", "local-model", "local-model"]]);
});

test("hovering anywhere on a row, logo included, shows the full model id", () => {
  const { sessionModelListHtml } = load();
  const html = sessionModelListHtml([{ id: "openrouter@openai/gpt-5", name: "gpt-5" }]);
  assert.equal((html.match(/title="/g) || []).length, 1);
  assert.match(html, /<div class="session-model-row" title="openrouter@openai\/gpt-5">/);
});

test("names and ids are escaped", () => {
  const { sessionModelListHtml } = load();
  const html = sessionModelListHtml([{ id: 'openrouter@x"<b>', name: "<b>bold</b>" }]);
  assert.doesNotMatch(html, /<b>/);
  assert.match(html, /&lt;b&gt;bold&lt;\/b&gt;/);
});

test("the session card lists chat models with the grouped list, not pills", () => {
  const cell = extractNamedFunction(portalHtml, "sessionModelAllowlistCell");
  assert.match(cell, /sessionModelListHtml\(chat\)/);
  assert.doesNotMatch(portalHtml, /session-model-pill/);
});
