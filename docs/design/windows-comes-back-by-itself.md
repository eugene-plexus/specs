# R2.6 — Windows comes back by itself

*Design for `release-roadmap.md` §3.6. Written 2026-09-18, after the slice's
first step — a measurement — came back with an answer the step did not
anticipate.*

**The promise is the requirement.** The default Windows install is a scheduled
task with `-AtLogOn` and no `-Principal`: it dies at sign-out, dies at a user
switch, and never starts after a reboot that lands on the lock screen. Nobody
signs in at 4 am after a Windows update, so the phone gets *connection refused*
and no screen explains it. Decision #4 (Troy, 2026-09-18) is that the mechanism
changes rather than the copy — see
[[dont-edit-copy-to-meet-a-gate]].

---

## 0. Measurements, and the two premises they falsified

Every number here was taken on `AMISH_STATION` on 2026-09-18, in an
**unelevated** session. Where a measurement needs Administrator it says so and
is not claimed.

### 0.1 The box

    user             AMISH_STATION\troyc
    PrincipalSource  MicrosoftAccount     <-- an MSA password changes online
    domain-joined    False (WORKGROUP)    <-- so there is no machine account
    service          none registered      <-- no %ProgramData% install exists
    task             \EugenePlexusAgent, LogonTrigger, LogonType InteractiveToken,
                     no <RunLevel>, no <BootTrigger>

### 0.2 ▶ Step 1 answered NO, and not for the reason step 1 gave

The roadmap asked: *can a LocalSystem service open this install's models?* It
expected the failure mode to be "the machine account is not authorised on the
share". It is not that.

    Get-SmbClientConfiguration  EnableInsecureGuestLogons : False   <-- Win11 default
                                RequireSecuritySignature  : True

    cmdkey /list                Target: Domain:target=192.168.16.252
                                Type:   Domain Password
                                User:   tcorbin            <-- in TROYC's profile

`\\CORBIN01\...` is the same server as `\\192.168.16.252\...` (`nbtstat -A`
confirms `CORBIN01 <20>`) under a name this logon session has no SMB session
for — the closest stand-in for a fresh, uncredentialed one that can be arranged
without elevation:

    \\192.168.16.252\downloads\models   OK, 1 entry ['huihui-ai']
    \\CORBIN01\downloads\models         OSError winerror=1272
      "You can't access this shared folder because your organization's
       security policies block unauthenticated guest access."

    WNetAddConnection2W(bad creds) -> 1272
    WNetAddConnection2W(no creds)  -> 1272
    net use \\CORBIN01\downloads /user:"" ""
       -> "The password is invalid", then prompts for a user name

So the UnRAID share is **guest-open** — it asks for nobody in particular — and
it is **Windows 11 that refuses the guest fallback**. The only thing bridging
the gap is a per-user Credential Manager entry. A LocalSystem service has its
own credential store and does not have it, and a workgroup box has no machine
account to fall back on either.

**The roadmap's conditional fires:** *"if the answer is no, the slice is about
credentials rather than about a service."* And it generalises well past this
box — any Windows client at default settings, plus any NAS share, public or
private, needs a credential held by **whatever logon session the agent runs
in**.

### 0.3 ▶ Step 3 answered YES, and it overturns a decision from 2026-09-11

`install-paths-and-distribution.md` §7 carries this row:

    | Real service + AllocConsole() | yes | works | can reassign the agent's
    |                              |     |       | std handles — logs vanish |

followed by *"We do not conjure a console: an agent whose logs disappear is a
worse outcome than a hard kill."* **That cost was asserted and never measured.**

`scripts/r26-console-experiment.py`, three arms, each in its own process, child
spawned with `CREATE_NEW_PROCESS_GROUP` and a `SIGBREAK` handler:

    ARM A  inherited console (the logon task today)
           GenerateConsoleCtrlEvent -> True   child exit=7 after 0.034s  SIGNALLED
    ARM B  after FreeConsole()  (the service as it stands)
           GenerateConsoleCtrlEvent -> False  WinError=6   child NEVER EXITED
    ARM C  after FreeConsole() + AllocConsole()
           AllocConsole -> True
           GenerateConsoleCtrlEvent -> True   child exit=7 after 0.036s  SIGNALLED

