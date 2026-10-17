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

| Input                   | Commit                                     |
| ----------------------- | ------------------------------------------ |
| Workbench source        | `a25f269e1e785ffd722bdd004bb4476f9eb94269` |
| Workbench distribution  | `6a0424cab7f9e4173592e81e95c4c20fa73da33c` |
| Agent and app catalogue | `0374066137040ee83b95e508feb394ae4c8e1975` |

The distribution retains the previous distribution and source histories. All
183 static files match the committed build byte for byte. The initial public
GitHub archive (`74aa7c4`) returned HTTP 200; its wheel retains all 183 static
files, schema 19, the reasoning backend, preview runtime and its own commit stamp.
The final public archive (`6a0424c`) also returned HTTP 200 and has the corrected
source provenance. All 183 static files and 281 package files are byte-identical
to the initial archive; only the package's own commit stamp changes.

The agent's 150 app/catalogue tests pass. Agent Ruff, formatting, mypy on both
platform targets and staged secret scanning pass. Workbench's publication
preflight repeats the 109 backend and 64 frontend checks, with lint, formatting,
both mypy platform targets, TypeScript and staged secret scanning passing.

The release manifest and both generated installers change only their agent
pin. Dependencies and other component pins are unchanged. Edge availability
depends on the release commit's workflows; their remote results are separate
from these local checks. No stable tag or running installation is changed.
Installed copies of Workbench still require their separate update from Apps.

## CI Follow-Up

The initial Edge commit `b35a21d57b1a466a78c5aaef9461950815364337`
passed specs CI, A4 macOS and container publication. Workbench's full CI exposed
12 stale schema expectations in four migration test files. The correction
preserves historical input fixtures, expects schema 19 and verifies the appended
columns. All 58 tests in those four files pass; runtime behavior is unchanged.
The distribution and catalogue were refreshed to the corrected source above.

Agent's forwarding test failure reproduces on the unchanged parent `34a38dc`:
an empty Cookie header is present where the test expects the header absent.
This predates the catalogue change and is tracked as
[agent#18](https://github.com/eugene-plexus/agent/issues/18); it is not changed here.