# AG-UI backend acceptance (G4)

2026-10-15. Both directions of
[G4](../design/workbench-ui-interoperability.md#g4-ag-ui-server-integration)
implement the [declared AG-UI 1.0 subset](../design/workbench-ag-ui-v1.md).
Serve exposes Workbench's existing answer loop; connect consumes explicitly
configured external agents. These are headless capabilities. Production
`supportedProtocols` remains empty and `renderer` remains false.

## Published sources

- Initial contract: specs `9cffc31cd876a5bb163890e8b743a6188dbc2f13`.
- Clarified contract and Workbench specs pin: `d1bd751695b3d788c69073c383ad4ca3b2883e41`.
- Workbench source: `af68b11f06779afae52312a64871d337a55a809d`.
- Workbench distribution: `028c4083aebdcc4edee886a06a70260b45d19a8b`.
- Agent catalogue: `589379aefed9707f439b5dcbcf5e305cf25aba7e`.
- Upstream: AG-UI release/2026-10-13,
  `b3f61a96fa3c755f37558ac44f4acc5b1c3828f1`, normative protocol **1.0**.

The unmodified normative schema, MIT license and fifteen selected upstream
conformance streams are vendored with SHA-256 provenance in
`protocols/ag-ui/SOURCE.json`. Workbench codegen copies these from its specs pin;
CI checks generated models and both protocol schema directories for drift.

## Backend evidence

Windows, CPython 3.12.14, Workbench's own environment. Acceptance uses real
Workbench HTTP, OIDC/gateway fixtures, real HTTP reference agents, real MCP SDK
tools, temporary SQLite databases and OS-selected loopback ports. The crash case
starts a separate Workbench process, kills it after the reference agent counts
the received run, and restarts against the same database. No installed service,
model process or live data was changed. G4 does not measure model generation;
the separate [G3 QWen samples](genui-a2ui-run.md#running-model-generation-sample)
retain that scope.

The affected-feature suite (AG-UI, database migrations, chats/branches,
interactions, A2UI, MCP Apps and tools) passed **232 tests, 2 skipped** in
201.17 seconds. Four added regressions also passed: schema-16 migration,
cancellation with an open tool stream, an authenticated A2UI surface reference,
and preservation of a remote cancelled outcome in the ordinary chat fallback.
This is **236 distinct passing checks**, including **58 AG-UI cases**. The two
skips are the pre-existing opt-in system Chrome checks, outside this headless gate.

| Direction/boundary | Observed result |
| --- | --- |
| Serve: native answer | Pinned lifecycle and text events, saved assistant text, authoritative messages/state, subsequent user turn through the normal gateway path |
| Serve: approval | No MCP call before the existing per-call approval; ordered tool events/results afterwards; replay never repeats the approved call |
| Serve: UI linkage | CUSTOM eugene.interactions names the persisted A2UI surface and answer; callers read it through the existing authenticated interaction API; UI-only data stays out of inference |
| Serve: cancellation | Client disconnect preserves the run; explicit Stop closes partial message/tool streams and records a cancelled terminal outcome |
| Connect: trace/state | Interleaved tool IDs assemble independently; Unicode and fragmented SSE survive; snapshot replacement and all six patch operation names have tested semantics; custom values remain inert |
| Connect: continuation | Saved state/history required; interrupt response validated; duplicate run IDs replay, conflicting bodies fail, and competing successors produce only one additional external request |
| Connect: failures | Explicit remote errors, missing/truncated terminal frames, unsupported events, bad state patches, HTTP errors, redirects and events after terminal never become success or trigger retry |
| Connect: cancellation | Closing an external request records uncertain execution; an agent-reported cancelled outcome remains cancelled and its chat fallback says stopped |
| Identity | Other people and an install owner's read-only chat privilege cannot access AG-UI records; configured per-person grants apply; forged context/identity/state and wrong Origin are refused |
| Credentials | Only the configured server bearer token reaches the reference agent; list/run data omit it; the Eugene gateway key is not forwarded |
| Revocation/lifecycle | Sign-out, source removal, Stop, chat deletion and server restart stop active work without repeating the counted external request |
| Real process kill | The database still said running after forced termination; the next boot appended RUN_ERROR and marked uncertain; repeated POST returned the saved result with external request count still one |
| Bounds/retention | Request, schema, patch and event limits refuse excessive work; a reserved terminal slot remains available; person quota does not evict replay records; chat deletion releases quota |
| Isolation/branches | Remote tool/state/custom data do not enter a subsequent native inference turn; an ordinary turn invalidates the old AG-UI continuation; active runs block ordinary chat/branch writes |
| Migration/package | Schema 17 preserves prior messages/interactions and backs up schema 16; published archive and wheel retain protocol data, version stamp and frontend assets |

Pinned upstream streams cover text/tool assembly, reopening text messages,
message snapshot reconciliation, falsy/null state, state deltas, cancelled and
interrupt outcomes, and invalid ordering. Additional tests exercise JSON Pointer
escaping, array bounds, atomic patch failure, multi-line/fragmented SSE and
explicit refusal of unsupported event families.

## Review and checks

One adversarial source review identified a cancellation/checkpoint race: SQLite
could commit an event after its awaiter was cancelled, leaving the in-memory
projection behind. The adapter now finishes that checkpoint before constructing
its terminal event. A regression deliberately cancels that await; removing the
shield loses the committed projection and fails the check. Review also tightened
chat-write arbitration at the SQLite transaction, bounded interrupt schemas
without references/regular expressions, and closed partially emitted tool streams
on native Stop.

`scripts/check-agui-sabotage.py` verified its unmodified controls and detected all
seven removed guards in temporary copies: request binding, chat ownership, agent
access grants, state deltas, terminal ordering, checkpoint cancellation and
restart recovery. Targeted reruns covered the last two cases after adjusting the
cancellation assertion matcher. Working source fingerprints remained unchanged.
The normal Windows/Linux CI workflow now includes this gate.

Ruff lint/format, native and Linux-target mypy, whitespace checks and staged
secret scans passed. Regeneration from the published pin retained the unchanged
shared model definitions and pinned protocol bytes. The frontend/preview build
passed with its existing large-chunk warning. The agent's three catalogue checks,
lint/format, native/Linux mypy and staged secret scan passed.

The distribution differs from its source only by static files and BUILD_INFO.
Its GitHub archive was downloaded and verified against the source, all vendored
AG-UI/A2UI hashes, page/preview assets and stamped distribution SHA. A wheel built
from that archive imported the packaged adapter and validated a pinned event.
Wheel SHA-256:
`3e07cda66795179fc854715d11005b172606451aac313d3a4d3e6eb19158908f`.

## Delivery and remaining gate

Publication and catalogue pinning are complete; the live installation was not
upgraded. [G4 Workbench CI](https://github.com/eugene-plexus/workbench/actions/runs/38822371601)
was still running when this record was published. Local Linux-target type checks
are not a Linux runtime acceptance claim. The preceding G3 Workbench and agent
CI runs completed successfully.

The declared subset requires a new empty chat, text messages, server-owned
tools and saved authoritative continuation. Client-executed tools, reasoning,
multimodal, activity, chunk and subagent events remain explicitly unsupported.
No automatic retry promises exactly-once remote effects. G0–G4 backend gates
are now implemented; **G5 browser conformance and product UI** is next. The older
Job Site signature timing issue remains tracked separately as
[Workbench #13](https://github.com/eugene-plexus/workbench/issues/13).
