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

test("supported browsers discover working context and list Classes", async () => {
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
    request: async (url) => {
      assert.equal(url, "/teacher/classes");
      return {
        ok: true,
        status: 200,
        json: async () => ({
          items: [{
            id: 7,
            name: "Python 入門",
            status: "active",
            teacher_email: "teacher@school.edu",
          }],
        }),
      };
    },
  });
  await result.registration;

  assert.equal(result.supported, true);
  assert.deepEqual(
    registered.map((tool) => tool.name),
    [
      "get_portal_working_context",
      "list_classes",
      "list_class_sessions",
      "get_class_session",
      "get_class_usage",
      "get_upstream_pool_status",
    ],
  );
  assert.equal(typeof registered[0].execute, "function");
  assert.doesNotMatch(registered[1].description, /DOM|click|selector/i);
  assert.deepEqual(JSON.parse(JSON.stringify(await registered[1].execute({}))), {
    classes: [{ id: 7, name: "Python 入門", status: "active" }],
  });
});

test("capability consumes the live Portal Working Context on every execution", async () => {
  const adapter = loadAdapter();
  let workingContext = { class_id: 7, class_name: "Python 入門" };
  let registeredTool;
  const document = {
    modelContext: {
      registerTool(tool) {
        if (tool.name === "get_portal_working_context") registeredTool = tool;
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

test("list Class Sessions sends an explicit target and returns selectable data", async () => {
  const adapter = loadAdapter();
  const registered = new Map();
  const document = {
    modelContext: {
      registerTool(tool) {
        registered.set(tool.name, tool);
        return Promise.resolve();
      },
    },
  };
  const result = adapter.enhance({
    document,
    getWorkingContext: () => ({ class_id: 7 }),
    request: async (url) => {
      assert.equal(url, "/teacher/classes/9/sessions");
      return {
        ok: true,
        status: 200,
        json: async () => ({
          items: [{
            id: 21,
            class_id: 9,
            name: "第一堂",
            status: "active",
            invite_code: "VANS-SECRET",
            course_catalog_yaml: "actions: []",
          }],
        }),
      };
    },
  });
  await result.registration;

  const output = await registered.get("list_class_sessions").execute({ class_id: 9 });
  assert.deepEqual(JSON.parse(JSON.stringify(output)), {
    class_id: 9,
    class_sessions: [{ id: 21, class_id: 9, name: "第一堂", status: "active" }],
  });
});

test("get Class Session resolves omitted targets from live Portal Working Context", async () => {
  const adapter = loadAdapter();
  const registered = new Map();
  const document = {
    modelContext: {
      registerTool(tool) {
        registered.set(tool.name, tool);
        return Promise.resolve();
      },
    },
  };
  const result = adapter.enhance({
    document,
    getWorkingContext: () => ({ class_id: 7, session_id: 21 }),
    request: async (url) => {
      assert.equal(url, "/teacher/classes/7/sessions/21");
      return {
        ok: true,
        status: 200,
        json: async () => ({ id: 21, class_id: 7, name: "第一堂", status: "active" }),
      };
    },
  });
  await result.registration;

  const output = await registered.get("get_class_session").execute({});
  assert.deepEqual(JSON.parse(JSON.stringify(output)), {
    class_session: { id: 21, class_id: 7, name: "第一堂", status: "active" },
  });
});

test("get Class usage returns existing backend facts without browser analysis", async () => {
  const adapter = loadAdapter();
  const registered = new Map();
  const document = {
    modelContext: {
      registerTool(tool) {
        registered.set(tool.name, tool);
        return Promise.resolve();
      },
    },
  };
  const facts = [{ user_id: 3, prompt_tokens: 120, completion_tokens: 40 }];
  const result = adapter.enhance({
    document,
    getWorkingContext: () => ({ class_id: 7 }),
    request: async (url) => {
      assert.equal(url, "/teacher/classes/7/usage");
      return { ok: true, status: 200, json: async () => ({ items: facts }) };
    },
  });
  await result.registration;

  const output = await registered.get("get_class_usage").execute({});
  assert.deepEqual(JSON.parse(JSON.stringify(output)), { class_id: 7, usage: facts });
  assert.equal("analysis" in output, false);
});

test("get upstream pool status preserves provider facts", async () => {
  const adapter = loadAdapter();
  const registered = new Map();
  const document = {
    modelContext: {
      registerTool(tool) {
        registered.set(tool.name, tool);
        return Promise.resolve();
      },
    },
  };
  const providers = { ollama_cloud: { pool: { key_count: 2, busy_total: 1 } } };
  const result = adapter.enhance({
    document,
    getWorkingContext: () => ({}),
    request: async (url) => {
      assert.equal(url, "/teacher/upstream-pools");
      return { ok: true, status: 200, json: async () => ({ providers }) };
    },
  });
  await result.registration;

  const output = await registered.get("get_upstream_pool_status").execute({});
  assert.deepEqual(JSON.parse(JSON.stringify(output)), { providers });
});

test("capabilities expose validation, auth, target, throttling, and temporary errors", async () => {
  const cases = [
    [422, "validation"],
    [401, "unauthenticated"],
    [403, "forbidden"],
    [404, "missing_target"],
    [429, "throttling"],
    [503, "temporary_service"],
  ];

  for (const [status, type] of cases) {
    const adapter = loadAdapter();
    const registered = new Map();
    const document = {
      modelContext: {
        registerTool(tool) {
          registered.set(tool.name, tool);
          return Promise.resolve();
        },
      },
    };
    const result = adapter.enhance({
      document,
      getWorkingContext: () => ({}),
      request: async () => ({
        ok: false,
        status,
        json: async () => ({ detail: `failure ${status}` }),
      }),
    });
    await result.registration;
    assert.deepEqual(
      JSON.parse(JSON.stringify(await registered.get("list_classes").execute({}))),
      { error: { type, status, message: `failure ${status}` } },
    );
  }

  const adapter = loadAdapter();
  const registered = new Map();
  const document = {
    modelContext: {
      registerTool(tool) {
        registered.set(tool.name, tool);
        return Promise.resolve();
      },
    },
  };
  const result = adapter.enhance({
    document,
    getWorkingContext: () => ({}),
    request: async () => assert.fail("missing target must not send an HTTP request"),
  });
  await result.registration;
  assert.deepEqual(
    JSON.parse(JSON.stringify(await registered.get("get_class_session").execute({}))),
    {
      error: {
        type: "missing_target",
        status: null,
        message: "class_id and session_id are required",
      },
    },
  );
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
