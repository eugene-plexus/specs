# R2.6 — Windows comes back by itself

`scripts/r26-acceptance.sh`, **25 PASS, zero failures, zero skipped**
(fifth execution — the first four failed on harness defects, all four
recorded in §4). `scripts/r26-sabotage.py`, **26 sabotages, 25 caught,
one escape expected and one unexpected that named a check which could
not fail**. Design:
[`../design/windows-comes-back-by-itself.md`](../design/windows-comes-back-by-itself.md).

Repos: `specs` (contract `dfe6b67`, both installers), `agent`
`51d1c8a`, `ui` `e98ed30` / dist `14f9073`, and `control`, `gateway`,
`library`, `inference-driver` regen-only. **All six pinned level at
`dfe6b67`** and both installers re-pinned.

---

## 0. ▶ What this run did NOT do, first, because it is most of the point

The slice's *Done when* is **"a Windows box with nobody logged in
reboots and serves a completion"**, and this run does not reach it. The
session was **unelevated**; `SC_MANAGER_CREATE_SERVICE` is granted to
nobody but Administrators, and nothing non-interactive can reboot a
machine and then not sign in.

**Six checks are owed**, and they are printed by `install.ps1 -Verify`
so they cannot be lost in a document:

1. The service registers, answers `/healthz`, and stops.
2. **`AllocConsole()` in SESSION 0.** §0.3 below measured it in session
   1. A service runs in session 0 and that has not been measured
   anywhere; the log line `child shutdown: ...` is the tell.
3. The master key lands in **SYSTEM's** credential store and survives a
   service restart.
4. A real share opens for LocalSystem with a real `shareCredentials`
   row.
5. **The reboot with nobody signed in.**
6. A tray click that stops and starts the service with no UAC prompt.

Everything below is what could be decided without a service.

---

## 1. Step one was a measurement, and it came back no

The roadmap made this slice conditional: *can a LocalSystem service open
this install's models?* It expected the failure mode to be "the machine
account is not authorised on the share". **It is not that**, and the
difference is the whole shape of what got built.

    Get-SmbClientConfiguration  EnableInsecureGuestLogons : False   (Win11 default)
    cmdkey /list                Domain:target=192.168.16.252 / tcorbin
    Get-LocalUser troyc         PrincipalSource : MicrosoftAccount
    Win32_ComputerSystem        PartOfDomain    : False

    \\192.168.16.252\downloads\models   OK, 1 entry
    \\CORBIN01\downloads\models         OSError winerror=1272
      "...security policies block unauthenticated guest access."
    WNetAddConnection2W(no creds)  -> 1272
    WNetAddConnection2W(bad creds) -> 1272

`CORBIN01` is the same server (`nbtstat -A 192.168.16.252`) under a name
this logon session has no SMB session for — the closest reachable
stand-in for an uncredentialed one.

So: the share is **guest-open**, it is **Windows 11 that refuses**, the
box is a **workgroup** member with no machine account, and the only
thing bridging the gap is a per-user Credential Manager entry. The
roadmap's conditional fired — *"the slice is about credentials rather
than about a service"* — and check 1 of the run reproduces it.

**And it generalises past this box.** Any Windows client at default
settings plus any NAS share, public or private, needs a credential held
by whatever logon session the agent runs in.

---

## 2. The finding with the longest reach: FOUR per-user things, not one

Only one was on the roadmap. Name the pattern rather than the
instances — **a LocalSystem service has none of the user's secrets, and
this install keeps three of them in the user's profile:**

| what | where it lives | if unhandled |
| --- | --- | --- |
| `EUGENE_PLEXUS_AGENT_CONFIG_FILE` | `HKCU\Environment` (User scope; Machine scope holds **no** `EUGENE_PLEXUS_*` at all) | the service finds no `agent.yaml` and **raises a second install** |
| the master key | Credential Manager, per Windows user | the install comes back **sealed** with every health check green — the container symptom of 2026-09-12 again |
| the SMB credential | Credential Manager | §1: `WinError 1272`, no models |
| `Y:` / `Z:` | the interactive session | **already handled**: no drive letter appears in any yaml or json under the live prefix |

The first is the installer's, the second is one sign-in after migrating
(`routes/auth.py` re-seals on every successful unlock, so it is
self-healing after once), and the third became `shareCredentials`.

---

## 3. §0.3: the 2026-09-11 cost was asserted, never measured, and is false

`install-paths-and-distribution.md` §7 lists *"Real service +
`AllocConsole()`"* with the cost *"can reassign the agent's std handles
— logs vanish"* and concludes *"we do not conjure a console"*. **That
decided a product limitation for seven days on an unmeasured premise.**

