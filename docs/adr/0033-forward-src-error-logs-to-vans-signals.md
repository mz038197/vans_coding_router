# Forward production src ERROR logs to vans-signals

The operator cannot see a production failure once the Fly machine restarts, including an Upstream Model Catalog round where an upstream fetch fails and the previous snapshot stays. The production router posts each ERROR log under `src` to vans-signals as one Signal. The caller does not wait. The post times out after about 2 seconds and is not retried. A missing destination URL or token sends nothing, so local and staging stay quiet. A catalog round that finishes with at least one upstream that did not update emits one ERROR naming those upstreams. A round that throws keeps the existing error only. A successful round, including the first success after failures, emits none. Warnings, web-server logs, and the forwarder's own delivery failure are not posted.

Expected refusals are not posted, with four exceptions that emit one ERROR when that failure is what the student finally receives. An unexpected Python exception emits one. A `ServiceUnavailableError` emits one, because the call never reached an upstream response: the provider has no base URL, no upstream API key, or the transport failed. An upstream 401 or 403 emits one. An Extra Usage Exhaustion or a Credit Exhaustion emits one only when Key Failover and `vcr-auto` did not recover and that refusal is what the student receives. These last three stay what they already are. They are not reclassified as bugs. A 402 or 429 that failover swallows while trying another key, or that `vcr-auto` swallows while trying the next Model ID, emits none. `UpstreamBusyError`, an invalid or expired API key, a model that is not allowed, a disabled capability, and any other upstream refusal emit none. Chat, Responses, image, speech, and speech-transcription streams follow the same rule. Realtime is not covered. Every returned failure emits its own ERROR. This version does not deduplicate.

The student-facing HTTP status and body stay as they are, except an unexpected exception. In a stream that exception's SSE sentence is the fixed `Internal server error`, not the exception text. Outside a stream, an OpenAI-compatible path uses the OpenAI error shape with that same sentence, and every other path uses `{"detail": "Internal server error"}`. Portal's existing failure response is unchanged. The log message carries the HTTP method, the path without the query string, the exception's own status code, the provider when the failure is an upstream response, and the sentence the student sees, in full. A stream has already sent HTTP 200, and an upstream 401 or 403 is still shown to the student as 502, so the Signal names the exception's status rather than that HTTP status. The message does not carry the raw upstream body, an API key, an Authorization header, or the student's prompt. FastAPI does not call Slack. `SignalForwarder` is unchanged.

## Considered Options

- **Post from the catalog job only**: rejected. Other ERROR logs under `src` would stay in process output alone.
- **Wait for vans-signals on the student request**: rejected. A dead destination would slow the class.
- **Retry a failed post**: rejected. A dead destination would pile up work.
- **Send a Signal when a failed round later succeeds**: rejected. Recovery is not an error, and this version has no recovery Signal.
- **Post every `UpstreamServiceError`**: rejected. A student 400, a content refusal, or a Decision Refusal would page the class.
- **Post every HTTP 402**: rejected. A 402 that is not Extra Usage Exhaustion or Credit Exhaustion is an ordinary upstream refusal.
- **Log at the Key Failover raise site**: rejected. A recovered request would alert, and the final failure would alert twice.
- **Deduplicate identical failures in one sitting**: rejected. The count should match what the class hit. Combining them is a later mechanism.
- **Truncate the student sentence in the Signal**: rejected. The operator wants the sentence the student sees, whole. The existing upstream-text extract already limits that sentence.
- **A new Alert Dispatcher or a second ADR**: rejected. ERROR logs under `src` already reach vans-signals.
- **Include Realtime**: rejected for this decision. Closing the socket is a separate path.

## Consequences

- Production sends only when both `VANS_SIGNALS_URL` and `VANS_SIGNALS_TOKEN` are set. The token is the vans-signals bearer whose service name is `vans-coding-router`. Neither value belongs in the router config file.
- A failed post is written on the `vans_signals_forwarder` logger, which is outside `src`, and is not posted again. The student's HTTP response is unchanged when the post fails.
- Process shutdown waits for an in-flight post, up to that same timeout, so a thrown startup catalog round still reaches vans-signals. A student request does not wait.
- The Signal body is the log time, logger name, level, message, and source. When the log record has an exception, the message keeps that sentence and then the exception stack, so an agent can read the failure from Slack and from the stored row. A catalog round that names upstreams which did not update also keeps each failed fetch's stack after that sentence. Fly process output still has the same stack.
- A `ServiceUnavailableError` sentence and a traceback can still contain the transport exception text, including a URL. This decision adds no scrubber.
- Sixty students hitting the same dead key or the same broken transport produce sixty Signals.
- Portal routes that already log an unexpected failure and return their own 500 stay on that path, so the app-wide fallback does not log them a second time.
