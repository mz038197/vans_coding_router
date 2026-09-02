# WebMCP Quarantine Release is explicit, guarded, and auditable

The `release_key_quarantine` Agent Capability targets an upstream provider and key index explicitly. It uses the existing teacher Quarantine Release HTTP endpoint, Portal Session, and `PortalUseCase` teacher authorization; the WebMCP invocation marker and reason never grant additional permission. The browser adapter does not infer a target from Portal Working Context or initiate a write while registering tools.

Agent-triggered Quarantine Release is accepted only for a key that is currently in Key Quarantine. The application applies a per-provider-key cooldown to WebMCP releases, including successful releases recorded in the Agent Action Audit, so a new application instance does not immediately reopen an Agent-driven release loop. A cooldown rejection happens before the gateway mutation and is returned as throttling; it creates no successful audit. Human Portal requests remain directly executable for an authorized teacher and are not subject to the Agent-only cooldown or audit marker.

Successful Agent-triggered releases record the canonical action, authenticated Portal actor, provider/key target and reason in `arguments`, the `webmcp` invocation channel, and the event time. Because Agent Capabilities are not all Class Session operations, Agent Action Audit `class_id` and `session_id` may be null; Class Session mutations continue to populate those fields. SQLite migrates the existing non-null audit table to the nullable shape, and PostgreSQL drops the old target constraints during schema initialization.

This preserves Page Content Is Data: Portal-visible text and prior tool results may inform a teacher's agent, but only an explicit tool execution can send the state-changing request.
