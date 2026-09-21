# A3: install-wide client keys

Design before contract changes, 2026-09-20. Implements the
[adoption roadmap](adoption-roadmap.md#a3--install-wide-key-revocation).

## Authority and persistence

On an enrolled install the active control root owns the client-key registry.
Creation, migration and revocation use its existing durable log, deterministic
state machine, snapshots and standby replication. A standby does not serve an
apparently fresh policy: only the active root may issue it. The policy version is
the applied log index, with the persistent control identity identifying authority.
Revocation is monotone; replaying an import cannot restore a revoked key.

Agent management endpoints remain the UI entry point. On enrolled nodes they
forward the operator's credential to the root for list/create/revoke; they do not
substitute a service token for an operator. The root mints new client tokens using
its existing signing key and returns the token once. Records hold only identifiers,
names, timestamps and a short token tail. No new signing material reaches gateways.

On an unenrolled agent the local registry is authoritative. Its file writes become
atomic and failures are reported; corrupt files cannot become an apparently empty,
healthy policy. Joining an install switches authority and triggers migration.
Operator and service authentication remain independent of client-key policy so
management stays accessible during an outage.

## Existing keys

Each upgraded enrolled agent automatically submits its existing unexpired records,
including revocations, using its enrolled node's Ed25519 identity. The import is
domain-separated, signed over the complete canonical payload, bound to that node,
and idempotent. The root validates membership/signature and records origin and
migration status. An import cannot overwrite another node's record or clear a
revocation. Existing JWTs retain their identifiers and expiration; no reissue is
required after a successful import. The old local file is retained.

There is no anonymous compatibility grace period: a correctly signed client JWT
whose identifier is absent from the authoritative registry is refused as
unregistered. Keys from an offline/not-yet-upgraded node therefore become usable
after that node imports its records. Missing/corrupt records require restoring the
record file or replacing those keys. The key-management UI explicitly shows
authority, migration pending/complete/error, origin and actionable failures.

## Gateway policy and outage behavior

Each gateway fetches a policy from its own agent, which obtains an enrolled
install's policy from control. The agent does not renew timestamps on cached data.
Policies contain the authority, revision, generation time and active/revoked key
records with expiration. JWT signature, audience and expiration validation runs
before consulting this policy.

Default refresh interval: **15 seconds**. Request timeout: **4 seconds** at the
gateway and **3 seconds** from agent to control. With healthy components, an
acknowledged revocation is enforced by the next request after refresh (normally
within 15 seconds; allow 20 seconds including the read). Existing responses already
in progress are not retroactively cancelled.

Default maximum policy age: **60 seconds**, measured from authority generation,
not the last failed fetch. A still-fresh cached policy permits registered keys
during a brief outage. At the maximum age, or without a valid cache, client access
fails closed with **503 policy unavailable**. Known revoked keys remain **401**
(Anthropic **403**, preserving its measured non-retry behavior), even during an
outage. Unregistered keys are a distinct credential refusal when policy is fresh;
invalid/expired tokens retain ordinary authentication failures.

Persist policy atomically beside gateway configuration, scoped to its verification
key and agent endpoint. Retain known revocations across restart, reject regressed
versions, and do not treat a missing, malformed or differently scoped cache as an
empty allowlist. In-process durations use `perf_counter`; persisted age uses UTC.
Clock rollback/future timestamps beyond five seconds invalidate cache freshness.
The documented outage bound allows that five-second clock tolerance (65 seconds).
Small test-only/deployment setting overrides make the bounds testable without
waiting a minute per scenario; changing the maximum changes availability/security.

Refresh uses one shared task, shielded from individual request cancellation, with
bounded retry backoff (1, 2, 4, 8, 15 seconds). Concurrent failures share one timeout;
later callers during backoff receive the cached decision or 503 immediately.
Successful reads reset backoff. A failing persistence write cannot authorize a new
policy. This avoids both indefinite stale permission and N serialized timeouts.

## Acceptance

Use real isolated control, two agents and two gateways with Ed25519 verification
keys only in gateways. Mint through one agent, use on both gateways, revoke through
the other, and observe the bound. Cover gateway/control restarts, local-agent and
root outages, fresh/stale/missing/corrupt persisted policy, concurrent requests,
recovery, existing active/revoked-record migration and replay/standby equivalence.
Confirm operator recovery access throughout. UI checks cover migration/error copy
and revocation from a different node. No live node or inference engine is needed.
