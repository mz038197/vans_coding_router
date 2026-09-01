(function exposePortalWebMcp(global) {
  "use strict";

  function errorType(status) {
    if (status === 400 || status === 422) return "validation";
    if (status === 401) return "unauthenticated";
    if (status === 403) return "forbidden";
    if (status === 404) return "missing_target";
    if (status === 429) return "throttling";
    if (status >= 500) return "temporary_service";
    return "service_error";
  }

  function structuredError(type, status, message) {
    return { error: { type, status, message } };
  }

  function selectFields(item, fields) {
    return Object.fromEntries(
      fields.filter((field) => item[field] !== undefined).map((field) => [field, item[field]]),
    );
  }

  function normalizeClass(item) {
    return selectFields(item, [
      "id",
      "name",
      "status",
      "ends_at",
      "api_key_ttl_hours",
      "member_count",
    ]);
  }

  function normalizeSession(item) {
    return selectFields(item, [
      "id",
      "class_id",
      "name",
      "status",
      "session_at",
      "expires_at",
      "image_generation_enabled",
      "tts_enabled",
      "speech_transcription_enabled",
      "prompt_logging_enabled",
      "seat_limit",
      "nickname_seat_count",
      "redemption_count",
    ]);
  }

  async function requestResult(request, path, normalize) {
    try {
      const response = await request(path);
      const payload = await response.json();
      if (!response.ok) {
        const detail = payload && payload.detail;
        const message =
          typeof detail === "string"
            ? detail
            : (detail && detail.message) || `Portal request failed (${response.status})`;
        return structuredError(errorType(response.status), response.status, message);
      }
      return normalize(payload);
    } catch (_error) {
      return structuredError(
        "temporary_service",
        null,
        "Portal service is temporarily unavailable",
      );
    }
  }

  function readWorkingContext({ document, classes = [], sessions = [], getSessionName }) {
    const monitorTab = document.getElementById("monitorTab");
    const monitorIsActive = monitorTab && !monitorTab.classList.contains("hidden");
    const classSelect = document.getElementById(
      monitorIsActive ? "monitorClassId" : "courseSelect",
    );
    const classId = Number(classSelect && classSelect.value);
    if (!Number.isInteger(classId) || classId <= 0) {
      return { class_id: null, class_name: null };
    }

    const selectedClass = classes.find((item) => Number(item.id) === classId);
    const context = {
      class_id: classId,
      class_name: (selectedClass && selectedClass.name) || null,
    };
    if (!monitorIsActive) return context;

    const sessionSelect = document.getElementById("monitorSessionId");
    const sessionId = Number(sessionSelect && sessionSelect.value);
    if (!Number.isInteger(sessionId) || sessionId <= 0) return context;
    const selectedSession = sessions.find((item) => Number(item.id) === sessionId);
    return {
      ...context,
      session_id: sessionId,
      session_name: selectedSession && getSessionName ? getSessionName(selectedSession) : null,
    };
  }

  function enhance({ document, getWorkingContext, request = global.fetch }) {
    const modelContext = document && document.modelContext;
    if (!modelContext || typeof modelContext.registerTool !== "function") {
      return { supported: false, registration: null };
    }

    const tools = [{
      name: "get_portal_working_context",
      title: "Get Portal Working Context",
      description: "Return the Class and optional Class Session currently selected in the Portal.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
      execute() {
        return { working_context: getWorkingContext() };
      },
    }, {
      name: "list_classes",
      title: "List Classes",
      description: "List the Classes available to the authenticated Portal teacher.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
      async execute() {
        return requestResult(request, "/teacher/classes", (payload) => ({
          classes: payload.items.map(normalizeClass),
        }));
      },
    }, {
      name: "list_class_sessions",
      title: "List Class Sessions",
      description: "List the Class Sessions for an explicit Class or the current Portal Class.",
      inputSchema: {
        type: "object",
        properties: { class_id: { type: "integer", minimum: 1 } },
        additionalProperties: false,
      },
      async execute(input = {}) {
        const classId = input.class_id || getWorkingContext().class_id;
        if (!classId) {
          return structuredError("missing_target", null, "class_id is required");
        }
        return requestResult(
          request,
          `/teacher/classes/${classId}/sessions`,
          (payload) => ({
            class_id: classId,
            class_sessions: payload.items.map(normalizeSession),
          }),
        );
      },
    }, {
      name: "get_class_session",
      title: "Get Class Session",
      description: "Inspect an explicit Class Session or the current Portal Class Session.",
      inputSchema: {
        type: "object",
        properties: {
          class_id: { type: "integer", minimum: 1 },
          session_id: { type: "integer", minimum: 1 },
        },
        additionalProperties: false,
      },
      async execute(input = {}) {
        const context = getWorkingContext();
        const classId = input.class_id || context.class_id;
        const sessionId = input.session_id || context.session_id;
        if (!classId || !sessionId) {
          return structuredError(
            "missing_target",
            null,
            "class_id and session_id are required",
          );
        }
        return requestResult(
          request,
          `/teacher/classes/${classId}/sessions/${sessionId}`,
          (payload) => ({ class_session: normalizeSession(payload) }),
        );
      },
    }, {
      name: "get_class_usage",
      title: "Get Class Usage",
      description: "Return existing usage facts for an explicit Class or the current Portal Class.",
      inputSchema: {
        type: "object",
        properties: { class_id: { type: "integer", minimum: 1 } },
        additionalProperties: false,
      },
      async execute(input = {}) {
        const classId = input.class_id || getWorkingContext().class_id;
        if (!classId) {
          return structuredError("missing_target", null, "class_id is required");
        }
        return requestResult(request, `/teacher/classes/${classId}/usage`, (payload) => ({
          class_id: classId,
          usage: payload.items,
        }));
      },
    }, {
      name: "get_upstream_pool_status",
      title: "Get Upstream Pool Status",
      description: "Return the current upstream provider pool facts visible to the Portal teacher.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
      async execute() {
        return requestResult(request, "/teacher/upstream-pools", (payload) => ({
          providers: payload.providers,
        }));
      },
    }];
    const registration = Promise.resolve()
      .then(() => Promise.all(tools.map((tool) => modelContext.registerTool(tool))))
      .then(
        () => true,
        () => false,
      );

    return { supported: true, registration };
  }

  global.VansPortalWebMcp = { enhance, readWorkingContext };
})(window);
