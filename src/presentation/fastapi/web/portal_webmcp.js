(function exposePortalWebMcp(global) {
  "use strict";

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

  function enhance({ document, getWorkingContext }) {
    const modelContext = document && document.modelContext;
    if (!modelContext || typeof modelContext.registerTool !== "function") {
      return { supported: false, registration: null };
    }

    const tool = {
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
    };
    const registration = Promise.resolve()
      .then(() => modelContext.registerTool(tool))
      .then(
        () => true,
        () => false,
      );

    return { supported: true, registration };
  }

  global.VansPortalWebMcp = { enhance, readWorkingContext };
})(window);
