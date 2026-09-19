#!/usr/bin/env bash
# R2.6 -- Windows comes back by itself.
#
# Roadmap: docs/design/release-roadmap.md §3.6. Design:
# docs/design/windows-comes-back-by-itself.md. Finding: review §6.2 #26
# (the wizard promises an autostart the default lacks), plus two defects
# this slice found while reading -- a three-second wait that never
# happened, and a `-Detect` that closed the operator's terminal.
#
# ▶ WHAT THIS RUN CANNOT DO, SAID FIRST BECAUSE IT IS MOST OF THE POINT.
#
# The slice's *Done when* is "a Windows box with nobody logged in
# reboots and serves a completion". That needs Administrator and a
# reboot, and this harness has neither: `SC_MANAGER_CREATE_SERVICE` is
# granted to nobody but Administrators, and nothing non-interactive can
# reboot a machine and not sign in. Six checks are owed and are listed
# in `install.ps1 -Verify` and in §7 of the design. They are Troy's to
# run, elevated, on a box he is willing to restart.
#
# What is left is still worth running, and it is everything that can be
# decided without a service: the credential half (which is what step
# one's measurement turned this slice into), the console measurement in
# session 1, the restart command's shape, the installer's own decisions,
# and whether the pinned archives carry what was built.
#
# The checks:
#   0. isolated from the live install and from its ports
#   1. §0.2 REPRODUCED: an uncredentialed session cannot open the share
#   2. §0.3: a console-less parent that allocates one stops its child
#      gracefully -- with the negative control that says the arm means
#      something
#   3. the restart command reaches for neither `timeout` nor PowerShell,
#      both of which were measured to do nothing detached
#   4. the service branch says what a service means, and session 0 alone
#      does not make it this install's service
#   5. `shareCredentials` exists, redacts, and survives the round trip
#      that would otherwise blank it
#   6. the tray reads the real SCM and greys what cannot apply
#   7. install.ps1 parses, is pure ASCII, and defaults to a service
#   8. `-Detect` reports without ending the session that ran it
#   9. every pinned archive resolves, and the UI one carries the build
#  10. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped, ports are +100, state is a throwaway, teardown is by pid.
# Never `pkill -f eugene_plexus_`: this box is a worker node.
#
# **And it registers no service and unregisters none.** A harness that
# touched the SCM on this box would be the S5 note all over again --
# a throwaway agent reaching for the live install's supervisor.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-r26}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
AGENT="http://127.0.0.1:$AGENT_PORT"
OWNED_PORTS="$AGENT_PORT"
PASS="r26-acceptance-passphrase"
# The live install's own NAS, under a name this logon session has no SMB
# session for -- the closest stand-in for an uncredentialed one that can
# be arranged without elevation. Overridable, and skipped when absent.
SHARE_HOST="${EP_SHARE_HOST:-CORBIN01}"
SHARE_NAME="${EP_SHARE_NAME:-downloads}"

FAILURES=0
SKIPS=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
skip() { printf '  SKIP  %s\n' "$*"; SKIPS=$((SKIPS + 1)); }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }

# --- 0. isolation -----------------------------------------------------
say "0. isolated from the live install"

# Drop every ambient EUGENE_PLEXUS_* variable, as a LOOP and not a list.
# Step 7's run repointed the live install at a dead port by inheriting
# EUGENE_PLEXUS_AGENT_CONFIG_FILE from the user environment; this is the
# fix, and any future script that starts an agent must do the same.
while IFS='=' read -r name _; do
  case "$name" in EUGENE_PLEXUS_*) unset "$name" ;; esac
done < <(env)

rm -rf "$WORK"
mkdir -p "$WORK"
export EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK/agent.yaml"
export EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT"

for port in $OWNED_PORTS; do
  if [ -n "$(listening_pids "$port")" ]; then
    bad "port $port is already in use; refusing to start (this box is a worker node)"
    exit 1
  fi
