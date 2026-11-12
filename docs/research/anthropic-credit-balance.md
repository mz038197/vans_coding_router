# Anthropic credit balance

Researched on 2026-11-12 against Anthropic's official docs, API reference, Help Center, and the official Python and TypeScript SDK source. The question: can a program read the **remaining prepaid credit balance** (dollars left) of an Anthropic Claude API organization, so the Portal tile "餘額" can show it the way it shows OpenRouter's `GET /credits`? The owner has one ordinary workspace key and might create an Admin API key.

Usage and cost reports, rate-limit headers, and the router-side spend estimate are covered in [Anthropic upstream metering](anthropic-upstream-metering.md). This note does not repeat them.

## Result

**No official API returns the prepaid credit balance, with any credential.** That includes the Admin API, the Spend Limits API (stable and beta), the Claude Enterprise Analytics API, and the Usage and Cost Analytics API. The balance is shown only on the Console Billing page. ([How do I pay for my Claude API usage?](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage))

What has changed since the sibling note was written: the open lead `spend-limit-reads-2026-09-26` is now explained. It gates a beta `GET /v1/organizations/spend_limits` that **does** cover Claude Console organizations, as an early access preview. It returns the configured organization, workspace, and usage-tier **limits**. It does not return spend against them, and it does not return the balance.

So the best that an Admin key can give is a derived figure: "remaining under this month's spend limit" = a limit (from the beta list, or typed into config) minus month-to-date cost (from the Usage and Cost Analytics API). That is not the balance.

## Method

- Sources: `platform.claude.com/docs` guide and API reference pages, `support.claude.com` articles, `anthropic.com/legal/commercial-terms`, and the SDKs' `api.md` and type files on `main` ([anthropic-sdk-python](https://github.com/anthropics/anthropic-sdk-python) at commit `5139cf2`, 2026-11-10; [anthropic-sdk-typescript](https://github.com/anthropics/anthropic-sdk-typescript) `api.md`).
- I searched both SDKs' `api.md` for `credit`, `balance`, `billing`, `prepaid`, `invoice`, `grant`, `spend`, `cost`, `auto_reload`. Every HTTP path that matched is listed in section 1.
- No call was made to `api.anthropic.com` or to the Console. Nothing here was confirmed against a live key.
- "Not documented" means I did not find it in these sources. Third-party claims are marked **unverified**.

## 1. Official endpoints that mention money

