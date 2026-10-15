# Interactive UI: durable backend interactions (G1)

2026-10-15. G1 of [UI interoperability](../design/workbench-ui-interoperability.md)
is implemented and passed locally. This is the shared backend foundation, not
AG-UI, A2UI or MCP Apps conformance. Production startup registers no adapters and
`/api/v1/interactions/capabilities` returns an empty supported-protocol list.

## Sources and environment

- Contract and upstream source lock: specs `62d2d74214ab9a6911259f5ed6b42c3d60406d6c`.
- Workbench implementation: `c38b64027269583b50cc51a578eea599d6016839`.
- Published distribution: `b2c8a6b1dbba51861d50a279fa62f3f9cd2ed1e8`.
- Agent catalogue update: `5b68a9b5098c3d2977689a6519daac8016c574b3`;
  three catalogue checks, Ruff and mypy pass.
- Windows, CPython 3.14.3, Workbench's own development environment.
- Real Workbench HTTP, OIDC fixture, gateway fixture and a separate HTTP server
  that counts external effects. An internal reference adapter exists only in
  tests; it is not an implementation or advertised version of a UI protocol.
- Isolated temporary SQLite databases, loopback servers, OS-selected ports.
  The crash test starts Workbench in a separate spawned OS process, kills it
  after the external counter increments, and starts a fresh process against
  the same saved data. No live installation or real provider is used.

## Results

**27 interaction tests pass.** The coverage includes:

| Behavior | Observed result |
|---|---|
| Proposal and explicit host decision | Proposal alone produces zero effects; approval produces one |
| Concurrent/repeated approval | Twelve concurrent decisions and later repeats produce one effect |
| Request identity | Identical IDs return saved outcomes; altered payloads, including boolean/integer substitutions, conflict |
| Ownership | Another person cannot read or act; permitted install-owner inspection is read-only |
| Private answers | Surfaces/actions of hidden job-site answers are absent from the owner's snapshot |
| Branches | Selecting/retrying an answer restores only its surfaces; historical branches cannot act |
| Surface lifecycle | Stale revisions, origin rebinding, unknown versions and tombstone reactivation are refused |
| Authority after an asynchronous wait | Sign-out, source deletion, branch/revision changes, expiry, expired access lease and adapter refusal prevent dispatch |
| OIDC revocation | Refresh rejects a revoked person and cancels the pending proposal |
| In-flight cancellation | Stop/sign-out end the wait; an already-started external effect remains uncertain |
| Hard process kill | Disk says dispatching before restart; the fresh process saves uncertain; repeated requests leave the external count at one |
| Reconnect | SSE supplies an authoritative snapshot regardless of Last-Event-ID; reconnect never executes work |
| Disconnect | Closing an event stream does not cancel an approved action; revoked access closes the stream |
| Model/UI separation | UI-only descriptions/results do not enter later inference requests; model projection is stored separately |
| Bounds | Oversized/deep/malformed input is refused; pending work reserves result space; quotas retain old IDs |
| Removal | Deleting the chat cascades to surfaces, action records and cursor |

`scripts/check-interactions-sabotage.py` passes its unmodified HTTP-test control
and catches all four deliberately broken guards: terminal action replay, revision
checking, the access-lease check after authorization, and owner redaction. Each
mutation runs in a temporary source copy; the original Python tree's hash stays
unchanged. CI runs this check on Windows and Linux after pytest.

The final focused run of interaction, migration, conversion, document-store and
memory-store tests passes **92 tests**. It includes migrating a schema-15 database
after preserving a schema-15 backup, while retaining the old answer.

The broader regression run produced **2,001 passes and 28 skips**, plus eleven
assertions still expecting schema 15. Those assertions were corrected to schema
16; all eleven pass in the subsequent failure-only run, and their full test
files pass in the focused run. The skips are existing opt-in browser or
platform-specific tests. This is not reported as one all-green full-suite run.

Ruff lint/format, mypy, whitespace and secret checks pass. Workbench repins specs
and regenerates with its own generator: common schemas add 24 classes and extend
four enums; existing classes are retained. Config-trio checks pass. Frontend
type-check/lint, **3,235 tests in 85 files**, and the distribution build pass.
These frontend tests cover existing features; they do not establish G5 conformance.

The distribution tree matches the named main commit except for its static build
and BUILD_INFO. Its published GitHub archive was downloaded and checked for the
backend, page, preview runtime, build provenance and correct archive commit stamp.
The agent catalogue is updated to this distribution; live services are unchanged.

[Workbench CI](https://github.com/eugene-plexus/workbench/actions/runs/38801446070)
was started after publication; its final result is separate from these local results.

## Limits and next gate

The [v1 contract](../design/workbench-interactions-v1.md) declares the bounds and
state machine. Saved chat changes advance a persistent cursor. A visibility-only
change can replace a snapshot at the same cursor; every received snapshot remains
authoritative, including after reconnect. Adapters must honor cancellation and
bound their own network operations.

The coordinator does not append model context or create a public surface-publishing
door. Protocol adapters must validate their descriptions, catalog/assets/MIME
types, execution targets and current source policy. Embedded content must never
receive the host approval endpoint or credentials. Those integrations and their
browser boundary remain G2–G5.

Remote sign-in revocation follows Workbench's existing OIDC refresh lease.
Uncertain work is never automatically retried; this does not guarantee exactly-once
effects within a remote server. The next gate is MCP Apps discovery, metadata,
resources and approved calls through this durable path, including reconnection
after the originating answer has ended.