done
ok "ports $OWNED_PORTS are free and the ambient environment is cleared"

if [ ! -x "$PY" ]; then
  bad "no agent interpreter at $PY"
  exit 1
fi
ok "agent interpreter: $PY"

# --- 1. the measurement that turned this slice into a credential slice -
say "1. an uncredentialed session cannot open the share (design §0.2)"

SHARE_PROBE=$("$PY" - "$SHARE_HOST" "$SHARE_NAME" <<'PYEOF'
import os, sys
host, share = sys.argv[1], sys.argv[2]
path = "\\\\" + host + "\\" + share
try:
    os.listdir(path)
    print("OPENED")
except OSError as exc:
    print(f"REFUSED {exc.winerror}")
except Exception as exc:  # pragma: no cover
    print(f"ERROR {exc}")
PYEOF
)
case "$SHARE_PROBE" in
  "REFUSED 1272")
    ok "the share refuses an unauthenticated connection (WinError 1272) -- exactly what a LocalSystem service would get"
    ;;
  "REFUSED "*)
    ok "the share refuses an uncredentialed session ($SHARE_PROBE); the premise holds, the code differs"
    ;;
  OPENED)
    # Not a failure of the product. It means this box already holds a
    # session to that name, which makes the probe blind rather than
    # wrong -- and saying so beats reporting a pass.
    skip "this session can already open \\\\$SHARE_HOST\\$SHARE_NAME, so it cannot stand in for one that cannot"
    ;;
  *)
    skip "could not probe \\\\$SHARE_HOST\\$SHARE_NAME ($SHARE_PROBE)"
    ;;
esac

# --- 2. the console ---------------------------------------------------
say "2. a console-less parent can still stop a child gracefully (design §0.3)"

# pytest on Windows cannot read an MSYS `/d/...` path, so this runs
# from the repo with a relative node id. The first version reported
# "the experiment did not pass" for a file it never found.
CONSOLE_TEST="tests/test_windows_supervision.py::test_a_console_less_parent_regains_the_graceful_stop"
(cd "$EP_ROOT/agent" && "$PY" -m pytest "$CONSOLE_TEST" -q -p no:randomly) >"$WORK/console.log" 2>&1
if grep -q "1 passed" "$WORK/console.log"; then
  ok "arm A signals, arm B (no console) does not, arm C (AllocConsole) signals again"
else
  bad "the three-arm console experiment did not pass; see $WORK/console.log"
fi

# --- 3. the restart command -------------------------------------------
say "3. the restart helper waits, and does not reach for what cannot run detached"

RESTART=$("$PY" - <<'PYEOF'
from eugene_plexus_agent import reach
from eugene_plexus_agent._generated.models import AgentRestart, Mechanism

problems = []
for mechanism, starter in ((Mechanism.service, "sc start"), (Mechanism.logon_task, "schtasks /Run")):
    argv = reach.restart_argv(AgentRestart(mechanism=mechanism, canSelfRestart=True))
    line = " ".join(argv or [])
    if "timeout /t" in line:
        problems.append(f"{mechanism.value}: still waits with `timeout`, which exits rc 125 in 0.18s")
    if "powershell" in line.lower():
        problems.append(f"{mechanism.value}: uses PowerShell, which does nothing under DETACHED_PROCESS")
    if "ping -n" not in line:
        problems.append(f"{mechanism.value}: no pacer between attempts")
    if line.count(starter) < 2:
        problems.append(f"{mechanism.value}: the start is not retried, so a slow stop loses")
print("OK" if not problems else "; ".join(problems))
PYEOF
)
if [ "$RESTART" = "OK" ]; then
  ok 'both Windows branches retry the start on a pacer; no timeout, no PowerShell'
else
  bad "$RESTART"
fi

# --- 4. the service branch --------------------------------------------
say "4. session 0 is a precondition, not the answer"

