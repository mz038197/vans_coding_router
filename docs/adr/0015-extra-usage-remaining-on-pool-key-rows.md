# Extra Usage Remaining lives on ollama_cloud pool key rows

Show Extra Usage Remaining on each existing `ollama_cloud` key row next to in-flight and Key Quarantine, using the same teacher permission as the upstream pools monitor. Do not add a separate usage panel. Do not display credits or other Ollama balances (including included session or weekly usage).

If `OLLAMA_CLOUD_API_KEY_2` is unset, only configured keys appear, matching existing pool rows. Unavailable Extra Usage Remaining uses "—" or "額度無法取得" on that row only.

This keeps Extra Usage Remaining a row-level fact for Key Failover and Key Quarantine, instead of a second dashboard that teachers would have to reconcile with the pool.
