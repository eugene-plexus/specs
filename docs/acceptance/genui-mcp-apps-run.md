# MCP Apps headless backend acceptance (G2)

2026-10-15. G2 of [UI interoperability](../design/workbench-ui-interoperability.md)
is implemented and passed locally for the [declared backend subset](../design/workbench-mcp-apps-v1.md).
This does not establish a browser renderer, sandbox or iframe bridge; those remain G5.

## Published sources

* Contract: specs `8c293ff93f28157062e127da88089095509f7340`.
* Workbench source: `6189dc2c38c8d585298e575681f839519f7c7ae0`.
* Workbench distribution: `1f6eb5f4803b8dbccfa6d48cb8bba0e5603bc1aa`.
* Agent catalogue: `b44951b218077e0b029e6aef14b2f6120991e9d7`.
* Upstream MCP Apps: published 2026-01-26, commit
  `298e884ec3f02daba085acdb02042d73bd00b355`, checked against the SHA-256 in
  `protocols/ui-sources.lock.json`. No upstream code was vendored.

Windows, CPython 3.14.3, Workbench's own environment and pinned MCP SDK dependency.
Tests use real Workbench HTTP with OIDC/gateway fixtures, real MCP SDK servers,
isolated temporary SQLite stores and OS-selected loopback ports. The stdio test
launches real child processes and verifies their exit. No live services or
real providers were used or changed.

## Observed behavior

`python -m pytest -q tests/test_mcp_apps.py` passes **24 tests** (31.55 seconds).

| Boundary | Observation |
| --- | --- |
| Negotiation | Extension and MIME capability arrive at the SDK server with both legacy and modern MCP handshakes, over JSON and SSE responses |
| Discovery | Model receives model/both tools; app-only tools are absent and a guessed model call is rejected |
| Saved result | Tool descriptor, input, readable fallback and UI-only result metadata survive answer completion and restart |
| Resources | Bound `ui://` text and base64 HTML are returned as JSON with retained CSP/permission requests, no-store and nosniff |
| Malformed resources | Wrong URI/MIME, invalid base64, oversized/non-document HTML and unsupported policy shapes are refused |
| App calls | Proposal makes zero effects; explicit approval dispatches one call; repeated proposals/decisions never dispatch again |
| Current policy | Changed linkage, changed app visibility, deselected/deleted sources, unknown tools and invalid schema arguments are refused |
| Source and person | Other people, read-only owner inspection, another configured MCP server and forged resource targets cannot grant access |
| Revocation during IO | Deleting the source while a resource read waits prevents its bytes being returned |
| Uncertainty | Restart after an external effect and an oversized returned result both remain uncertain; resubmission produces no extra effect |
| Error result | A valid MCP `isError` result is preserved as a completed protocol result |
| Model isolation | Original UI metadata, app-result metadata and HTML never enter subsequent inference requests |
| Context/message | Only approved text/structured context enters a later explicit user turn; latest completion replaces prior context, and sibling branches exclude it |
| Fallback | Invalid UI linkage and oversized app descriptions retain the ordinary completed tool result |
| Stdio | Owner's saved app reconnects after restart; its approved call runs once and every fixture process exits |

The affected-feature regression command covers MCP Apps, interactions, HTTP and
local tools, tool content, chats and conversions: **178 passed, 2 skipped** in
162.40 seconds. The skips are opt-in system Chrome tests. The final 24-test
acceptance above also includes the last test-only refinements.

`python scripts/check-mcp-apps-sabotage.py` passes its unmodified control and
catches all five deliberately removed guards: model visibility, app visibility,
resource binding, post-IO authorization and UI-only result isolation. Mutations
run only in temporary copies and verify the working source hash is unchanged.
CI runs this alongside the existing G1 guard checks on Windows and Linux.

Adversarial source review also identified completion-order ambiguity for context
updates. The store now orders projections by the completion cursor, with separate
keys for context and ordinary actions. A regression approves proposals in reverse
submission order and verifies that the most recently approved context wins.

Ruff lint/format, mypy on native Windows and Linux settings, whitespace and staged
secret scans pass. Codegen from the new specs pin changes only generated provenance.
The frontend distribution build, including TypeScript checks and preview runtime,
passes. Agent catalogue parsing, archive pin and Workbench capability tests pass.

The distribution tree matches the source commit except for static files and
BUILD_INFO. Its published GitHub archive was downloaded and checked for the
adapter modules, page, preview runtime, source provenance and stamped archive SHA.
The agent catalogue points at that archive. This is publication, not deployment
to the live installation.

## CI and remaining gates

[G2 Workbench CI](https://github.com/eugene-plexus/workbench/actions/runs/38805157097)
completed successfully on Windows and Linux, including the frontend and guard checks
(checked during G3). Its result is separate from local acceptance.
The prior G1 run passed Linux and frontend checks, but Windows had one failure
in the existing Job Site signature workflow (2,020 passed, 28 skipped).
[Workbench #13](https://github.com/eugene-plexus/workbench/issues/13) tracks a
decline apparently lost between held-call polls. G2 uses the separate durable
interaction coordinator; this issue remains open and is not reported as fixed.

Backend capabilities identify MCP Apps 2026-01-26, its exact method allowlist and
`renderer: false`. Production `supportedProtocols` remains empty. UI policies
are preserved requests, not grants; no HTML is executed by this backend.
Resources are restricted to the bound UI document. Job Site/folder proxies,
arbitrary resources, links, downloads, sampling, elicitation and app-provided
tools are outside this declared subset. Messages/context are deferred to the next
explicit user turn. The next roadmap gate is A2UI backend integration (G3).
