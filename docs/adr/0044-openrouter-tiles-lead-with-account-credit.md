# OpenRouter tiles lead with Account Credit Remaining

Status: accepted. Amended by ADR 0047 (concurrency moves from the sub line to the in-flight light).

Supersedes ADR 0042 for the 我的課程 tile layout. Every OpenRouter tile now leads with that key's Account Credit Remaining (`餘額 $…`), whether or not the key has a Key Monthly Limit. A key with a monthly cap adds the cap's meter under the headline and a sub line `月上限 $X of $Y used · Resets in … · 併發 n/m`. 快用完 still shows at 90% of the cap, 餘額偏低 still shows below $5, and a quarantined key still shows 隔離中 with 解除隔離 in place of the concurrency. A key with no cap is unchanged: the balance and its concurrency, no meter.

Ollama tiles are unchanged and still lead with Included Monthly Usage.

What 0042 decided about reading the cap still holds: the router reads each key's own `GET /key` document server-side, used is `limit - limit_remaining`, the meter is cached for 45 seconds, and only the sanitized meter reaches the browser.

## Considered Options

- **Keep 0042: the cap as the headline when a key has one.** Rejected. The tiles now sit in a narrow rail where the headline is the one number a teacher reads at a glance, and running out of credit stops every key on that account, while a cap only stops one key. Leading with the balance also makes every OpenRouter tile read the same way, cap or not.

## Consequences

- The cap is still visible on the tile and still warns at 90%, so nothing 0042 surfaced is lost, only demoted to the sub line.
