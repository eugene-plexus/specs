# Development plan: building the roadmap fast and safely

**Status: proposal, 2026-10-21, for Troy. None of it is in force until Troy
approves it.** Each approved rule then goes into `AGENTS.md`, which every
harness reads, and `CLAUDE.md` points to it.

**Goal:** build the [roadmap](roadmap.md) as fast as is safe.

**Terms used in this document:**
- **Row:** one numbered line of the roadmap.
- **Lane:** a queue of rows that edit the same files. One builder works a
  lane at a time, so two builders never edit the same file.
- **Builder:** an agent that builds one row on a branch. It can be a Claude
  Code subagent or an agent in another harness.
- **Orchestrator:** the one Claude Code session that runs the whole push. It
  writes designs and briefs, reads each diff, merges to `main` and runs
  `ship.py`.
- **Brief:** a row's instructions, kept in the row's GitHub issue.
- **Checkpoint:** a point where Troy answers calls, tests Edge, and can change
  the order.

## 1. Where the time goes today

Measured 2026-10-21 from the last 30 runs of every workflow, and from the
records in memory.

| Step | Minutes | Note |
|---|---|---|
| Local suites and acceptance before a merge (session time) | 30-45 per row | The largest cost, and it blocks the session. Over 14 sessions, local acceptance took ~240 min and local pytest ~195 min (memory, 2026-10-18) |
| Component CI on a branch | 1-19, started by hand | A branch push runs nothing. Agent takes ~10, Workbench ~17 |
| Specs CI on a branch, when several repos change | 17-20, started by hand | A dispatch always runs the full profile |
| `ship.py` local work | 1-2 | |
| CI after the ship push | 6 (selective) or 16-22 (full) | 10 of the last 17 ships ran the full profile |
| Publish Edge | 0.3 | |
| A call waiting for Troy | hours to days | 30+ calls are open today |

From a commit on a branch to Edge takes 10-40 minutes of machine time, plus
30-45 minutes of session time per row. One session builds one row at a time.

**Failures that cost a re-run:**
- Workbench CI failed 12 of its last 30 runs, mostly Windows pytest on `main`.
- 4 of the last 20 ship pushes had a red CI or image run.
- control, library, workbench and site-host have a pre-commit config but no
  installed hook. Nothing local runs the vendored-platform or codegen checks,
  and those fail in CI in under a minute.

**Slow suites:**
- The agent's pytest is serial: 10-13 minutes.
- Workbench's Windows pytest takes 13 minutes.
- Specs' pinned integration runs about 40 acceptance steps one after another:
  13-16 minutes per OS. Job Sites alone takes about 5.

**The roadmap's shape:** 69 rows. 24 are high risk. 14 are size L, and 15 need
a full design before anyone builds them.

## 2. The plan in brief

1. Fix the pipeline first (Wave 0, about one day).
2. Run up to six builders at the same time, one per lane.
3. Make green CI on the branch the merge gate. Sessions stop running full
   suites and acceptance locally.
4. Never stop a row for a call. The builder builds the recommended option.
5. Only the orchestrator merges to `main` and runs `ship.py`. Builders never
   push `main`.
6. Have a second model review each high-risk row while its CI runs.
7. Troy answers calls and tests Edge at checkpoints.

## 3. Rule changes

Each row below is one decision for Troy (P1-P11).