Three arms, each in its own process, child spawned with
`CREATE_NEW_PROCESS_GROUP` and a SIGBREAK handler:

    ARM A  inherited console            signalled, child out in 0.034 s
    ARM B  after FreeConsole()          WinError 6, never signalled
    ARM C  after FreeConsole()+Alloc    signalled, child out in 0.036 s

Arm B is the negative control and reproduces the documented failure
exactly, so arm C means something. And the rejected cost does not
materialise: the `RotatingFileHandler` keeps writing, `print` and
`sys.stderr.write` do not raise. It was never going to — the durable
sink is a file, children are `stdout=PIPE`, and under pywin32's host
`sys.__stdout__` is already `None`.

**So the service no longer costs the graceful stop**, and
`install-paths` §7's table row is wrong in its cost column.

---

## 4. Two live defects found by reading, neither on the roadmap

**The three-second wait in both restart branches does not exist**, and
it is live on `logon_task` today rather than only on the branch R2.6
lights up:

    cmd /c "timeout /t 3 /nobreak >nul & echo done"   0.18 s, rc 125
    cmd /c "ping -n 4 127.0.0.1 >nul"                 3.17 s

`timeout` refuses to run without a console input handle and
`spawn_restart` passes `stdin=DEVNULL`. So `sc start` was issued ~0.18 s
after `sc stop`, against a `SvcStop` that may take 90 s — and the
helper's output goes to DEVNULL, so a refused start was
indistinguishable from a working restart.

**▶ And the obvious fix is a worse trap.** `Restart-Service` waits for
you, which makes PowerShell tempting. Measured, one flag at a time:

    no creationflags            2.16 s  rc=0  'done'
    CREATE_NEW_PROCESS_GROUP    2.17 s  rc=0  'done'
    DETACHED_PROCESS            0.05 s  rc=0  ''      <-- never ran
    DETACHED|NEW_PROCESS_GROUP  0.05 s  rc=0  ''      <-- never ran

`DETACHED_PROCESS` — which `spawn_restart` must pass, so the helper
outlives the agent it restarts — makes `powershell.exe` exit
immediately, successfully, having done nothing. **A silent no-op that
still reports success** is precisely the failure being fixed.

So the start itself is the probe, retried on a widening pacer: `sc
start` fails while the service is STOP_PENDING, so a start that
*succeeds* proves the stop finished. Measured against a stand-in that
fails a chosen number of times: **0.01 s** when the first attempt takes,
**2.13 s** for the second, **7.31 s** for the third. Nothing waits that
does not need to.

**`-Detect` closed the operator's terminal.** `install.ps1:344` was
`exit 3`, against the rule stated forty lines above it. `-Detect` is
only reachable as `& ([scriptblock]::Create((irm ...))) -Detect`, which
runs in the caller's process — so it ended the session in exactly the
case it exists to report. Check 8 runs it as a scriptblock and asserts
the caller survived.

---

## 5. The run

```
0.  isolation                    2 PASS
1.  the share refuses an uncredentialed session (WinError 1272)
2.  the three-arm console experiment
3.  the restart helper: no `timeout`, no PowerShell, retried
4.  session 0 is a precondition, not the answer
5.  shareCredentials                                       9 PASS
6.  the tray against this box's real SCM ('unknown', correctly)
7.  install.ps1: ASCII, parses, service by default, elevates,
    sdset, tray task                                       7 PASS
8.  -Detect returns to its caller (SURVIVED exit=3)
9.  every pin resolves; the pinned UI archive carries the build;
    both installers agree                                  3 PASS
10. teardown by pid
```

**Check 9's UI half fetches the ARCHIVE and greps it**, not the working
tree. S10 clicked a 16 GB download because a merged, tested UI fix had
reached no build; fetching what the installer will fetch is the only
form of that check which cannot pass silently.

---

## 6. The sabotage pass

**26 sabotages, 25 caught.** Two escaped on the first pass.

**One escape is expected and recorded rather than patched over.**
`console-ordering` — the service allocating its console *after*
`build_server` instead of before — is not observable from a unit test:
`SvcDoRun` needs a real SCM to run at all. A test that asserted the
source text would look like coverage and be none. It is check 2 of the
elevated list instead.

**▶ The unexpected escape named a check that could not fail, and it is
R2.2's own lesson repeated.** `installer-no-sdset` deleted the
`Grant-ServiceControl` **call** and the check still passed, because it
grepped for `sc.exe sdset` — a string that lives inside the function
*definition*. **A check that matches a NAME is not a check.** It now
asserts both halves, and the call site is the one that can be deleted by
accident.

