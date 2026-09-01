# WebMCP mutations are recorded in a backend Agent Action Audit

Successful WebMCP Class Session mutations are recorded in the shared repository as Agent Action Audit records after the existing Portal use case completes the mutation. The record stores the authenticated Portal actor, canonical Agent Capability action, explicit Class and Class Session target, relevant request arguments, invocation channel, and UTC event time.

The browser adapter identifies WebMCP with the descriptive `X-Vans-Invocation-Channel: webmcp` request header. The server normalizes that marker for audit purposes only; it never uses the header to authenticate a request, select an actor, or grant authorization. Portal Session authentication and the existing `PortalUseCase` authorization checks remain authoritative, so spoofing the marker cannot make an otherwise-forbidden mutation succeed.

Human Portal writes continue to use the same teacher HTTP endpoints without an Agent Action Audit marker. Failed, rejected, unauthorized, or missing-target mutations are recorded neither as successful audits nor as partial audit events.

SQLite and PostgreSQL both persist the audit table through the repository boundary. The audit is intentionally a backend record rather than a browser log, so later operators can distinguish an authorized agent invocation from an ordinary human Portal action.
