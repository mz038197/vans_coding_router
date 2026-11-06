# OpenRouter tiles lead with the Key Monthly Limit when a key has one

Status: superseded by ADR 0044 for the tile layout (the headline is Account Credit Remaining). How the cap is read, cached and sanitized still holds.

Amends ADR 0026. An OpenRouter key whose spending cap is set in OpenRouter with a monthly reset now leads its 我的課程 upstream tile with the Key Monthly Limit, shaped like the Ollama tile: `$X of $Y used`, a meter, 快用完 at 90%, and `Resets in …`. Account Credit Remaining (`餘額 $…`) moves to that tile's sub line, and 餘額偏低 below $5 still warns, because a key under its cap still fails when its account has no credit. A key with no cap, or a cap that resets daily or weekly, keeps the ADR 0026 tile: Account Credit Remaining as the headline, no meter.

The router reads each key's own `GET /key` document server-side. Used is `limit - limit_remaining`; the reset is 00:00 UTC on the next 1st. Only the sanitized meter reaches the browser (ADR 0014 boundary).

## Considered Options

- **Account wallet as the meter (remaining ÷ total purchased)**: rejected. The denominator grows with every top-up, so the bar stops meaning "nearly out".
- **A budget written in router config**: rejected. It duplicates a cap OpenRouter already enforces and reports.
- **Keep the 0026 rejection of per-key caps**: rejected for keys that have a monthly cap. 0026's worry was an unset cap reading as unavailable; a key with no cap now falls back to the balance tile instead.

## Consequences

- A meter is cached for 45 seconds like the other overlays. A key with no cap is asked again on every refresh, so a cap set in OpenRouter shows on the next refresh.
- One key's failed `/key` fetch drops only that tile to the balance layout until the next refresh.
- Quarantine, Quarantine Release, and Credit Exhaustion are unchanged; the meter is display-only.
