# Row 8: Installer pass: a Mac service in its own account, and `--label`

Lane OPS. Risk: high (installers, an account, a migration). Size: L (was M; MAC-ACCT Choice 2). Sources: R2.6-mac, PLAT-START, NL-INST. Calls: MAC-ACCT (Choice 2), MAC-KEY (Choice 1), both answered 2026-10-21.

**Revised 2026-10-21 for MAC-ACCT Choice 2.** Eugene runs on a Mac as the Linux system install runs: in an account of its own, so a program the person runs cannot read Eugene's keys, environment or memory.

## 1. What the row delivers

- A new Mac install runs Eugene as a LaunchDaemon in its own hidden account, `_eugeneplexus`. It starts at boot, before anyone signs in. The installer asks for sudo once.
- An existing Mac install (a LaunchAgent in the person's account) moves to the daemon on its next installer run. Node identity, settings, port and Library state move with it. After the move it asks for the passphrase once.
- The wizard's "Eugene itself starts when this machine does, before anyone signs in." becomes true on a Mac. `--user` keeps today's LaunchAgent, with no sudo.
- `install.sh --label "Studio Mac"` and `install.ps1 -Label "Studio PC"` set the machine's label when it joins. The console's "Add a machine" form gets "Shown as", which adds the flag to the printed command.

## 2. The design

### The Mac layout (`install.sh`)

Mirror the Linux system layout (`MODE=system`, `install.sh` "which layout"), with the Mac's tools:

- **Mode.** macOS with a service and without `--user` is `MODE=system`. Remove macOS from the `MODE=user` condition.
- **Prefix:** `/usr/local/eugene-plexus` (no space, allowed under SIP, 0750 `_eugeneplexus:_eugeneplexus`). Not `/Library/Application Support`: a space in the venv path breaks script shebangs.
- **The account.** If absent, create group and user with `dscl`: name `_eugeneplexus`, a free id below 500 (scan `dscl . -list /Users UniqueID` and `/Groups PrimaryGroupID` from 400 down), `UserShell /usr/bin/false`, `NFSHomeDirectory` the prefix, `IsHidden 1`, no password. Record `ACCOUNT_CREATED=1` for removal, as Linux does.
- **Models.** The account joins the person's primary group (`staff` on a Mac) with `dseditgroup -o edit -a _eugeneplexus -t user staff`. `prepare_models_dir` makes `~/Eugene Models` 2775, as on Linux. A Mac home is 0750 `person:staff`, so the group can pass. Folders the person keeps in `~/Documents`, `~/Desktop` or `~/Downloads` are 0700 and covered by macOS privacy rules, so Eugene's account cannot read them. The Library must name that cause (see risks).
- **The engine store and the model copy directory** live under the prefix (`EUGENE_PLEXUS_AGENT_ENGINE_ROOT=$PREFIX/engines`), never in the person's home.
- **The plist:** `/Library/LaunchDaemons/com.eugeneplexus.agent.plist`, `root:wheel`, 0644, written by the install's Python with `plistlib` (today's heredoc plist is invalid XML for a path holding `&` or `<`; the LaunchAgent writer changes too). Keys: `UserName` and `GroupName` `_eugeneplexus`, `ProgramArguments` (`$VENV/bin/eugene-plexus-agent --unattended`), `WorkingDirectory`, `RunAtLoad`, `KeepAlive` true, `ThrottleInterval` 10, the logs under the prefix, and `EnvironmentVariables`: `HOME` (the prefix), `USER`, the config file, the engine root, `EUGENE_PLEXUS_AGENT_PASSPHRASE_FILE` and `EUGENE_PLEXUS_CONTROL_PASSPHRASE_FILE` (`$PREFIX/passphrase`), and the port and bind variables.
- **Never root.** The installer refuses to write a plist whose `UserName` is empty or `root`.
- **Start and stop:** `sudo launchctl bootstrap system <plist>`; `sudo launchctl bootout system/com.eugeneplexus.agent`.
- **Unlock (MAC-KEY Choice 1).** The Keychain stays locked until someone signs in. A daemon install writes `securityMode: passphrase_file`, as the Linux system install does. The file is 0400 `_eugeneplexus`. Only Eugene's account (and root) can read it.
- **Firewall.** A daemon cannot show macOS's "Allow incoming connections" prompt. When the install binds wide, the installer allows the venv's Python with `socketfilterfw` and records it in the receipt's `firewall.txt`, which removal already reads.
- **`as_service`** runs a step as `_eugeneplexus` with `sudo -u _eugeneplexus env ...`, handing over the same variables as on Linux.

### Migration: a plain re-run over a LaunchAgent

1. Continue only when the LaunchAgent's `ProgramArguments[0]` is inside the old prefix (`~/.local/share/eugene-plexus`); otherwise stop and name the other install.
2. Say it first: "Eugene will start when this Mac starts, before anyone signs in, in an account of its own. This needs your password once. After the move, sign in to Eugene once; from then on it unlocks by itself."
3. Keep the port and bind-host variables from the old plist.
4. Stop the LaunchAgent (`launchctl bootout gui/<uid>/...`); wait up to 15 s for every process whose argv[0] is in the old prefix.
5. **Copy, then switch.** Copy the old prefix's state (`node.yaml`, `agent.yaml`, `control.yaml`, control's log and snapshots, the Library state, profiles, logs) to the new prefix with `ditto`, `chown -R _eugeneplexus:_eugeneplexus`. Rewrite paths in `agent.yaml` that point into the old prefix. Build the new venv in the new prefix (a venv cannot move). Move the engine store from `~/.eugene-plexus/engines` to `$PREFIX/engines`.
6. Write the daemon plist under a temporary name, check it with `plutil -lint`, rename it, and `launchctl bootstrap system <plist>`.
7. Wait for `/healthz`. On failure: boot the daemon out, bootstrap the LaunchAgent again (the old prefix is untouched), and stop with launchctl's or the agent's words.
8. On success: `os_keyring` in `agent.yaml` and `control.yaml` becomes `passphrase_file`; the first sign-in writes the file. Delete the old plist. Move the old prefix aside to `~/.local/share/eugene-plexus.moved-<date>` and say so; it is not deleted. Old Keychain entries stay until uninstall drops them.

`--update` never migrates. `--user` beside the daemon is refused: "This Mac already starts Eugene at boot. Re-run without --user to update it."