SERVICE_SCOPE=$("$PY" - <<'PYEOF'
import os, sys
from eugene_plexus_agent import reach

problems = []
# Pretend we are in session 0, which is where a service runs -- and
# where a SYSTEM-principal task, `PsExec -s` and ANOTHER INSTALL'S
# service also run.
reach._running_as_windows_service = lambda: True

reach._service_image_path = lambda name: r"C:\Users\someone\Local\EugenePlexus\venv\pythonservice.exe"
if reach._windows_service_runs_this_install():
    problems.append("another install's service counted as this one")

reach._service_image_path = lambda name: None
if reach._windows_service_runs_this_install():
    problems.append("an unreadable service entry fell back to 'well, session 0'")

reach._service_image_path = lambda name: os.path.join(sys.prefix, "pythonservice.exe")
if not reach._windows_service_runs_this_install():
    problems.append("this install's own service was not recognised")
else:
    described = reach._windows_restart()
    if not described.detail:
        problems.append("the service branch has no detail for a screen to print")
    elif "before anyone signs in" not in described.detail:
        problems.append(f"the service branch says {described.detail!r}")
print("OK" if not problems else "; ".join(problems))
PYEOF
)
if [ "$SERVICE_SCOPE" = "OK" ]; then
  ok "only this install's own service counts, and it says it starts before anyone signs in"
else
  bad "$SERVICE_SCOPE"
fi

# --- 5. share credentials, through the running agent ------------------
say "5. shareCredentials: redacted on the way out, kept on the way back"

"$PY" -m eugene_plexus_agent >"$WORK/agent.log" 2>&1 &
AGENT_PID=$!
for _ in $(seq 1 60); do
  curl -sS "$AGENT/healthz" >/dev/null 2>&1 && break
  sleep 0.5
done
if ! curl -sS "$AGENT/healthz" >/dev/null 2>&1; then
  bad "the agent did not answer on $AGENT_PORT; see $WORK/agent.log"
