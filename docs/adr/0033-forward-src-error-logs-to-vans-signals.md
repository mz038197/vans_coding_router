# Forward production src ERROR logs to vans-signals

The operator cannot see a production failure once the Fly machine restarts, including an Upstream Model Catalog round where an upstream fetch fails and the previous snapshot stays. The production router posts each ERROR log under `src` to vans-signals as one Signal. The caller does not wait. The post times out after about 2 seconds and is not retried. A missing destination URL or token sends nothing, so local and staging stay quiet. A catalog round that finishes with at least one upstream that did not update emits one ERROR naming those upstreams. A round that throws keeps the existing error only. A successful round, including the first success after failures, emits none. Warnings, expected refusals, web-server logs, and the forwarder's own delivery failure are not posted.

## Considered Options

- **Post from the catalog job only**: rejected. Other ERROR logs under `src` would stay in process output alone.
- **Wait for vans-signals on the student request**: rejected. A dead destination would slow the class.
- **Retry a failed post**: rejected. A dead destination would pile up work.
- **Send a Signal when a failed round later succeeds**: rejected. Recovery is not an error, and this version has no recovery Signal.

## Consequences

- Production sends only when both `VANS_SIGNALS_URL` and `VANS_SIGNALS_TOKEN` are set. The token is the vans-signals bearer whose service name is `vans-coding-router`. Neither value belongs in the router config file.
- A failed post is written on the `vans_signals_forwarder` logger, which is outside `src`, and is not posted again.
- The Signal body is the log time, logger name, level, message, and source. The traceback stays in Fly process output.