| # | Rule today | Proposed rule | Why | What keeps it safe |
|---|---|---|---|---|
| P1 | Component CI runs on `main` pushes and PRs. A branch run is a hand dispatch | Every repo's CI runs on every push to every branch. A new push cancels the older run on the same branch | Removes a hand step. The result is ready by merge time | The repos are public, so Actions minutes cost nothing. The real limit is concurrent jobs (§11) |
| P2 | Before a merge, `runner` runs full suites and acceptance locally | The merge gate is green CI on the branch: component CI in each repo the row touches, plus specs branch integration when two or more repos change. Locally, a builder runs only the changed files' tests and the pre-commit hooks | Local runs were the largest cost | CI runs the same suites on Linux and Windows. The Edge gate does not change |
| P3 | A high-risk row needs a real-environment acceptance run by a session and one adversarial review, one after the other | The acceptance is a script that runs in CI on real Linux and Windows processes. One adversarial review by a second model runs at the same time as CI. Only a blocker finding stops the merge | The checks stay; only the waiting goes | Changes to the Windows service or UAC still get one elevated run on this machine. The builder asks Troy for it |
| P4 | An open call stops a row, or a session asks Troy | Build the recommended option and mark it "default built" in the design. An option that deletes data, or keeps people's chats somewhere new, ships switched off until Troy confirms. Troy answers calls in one batch at each checkpoint | Calls were the longest waits | Troy can overturn any default. The risky defaults stay off until he says |
| P5 | Each slice gets an acceptance record, a run document and a handoff | A row's GitHub issue holds its brief and status. The design doc gets 3-10 lines of "what building found". Only a release keeps an acceptance record | Writing records cost time and nobody read most of them | The issue, the commits and the CI runs are the record |
| P6 | A fresh session per slice. Design, review and merges stay in the main session | One orchestrator session runs the whole push, with auto-compaction on. Builders build the rows | Parallel building | The orchestrator reads every diff before it merges |
| P7 | Merge per piece of work, after one set of checks | Merge each row when its CI is green and its review has no blocker. Rebase on `main` first. Merge green rows in batches and run `ship.py` once per batch, at most every 30 minutes | Keeps Edge from changing too often while rows land quickly | Each batch passes the Edge gate |
| P8 | `AGENTS.md` says "commit on `main`"; `CLAUDE.md` says branch only | One rule set in `AGENTS.md` for every harness (Appendix A). `CLAUDE.md` points to it | Agents in other harnesses do not read `CLAUDE.md` or memory | One source of rules |
| P9 | Subagents default to Sonnet, and the weekly allowance binds | For this push: Opus builders for high-risk and size-L rows, Sonnet for S and M rows, Haiku for CI waits | Weak builders cost rework | Troy's call on budget |
| P10 | A flaky test gets run again | Fix a flaky test the same day, or skip it with an issue number. Never re-run it silently | Flakes block every lane | Each skip has an owner and a deadline |
| P11 | The ship push carries contract and script commits, so CI runs the full profile | Push merged rows to `main` as they merge. `ship.py` then pushes its pin commit alone, so the ship runs the selective profile | 6 minutes, not 19 | The full profile still runs on each merge's own push |

**Rules that stay:**
- Edge publication: CI and image receipts on identical inputs, and the
  security hold.
- A test that fails without the change, for every behaviour change and every
  defect.
- One adversarial review for each high-risk row.
- Release qualification, unchanged.
- Acceptance never runs on the default ports on this machine, and anything
  that starts an agent clears every `EUGENE_PLEXUS_*` variable.
- The test accounts stay.
- Stage files by path, and keep secrets out of commits.
- The product rules: settings never lie, failures name their observed cause,
  an easy default with an expert override, GUI equality, no terminal steps for
  users. Appendix A carries them for other harnesses.

## 4. Roles

| Role | Who | Does |
|---|---|---|
| Troy | Troy | Answers calls at checkpoints, tests Edge, changes the order |
| Orchestrator | One Claude Code session (Opus) | Writes designs and briefs. Answers builders' questions. Reads every diff. Merges, runs `ship.py`, files issues. Reports to Troy |
| Builders | Up to six at a time: Claude Code background subagents, and agents in other harnesses | One row at a time from one lane, on a branch, to green CI |
| Reviewer | A second model: another harness, or a Claude subagent on a different model | Adversarial review of each high-risk row, while its CI runs |
| Fix lane | One builder, when needed | Red CI on `main`, flaky tests, defects Troy finds on Edge |

## 5. Lanes and their queues

The lanes come from the files each row edits: one builder per lane, so no
two builders edit the same file. A row moves only when its "needs" rows are
merged. When a lane's next row is blocked, the lane takes its next unblocked
row.