Arm B reproduces the documented `WinError 6` exactly, so the experiment's
negative control holds. **Arm C works at arm A's latency.** And the rejected
cost does not materialise: after `FreeConsole()` + `AllocConsole()` the
`RotatingFileHandler` keeps writing and neither `print` nor `sys.stderr.write`
raises.

It was never going to. The agent's durable sink is a file handler
(`console_logging.py:143-148`), children are `stdout=PIPE, stderr=STDOUT`
(`supervisor.py:789-790`), and under pywin32's host `sys.__stdout__` is already
`None` — a case `console_logging.py:168-175` handles today. A session-0 console
is invisible and valid, which is all `GenerateConsoleCtrlEvent` needs.

**Unverified, and it needs Administrator:** all three arms ran in an
interactive session. A real service runs in **session 0**, and `AllocConsole()`
there is the one thing that has to be confirmed from inside a registered
service. §7 says how.

### 0.4 The service loses FOUR per-user things, not one

This is the finding with the longest reach, and only one of the four was on the
roadmap. Everything the install keeps in the user's profile becomes invisible
the moment the agent runs as LocalSystem:

| what | where it lives now | what a LocalSystem service sees | consequence if unhandled |
| --- | --- | --- | --- |
| `EUGENE_PLEXUS_AGENT_CONFIG_FILE` | `HKCU\Environment` (**User** scope; Machine scope has no `EUGENE_PLEXUS_*` at all) | nothing | resolves its own default path, finds no `agent.yaml`, **raises a second install** — a fresh trust root, a fresh wizard, `Amish_Station`'s enrollment orphaned |
| the master key | Credential Manager, `master-key:<salt fp>@eugene-plexus-agent`, **per Windows user** | nothing | the install comes back **sealed** with every `/healthz` green — the container symptom of 2026-09-12 in a new disguise |
| the SMB credential | Credential Manager, `Domain:target=192.168.16.252` | nothing | §0.2: `WinError 1272`, no models |
| `Y:` / `Z:` | interactive session drive mappings | nothing | **already handled** — `grep` over every yaml/json under the prefix finds no drive letter; the live config carries the UNC form, which is what the 2026-09-15 "clear Amish's override, set the folder's Windows mount" change bought. Documented, not fixed. |

**Name the pattern rather than the four instances: a LocalSystem service has
none of the user's secrets, and this install keeps three of them in the user's
profile.** Anything added later that reaches for a per-user store has the same
problem, so §3 answers it per store and not per symptom.

### 0.5 Two live defects found while reading, neither on the roadmap

**`reach.restart_argv`'s three-second gap does not exist.** Both Windows
branches emit `cmd /c <stop> & timeout /t 3 /nobreak >nul & <start>`, and
`spawn_restart` passes `stdin=subprocess.DEVNULL` (`reach.py:590`). `timeout`
refuses to run without a console input handle. Measured:

    cmd /c "timeout /t 3 /nobreak >nul & echo done"   DETACHED, stdin=DEVNULL
      -> elapsed 0.18s, rc 125, stdout 'done'
    cmd /c "ping -n 4 127.0.0.1 >nul"                 same flags
      -> elapsed 3.17s

So the start is issued ~0.18 s after the stop, while `SvcStop` allows the
uvicorn thread up to 90 s (`winservice.py:160`). This is **live on the
`logon_task` branch today**, not only on the service branch R2.6 lights up.

