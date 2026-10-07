# A Revocation List copy older than 600 seconds is refused

vans-mcp-server and pokemon-world-mcp refuse student calls until they have a Revocation List copy. After that, a failed refresh keeps the previous copy for 600 seconds, measured from the last success. Past that, both services refuse every student call. The bound is the same during a sitting. The router's own calls use its records and do not wait on this copy.

A failed refresh sends an ERROR Signal through the service's existing forwarder. A student refusal, including one caused by a stale copy, is not an ERROR.

## Considered Options

- **A longer bound, or a longer bound during a sitting**: rejected. A closed sitting or a key ended by a newer one would keep working on MCP for the whole outage.
- **Keep the last copy with no age limit**: rejected. A refresh that never recovers would leave those refusals unset for good.
