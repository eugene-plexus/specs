# Workbench interactive UI interoperability

**2026-10-15. Backend first, at Troy's request.** G0's inference prerequisite
gate is implemented and passed locally; [acceptance](../acceptance/genui-inference-run.md).
G1–G5 remain planned. No AG-UI, A2UI or MCP Apps compatibility is advertised yet.

This follows the [rich-content roadmap](workbench-rich-content-roadmap.md),
whose RC1–RC6 provide rendering, typed content, assets and saved previews.
The next capability is interoperable UI descriptions and user actions that
return to an agent or tool. Backend contracts and behavior come first; production
renderers follow their acceptance. A small reference client is allowed to prove
the protocol and, later, the actual browser boundary.

## Ownership

```text
Workbench browser / reference client
                   |
          Workbench Python server
            |          |          |
            |          |          +-- external AG-UI agents
            |          +------------- MCP servers and their UI resources
            +------------------------ Eugene gateway -> inference-driver -> model
```

Workbench owns agent runs, tool execution, conversations and UI state. The
gateway and inference-driver own inference transport, model capabilities,
routing, admission and failure classification. A2UI JSON can be model text or
function arguments. MCP UI metadata and AG-UI lifecycle/state events belong
above inference; they are not new fields to add indiscriminately to
`/v1/chat/completions`.

Keep the gateway's existing unknown-field rejection. Preserve UI-only metadata
in Workbench's own records and deliver only the intended model projection to
inference. Shared Eugene contract defects must be fixed in specs before affected
consumers are updated. Workbench's own server/client wire contract must also be
written before its endpoints and renderers are built.

## Protocol baselines

| Protocol | Initial design target | What completion must establish |
|---|---|---|
| MCP Apps | Published specification **2026-01-26**, excluding draft additions | Negotiated extension, UI resource discovery, tool/view linkage, authorized resource and tool operations, explicit supported host methods |
| A2UI | **v0.9.1**, with an explicitly identified supported component catalog | Validated surface/component/data updates, deletion, capabilities and actions, bounded state and persisted revisions |
| AG-UI | Stable events/types in **release/2026-10-13**; pin exact schemas/SDK before implementation | Run lifecycle, message/tool events, supported state events, input/actions and explicit unsupported features |

These are targets, not installed dependencies. G1 records exact upstream source
revisions, schema hashes, licenses and the feature matrix. Do not follow a moving
`main` branch or silently adopt draft event shapes. Each integration advertises
only capabilities proven by its acceptance. Full support means the declared
version and capability set, not every optional feature or future draft.