else
  ok "a throwaway agent is answering on $AGENT_PORT"

  TOKEN=$(curl -sS -X POST "$AGENT/v1/auth/initialize" \
    -H 'content-type: application/json' \
    -d "{\"passphrase\":\"$PASS\"}" |
    python -c "import sys,json; print(json.load(sys.stdin)['sessionToken'])" 2>/dev/null)
  if [ -z "${TOKEN:-}" ]; then
    bad "could not initialize the throwaway agent"
  else
    SCHEMA=$(curl -sS "$AGENT/v1/config/schema" -H "authorization: Bearer $TOKEN")
    if printf '%s' "$SCHEMA" | grep -q '"share_credentials"'; then
      ok "the agent's config schema carries shareCredentials as share_credentials"
    else
      bad "shareCredentials is not in the agent's config schema"
    fi

    curl -sS -X PATCH "$AGENT/v1/config" -H "authorization: Bearer $TOKEN" \
      -H 'content-type: application/json' \
      -d '{"shareCredentials":[{"host":"nas.example","username":"tcorbin","password":"hunter2"}]}' \
      >"$WORK/patch.json"
    if grep -q '"rejected": *\[\]' "$WORK/patch.json" || grep -q '"rejected":\[\]' "$WORK/patch.json"; then
      ok "a credential saves"
    else
      bad "saving a credential was rejected: $(cat "$WORK/patch.json")"
    fi

    READ=$(curl -sS "$AGENT/v1/config" -H "authorization: Bearer $TOKEN")
    if printf '%s' "$READ" | grep -q "hunter2"; then
      bad "GET /v1/config handed the password back"
    else
      ok "GET /v1/config redacts the password"
    fi
    if printf '%s' "$READ" | grep -q "tcorbin"; then
      ok "...and keeps the host and user name, so a row is still renderable"
    else
      bad "the redaction removed the whole row, not just the password"
    fi

    if grep -q "hunter2" "$WORK/agent.yaml"; then
      bad "the password is in agent.yaml in the clear"
    else
      ok "the password is sealed at rest"
    fi

    # **The one that matters.** A UI writes back the row it was shown,
    # whose password is null. Without the merge the secret is gone and
    # nothing says so until the next reboot.
    curl -sS -X PATCH "$AGENT/v1/config" -H "authorization: Bearer $TOKEN" \
      -H 'content-type: application/json' \
      -d '{"shareCredentials":[{"host":"nas.example","username":"someone-else","password":null}]}' \
      >/dev/null
    KEPT=$("$PY" - "$WORK/agent.yaml" <<'PYEOF'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
rows = doc.get("shareCredentials") or []
row = rows[0] if rows else {}
print("KEPT" if isinstance(row.get("password"), dict) and row.get("username") == "someone-else" else f"LOST {row!r}")
PYEOF
)
    if [ "$KEPT" = "KEPT" ]; then
      ok "writing back a redacted row changes the user name and KEEPS the password"
    else
      bad "the round trip lost the password: $KEPT"
    fi

    # And the explicit clear, which must still work or the field is a
    # one-way door.
    curl -sS -X PATCH "$AGENT/v1/config" -H "authorization: Bearer $TOKEN" \
      -H 'content-type: application/json' \
      -d '{"shareCredentials":[{"host":"nas.example","username":"someone-else","password":""}]}' \
      >/dev/null
    CLEARED=$("$PY" - "$WORK/agent.yaml" <<'PYEOF'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
rows = doc.get("shareCredentials") or []
print("CLEARED" if rows and rows[0].get("password") is None else f"STILL THERE {rows!r}")
PYEOF
)
    if [ "$CLEARED" = "CLEARED" ]; then
      ok "an explicit empty password clears it"
    else
      bad "$CLEARED"
    fi

    # A second row for one server can never take effect (Windows 1219),
    # so accepting it would be a field that lies.
    DUPE=$(curl -sS -X PATCH "$AGENT/v1/config" -H "authorization: Bearer $TOKEN" \
      -H 'content-type: application/json' \
      -d '{"shareCredentials":[{"host":"nas.example","username":"a","password":"1"},{"host":"NAS.EXAMPLE","username":"b","password":"2"}]}')
    if printf '%s' "$DUPE" | grep -qi "already listed"; then
      ok "two rows for one server are refused, because Windows allows one login per server"
    else
      bad "a duplicate server was accepted: $DUPE"
    fi
  fi
fi

# --- 6. the tray ------------------------------------------------------
say "6. the tray reads the real SCM"

TRAY=$("$PY" - <<'PYEOF'
from eugene_plexus_agent import tray

state = tray.query_state()
offered = {label: enabled for _, label, enabled in tray.menu_for(state)}
problems = []
if state not in ("running", "stopped", "unknown"):
    problems.append(f"unrecognised state {state!r}")
if not offered.get("Open Eugene"):
    problems.append("Open Eugene is not offered")
if state == "unknown" and (offered.get("Start Eugene") or offered.get(
    "Stop Eugene (frees the graphics card)"
)):
    problems.append("an unreadable service offered an action anyway")
if len(tray.tooltip_for(state)) >= 64:
    problems.append("the tooltip is long enough for the shell to truncate it")
print(("OK " + state) if not problems else "; ".join(problems))
PYEOF
)
case "$TRAY" in
  "OK "*)
    ok "the tray reports '${TRAY#OK }' against this box's real SCM and greys what cannot apply"
    ;;
  *) bad "$TRAY" ;;
esac

# --- 7. the installer's decisions -------------------------------------
say "7. install.ps1 parses, is ASCII, and defaults to a service"

PS1="$EP_ROOT/specs/scripts/install.ps1"
if LC_ALL=C grep -qP '[^\x00-\x7F]' "$PS1" 2>/dev/null; then
  # A BOM-less UTF-8 .ps1 is decoded as CP-1252 by PowerShell 5.1, and
  # one em dash makes the file unparseable from disk while `irm | iex`
  # keeps working.
  bad "install.ps1 contains a non-ASCII byte"
