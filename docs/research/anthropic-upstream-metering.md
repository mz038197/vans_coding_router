# Anthropic upstream metering

Researched on 2026-11-12 against Anthropic's official docs, API reference, and the official Python SDK source, to decide what meter the Portal tile can show for an Anthropic upstream key. The owner will supply one ordinary, workspace-scoped API key (`sk-ant-api…`) and no Admin key.

## Result

**An ordinary workspace key cannot read any dollar figure from Anthropic.** There is no documented endpoint for credit balance, spend, usage, or configured limits that accepts it. Every usage, cost, and rate-limit report is part of the Admin API, and the docs say "workspace API keys don't work" there.

**No documented endpoint returns the prepaid credit balance, with any credential.** The balance is shown only on the Console Billing page. So Account Credit Remaining has no Anthropic equivalent.

What the one ordinary key does give, at no extra upstream call:

- **Rate-limit headroom**, from the `anthropic-ratelimit-*` response headers on each Messages call. This is requests and tokens per minute, not dollars.
- **Token counts per call**, from `usage` in each Messages response. With the published prices the router can estimate its own spend through that key.

With an Admin credential, the Usage and Cost Analytics API can report month-to-date dollars for one API key, typically 4 hours behind and up to 24.

## Method

- Sources are `platform.claude.com/docs` guide and API reference pages, one `support.claude.com` article, and `github.com/anthropics/anthropic-sdk-python` (`api.md` and type files on `main`). Each claim below carries the URL of the page that owns it.
- No call was made to `api.anthropic.com`. Nothing here was confirmed against a live key.
- "Not documented" means I did not find it in these sources. It does not mean the API lacks it.
- The docs use `anthropic-version: 2026-10-21` in their examples.

## 1. What an ordinary workspace key can read

Nothing about balance, spend, or usage.