| Lane | Files it owns | Rows, in order | Builder |
|---|---|---|---|
| OPS | specs scripts, CI workflows, installers | Wave 0, then 1, 2, 6, 8, 10 | Claude |
| TRUST | control trust and keys; the agent's identity and trust | 3, 4, 5, 46, 45, 36, 39, 37 (after its design) | Claude, Opus. Every row is high risk |
| GW | gateway request path; client keys | 24, 11, 12, 14, 19, 57, 54, 55, 40, 59, 58, 56 | Claude |
| ENG | the agent's engine adapters | 9, 18, 13, 17, 20, 15, 41, 42, 63, 66, 50, 68, 44 | Claude |
| WB | Workbench's store and server | 7, 27, 28, 30, 26, 47, 32; MV5b once MV5b-C1 is taken | Claude. The brief assigns each store migration its number |
| LIB | library | 16, 22, 21, 65, 64, 48, 61, 43 (with ENG), 67 | Claude, or another harness |
| WEB | console and Workbench web pages | 33, 62, 31, 38 (after 12), the card and view parts of 69 | Another harness: TypeScript only, low coupling |
| AG2 | the agent's apps, tray and folders; site-host | 23, 35, 34, 51, 52, 25 (after its design), 60 | Another harness, or Claude |
| Design | `docs/design/` | Full designs, in roadmap order: 26, 25, 37, 38, 40, 44, 47, 49, 50, 52, 53, 56, 58, 60, 67, 32. Short designs one row ahead of each lane | The orchestrator |

**Which lanes start first:** OPS, TRUST, GW, ENG, WB and LIB. Add WEB and AG2
when agents in other harnesses are ready.

**The busiest shared files (from the 2026-10-21 analysis):**
- `gateway.yaml`: 12 rows edit it. Most are in GW; rows 1, 13, 29, 37 and 38
  merge in roadmap order.
- `gw/routes/inference.py` and `gw/routing.py`: the GW lane holds them.
  Rows 13 and 61 touch them lightly and merge after the GW row ahead of them.
- `ag/engines/llama_cpp.py` and `vllm.py`: 10 rows, all in ENG.
- `wb/store.py`: 6 rows, all in WB, each with its own migration number.
- Every repo's `scripts/codegen.py`: row 1 lands first and alone among
  contract rows.

## 6. Wave 0: fix the pipeline (about one day)

Five builders run these at the same time. The orchestrator writes
Appendix A and the agent definitions.

| # | Task | Target |
|---|---|---|
| W0.1 | CI on every push to every branch, in every repo, with cancel-in-progress per branch | No hand dispatches |
| W0.2 | `scripts/branch-ci.py <branch>`: dispatch specs CI with the `*_ref` inputs of every repo that has the branch, and give it a base so the planner can choose the selective profile | Cross-repo rows tested in CI |
| W0.3 | Split the pinned-integration acceptance steps across parallel jobs | Under 7 minutes per OS (today 13-16) |
| W0.4 | `pytest -n auto` for the agent (pytest-xdist) | Under 4 minutes (today 10-13) |
| W0.5 | Fix Workbench's failing Windows suite and workbench#16 | 0 red runs from flakes |
| W0.6 | Install pre-commit in every repo, and add the vendored-platform and codegen-freshness checks | These failures found in seconds, before a push |
| W0.7 | `ship.py`: push the pin commit alone (P11) | Ships run in about 6 minutes |
| W0.8 | `scripts/worktree.py <branch> <repos...>`: a same-named worktree in each repo, its own uv venv, and a check that imports come from the worktree, not the `main` checkout | Safe parallel worktrees |
| W0.9 | Rebuild the local venvs on Python 3.12, as CI uses | Local results match CI |
| W0.10 | `scripts/roadmap-issues.py`: one GitHub issue per row, with the brief, and lane, risk and needs labels | The work queue |
| W0.11 | Appendix A becomes `AGENTS.md`; `CLAUDE.md` points to it | One rule set |
| W0.12 | `builder` and `reviewer` agent definitions in `.claude/agents/` | Briefs run the same way every time |

