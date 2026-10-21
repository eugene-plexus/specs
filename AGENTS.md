# Rules for coding agents (every harness)

These rules apply to every coding agent in this project: Claude Code, Codex,
Copilot, Gemini and any other. Troy approved them on 2026-10-21
([development plan](docs/design/development-plan.md)).

The component repositories are siblings of this one (`../agent`, `../ui`,
`../workbench`, ...). This repository holds the contracts, the installers,
the release pins and the [roadmap](docs/design/roadmap.md).

## Roles

- **Builder:** you build one roadmap row, on a branch, until its CI is green.
  The row's GitHub issue in this repository (label `row`) is your brief.
- **Orchestrator:** one Claude Code session. It writes the briefs, reads every
  diff, merges to `main` and runs `scripts/ship.py`.
- **Reviewer:** a second model that reviews each high-risk row while its CI
  runs.

## Your work

- Work only on the row in your issue. Its brief says what to change, which
  files, the test, the risk and the done-when.
- Assign the issue to yourself, and set its label to `status:building`.
- Never commit to `main`. Never push `main`. Never run `scripts/ship.py`.
- Make a worktree for your branch, named after the row:
  `python scripts/worktree.py add r<row>-<slug> <repo> [<repo> ...]`.
  It gives each Python repository its own `.venv`. Never work in the `main`
  checkouts. A worktree that uses the `main` checkout's venv tests the `main`
  checkout's code.
- Do not edit a file that the brief's "Do not change" line names: another
  lane owns it now.
- Change a contract (`openapi/*.yaml`) first, on the specs branch. Push it.
  Set `SPECS_REF` in each consumer to that specs commit, and regenerate from
  that repository's own `.venv`. Never write `SPECS_REF` with PowerShell
  `Set-Content -Encoding utf8` (the BOM breaks the archive URL).
- Commit with `git commit -s` (DCO). Stage files by path. Never `git add -A`
  in `agent`: its runtime configs can hold secrets.
- Push your branch in every repository you change. CI starts by itself.

## Tests

- Write the test that fails without your change, first.
- Locally, run the tests for the files you changed and the pre-commit hooks.
  Do not run full suites or acceptance scripts: CI runs them.
- If you change two or more repositories, CI on the specs branch runs the
  cross-repository integration with your branches. To start it by hand:
  `python scripts/branch-ci.py <branch>`.
- A high-risk row (auth, privileges, destructive file operations, migrations,
  installers, publication gates) also gets an acceptance script that runs in
  CI. Set the issue to `status:review`; the reviewer starts.
- A flaky test is never re-run silently. Fix it, or skip it with
  `reason="<repo>#<issue>: ..."` and open that issue.
- Never run an acceptance script on the default ports (8079-8083). Clear every
  `EUGENE_PLEXUS_*` variable in anything that starts an agent. Never touch the
  live install.

## Open questions and calls

- A question for Troy goes on your issue as a comment. The orchestrator adds
  it to Troy's calls file. Meanwhile, build the recommended option.
- A default that deletes data, or keeps people's chats somewhere new, may ship
  on when it is better for the project. Say so in your issue comment, so the
  orchestrator can call it out to Troy.

## When you finish

- Comment on your issue: what changed, what building found, and the defaults
  you built for open calls.
- When CI is green in every repository, set the issue to `status:green`.
- The orchestrator rebases if needed, merges, and ships at most once an hour.

## Product rules (every change)

- A setting never shows a value other than the one in effect.
- A failure names its observed cause.
- An easy default for a person with no technical knowledge, and always an
  override for an expert.
- What an operator can configure, the GUI can configure.
- No terminal steps for end users.
- A bad config never stops a component from starting; its config endpoints
  stay reachable.
- Once a machine is connected, the person never opens another machine's UI to
  manage it.
- UI text leads with the state or the action, in one line. No internals.
- Write in the spirit of ASD-STE100: direct sentences, one action per step,
  one word for one meaning.
- Out-of-scope bugs go in a GitHub issue on the repository that owns the fix.

## Architecture (immutable)

- Polyrepo with this shared specs repository. Components share schemas,
  never code.
- OpenAPI 3.1 for everything. Codegen: `datamodel-code-generator` and
  `openapi-python-client` for Python, `openapi-typescript` for TypeScript.
  Never the Java `openapi-generator`.
- A routing gateway above per-backend inference drivers. Never collapse the
  two layers.
- Every component serves `GET /v1/config`, `GET /v1/config/schema` and
  `PATCH /v1/config`.
- One HTTP client per instance, built through the repository's `_http.py`.
- `time.perf_counter()` for durations, never `time.monotonic()`.

## Edge

`scripts/ship.py` (the orchestrator runs it) pushes `main`, builds the `ui`
and `workbench` `dist` commits, pins Workbench and the site host in the
agent, updates `release/manifest.json` and both installers, and pushes this
repository. The `edge` branch moves only when CI and the container image pass
for the same content. If a dependency changed, `ship.py` stops and asks for
the lock to be re-resolved:
`python scripts/release-inputs.py --resolve --uv <uv>`.
