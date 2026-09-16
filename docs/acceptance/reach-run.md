# Reach it from other devices — acceptance run (2026-09-15)

**Result: 39 `PASS` lines, zero failures, second execution** — and the
first execution's one `NOTE` was a real defect, which is why the note is
now a check. `scripts/reach-acceptance.sh`: four processes on +100
ports, the environment cleared, teardown by pid, the system Chrome
driving `ui/e2e/reach.spec.ts`. Hobbyist UX plan S5, decision **#8**.
Design: [`../design/hobbyist-ux.md`](../design/hobbyist-ux.md) §7 S5 and
§6.6; record §11.6.

## What was built, in one paragraph

`GET /v1/node` gains `reach`, and `POST /v1/node/reach` is the switch
behind Home's **Reach it from other devices**. Three separate things have
to be true before another device can open this install — something is
listening off loopback, the node advertises that address, and the host
firewall lets the connection in — and all three fail identically from
outside, as *connection refused*. Each is now reported on its own and
from evidence: `boundAddresses` from the value each process was handed at
bind time, `firewall` from the host firewall through `HNetCfg.FwPolicy2`,
`lastReachedFrom` from a connection something off this machine actually
made.

## What the run proves, and the one thing it does not

It proves the **bind** moved and the **setting** moved: before the
switch, `192.168.16.75:8179` refuses; after it and an agent restart, the
UI, the agent's API and the gateway's OpenAI surface all answer there.

It does **not** prove a second device can get in, and the run says so
rather than implying otherwise. Every connection in check 8 came from
this machine to its own LAN address, and host-local traffic is not
filtered by the host firewall — which is why check 10 reports the
verdict `blocked` for the same port in the same run. **That is not a
contradiction; it is §6.6's thesis reproduced.** Static inspection says
what should happen; only a connection from elsewhere says what did.

## The measurements that changed the code, before a line was written

| what was measured | what it changed |
| --- | --- |
| The advertise address the agent has derived since M7 is the local end of a socket **to the control root** — `127.0.0.1` on a standalone install, because the root is on loopback | The plan's "propose the LAN address the agent already derives" could not work for the person S5 is for. `proposed_host` is a second derivation off the routing table |
| `Get-NetFirewallPortFilter` raises **Access is denied** unelevated *and returns a truncated list on the way out* | The cmdlets are not used at all. A detector built on them reports "nothing covers our port" from a partial read |
| COM: **78 ms** for profiles plus all 708 rules, against ~2.8 s for three cmdlets, before a PowerShell subprocess has started | The read happens with the node view; the design's caching worry goes away |
| This box is reachable through a rule bound to the **program** — Windows' own Security Alert dialog named the interpreter — with **no rule mentioning 8079 or 8080** | Program rules count, and `FirewallPort.scope` reports which kind decided |
| That program is `...\EugenePlexus\pythons\cpython-3.12.14-...\python.exe`, a **versioned** path | A rule *we* add is scoped to ports. A program rule stops applying the day the interpreter is upgraded, silently |
| `Get-NetFirewallProfile` reports `DefaultInboundAction: NotConfigured` on a stock, blocking machine | `DefaultInbound` has `unknown` as a third member; comparing the cmdlet's string to `"Block"` reads a blocking machine as not blocking |
| A closed local port on Windows is **dropped, not refused**: 362 ms to time out against 6.6 ms for an open one | A connect probe was written for `boundAddresses` and thrown away; the bind value is exact and free |

## The checks

```
preflight   agent python, Playwright, ports free, this host at 192.168.16.75
 0  isolated: no ambient EUGENE_PLEXUS_*
 1  the UI staged from this tree AND served by this agent venv
 2  the fleet, with NOTHING declared about binding
 3  before: loopback answers, 192.168.16.75 does not — agent and gateway
 4  reach.proposedUrl is http://192.168.16.75:8179, and is NOT loopback
    boundAddresses: agent, control, gateway, library all 127.0.0.1
 5  the switch: advertise ok, components restarted, restartRequired true,
    mechanism none / canSelfRestart false
 6  after: the gateway answers on 192.168.16.75:8180 with no agent restart;
    the agent still does not
 7  restarted by hand: the agent answers there, and said why it widened
 8  the UI, the agent API and the gateway's /v1/models all answer on
    192.168.16.75  ← the done-when
 9  lastReachedFrom is 192.168.16.75, and a loopback caller does not
    overwrite it
10  the verdict names Windows Defender Firewall, is `blocked` for 8179,
    and carries the command that would change it
11  off: the gateway is back on loopback only, and no restart was asked for
12  Chrome: the card, the non-loopback address, the switch, and the
    "needs to restart" line it produces
13  teardown: no owned port still listening
```

