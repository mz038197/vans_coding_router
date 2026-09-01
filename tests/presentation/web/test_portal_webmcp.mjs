import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const adapterSource = readFileSync(
  new URL("../../../src/presentation/fastapi/web/portal_webmcp.js", import.meta.url),
  "utf8",
);

function loadAdapter() {
  const window = {};
  vm.runInNewContext(adapterSource, { window });
  return window.VansPortalWebMcp;
}

test("unsupported browsers keep the Portal usable without registering tools", () => {
  const adapter = loadAdapter();

  const result = adapter.enhance({
    document: {},
    getWorkingContext: () => ({ class_id: 7 }),
  });

  assert.equal(result.supported, false);
  assert.equal(result.registration, null);
});

test("supported browsers discover the Portal Working Context capability", async () => {
  const adapter = loadAdapter();
  const registered = [];
  const document = {
    modelContext: {
      registerTool(tool) {
        registered.push(tool);
        return Promise.resolve();
      },
    },
  };

  const result = adapter.enhance({
    document,
    getWorkingContext: () => ({ class_id: 7 }),
  });
  await result.registration;

  assert.equal(result.supported, true);
  assert.equal(registered.length, 1);
  assert.equal(registered[0].name, "get_portal_working_context");
  assert.equal(typeof registered[0].execute, "function");
  assert.doesNotMatch(registered[0].description, /DOM|click|selector/i);
});

test("capability consumes the live Portal Working Context on every execution", async () => {
  const adapter = loadAdapter();
  let workingContext = { class_id: 7, class_name: "Python 入門" };
  let registeredTool;
  const document = {
    modelContext: {
      registerTool(tool) {
        registeredTool = tool;
        return Promise.resolve();
      },
    },
  };

  const result = adapter.enhance({ document, getWorkingContext: () => workingContext });
  await result.registration;
  const first = await registeredTool.execute({});
  workingContext = {
    class_id: 9,
    class_name: "AI 實作",
    session_id: 21,
    session_name: "第一堂",
  };
  const second = await registeredTool.execute({});

  assert.deepEqual(first.working_context, { class_id: 7, class_name: "Python 入門" });
  assert.deepEqual(second.working_context, {
    class_id: 9,
    class_name: "AI 實作",
    session_id: 21,
    session_name: "第一堂",
  });
});

test("a rejected registration does not create a Portal error state", async () => {
  const adapter = loadAdapter();
  const document = {
    modelContext: {
      registerTool() {
        return Promise.reject(new Error("WebMCP disabled by policy"));
      },
    },
  };

  const result = adapter.enhance({
    document,
    getWorkingContext: () => ({ class_id: 7 }),
  });

  assert.equal(await result.registration, false);
});

test("Portal Working Context follows the currently active Portal selection", () => {
  const adapter = loadAdapter();
  let monitorIsActive = true;
  const elements = {
    monitorTab: { classList: { contains: () => !monitorIsActive } },
    monitorClassId: { value: "9" },
    monitorSessionId: { value: "21" },
    courseSelect: { value: "7" },
  };
  const document = { getElementById: (id) => elements[id] };
  const options = {
    document,
    classes: [
      { id: 7, name: "Python 入門" },
      { id: 9, name: "AI 實作" },
    ],
    sessions: [{ id: 21, name: "第一堂" }],
    getSessionName: (session) => session.name,
  };

  assert.deepEqual(JSON.parse(JSON.stringify(adapter.readWorkingContext(options))), {
    class_id: 9,
    class_name: "AI 實作",
    session_id: 21,
    session_name: "第一堂",
  });

  monitorIsActive = false;
  assert.deepEqual(JSON.parse(JSON.stringify(adapter.readWorkingContext(options))), {
    class_id: 7,
    class_name: "Python 入門",
  });
});