else
  ok "install.ps1 is pure ASCII"
fi

PARSE=$(powershell -NoProfile -NonInteractive -Command "
  \$e=\$null; [void][System.Management.Automation.Language.Parser]::ParseFile('$(cygpath -w "$PS1" 2>/dev/null || echo "$PS1")',[ref]\$null,[ref]\$e)
  if (\$e) { \$e | ForEach-Object { \$_.Message } } else { 'CLEAN' }" 2>&1 | tr -d '\r')
if [ "$PARSE" = "CLEAN" ]; then
  ok "install.ps1 parses"
else
  bad "install.ps1 does not parse: $PARSE"
fi

if grep -q 'WantsService = -not (\$NoService -or \$Uninstall)' "$PS1"; then
  ok "a Windows install is a service unless -NoService says otherwise"
else
  bad "the service is not the default"
fi
if grep -q 'Verb RunAs' "$PS1"; then
  ok "the installer asks for Administrator rather than telling somebody to re-run"
else
  bad "nothing elevates, so the default install cannot register a service"
fi
# **The grant has to be CALLED, not merely defined.** The first version
# of this grepped for `sc.exe sdset`, which lives inside
# `Grant-ServiceControl` -- so deleting the call site left the string in
# the file and the check passed against an installer that granted
# nothing. That is R2.2's own lesson repeated: a check that matches a
# NAME is not a check. Both halves now, and the call site is the one
# that can be removed by accident.
if grep -q 'sc.exe sdset' "$PS1"; then
  ok "Grant-ServiceControl really calls sc sdset"
else
  bad "no sc sdset anywhere, so nothing grants the tray its rights"
fi
if grep -qE '^\s+Grant-ServiceControl\s*$' "$PS1"; then
  ok "the service branch calls it, so the tray needs no prompt"
else
  bad "Grant-ServiceControl is never called: every tray click raises UAC"
fi
if grep -q 'TrayTaskName = "EugenePlexusTray"' "$PS1"; then
  ok "the logon task changed job rather than disappearing"
else
  bad "no tray task"
fi

# --- 8. -Detect does not end the session that ran it ------------------
say "8. -Detect reports without closing the terminal"

# The rule is stated in install.ps1 forty lines above the line that
# broke it: `exit` inside a scriptblock ends the CALLER'S process, and
# `-Detect` is only reachable as a scriptblock. Run it as a scriptblock,
# the way a person does, and check we are still here afterwards.
DETECT=$(powershell -NoProfile -NonInteractive -Command "
  \$src = Get-Content -Raw '$(cygpath -w "$PS1" 2>/dev/null || echo "$PS1")'
  & ([scriptblock]::Create(\$src)) -Detect *>\$null
  'SURVIVED exit=' + \$LASTEXITCODE" 2>&1 | tr -d '\r' | tail -1)
case "$DETECT" in
  SURVIVED*)
    ok "-Detect returned to its caller ($DETECT)"
    ;;
  *)
    bad "-Detect did not return to its caller: $DETECT"
    ;;
esac

# --- 9. the pins ------------------------------------------------------
say "9. every pinned archive resolves, and the UI one carries the build"

PIN_FAIL=0
pin_sh() { grep "^$1=" "$EP_ROOT/specs/scripts/install.sh" | head -1 | sed "s/^$1=//" | awk '{print $1}'; }
# **Only the hashtable whose values are SHAs.** `$DIST` in install.ps1
# has the same keys with package names for values, and a grep on the key
# alone matched both -- which reported every pin as disagreeing with
# itself. A check that cannot pass is as useless as one that cannot
# fail.
pin_ps1() {
  grep -E "\"$1\" *= *\"[0-9a-f]{40}\"" "$EP_ROOT/specs/scripts/install.ps1" |
    head -1 | grep -oE '[0-9a-f]{40}'
}

