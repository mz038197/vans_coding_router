# OpenRouter pool rows show Account Credit Remaining

Teachers read OpenRouter credit on the same 上游負載 key row where `ollama_cloud` shows Included Monthly Usage. The cell is Account Credit Remaining: remaining prepaid dollars on the OpenRouter account that key draws from (`total_credits` minus `total_usage` on that key's credits document). Every key on one account shows the same remaining. Portal copy is `餘額 $15.14` (two decimal dollars), including `餘額 $0.00` and a negative such as `餘額 -$0.12`. A missing or unreadable document is `餘額無法取得` on that row only. The overlay is display-only. It does not Key Quarantine or Key Failover. Ollama rows stay Included Monthly Usage.

## Considered Options

- **Same shape as 月用量 (already-used fraction)**: rejected. OpenRouter's operable number is remaining account dollars, not a 0–1 included-plan fraction.
- **Per-key `limit_remaining`**: rejected. An unset spending cap is null, so the cell would read unavailable while the account still has dollars. A later cap still stays off this cell; Credit Exhaustion on that cap is unchanged.
- **That key's own usage**: rejected. It is not the account wallet.
- **Remaining plus purchased total**: rejected. The cell is the remaining balance only.

## Consequences

- The router fetches the credits document server-side and returns only the sanitized overlay on the existing teacher upstream-pools path. Provider keys stay off the browser (same boundary as ADR 0014).
- One key's failed fetch does not blank a sibling row, hide in-flight, or fail the monitor page. Zero and negative amounts are the balance, not unavailability.
- A row can show account dollars while that key is already in Credit Exhaustion from a per-key spending cap.
