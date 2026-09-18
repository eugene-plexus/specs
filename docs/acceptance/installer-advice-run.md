# R2.2 — the installer's own advice: the run

**2026-09-18. `scripts/r22-acceptance.sh`, 49 PASS across three gates, zero
failures. `scripts/r22-sabotage.py`, 29 sabotages, 29 caught, 0 escaped** —
**after five escaped on the first pass, and each of those five named a missing
check rather than a missing fix.** Roadmap:
[`../design/release-roadmap.md`](../design/release-roadmap.md) §3.2. Findings
closed: review §6.1 #10, §6.2 #24, §6.2 #30, §6.3 #31, §6.3 #34.

Repos: `specs` (both installers) and `agent` (`reach.py`). **No contract change
and no UI change**; `dist` untouched. §6.2 #26 left this slice on 2026-09-18 and
is R2.6.

**Both installers re-pinned, and this is the slice that had to do it.** The
component pins had been five repos stale since R1.1 — deliberately, because no
slice until now shipped anything a pinned install reads. #34's fix is in the
agent, so it reaches nobody without a bump; and bumping the agent alone would
ship an R2.2 agent beside a pre-R1.1 gateway. All five component pins go to the
current pushed HEADs: `agent` `2ac8486`, `control` `f72921b`, `gateway`
`6d0e62b`, `inference-driver` `e4ac3c1`, `library` `3e125f3`. `ui` stays at
dist `9fccf05` because no UI changed. Every archive was fetched and confirmed
to resolve, and `install-acceptance.sh EP_MODE=posix` re-ran green **from the
bumped pins** — 16 checks, a real install from nothing over the real network.
That is R1.1 through R2.2 reaching an install for the first time.

**`scripts/install-acceptance.sh EP_MODE=posix` re-ran green afterwards — 16
checks, zero failures, a real install from nothing in WSL2 over the real
network.** The stubbed run below cannot prove that step 4's VERIFY still passes
against real packages; that one can, and does.

---

## 0. Three programs, three gates

R2.2 is not one codebase. It is two installers written in two languages plus
one function in the agent, so the run is three gates and the acceptance script
is a dispatcher:

| gate | what it drives | where |
| --- | --- | --- |
| `agent` | `tests/test_reach.py` — #34's decode, as arithmetic | pytest, the agent's 3.14 venv |
| `posix` | `install.sh`, end to end, with four stubs | WSL2 Ubuntu |
| `windows` | `install.ps1`, against a decoy scheduled task | Windows PowerShell 5.1 |

**The POSIX gate stubs `uv`, `curl`, `systemctl` and `loginctl` and nothing
else.** Every branch of `install.sh` is real. The reason is not speed: what has
to be observed is what the script *writes* (a unit file, an `agent.yaml`) and
what it *says when a network step fails*, and both sit past step 3, which is a
real `uv pip install`. A run that cannot make the network fail cannot reach the
paths this slice is about. `install-acceptance.sh` remains the run that
installs for real; this one is its complement, not its replacement.

**The Windows gate drives a COPY whose task and service names are rewritten,
and that is the only edit.** The finding is precisely that the installer
unregisters a task by a fixed name without looking at whose it is — so
reproducing it against the shipped names would have stopped the live worker's
agent on this box. `EugenePlexusR22Probe` is registered as a decoy, and
everything destructive happens to the decoy. Registering a logon task for the
current user needs no Administrator.

**The keyring half is real, not stubbed.** Two entries go into Windows
Credential Manager under a username scoped by a salt no install has, the
uninstall runs, and the entries are read back. A cleanup step removes them
whatever the verdict.

---

## 1. #24 — `sh -c "$(curl ...)"` cannot fail

The uv bootstrap was

```sh
sh -c "$(curl -fsSL https://astral.sh/uv/install.sh)" >/dev/null 2>&1 \
    || die "could not install uv from https://astral.sh/uv/install.sh"
```

When curl exits non-zero the command substitution is empty, `sh -c ""` exits 0,
and the `|| die` that names the URL **never fires**. Reproduced in the run: with
curl failing, the unfixed script died one line later on

```
error: uv did not land at /tmp/.../prefix/bin/uv
```

— a true sentence about the wrong subject, which sends a person to look at a
directory when the problem is their proxy. Fetch to a file, check curl, then run
the file; curl's own diagnosis is relayed under the refusal.

**The other half of #24 is that `uv venv` and `uv pip install` ran under
`>/dev/null 2>&1`.** A TLS-intercepting corporate proxy — the commonest reason
either fails on a machine that is otherwise fine — read as *could not create a
virtualenv*. `run_step` sends every network step to `$PREFIX/logs/install.log`
and prints the last twenty lines only on failure, so a good install is as quiet
as it was. A check asserts that quietness, because a fix that made the package
resolver scroll past would be a different defect.

