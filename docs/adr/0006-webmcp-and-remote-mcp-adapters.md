# WebMCP and remote MCP use separate adapters around shared agent capabilities

WebMCP is a browser-side Presentation adapter for the Vans Portal. It exposes domain-intent tools to an agent, inherits the currently authenticated Portal Session, reads Portal Working Context for convenient default targets, and invokes the existing `/teacher/*` HTTP APIs. It does not create a second authorization path and does not grant permissions beyond those already available to the Portal user.

A future remote MCP server may expose the same canonical agent capability vocabulary, but it is a separate adapter with its own transport and authentication boundary. It must not depend on Portal cookies or reuse browser-only authentication assumptions. Remote MCP authentication is intentionally deferred until that interface is designed.

We chose this separation over sharing one browser-oriented implementation because capability vocabulary is a useful compatibility contract for agents, while authentication and transport have different trust boundaries. Coupling remote MCP to Portal Session mechanics would make a future non-browser client depend on browser state and would blur the authorization boundary.

## Consequences

- WebMCP v1 lives in the Portal Presentation layer and progressively enhances supported browsers; unsupported browsers remain fully usable by humans.
- WebMCP tools express domain intent rather than DOM operations or UI clicks.
- WebMCP reuses existing `/teacher/*` APIs and existing `PortalUseCase` authorization instead of adding `/webmcp/*` business endpoints.
- The Portal UI owns the current Class and Class Session working context. WebMCP may use that context as a default target, but explicit tool targets may refer to another authorized Class Session.
- Page content is data, not authority. Only explicit user intent may initiate state-changing WebMCP actions.
- WebMCP write actions do not require an additional confirmation when the current Portal user is already authorized, but individual actions may still have mechanism-level guardrails such as quarantine-release cooldowns.
- Successful WebMCP mutations are recorded by the backend as Agent Action Audit events. Client-supplied invocation metadata is audit/telemetry information only and never increases authorization.
- WebMCP v1 exposes Class Session management, usage, upstream status, and guarded quarantine recovery. It does not create Classes, expose Prompt Logs, perform destructive administration, change user roles, or rotate credentials.
- WebMCP and future remote MCP should use the same canonical capability names where the domain intent is the same, but their adapters and authentication remain independent.
- Remote MCP implementation and authentication are outside the scope of WebMCP v1.
