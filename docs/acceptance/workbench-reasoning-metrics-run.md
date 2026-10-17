# Workbench Reasoning Metrics

2026-10-17. Workbench reasoning metrics and Edge publication.

The collapsed Reasoning header shows reasoning tokens and observed reasoning
streaming time. Provider-reported `completion_tokens_details.reasoning_tokens`
are used when every model request reports a valid count. Otherwise the visible
text's length divided by four is shown with `~` and `(estimated)`. This is not
a tokenizer measurement. Providers withholding their reasoning text can still
show a reported count.

Time accumulates from the first observed reasoning chunk until answer text,
tool calls, tool/prompt progress, or request termination. Tool waits and answer
streaming are excluded. This measures observed streaming time, not engine-internal
compute time. Values persist with the message through schema 19's additive
migration; older messages have no measured duration.

## Verification

- Backend regression checks: 109 passed, 3 optional browser checks skipped.
  Covered chats, schema migration, output caps, search suggestions, tools,
  versions, and citations.
- Final focused reasoning checks: 10 passed, 1 optional browser check skipped.
- Frontend message and event tests: 64 passed.
- Ruff check/format, mypy (70 source files), TypeScript, targeted ESLint and
  Prettier: passed. Both static builds passed, with the existing chunk-size warning.
- Real Chrome acceptance: passed at 1440px and 320px. Checked collapsed token
  estimates and duration, expand/collapse, reload persistence, no horizontal
  overflow, and no page errors. Used real isolated Workbench HTTP services with
  the test gateway, not a live model or production install.
- Three changed-code sabotages detected: zeroed elapsed time, discarded saved
  duration, and zeroed rendered duration. Original bytes restored and verified;
  normal focused tests passed afterward.

Screenshots are local ignored artifacts in
`workbench/.pytest_cache/reasoning-shots/reasoning-{1440,320}.png`.

Live-provider token accounting has not been verified against a running engine.

## Publication

| Input | Commit |
| --- | --- |
| Workbench source | `e61d880928c525ef1cac0c2aa8025eaa8225b067` |
| Workbench distribution | `74aa7c41880270054b8bb197f841ef532eaa3bcc` |
| Agent and app catalogue | `9a57c10e24e4f2caf30be5fc141b12ccbd051196` |

The distribution retains the previous distribution and source histories. All
183 static files match the committed build byte for byte. The public GitHub
archive returned HTTP 200 and retains the exact source provenance; a wheel
built from that downloaded archive retains all 183 static files, schema 19,
the reasoning backend, preview runtime and the distribution's own commit stamp.

The agent's 150 app/catalogue tests pass. Agent Ruff, formatting, mypy on both
platform targets and staged secret scanning pass. Workbench's publication
preflight repeats the 109 backend and 64 frontend checks, with lint, formatting,
both mypy platform targets, TypeScript and staged secret scanning passing.

The release manifest and both generated installers change only their agent
pin. Dependencies and other component pins are unchanged. Edge availability
depends on the release commit's workflows; their remote results are separate
from these local checks. No stable tag or running installation is changed.
Installed copies of Workbench still require their separate update from Apps.