# Row 8: Installer pass: a Mac service that starts at boot, and `--label`

Lane OPS. Risk: high (installers, a migration). Size: M. Sources: R2.6-mac, PLAT-START, NL-INST. Calls: MAC-ACCT, MAC-KEY.

## 1. What the row delivers

- A new Mac install runs Eugene as a LaunchDaemon. It starts at boot, before anyone signs in, as the person who installed it. The installer asks for sudo once.
- An existing Mac install (a LaunchAgent) moves to the LaunchDaemon on its next installer run. Folder, port, settings and node identity stay. After the move it asks for the passphrase once.
- The wizard's "Eugene itself starts when this machine does, before anyone signs in." becomes true on a Mac. `--user` keeps today's LaunchAgent, with no sudo.
- `install.sh --label "Studio Mac"` and `install.ps1 -Label "Studio PC"` set the machine's label when it joins. The console's "Add a machine" form gets "Shown as", which adds the flag to the printed command.

## 2. The design

### The Mac layout (`install.sh`)

- New mode `daemon`: macOS, with a service, without `--user`. The prefix stays `~/.local/share/eugene-plexus` and the daemon runs as the person (call MAC-ACCT), so nothing moves.
- `/Library/LaunchDaemons/com.eugeneplexus.agent.plist`, `root:wheel`, 0644, written by the install's Python with `plistlib`. (Today's heredoc plist is invalid XML for a home path holding `&` or `<`; the LaunchAgent writer changes too.)
- Keys: `UserName` (the person), `GroupName` (their primary group), `ProgramArguments` (`$VENV/bin/eugene-plexus-agent --unattended`), `WorkingDirectory`, `RunAtLoad`, `KeepAlive` true, `ThrottleInterval` 10, the logs, and `EnvironmentVariables`: `HOME`, `USER`, the config file, `EUGENE_PLEXUS_AGENT_PASSPHRASE_FILE` and `EUGENE_PLEXUS_CONTROL_PASSPHRASE_FILE` (`$PREFIX/passphrase`), and the port and bind variables.
- A daemon plist without `UserName` runs a program the person can write as root. So the installer refuses an empty or root person: "Run this as yourself, not in a root shell. It asks for sudo when it needs it."
- Start: `sudo launchctl bootstrap system <plist>`. Stop: `sudo launchctl bootout system/com.eugeneplexus.agent`.
- **Unlock (call MAC-KEY).** The login Keychain stays locked until someone signs in, so `os_keyring` would leave every boot sealed. A fresh daemon install writes `securityMode: passphrase_file`, as the Linux system install does; the wizard already sets the control root to match.
- **Firewall.** A daemon cannot show macOS's "Allow incoming connections" prompt. When the install binds wide, the installer allows the venv's Python with `socketfilterfw` and records it in the receipt's `firewall.txt`, which removal already reads.

### Migration: a plain re-run over a LaunchAgent

1. Continue only when the LaunchAgent's `ProgramArguments[0]` is inside this prefix; otherwise stop and name the other install.
2. Say it first: "Eugene will start when this Mac starts, before anyone signs in. This needs your password once. After the move, sign in to Eugene once; from then on it unlocks by itself."
3. Keep the port and bind-host variables from the old plist (`--update` reads the port this way already; read the bind host the same way).
4. Write the daemon plist under a temporary name, check it with `plutil -lint`, rename it.
5. `launchctl bootout gui/<uid>/...`; wait up to 15 s for every process whose argv[0] is in the prefix.
6. `launchctl bootstrap system <plist>`. On failure, remove it, bootstrap the LaunchAgent again, and stop with launchctl's words.
7. Wait for `/healthz`, then delete the old plist.
8. `os_keyring` in `agent.yaml` becomes `passphrase_file` there and in `control.yaml`; `prompt_on_startup` stays. The first sign-in writes the file. Old Keychain entries stay until uninstall drops them.

`--update` never migrates. `--user` beside the daemon is refused: "This Mac already starts Eugene at boot. Re-run without --user to update it."

### Agent (`reach.py`)

- `_launchd_restart` reads the daemon plist first. It is this install's when `ProgramArguments[0]` is inside `sys.prefix` and the parent is pid 1. Then: `mechanism: launchd`, `detail` "This agent starts at boot, before anyone signs in.", and `canSelfRestart: true`. The person cannot kickstart a system job, so `restart_argv` is `/bin/sh -c "sleep 1; kill -TERM <own pid>"` and `KeepAlive` brings the agent back. `command`: `sudo launchctl kickstart -k system/com.eugeneplexus.agent`.
- The LaunchAgent branch gets `detail` "This agent starts when you sign in to this Mac."
- No contract change: `Mechanism.launchd` covers both.

### Removal (`scripts/uninstall.sh`, embedded by `embed-uninstall.py`)

