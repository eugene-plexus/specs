# Settings that tell the truth — run record, 2026-09-30

Design, the inventory of every setting and the decision table:
[`../design/settings-accuracy.md`](../design/settings-accuracy.md). The rule
(Troy, 2026-09-29, fundamental): **no settings widget anywhere in Eugene may
show a value other than the one in effect.**

## The decisions

The full table, with reasons, is in the design doc. In short, each **Troy's to
overturn** unless marked *Troy*:

| # | Call |
| - | ---- |
| 1-5 | *Troy:* `updateChannel` is binary, default `releases`; no install changes channel (settled once: a container from its image at load, a native install at its first check that reads the release list, `pending` until then); `infer_channel` gone as a rule; never offer an older build (placed per component by commit date); the `:edge` image defaults to `edge` from its environment. |
| 6 | A new native install from `main` follows releases and is told it is newer than the newest release. |
| 7-10 | *Troy, asked because they touch security:* secret presence reported, never values; driver address fields shown wherever read; `securityMode` not `requiresRestart`, plus a warning when the mode cannot work here; CORS/advertise display says what is in effect. |
| 11-16 | A value no widget can show is shown as itself; a file `null` is the default everywhere; restart results per PATCH, pending shown with what runs; agent-managed driver keys read-only; legacy stored defaults left alone; unset profile flags are not the schema default. |

## What was run

| Gate | Result |
| ---- | ------ |
| Contract | specs `c9098f7` + `7dcae2a` (the status level named, not inline); `openapi_spec_validator` on all six documents, Redocly lint, `r38-contract-checks.py --sabotage` 11/11 |
| agent (`ruff`, `mypy`, `pytest`) | **1434 passed**, 15 skipped; `tests/test_settings_truth.py` new (16), `test_updates.py` reworked for placement and settling (47) |
| gateway | **1035 passed** before the extra tests; `tests/test_settings_truth.py` 7 |
| library | **539 passed**; `tests/test_settings_truth.py` 5 |
| control | **266 passed**; `test_config.py` +4 |
| inference-driver | **851 passed**; `tests/test_settings_truth.py` 8 |
| tool-driver | **63 passed**; `tests/test_settings_truth.py` 4 |
| ui (`tsc`, `eslint`, `prettier`, `vitest`) | **123 files, 1485 tests**, then +1 (`configTrio.test.ts`); `ConfigFieldTruth.test.tsx` renders the bodies each component really serves (`src/lib/__fixtures__/settings-wire.json`, captured from each component's own code) |
| Every component repo's CI | green at the pinned commits |
| `scripts/settings-sabotage.py` | **65 of 65 caught** (second pass; below) |
| `scripts/settings-truth-acceptance.sh` | **ALL 34 CHECKS PASSED**, 8 of them in the system Chrome (second execution; below) |
| `scripts/navigation-acceptance.sh` | **15 of 15** browser tests, second execution (below) |
| Every acceptance script specs CI runs | **all 19 green locally** before pinning: s10 starter, r7 signing (13/13) and rotation (8/8), row3 per-node keys (27), r8 profile acceptance and checks (10 regressions caught), a3, a5, a6, a6b, p2 (18), p3 (27), p4 (15), p5 (8), p6 (9), p8 (15), a7 recovery checks, r7 launch boundary (15/15), r6 benchmark checks (6/6); plus s10-checks, release-artifacts-checks, a8-summarize, and in WSL r37 install.sh checks (97, 0 failures) and r37 sabotage (13/13) |
| Not run here | `windows-service-smoke.py` (installs a real service: elevation); `updates-system-install-acceptance.sh` (Linux root, CI); `compose-acceptance.sh` runtime half incl. the new check 28 (no container runtime on this box: CI builds the image) |

## The sabotage pass

`scripts/settings-sabotage.py`: 65 sabotages across all seven repos, each
putting back one way a setting lied, each restored from a byte copy, opened
with a baseline that every gate passes unsabotaged.

- **First pass: 44 of the first 45 caught, then the runner crashed** — at the
  first UI gate, printing vitest's `✓` to a cp1252 stdout (it restored every
  file first). The runner now reconfigures stdout to UTF-8.
- **The one escape named a missing assertion:** *the library's restart result
  is not per PATCH* passed because the library test put `logLevel` back and
  asserted only the schema's side (`pending_restart() == {}`), never the PATCH
  result. It asserts both now.
- **Second pass: 65 of 65 caught**, none expected to escape.

