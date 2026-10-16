# Interactive content browser acceptance (G5)

2026-10-15. Workbench now exposes the G1–G4 backends through its product UI:
self-contained MCP Apps, A2UI forms and native/external AG-UI conversations.
The [browser contract and capability matrix](../design/workbench-ui-browser-v1.md)
define the supported subsets. MCP Apps uses a constrained opaque-origin offline
sandbox; this is **not full upstream MCP Apps browser conformance**.

## Published sources

- Final contract and Workbench specs pin: `13688ded8a2b1896e93e1a3fe340cca89982c88c`.
- Workbench source: `61c6d5d14a31b7c45aa1254c1e992731c845cdb5`.
- Workbench distribution: `00c0f61d2e15b8f2767c827e4fcb058d21bab1a4`.
- Agent catalogue: `82a6ffa54c1ca1b5ed2d2e09709a2360c4a0389b`.

Wire versions remain MCP Apps 2026-01-26, A2UI 0.9.1 forms-v1 and AG-UI 1.0,
with the unchanged upstream locks and vendored hashes. SQLite schema remains 17.
Renderer capabilities require the built `ui-capabilities.json` marker; a headless
or source-only install continues to report no renderer. The MCP capability names
`opaque-offline`, `constrained`, `no-network`, `no-devices` and `opaque-proxy-origin`.

## Browser run of record

Windows, CPython 3.12.14, system Chrome through Playwright, actual built Workbench
frontend and Python HTTP server. Isolated OIDC/gateway fixtures, MCP SDK producers,
an HTTP reference AG-UI agent and temporary SQLite databases use OS-selected
loopback ports. Ambient Eugene variables were cleared. No installed service,
live model, account configuration or production data was changed.

`tests/test_ui_browser.py` passed **3 tests in 24.28 seconds**: real Chrome
product acceptance, the owner-only people picker and sandbox response headers.
The browser exercises both light and dark modes at 1280 by 900, accessible field
labels and keyboard submission, plus reload, read-only views and teardown.

| Boundary | Observed result |
| --- | --- |
| MCP rendering | Explicit Open app, two opaque sandboxed frames, initialization followed by tool input and result, theme changes and size updates |
| MCP isolation | Parent DOM, cookies, storage, top navigation and popup attempts refused; response CSP blocked fetch and image network probes; counted probe requests remained zero |
| MCP bridge | Forged window source, origin and channel messages produced no action; unknown methods refused; duplicate RPC ID did not repeat the tool effect |
| MCP action | Host-owned source label, exact method/arguments and Allow once review; producer counted `show` and one approved `increment`, with no extra effects after replay/reload |
| MCP lifecycle | An actual infinite loop stopped answering ping and was closed; a later app could open; reload never auto-opened an app; removing the source unmounted its frame and retained fallback |
| A2UI form | Two edited fields saved sequentially with returned revisions; labeled input and checkbox; keyboard action proposal, host approval and exactly one producer effect with saved values `Grace` and `true`; reload retained those values |
| Read-only views | Owner read-chat access exposed fallback but no executable MCP frame or action; A2UI inputs remained disabled |
| Agent configuration | Owner GUI created an immutable agent connection and granted Ada access; token field cleared after saving; server supplied known people independently of read-chat permission |
| Native AG-UI | Empty-chat agent selection and a completed answer through Workbench's existing gateway path |
| External AG-UI | Tool trace/state display, exact saved continuation, reload, interrupt response and explicit Stop with an uncertain outcome; five counted reference-agent requests, all with its configured fixture token |

