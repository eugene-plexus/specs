# Interactive UI: inference prerequisites (G0)

2026-10-15. First backend milestone of
[Workbench UI interoperability](../design/workbench-ui-interoperability.md).
This records inference transport readiness, not implementation of AG-UI, A2UI
or MCP Apps.

Follow-up: [specs CI run 38796531895](https://github.com/eugene-plexus/specs/actions/runs/38796531895)
completed successfully, including this gate and sabotage on Windows and Linux.

## Code and environment

- Windows, Python 3.14.3, shared acceptance environment `agent/.venv`.
- Specs base `757c6c839cda855b1e270c16b0c3373a4873a41a` plus this slice.
- Gateway `d15342fed555feab31e5bc0a27431ddce2fe8c11`.
- Inference-driver `c116ef5d9c1db2258e9057423bc1ffbf4e88ed80`.
- Both component heads match the v0.2.2 installer pins. Git reported an existing
  modified generated `__init__.py` in each checkout; `git diff` showed no textual
  change. This slice did not edit either component.
- Real gateway HTTP server with a signed client key; real driver processes.
  Agent discovery/admission and provider endpoints are deterministic fixtures.
  Private temporary state, OS-assigned loopback ports, ambient Eugene variables
  cleared. No running installation, real provider, engine or GPU was used.

## Results

`scripts/genui-inference-acceptance.py`: **19/19 groups passed** (about six seconds).

| Check group | Local-compatible | Strata | OpenAI account |
|---|---|---|---|
| JSON object/schema forwarding, whole and streamed | Pass | Pass | Pass |
| UI JSONL and Unicode fidelity, whole and streamed | Pass | Pass | Pass |
| Two interleaved tool calls and tool-result continuation | Pass | Pass | Pass |
| UI metadata rejected before provider dispatch | Pass | Pass | Pass |
| Responses/Messages structured-output translations | Pass | Pass | Pass |
| Disconnect reaches provider and releases admission | Pass | Pass | Pass |

The nineteenth group uses a Strata-first/local-second slot: 429 falls back once;
an ambiguous 503, truncated text and truncated tool arguments do not replay.
The partial cases assert that actual text/tool fragments reached the caller,
and that the incomplete stream ends in an error rather than success.

Schema equality is checked at the fixture provider, not just at the gateway's
response. It covers `strict`, nested definitions and references. Function
arguments include Unicode, escaped quotes, backslashes, a newline, null, boolean
and numeric values; their fragments interleave across two tool-call indices.

`scripts/genui-inference-sabotage.py`: **passed**. A temporary driver copy drops
`response_format`. The schema gate fails specifically with
`response_format changed upstream`; a startup failure cannot satisfy the check.
The original driver's bytes remain unchanged.

Ruff lint/format, mypy on the two new scripts, local Markdown links, workflow
YAML parsing, `git diff --check`, and the staged Gitleaks scan also passed.

The initial run passed its 16 then-existing behavior groups but failed cleanup
because a temporary log remained open on Windows. A subsequent sabotage exposed
the driver's log too: terminating the Windows venv launcher can leave its Python
child briefly alive. The new gate closes the driver's parent-watch pipe and waits
for exit before removing temporary state. It also closes fixture listeners and
avoids temporary gateway log handlers. The completed run includes three additional
API-translation groups and checks that loaded component paths match the reported
checkouts (or the explicit temporary copy during sabotage).

## Coverage limits and next work

No product defect or required core contract change was found for these paths.
Results establish transport behavior with fixture providers. They do not establish
real-model generation quality, provider schema enforcement, all adapter families,
or UI protocol conformance. Python 3.12 on Windows/Linux is configured in CI;
those runs are not claimed by this local record.

G1–G4 remain backend implementation work: durable UI/action contracts, MCP Apps
resources and tool metadata, A2UI state/actions, and AG-UI adapters. Existing
Workbench rendering does not supply those capabilities. Production UI work waits
for their backend acceptance; browser isolation still needs its own later check.