### Agent (`reach.py`)

- `_launchd_restart` reads the daemon plist first. It is this install's when `ProgramArguments[0]` is inside `sys.prefix` and the parent is pid 1. Then: `mechanism: launchd`, `detail` "This agent starts at boot, before anyone signs in.", and `canSelfRestart: true`. The account cannot kickstart a system job, so `restart_argv` is `/bin/sh -c "sleep 1; kill -TERM <own pid>"` and `KeepAlive` brings the agent back. `command`: `sudo launchctl kickstart -k system/com.eugeneplexus.agent`.
- The LaunchAgent branch gets `detail` "This agent starts when you sign in to this Mac."
- No contract change: `Mechanism.launchd` covers both.

### Removal (`scripts/uninstall.sh`, embedded by `embed-uninstall.py`)

Remove the daemon only when its program is in the prefix: `sudo` from a terminal, `osascript ... with administrator privileges` from the Mac removal app. Remove the account and its group only when the receipt says the installer created them (`dscl . -delete`). Failure: "macOS refused to stop Eugene's startup job: <launchctl's words>. Nothing was removed."

### `--label` (NL-INST)

- Both installers pass `--label TEXT` to the agent's `join`. A job site's `site join --label` uses it before `--name` and the host name.
- Without `--join`, refused: "--label names this machine when it joins an install. The first machine's name is asked on its setup page."
- `install.ps1` refuses a label holding `"` (PowerShell 5.1 passes it to a native program wrongly) and stays ASCII. The agent and control check the rest.
- ui `joinCommand.ts` adds `-Label`/`--label`, quoted like the other values; `app/nodes/page.tsx` adds "Shown as (optional)".

## 3. Repositories and files

- **specs:** `install.sh`, `install.ps1`, `uninstall.sh`, `uninstall_inventory.py`, the two `r22-install-*-checks`, new `row8-macos-daemon-acceptance.py`, `a4-macos-acceptance.py` (launchd checks move to the system domain), `a4-macos.yml`; docs `support-matrix.md`, `tailnet.md`, `windows-comes-back-by-itself.md` §8, `node-labels.md` §8.
- **agent:** `reach.py`. **ui:** `joinCommand.ts`, `app/nodes/page.tsx` (add ui to the row).
- No contract change, no codegen.

## 4. Tests that fail before the change

- agent `test_reach.py::test_a_launch_daemon_of_this_install_starts_at_boot` (plist fixture, parent pid 1). Today: "Nothing starts this agent automatically". Also `test_a_launch_daemon_of_another_install_is_not_ours` and `test_daemon_restart_signals_only_itself`.
- `r22-install-sh-checks.sh`: `--label 'Studio PC'` reaches the stub agent as one argument; `--label` alone is refused. Today: "unknown option". On a Mac stub: the layout is `system`, and a plist with `UserName` root is refused.
- `r22-install-ps1-checks.ps1`: `-Label` reaches `$joinArgs`; a `"` is refused; every byte is below 0x80.
- ui `joinCommand.test.ts`.

## 5. Acceptance