## THE FIRST EXECUTION'S ONE NOTE WAS A DANGEROUS DEFECT

Check 5 printed:

```
NOTE  canSelfRestart=True (this shell's agent looked supervised; ...)
```

A throwaway agent, started from a bash shell, running out of
`d:\py\eugene-plexus\agent\.venv`, on ports +100, reported
`mechanism: logon_task` and `canSelfRestart: true`. It is not supervised
by anything. **The detector had asked only whether a scheduled task named
`EugenePlexusAgent` exists — and the live worker install on this box owns
one.** Had anything in the run pressed the card's restart, it would have
run `schtasks /End /TN "EugenePlexusAgent"` against **the operator's real
agent**, stopping the live install and starting it again while the
throwaway kept its ports.

Nothing was harmed because the run never asked for a restart. That is
luck, not design, and it is exactly the shape of the M11-era finding
where an acceptance script inherited the live install's identity through
the user environment. **A machine can hold two installs**, and the rest
of this codebase knows it: `keyring_store` scopes its entry by install
(S0), and every script since 2026-09-12 clears `EUGENE_PLEXUS_*`.

Fixed by asking whether the task's program lives inside **this process's
`sys.prefix`** — the installer registers
`<prefix>\Scripts\eugene-plexus-agent.exe`. Deliberately not
`sys.executable`: in a uv-made virtualenv that is the base interpreter
under `pythons\cpython-...`, outside the prefix and shared between
installs, so comparing it would call the real install's own task somebody
else's. Verified both directions on this box — the live install's
interpreter detects its task, this checkout's does not.

`launchd` had the same shape (a plist existing is not proof this process
is what it starts) and now also requires the parent to be pid 1.

And the note became a check. **A note is what you write when you do not
want to decide**, and deciding this is the entire reason to run on a box
that also holds a live install.

## Three sabotages escaped, all the same mistake

Ten sabotages were run against the agent's tests and four against the
UI's. Three escaped, and every one of them escaped for the same reason:
**the test exercised a pure helper rather than the function that uses
it.**

1. Removing the `canSelfRestart` guard from `restart_argv` passed all 34
   tests, because the only case asserted was `mechanism: none` — where no
   branch matches and the guard is redundant. The case that matters is a
   mechanism that *is* detected while its tool is absent (systemd with no
   `systemctl`), where the unguarded version stops the agent with nothing
   to start it. An install ended by a browser click.
2. Replacing `_windows_task_runs_this_install`'s body with `return True`
   passed all 36 — undoing the fix above, in the same session that made
   it.
3. Loosening the prefix comparison to its **parent directory** passed all
   36, because the only negative case was a task under another user's
   home. A negative case has to be near the positive one: two
   virtualenvs side by side, and `.venv2` not read as inside `.venv`.

Same family as M10's check 7, step 6's fragmentation checks and the
navigation slice's `/librarian` prefix case. Each has its own test now,
and each was re-sabotaged to confirm it fails.

## Not covered

- **Reach from a genuinely second device.** The run is one box. The
  firewall verdict says `blocked` while check 8 passes, which is the
  honest state of the evidence and the reason `lastReachedFrom` exists.
- **`blocked` → `allowed`.** Adding a firewall rule needs administrator
  rights and outlives the run, so it is `EP_FIREWALL=1` and was skipped,
  reported as `SKIP` rather than silently not run.
- **The UAC path.** An unelevated `add_rule` raises a prompt on the
  desktop and returns "we do not know yet"; nobody has clicked Yes.
- **Linux and macOS detectors.** Written, unit-tested, never run against
  a live `ufw`, `firewalld` or `socketfilterfw`.
- **A real self-restart.** Every mechanism's argv is asserted; none has
  been executed. The run restarts the agent by hand, which is what the
  card tells an unsupervised install to do.
- **A third-party firewall.** `root\SecurityCenter2` returned nothing on
  this box, so the "every verdict becomes `unknown`" branch is
  unit-tested only.
