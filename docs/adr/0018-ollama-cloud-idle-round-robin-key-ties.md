# ollama_cloud breaks least-in-flight ties with round-robin

Least-in-flight on a two-key `ollama_cloud` pool always picked index 0 when both keys were idle, so sporadic classroom traffic burned one Ollama account while bursty traffic looked even. For `ollama_cloud` only, equal in-flight (including both idle) rotates to the next key after the last successful acquire; unequal load still prefers the quieter key. Other providers keep lowest-index ties. Selection is not Key Failover: Failover and Key Quarantine stay Extra Usage Exhaustion / Credit Exhaustion. Included Monthly Usage stays display-only. The cursor is in-process, follows the key actually acquired (including Failover retries; no phantom rotation over a quarantined key), and is N-way.

## Considered Options

- **Route by Included Monthly Usage or Extra Usage Remaining**: rejected. Usage documents are cached and can fail per key; they are not a routing signal.
- **Strict round-robin ignoring in-flight**: rejected. It would pile onto a busy key and fight `max_concurrent_per_key`.
- **Round-robin ties on every provider pool**: rejected. Only Ollama accounts showed the idle-imbalance problem; OpenRouter and others keep pin-to-first when idle.