**And `EUGENE_PLEXUS_AGENT_BIND_PORT` reached nothing the autostart reads.** It
was consulted for the health wait at the end of the script and nowhere else, so
the install that answered on the chosen port during the run came back on 8079 at
the next boot — while the closing line told the person to open the port it would
not be on. It is in the systemd unit and the launchd plist now, and on Windows
in the same environment scope as the config-file variable. **A run that goes
back to the default clears the override**, or the port would be sticky per
account forever.

**The one existing test that touched this could not have caught it:** it passes
`--no-service --no-start`, so it never reaches the code the override was missing
from.

## 2. #30 — `--advertise` outside the join branch

Both installers parsed the flag on any invocation and passed it on only inside
`if [ -n "$JOIN_CONTROL" ]` / `$joinArgs`. On the first machine — one box, no
control root to join, an operator who already knows the address their phone will
use — it was accepted and discarded.

It now writes `advertiseUrl` into `agent.yaml` **before the agent is started**,
which is the *before the first start* `tailnet.md` calls the single most
important thing on its page. The agent derives its own bind host from that
field, so writing it is the whole fix; the systemd unit gets
`EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0` beside it for the same reason a join
does.

**Written as plain YAML rather than through the install's Python**, because on a
fresh install `agent.yaml` does not exist yet and the file is a flat mapping of
config keys, so replacing one top-level line is exact. A check asserts that a
re-run keeps everything else in the file — an installer that clobbers an
existing install's state would be the same class of defect as #10. On Windows it
is written **without a BOM**: `yaml.safe_load` does not survive one, and this
repo has been bitten by `Set-Content -Encoding utf8` before.

`tailnet.md` §1 is corrected in place.

## 3. #10 — a second install, built by following our own advice

`install.ps1` told an unelevated user to re-run from an elevated PowerShell to
get a service. Doing exactly that switched the prefix from `%LOCALAPPDATA%` to
`%ProgramData%`, unregistered the first install's task **by name and without a
word**, repointed the config-file variable, and started a service with no
`agent.yaml` — the wizard again, a second trust root, and the first install's
passphrase, models folder, keyring entry and enrolled workers stranded.

**The discriminator was already written, one repo over, for the same question.**
`reach.py` decides whether a task is *this* install's by comparing the task's
program path against `sys.prefix`; the installer compares it against the
virtualenv it is about to write. Two guards, not one:

- `Assert-OwnInstall` runs before the first byte is written and before step 3
  stops a running agent, and refuses with the three ways forward (`-Prefix` the
  other one, `-Migrate`, or uninstall the old one first).
- `Remove-Autostart` refuses to unregister an autostart that is not this
  install's, whatever asked it to.

**The second guard existed and was gated by nothing** — see §6.

`-Detect` prints the verdict and changes nothing, which is how an operator
answers *is this machine already somebody's install?* without running one.

**And an elevated install no longer inherits the SYSTEM profile.**
`EUGENE_PLEXUS_AGENT_ENGINE_ROOT` and
`EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS` are pinned under the prefix, so a
LocalSystem service does not put engine builds in
`C:\Windows\System32\config\systemprofile` and the wizard's Models screen — which
proposes `<home>\Eugene Models` from the library's own `Home` entry — does not
offer a folder inside the Windows directory. **The variable's effect is
exercised live** rather than asserted from the script: the library really does
take its default roots from it.

**Not covered, and said rather than implied: the elevated branch itself.**
Registering a service needs Administrator, which no session here has. What is
checked is the statement that sets each variable, plus the mechanism it relies
on. R2.6 is where a real service gets run.

## 4. #31 — two keyring entries, and a directory full of models

The agent stores its master key under `eugene-plexus-agent`; the control root
stores the install's signing key under `eugene-plexus-control`. Both are scoped
by a fingerprint of the install's master salt (S0). The uninstall took neither —
**and the salt goes into the `.removed-` directory with everything else, so
after the uninstall runs nothing can work out what to delete.** It happens there
or not at all. The install's own interpreter does it, because that is what holds
`keyring`; a missing library or a locked backend is a warning, never a failure,
since an uninstall that refuses to finish is worse than one that leaves a
credential.

**Two directories live outside the prefix and both are ours.** The engine store
— `~/.eugene-plexus/engines`, or wherever `EUGENE_PLEXUS_AGENT_ENGINE_ROOT` says
— holds the llama.cpp builds the agent downloaded, two per engine, and nothing
else on the machine writes there. The review's own row for #31 says *engines,
two keyring entries, copies*; this slice covers all three. The switch is
`--purge-downloads` / `-PurgeDownloads` because it now covers more than copies
(`--purge-model-copies` still works).

**The node-local model copy directory is named with its size, not deleted.** It
is ours by design — the agent creates it, fills it and deletes from it, and a
Library folder is never written to — but tens of gigabytes is not a thing to
remove on somebody's behalf. `--purge-downloads` / `-PurgeDownloads` is the
explicit answer, and a check proves both halves for both directories.

