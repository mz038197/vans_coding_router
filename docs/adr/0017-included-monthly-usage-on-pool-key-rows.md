# Portal pool rows show Included Monthly Usage

Live `GET https://ollama.com/api/usage` returns `limits.monthly.usage` (already-used 0–1), not `limits.weekly.usage`. Mapping only weekly made both keys look unavailable after a 200. Each `ollama_cloud` key row shows Included Monthly Usage. Teacher field `included_monthly_usage`; Portal copy `月用量 N%` or `月用量無法取得`. Weekly used fraction is a fallback if monthly is absent. Do not invert remaining. Failover stays Extra Usage Exhaustion / Credit Exhaustion.

This supersedes the displayed window in ADR 0016.
