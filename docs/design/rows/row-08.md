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
  - *The move never reads with root's access.* It used root's `ditto`, which follows a link given as an argument, then chowned the copy to the account. Now the person's `tar` reads the old folder (links stay links) and the account's `tar` writes it, through a 0600 file this run made.
  - *The old folder is kept as root's.* Its `node.yaml` holds the machine's private keys in clear; left in the person's home, a program running as the person could sign as the machine. It is now renamed to `/usr/local/eugene-plexus.moved-<time>`, root:wheel 0700, and the installer says it holds the machine's keys. A link in place of the old folder is refused.
  - *A move commits only on the daemon's answer:* the process on the port must be the pid launchd gives for the system job, running this install's program.
  - *A rollback that cannot stop the daemon stops there*, with launchctl's words: it does not start the LaunchAgent beside it or take the copy apart.
  - *The root's move at sign-in* (agent) requires a control entry on loopback, counts a keyring probe that ran out of time as "might work" (never as absent), logs a config the root will not show, and logs a `securityMode` the root rejects in a 200 answer with the root's words.
  - *The acceptance* fails 11d and 11e when the Keychain move was not exercised, and reads the root's mode after the sign-in.
- **With 8080 taken at first boot, control lands on the gateway's port** (agent#31): the gateway walks to 8084, then `move_control_behind` moves control to 8084 too, because `first_free` never skips its preferred port. Any Mac or Linux box with JupyterLab on 8080 meets it. `machine_port.py` is another lane's, so it is filed, not fixed. The acceptance therefore holds only 8079 and 8081 (the design said 8079-8083), and leaves 8083 to the install's machine port: every node opens it there, the installer has no setting for it, and the root's own join token pins it (agent#27).
- A4 moves to the daemon: it reads the account's files with sudo, kickstarts `system/...`, sets the control root to `passphrase_file` as the wizard does, and expects the account gone after removal.