W0.8 matters before any builder starts. A worktree that uses the `main`
checkout's venv tests the `main` checkout's code, through its editable
install.

## 7. How a row moves

**The orchestrator:**
1. Write the row's brief in its issue (Appendix B).
2. Label the issue `ready`.

**The builder:**
3. Assign the issue to yourself, and label it `building`.
4. Run `scripts/worktree.py r<row>-<slug> <repos>`.
5. If the row changes a contract, edit the specs yaml first, and push the
   specs branch.
6. Set each consumer's `SPECS_REF` to that specs commit, and regenerate from
   the repo's own venv.
7. Write the test that fails without the change.
8. Make the change.
9. Run the changed files' tests and the pre-commit hooks.
10. Push the branch in every repo you changed. CI starts by itself.
11. If you changed two or more repos, run `scripts/branch-ci.py <branch>`.
12. If the row is high risk, label the issue `review`. The reviewer starts.
13. When CI is green, comment on the issue: what changed, what building
    found, and which defaults you built. Then label it `green`.

**The orchestrator:**
14. Read the diff, and the review if there is one.
15. If `main` moved, have the builder rebase. Wait for CI to pass again.
16. Fast-forward `main` in each repo, specs last.
17. When the batch is ready, run `python scripts/ship.py --wait` in the
    background.
18. When Edge carries the row, close the issue and mark the row built in the
    roadmap.

A fast-forward keeps commit SHAs, so a `SPECS_REF` that names a specs branch
commit stays valid after the merge. A rebase of specs changes the SHA, so the
consumers' `SPECS_REF` must be set again.

## 8. Checkpoints

| Checkpoint | When | Troy |
|---|---|---|
| K0 | Wave 0 is done | Says whether the pipeline targets were met |
| K1 | Rows 1-8 are merged | Decides on v0.3.1: stable installs get TLS between machines, key rotation and the installer pass |
| K2 | Rows 9-15 and 24 are merged | Tests the speed work on Edge |
| K3 | Part 3 (rows 21-35) is merged | Tests the features |
| K4 | Part 4 is merged | Tests multi-machine and business features |
| K5 | Parts 5 and 6 are merged | Release |

At each checkpoint, Troy also answers the calls collected since the last one,
and can reorder the rows.

## 9. Calls to answer before the lanes start

They are in Troy's calls file, `docs/private/calls.md`, sections 1 and 2:
P1-P13 for this plan, and the calls of the rows the first lanes build. Under
P4, builders build each recommendation until Troy answers otherwise.

## 10. Using agents in other harnesses

- **Rules:** each agent reads `AGENTS.md` (Appendix A) and the row's issue.
  Neither the agent nor the issue may assume memory or `CLAUDE.md`.
- **Working copy:** each agent works in its own worktree (W0.8) or its own
  clone, never in the `main` checkouts.
- **Branches:** each agent pushes a branch named after the row. It never
  pushes `main`.
- **Cloud agents** (for example Codex cloud, the Copilot coding agent,
  Jules) work from GitHub and cannot run Windows tests. CI runs them.
- **Good lanes for them:**
  - WEB: TypeScript pages with little coupling.
  - AG2: separate agent modules.
  - LIB: a small, well-tested repo.
- **Second-model review:** a different model reviews each high-risk row from
  Claude builders. A Claude reviewer reviews their high-risk rows.

## 11. Risks and controls