**`-Detect` closes the operator's terminal.** `install.ps1:344` is
`if (-not $clean -and -not $Migrate) { exit 3 }`, against the file's own rule at
:103-105 (*"every early return below is `return`, never `exit` — `exit 0` inside
a scriptblock ends the host session too"*). `-Detect` is only reachable as
`& ([scriptblock]::Create((irm ...))) -Detect`, i.e. in the caller's process, so
it ends the session in exactly the case it exists to report.

### 0.6 What is already built, and is not what the roadmap assumed

- **`Mechanism.service` is already in the contract** (`agent.yaml:2331`) and
  already returned by `reach.py:237-243`. R2.6 adds no enum member.
- `winservice.py` already registers, already stops the agent gracefully
  (`SvcStop` → `should_exit` → the ASGI lifespan shutdown runs), and already
  refuses unelevated with a sentence.
- `install.ps1` already has the elevated service branch, `-Detect`, `-Migrate`
  and `Get-OtherInstall`'s three discriminators (R2.2).
- What `-Migrate` does **not** do is migrate any state: it takes the autostart
  over and leaves `agent.yaml`, `node.yaml`, the keyring entry, the models
  folder and the engine store at the old prefix.

---

## 1. The shape

**The agent runs as a LocalSystem Windows service, and that is what an ordinary
Windows install gets.** The installer elevates itself once.

**The logon task does not disappear. It changes job.** It stops starting the
agent — which now boots without anyone — and starts the **tray icon**, which is
the one thing that genuinely belongs in a person's own session. Session 0
isolation has forbidden a service from showing UI since Vista, so a tray icon
was never going to be part of the service; the mechanism we are replacing for
the agent turns out to be exactly right for the icon.

    boot ──> SCM ──> EugenePlexusAgent (LocalSystem, session 0)
                       AllocConsole()  ──> engines stop gracefully
                       components, engines, the UI at :8079

    sign-in ──> logon task ──> eugene-plexus-tray (your session)
                       Open Eugene · Release the GPU · Stop · Start

**Why the tray, in Troy's words (2026-09-18):** *"many users with RTX graphic
cards will want to turn Eugene off easily to play a video game, and then turn it
back on to infer again."*

That is a request about **VRAM**, and stopping the whole control plane is a
blunt way to free it — it also takes the UI, the gateway and every other
machine's view of this node. So the tray offers both, and the cheap one is the
prominent one:

- **Release the GPU** — stop every runtime on this node (`POST
  /v1/runtimes/{name}/stop`, which since M6 is a supervised stop the gateway
  already understands). The control plane stays up, the UI stays reachable, and
  one click brings a model back. Instant, reversible, no elevation.
- **Stop Eugene** / **Start Eugene** — the whole service, via the SCM.

---

## 2. Decisions, with the argument and the counter-argument

| # | Question | Decision | Why, and what it costs |
| --- | --- | --- | --- |
| 1 | Service as LocalSystem, or a boot task running as the user with a stored password? | **LocalSystem service** | A stored-password task would keep all three per-user secrets for free, which is a real argument and the reason §0.4 exists. It loses on one measured fact: `troyc` is a **MicrosoftAccount**. An MSA password changes online, from a phone; the LSA copy the task holds does not follow, and the next boot fails with a logon error that no screen in this product can explain. A mechanism whose failure mode is silent and remote is not one to make the default. LocalSystem has no password to rot. |
| 2 | Does the installer elevate itself? | **Yes, once, unless `-NoService`** | `SC_MANAGER_CREATE_SERVICE` is granted to nobody else, so "the service is the default" and "no Administrator needed" cannot both be true. R2.2 made re-running elevated safe (it refuses to strand the first install), which is what makes a self-elevating installer honest rather than the trap #10 described. `-NoService` keeps a fully unelevated path for anyone who wants one. |
| 3 | The master key, on a **fresh** service install | **`os_keyring` into SYSTEM's vault** | It works unattended, which is the whole requirement. What it costs is that the operator cannot inspect or recover the entry, and the uninstaller's keyring drop (run as the invoking user) will not find it — so the uninstall drop runs as the service's own account. `passphrase_file` would be inspectable and **the agent does not have it** (it is a control-only mode; `SecurityMode` missing `passphrase_file` is already an R3 item). Not worth blocking R2.6 on. |
| 4 | The master key, on a **migrated** install | **It comes back sealed, once, and the installer says so before it happens** | The key is in troyc's vault; SYSTEM cannot read it, and there is no supported way to write another account's vault from the installer. But the recovery already exists and is one step: `routes/auth.py:355` re-seals into the keyring on every successful unlock, so signing in once after the migration writes the key into SYSTEM's vault and every boot after that is unattended. S7's Issues badge already surfaces a sealed root from any page. **Refusing to migrate silently is the defect; migrating loudly is not.** |
| 5 | The SMB credential | **The agent holds it, per server** (Troy, 2026-09-18) | §3.2. The unit is the **server**, not the share: Windows refuses a second credential to a server it already has a session with (`ERROR_SESSION_CREDENTIAL_CONFLICT`, 1219), so a per-share credential would be a field that cannot always be honoured. |
| 6 | `AllocConsole()` in the service | **Yes** | §0.3. It restores the graceful engine stop at the same latency as a console-owning agent, and the 2026-09-11 cost that ruled it out is measurably false. The honest residual is that session 0 is unverified — §7. |
| 7 | Where the tray lives | **The `agent` repo, `[tray]` extra, a per-user logon task** | It is not a component (`ComponentKind` has four values and this is not one), it is not a repo (it has no responsibility of its own — it is a remote control for the agent's own API plus the SCM), and it must run in the user's session. `pywin32` is already the `[service]` dependency, so `Shell_NotifyIcon` costs nothing new. |
| 8 | How the tray stops a service without a UAC prompt | **`sc sdset` at install, granting the installing user start/stop on this one service** | The alternative is a UAC prompt per click, which fails the "easily" in the request. Granting `RP` (start) and `WP` (stop) on a single service to a single account is the targeted form; it is not `SeServiceLogonRight` and it is not machine-wide. |
| 9 | Linux and macOS | **Out of scope, named, not fixed** | `install.sh` writes a `--user` systemd unit and a `~/Library/LaunchAgents` plist — both die at logout exactly as the Windows task does, and `install.sh:561-568` already *warns* about lingering rather than enabling it. If the premise is *the promise is the requirement*, the sentence is untrue on all three platforms. Windows is scheduled because Windows is where the beginner is; the other two get a roadmap row, not a silent pass. |

---

## 3. What each piece is

### 3.1 The console (`agent`)

`process_signals.ensure_console()` — Windows only, idempotent, returns what it
did. Called from `winservice.SvcDoRun` **before** `build_server`, because
`spawn_kwargs` sets no console flag and a child inherits whatever the parent has
at spawn time; a console allocated after the first child is a console that child
is not in.

Nothing else changes. `console_attached()` starts returning True on its own,
`describe_stop_capability()` stops printing the hard-kill badge, and
`request_stop`'s `os.kill(pid, CTRL_BREAK_EVENT)` starts working — which is the
point: the fix is one call, and every surface that reports on it is already
wired to the truth.

The badge string for the console-less case **stays**, because it is still the
truth for anything that reaches that state another way.

### 3.2 Share credentials (`agent`, contract, `ui`)

A new per-node config field, beside `pathMappings` under **Library**:

    shareCredentials:
      - host: 192.168.16.252
        username: tcorbin
        password: <secret>

`ConfigValueType.share_credentials` in `common.yaml`, `ShareCredential` beside
`PathMapping`. The password is redacted in `GET /v1/config` and accepted in
`PATCH`, which is what the existing `secret` type already promises for scalars —
the list form needs the same rule stated per entry.

**Per node, not per folder**, and that is the `library-folders-and-reach` shape
rather than a departure from it: a folder states its mounts once because the
mount is a property of the share; a credential is a property of *this machine's
relationship to* the share, which is what `pathMappings` already is. Cross-linked
both ways with the folder's mounts, per
[[cross-link-related-settings]].

The agent calls `WNetAddConnection2W` for each entry at startup and after any
PATCH, before anything opens a model. Children inherit the agent's logon session,
so `llama-server` sees the authenticated session without knowing it exists.
Error codes are named rather than numbered — 1272 is *"Windows refused an
unauthenticated connection; this share needs a user name"*, 1326 is *"the user
name or password was not accepted"*, 1219 is *"Windows already has a different
connection to this server"*.

### 3.3 `reach.py` (`agent`)

Three changes, and the first is the S5 lesson on the branch it was never applied
to:

1. **Session 0 becomes a precondition, not the answer.**
   `_running_as_windows_service()` asks only *am I in session 0*, which is
   equally true of a SYSTEM-principal scheduled task, `PsExec -s`, and **another
   install's service**. A new `_windows_service_runs_this_install()` reads the
   service's `ImagePath` and passes it to the existing
   `action_runs_from_prefix(path, sys.prefix)`. Measured and it lands correctly
   with no new comparison logic: `win32serviceutil.LocatePythonServiceExe` puts
   the host exe at `os.path.join(sys.exec_prefix, "pythonservice.exe")`, which in
   a venv is `<sys.prefix>\pythonservice.exe` — inside the prefix. Readers in
   preference order: `QueryServiceConfig` via pywin32, then
   `HKLM\SYSTEM\CurrentControlSet\Services\<name>\ImagePath` via `winreg`, which
   needs no dependency and is readable unelevated.
   `_running_as_windows_service` has **no test at all** today, which is why the
   gap has never been asserted either way.
2. **The restart actually waits.** §0.5. Poll the SCM for `SERVICE_STOPPED`
   rather than sleeping a number, bounded by the same 90 s `SvcStop` allows.
3. **`detail` on the service branch**, which today has none: *"This agent starts
   at boot, before anyone signs in."* That is the sentence R2.6 exists to make
   true, and §3.5 is what puts it on a screen.

### 3.4 `install.ps1` (`specs`)

- Self-elevate unless `-NoService`; `-NoService` keeps today's unelevated path.
- The service is registered on the ordinary path; `%ProgramData%` is the prefix.
- **Migration** (`-Migrate`), which today moves nothing: move the prefix, rewrite
  `EUGENE_PLEXUS_AGENT_CONFIG_FILE` from User to Machine scope, carry `node.yaml`
  so the enrolled identity survives, carry the model-copy directory setting, and
  **say in advance** that the first start will be sealed and why (decision #4).
- `sc sdset` granting the installing user start/stop.
- Register the tray as the per-user logon task, under the name the agent's task
  used to have — with a different task name, because `$TaskName -eq $ServiceName`
  today and the tray is not the agent.
- A working directory for the service: the comment at :723-724 promises one and
  no code sets it, and `sc` has no knob for it, so it is an `os.chdir` in
  `SvcDoRun`.
- Fix `exit 3` → `return 3` (§0.5).

### 3.5 The tray (`agent`)

`eugene_plexus_tray`, console script `eugene-plexus-tray`, `[tray]` extra.
`Shell_NotifyIcon` via pywin32, one hidden message window, no event loop of its
own beyond `PumpMessages`. It talks to the agent over `127.0.0.1` with a client
key — **not** an operator session: the tray is a long-lived unattended process in
a user session, which is exactly what S4's `aud: client` keys are for, except
that a client key is only accepted on the gateway's three OpenAI paths. So the
tray holds an **operator** credential and that is a real cost; §8 records it as
the open question it is.

### 3.6 `ui`

Render `restart.detail` and `restart.mechanism` — the fixture at
`page.test.tsx:599` supplies `mechanism: "logon_task"` and nothing asserts it,
which is the wiring lesson again. And the wizard's sentence: the mechanism
change makes *"comes back working without you"* true about the process, and the
same edit has to keep it true about the key, because "your OS's password
manager" is now **SYSTEM's**, not yours.

---

## 4. Done when

Unchanged from the roadmap, and none of it is reachable from a non-interactive
harness:

1. A Windows box with nobody logged in reboots and serves a completion.
2. An existing per-user install is migrated rather than stranded.
3. The wizard's sentence is true **without having been edited to fit**.

---

## 5. Build order

1. The console (`agent`) — smallest, measured, and it removes a documented
   product cost.
2. `reach.py` — install-scoped detection, the real wait, the `detail`.
3. Contract — `common.yaml` + `agent.yaml`.
4. Share credentials (`agent`).
5. `install.ps1` — service default, elevation, migration, `sc sdset`, the tray
   task.
6. The tray (`agent`).
7. `ui` — render the mechanism, correct the wizard.
8. `scripts/r26-acceptance.sh`, `scripts/r26-sabotage.py`, docs, pins.

---

## 6. Implementation record

**Built 2026-09-18.** `scripts/r26-acceptance.sh` **25 PASS, zero
failures, fifth execution**; `scripts/r26-sabotage.py` **26 sabotages,
25 caught**; record
[`../acceptance/windows-service-run.md`](../acceptance/windows-service-run.md).

| repo | commit | what |
| --- | --- | --- |
| `specs` | `dfe6b67` | `ShareCredential` + `ConfigValueType.share_credentials` in `common.yaml`; `shareCredentials` and the Windows-service prose in `agent.yaml`; `AgentRestart.detail` finally has a description — it was the one property of that schema with none |
| `agent` | `51d1c8a` | `process_signals.ensure_console`, `winservice` calling it before the first child plus `_chdir_to_prefix`, `share_credentials.py`, `reach.py`'s install-scoped service check and its real wait, `tray.py` + `_tray_window.py` |
| `ui` | `e98ed30` / dist `14f9073` | `startsWhen` on the Reach card, the `share_credentials` editor, the wizard's verb |
| `control`, `gateway`, `library`, `inference-driver` | `5cbf536`, `25128f1`, `a43a7f4`, `9001722` | regen-only; the `ConfigValueType` member reaches every consumer through `ConfigField`, the M11 rule |

All six pinned level at `dfe6b67`; both installers re-pinned and every
archive verified to resolve, with the UI one unpacked and grepped so the
`dist` trap cannot have happened silently.

**Build order as it actually went**, and it differs from §5 in one
place: the contract was committed and pushed **before** the agent
implementation, because `ShareCredential` is a generated model and
`codegen.py` fetches a GitHub archive at a SHA. Publish → bump → regen →
implement, not implement → contract.

### Where the slice departed from this design

* **§3.2 said the agent's config validator would check shape only, and
  it does — but the validator also has to accept the SEALED form.** It
  sees the value on the way in (a typed string) *and* on the way out of
  the file (an envelope). Refusing the envelope would have made the
  agent write a config it could not load, which is the worst of the
  three failures available because it appears only on the next start.
* **§3.5 said the tray would hold an `aud: client` key.** It holds
  nothing. A client key is accepted only on the gateway's three OpenAI
  paths, so using one here would mean widening what that audience may
  do — three slices after R2.4 spent itself narrowing exactly that. The
  tray drives the SCM instead, which needs no Eugene credential at all,
  and the cost is that *"unload the models but keep serving"* is not on
  the menu. §8.
* **The migration refuses rather than proceeding.** §3.4 said
  `-Migrate` would carry state; what it does is **print the two
  consequences and refuse without `-Migrate`**. A first-time upgrade on
  any existing Windows box now reads as *a DIFFERENT install* —
  correctly, because the prefix moved — and the verdict's advice leads
  with `-Migrate` for exactly that case.

---

## 7. What needs Administrator, and cannot be claimed until it runs

The session that wrote this was **unelevated**, which is the same sentence
`winservice.py` has carried since 2026-09-11. What that leaves open:

1. `AllocConsole()` **in session 0**, from inside a registered service, and a
   real `llama-server` exiting on `CTRL_BREAK_EVENT` under it. §0.3 measured the
   mechanism in session 1; this measures it where it ships.
2. `keyring` writing to and reading from **SYSTEM's** vault.
3. `WNetAddConnection2W` from LocalSystem with a real credential against the
   live share.
4. The migration, end to end, on the live install.
5. The reboot with nobody logged in — Done-when #1.
6. `sc sdset` and a tray click that starts and stops the service with no UAC
   prompt.

---

## 8. What is open

* **The six checks in §7.** They are the *Done when*, and they need
  Administrator and a reboot.
* **The Start menu entry has never been created or clicked.** Added
  2026-09-19 after Troy asked whether stopping Eugene left any way back
  (it did not — see the record's §7a). `Add-StartMenuShortcut` uses
  `WScript.Shell`, which needs a desktop session to write a `.lnk`, and
  the elevated path writes to All Users. Check 6 of §7 covers it.
* **The tray icon has never been drawn.** Everything decidable about it
  is tested — the menu, the tooltip, the SCM read, the refusals;
  `_tray_window.run_message_loop` needs a desktop and a registered
  service.
* **The tray cannot free the GPU without stopping the control plane.**
  Stopping the service frees the card, which is what was asked for, and
  it also takes the UI and this node's place in the install. A finer
  *"unload the models, keep serving"* is one `POST
  /v1/runtimes/{name}/stop` per runtime and needs a credential a
  long-lived unattended process in a user session should not hold. The
  honest options are a narrow new audience or a route that accepts
  `aud: client`; both are a slice, and neither should be decided as a
  side effect of a tray icon.
* **`Show-MigrationConsequences` has never run against a real
  migration.** Its refusal is sabotage-checked; the path where somebody
  passes `-Migrate` and the install actually moves is Troy's.
* **Linux and macOS.** `install.sh` writes a `--user` systemd unit and a
  `~/Library/LaunchAgents` plist. Both die at logout exactly as the
  Windows logon task did, and `install.sh` already *warns* about
  `loginctl enable-linger` rather than doing it. **If the premise is
  *the promise is the requirement*, the wizard's sentence is untrue on
  all three platforms and only one has been fixed.** Named here so it is
  a decision rather than an oversight.
* **`_RESTART_PACES` sums to ~37 s against a `SvcStop` that allows 90.**
  A stop that takes longer than the last pacer leaves the service
  stopped, and the helper's output goes nowhere. Bounded on purpose —
  supervised children escalate concurrently at 5 s each — but it is a
  number chosen rather than measured against a real service stop, which
  is check 1 of §7.