---

## 7. Four harness defects, over four executions

Every one of them reported a working product as broken, which is the
cheaper direction and still worth writing down.

1. **pytest cannot read an MSYS path.** `-m pytest /d/py/...::test_name`
   is "file or directory not found", so the console experiment reported
   *did not pass* for a test it never ran.
2. **Backticks inside a double-quoted bash string are command
   substitution.** The success message `no \`timeout\`, no PowerShell`
   **ran `timeout`**, pasted its usage into the report, and printed
   "no , no PowerShell" — while passing.
3. **The pin comparison matched the wrong hashtable.** `install.ps1` has
   `$PIN` and `$DIST` with identical keys, so a grep on the key alone
   found the package name and reported every pin as disagreeing with
   itself.
4. **▶ AND THIS BASH'S QUOTED HEREDOCS EAT BACKSLASHES.** `<<'PY'` is
   supposed to be literal and is not: `\\n` arrives as `\n`, and
   `r"\\192.168..."` arrives with one backslash. It cost three separate
   bugs this session — a probe that could not find the share, a test
   whose generated child was a syntax error, and a shell continuation
   that became the argument `n`. **Write files with the editor, not with
   a heredoc, wherever backslashes are involved.**

And one finding that is about Python rather than the harness: **a long
`time.sleep()` on Windows is not interrupted by `SIGBREAK`**, only by
`SIGINT`. The console experiment's first child slept 30 s in one call
and reported *never signalled* for a child that had been signalled
perfectly well. Short sleeps in a loop; a real engine has its own
handler and does not care.

---

## 7a. The gap the question found, 2026-09-19

Troy, reading §8's *"stopping the service frees the card and takes the
UI with it"*: **"does it register as a Program the user can run again
from the Start menu, since the UI goes with it?"**

**It did not**, and that made the tray's own *Hide this icon* a
**one-way door**. The tray process survives a service stop — it is in
the user's session, which is what session 0 isolation forces — so the
common path was fine. Every path where the icon was gone was not: hide
it, or `-NoTray`, or a second Windows user, and the routes back were
`services.msc`, an elevated `Start-Service`, or signing out and in. The
URL the installer prints answers *connection refused*, **because
stopping Eugene is what took the page away**.

Fixed (`agent` `f14ec87`, `specs`):

* **A Start menu entry, "Eugene Plexus"**, All Users for a service
  install. It passes `--open`: start the service if stopped, wait for
  `/healthz`, then open the browser. One entry covers *I want Eugene*
  and *give me my icon back* without the person having to know those are
  different questions.
* **`sc start` returning success is not the thing to wait for.** It
  means the SCM accepted the request while the agent still has to load
  its config, recover its key and bring up four children. Opening then
  shows connection refused, which reads as *broken* rather than
  *starting* — and it is the first impression after clicking a Start
  menu entry.
* **A session-local single-instance mutex.** Without it the entry whose
  job is to bring the icon *back* adds a second one beside it every
  click. The open action deliberately runs **before** the instance
  check, because an icon already in the tray is exactly the state
  somebody clicks the entry in.
* **The label names its own undo:** *"Hide this icon (it is in your
  Start menu)"*.

Five sabotages, five caught; four acceptance checks added (32 PASS).
**Still unverified:** no shortcut has been created or clicked — that is
elevated, and joins the six in §0.

## 8. What is not done, named

* Everything in §0 — six checks, Administrator and a reboot.
* **The tray icon has never been drawn.** Everything decidable about it
  is tested; `_tray_window.run_message_loop` needs a desktop and a
  registered service, and nothing here has either.
* **`Show-MigrationConsequences` has never run against a real
  migration.** Its refusal path is asserted by the sabotage pass; the
  path where somebody passes `-Migrate` and the install actually moves
  is Troy's.
* **Linux and macOS have the identical defect and are out of scope.**
  `install.sh` writes a `--user` systemd unit and a
  `~/Library/LaunchAgents` plist; both die at logout exactly as the
  Windows task did, and `install.sh:561-568` warns about lingering
  rather than enabling it. If the premise is *the promise is the
  requirement*, the sentence is untrue on all three platforms. Windows
  was scheduled because Windows is where the beginner is.
* **The tray cannot free the GPU without stopping the control plane.** A
  finer *"unload the models, keep serving"* needs a credential a
  long-lived unattended process in a user session should not hold — an
  operator session token on disk, or widening what an `aud: client` key
  may do three slices after R2.4 narrowed exactly that. Stopping the
  service frees the card, which is what was asked for; the finer version
  is a real slice someone may want.