The browser reported no page errors. Snapshot polling is once per second; the
backend remains authoritative for access, revisions, approval, dispatch and run
projections. Branch/access/replay backend tests also passed in the complete suite.
These fixtures test integration behavior, not model generation quality. The
separate [G3 QWen sample](genui-a2ui-run.md#running-model-generation-sample)
remains the model evidence.

## Regression, review and sabotage evidence

The complete backend suite passed **2,150 tests, 29 skipped** in 980.68 seconds.
The skips are opt-in/environment checks, including the separately executed G5
Chrome test. The frontend suite passed **3,243 tests in 87 files**. The final
trusted-source-label change also passed 27 interaction/MCP regression tests and
the browser run above.

The preceding G4 CI failed on stale schema-16 assertions and timing issues.
This slice updated the assertions to schema 17, made the native-disconnect
fixture actually wait, and fixed a signature decision being replaced during
site polling. It also fixed AG-UI emitting an empty tool result while a signature
was still pending. Dedicated tests prove a decline is consumed and the eventual
tool result is emitted exactly once. This record does not claim resolution of
every issue covered by the older Workbench #13 report. The remaining cases were
subsequently covered by the [2026-10-16 follow-up](signed-call-poll-race-2026-10-16.md).

Adversarial review and browser failures also led to preserved dirty form drafts,
edit-revision checks, reachable-only validation, distinct shared-component label
IDs, rejection of nested interactive button contents, stale-run-read protection,
durable ambiguous-start IDs, bridge initialization/request bounds, and host-owned
source labels. A missing heartbeat closes a stuck app. Chrome can briefly retain
the blocked sandbox process after removal, so an empty proxy that never becomes
ready may restart at most six times with a new channel; loaded apps are never
automatically replayed.

All **31 deliberate mutations** were caught in temporary copies:

- G1: four guards covering replay, revision, session and owner redaction.
- G2: five guards covering visibility, resource binding, post-I/O authorization
  and UI-only result isolation.
- G3: six guards covering context, typed input, completion, data-model opt-in,
  model projection and atomic refusal of invalid updates.
- G4: seven guards covering request binding, ownership, grants, state deltas,
  terminal order, checkpoint cancellation and restart recovery.
- G5 frontend: six guards covering frame source, origin, channel, duplicate RPC,
  form revision and saved continuation.
- G5 backend/browser: the two signature regressions and an actual Chrome CSP
  probe after weakening `connect-src`.

Unmodified controls passed. Working-source fingerprints remained unchanged in
the final sabotage passes. CI now runs the six frontend and two backend G5
mutations; the real Chrome CSP mutation remains an explicit local acceptance.

Ruff lint/format, native and Linux-target mypy, TypeScript strict checking,
ESLint, Prettier, source whitespace checks and staged secret scans passed.
Codegen from the published pin passed. The frontend/preview build passed with
its existing large-chunk warning. The agent's three catalogue checks, Ruff,
native/Linux mypy and staged secret scan also passed.

## Distribution and limits

The distribution differs from source only by BUILD_INFO and 183 built files.
Its downloaded GitHub archive matched the source modules, source SHA, stamped
distribution SHA, all A2UI/AG-UI schema hashes and every final frontend asset,
including the renderer marker. A wheel built from that exact archive imported
the packaged modules under Python 3.12 and passed stamp, CSP, capability-marker
and schema checks. Wheel SHA-256:
`744912061eaff1bf1ec2c0aa3739a5c78ab80d2b2cb9e92b2ab4ed615885ccad`.

Network/device-dependent MCP Apps retain fallback. Upstream's separate-origin
proxy with allow-same-origin is not implemented. A2UI uses the eight-component
local forms catalog, four pure functions, plain text and host palette. AG-UI
retains the G4 event subset and never promotes remote custom data into trusted
HTML. Firefox, Safari, mobile layouts and assistive-technology certification were
not measured in this run. Linux-target typing is not Linux browser acceptance.

Publication and catalogue pinning are complete; **the live installation was not
upgraded**. [Workbench CI](https://github.com/eugene-plexus/workbench/actions/runs/38829077072)
was still running at publication; the page job, codegen freshness and secret scan
had passed. [Agent catalogue CI](https://github.com/eugene-plexus/agent/actions/runs/38829274764)
was also running after its push. G0–G5 are implemented
for these declared subsets; full MCP Apps web conformance remains future work.
