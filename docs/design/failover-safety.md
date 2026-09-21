# A6b: failover safety

One request may try another eligible backend only when the failed attempt is
known not to have accepted application work. Connection establishment failures,
driver pre-execution unavailability and explicit HTTP 429 refusals are safe.
Read/write failures, malformed or truncated responses, deadlines, CLI failures
after launch and generic upstream 5xx responses have an indeterminate outcome.
They stop the request. Other request/authentication refusals are terminal.
Older drivers' unclassified server failures are indeterminate. A Retry-After
header alone never makes replay safe. No fallback follows emitted text or a
tool-call fragment, even if an error claims to be safe.

Gateway-generated request IDs accompany every driver request and response header
and retained request record. HTTP drivers pass the identifier to their upstream
as X-Request-ID. This is correlation, not an idempotency key. CLI lifecycle
correlation ends at the driver boundary; provider-internal actions cannot be
made exactly-once by this gateway.

requestTimeoutSeconds bounds the entire gateway request, including admission,
preparation, wake and fallback. Disconnect or expiry cancels owned tasks and
releases admission. Cancellation does not prove a remote provider stopped or
that an external tool did nothing. Admission release has its own bounded cleanup
window. A deadline after stream headers is an error event, never a second answer.

Per-driver connection circuit state survives routing refreshes that reuse that
client. Failure starts a bounded exponential cooldown (one to sixty seconds),
extended by a provider delay up to five minutes. Cooldown skips that backend
without waiting. Expiry permits one concurrent recovery probe; two successful
probes separated by one second restore ordinary traffic. Configuration replacing
the client starts fresh state. Circuits are gateway-local, not a shared quota.

Candidate selection preserves key/model/locality restrictions, images, tools and
explicit request settings. Unsupported or unknown explicit capabilities cannot
receive application content. Drivers validate again before execution. Provider
acceptance of every schema or sampler value is not promised by adapter support.

Retained attempts record failure disposition and whether usage is known. Missing
usage remains unknown, including work cancelled or lost before a final response.
Unknown tokens are never reported as proof of zero spend. Billing reconciliation
and tool-effect idempotency remain the provider/tool executor's responsibility.
