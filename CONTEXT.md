# Vans Coding Router

OpenAI-compatible cloud provider router for Vans Coding classes. Students call the router with a classroom API key; the router forwards to teacher-configured upstream providers.

## Language

**Model ID**:
A request identity of the form `provider@upstream_model` (for example `ollama_cloud@kimi-k3:cloud`). The router uses the provider segment for routing and forwards the upstream segment to that provider.
_Avoid_: Bare model name, display name

**Upstream Refusal**:
A provider response that rejects the request before any model output is produced (for example Ollama Extra Usage exhausted). It is a billing or entitlement failure at the provider, not a router routing mistake.
_Avoid_: Copilot bug, no choices, model offline

**Readable Upstream Error**:
The provider's refusal text surfaced to the client (chat choices content or Responses `output_text`) so the user can act on it.
_Avoid_: Generic "Upstream provider error", "Response contained no choices"
