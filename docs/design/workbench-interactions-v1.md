# Workbench interactions v1

G1 of [UI interoperability](workbench-ui-interoperability.md). The wire shapes
are in [OpenAPI](../../openapi/workbench-interactions.yaml). This foundation
does not itself claim AG-UI, A2UI or MCP Apps compatibility. The
[MCP Apps headless adapter](workbench-mcp-apps-v1.md) is implemented in G2;
A2UI and AG-UI remain G3–G4, and production renderers remain G5.

## Authority and state

Trusted server adapters publish a surface bound permanently to the chat owner,
chat, assistant message, run, protocol version and optional originating MCP
connection. Publication validates the adapter's exact version and description.
There is no public publication endpoint. Browser actions name a saved surface
and one of its allowed actions; they cannot select a server or credential.
An adapter may accept a tool name within its bound source's current allowlist.
The adapter checks current source access before any external dispatch, in
addition to Workbench's ownership, session and selected-branch checks.

Surface updates use compare-and-swap revisions. Deletion is a tombstone;
disabled/deleted surfaces cannot be reactivated under the same ID. Plain text
fallback is required. UI data and results are saved separately from their
explicit model projection. Protocol adapters define which approved projections
enter subsequent model turns; raw UI records never enter inference.
MIME types and asset references are validated by the applicable adapter using
Workbench's existing authorized assets; arbitrary URLs are not asset grants.

The owner's configured read-only view obeys the same hidden-answer rules as
chat and artifact reads. Historical branches can be inspected with `via`.
Actions always require the currently selected branch. Saved snapshots contain
only that branch's surfaces and actions. Deleting a chat deletes these records.

## Action lifecycle

`proposed -> queued -> dispatching -> completed | failed | uncertain`

Proposal records an ID, surface revision, action name, arguments, originating
session and expiry. It has no side effects. A separate decision approves those
exact saved arguments, or sets `cancelled`. The host's trusted approval UI must
own that decision endpoint; a future embedded-app bridge must not expose it.
An adapter may apply stricter existing tool policy, never weaker policy.

Immediately before dispatch, refresh/check the sign-in and current adapter
authorization, then atomically recheck session, source, branch, surface revision
and expiry while changing `queued` to `dispatching`. Only that transition may
execute. Durable intent precedes the external call. Once dispatch begins,
exceptions, timeout, cancellation and interrupted execution mean `uncertain`
unless the adapter explicitly certifies failure without an external effect.
Uncertain actions do not retry. This prevents automatic duplicate dispatch,
not duplicate effects inside a remote server without idempotency support.

An identical proposal with the same chat-scoped ID returns its saved disposition;
changing any payload or target under that ID conflicts. Repeated decisions never
re-dispatch. Terminal records survive expiry so an old ID cannot become new work.
Another sign-in of the same person can read results but cannot approve a proposal
created by the old sign-in. Revocation uses Workbench's existing OIDC refresh
lease; it does not promise instantaneous remote revocation notification.

Stop disables the chat's surfaces and cancels pending actions. Source removal,
expiry, lost sessions and branch/revision changes cancel pending work; in-flight
work becomes uncertain. A restart cancels every proposed/queued action and marks
every dispatching action uncertain, without running any of them. An approved
action outlives its HTTP connection; disconnecting an event stream has no effect
on execution. The server bounds tasks and execution duration.

## Reconnect and bounds

Each chat has a persisted, increasing cursor. Surface changes, action changes
and branch selection advance it. SSE starts with a complete saved snapshot and
then sends replacement snapshots, never a replay of commands. `Last-Event-ID`
does not request replay. The snapshot and cursor are read in one transaction.
Access is checked again on each one-second poll. A lost sign-in ends the stream.

Limits: 256 KiB per complete surface record, 16 KiB action arguments, 64 KiB
per UI result or model projection, JSON nesting depth 32, 64 surfaces per chat,
256 action records per chat, 25 MiB interaction data per person, 8 executing
actions per process and 1 per chat, 120 seconds per dispatch, and 15 minutes
per proposal (also capped by surface expiry). Quotas refuse new work; old action
IDs are not evicted or reused. Deleting the chat releases its quota. Only the
latest surface revision is kept; protocol-specific history is not promised.

## Capability matrix

| Capability | G1 declaration |
|---|---|
| Workbench interaction HTTP/SSE v1 | Backend foundation |
| MCP Apps 2026-01-26 | Disabled until G2 acceptance |
| A2UI v0.9.1 and catalog | Disabled until G3 acceptance; no catalog advertised |
| AG-UI release/2026-10-13, host and client | Disabled until G4 acceptance |
| Browser rendering / embedded bridge | Not exposed in G1 |

The capability endpoint lists only registered adapters that have passed their
own acceptance. Tests use an internal reference adapter; it is never registered
by production startup. Exact upstream inputs and license hashes are recorded in
[the source lock](../../protocols/ui-sources.lock.json); these are design inputs,
not installed SDK dependencies or a claim to implement their entire feature set.