- The APIs open to a standard key are Messages, Message Batches, Token Counting, Models, Files, and Skills, plus the beta Managed Agents APIs. None reports billing or usage. ([API overview](https://platform.claude.com/docs/en/api/overview))
- The usage and cost endpoints need Admin API credentials: "an Admin API key, an OAuth token with the `org:admin` scope, or a personal or service account key that isn't scoped to a workspace; workspace API keys don't work." ([Usage and Cost API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api))
- The Rate Limits API carries the same sentence. ([Rate Limits API](https://platform.claude.com/docs/en/manage-claude/rate-limits-api))
- The Python SDK's method list has no method whose path or name mentions credit, balance, billing, or invoice. ([api.md](https://github.com/anthropics/anthropic-sdk-python/blob/main/api.md))

One nuance on key types. Anthropic now has three kinds of `sk-ant-api…` key: personal, service account, and workspace (legacy). A personal or service account key that is **not** scoped to one workspace is accepted by the Admin API and "has the same permissions as the linked account". Such a key must send an `anthropic-workspace-id` request header on every Messages call. A key scoped to one workspace, of any kind, is not accepted by the Admin API. ([Authentication](https://platform.claude.com/docs/en/manage-claude/authentication), [Admin API](https://platform.claude.com/docs/en/manage-claude/admin-api))

The Admin API is also not available to individual Console accounts. The account must first set up an organization. ([Admin API](https://platform.claude.com/docs/en/manage-claude/admin-api))

## 2. Admin API usage and cost reports

There are two generations. Both need Admin API credentials (section 1).

### Legacy Usage and Cost API

Marked legacy but still supported. ([Usage and Cost API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api))

| | `GET /v1/organizations/usage_report/messages` | `GET /v1/organizations/cost_report` |
|---|---|---|
| Reports | Token counts | Cost in USD |
| `bucket_width` | `1m`, `1h`, `1d` (default `1d`) | `1d` only |
| `limit` (buckets per page) | `1d`: default 7, max 31. `1h`: default 24, max 168. `1m`: default 60, max 1,440 | Default 7, max 31 |
| `group_by[]` | `api_key_id`, `workspace_id`, `model`, `service_tier`, `context_window`, `inference_geo`, `speed`, `account_id`, `service_account_id` | `workspace_id`, `description` only |
| Filters | `api_key_ids[]`, `workspace_ids[]`, `models[]`, `service_tiers[]`, `context_window[]`, `inference_geos[]`, `speeds[]`, `account_ids[]`, `service_account_ids[]` | None |
| Metric fields | `uncached_input_tokens`, `cache_creation.ephemeral_5m_input_tokens`, `cache_creation.ephemeral_1h_input_tokens`, `cache_read_input_tokens`, `output_tokens`, `server_tool_use.web_search_requests` | `amount`, `currency` (always `"USD"`), and with `group_by[]=description`: `description`, `cost_type`, `model`, `token_type`, `service_tier`, `context_window`, `inference_geo`, `speed` |
| Paging | `has_more`, `next_page` → `page` | Same |

Sources: [usage report reference](https://platform.claude.com/docs/en/api/beta/organization/usage_report/retrieve_messages), [cost report reference](https://platform.claude.com/docs/en/api/beta/organization/cost_report/retrieve).

- **Units.** `amount` is "Cost amount in lowest currency units (e.g. cents) as a decimal string. For example, `"123.45"` in `"USD"` represents `$1.23`." ([cost report reference](https://platform.claude.com/docs/en/api/beta/organization/cost_report/retrieve))
- **Freshness.** "Usage and cost data typically appears within 5 minutes of API request completion, though delays might occasionally be longer." ([Usage and Cost API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api))
- **Polling.** "The API supports polling once per minute for sustained use." No numeric rate limit is given. (same page)
- **Per-key attribution.** Tokens: yes, with `group_by[]=api_key_id` or `api_key_ids[]`. Cost: no. The cost report groups only by workspace and description.
- **Month-to-date dollars.** Yes for the organization or one workspace: request daily buckets from the 1st and sum `amount`. Not for one key.
- The default workspace has `workspace_id: null` in these reports. (same page)
- Priority Tier costs are not in the cost report. Code execution is in the cost report but not the usage report. (same page)

### Usage and Cost Analytics API (beta, recommended by Anthropic)

Needs the header `anthropic-beta: analytics-usage-cost-2026-08-24`. ([Usage and Cost Analytics API](https://platform.claude.com/docs/en/manage-claude/usage-cost-analytics-api))

- **Endpoints.** `GET /v1/organizations/analytics/usage` (tokens and request counts) and `GET /v1/organizations/analytics/cost` (USD).
- **Buckets.** `time_bucket_width` is optional: `1m`, `1h`, or `1d`. Without it and without `group_by[]`, "the response is a single row that totals the whole range". `ending_at` is required when a bucket width is set. `1m` spans at most 24 hours per request.
- **Range.** `starting_at` must be on or after 2026-01-01 and within the last 365 days. One request spans at most 31 days.
- **Grouping.** `group_by[]` takes up to five dimensions, including `api_key_id`, `workspace_id`, `model`, `service_tier`, `context_window`, `inference_geo`, `speed`, `actor`. The cost endpoint adds `cost_type` and `token_type`. Each has a matching list filter, such as `api_key_ids[]`.
- **Cost fields.** `amount` is "the cost after discounts and before any credits are applied". `list_amount` is the cost at list prices. `currency` is always `"USD"`. "Amounts are decimal strings in cents with six decimal places: `"41280.000000"` is $412.80 USD."
- **Usage fields.** The same token fields as the legacy report, plus `total_tokens` and `requests`.
- **Freshness.** Every response has `data_refreshed_at`. "Data typically refreshes within 4 hours of the underlying usage and can take up to 24 hours." Values can be revised "until about 7 days after the end of the calendar month".
- **Rate limit.** The page says an organization-level rate limit carries over from the Claude Enterprise Analytics API. That API's page gives "a default of 60 requests per minute across all endpoints". ([Analytics APIs](https://platform.claude.com/docs/en/manage-claude/analytics-api)) I did not find a separate figure stated for Console organizations.
- **Per-key attribution.** Tokens and cost: yes. "For cost by API key, group by `api_key_id`." ([Usage and Cost API FAQ](https://platform.claude.com/docs/en/manage-claude/usage-cost-api))
- **Month-to-date dollars for one key.** Yes: one call to `/analytics/cost` from the 1st of the month with `api_key_ids[]=apikey_…` and no bucket width returns one row. It lags by hours.
- Requests under a Priority Tier commitment contribute zero token cost. (same page)

## 3. Credit balance and spend limits

- **Credit balance.** No endpoint is documented, for any credential. "Your organization's available credit balance and credit usage are shown on the same Billing page" in the Console. ([How do I pay for my Claude API usage?](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage)) The SDK has no such method. ([api.md](https://github.com/anthropics/anthropic-sdk-python/blob/main/api.md))
- **Organization info.** `GET /v1/organizations/me` returns only `id`, `name`, and `type`. ([organization_info.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/organization_info.py))
- **Organization spend limit.** Viewed and set at `platform.claude.com/settings/spend-limits`. No API read is documented for Console organizations. ([Rate limits](https://platform.claude.com/docs/en/api/rate-limits))
- **Workspace spend limit.** Set on the Console Workspaces page. The `Workspace` object returned by the Admin API has no spend-limit field. ([Workspaces](https://platform.claude.com/docs/en/manage-claude/workspaces), [workspace.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/organization/workspace.py)) The default workspace cannot have a spend limit.
- **Spend Limits API.** `/v1/organizations/spend_limits…` exists, but "is available to Claude Enterprise organizations only. It is not available to Claude Platform (Claude Console) organizations." It covers per-member limits. ([Spend Limits API](https://platform.claude.com/docs/en/manage-claude/spend-limits-api))
- **Tier spend cap.** The cap per usage tier is published: Start $500, Build $1,000, Scale $200,000 per calendar month; Custom has none. It resets at 00:00 UTC on the 1st. ([Rate limits](https://platform.claude.com/docs/en/api/rate-limits)) Which tier an organization is on is shown in the Console. An API read of the tier is not documented.

Open lead: the API reference lists a beta header value `spend-limit-reads-2026-09-26`. I found no page that says what it enables or for which organizations.

## 4. Response headers on Messages calls

All names below are from [Rate limits: Response headers](https://platform.claude.com/docs/en/api/rate-limits#response-headers) unless noted.

| Header | Meaning |
|---|---|
| `retry-after` | Seconds to wait before retrying. Not on every 429; never on the spend-cap 429. |
| `anthropic-ratelimit-requests-limit` / `-remaining` / `-reset` | Requests allowed, requests left, and the RFC 3339 time the limit is fully replenished. |
| `anthropic-ratelimit-tokens-limit` / `-remaining` / `-reset` | The most restrictive token limit now in effect. If no workspace limit applies, it is input plus output tokens. |
| `anthropic-ratelimit-input-tokens-limit` / `-remaining` / `-reset` | Input tokens per minute. |
| `anthropic-ratelimit-output-tokens-limit` / `-remaining` / `-reset` | Output tokens per minute. |
| `anthropic-priority-input-tokens-*`, `anthropic-priority-output-tokens-*` (`limit` / `remaining` / `reset`) | Priority Tier only. The commitment "is no longer sold". ([Service tiers](https://platform.claude.com/docs/en/api/service-tiers)) |
| `anthropic-fast-input-tokens-*`, `anthropic-fast-output-tokens-*` (`limit` / `remaining` / `reset`) | Fast mode limits, on fast mode requests. ([Fast mode](https://platform.claude.com/docs/en/build-with-claude/fast-mode)) |
| `request-id` | Unique request ID. ([API overview](https://platform.claude.com/docs/en/api/overview#response-headers)) |
| `anthropic-organization-id` | The organization the key belongs to. (same) |
| `anthropic-workspace-id` | The `wrkspc_` ID the key resolved to, including the default workspace. (same) |

Could they drive a "remaining this minute" tile with no extra calls? Yes, with these limits:

- The limits are per model class and are set for the organization, or the workspace if it has lower ones. They are not per key. Every key in the organization draws from the same pool.
- The token `-remaining` values are "rounded to the nearest thousand".
- The API uses a token bucket: "capacity is continuously replenished up to your maximum limit, rather than being reset at fixed intervals". `-reset` is the time of full replenishment, not a window boundary.
- Only uncached input tokens and cache writes count toward the input limit. Cache reads do not.
- The numbers update only when a request goes through the key. An idle key shows a stale value. A tile needs one value per model class, or it shows only the last model used.
- No header reports dollars, credit, or spend.

Whether these headers are also sent on non-Messages endpoints such as `GET /v1/models`, or on error responses other than 429, is not documented.

## 5. Listing configured rate limits

The Rate Limits API is part of the Admin API. Workspace keys do not work. ([Rate Limits API](https://platform.claude.com/docs/en/manage-claude/rate-limits-api))

- `GET /v1/organizations/rate_limits` returns one entry per rate limit group. Each has `id`, `group` (`type`, `id`, and `display_name` for model groups), `models` (every model ID and alias in the group), and `limits`, a list of `{type, value}` such as `requests_per_minute`, `input_tokens_per_minute`, `output_tokens_per_minute`. A `model` query parameter returns the one group holding that model.
- `GET /v1/organizations/workspaces/{workspace_id}/rate_limits` returns the workspace's overrides. With `include_inherited=true` it returns every applicable limit, each with `org_limit` and a `source` of `workspace` or `organization`.
- `POST /v1/organizations/workspaces/{workspace_id}/rate_limits/{rate_limit_id}` sets or clears overrides. Changes take effect "within about an hour".
- It returns rate limits only. Spend limits are not in it.

With an ordinary key, the same limit values arrive in the `-limit` headers of section 4, one model class at a time.

## 6. What a key can learn about itself

- **Ordinary key.** No "whoami" or key-info endpoint is documented. The key learns its organization ID and workspace ID from the `anthropic-organization-id` and `anthropic-workspace-id` response headers. ([API overview](https://platform.claude.com/docs/en/api/overview#response-headers)) Its own `apikey_…` ID, name, and expiry are not exposed to it.
- **Admin API.** `GET /v1/organizations/api_keys` and `GET /v1/organizations/api_keys/{api_key_id}` return `id`, `name`, `created_at`, `created_by`, `expires_at`, `partial_key_hint` (such as `sk-ant-api03-R2D...igAA`), `principal`, `scope` (the workspace ID, or `organization`), and `status` (`active`, `inactive`, `archived`, `expired`). There is no spend, usage, or limit field. ([Retrieve API Key](https://platform.claude.com/docs/en/api/organization/api_keys/retrieve))
- The Admin API cannot create keys. (Admin API FAQ, [Admin API](https://platform.claude.com/docs/en/manage-claude/admin-api))

## 7. Computing spend in the router

It is feasible as an estimate. Each Messages response carries what is needed.

`usage` fields ([usage.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/usage.py)):

- `input_tokens`: tokens after the last cache breakpoint, not all input. ([Rate limits](https://platform.claude.com/docs/en/api/rate-limits))
- `cache_creation_input_tokens`, split by `cache_creation.ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`.
- `cache_read_input_tokens`.
- `output_tokens`: "the inclusive, authoritative total used for billing".
- `server_tool_use.web_search_requests` and `web_fetch_requests`.
- `service_tier` (`standard`, `priority`, `batch`), `speed` (`standard`, `fast`), `inference_geo`.

In a stream, the `usage` counts in `message_delta` are cumulative. ([Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming))

Caveats, all from [Pricing](https://platform.claude.com/docs/en/about-claude/pricing) unless noted:

- **Prices change.** The page defers to `claude.com/pricing` for current prices. The router needs a price table per model that someone keeps up to date. A model with no entry has no cost.
- **Cache multipliers.** A 5-minute cache write is 1.25x base input. A 1-hour write is 2x. A cache read is 0.1x on most models, 0.05x on Opus 5.5 and Sonnet 5.5, and 0.025x on Fable 5.1/5.2 and Mythos 5.1/5.2.
- **Long context.** Most current models bill the full 1M window at the standard rate. Claude Haiku 5.5 does not: a request whose prompt is over 100,000 tokens, counting cache reads and writes, pays 5x prices for that whole request.
- **Fast mode.** Priced separately per model, for example $8 / $40 per MTok on Opus 5.5 against $4 / $20 standard. It stacks with cache and data-residency multipliers. `usage.speed` says which applied.
- **Data residency.** `inference_geo: "us"` multiplies every token price by 1.1 on Claude 4.6 and later.
- **Batch.** 50% off input and output. It applies only to the Message Batches API.
- **Priority Tier.** Covered requests cost zero per token; the commitment is billed separately. ([Usage and Cost Analytics API](https://platform.claude.com/docs/en/manage-claude/usage-cost-analytics-api))
- **Server tools.** Web search is $10 per 1,000 searches plus tokens. Web fetch has no extra charge. Code execution is billed by container time, which `usage` token counts do not show.
- **Discounts.** The estimate is at list price. Anthropic's own `amount` is after discounts.
- **Scope.** The router sees only its own calls. Spend through the same key elsewhere, or through other keys in the organization, is invisible to it. It measures spend, never balance.
- **Charged failures.** "A request that times out while on track to succeed is still charged." The router records Token Usage only for successful calls, so such a call would be missed. ([How do I pay for my Claude API usage?](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage))

## Exhaustion signals

Not a meter, but the tile and Key Failover need these. They differ from OpenRouter's 402.

| Condition | Response | Source |
|---|---|---|
| Credit balance exhausted | Message "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits." The status code is not stated on that page. | [API credits for subscribers](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers) |
| Billing or payment problem | 402 `billing_error` | [Errors](https://platform.claude.com/docs/en/api/errors) |
| Tier monthly spend cap reached | 429 `rate_limit_error`, `error.details.error_code` = `enforced_spend_limit_reached`, no `retry-after`. Lasts until 00:00 UTC on the 1st. | [Rate limits](https://platform.claude.com/docs/en/api/rate-limits#reaching-your-spend-cap) |
| Spend limit the owner set (organization or workspace) | 400 `invalid_request_error`. Message starts "You have reached your specified API usage limits" or "You have reached your specified workspace API usage limits". | [Rate limits](https://platform.claude.com/docs/en/api/rate-limits#setting-your-own-spend-limit) |
| Ordinary rate limit | 429 `rate_limit_error`, usually with `retry-after` | [Rate limits](https://platform.claude.com/docs/en/api/rate-limits) |

`is_credit_exhaustion` in `src/domain/extra_usage.py` matches only a 402 with `insufficient credits` or `payment_required`. None of the Anthropic responses above match it.

## Options for the Portal tile

| Meter | Credential | Extra upstream calls | Closest existing meter | Notes |
|---|---|---|---|---|
| Remaining prepaid credit | None works | — | Account Credit Remaining | Not feasible. No documented endpoint. |
| Router-estimated spend this month | Ordinary key | None | Key Monthly Limit, the "used" half | Computed from `usage` and a price table. An estimate, and only of router traffic. |
| Router-estimated spend out of an owner-entered monthly amount | Ordinary key, plus a number typed into config | None | Key Monthly Limit (`$X of $Y used`, resets on the 1st at 00:00 UTC) | `$Y` is the workspace or organization spend limit set in the Console, or the tier cap. Anthropic does not expose it, so it can drift. |
| Rate-limit headroom per model class | Ordinary key | None | None. It is requests and tokens per minute. | From `anthropic-ratelimit-*` headers. Shared by the whole organization. Stale when idle. |
| Month-to-date cost for this key, from Anthropic | Admin credential | One `GET /v1/organizations/analytics/cost` per refresh | Key Monthly Limit, the "used" half | Typically 4 hours behind, up to 24. After discounts, before credits. No cap is returned. |
| Month-to-date cost for the workspace or organization | Admin credential | One `GET /v1/organizations/cost_report` per refresh | Included Monthly Usage, the "used" half | About 5 minutes behind. Not per key. |
| Month-to-date tokens for this key | Admin credential | One `GET /v1/organizations/usage_report/messages` per refresh | None | About 5 minutes behind. Tokens, not dollars. |
| Configured rate limits | Admin credential | One `GET /v1/organizations/rate_limits` | None | The `-limit` headers give the same values without an Admin key. |

## Recommendation

With one ordinary key and no Admin key, Anthropic reports no dollar figure at all, so the tile cannot show Account Credit Remaining or any upstream-reported meter. The honest choice is a router-computed estimate: month-to-date spend through that key, priced from the `usage` the router already receives on each call, reset at 00:00 UTC on the 1st to line up with Anthropic's own monthly limits. If the owner sets a spend limit on the key's workspace in the Console and enters the same amount in router config, the tile can read `$X of $Y used` in the shape of Key Monthly Limit. It needs its own glossary term, because it is an estimate of router traffic at list price and not a number Anthropic reported; the tile should say so. Rate-limit headroom from the response headers is free to add but answers a different question and is shared across the organization, so it belongs beside the dollar meter, not in its place. Whatever the tile shows, the router should recognise the Anthropic exhaustion responses listed above, since the meter cannot warn of an empty balance. If the owner later provides an Admin credential, `GET /v1/organizations/analytics/cost` filtered to the key can replace the estimate with Anthropic's own figure, at the cost of a lag of hours.