Remove the daemon only when its program is in the prefix: `sudo` from a terminal, `osascript ... with administrator privileges` from the Mac removal app. Failure: "macOS refused to stop Eugene's startup job: <launchctl's words>. Nothing was removed."

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
- `r22-install-sh-checks.sh`: `--label 'Studio PC'` reaches the stub agent as one argument; `--label` alone is refused. Today: "unknown option".
- `r22-install-ps1-checks.ps1`: `-Label` reaches `$joinArgs`; a `"` is refused; every byte is below 0x80.
- ui `joinCommand.test.ts`.

## 5. Acceptance

**`scripts/row8-macos-daemon-acceptance.py`**, CI on macos-14, 15 and 26, as the runner with passwordless sudo. Agent on 18279; idle listeners hold 8079-8083 for the run; `EUGENE_PLEXUS_*` cleared.
1. The daemon plist is `root:wheel` 0644, lints, and names the runner. No LaunchAgent.
2. launchd runs it; the agent's uid is the runner's (never 0); its parent is pid 1.
3. Health answers; nothing of the run listens on 8079-8083.
4. Onboarding: agent and control use `passphrase_file`; the file is 0400 and the runner's.
5. Reach says launchd, "starts at boot", can restart.
6. `security lock-keychain`, then `sudo launchctl kickstart -k`: the root comes back unlocked with nobody signing in. (The runner's Keychain is unlocked, so without the lock a Keychain-dependent install passes.)
7. Reach's restart gives a new pid under launchd within 30 s.
8. In the daemon, the agent reports Metal, and a tiny GGUF answers through the gateway.
9. Migration from a `--user` install onboarded with `os_keyring` and enrolled: words first; node name, key and port unchanged; sealed until one sign-in; then a kickstart unlocks by itself.
10. A `launchctl` stand-in fails `bootstrap system`: the LaunchAgent serves again, and the message holds launchctl's words.
11. `--user` beside the daemon is refused.
12. Uninstall: plist gone, job unknown to launchd, no process left, config kept.

Linux and Windows run the `--label` stub checks. **Not in CI:** a reboot and sign-in on a real Mac, bare-metal Metal, macOS privacy prompts (runner images may pre-grant them).

**The reviewer should attack:** a plist with no `UserName`, root, or another person; XML or path injection, or a symlink at the plist path; a migration leaving two agents or none; identity or port lost; removal of another install's daemon; the restart signal reaching another process; the passphrase file's mode; `-Label` quoting on PowerShell 5.1, and `'`, `$` and spaces in sh.

## 6. Do not change

- `install.sh`'s Linux system path, root update helper and job-site sections: change only the Mac and `--label` code.
- agent `install_info.py`, `update_apply.py`; `apps.py`, `client_doors.py` (AG2); `node_identity.py`, `machine_port.py` (TRUST 3, 46); `entrypoint.py` (TRUST 45).
- ui `settingsTopics.ts`, `ResourceTree.tsx` (WEB 33), `ConfigField.tsx` (WEB 62), the setup wizard.
- `release.py`, `release_gate.py`, `release-inputs.py` (OPS 6); every `scripts/codegen.py`.

## 7. Size, risks, calls

**Size:** M, about 1.5 days. One branch, `r8-installer`: **8a (S)** `--label` and the form; **8b (M)** the daemon, migration, Reach, removal, acceptance. One adversarial review after 8b.

**Risks:**
- Metal in a daemon is unproven. Check 8 decides; if it fails, the row stops for Troy.
- A daemon cannot show a privacy prompt, so a model folder under `~/Documents`, `~/Desktop` or `~/Downloads` may be unreadable. If the Library does not name the cause, file a library issue with: "macOS keeps Eugene out of this folder. Give python3.12 Full Disk Access in System Settings > Privacy & Security, or keep models in ~/Eugene Models."
- Network shares mount at sign-in, so a model on one is missing at boot.

**Calls only Troy can make (recommendation first):**
- **MAC-ACCT.** Run as the person now: nothing moves, and it is M. Its own account, as on Linux, also protects the keys from programs the person runs, but it is L (group access, privacy permissions, the engine store): a later row.
- **MAC-KEY.** A passphrase file in place of the Keychain on a daemon. Any program running as the person can read it, as it can already read `node.yaml`; the same-account warning stays.

**Found while drafting:**
- The wizard's sentence is fixed text, false on `--user` and `-NoService`. File a ui issue: print `restart.detail`.
- `reach._systemd_restart` uses `systemctl --user` whenever the process is not root, as a Linux system install (`User=eugene-plexus`) never is. Check it, and file an agent issue if Reach's restart fails there.

## Calls answered by Troy (2026-10-21)

- **MAC-ACCT: Choice 2.** Eugene runs on a Mac in an account of its own, as on Linux. The row grows from M to L: folder access, macOS privacy permissions and the engine store move to that account.
- **MAC-KEY: Choice 1.** The passphrase is kept in a file that only Eugene's own account can read.