| Risk | Control |
|---|---|
| Two builders edit the same file | Lanes (§5). One builder per lane |
| Contract changes collide | Contract edits go first, on a specs branch. Fast-forward merges keep SHAs. Most `gateway.yaml` rows are in one lane |
| Rows pass alone and fail together on `main` | Branch integration in CI (W0.2). Rebase before merge. Batched ships pass the Edge gate. The fix lane takes red `main` first |
| Workbench store migrations collide | One WB lane. The brief assigns the migration number |
| CI jobs queue | Superseded runs are cancelled. Specs branch integration runs only for cross-repo rows. W0.3 splits the long jobs. Move to the Team plan if queues show |
| The orchestrator becomes the bottleneck | Precise briefs. Reviewers screen high-risk diffs. Merges go in batches |
| Edge changes too often for Troy's own install | One ship every 30 minutes at most (P7). Checkpoints for testing |
| Speed lowers quality | A failing test first. A second-model review for high-risk rows. The Edge gate. Release qualification unchanged. Troy's tests at checkpoints |
| The weekly allowance runs out | The model mix in P9. Troy's call |

## 12. Expected pace

This is a first estimate. K1 measures the real rate.

- **Builder hours:** about 2 for an S row, 5 for M and 14 for L, CI included.
  The 69 rows total about 480 builder-hours.
- **Rate:** six builders at about 10 productive hours a day give about 60
  builder-hours a day.
- **Calendar:**
  - Wave 0: 1 day.
  - Rows 1-35: about 1.5-2 weeks.
  - All 69 rows: about 4-5 weeks.
  - The long poles are the 15 full designs (the orchestrator writes them
    while the lanes build), Troy's calls, and the merge rate on the GW and
    ENG lanes.

## Appendix A: proposed `AGENTS.md`

```markdown
# Rules for coding agents (every harness)

The component repositories are siblings of this one (../agent, ../ui,
../workbench, ...). This repository holds the contracts, the installers, the
release pins and the roadmap (docs/design/roadmap.md).

## Your work
- Work only on the row in your issue. Its brief says what to change, which
  files, the tests, the risk and the done-when.
- Never commit to main. Never push main. Never run ship.py.
- Make a worktree for your branch: python scripts/worktree.py <branch> <repos>.
  Never work in the main checkouts.
- Push your branch in every repository you change. CI runs by itself.
- Change a contract (openapi/*.yaml) first, on the specs branch. Set
  SPECS_REF in each consumer to that commit, and regenerate from that repo's
  own .venv.

## Tests
- Write the test that fails without your change, first.
- Locally, run the tests for the files you changed and the pre-commit hooks.
  Do not run full suites or acceptance scripts: CI runs them.
- If you change two or more repositories, run
  python scripts/branch-ci.py <branch>.
- A flaky test is not re-run silently. Report it on your issue.
- Never run an acceptance script on the default ports (8079-8083). Clear
  every EUGENE_PLEXUS_* variable in anything that starts an agent.

## When you finish
- Comment on your issue: what changed, what building found, and the defaults
  you built for open calls.
- Label the issue green when CI is green.
- A question for Troy goes on your issue. The orchestrator adds it to his
  calls file. Build the recommended option meanwhile.

## Product rules (they apply to every change)
- A setting never shows a value other than the one in effect.
- A failure names its observed cause.
- An easy default, and an expert override.
- What an operator can configure is configurable in the GUI.
- No terminal steps for end users.
- UI text: lead with the state or action, in one line. No internals.
- Write in the spirit of ASD-STE100: direct sentences, one action per step,
  one word for one meaning.
- Out-of-scope bugs go in a GitHub issue on the repository that owns the fix.
- git commit -s on every commit (DCO).
```

## Appendix B: the row brief (issue body)

```markdown
**Row:** <n>, <title> (roadmap.md)
**Lane:** <lane>     **Risk:** low | cross | high     **Size:** S | M | L
**Needs (merged first):** rows <n>, <n>
**Design:** docs/design/<doc>.md §<section>
**Open calls and the default to build:** <call>: <recommended option>
**Repositories:** <repos>     **Contract:** <yaml or none>
**Files you will likely change:** <paths>
**Do not change:** <files other lanes own right now>
**Store migration number (Workbench only):** <n>
**The test that must fail before the change:** <description>
**Done when:**
- <observable behaviour>
- CI green in every repository; branch integration green if two or more repos
- High risk only: the reviewer's findings answered
```