Sources: [MCP Apps published specification](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx),
[A2UI v0.9.1](https://a2ui.org/specification/v0.9.1-a2ui/),
[AG-UI release](https://github.com/ag-ui-protocol/ag-ui/releases/tag/release/2026-10-13)
and [event definitions](https://docs.ag-ui.com/concepts/events).

## G0: inference prerequisites

**Implemented.** `scripts/genui-inference-acceptance.py` uses the real gateway
over HTTP, real driver processes and deterministic local provider fixtures.
It reuses the isolated process/trust setup from `tools-assumed-acceptance.py`.

The gate covers:

- Whole and streamed JSON/JSONL, Unicode, escaped strings, nulls and numbers.
- Exact JSON Schema forwarding, including definitions/references and `strict`.
- Interleaved function-call fragments, stable IDs and names, complete arguments,
  and a subsequent request containing the assistant calls and both tool results.
- Rejection of UI-only metadata at the inference boundary, before a provider call.
- Structured-output translation through Responses and Messages, whole and streamed.
- Client disconnect reaching the upstream stream and releasing client admission.
- Safe fallback after a 429, and no replay after a 503 with unknown outcome or
  after text/tool fragments. Each failure case proves the primary was called;
  partial cases also prove that output reached the caller before the error.

Local-compatible, Strata and OpenAI-account driver configurations are measured.
The provider fixtures return known payloads: they do not establish a real model's
ability to generate valid interfaces or enforce JSON Schema. The A2UI-shaped
JSONL is a transport fixture, not a catalog/schema conformance test. MCP App
resources and AG-UI events do not pass through this gate as inference fields.

The paired sabotage copies the driver, disables schema forwarding, and requires
the gate to fail specifically for the lost upstream format. It does not edit
the developer's driver checkout. Both scripts run in Windows/Linux specs CI.

No inference contract or runtime change was needed for the measured paths.
CLI backend limitations, native Gemini/Ollama transport, every provider/model,
actual model generation, and application restart/reconnect remain outside this
gate. Existing broader acceptance records remain evidence for their own scope;
they are not relabeled as UI protocol conformance.

## G1: application-server contracts and durable interaction

Write the versioned Workbench HTTP/event contract and capability matrix before
implementing protocol endpoints. Inspect the current store, answer branches,
session authentication, MCP connection lifetime and Stop behavior. Extend these
where useful; do not introduce a second conversation or permission system.

The contract must specify:

- Ownership by person, chat, answer version, run, surface and originating tool
  connection. An install owner's read-only view never gains action permission.
- Separate model-visible content and UI-only metadata/results; bounded payloads,
  normalized MIME types and existing authorized asset references.
- Stable event IDs/revisions, ordered updates and an authoritative saved snapshot.
  Reconnect restores state without replaying tool side effects. Version selection
  restores its own surfaces, never those from a different answer branch.
- Action IDs and expected surface revision. Duplicate submissions return their
  recorded disposition; stale, removed, unowned or disabled targets are refused.
- Durable intent before dispatch, completion/error/uncertain outcomes afterwards,
  and no automatic retry after uncertain execution. This does not promise
  exactly-once effects at a remote tool that lacks its own idempotency support.
- Cancellation, expiry, connection removal, sign-out/revocation, server restart
  and bounded cleanup. Reopening a chat must not silently restart execution.
- Plain-text fallback and explicit capability/version refusal.

**Acceptance:** a reference HTTP client exercises these transitions across a
real Workbench restart with two people, an owner read-only view, duplicate and
stale actions, revoked access and disconnected streams. Validate actual persisted
state and counted external effects, not only successful status codes.

## G2: MCP Apps server integration

Current discovery retains names, descriptions and input schemas, but drops tool
UI metadata. Current result normalization retains content and structured data,
but does not establish an MCP Apps resource/interaction lifecycle. Per-answer
MCP sessions also end when the answer ends; a saved app needs an explicit policy
for later interaction and fresh authentication/discovery.

Preserve validated tool/UI linkage and UI-only result metadata. Negotiate the
extension; distinguish tools visible to the model, the app, or both. An app-only
tool must not appear in the model's tool list. Read `ui://` resources through the
originating connected MCP server, with bounded responses and retained CSP and
permission metadata. A URI is not authorization to fetch arbitrary HTTP or files.

Define authorized server endpoints for resource reads, tool calls and permitted
context/message operations. Bind every request to the original person and
connection; recheck current tool visibility and existing approval policy before
dispatch. Embedded code receives no Eugene, provider or MCP credentials. The
bridge is an allowlist of supported methods, not a generic authenticated proxy.

**Acceptance:** use a real MCP SDK fixture server and a headless host client.
Exercise discovery, app-only tools, UI-only metadata isolation, resources,
interaction after answer completion, restart, removal/revocation and uncertain
calls. Reject forged cross-server/cross-person resource and tool references.
Browser sandbox/CSP conformance remains a separate G5 requirement.

## G3: A2UI server integration

Validate the pinned protocol and advertised catalog. Keep surfaces and data
models as versioned structured state; do not infer interfaces from arbitrary
JSON in ordinary answers. Bound message size, component count, graph/reference
work and stored revisions. A partially streamed object is not a committed update.
Catalog identifiers select approved local schemas; they do not authorize remote
schema retrieval or code installation.

Route server actions through G1's durable action path. Distinguish registered
client-local functions from actions that reach the server. Preserve original
output and readable fallback on invalid or unsupported descriptions. Model
repair attempts must be bounded and cannot repeat external side effects.

**Acceptance:** pinned upstream fixtures plus invalid/oversized graphs, unknown
catalogs, incremental updates, deletion, stale actions, branch selection and
restart. Separately measure at least one real local model through Eugene; report
generation/schema reliability apart from wire and state-machine conformance.

## G4: AG-UI server integration

Treat two directions separately: exposing Workbench's existing agent loop through
AG-UI, and connecting Workbench to external AG-UI agents. Record the supported
direction on every capability and acceptance result. Neither direction turns an
inference-driver into a general remote-agent runner.

Adapt the existing run/message/tool events and persisted state to the pinned
AG-UI types. Define supported state patches and custom UI events, input/tools,
run/thread IDs, error/terminal behavior and cancellation. Authentication must
identify the initiating person; Workbench's shared gateway key is not permission
to act as another person. External agent credentials stay in the server.

**Acceptance:** a reference AG-UI client against Workbench and a reference agent
against Workbench's client adapter. Verify event ordering, interleaved tool calls,
state updates, terminal errors, interrupted runs, input continuation, authorization
and reconnect without duplicate actions. Draft/unimplemented events must have a
documented refusal or fallback, not an apparent success.

## G5: browser conformance and product UI

Begin production UI integration after G1–G4 backend gates pass. Use the existing
rich-content renderers and previews where their boundaries fit the protocols.
Run browser acceptance for iframe isolation, CSP enforcement, message origin and
channel validation, accessibility, themes, lifecycle and fallback. A headless
server test cannot prove these browser properties.

Only after these gates should Workbench advertise a protocol as usable. Publish
the implemented capability matrix and known limits with the release, rebuild
Workbench's distribution and update its catalogue pin through the normal workflow.