AGENT_SHA=$(pin_sh PIN_AGENT)
code=$(curl -sS -o /dev/null -w "%{http_code}" -L "https://github.com/eugene-plexus/agent/archive/$AGENT_SHA.tar.gz" 2>/dev/null)
if [ "$code" = "200" ]; then
  ok "the agent pin resolves"
else
  bad "the agent pin ($AGENT_SHA) does not resolve (HTTP ${code:-?})"
  PIN_FAIL=1
fi

UI_SHA=$(pin_sh PIN_UI)
rm -rf "$WORK/uipin" && mkdir -p "$WORK/uipin"
if curl -sSL "https://github.com/eugene-plexus/ui/archive/$UI_SHA.tar.gz" -o "$WORK/uipin/ui.tgz" 2>/dev/null &&
  tar xzf "$WORK/uipin/ui.tgz" -C "$WORK/uipin" 2>/dev/null; then
  # **The `dist` trap, checked against the ARCHIVE and not the working
  # tree.** S10 clicked a 16 GB download because a merged, tested UI fix
  # had reached no build; the only way that cannot happen silently is to
  # fetch what the installer will fetch and grep it.
  if grep -rq "before anyone signs in" "$WORK"/uipin/ui-*/python/eugene_plexus_ui/static/_next/static/chunks/ 2>/dev/null; then
    ok "the pinned UI archive carries this slice's code"
  else
    bad "the pinned UI archive does not carry this slice's code -- dist was not rebuilt"
  fi
else
  bad "could not fetch the pinned UI archive"
fi

# Both installers must agree, or one platform ships a different install.
for var in PIN_AGENT PIN_CONTROL PIN_GATEWAY PIN_DRIVER PIN_LIBRARY PIN_UI; do
  case "$var" in
    PIN_DRIVER) key="inference-driver" ;;
    *) key=$(printf '%s' "${var#PIN_}" | tr 'A-Z' 'a-z') ;;
  esac
  a=$(pin_sh "$var")
  b=$(pin_ps1 "$key")
  if [ -z "$a" ] || [ -z "$b" ]; then
    bad "$var could not be read from both installers (sh=${a:-none} ps1=${b:-none})"
    PIN_FAIL=1
  elif [ "$a" != "$b" ]; then
    bad "$var disagrees between the installers ($a vs $b)"
    PIN_FAIL=1
  fi
done
[ "$PIN_FAIL" = "0" ] && ok "both installers pin the same six commits"

# --- 10. teardown -----------------------------------------------------
say "10. teardown"

if [ -n "${AGENT_PID:-}" ]; then
  kill "$AGENT_PID" 2>/dev/null
  sleep 1
fi
for port in $OWNED_PORTS; do
  for pid in $(listening_pids "$port"); do
    powershell -NoProfile -NonInteractive -Command "Stop-Process -Id $pid -Force" >/dev/null 2>&1
  done
done
sleep 1
STILL=""
for port in $OWNED_PORTS; do
  [ -n "$(listening_pids "$port")" ] && STILL="$STILL $port"
done
if [ -z "$STILL" ]; then
  ok "no owned port is still listening"
else
  bad "still listening on:$STILL"
fi

printf '\n'
printf '  %s failures, %s skipped\n' "$FAILURES" "$SKIPS"
printf '\n'
printf '  NOT COVERED, and it is the Done when: a service registered, a\n'
printf '  reboot with nobody signed in, AllocConsole in SESSION 0, the\n'
printf '  master key in SYSTEM'"'"'s store, a real share opened by\n'
printf '  LocalSystem, and a tray click with no UAC prompt. Six checks,\n'
printf '  listed by `install.ps1 -Verify`. They need Administrator.\n'
[ "$FAILURES" -eq 0 ] || exit 1