Every `/v1/…` path in the SDKs whose name contains credit, balance, billing, prepaid, invoice, grant, spend, or cost. Both SDKs list the same set. ([py api.md](https://github.com/anthropics/anthropic-sdk-python/blob/main/api.md) lines 1136–1182 and 3319–3420; [ts api.md](https://github.com/anthropics/anthropic-sdk-typescript/blob/main/api.md) lines 1065–1082 and 2955–3029)

| Path | SDK resource | Returns |
|---|---|---|
| `GET /v1/organizations/analytics/cost` | `client.beta.organization.analytics.cost` | Cost in USD. See the sibling note. |
| `GET /v1/organizations/analytics/cost_report`, `…/user_cost_report` | `client.beta.organization.analytics.*` | Legacy Claude Enterprise cost reports. |
| `GET /v1/organizations/spend_limits` | `client.beta.organization.spend_limits.list` | Configured spend limits (section 2). Beta only. |
| `GET /v1/organizations/spend_limits/{id}` | `…spend_limits.retrieve` | One configured spend limit. |
| `POST /v1/organizations/spend_limits` | `…spend_limits.set` (beta) | Upserts a limit. |
| `DELETE /v1/organizations/spend_limits/{id}` | `…spend_limits.delete` (beta) | Removes a limit. |
| `GET /v1/organizations/spend_limits/effective` | `client.organization.spend_limits.effective` and the beta twin | Per-member limit and period-to-date spend. Enterprise only. |
| `…/spend_limit_increase_requests…` (list, get, approve, deny) | `…spend_limits.increase_requests` | Enterprise members' requests for more usage. |

No path contains `credit`, `balance`, `billing`, `prepaid`, `invoice`, or `grant`. The only SDK names with "credit" or "billing" are unrelated types:

- `BillingError` / `BetaBillingError` (`type: "billing_error"`), the 402 error body. ([beta_billing_error.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/beta_billing_error.py))
- `BetaFallbackCredit*`, which reports whether a refusal-retry "reprice" was applied to one request (beta `fallback-credit-2026-07-01`). It has no balance. ([beta_fallback_credit_usage.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/beta/beta_fallback_credit_usage.py))
- `NoBillingWorkspaceRole`, a workspace role name.

`GET /v1/organizations/me` returns only `id`, `name`, `type`. (sibling note, section 3)

### Claude Enterprise Analytics API

Not a source of balance. It reports engagement and adoption, plus cost and usage, for **Claude Enterprise** organizations. It uses an Analytics API key created in claude.ai by the primary owner, not a Console Admin key. "The cost and usage endpoints apply to usage-based Enterprise plans; for seat-based Enterprise plans, they reflect usage credits only." Rate limit 60 requests per minute per organization. ([Analytics APIs](https://platform.claude.com/docs/en/manage-claude/analytics-api)) No balance or credit field is documented.

### Usage and Cost Analytics API

Covered in the sibling note. One point matters here: its `amount` is "post-discount, pre-credit". ([beta_analytics_cost_metrics.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/beta/organization/analytics/beta_analytics_cost_metrics.py)) So cost is not "credit consumed", and the API does not say how much was paid from credits.

## 2. Spend Limits API

There are two documented scopes of availability, and they disagree for Console organizations.

### What the guide says (Enterprise only)

- "The Spend Limits API is available to Claude Enterprise organizations only. It is not available to Claude Platform (Claude Console) organizations." Prerequisites: an Enterprise plan with usage credits turned on. ([Spend Limits API](https://platform.claude.com/docs/en/manage-claude/spend-limits-api))
- **Credential.** An Enterprise key from claude.ai with scope `read:spend_limits` (GET) or `write:spend_limits` (POST, DELETE). ([Create an Admin API key](https://platform.claude.com/docs/en/manage-claude/admin-api-keys))
- **Eight endpoints.** Four on spend limits, four on increase requests (table in section 1).
- **Writes.** `POST` sets only per-user overrides (`scope.type: "user"`). Seat-tier, group, and organization defaults are set in claude.ai.
- **Spend against the limit: yes, per member.** `GET /v1/organizations/spend_limits/effective` returns one row per member with `amount` (the effective limit, `null` = unlimited, `"0"` = included usage only), `currency`, `period`, `source` (`user`, `seat_tier`, `rbac_group`, `organization`), `spend_limit_id`, and `period_to_date_spend`.
- **Units.** Strings in minor units of the billing currency: `"50000"` is $500.00. `period_to_date_spend` can have fractional cents, such as `"41280.125"`.
- **Freshness.** `period_to_date_spend` "might read as `"0"` if the spend reading is temporarily unavailable; treat it as informational, not transactional." No lag figure is given.
- **Period.** Only `monthly`, reset at 00:00 UTC on the 1st. (The beta type also lists `daily` and `weekly`. [beta_spend_limit_period.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/beta/organization/beta_spend_limit_period.py))
- **Rate limit.** 60 requests per minute per organization, shared by all eight endpoints.

### What the beta reference and SDK say (Console too, early access)

- **`GET /v1/organizations/spend_limits`** needs the header `anthropic-beta: spend-limit-reads-2026-09-26`. "A Claude Console organization's limits, including any read-only `usage_tier` limit, come newest first. Listing them is in an early access preview. To request access, contact your Anthropic account team." ([List Spend Limits](https://platform.claude.com/docs/en/api/beta/organization/spend_limits/list); [spend_limits.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/resources/beta/organization/spend_limits/spend_limits.py) lines 141–176)
- **Console scopes.** `organization`, `workspace` (with `workspace_id`), and `usage_tier`. The `usage_tier` row is "the monthly spend cap Anthropic sets for a Claude Console organization from its usage tier, or a higher cap Anthropic granted the organization. Read-only". Its timestamps are the organization's creation time, "so `amount` can change while `updated_at` stays the same." ([beta_spend_limit_usage_tier_scope.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/beta/organization/beta_spend_limit_usage_tier_scope.py) lines 9–18)
- **Filters.** `scope_type[]` (a type that does not apply to the organization returns 400), `workspace_id` ("Claude Console organizations only"), `limit` (default 20, max 1000), `page`. ([spend_limit_list_params.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/beta/organization/spend_limit_list_params.py))
- **Fields per limit.** `id` (`spl_…`), `amount` (minor units, nullable), `currency`, `is_enabled` ("`false` when extra usage is switched off for this organization (`organization` limit)"), `period`, `scope`, `created_at`, `updated_at`, `type: "spend_limit"`. **No spend, used, or remaining field.** ([beta_spend_limit.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/beta/organization/beta_spend_limit.py))
- **Writes for Console.** "A Claude Console organization sets `organization` and `workspace` limits, which are monthly and always carry an amount. Setting those limits is in an early access preview." Delete can remove those, not `usage_tier`. ([spend_limits.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/resources/beta/organization/spend_limits/spend_limits.py) lines 218–230, 276–288)
- **Spend against the limit for Console: no.** The effective report is "Supported for Claude Enterprise organizations only, not for Claude Console organizations." ([effective.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/resources/beta/organization/spend_limits/effective.py) lines 59–64)
- **Not-enabled error.** `error_code: "spend_limits_admin_api_writes_not_enabled"`: "The organization cannot retrieve, set or delete spend limits with an Admin API credential." ([beta_spend_limits_admin_api_writes_not_enabled_error_details.py](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/beta/organization/beta_spend_limits_admin_api_writes_not_enabled_error_details.py)) The list method can also raise `OrganizationTypeNotSupportedError`.
- **Credential for Console.** Console Admin keys (`sk-ant-admin01-…`) "do not have selectable scopes; every key carries full access to all endpoints that accept Admin API keys". The key page does not list the Spend Limits API among the APIs a Console key works with. ([Create an Admin API key](https://platform.claude.com/docs/en/manage-claude/admin-api-keys)) Whether a Console Admin key reaches the beta list after early access is granted is not documented beyond the reference page above.

### What this gives the tile

With an Admin key and early access, the router can read the organization limit, a workspace limit, and the tier cap. With no early access, the owner can type the same number into config. Either way, "remaining under the limit" must be computed as limit minus month-to-date cost from `GET /v1/organizations/analytics/cost` (sibling note, section 2), which lags by hours and is pre-credit. Without an Admin key neither number is readable.

A spend limit is a cap on monthly spend, not money held. An organization with $20 of credit and a $500 limit stops at $20.

## 3. Console internal endpoints

- The Billing page at `platform.claude.com/settings/billing` shows "available credit balance and credit usage". ([How do I pay for my Claude API usage?](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage)) Promotional credits from Max, Ultra, and Team plans appear in its **Promotional credits** section "with the amount and expiry date". ([API credits for subscribers](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers))
- No official source documents, names, or sanctions any endpoint behind that page for programmatic use. Nothing says an API key or Admin key works there. Its stability, auth, and rate limits are not documented. I did not call it.
- Terms. The Commercial Terms have no clause that expressly bans scripted access to the Console. The nearest is D.4: customer may not "reverse engineer or duplicate the Services". ([Commercial Terms](https://www.anthropic.com/legal/commercial-terms)) The Usage Policy, incorporated by D.2, was not checked. Calling undocumented Console endpoints would likely need the owner's browser session rather than an API key; that is my inference, not documented. It is unsupported and could break or breach terms without notice, so this note does not treat it as an option.

## 4. Auto-reload and low-balance notifications

- **Auto-reload: documented, Console only, no API.** "Auto-reload purchases additional credits automatically when your balance falls below a threshold you set." The owner sets **When credit balance reaches** (the trigger) and **Bring credit balance back up to** (the target) on the Billing page. Turning it on at or below the trigger charges at once. ([How do I pay for my Claude API usage?](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage))
- With plan-included API credits, "Auto-reload is based only on your purchased balance. It reloads when that balance reaches your threshold, even if included credits remain." Included credits are spent first. ([API credits for subscribers](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers))
- **Low-balance email: not documented** for Console credit. The payment article does not mention one.
- **Workspace spend alerts: documented, spend not balance.** On the Workspaces page, **Spend limits** lets the owner "cap monthly spending and configure alerts when spending reaches certain thresholds". ([Workspaces](https://platform.claude.com/docs/en/manage-claude/workspaces)) The channel (email) and recipients are not stated on that page. No API reads or sets these alerts.
- **Webhooks: none for billing.** Organization webhooks (beta `webhooks-2026-10-07`) have only `user_profile.enforcement_action_opened` and `…_resolved`. Managed Agents webhooks cover sessions, agents, deployments, vaults, environments, memory stores. ([Organization webhooks](https://platform.claude.com/docs/en/manage-claude/organization-webhooks), [Managed Agents webhooks](https://platform.claude.com/docs/en/managed-agents/webhooks)) No balance, credit, or spend event is documented.

## 5. Invoices, receipts, credit grants

- **Invoices.** Monthly-invoiced customers get "an invoice from Stripe" at the end of each calendar month. "Expired credits appear in your Invoice history on the Billing page." ([How do I pay for my Claude API usage?](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage)) No API to list or read invoices is documented, and none is in either SDK.
- **Purchases and grants.** Purchased credits "expire one year from the purchase date". Plan-included credits expire at the end of each billing cycle with no rollover. (same pages) No API lists purchases, grants, promotional credits, or expiry dates.
- **Billing exports.** Not documented. The Console **Cost** page is the documented place to track spend. ([API credits for subscribers](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers))

## 6. What happens at zero balance

| Source | What it says |
|---|---|
| [How do I pay for my Claude API usage?](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage) | "If you run out of credits, you can no longer call the API or use the playground until you add more." |
| [API credits for subscribers](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers) | Message: "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits." Status code and error `type` are **not documented**. Organizations invoiced through Anthropic sales are billed as usual past the credits. |
| [Errors](https://platform.claude.com/docs/en/api/errors) | 402 `billing_error`: "There's an issue with your billing or payment information." The page does not tie 402 to an empty balance. |

**Unverified (third-party):** several GitHub issue reports say the "credit balance is too low" message comes as **HTTP 400 `invalid_request_error`**, not 402. ([crmne/ruby_llm #1006](https://github.com/crmne/ruby_llm/issues/1006); also issues on `anthropics/claude-code`, which are user reports, not docs.) Do not rely on the status. Match the message text, and treat 402 `billing_error` as a second exhaustion signal.

The other stop conditions (tier cap 429 `enforced_spend_limit_reached`, own-limit 400) are in the sibling note's "Exhaustion signals" table.

## Ways to get the balance

Ranked by how close the number is to "dollars left". None returns the real balance.

| # | What the tile shows | Real or derived | Credential | Extra calls | Notes |
|---|---|---|---|---|---|
| 1 | Prepaid credit balance | Real | None works | — | Not feasible. No documented API (sections 1, 3). |
| 2 | Remaining under this month's spend limit: limit − month-to-date cost | Derived from two Anthropic numbers | Console Admin key **and** early access to `spend-limit-reads-2026-09-26` | One `GET /v1/organizations/spend_limits` (rarely) plus one `GET /v1/organizations/analytics/cost` per refresh | Limit is current. Cost lags hours, is pre-credit, and is org- or workspace-wide unless filtered by key. Says nothing about credit left. |
| 3 | Remaining under an owner-entered monthly limit | Derived | Console Admin key | One `GET /v1/organizations/analytics/cost` per refresh | As 2, without early access. The typed limit can drift from the Console. |
| 4 | Owner-entered balance snapshot − Anthropic cost since the snapshot | Derived, an approximation of balance | Console Admin key | As 3 | The only route that tracks the balance itself. Breaks silently on top-ups, auto-reload, plan credits arriving, expiry, and discounts vs credits (cost is post-discount, pre-credit). Needs the owner to re-enter the balance after each change. |
| 5 | Router-estimated spend | Estimate of router traffic only | Ordinary key | None | Sibling note, section 7. |
| 6 | "Exhausted" flag | Real event | Ordinary key | None | From the zero-balance message (section 6). It tells you the balance hit zero, never how much is left. |

## Recommendation

The Anthropic tile cannot show a real "餘額". No Anthropic API reports the prepaid balance, and the only page that does is the Console Billing page, which has no sanctioned programmatic access. Do not build on Console internals.

Do not label any derived number "餘額". If the owner creates a Console Admin key, show option 3 as month-to-date spend against a monthly limit (`$X of $Y this month`), taking `$X` from `GET /v1/organizations/analytics/cost` and `$Y` from config. Upgrade to option 2 only if Anthropic grants early access to the spend-limit reads; then `$Y` comes from the organization or workspace limit, or the `usage_tier` cap, and cannot drift. Option 4 looks like a balance but goes wrong after every top-up or auto-reload, so offer it only if the owner wants to keep re-entering the balance. Without an Admin key, keep the router estimate from the sibling note. In every case, add option 6: match "Your credit balance is too low" (and 402 `billing_error`) so the tile and Key Failover show the key as out of credit, since nothing else will warn first. Recommend the owner turn on auto-reload in the Console, since that is the only documented guard against reaching zero.
