# A5: scoped client access and shared admission

Status: implementation in progress. Acceptance requires two independent keys
and two real gateways, including cancellation, wake, fallback and authority loss.

The existing key registry is also the admission authority: the active control
root for an enrolled install, the local agent for a standalone install. Enrolled
agents relay admission to their control root and never create a local allowance
during an outage. Limits are per key across gateways, not per gateway or IP.
This uses the existing single-active-root trust boundary. Promotion must fence
the former active root, as with registry changes; this does not introduce a
consensus protocol that can make two intentionally active roots safe.

New keys default to all models, two concurrent requests and sixty accepted
requests per rolling minute. Operators can choose exact allowed model IDs,
1–64 concurrent requests and 1–10,000 requests/minute. An empty model list denies
all models; null means all. An alias and each actual target both need permission.
Restricted targets are removed before capability checks, wake, selection and
fallback; listings expose only the permitted portion of an alias. No wildcard
or inferred model family grants access.

Existing records without limits retain all-model access and no per-key rate or
concurrency limit, visibly labeled legacy/unrestricted. Operators can set limits
on them without replacing the bearer. New keys always receive bounded defaults.
Changing policy never clears revocation; re-importing a legacy record cannot
overwrite a policy subsequently set by the operator.

Client model discovery checks current access with the authority without consuming
an allowance. Inference acquires a reservation before routing or waking and
retains it through response streaming. Accepted attempts consume the rolling
rate allowance even if they later fail or are cancelled. Internal fallback is
one request, not another rate charge. Refused admission does not enter a queue.
HTTP 429 includes Retry-After; unavailable coordination gives client-only 503.
Operator/service repair paths remain usable. A3's cached authentication policy
still distinguishes revoked/invalid credentials, but cannot authorize inference
or model discovery without A5's current authority check.

Reservations have renewable 30-second leases. Gateways renew before expiration
and cancel upstream work if renewal fails or policy changes. A gateway stops
using a lease before the authority may reclaim it, based on the start of its
HTTP round trip and a conservative fraction of the returned lease duration.
Normal completion, disconnect, cancellation, timeout and failed wake release in
a bounded finally path; a dead gateway's reservation expires. Release is
idempotent. A lost acquisition response cannot authorize work and still triggers
best-effort release by its stable request ID.

Admission is durable: the control log/snapshot records each changed key bucket;
the standalone agent commits it with its existing atomic registry file. The
admission clock advances from a persisted logical value using perf_counter,
never wall-clock arithmetic. Restart resumes from the persisted value, so time
while the authority was offline does not erase allowance or shorten old leases.
This can delay reuse by at most one lease/minute window after recovery; it
cannot grant a fresh allowance merely because a process restarted or UTC jumped.
State is bounded to 50,000 recent reservations; overload is a useful refusal.

Gateway metrics add authenticated key ID and registry name, never the caller's
`user` annotation. Both chat APIs and embeddings retain attribution through
fallback, streaming, early refusal and failure. Per-key totals are per gateway
over retained raw rows, with explicit retention/drop information. Reported token
totals cannot account for tokens an upstream failed attempt never reported;
this is operational usage, not billing. No prompt, credential or image is needed.

Update all agents, control roots and gateways together before relying on A5;
older gateways do not enforce this policy. A5 does not classify backend locality
or prevent an administrator/malicious backend from misrepresenting a model. A6
adds the separate local-only routing constraint.
