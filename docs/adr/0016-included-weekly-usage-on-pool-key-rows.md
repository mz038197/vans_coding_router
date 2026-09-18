# Portal pool rows show Included Weekly Usage, not Extra Usage Remaining

Status: superseded by ADR 0017 (live usage document uses `limits.monthly`, not weekly).

`GET https://ollama.com/api/usage` returns included session/weekly used fractions and `activity.cost`; it does not return Extra Usage Remaining. Teachers treated "額度無法取得" as a fault, so each `ollama_cloud` key row shows Included Weekly Usage (`limits.weekly.usage`, already-used 0–1) next to in-flight and Key Quarantine. The teacher API field is `included_weekly_usage`; Portal copy is `週用量 N%` (integer percent of the used fraction) or `週用量無法取得`. Do not show Extra Usage Remaining, session usage, credits, or `activity.cost`. Do not invert the fraction into remaining. Failover and Key Quarantine stay Extra Usage Exhaustion / Credit Exhaustion; Included Weekly Usage is display only.

This supersedes the displayed quantity in ADR 0015. Backend-proxied usage, per-row failure, and no separate usage panel stay as in ADR 0014 and ADR 0015.
