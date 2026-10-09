# J14b + 2b.4: signed calls and commands — run record

**Date:** 2026-10-08. **Design:**
[`person-held-keys.md`](../design/person-held-keys.md) §13 (J81-J91, *What
building found*). Built while Troy was away, from
`docs/private/handoff-2b4-commands.md`; J29, J30, J47 and J9 taken before,
J81-J84 taken by Troy at the start (2026-10-08), J85-J91 taken by building
for him to confirm.

For a person with a key, a job site now checks their calls, not only their
changes: a tool whose rule is `ask`, and every command, runs only with their
own signature over that call; a tool whose rule is `allow` runs only inside
a 60-minute window they opened with their key. A call without one is held,
listed on the machine's page, and runs when Workbench sends it again once it
is signed there (a click) or with a passkey. Commands (`run_command`,
`command_output`, `command_stop`) run as the person, in their own workspaces
whose rules ask about them, only where an administrator consented at the
machine.

| Repo | Commit | What |
|---|---|---|
| site-host | `db20f3e` | signed calls and windows (`calls.py`), commands (`commands.py`), consent (`consent.py`), the command rule, audit lines |
| control | `2b2ae24` | carries `approval`, relays `held` and `windowUntil`; `window/close`, `commands/withdraw`; leaves an absent rule out |
| workbench | `31abd61`, dist `1924540` | waits for the signature (passkey here, or the machine's page) and sends the call again; the command rule; window and consent on Job sites |
| agent | `16edbac` | `site consent`, the join's question, the tray's *Allow commands*; the page lists calls and windows; pins site host `db20f3e` and Workbench dist `1924540` |
| specs | this push | contract `f16d72a`; `job-sites-acceptance.py` (C1-C6, B4 and B6 rewritten), `job-sites-windows-acceptance.py` (signs at the machine; not run), `j14b-sabotage.py` (new); both installers (`--site-commands`, `-SiteCommands`), `release/manifest.json` |

## What was run

**`scripts/job-sites-acceptance.py --root-wsl` — 41 passed, 4 skipped** (the
one-account skips: a second OS account needs CI's sudo run), 2026-10-08, the
run of record, against the working trees (root in WSL2, site host and
workers on Windows, interpreter the agent's venv). The new checks:

| Check | What passed |
|---|---|
| C1 | with her window closed, ada's read is held for a 60-minute window, runs once she signs it at the machine and Workbench sends it again, and inside the window reads run unsigned; the audit line names the window her key opened; the root's listing shows when it ends |
| C2 | without the administrator's consent in the protected list, `run_command` is not offered and a call is refused saying so; with it, it is offered in ada's own workspace whose rules ask, named for its shell (Windows PowerShell 5.1), with no restart |
| C3 | a command the root forges in ada's name is held, never run; naming the held call unsigned leaves it held; a forged signature is refused; the audit log records the held call with its command and the refusal with its reason |
| C4 | held until ada signs it at the machine, the command runs, answers its output and exit code (0, then 3), and its audit line names the key that signed it and how it ended |
| C5 | a command still running after 15 s answers what it printed and a handle; `command_output` reads on, `command_stop` ends it |
| C6 | the owner turns commands off from Workbench's route; an administrator's later consent counts again |

**In CI, at the pins** (specs `624c768`, [run 37884207292](https://github.com/eugene-plexus/specs/actions/runs/37884207292)):
the same script on Linux with passwordless sudo, so the site host, ada's and
jo's workers each run as their own throwaway account: **42 passed**, C1-C6
included, the commands running as ada's account. Every component's CI, A4
macOS and the container image passed at the same pins.

B4 and B6 were rewritten for J14b (with a key, Workbench's word is not an
approval: the write is held until signed), and J14a.2's per-user check now
signs ada's window **through the agent's own approve page** (`PageClient`),
the Path A route a person uses (J83).

**Unit and suite runs**, Windows unless said:

- site-host: 337 passed (18 new in `test_signed_calls.py`, 13 in
  `test_commands.py`); Linux (WSL2, Python 3.12): 330 passed, 7 skipped;
- control: 455 passed (6 new in `test_site_calls.py`);
- Workbench: the page, 206 passed (9 new);
- agent: 2048 passed, 19 skipped, 1 failed (5 new in `test_site_consent.py`);
  the failure, `test_first_boot_declares_control_gateway_and_library`, is this
  machine's warm-standby control holding 8083, which the test assumes free
  (unrelated to the change; fixed separately);
- Workbench: 243 passed with the 4 new;
- static checks (ruff, ruff format, mypy and `mypy --platform linux`) pass in
  all four; gitleaks finds nothing in any of the five repos;
- `r37-install-sh-checks.sh` (WSL2): 141 checks, 0 failures; `install.ps1`
  parses and stays ASCII; install.sh's consent writer, extracted and run on a
  scratch list, keeps the servers and the file's mode.

**Sabotage** (`scripts/j14b-sabotage.py`, 36 entries over six gates, each
gate's baseline and restored runs passing): **36 of 36 caught**. The first
pass caught 35; the escape was *stopping a command signals only its shell*
(Linux), which the group kill after any exit makes redundant, so stopping
still ended the tree. It was replaced by an entry that breaks the group kill
both rest on, which is caught.

## What building found

See the design's §13.5. In short: the root sent `"command": null`, which an
older site refuses (fixed, both in control and Workbench); a command's exit
was awaited through `Process.wait()`, which on Linux waits for every pipe to
close, so a background child kept the command "running" (fixed: the exit
code is watched); PowerShell's `-EncodedCommand` writes errors as CLIXML
(fixed: a script block from base64).

## Deploying

**The root first** (the NAS container), then the nodes: a site's report now
carries each workspace's `command` rule, `commands` and each link's
`windowUntil`, which a root older than this refuses. Then Amish_Station.
Commands stay off on a machine until an administrator allows them there:
*Allow commands from Workbench...* in the tray (Windows), or the install
command again with `--site-commands` (Linux).

## Owed

- **The remote passkey path (J47) on Troy's own Workbench**
  (`https://workbench.screamingamish.com/`): a passkey on his phone (synced
  passkeys are accepted, J64), paired with a code from Amish_Station, signing
  a command from away from the machine.
- **`job-sites-windows-acceptance.py --person-account jessie`**, elevated: it
  is updated for J14b (each person's calls are signed in their own Chrome on
  the machine's page) and has not been run.
- **The tray's *Allow commands from Workbench…*** behind a real UAC prompt,
  and **the join's question** at a console: both need a person at the
  machine.
- **A Linux system install's `--site-commands`** on a real machine (WSL's
  sudo needs a password here; the extracted writer was run on a scratch list).