**A hazard the engine-store half introduced, and closed.** The Windows check
runs `-PurgeDownloads` for real, and the default engine store on this box is the
live worker's. The check points `EUGENE_PLEXUS_AGENT_ENGINE_ROOT` at a throwaway
before anything runs, so the directory it deletes is one it made — the same
discipline as the environment-variable snapshot, for the same reason.

**One correction the fix produced: the uninstall must not clear another
install's environment variables.** Removing a named prefix is legitimate on a
machine whose autostart belongs to a different install — it is, in fact, how an
operator recovers from #10 — so the Windows uninstall now clears only the
variables that pointed at *this* prefix. `EUGENE_PLEXUS_AGENT_BIND_HOST` is the
exception and is cleared regardless: the installer stopped setting it on
2026-09-11, every install made before then did, and an account-wide widened bind
outliving the install that set it is what made it a defect.

## 5. #34 — `schtasks` is not UTF-8

`_windows_task_runs_this_install` ran `schtasks` with `encoding="utf-8"`. A
console program on Windows writes its stdout in the **OEM code page** — measured
on this box: **cp437**. A person whose Windows account name carries an accent has
`%LOCALAPPDATA%` under it, so the installer's per-user prefix carries it too, the
task's program path no longer matched `sys.prefix`, and the Reach card said
*nothing starts this agent automatically* — affirmatively, wrongly, and while
withholding the one action it exists to offer.

Two readers now, in order. `Schedule.Service` through COM first, because the Task
Scheduler hands back a `str` Windows decoded itself from UTF-16 and a code page
cannot touch it — the same instrument, for the same reason, as
`firewall/windows.py`. `schtasks` decoded in the OEM code page second, for an
install with no `pywin32`.

**`task_runs_from_prefix` had to change shape**, because the COM reader hands it
a bare path and `C:\...` has a colon in it: the label-stripping that made sense
for `Task To Run:   <exe>` would have eaten the drive letter. Each line is tried
whole first, then after the label.

**The live half is in the run**: a real scheduled task whose program lives under
a real accented directory, read by the agent's own detector, on a box whose
console writes cp437.

---

## 6. The sabotage pass, and the five that escaped

29 sabotages, **29 caught — after a first pass in which five escaped.** Every one
of the five was a missing check, not a missing fix, and that is the value of the
pass:

1. **`schtasks` decoded as UTF-8 again — THE finding — escaped.** One test
   encoded the bytes itself and never called the reader; another patched the
   reader out; the caller test used an ASCII path, where cp437 and UTF-8 agree.
   **The one line the finding is about was ungated.** Now
   `test_the_schtasks_reader_decodes_what_the_console_wrote` drives
   `_task_query_via_schtasks` with OEM-encoded bytes carrying an accent.
2. **Removing `Remove-Autostart`'s ownership guard — THE finding — escaped**,
   because on the install path `Assert-OwnInstall` refuses first. The guard is
   the *only* protection on the uninstall path, where refusing outright would be
   wrong. New check: `-Uninstall` aimed at a stray prefix while a foreign
   autostart is registered must leave that autostart alone.
3. **Dropping the elevated `ENGINE_ROOT` assignment escaped**, because the check
   matched the variable *name* — which the uninstall also mentions when it
   clears it. It matches the statement that sets it to a Machine-scope value
   now. **A name is not a behaviour.**
4. **"The uninstall does not name the copy directory" escaped** because the
   sabotage removed one of the two lines that print the path. That one was a
   sabotage that did not sabotage; it was made precise rather than the check
   loosened.
5. **Loosening the prefix comparison to a bare `StartsWith` escaped**, exactly
   as it did in S5's reach detector — the only negative case was a decoy in a
   different directory. New check: a task running from `venv2` beside `venv`
   must read as a different install.

**A note about the pass itself.** The Windows checks write account-wide
environment variables, and this box is a worker node — so a probe run that ends
normally repoints `EUGENE_PLEXUS_AGENT_CONFIG_FILE` at a throwaway prefix and
the live install's identity is gone. That happened once, during development, and
was caught by looking. The checks snapshot and restore every variable the
installer touches; it is
`acceptance-scripts-must-clear-the-environment` one scope over, and the scope
that script does not cover.

---

## 7. What this run does not cover

- **The elevated service branch of `install.ps1`.** No Administrator here.
- **A real network failure.** The POSIX gate stubs it; only a machine behind a
  TLS-intercepting proxy produces the real thing.
- **macOS.** `install.sh`'s launchd branch is written and unrun, as it has been
  since step 3.
- **A real second install being migrated.** `-Migrate` is checked as a verdict,
  not by building one install and moving it.
- **An OEM code page that cannot represent the path at all** — a Cyrillic
  account name on an English machine. The COM reader handles it; the `schtasks`
  fallback cannot, and says so in its docstring.
