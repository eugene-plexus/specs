# A2UI backend acceptance (G3)

2026-10-15. G3 of [UI interoperability](../design/workbench-ui-interoperability.md)
implements the [declared A2UI backend subset](../design/workbench-a2ui-v1.md).
The protocol is 0.9.1 with the eight-component forms catalog, four pure local
functions and an explicit MCP producer extension. No production renderer is
advertised. A2A networking and the full upstream basic catalog are outside this slice.

## Published sources

* Contract: specs `f8bcc07dccbef12f22eda38a20da493fa94edba7`.
* Workbench source: `d9e3aa8aa07f3c001557f63adc6446defb38d222`.
* Workbench distribution: `1cf061004fa2c5a80c4e91f73400e7dd270bc3b2`.
* Agent catalogue: `16172e596ff249ff2350d04fc55c1ec64b0b6697`.
* Upstream A2UI: `c07134caf2f63e3356c4439d248afc9eb04f310e`.
  Vendored schema, catalog, license and fixture hashes are checked against
  `protocols/a2ui/SOURCE.json`; Workbench codegen copies them from its specs pin.

## Backend results

Windows, CPython 3.12.14, Workbench's own environment. Tests use real Workbench
HTTP, OIDC/gateway fixtures, real MCP SDK servers over JSON and SSE responses,
isolated temporary SQLite stores and OS-selected loopback ports. Owner-only
stdio acceptance launches real child processes and verifies their exit.

The final affected-feature run covers A2UI, durable interactions, MCP Apps, HTTP
and local tools, and rich tool content: **158 passed, 2 skipped** in 165.71
seconds, including all **42 A2UI cases**. The skips are opt-in system Chrome
tests. A final compatibility check preserving the pre-existing post-sweep
publication return value passed all 27 durable-interaction tests in 34.89 seconds.

| Boundary | Observed behavior |
| --- | --- |
| Pinned protocol | Original upstream text/button fixtures validate; wire v0.9 compatibility is retained; the custom catalog is explicit |
| Negotiation | A2UI version and catalog capability reach the producer; app-only action tools never enter model tool discovery |
| Typed admission | Wrong MIME/catalog/declaration, untyped metadata, partial JSON, oversized messages and cyclic graphs retain the completed ordinary tool result; no repair repeats a tool |
| State | Component replacement by ID, data replacement, escaped pointers, array append/deletion and missing-path deletion preserve other state |
| Graphs | Unknown components/functions, relative paths, regex and unsafe data keys fail; missing references stay inert; cycles and excessive graph expansion fail |
| Form input | Owner/current-branch/revision checks apply; only reachable bound fields accept their declared value type; input changes no external state and cancels stale proposals |
| Event approval | Saved name/component/surface/context and form checks must match; JSON types are exact; local function actions cannot call server tools |
| Current source | Changed producer declarations, action visibility, input schemas and deleted sources are rejected before an effect |
| Completion | Returned UI updates and action completion commit atomically; another proposal at the old revision is cancelled |
| Invalid update | A bad batch or publication-validation failure keeps the old form and a readable result/error; the confirmed effect is not repeated |
| Transaction failure | Failure on the second delete/recreate write rolls back both surface writes and completion; the action remains uncertain without replay |
| Identity | Deletion and recreation of a wire surface produces a fresh durable ID; old actions cannot address it |
| Lifecycle | Restart does not replay completed actions; Stop and sibling branches reject input/actions; concurrent input after dispatch leaves the effect uncertain |
| Data isolation | UI-only descriptions/results never enter inference; only normalized completed action content enters a subsequent explicit turn; dataModel is sent only when opted in |

`scripts/check-a2ui-sabotage.py` passed its unmodified control and caught all six
removed guards: event context, input type, atomic completion updates, data-model
opt-in, model projection, and discarding an invalid update plan. Mutations ran
only in temporary copies and verified the working source hash was unchanged.
The workflow runs this gate on Windows and Linux alongside G1 and G2.

Adversarial source review found that a plan rejected during publication validation
could remain attached to the result. The adapter now clears it before preserving
the completed tool result. A regression and sabotage case cover that boundary.

Ruff lint/format, mypy for native Windows and Linux settings, whitespace checks,
and the frontend distribution build (including TypeScript and preview runtime)
passed. Schema hashes were checked in the A2UI suite. Regeneration from the
published specs pin produced no diff in models or protocol data. Staged secret
scans passed in all three repositories. The agent's three catalogue checks and
its lint/format and native/Linux mypy checks passed.

The distribution tree matches the source commit except for static files and
BUILD_INFO. Its published GitHub archive was downloaded and checked for the
adapter modules, every vendored schema/catalog/license hash, page, preview runtime,
source provenance and stamped archive SHA. A wheel built from that archive also
retained the schemas, page, preview runtime and stamped SHA. The wheel SHA-256 is
`ddc7b85be6c83683d05f87d24538a26e73d892591705bfc2ea126056a04caff2`.

## Running-model generation sample

The user selected their already-running **QWen Flash Next on Strata**. Discovery
reported `qwen3.8-flash-next-iq2_xs`, loaded at loopback port 8092. No model was
downloaded, restarted, switched or reconfigured. The installed NAS gateway was
unavailable from this session, and Windows denied access to its service config.
The measurement therefore used a temporary real Eugene gateway and real Strata
driver against that running engine, with generated test credentials and fixture
discovery/admission. It did not use the production Workbench browser session.

`scripts/genui-a2ui-model-check.py` made three requests through the gateway's
public chat-completions endpoint. Each included the pinned schemas, temperature
0, a 4,096-token limit and JSON-object response format. No generation was retried
or repaired. Results are retained in [the sample record](genui-a2ui-qwen.json).

| Task | JSON | Catalog/state | Task checks | Seconds | Completion tokens |
| --- | --- | --- | --- | --- | --- |
| Text panel | Pass | Pass | Pass | 10.355 | 968 |
| RSVP form with bound fields, required check and event | Pass | Pass | Pass | 20.347 | 2,456 |
| Row with two bound cards | Pass | Pass | Pass | 15.022 | 1,800 |

All three finished with `stop`. The generation harness used CPython 3.14.3;
offline validation of the saved responses used Workbench's CPython 3.12.14.
The first validation attempt exposed an unnecessary runtime import of the MCP
transport dependency in the A2UI validator. Moving type-only imports under
TYPE_CHECKING fixed it; the original responses were revalidated without making
more model calls. The script now preflights that import before generation.

This is **3/3 valid samples**, not a reliability percentage for arbitrary prompts,
all quantizations or the full A2UI catalog. It establishes that this running model
can generate the declared subset when supplied with its schema. Typed producer
integration is still required; ordinary JSON answers are not promoted to UI.

## Delivery and remaining gates

The distribution and catalogue update are publication, not deployment to the live
installation. [G3 Workbench CI](https://github.com/eugene-plexus/workbench/actions/runs/38810765147)
completed successfully on Windows and Linux, verified at the start of G4.
The preceding G2 CI completed successfully on both
platforms. The older Job Site signature timing issue remains tracked separately
as [Workbench #13](https://github.com/eugene-plexus/workbench/issues/13).

Capabilities report A2UI 0.9.1, the forms catalog, input/action methods and
`renderer: false`; production `supportedProtocols` remains empty. The next
backend gate is AG-UI (G4), followed by production renderer work (G5).
