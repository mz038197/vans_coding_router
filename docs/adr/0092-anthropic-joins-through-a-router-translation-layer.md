# Anthropic joins through a router translation layer

The `anthropic` provider is the first upstream that does not speak the OpenAI API. Students reach the router from VS Code Copilot Chat through the VCRouter Stencil, which sends Responses requests, and some tools send chat completions. Anthropic serves only its Messages API. So the router translates both student endpoints into Messages and translates the replies back, inside one Anthropic gateway. That gateway has the same interface as the OpenAI-compatible gateway, so routing by Model ID, vcr-auto, Key Failover, Key Quarantine, Token Usage, and Prompt Log work unchanged. A Model ID names the provider: `anthropic@claude-opus-5-5` is the owner's Anthropic account, and `openrouter@anthropic/...` is Claude through OpenRouter. The two are different routes.

The translation is not a full mapping. It drops fields Claude would reject or that mean nothing upstream:

- `temperature`, `top_p` and `top_k`, which `anthropic-version: 2026-10-21` rejects on every model;
- Copilot's own fields.

It changes other fields:

- a forced `tool_choice` becomes `auto`, because Opus 5.5 and Fable 5.2 reject it;
- `minimal` effort becomes `low`.

It refuses the rest with a Readable Upstream Error: file parts, audio parts, and `n > 1`. Upstream calls always stream. When no output limit is sent, `max_tokens` defaults to 32000. Every request uses automatic prompt caching. These rules mean a student request that works on another model does not fail only because it went to Claude.

Anthropic's refusals differ from OpenRouter's. For the `anthropic` provider, each of these is Credit Exhaustion:

- 402 `billing_error`;
- a 400 whose message says "You have reached your specified API usage limits", or the workspace variant;
- a 429 whose error code is `enforced_spend_limit_reached`;
- any status whose message says "credit balance is too low".

A plain 429 and a 529 stay busy signals.

Anthropic offers no API that returns the prepaid balance. Its cost data runs hours behind. So the Portal tile for this provider shows in-flight requests and Key Quarantine only, without a money meter. The router does not need an Admin key.

## Considered Options

- **Anthropic's OpenAI-compatibility layer** (`https://api.anthropic.com/v1/` as an `openai_compatible` provider): rejected. It serves chat completions only, with no Responses endpoint. It does not return thinking and does no prompt caching. Anthropic calls it not a long-term or production-ready solution.
- **A `/v1/messages` endpoint on the router, passed through to Anthropic**: dropped by the owner. Copilot would still need the translation, so the endpoint would add a second path to keep, not remove one. Claude Code students already reach the router through VansPod's Responses adapter.
- **Claude through OpenRouter only**: kept as a separate route, not a replacement. The owner wants the Anthropic account's own keys, and OpenRouter's thinking handling is outside the router's control.

## Consequences

- The router now owns protocol correctness for one provider. A Messages API change, or a new Copilot field, can break Claude without breaking any other model.
- Claude's thinking needs its own design, because Anthropic binds each thinking block to the conversation that produced it (ADR 0093).
