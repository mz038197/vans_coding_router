// Step 5 of the class model settings wizard: Anthropic is an All Models provider whose models
// only answer text (#124), so its models are never offered on the speech pickers.
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

function extractConst(source, name) {
  const match = source.match(new RegExp(`const ${name} = [\\[{][\\s\\S]*?\\n {4}[\\]}];`));
  if (!match) throw new Error(`missing const ${name}`);
  return match[0];
}

function catalogFor() {
  const code = [extractConst(portalHtml, "MODEL_WIZARD_EXTRA_KINDS"), extractNamedFunction(portalHtml, "modelIdPrefix"),
    extractNamedFunction(portalHtml, "modelWizardExtraCatalog")].join("\n");
  const box = {};
  vm.runInNewContext(`${code}\nthis.catalog = modelWizardExtraCatalog;`, box);
  return box.catalog;
}

const CATALOGS = {
  speech: [{ id: "openrouter@openai/tts-1" }],
  speech_transcription: [{ id: "openrouter@openai/whisper-1" }],
  all: [{ id: "ollama_cloud@gpt-oss:120b" }, { id: "anthropic@claude-opus-5-5" }],
};

for (const shelf of ["speech", "speech_transcription"]) {
  test(`the ${shelf} picker offers no Anthropic model`, () => {
    const ids = catalogFor()(shelf, CATALOGS).map((item) => item.id);
    assert.ok(!ids.includes("anthropic@claude-opus-5-5"), ids.join(", "));
    assert.ok(ids.includes("ollama_cloud@gpt-oss:120b"), ids.join(", "));
    assert.ok(ids.includes(CATALOGS[shelf][0].id), ids.join(", "));
  });
}
