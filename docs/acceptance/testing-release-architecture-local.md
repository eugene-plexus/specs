# Testing and release architecture: local evidence

Scope: local implementation of the risk-based slice policy, conservative CI
planner, explicit Edge publisher/agent reader, and immutable Release
qualification. Operational policy and rollout order are in
[the runbook](../maintenance/testing-and-release.md).

## Observed checks

- Planner: 9 tests passed using real temporary Git histories, including
  dependency/unknown-input fallback and nested installer pin changes.
- Workflow contracts: 7 tests passed for planner wiring, reusable inputs,
  trusted publication, qualification imports and shipped UI payload selection.
- Edge publisher: 16 tests passed, including canceled/partial CI, stale run
  listings, exact per-run build artifacts, digest failures and real temporary
  Git fast-forward after registry verification. Remote writes were mocked.
- Release gate: 5 tests passed for exact workflow/run/tag/record/input binding
  and nested component pin resolution.
- Agent updater: 61 tests passed, 2 skipped. Reused after unchanged inputs;
  no claim that the skipped paths were exercised.
- Scoped Ruff lint/format, mypy (including the agent's Linux platform),
  actionlint and task-file secret scanning passed. Local Python was 3.14;
  the configured CI Python 3.12 execution has not run for these changes.
- Eleven critical-check mutants were caught by intended assertion failures
  in discarded temporary copies. A first nested-pin fixture did not kill its
  mutant; correcting it to change an existing pin produced the required failure.
- A read-only GitHub adapter check resolved a real successful Container image
  run. Pinned nested inputs were resolved from the actual committed agent
  blobs, not the current agent worktree.

Review corrected qualification that would otherwise test a rebuilt UI instead
of the shipped dist, and publication that would otherwise trust a mutable image
tag instead of the tested run's retained digest.

## Limits and rollout

No commits, pushes, repository settings, live installs, registry writes or
remote ref changes were performed. Full workflows, real registry promotion,
repository permission/ruleset behavior, packaged installs and upgrade recovery
have not been executed for this implementation. Local fixtures are not remote
publication acceptance or Release qualification.

Land the specs infrastructure first, verify its first receipts and protected
forward-only Edge marker, then land/pin the agent reader. Finish with the real
GitHub/registry publication and failure/retry trial described in the runbook.
Remote rollout remains pending. Registry retagging and Git ref movement are
separate operations, not an atomic transaction.