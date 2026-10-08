# A warm standby that follows (control#5) — record

**2026-10-08. Built, run and pinned.** Design:
[`warm-standby.md`](../design/warm-standby.md) (SB1–SB4, taken by Troy the
same day; §7 says what building found). Issue:
[control#5](https://github.com/eugene-plexus/control/issues/5).

An owner makes one machine the install's standby on Machines. That machine's
agent starts a standby control root by itself, which follows the active root
with its own `sub: standby` token. Nothing else reads the replication
surface. Removing the grant refuses the next pull at once, and the agent
stops the standby and deletes its copy of the replication set.

| Repo | Commit | What |
|---|---|---|
| specs | `1e76272`, `c65170f`, `62ef542` | contract: `TrustGrant.standby`, `makeStandby`/`stopStandby`, `LogOp.setStandby`, `TrustChange` reason `standby` and `standbyNode`, `StandbyStatus.node` (its `url` optional), `LocalStandby`, `NodeIdentity.standby` and `hostsControl` |
| control | `c4b5e40`, `c4a5a6f` | `setStandby`, the two node routes, `require_replica`, the follower's `StandbyToken`, `standby_reports`, status from the grant, `promote` takes the grant, `standbyUrls` retired |
| agent | `e87f5d3`, `cd8880e`, `bbc6aaf` | `standby.py` (`reconcile`), the planner's standby wiring and spawn token, `mint_service` for `sub: standby`, `GET /v1/node` `hostsControl` and `standby`; then a refused bundle write kept and written later (below) |
| gateway, library, inference-driver, tool-driver | `2044974` `3c27ceb`, `49c6652` `ae9e2d0`, `3a161f8` `d549ad9`, `e0da783` `9a8c79e` | the shared token module (`GRANT_STANDBY`, `SUB_STANDBY`, the rule in `_check_grants`), regenerated at `c65170f` |
| ui (`main`) | `5203605` | `StandbyPanel` on Machines, "· standby" in the Role column, `standbyUrls` gone from Settings |
| ui (`dist`) | `e8b0a1f` | the build of `5203605` |
| specs | `e17c1a6` | `platform/1.0.0/tokens.py`; `scripts/standby-acceptance.py` and its CI step; `scripts/standby-sabotage.py`; the pins in `release/manifest.json` and both installers |
| specs | this commit | agent re-pinned to `bbc6aaf`; the acceptance reads the standby's port from B; three more sabotage cases |

**The second commit in each Python repo is `VENDORED.json`.** `tokens.py`
is vendored from specs `platform/1.0.0/`, and the build edited the six copies
without the source. Each consumer's CI failed at *Verify vendored platform
integrity*, the step before its tests. The platform copy now matches the six,
`vendor-platform.py --check` passes, and the second commit carries each
repo's new hash.

## The acceptance: `scripts/standby-acceptance.py`

**8 of 8 passed** (16 s; Windows, `agent/.venv`, run with the CI batch
below on the committed code):

1. Before any grant nothing follows: B runs no standby, and B's standby
   token and both agents' tokens are refused at the log and the snapshot.
2. The root refuses to make its own machine the standby, and says why.
3. B's agent started a standby 1.3 s after the grant, and the root's status
   names B, up to date, heard from just now.
4. B's standby token reads the log and the snapshot; B's agent token, A's
   standby token and A's gateway token are refused.
5. A change on the root reached the standby, which reports index 5.
6. Removing the grant refused the next pull with 15 min left on the token,
   and B's agent stopped the standby and deleted its copy (0.6 s).
7. The standby promoted with the passphrase: it signs people in, lists the
   nodes, names B the root with no standby grant, and B's agent kept it
   running.
8. The old root, started again, is fenced: B refuses its bundle.

Real processes from the installed packages: a control root, agent A on the
root's machine and agent B, the machine that becomes the standby. Loopback
ports the OS picks (the standby's too, never 8083), temporary state, and no
`EUGENE_PLEXUS_*` variable from the calling shell. It runs in specs CI after
c3.

### Specs CI failed on `e17c1a6`, and what that found

Specs CI on `e17c1a6` failed at this script, on Ubuntu, at check 7. The
Windows twin passed. Because `edge` is the newest all-green specs commit,
Amish_Station's in-app update stayed at the previous pins (agent
`af6c371`). The NAS container image is built on every push, so it got
`cd8880e`, and Eugene correctly warned that the versions differed.

1. **The acceptance assumed the standby's port.** After the revoke and the
   second grant, Linux still held the first standby's port, so B's agent
   walked to the next one (47065 → 47066), as every component does. The
   script dialled the old port. It now reads the port from B's own report
   (`GET /v1/node` → `standby.url`). Not a product defect.
2. **A rerun on Windows then failed at the same check, for a product
   defect.** The promoted root pushed its bundle to B (200), but B's agent
   could not replace `trust_bundle.json`: `[WinError 5] Access is denied`.
   Windows refuses to replace a file any process has open. The agent kept
   the bundle in memory, logged one warning and never wrote it again, and
   B's pulls went to the root that had stopped. So the file stayed at
   epoch 1, and anything reading it (the components, or the agent after a
   restart) would have trusted the old root. The other reader was not
   identified: either the acceptance's own polling of that file every
   0.25 s, or antivirus.

   **Fixed in agent `bbc6aaf`** (Troy agreed the product fix over making
   the test read the epoch over HTTP). A write refused with
   `PermissionError` is retried after 50 and 150 ms. Any write that still
   fails is held, said with its cause, and written again before every trust
   pull until it lands. Four tests in `test_trust.py` each fail without the
   fix, one of them holding a real open handle on Windows. The acceptance
   still polls the file, so it keeps exercising this.

After both: **8 of 8 on Windows** (`agent/.venv`), and **8 of 8 on Linux**
(WSL Ubuntu, a venv importing the same working trees). The first WSL run
printed all eight PASS lines and its summary, with no traceback, but the
one-line wrapper around it reported exit 1. A second run, with the exit
code captured on its own line, exited 0.

## Sabotage: `scripts/standby-sabotage.py`

29 cases across control (15), agent (10) and ui (4), on the changed code
only. Each file is restored from bytes kept in memory, never from git, and a
baseline of the 20 named checks passes before and after.

- **First pass: 28 of 29.** The escape was *a promoted copy is stopped and
  deleted* (`if role == ROLE_ACTIVE:` → `if False:` in the agent's
  `standby.py`). The next branch (`role != ROLE_STANDBY`) keeps the copy
  too, so the test's only assertions, that nothing was stopped or deleted,
  still held. What the mutant loses is the log line that says the copy was
  promoted and is the root now: instead, it says every minute that the copy
  "did not say it is still one (control)".
- **The fix is a test, not a weaker case.**
  `test_a_promoted_standby_is_never_stopped_or_deleted` now also asserts
  that the agent logs exactly one line, the promotion, over two reconciles.
  It passes on the code and fails on the mutant.
- **Second pass, the run of record: 29 of 29**, baseline and restored
  baseline passing, and the three working trees byte-identical before and
  after.
- **Three cases for the bundle fix, 3 of 3 caught:** *a bundle file held
  open is not waited out*, *a bundle the file refused is forgotten*, *the
  trust pull never writes a held bundle*. That makes 32 cases in the script.

## Suites and checks

- **control:** pytest 449 passed, 2 skipped (POSIX file modes); ruff, ruff
  format, `mypy src/` and `mypy --platform linux src/` clean.
- **agent:** pytest 2040 passed, 18 skipped (platform); the same four checks
  clean. With the bundle fix (`bbc6aaf`): 2044 passed, 18 skipped; ruff,
  format, both mypy runs and `check-vendored.py` clean.
- **ui:** vitest 141 files, 1730 tests; lint clean. `typecheck` and
  `format:check` found two faults in the new files: an unnarrowed
  `NODES[0]` in `StandbyPanel.test.tsx`, and one long line in
  `StandbyPanel.tsx`. Both were fixed; then typecheck, format check and the
  panel's tests (4 of 4) passed. The copy gate (`vocabulary.test.ts`) runs
  inside vitest.
- **gateway, library, inference-driver, tool-driver:** full pytest, ruff,
  ruff format and mypy on both platforms passed with the token module in
  place. Nothing in them changed after that run.
- `r7-signing-checks.py`: the token module is byte-identical in all six
  repos.
- gitleaks 8.30.1 over each repo's committed HEAD: no findings.

## Every CI acceptance script, locally

Every Python script that specs CI runs on Windows passed, each with a
captured exit code of 0. They were run from `agent/.venv` (editable installs of the
committed trees), with `EP_SDK_PYTHON` set to a scratch venv holding
`openai` 3.20.0 and `anthropic` 1.9.0 and every `EUGENE_PLEXUS_*` variable
cleared. No log names a default port.

- **Release inputs:** `s10-checks`, `release-inputs --check`,
  `platform-checks`, `release-artifacts-checks` (seven matching pins),
  `a8-summarize`.
- **Tokens and keys:** `r7-signing-checks` 13/13, `r7-rotation-acceptance`
  8/8, `row3-per-node-keys-acceptance --lan` 27 PASS.
- **The rest:** `run-operations-checks`, `s10-starter-check`, r8, a3, a5,
  a6, a6b, p2 18, p3 27, p4 15, p5 8, p6 9, p8 15, c2 42/0, c3 50/50,
  standby 8/8, `a7-recovery-checks`, `r8-profile-checks` (10 regressions
  caught).
- **The launch boundary:** `test_winservice.py` 7 passed, 2 skipped;
  `r7-launch-boundary-checks --current-python` 15/15; `r6-benchmark-checks`
  6/6.
- **Contracts:** `r38-contract-checks --sabotage` 11/11.

Not run here:

- `job-sites-acceptance.py`, which CI runs on Linux only;
- `windows-service-smoke.py`, which installs a LocalSystem service and needs
  elevation (CI runs it).

Product code didn't change between these runs and the pins. The six
`VENDORED.json` commits came after the batch started.

**Rerun on agent `bbc6aaf`** (the bundle fix), the same way: all 32 passed,
standby 8/8, and every working tree was clean afterwards. The batch also
included `embed-uninstall.py --check` and `test_uninstall.py`, from the
offline-removal job. The retry path didn't fire in that run: neither *could
not keep* nor *kept trust bundle* appears in its log. The unit tests are
what exercise it.

## Deploying

The NAS root goes first (an older root refuses a node report that carries
`hostsControl` or `standby`: `extra=forbid`), then this PC. Old components
read grants as plain strings, so a bundle that carries `standby` breaks
nothing. Making Amish_Station the standby is Troy's call.

Troy updated both on 2026-10-08, while specs CI on `e17c1a6` was red. The
NAS container got agent `cd8880e`; Amish_Station's `edge` stayed at
`af6c371` (above). Once CI is green on this commit, both update to
`bbc6aaf`: the NAS by its container image, Amish_Station from the console.

## Left open

- **After a promotion, only the promoted machine reaches the new root.** The
  copy stays bound to loopback, and no agent learns a new root address
  (design §7). Banked with the step that turns a promoted copy into the
  install's `control` entry, and with promotion from the console.
- The promoted root's `securityMode` is run end to end only for
  `prompt_on_startup`; `os_keyring` and `passphrase_file` use the existing
  startup paths (design §7).
- The standby's directory on an installed Windows worker inherits the agent's
  protected ACL, which was not checked here.