**`scripts/row8-macos-daemon-acceptance.py`**, CI on macos-14, 15 and 26, as the runner with passwordless sudo. Agent on 18279; idle listeners hold 8079-8083 for the run; `EUGENE_PLEXUS_*` cleared.
1. The account `_eugeneplexus` exists, is hidden, has no login shell, and is in `staff`.
2. The daemon plist is `root:wheel` 0644, lints, and names `_eugeneplexus`. No LaunchAgent.
3. launchd runs it; the agent's uid is `_eugeneplexus`'s (never 0, never the runner's); its parent is pid 1.
4. The runner cannot read `node.yaml`, `agent.yaml` or the passphrase file (`cat` fails with a permission error).
5. Health answers; nothing of the run listens on 8079-8083.
6. Onboarding: agent and control use `passphrase_file`; the file is 0400 and `_eugeneplexus`'s.
7. Reach says launchd, "starts at boot", can restart.
8. `security lock-keychain`, then `sudo launchctl kickstart -k`: the root comes back unlocked with nobody signing in.
9. Reach's restart gives a new pid under launchd within 30 s.
10. In the daemon, the agent reports Metal, and a tiny GGUF in `~/Eugene Models` answers through the gateway. A download lands in `~/Eugene Models`.
11. Migration from a `--user` install onboarded with `os_keyring` and enrolled: words first; node name, key and port unchanged; profiles kept; the old prefix moved aside; sealed until one sign-in; then a kickstart unlocks by itself.
12. A `launchctl` stand-in fails `bootstrap system`: the LaunchAgent serves again from the old prefix, and the message holds launchctl's words.
13. `--user` beside the daemon is refused.
14. Uninstall: plist gone, job unknown to launchd, no process left, account and group removed, config kept.

Linux and Windows run the `--label` stub checks. **Not in CI:** a reboot and sign-in on a real Mac, bare-metal Metal, macOS privacy prompts (runner images may pre-grant them).

**The reviewer should attack:** a plist with no `UserName`, root, or another person; an account id that collides; the account getting a login shell or a password; XML or path injection, or a symlink at the plist path or in the prefix during `chown -R`; a migration leaving two agents or none, or losing identity, profiles or port; removal of another install's daemon or of an account the installer did not create; the restart signal reaching another process; the passphrase file's mode; `-Label` quoting on PowerShell 5.1, and `'`, `$` and spaces in sh.

## 6. Do not change

- `install.sh`'s Linux system path, root update helper and job-site sections: share helpers with the Mac path, but do not change Linux behaviour.
- agent `install_info.py`, `update_apply.py`; `apps.py`, `client_doors.py` (AG2); `node_identity.py`, `machine_port.py` (TRUST 3, 46); `entrypoint.py` (TRUST 45).
- ui `settingsTopics.ts`, `ResourceTree.tsx` (WEB 33), `ConfigField.tsx` (WEB 62), the setup wizard.
- `release.py`, `release_gate.py`, `release-inputs.py` (OPS 6); every `scripts/codegen.py`.

## 7. Size, risks, calls

**Size:** L, about 3 days. One branch, `r8-installer`: **8a (S)** `--label` and the form; **8b (L)** the account, the daemon, migration, Reach, removal, acceptance. One adversarial review after 8b (Codex `gpt-6.1-sol`).

**Risks:**
- Metal in a daemon under a non-console account is unproven. Check 10 decides; if it fails, the row stops for Troy.
- Folders in `~/Documents`, `~/Desktop` and `~/Downloads` are unreadable to Eugene's account. If the Library does not name that cause, file a library issue with: "macOS keeps Eugene's account out of this folder. Keep models in ~/Eugene Models, or in a folder outside Documents, Desktop and Downloads."
- Network shares mount at sign-in, so a model on one is missing at boot.
- A Job Site on the same Mac runs as the person; unchanged by this row.

**Found while drafting:**
- The wizard's sentence is fixed text, false on `--user` and `-NoService`. File a ui issue: print `restart.detail`.
- `reach._systemd_restart` uses `systemctl --user` whenever the process is not root, as a Linux system install (`User=eugene-plexus`) never is. Check it, and file an agent issue if Reach's restart fails there.

## Calls answered by Troy (2026-10-21)

- **MAC-ACCT: Choice 2.** Eugene runs on a Mac in an account of its own, as on Linux. This design is revised for it.
- **MAC-KEY: Choice 1.** The passphrase is kept in a file that only Eugene's own account can read.
- **R8-JOBSITE-MAC: Choice 1** (answered 2026-10-22, after the build). `--job-site` on a Mac with the daemon is refused and says why: a job site there would need root to run each person's worker, which is built for Linux only. A `--user` install keeps Job Sites, as before. This is what the branch builds (see "What building found").
- 2026-10-22, R8-ENGINES-COPY: Choice 2. Every copied engine build is fetched again after the move.
- 2026-10-23, R8-EXEC-TRUST: Choice 3. A program that one other account can change runs once an owner approves it, and the approval lapses when the program changes. Built in row 8 as part 8c (below), so row 8 never ships a refusal without the way to approve.

## What building found (2026-10-21)

Branch `r8-installer-pass` in specs, agent and ui.

**Defaults built for questions the design left open** (none deletes a person's data or keeps chats somewhere new):

- **The plist is written by `install.sh`, not by the install's Python.** The design said `plistlib` in the install's Python. That Python is in a folder `_eugeneplexus` can write, and root installs the plist it would print: the account could hand itself root through `GroupName` or `Program`. `install.sh` writes the XML itself, escaping `&`, `<` and `>` (the old heredoc's defect), lints it with `plutil -lint`, reads `UserName` and `GroupName` back, and checks the account: below 500, never uid or gid 0, not in `admin` or `wheel`. The LaunchAgent (`--user`) uses the same writer.
- **Removal for the daemon is root's own copy of `uninstall.sh`, outside the prefix** (`/usr/local/lib/eugene-plexus/remove.sh`, root:wheel 0755), with the receipts beside it: `account.txt` (made by this installer, with its numbers), `firewall.txt` and `mac-app.txt`. Nothing from the prefix runs as root. The Finder app "Remove Eugene Plexus" runs that copy; it asks once in a dialog, then for an administrator's password (`osascript ... with administrator privileges`). From a terminal, `install.sh --uninstall` runs the current copy as root. A prefix that `_eugeneplexus` owns is treated as the daemon's even with its plist gone, and the per-user removal refuses to run as root on a Mac (it would run the person's Python as root). Removal keeps the files as root's (`.removed-<time>`, 0700), drops the person's old Keychain entries with `security` as the person, removes the firewall entry, and deletes the account and group only when `account.txt` says this installer made them and the numbers match. `--purge-downloads` removes the kept engines; `--purge-data` removes the kept folder but a `models` folder.
- **The move's `securityMode` change happens on the copy, before the daemon starts** (the design put it after success). The running agent reads the mode at start; changed afterwards, the first sign-in would not write the passphrase file. The old folder is still never written.
- **The control root's `securityMode` is not in `control.yaml`.** The root keeps it in its applied state (the replicated log); `control.yaml` is a write-through cache read only at startup for the log level and state folder. So the installer cannot move the root off `os_keyring`, and after the move every boot would leave the root sealed. Built (agent, `routes/auth.py`): at a sign-in, an agent that unlocks from its passphrase file sets the root it runs on this machine from `os_keyring` to `passphrase_file`, with the session the root just issued -- what the wizard does on a fresh install. Only the active root this agent runs (never a worker's), only from `os_keyring`, only when this account has no keyring, and it never fails a sign-in. This is the "sign in once" the move asks for. The installer still rewrites `control.yaml`, so the cache agrees.
- **The engine store is copied, and the old one deleted only after the daemon answers**, so a move that is put back finds it where it was. These are downloaded builds, not a person's data.
- **A move needs the LaunchAgent and a start.** `--no-start` is refused before anything changes (without a start the move cannot be checked, and could end with two startup jobs). A per-user folder with no LaunchAgent is refused with the steps (re-run with `--user` once, then again without).
- **What is installed decides `--update`, `--uninstall` and `--job-site` on a Mac**, as `--uninstall` already did on Linux: with the person's LaunchAgent and no daemon they act on the LaunchAgent install. `--update` never moves an install.
- **A job site beside the daemon is refused**: "a job site ... is built for Linux system installs. On a Mac a job site joins beside a per-user install (--user)". Before row 8 a Mac job site joined beside the LaunchAgent as the person; that still works with `--user`. Building it for the daemon needs the Linux root-run site host on macOS (launchd units, `dscl`), which is a row of its own. Troy confirmed this as R8-JOBSITE-MAC Choice 1 (2026-10-22).
- **`install.ps1` also refuses a label ending in a backslash**, the second argument PowerShell 5.1 passes to a native program wrongly; the console's "Shown as" says both before the command is copied.
- **Account numbers** are taken from 400 down to 200, free as both a user and a group id; the group gets the same number when it can.

**Found while building:**

- **Not `staff`: a models group of its own** (the orchestrator's call after review, least privilege; this replaces the design's "Models" paragraph). `staff` is every person's group on a Mac, so the account in `staff` could read every person's group-readable files. Built: the group `_eugeneplexusmodels` (a free number, recorded like the account) holds `_eugeneplexus` and the installing person; `~/Eugene Models` is the person's and that group's, 2770; and the person's home gets one ACL entry, `group:_eugeneplexusmodels allow search`, so the group can pass through and list nothing. The group and mode are set with `-h`, never through a link, and a `~/Eugene Models` that is a link is refused. Removal takes the ACL entry out and deletes the group when the installer made it.
- **MLX's recipe does not run in the person's shell under the daemon** (agent#30): it names the install's own uv, inside the 0750 prefix, and its `~` is the person's home while the daemon's is its prefix. Run as Eugene's account (`sudo -u _eugeneplexus sh -c 'cd / && <recipe>'`) it works as written, the environment lands under the prefix as the engine store does, and `mlxBinary: ~/eugene-mlx/...` resolves for the daemon. A4 now runs it that way; the notes need to say so, and a GUI path would remove the terminal step.
- **The Library says "permission denied" for a folder in Documents, Desktop or Downloads** without naming macOS's rule (library#17).
- **Files the daemon downloads into `~/Eugene Models` are its account's**; after removal deletes the account they keep its number, as on Linux.
- **`r22-install-sh-checks.sh` checks 8-9 fail on main** (they predate the offline removal) and the script is not in CI (specs#105). Row 8's checks are in a new `row8-install-sh-checks.sh`, which CI's POSIX installer job runs: `--label`, and the Mac layout on stand-ins for `dscl`, `launchctl`, `plutil` (Python's `plistlib`), `sudo` and the rest, including the move and its rollback. The `-Label` checks are in `install-preflight.Tests.ps1`, which CI runs, through a real native program built by `Add-Type`.
- ui#23 (the wizard's sentence on `--user`/`-NoService`) and agent#25 (`systemctl --user` on a Linux system install) were already filed.
- **Metal works in the daemon** (the design's open risk). On GitHub's macOS 14 runner the daemon, as `_eugeneplexus`, reported the Metal device, ran `mlx_lm.server` and a llama.cpp build on it, and answered through the gateway (A4, all its Metal and engine checks).
- **The second-model review (Codex) found three blockers and five more, all fixed** (2026-10-21), each with a check that fails without it:
  - *Root no longer goes under the prefix.* Root's `install -d` made `bin` and `logs` too, and it follows a link: the account could point `logs` at root's receipts folder and be handed it. Root now makes the prefix alone (its parent is root's, so it cannot be swapped); the account makes its own folders; a link where one belongs is refused. The same holds for the engines a Linux join carries over, and removal reads `agent.yaml` as root only when it is not a link. Removal also closes the kept folder at its top (root:wheel 0700) instead of chowning through it, where a hard link could hand another person's file to root.
  - *The move never reads with root's access.* It used root's `ditto`, which follows a link given as an argument, then chowned the copy to the account. Now the person's `tar` reads the old folder (links stay links) and the account's `tar` writes it (re-review B below: through a pipe).
  - *The old folder is kept as root's.* Its `node.yaml` holds the machine's private keys in clear; left in the person's home, a program running as the person could sign as the machine. It is kept beside the new prefix, readable by administrators only, and the installer says it holds the machine's keys (re-review A below: inside a folder root makes).
  - *A move commits only on the daemon's answer:* the process on the port must be the pid launchd gives for the system job, running this install's program (re-review C below: every listener, the exact program, sampled on both sides of the health answer).
  - *A rollback that cannot stop the daemon stops there*, with launchctl's words: it does not start the LaunchAgent beside it or take the copy apart.
  - *The root's move at sign-in* (agent) requires a control entry on loopback, counts a keyring probe that ran out of time as "might work" (never as absent), logs a config the root will not show, and logs a `securityMode` the root rejects in a 200 answer with the root's words.
  - *The acceptance* fails 11d and 11e when the Keychain move was not exercised, and reads the root's mode after the sign-in.
- **The re-review (Codex, 2026-10-22) found two blockers and three more in those fixes, all fixed**, each with a stub check that fails without it (`row8-install-sh-checks.sh` M8b-d, M10-M17, U1) and, where a stand-in cannot show it, an acceptance check on the macOS runners (11c, 11f, 14b):
  - *A. The kept old folder.* An ACL entry the person put on the old folder (one that lets them search it) survived the chown and `chmod 0700`, so `node.yaml` stayed readable. A link swapped in for the old folder after the check was renamed, then `chmod 0700` followed it. And a failure here only warned, after the move was committed. Now root makes `/usr/local/eugene-plexus.moved-<time>` itself, takes any ACL entry off it (`chmod -h -N`), and checks it is root's, 0700 and has no entry; then it renames the old folder into it. Every path to the keys passes through root's closed folder, so what the person left on the old folder opens nothing; root changes no owner, mode or ACL inside it, so nothing is done through a link. The old folder must be the person's own real folder before the rename, and is checked again after it, inside root's folder where nobody else can swap it. All of this happens before the commit: a failure stops the run and the move is put back. A link that got in is left in root's folder and named. The removal closes what it keeps the same way: `chmod -h -N`, then checks it.
  - *B. The copy.* The 0600 file between the two `tar`s was the person's, so it could be swapped for an archive whose `.` entry carried an ACL granting the new prefix, which `tar -xp` restored. Now the person's `tar` streams to the account's through a pipe, and the account's `tar` restores no owner, permissions, ACL, extended attribute, file flag or Mac metadata (`--no-same-owner --no-same-permissions --no-acls --no-xattrs --no-fflags --no-mac-metadata`). The account then closes everything it copied to its group and others (`go-rwx`).
  - *C. The commit.* `lsof | head -1` saw one listener only, the samples could straddle a process swap, and the program match was a substring. Now every listener on the port must be launchd's pid, its command line must be exactly an interpreter in this install's venv, the agent and `--unattended` (`ps -ww`), and the health answer must fall between two samples that agree. A refusal says what it last saw.
  - *D. The home's ACL entry.* A run now records whether it added the entry. The entry goes on every way out of such a run: a move put back (whoever made the group), or a fresh install that stopped before its startup job was in place. Once the job is in place the install exists, and its removal takes the entry out by a receipt (`models-ace.txt`, the home it was put on), so root running the removal alone finds it. An entry an earlier install made is left alone. A membership of `_eugeneplexus` listed by name in `staff`, or in the person's own group, is taken back: an earlier build of this row put it there.
  - *E. Room.* Before anything stops, the move sizes what it copies as the person reads it and refuses, in MiB, when the disk holding the prefix lacks room for it plus 512 MiB for Eugene's own Python and packages (the third check below makes it twice the copy). The success message says where the old folder is kept and gives the `sudo rm -rf` that deletes it.
- **Defaults built in the re-review:**
  - **Removing Eugene deletes the old folder a move kept** (`/usr/local/eugene-plexus.moved-*`), and says so, in the confirmation dialog too. *This default deletes data:* that folder is a copy of the machine's keys and settings from before the move, and the current ones are kept as `.removed-<time>` as before. Only a real folder of root's with that name is deleted.
  - The headroom is 512 MiB.
  - A fresh install that fails after its startup job is written keeps the home's entry; its removal takes it out.
- **What these fixes cannot reach:** everything the move copies is the person's, so a program running as the person during the move can still put content in it: an engine build the daemon later runs as its account, or settings it later reads. Such a program could already read the keys before the move, so the move defends the keys from what arrives after it, not from what was there before. Root's removal run alone, with no `--person`, cannot drop the person's old Keychain entries (it does not know whose they are); run from the app or `install.sh --uninstall`, it does.
- **R8-ENGINES-COPY: no copied engine build is kept** (the orchestrator chose the stronger option before merge, 2026-10-22; first built as "keep a build that matches its record"). A record kept in the person's folder cannot vouch for a build there: a program that can change the build can rewrite the record. So the move removes every copied build, and a link where a build or an engine's folder belongs. The newest of each engine's builds is listed in `engines/refetch.json` (`{"builds": [{"engine", "version", "variant"}]}`). The agent, at its next start, fetches that version again through its usual install, verified against upstream's digests. A version upstream no longer has for the host is replaced by the newest it has. An entry whose fetch fails stays listed for the next start, and the console's Engines page can install one meanwhile. What is not a build (an engine's architecture lists) stays. The cost is one download per engine at the move.
  - *The record stays* for the builds the agent fetches itself: each build's `install.json` holds every file's `sha256:<hex>` (`files`) and every link's target (`links`), by `/`-separated path relative to the build, taken when the verified download is unpacked (`ManagedStore.write_metadata`, Strata's builds too). Nothing reads it yet; it is there for a later corruption check.
  - *Checks:* the agent's `test_install_records_each_files_sha256_and_each_links_target`, `test_a_listed_build_is_fetched_again_at_start` and `..._cannot_be_fetched_stays_listed`; the stub check M4b (a build matching its record is not kept either); and the acceptance's 11g on the macOS runners. 11g installs a build in the per-user install, changes its `llama-server`, moves, and checks that the move did not keep the build and that the daemon fetched it again, byte for byte as downloaded.
- **In its own account, Eugene runs no program anyone else can change** (orchestrator, before merge, 2026-10-22). A copied `agent.yaml` could name a program in the person's home (a runtime's `binary`, `vllmBinary`, `mlxBinary`, `strataServer`, `kevPython`, `uvBinary`), which the daemon would then run as its own account. Built (agent, `exec_trust.py`): when the agent runs as the account the installer made for it (`_eugeneplexus`, or `eugene-plexus` on a Linux system install), an engine binary (configured, a runtime's, on PATH, or a managed build) and the uv it installs apps with run only when the file and every folder above it belong to root or to Eugene's account, and none can be written by its group or by others. This is checked on the path as given and on the path its links resolve to, before anything runs, the `--version` probe and a Python engine's environment probe included. The runtime fails naming the path and the owner it found, for example "/Users/troy/llama/llama-server belongs to troy; Eugene's own account runs programs only from folders it or root owns. Move it, or let Eugene fetch its own build." A person's own install is not limited. At the move, such settings are kept as they were and listed as "will not run until moved", in the move's words and in root's receipt `/usr/local/lib/eugene-plexus/move-report.txt`. The removal and a rollback delete that receipt. Checks: `tests/test_exec_trust.py` (ten, on a stand-in disk, so they run on every platform; each part sabotaged once and caught), the stub check M4c, and two acceptance checks on the macOS runners. 11h puts `engineBinaryRoots` in the person's install at a folder of theirs, moves, and checks that the setting is kept and reported, in the move's words and in the receipt. 10e has the daemon run a runtime naming a stand-in `llama-server` in a folder of the runner's, allowed by `engineBinaryRoots` so only ownership decides. It checks that the runtime fails naming the path and the owner, and that the stand-in never ran, not even for its version. The first run found the rule working on the harness itself: when GitHub refuses the release list, 10d falls back to a llama.cpp build the workflow downloaded into the runner's own folder, and the daemon now refuses it. The acceptance copies that build into a folder of root's first.
  - *Not covered then:* Windows, macOS ACL entries, and executables an app or a tool server starts. The final review below replaced 10e and closed the ACL gap.
- **The final review (Codex, 2026-10-22, on refetch-all and exec_trust) found six blockers and two more, all fixed.** Each fix has a check that fails without it and was sabotaged once and caught: 11 installer sabotages against the stub checks, 15 agent sabotages, 2 ui sabotages.
  - *1, 2. Only state crosses the move.* A build whose `install.json` was a link survived, and other copied code gained trust: a planted `<old>/custom/llama-server` named by a setting was rewritten to its copy, and an app's planted `versions/.../python` was launched. Now the move carries a plain file or folder only when it is not code:
    - Never carried: links, Python modules, `.pth` files, compiled libraries, packages and environments at the top, the engine store, and the apps' `versions`, `pythons`, `launcher` and `.cache`.
    - Inside what crosses, the account removes every link and every execute bit.
    - The engine builds' install records cross as data, only to list the newest of each engine to fetch again; a linked record, or one behind a linked folder, is not read.
    - Every app whose data crossed is listed in `apps/rebuild.json`. The agent installs catalogue apps again from its own catalogue at start. An app the person added stays listed and is not started until it is installed again by hand.
    - A setting that named a program in the old install or its engine store is turned off (set to null) and said, in the move's words and in `move-report.txt`.
    - Components and apps start with `PYTHONSAFEPATH=1`, so nothing in the folder they start in is imported.
    - Why an allowlist by kind, not by name: state belongs to five repos' components, and a list of names would silently drop the state a later row adds, Workbench's chats among it. The property that matters is that nothing that runs crosses, and that is what is enforced.
  - *3, 4. What runs is what was checked.* `exec_trust` now walks a path by hand from `/`, following every link and checking every folder on every hop; a chain of links through a person's folder was the hole. It returns the path to execute: absolute, its folders resolved, and its last name kept when that is a link, because a venv's `bin/python` finds its environment by its own name. That path is what the agent runs, its probes included, so a relative path or a bare name cannot mean something else under a runtime's `workingDirectory` or on PATH.
  - *5. Interpreters and environments.* A script's interpreter is checked the same way: the `#!` line, and uv's `exec` line under `#!/bin/sh`. `#!/usr/bin/env` is refused. So is a Python environment the program belongs to, unless its root, its `site-packages` folders, and the interpreter it was made from (`home` in `pyvenv.cfg`) with that interpreter's standard library all pass. `uv` already builds app environments from its own managed Pythons only (`--python-preference only-managed`, into the apps' own folder). An app's interpreter is checked before it starts, and the checked path runs.
  - *Where the boundary stops, and why:* the files inside a checked folder are not each checked, since a folder only root or Eugene's account can change holds only what they put there. Packages come from the catalogue's pinned sources and PyPI, through uv's hashes, as on every install. What an app or a tool server starts in turn (Workbench's own tool processes, for example) runs inside that app's environment, which is checked when the app starts; the agent does not see those launches. Windows is not covered: its service accounts are guarded by ACLs, which this does not read.
  - *6. macOS permissions.*
    - On a Mac, each file and folder on the walk is also refused when an ACL entry lets anyone but root or Eugene's account write, append, delete, add or change it (read by name with `ls -le`). A root-owned 0755 file with `user:alice allow write` passed before.
    - A volume mounted with ownership ignored (`noowners`) is refused, naming the cause.
    - The volume is found from the file's own device: `df` names the volume's mount point, since a firmlinked `/usr/local` lives on the Data volume, and `mount` gives its options.
    - On Linux, a named user's write shows in the group bits (the ACL mask), which the mode check reads.
  - *The acceptance is unconditional and offline where it can be.* The A2 phase runs on the fresh daemon, before anything that can return early, on fixtures made there, each checked whatever happened before it:
    - Refused, naming the cause: a program in the runner's folder, root's program with an ACL entry that lets the runner write, a chain of links through the runner's home, a script whose interpreter the runner owns, an `env` shebang, and a volume mounted with ownership ignored.
    - Run: `/usr/bin/true`, and a program in Eugene's own store. A relative path runs as the absolute path that was checked.
    - None of the refused programs ran.

    11i plants the review's cases in the person's install before the move: a build as downloaded, one behind a linked record, a program named by a setting, an app's environment beside its data, a module, and a link in a data folder. It checks that none of them runs after the move. 11g, the fetch again from GitHub, may still skip when GitHub refuses, and says why. The bypassable 10e is gone.
  - *Recovery (should-fix).* When the agent, in its own account, refuses the program a runtime's own `binary` names, `Runtime.refusedBinary` says which. The console's row shows "Eugene won't run <path>: someone else can change it", with one button: "Use Eugene's own <engine>". The button installs the engine when there is none, declares the runtime again without `binary`, and starts it. This is the way out for a program in `/opt/homebrew` on Apple silicon, which belongs to the person who installed Homebrew. Positive checks: `/usr/bin/true` and Eugene's own store (A2g, A2h), and on Linux the real `/bin/true` (`test_linux_system_programs_run`).
- **The third check (Codex, 2026-10-22) found three blockers and three more, all fixed**, each with a stub check that fails without it (M2, M4, M8e, M13, M13b-f, M15b):
  - *1. Path components above the old folder.* The checks covered the final component only, so a link put in for `~/.local/share` could make root's rename move a folder of root's (`/usr/local/lib/eugene-plexus`, the receipts). Root now renames nothing on the person's side. It makes and closes its keeping folder, adds one ACL entry that lets the person, and only the person, put a folder into it (`search,add_subdirectory`), and the person's own `mv` moves the old folder in, with the person's rights. Root then takes the entry off and checks, inside its own closed folder, that the folder holds one real folder of the person's with a `node.yaml`. Root also reads the person's plist, `agent.yaml` and `node.yaml` as the person.
  - *2. Across disks* `mv` is a recursive copy. An old folder on another disk than `/usr/local` is refused before anything changes, with what to do instead, and is checked once more just before the rename.
  - *3. An interrupt after the keeping, before the commit,* removed the copy without putting the old folder back. A rollback now first opens root's folder to the person (`search,delete_child`), has the person rename the old folder back, and only then removes anything. What cannot be put back is said, with the `sudo mv` that does it.
  - *4.* The sample after the health answer checks the exact command line again (an exec in the same pid).
  - *5.* The home's entry is read by name (`ls -le`): with `-n`, macOS prints the group as a UUID, so a grant from before was never seen and could be taken out by a rollback. An entry that will not come out is said, and its receipt stays, in the installer and in the removal.
  - *6.* A size or a free space that cannot be read stops the move. The copy is kept by the account in its own prefix (`.move.tar`, closed to the person) and cut off at what was measured just before, plus a tenth and 64 MiB: a folder that grows while it is copied is refused. The room check counts the copy twice (staged, then unpacked).
  - *Not reachable by sampling:* a second listener that lives only between the two samples.
- **With 8080 taken at first boot, control lands on the gateway's port** (agent#31): the gateway walks to 8084, then `move_control_behind` moves control to 8084 too, because `first_free` never skips its preferred port. Any Mac or Linux box with JupyterLab on 8080 meets it. `machine_port.py` is another lane's, so it is filed, not fixed. The acceptance therefore holds only 8079 and 8081 (the design said 8079-8083), and leaves 8083 to the install's machine port: every node opens it there, the installer has no setting for it, and the root's own join token pins it (agent#27).
- A4 moves to the daemon: it reads the account's files with sudo, kickstarts `system/...`, sets the control root to `passphrase_file` as the wizard does, and expects the account gone after removal.

## 8c: approving a program one other account can change (R8-EXEC-TRUST, Choice 3)

Troy pushed back on the refusal above ("too restrictive") and chose Choice 3 (2026-10-23). It applies only where Eugene runs in an account of its own: the Mac's daemon and a Linux system install. A person's own install is not changed.

### The design (the orchestrator's, 2026-10-23)

1. **Three kinds.** `exec_trust` walks the chain as before: the file, every folder, every link and where it points, a script's interpreter, and the Python environment the program belongs to. Then it decides:
   - `ok`: root and Eugene's account own every item, and no group or others can write any of them. It runs.
   - `needs_approval`: every item is owned by root, by Eugene's account or by one other account, and no group or others can write any of them. It runs only with an owner's approval.
   - `refused`: a group or others can write an item, or two or more other accounts own items. It never runs. The error names the path and who can write it.

   The verdict carries the kind, the other account (uid and name) and the path to execute, so callers never work them out again.
2. **An approval binds** the path to execute, the other account's uid, the file's SHA-256, and the chain's (path, uid, mode) list. It lapses when any of them differ at the next check, and the runtime asks again. The agent keeps approvals in a file in its own state folder that only Eugene's account can write.

   **An approval trusts that account.** The hash catches a change. It is not a boundary against the account that owns the file, and nothing is done about a time-of-check race beyond what the walk already does.
3. **The contract** (`agent.yaml`): a runtime's failure carries `execTrust {kind, path, account, sha256}`. `GET/POST /v1/exec-approvals` and `DELETE /v1/exec-approvals/{id}`, for the owner only. POST takes `{path, sha256}`. The agent checks again at that moment and answers 409, naming the cause, when the kind is not `needs_approval` or the hash differs from the one shown.
4. **The console** asks on that runtime's failure: "Run llama-server from /home/ada/bin as Eugene's account? Anyone who can change this file (ada) can then act as Eugene." The buttons are "Run it" and "Not now", with "Use Eugene's own build" beside them. Settings lists the approvals, each with Remove.
5. **The move report and its receipt** say "Eugene will ask before running it" for a setting whose program one other account can change. Only `refused` settings say "It will not run until moved".

### What building found (2026-10-23)

Built on the same branch (agent `exec_trust.py`, `exec_approvals.py`, `routes/exec_approvals.py`; ui `lib/execTrust.ts`, `components/ExecApprovals.tsx`, the inference page; specs `agent.yaml`, `install.sh`).

**Defaults built for questions the design left open** (none of them deletes data or keeps chats somewhere new):

- **One decision function.** `exec_trust.assess(path)` returns a `Verdict`. One rule, `runs(verdict)`, decides what runs: `ok` runs, `needs_approval` runs while an approval holds, `refused` never runs. `trusted_program` and `untrusted` call it.
  - The walk now goes on past an item another account owns, so the verdict knows whether anything else could change the program too.
  - Before reading the first bytes of a file, the walk checks that it is a plain file, and it opens the file without blocking. A pipe a person puts where a program belongs cannot hold the agent.
- **What counts as `refused`, beyond the design's two cases:**
  - A macOS ACL entry that lets anyone but root, Eugene's account or the item's own owner write.
  - A volume that ignores ownership.
  - A `#!/usr/bin/env` script.
  - Anything that cannot be checked: a missing item, too many links or interpreters, an unreadable ACL or volume, or a file larger than 1 GiB to hash.

  An ACL entry that lets the single other account write is refused too, not offered for approval. That is stricter than needed, and simpler.
- **Which bytes are hashed.** The SHA-256 is of the file that runs. A script's interpreter and environment are bound through the chain (path, owner, mode), not through their bytes. The approval trusts that account in any case.
  - Hashes are cached by device, inode, size, mtime and ctime. Every write changes ctime, and an owner cannot set ctime back.
- **The approvals file** is `exec-approvals.json`, beside the agent's `agent.yaml`, written owner-only (0600) and atomically.
  - The agent reads approvals only while the file and every folder above it pass the same walk as an `ok` program. Otherwise it reads none and logs why, and an approval is refused (409) with the cause.
  - A lapsed approval is removed from the file at the check that finds it, and the agent logs which binding changed: the account, the file, or the chain.
  - Approving a program again replaces its earlier approval.
- **Who may approve:** the owner's session (`require_operator_session`, as every other write on the agent). A component's, the gateway's or another machine's service token gets 401 on all three routes.
  - POST answers 409 for a `refused` program (the refusal's words), for one Eugene runs already ("there is nothing to approve"), and for a hash that differs ("changed since it was shown").
  - DELETE answers 404 for an unknown id.
  - `approvedBy` is the session's `sub`.
- **Where `execTrust` appears:** on `Runtime` (cleared on a successful start) and on `GET /v1/engines`' entries. A program found through `vllmBinary` or on PATH can therefore be approved too, and the acceptance reads it there.
  - `Runtime.refusedBinary` stays: it names the runtime's own `binary`, which "Use Eugene's own build" clears.
- **The console.**
  - "Not now" hides the question for that file's hash. A changed file asks again.
  - "Run it" posts the path and hash the node showed, then starts the runtime. A failure is shown on the row with the agent's words.
  - A `refused` program is never offered for approval, whatever else a node sends.
  - Settings shows an "Approved programs" card, only when some machine has an approval. Each row shows the path, the machine, and "<account> can change it, and so act as Eugene", with Remove.
  - An agent from before 8c (404) lists nothing.
- **Messages name the path, who can change it, and what to do.** The way out is "copy its folder into <Eugene's folder> as an administrator, or let Eugene install the engine itself". Eugene's folder is the account's home, which the installers make the prefix.
  - An app's interpreter offers "install the app again".
  - The uv the agent installs apps with offers "install Eugene again, which puts its own uv back".

  For example: "Eugene's own account runs /Users/troy/llama/llama-server only once an owner approves it: it is reached through /Users/troy, which belongs to troy. Approve it, copy its folder into /usr/local/eugene-plexus as an administrator, or let Eugene install the engine itself."
- **The move's report** reads the settings as Eugene's account. It says "<account> can change it. Eugene will ask before running it." when one other account owns parts of the path and nothing on it is group- or other-writable. Otherwise it says "It will not run until moved." The agent's own walk (links, interpreters, ACLs) decides in the end. The report is the installer's forecast.

**Tests that failed first, and the sabotages:**
- agent `test_exec_trust.py`:
  - The three kinds on the stand-in disk: `ok` is not hashed; `needs_approval` carries the account, the uid, the SHA-256 and the chain.
  - A group-writable folder is refused, naming its owner and group. A person's group-writable folder is refused, not offered. Two accounts are refused.
  - A pipe is not read.
  - `Runtime.execTrust` and the engine list's `execTrust` are set.
- agent `test_exec_approvals.py`:
  - An approved program runs. Its approval lapses when the bytes change, when a folder on the way changes, and when another account holds it.
  - Each binding is compared on its own.
  - A refused, changed or trusted program is not approved.
  - Approvals are not read from a file others could change, and the file is checked like a program.
  - Through the API: approve, list, take back, 409s and 404, and only an owner's session (a gateway or library token gets 401).
- ui `execTrust.test.ts`, `ExecApprovals.test.tsx`, and three inference-page cases: the question and "Run it", "Not now", and a refused program not offered.
- specs `row8-install-sh-checks.sh` M4c: a setting naming a program only this shell's account can change, read as another account by the stand-in Python (`EP_STUB_EUID`), says "Eugene will ask before running it". Settings under `/tmp` (world-writable) still say "It will not run until moved".
- Sabotages, each restored from a copy and each caught: 14 in the agent, 7 in the ui, 2 in the installer.

**Acceptance (macOS runners, `row8-macos-daemon-acceptance.py`):**
- A2a has the daemon list a stand-in `vllm` in the runner's folder. Its interpreter, also the runner's, leaves a mark when run.
  - First the stand-in waits for approval (`needs_approval`, naming the runner) and is not run, not even to read its environment (A2a1).
  - Approved through the API, it runs: it is listed at its path, and its interpreter ran (A2a2).
  - With one byte changed, it asks again: the approval is gone, and it is not run (A2a3).
- A2c (a chain of links through the runner's home) and A2d (a script whose interpreter the runner owns) now expect `needs_approval`.
- A2b (ACL), A2e (`env`) and A2f (ownership ignored) expect `refused`.
- A new A2k puts root's program in a folder its group (staff) can write. The program is refused, naming the owner and the group, and `POST /v1/exec-approvals` answers 409 (A2k2).
- 11h now expects the move to say "Eugene will ask before running it" for `engineBinaryRoots` naming the runner's folder.

**What the first CI run of 8c found on the macOS runners** (A2 passed in full on macOS 14):
- **11h had been green for the wrong reason.** The move read the copied settings as Eugene's account before the home's ACL entry let that account pass. A folder in the home therefore read "it cannot be checked (Permission denied). It will not run until moved". The old 11h asked only for "It will not run until moved", so it passed without the ownership ever being read. Now the move reads the settings right after the home's entry is in place, as the daemon will read them. 11h expects "runner can change it. Eugene will ask before running it." The stub check M4c checks the order, in the stand-in `sudo`'s log (sabotaged once and caught).
- **11g's words were stale.** Since the final review the move copies no engine build, so the per-build line "did not keep the llama_cpp build" is gone. 11g now asks for the line the move does say: "fetches llama_cpp <version> again ... (no engine build crosses the move)". The refetch itself had passed, byte for byte.
- **MLX's environment was built on a Python Eugene's account will not trust** (A4 30, 44). Run as the account, the recipe's `uv venv --python cpython-3.12-macos-aarch64-none` picked the python.org framework on the runner. Its `/Library/Frameworks/Python.framework/Versions` is group-writable (0775, `root:wheel` there; `root:admin` from python.org's installer). The environment check refused `mlx_lm.server`, correctly by the rule. The recipe now adds `--python-preference only-managed`, so uv puts its own Python under the account's home, the install's folder (agent `engines/mlx.py`; `test_the_recipe_builds_on_uv_s_own_python_never_one_installed_on_the_mac` failed first).
  - *Not built:* a group whose only member is root (`wheel` on a Mac) can write nothing that root cannot. Treating it as root's would need the group's members read on every check. With uv's own Python no engine path met it, so it stays refused.

**The 8c review (Codex, 2026-10-23) found four blockers and two more, all fixed.** Each fix has a check that fails without it, and each was sabotaged once and caught (12 in the agent, 1 in the installer):
1. *The move carried forged approvals.* A program running as the person could write `exec-approvals.json` into the per-user install, binding a program of the person's exactly as an owner's approval would. The move carried it, made it the account's, and the daemon honoured it. Now the move never carries it ("did not carry exec-approvals.json: the owner approves programs again for Eugene's own account").
   - Stub check M4d covers the exclusion.
   - Acceptance 11j plants an approval that binds exactly what the owner's own approval binds: the path, the uid, the SHA-256 and the chain. The test approves the same program through the API and compares the two. After the move, it checks that the planted approval did not cross and that the daemon asks.
2. *ACL principals with spaces.* `group:Domain Users allow add_file,delete_child` did not match the parser and was passed over, so the program read as `needs_approval`. The principal is now read whole. An entry the parser does not understand is refused, naming the entry.
3. *The interpreter checked was not always the one run.*
   - `#!python` was walked from the agent's folder, while vLLM's probe ran a bare `python` through PATH. A link named `run` to `/usr/bin/env` passed the name check.
   - Now an interpreter must be an absolute path, in the shebang and in uv's exec line. A program or interpreter that is `env` under any name is refused.
   - In Eugene's own account, vLLM's probe runs only the absolute interpreter the check walked.
4. *Unreadable files failed open.* An execute-only script's first line could not be read, and the check took the script for a binary. That is now refused, naming the cause. So is an environment whose `pyvenv.cfg` cannot be read or whose `lib` cannot be listed.
5. *A refusal kept the approval.* Opening a folder to everyone and closing it again revived the approval. Now a refused check drops the program's approval.
6. *Folder links.* An approval was kept by the resolved path, so a program configured as `/Users/troy/current/llama-server` (with `current -> /opt/real`) was approved with a shorter chain, and its next start lapsed it. Now `ExecTrust.path` is the path a setting looks the program up by, made absolute with its links kept. The approval is shown, made and kept by that path.

Also from the review: the SHA-256 answer is no longer kept between checks. A file's change time moves on a coarse clock (a second on HFS+, a jiffy on Linux), so two writes could share one, and a changed file could keep its old hash. A test with the real hash changes one byte, keeps the size, puts the modification time back, and holds the clock still.

**Not covered, and why:**
- Windows, as before.
- What an app or a tool server starts, as before.
- An approval is not a boundary against the account it trusts, by design.
- The stub suite has no case with two other accounts. It runs as one account without root. The agent's test covers that case.
