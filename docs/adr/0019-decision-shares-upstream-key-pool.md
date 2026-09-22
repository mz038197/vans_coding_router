# Decision shares the provider key pool with chat

A Decision Request draws the same upstream keys as chat for that provider. Extra Usage Exhaustion and Credit Exhaustion follow the same Key Failover and Key Quarantine rules, so a quarantined key is not selected for either kind of call. Quarantine is a property of the key, and one provider does not keep a second pool for Decision.

## Considered Options

- **A separate Decision key pool**: rejected. Teachers would maintain two pools for one provider, and quarantine would no longer mean the key itself is out.