What they cover, by repo: the agent (20) — placement by date, a part the target
predates, the route's downgrade refusal, settling (not settled, guessed, marker
ignored, container left pending), a pending channel shown as the default, the
environment's default ignored, a reset written to the file, a file null shown,
`hasPassword`, a share reset refused, `securityMode` restart flag, the
passphrase warning, PATH not named, both halves of the companion keys; the
gateway (8) — cumulative restarts, file nulls, NaN, the empty-origin sentence,
the derived control root, pending in the schema, retention 0, the refresh
interval captured at start; the library (5); control (4, including an
anonymous caller being told what values are doing); the inference driver (6,
including `/v1/info` naming the saved provider); the tool driver (2); the UI
(20) — a non-choice drawn as the first choice, **the original bug itself** (an
unset enum with a default showing its first option), `Boolean(value)`, the
unset line, "none" for an empty list, the standby sentence borrowed, pending,
managed fields editable, share rows, `showWhen` on the document value, the cache
kept after a write, "newer" from an older agent, the ahead state, a newer
install named after an older release, web search, an emptied limit as 0, a
profile flag showing its schema default, a profile's engine drawn as the first,
an override looked up by exact string, overrides saved over when unread.

## The browser run

`scripts/settings-truth-acceptance.sh` builds a throwaway install on +400
ports (environment cleared, teardown by pid) whose files hold the old lies: an
`agent.yaml` from before the default (no channel, no marker, checks off so
nothing settles it behind the run), a gateway file with `loadBalancing: beta`
and `maxImagesPerRequest: 1000`. It then checks what each component serves (26
API checks) and drives the system Chrome through `ui/e2e/settings-truth.spec.ts`
(8 tests): the undecided channel shows *Not set* and *Not decided yet*;
choosing Releases saves and reads back, and afterwards `agent.yaml` holds it,
the marker exists and `GET /v1/node` says *releases, from the setting*;
`"beta" (not one of the choices)`; `1000` shown with *1 to 64*; *No cap*, *any
website*, the hub asked anonymously, *No standbys*; a gateway `logLevel` saved
over the API reads *runs on INFO until it restarts*; the two share logins read
*saved* and *no password saved*; the backend's saved provider waits for a
restart and its address is OpenRouter's own.

- **First execution failed one check, in the harness:** the served-build check
  looked for the widget's marker in the chunks Home names, and the settings
  widget is a chunk the Settings page loads on demand. It now finds the chunk in
  what was staged and requires the agent to serve that same file.
- **Second execution: ALL 34 CHECKS PASSED**, 8 browser tests in 16 s.

`scripts/navigation-acceptance.sh` against the same build: **14 of 15** first,
and the one failure was **stale since P8**, not this change — the tree spec
expected Backends to own two pages and P8 (`01fd6ee`) added *Add a search
account*. The expectation was corrected (ui `053def6`); **15 of 15** on the
second execution.

## SHAs

| Repo | Commit | What |
| ---- | ------ | ---- |
| specs | `c9098f7`, `7dcae2a` | the contract |
| agent | `ebf8947` | channel default and settling, placement by date, live schema facts, `hasPassword`, managed keys named to companions |
| control | `2e80343` | `securityMode`, per-PATCH restarts, status for authorized callers |
| gateway | `647186c`, `744964c` | per-PATCH restarts, nulls, NaN, unset meanings, retention 0, live refresh interval |
| library | `1e748e9`, `8122017` | nulls, empty token/address, default source, hub client refreshed on save |
| inference-driver | `fa99fa0`, `f5cf2e0` | fields shown where read, per-provider unset meanings, env key presence, managed keys, `/v1/info` |
| tool-driver | `c064c40`, `49c289f` | nulls, empty key, restarts, unset meanings |
| ui | `c7da4cb`, `053def6` | every widget; e2e specs |
| ui `dist` | `b93bbde` | export of `053def6` (source identical to `c7da4cb`), the build the browser run passed |
| specs | this commit | both installers pinned to the seven above; the `:edge` image's default channel (Dockerfile, compose, workflow, compose-acceptance check 28); the design doc, this record, the two scripts |

## Not done, named

- **Nothing here asked GitHub for a commit date.** The placement is unit-tested
  against GitHub's git-data answers as fixtures; the live endpoint was not
  called by this run (the throwaway install ran with checks off, so it stayed
  `pending` for the browser). The first real check on an updated machine is
  where it is exercised.
- **Troy's worker is not updated.** Amish_Station is a native alpha.5 install
  with no saved channel: after it runs this build it reads *pending* until its
  first check, which saves `releases` — what it follows today.
- **The container's default is checked by `compose-acceptance.sh` check 28 in
  CI**, not on this box (no container runtime here).
- The findings the design doc lists as *found, not fixed*.
