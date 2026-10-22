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
