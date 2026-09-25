#!/usr/bin/env bash
#
# M9 acceptance: onboarding, leaving, moving house -- and a browser.
#
# LAST RUN 2026-09-25, under per-node token keys (row 3): 53 PASS, 0 FAIL,
# first execution, the browser arc included (auth-arc.spec.ts unchanged: 4
# passed, the playground completion skipped for want of EP_CHAT_MODEL), the
# keyring branch of 2b. Every port moved +100, because this box's live
# install holds 8079, so section 1 ran the off-contract-ports branch:
#   EP_AGENT_A_URL=http://127.0.0.1:8179 EP_AGENT_B_URL=http://127.0.0.1:8184 \
#   EP_AGENT_B2_URL=http://127.0.0.1:8185 EP_CONTROL_URL=http://127.0.0.1:8183 \
#   EP_GATEWAY_URL=http://127.0.0.1:8180 EP_LIBRARY_URL=http://127.0.0.1:8182 \
#   EP_MOVED_URL=http://127.0.0.1:8199 EP_SKIP_UI_BUILD=1 \
#   bash scripts/m9-acceptance.sh
# (EP_SKIP_UI_BUILD because the agent venv serves the UI checkout EDITABLE and
# its staged export was already newer than ui HEAD with a clean tree.)
#
#   host A (this box)   agent A :8079  -> control :8083, gateway :8080, library :8082
#                       and serves the UI at its own root from the
#                       eugene-plexus-ui wheel (EP_SKIP_BROWSER=1 to omit)
#   host B (also here)  agent B :8084  -> onboarded by `eugene-plexus-agent join`
#   (the defaults; every one is a variable, and the preflight refuses a port
#   something already holds rather than sharing or reclaiming it)
#
# **THIS SCRIPT DOES NOT PRE-WRITE `firstRunComplete`, AND THAT IS THE
# POINT.** Every multi-host script since M0 wrote `firstRunComplete: true`
# with an empty component list before starting anything -- which is the
# bypass for an onboarding feature that did not exist, written so fluently
# that nobody noticed it was standing in for one. Host A here starts with
# NO agent.yaml at all and has to declare its own control plane; host B is
# onboarded the way an operator would, with a token minted at the root.
#
# **Except when the three components are moved off their contract ports.**
# First-boot seeding declares control, gateway and library at 8083, 8080 and
# 8082 whatever port the agent took (`default_topology.py`), with no setting
# to change that, so a run that must not bind those ports -- this box, whose
# live install shares the machine -- cannot seed. Then A starts from an
# agent.yaml holding ONLY those three components at the requested ports:
# still no `firstRunComplete`, no passphrase, nothing else, so the wizard
# still meets an install nobody has set up, and the checks assert that the
# agent declared nothing on top and that nobody had set it up. Seeding
# itself is exercised only when EP_CONTROL_URL, EP_GATEWAY_URL and
# EP_LIBRARY_URL are left at the contract defaults.
#
# Four things under test, all new at M9:
#   1. onboarding   -- a fresh agent seeds; `join` enrolls without a browser
#                      and leaves a node that does NOT raise a rival root
#   2. re-advertise -- a node whose address changes tells the root, signed,
#                      on startup and on a config change; replays refused
#   3. unenroll     -- a node forgets the root it pinned and becomes its own
#                      authority again, telling the root, which drops the
#                      node's key from the trust bundle and signs nobody
#                      else out
#   4. the browser  -- Playwright drives first run, login, restart-on-login,
#                      and the topology-resolved proxy. No script can test
#                      the third: logging in respawns every child, so the
#                      page that just authenticated is talking to a fleet
#                      that is going away.
#
# Rewritten for per-node token keys (2026-09-25,
# docs/design/per-node-token-keys.md). Removed or replaced:
#   * "Logging in at a joined node points the operator at the control root":
#     signing in there now forwards to the root and returns a session
#     addressed to that machine and the root -- a worker is a console.
#   * "A token minted at the control root verifies on B": the root's own
#     session is addressed to the root alone and B refuses it; B is read
#     with a session from its own sign-in.
#   * "The install's signing key is gone from node.yaml after leaving": no
#     node ever held one; the check is that B no longer pins the root and
#     keeps a bundle it signed itself, and that the root's bundle no longer
#     lists B's key.
#   * The up-front `kill_port` on A's, B's and B2's ports: it killed
#     whatever held them, including another install's processes. The
#     preflight refuses a taken port instead, and teardown by port is
#     limited to ports it proved free.
#
# Design: docs/design/m9-networked-polish.md
# Deployment doc this exercises the happy path of: docs/deployment/tailnet.md
#
set -uo pipefail

# Nothing from the calling shell's install reaches anything started here:
# this box's live agent sets EUGENE_PLEXUS_AGENT_CONFIG_FILE at user scope,
# and a throwaway agent that loads the operator's node.yaml announces the
# real node at a port that dies with this script.
while read -r _ep_var; do unset "$_ep_var"; done < <(compgen -e | grep -i '^EUGENE_PLEXUS_')

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
EP_AGENT_PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
EP_UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
EP_WORKDIR="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-m9-acceptance}"
EP_AGENT_A_URL="${EP_AGENT_A_URL:-http://127.0.0.1:8079}"
EP_AGENT_B_URL="${EP_AGENT_B_URL:-http://127.0.0.1:8084}"
EP_AGENT_B2_URL="${EP_AGENT_B2_URL:-http://127.0.0.1:8085}"
EP_CONTROL_URL="${EP_CONTROL_URL:-http://127.0.0.1:8083}"
EP_GATEWAY_URL="${EP_GATEWAY_URL:-http://127.0.0.1:8080}"
EP_LIBRARY_URL="${EP_LIBRARY_URL:-http://127.0.0.1:8082}"
# Where section 5 says B moved. Deliberately an address nothing listens on;
# the preflight proves that, because the root will probe it.
EP_MOVED_URL="${EP_MOVED_URL:-http://127.0.0.1:8099}"
# **The browser drives the agent, not a dev server.** Until
# install-paths §9 step 1 this was `next dev` on :3100, which is the one
# thing an install never runs: the UI now ships as a static export inside
# the `eugene-plexus-ui` wheel and the agent serves it at its own root.
# Pointing Playwright at a dev server tested a configuration no operator
# has -- a reference client sharing a path with nothing it ships.
EP_UI_URL="${EP_UI_URL:-$EP_AGENT_A_URL}"
EP_SKIP_BROWSER="${EP_SKIP_BROWSER:-}"
PASSPHRASE="${EP_PASSPHRASE:-m9-acceptance-passphrase}"

port_of() { printf '%s' "$1" | sed -E 's|.*:([0-9]+)/?$|\1|'; }
A_PORT=$(port_of "$EP_AGENT_A_URL")
B_PORT=$(port_of "$EP_AGENT_B_URL")
B2_PORT=$(port_of "$EP_AGENT_B2_URL")
CONTROL_PORT=$(port_of "$EP_CONTROL_URL")
GATEWAY_PORT=$(port_of "$EP_GATEWAY_URL")
LIBRARY_PORT=$(port_of "$EP_LIBRARY_URL")
MOVED_PORT=$(port_of "$EP_MOVED_URL")
SEED=0
[ "$CONTROL_PORT:$GATEWAY_PORT:$LIBRARY_PORT" = "8083:8080:8082" ] && SEED=1

FAILURES=0
PASSES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; PASSES=$((PASSES + 1)); }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
wait_http() { for _ in $(seq 1 "${2:-90}"); do curl -sf -m 2 -o /dev/null "$1" && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -m 10 -w '%{http_code}' -H "Authorization: Bearer $2" "$1"; }
aud_of() { printf '%s' "$1" | PYTHONUTF8=1 python -c "import sys,json,base64; p=sys.stdin.read().strip().split('.')[1]; print(','.join(json.loads(base64.urlsafe_b64decode(p + '=' * (-len(p) % 4))).get('aud',[])))"; }
ctl_login() { curl -s -X POST "$EP_CONTROL_URL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')" 2>/dev/null; }
agent_login() { curl -s -X POST "$1/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')" 2>/dev/null; }
# An enrolled agent's sign-in is the root's: it answers 503 while the root is
# not reachable yet (right after a restart, for instance). Bounded, not assumed.
login_retry() { local t=""; for _ in $(seq 1 30); do t=$(agent_login "$1"); [ -n "$t" ] && break; sleep 1; done; printf '%s' "$t"; }
port_free() {
  local p="$1"
  curl -s -m 1 -o /dev/null "http://127.0.0.1:$p/healthz" && return 1
  netstat -ano 2>/dev/null | grep LISTENING | grep -qE "[:.]$p[[:space:]]" && return 1
  return 0
}

# --- preflight -----------------------------------------------------------------
say "preflight"
[ -f "$EP_AGENT_PY" ] || bad "agent venv python not found at $EP_AGENT_PY"
[ "$FAILURES" -ne 0 ] && exit 1
"$EP_AGENT_PY" -c "import eugene_plexus_agent, eugene_plexus_control, eugene_plexus_gateway, eugene_plexus_inference_driver, eugene_plexus_library" 2>/dev/null \
  || { bad "all five components must import from $EP_AGENT_PY"; exit 1; }
# Every port this run binds or announces, proved free before anything
# starts. That proof is also what makes tearing down by these ports safe.
RUN_PORTS=("$A_PORT" "$CONTROL_PORT" "$GATEWAY_PORT" "$LIBRARY_PORT" "$B_PORT" "$B2_PORT" "$MOVED_PORT")
TAKEN=""
for p in "${RUN_PORTS[@]}"; do port_free "$p" || TAKEN="$TAKEN $p"; done
if [ -n "$TAKEN" ]; then
  bad "port(s)$TAKEN already in use; move every EP_*_URL to free ports (never reclaim one)"
  exit 1
fi
ok "five components import from the agent's interpreter; every port this run uses is free (${RUN_PORTS[*]})"

BROWSER=1
if [ -n "$EP_SKIP_BROWSER" ]; then
  BROWSER=0
  echo "  browser arc skipped (EP_SKIP_BROWSER set)"
elif [ ! -d "$EP_UI_DIR/node_modules" ]; then
  BROWSER=0
  echo "  browser arc skipped: $EP_UI_DIR/node_modules is absent (npm ci first)"
else
  # **Rebuild the UI rather than trust the installed one.** The agent
  # serves whatever `eugene-plexus-ui` is in its interpreter, and a build
  # of unknown age is a stale instrument -- the failure that already cost
  # this script a misattributed run when `next dev` kept serving a
  # previous build. `EP_SKIP_UI_BUILD=1` for a fast re-run where the UI
  # has not changed.
  #
  # **An editable install is restaged, never replaced.** When the agent's
  # interpreter has the UI checkout installed editable, it serves what
  # `npm run build:python` stages; force-installing a wheel over it
  # replaced the editable install once and four runs asserted about a
  # build no browser saw.
  if [ -z "${EP_SKIP_UI_BUILD:-}" ]; then
    UI_EDITABLE=$("$EP_AGENT_PY" -m pip show eugene-plexus-ui 2>/dev/null | grep -i '^Editable project location' | sed 's/^[^:]*: //')
    if [ -n "$UI_EDITABLE" ]; then
      if (cd "$EP_UI_DIR" && npm run build:python > "$EP_WORKDIR-uibuild.log" 2>&1); then
        ok "restaged the export the agent's editable eugene-plexus-ui serves ($UI_EDITABLE)"
      else
        BROWSER=0
        echo "  browser arc skipped: the ui export would not build -- see $EP_WORKDIR-uibuild.log"
        tail -15 "$EP_WORKDIR-uibuild.log"
      fi
    elif (cd "$EP_UI_DIR" && npm run build:python > "$EP_WORKDIR-uibuild.log" 2>&1 \
          && "$EP_AGENT_PY" -m build --wheel >> "$EP_WORKDIR-uibuild.log" 2>&1 \
          && "$EP_AGENT_PY" -m pip install --quiet --force-reinstall \
               "$(ls -t "$EP_UI_DIR"/dist/eugene_plexus_ui-*.whl | head -1)" \
               >> "$EP_WORKDIR-uibuild.log" 2>&1); then
      ok "rebuilt and installed eugene-plexus-ui from the checkout"
    else
      BROWSER=0
      echo "  browser arc skipped: the ui wheel would not build -- see $EP_WORKDIR-uibuild.log"
      tail -15 "$EP_WORKDIR-uibuild.log"
    fi
  fi
  if [ "$BROWSER" = "1" ]; then
    "$EP_AGENT_PY" -c "import eugene_plexus_ui" 2>/dev/null \
      && ok "the browser arc will drive the agent's own UI at $EP_UI_URL" \
      || { BROWSER=0; echo "  browser arc skipped: eugene-plexus-ui is not installed in $EP_AGENT_PY"; }
  fi
fi

rm -rf "$EP_WORKDIR"; mkdir -p "$EP_WORKDIR/a" "$EP_WORKDIR/b" "$EP_WORKDIR/seeded"; cd "$EP_WORKDIR" || exit 1
WIN_WORKDIR="$(pwd -W)"

A_PID=""; B_PID=""
# **Clear the PORT, not just the pid.** Written for `next dev`, which
# spawned a child of its own, so killing the held pid left a server
# listening and the next run silently tested the previous run's build --
# a misattributed failure that cost a session. The dev server is gone
# (the agent serves the UI now) and the rule is not: Windows lets a
# second process bind an already-bound loopback port and keeps serving
# from the OLDEST binder, which is how M10 read a two-runs-old reply.
# Same shape as M7's "the pid the script held was a subshell's", one
# layer further out. **Only ports the preflight proved free** -- anything
# else on them is not this run's to kill.
kill_port() {
  local port="$1"
  local pids
  pids=$(netstat -ano 2>/dev/null | grep -E "LISTENING" | grep -E ":$port[[:space:]]" | awk '{print $NF}' | sort -u)
  for pid in $pids; do
    [ -n "$pid" ] && taskkill //PID "$pid" //T //F >/dev/null 2>&1
  done
}
cleanup() {
  for pid in "$B_PID" "$A_PID"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
  done
  for port in "$A_PORT" "$B_PORT" "$B2_PORT" "$CONTROL_PORT" "$GATEWAY_PORT" "$LIBRARY_PORT"; do kill_port "$port"; done
}
trap cleanup EXIT

# --- 1. a fresh machine declares its own control plane --------------------------
if [ "$SEED" = "1" ]; then
  say "1. agent A starts with NO agent.yaml -- and has to be an install by itself"
  [ -f a/agent.yaml ] && bad "a/agent.yaml exists before the run; the bypass is back" || ok "no agent.yaml exists yet"
else
  say "1. agent A starts with only its three components declared, off their contract ports"
  printf 'components:\n  - name: control\n    kind: control\n    url: http://127.0.0.1:%s\n    spawn:\n      configFile: control.yaml\n  - name: gateway\n    kind: gateway\n    url: http://127.0.0.1:%s\n    spawn:\n      configFile: gateway.yaml\n  - name: library\n    kind: library\n    url: http://127.0.0.1:%s\n    spawn:\n      configFile: library.yaml\nruntimes: []\n' \
    "$CONTROL_PORT" "$GATEWAY_PORT" "$LIBRARY_PORT" > a/agent.yaml
  grep -qE "firstRunComplete|auth" a/agent.yaml && bad "a/agent.yaml carries onboarding state; the bypass is back" || ok "a/agent.yaml declares three components and nothing else: no firstRunComplete, no passphrase"
fi
# No TTY here, deliberately: that is the documented non-interactive path
# and the one a service unit takes. It must seed rather than block.
(cd a && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$A_PORT" "$EP_AGENT_PY" -m eugene_plexus_agent > ../agent-a.log 2>&1) &
A_PID=$!
wait_healthy "$EP_AGENT_A_URL" && ok "agent A answering on :$A_PORT with nobody having set it up" || { bad "agent A never came up"; tail -30 agent-a.log; exit 1; }
wait_healthy "$EP_CONTROL_URL" && ok "control root spawned by a first boot nobody configured" || { bad "control never came up"; tail -40 agent-a.log; exit 1; }
wait_healthy "$EP_GATEWAY_URL" 90 && ok "gateway spawned" || bad "gateway never came up"
if [ "$SEED" = "1" ]; then
  grep -q "first boot: declared the default topology" agent-a.log \
    && ok "agent A said so in its own log" || bad "no first-boot declaration in agent-a.log"
else
  grep -q "first boot: declared the default topology" agent-a.log \
    && bad "agent A seeded on top of a declared topology" || ok "agent A declared nothing on top of the topology it was given"
fi
[ "$(curl -s "$EP_AGENT_A_URL/v1/auth/status" | jq_ "d.get('initialized')")" = "False" ] \
  && ok "no passphrase is set: the first-run wizard is what a browser meets" || bad "agent A reports itself initialized before anyone set it up"

if [ "$BROWSER" = "1" ]; then
  # --- 2. the browser does first run ---------------------------------------------
  say "2. a browser walks the first-run wizard, logs in, and survives the restart"
  # No server to start: agent A is already up and already serving the UI,
  # which is the whole point of the repoint. The wait is on the page
  # rather than on a process, because the agent answering /healthz says
  # nothing about whether the wheel is mounted.
  if wait_http "$EP_UI_URL/" 30; then
    ok "the agent is serving the UI at $EP_UI_URL"
    # Only the arc this script builds an install for. The other spec files
    # each belong to the script that stands up what they need -- a
    # declared driver (navigation-acceptance.sh), a chat model
    # (playground-diagnostic-acceptance.sh), a second enrolled agent
    # (library-folders-acceptance.sh), a root restarted sealed
    # (login-unlock-check.sh) -- and an unfiltered run here fails eight of
    # them for want of that, which is what the first S0 run reported.
    # Results go under this run's directory, not the checkout's shared
    # `test-results`, which Playwright empties at the start of every run.
    if (cd "$EP_UI_DIR" && EP_UI_URL="$EP_UI_URL" EP_PASSPHRASE="$PASSPHRASE" \
         npx playwright test e2e/auth-arc.spec.ts --output "$WIN_WORKDIR/playwright-results" > "$EP_WORKDIR/playwright.log" 2>&1); then
      ok "the browser arc passed (first run, login, restart-on-login, proxy)"
    else
      bad "the browser arc failed -- see $EP_WORKDIR/playwright.log"
      tail -40 "$EP_WORKDIR/playwright.log"
    fi
  else
    bad "the agent never served a page; skipping the browser arc"
    tail -20 agent-a.log
  fi
else
  say "2. no browser; initializing with curl the way every earlier script did"
  curl -s -o /dev/null -X POST "$EP_AGENT_A_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}"
  curl -s -o /dev/null -X POST "$EP_CONTROL_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}"
fi

ATOK=$(login_retry "$EP_AGENT_A_URL")
CTOK=$(ctl_login)
[ -n "$ATOK" ] && ok "agent A has an operator session (aud $(aud_of "$ATOK"))" || { bad "no agent A session"; exit 1; }
[ -n "$CTOK" ] && ok "the trust root is initialized and issues sessions" || { bad "control is not initialized -- did the wizard reach it?"; exit 1; }

# --- 2b. every process is killed and the agent started again; nobody signs in ----
# S0 of the hobbyist UX plan (docs/design/hobbyist-ux.md, decision #9). The
# wizard defaults securityMode to os_keyring where this host has a keyring
# and writes it to BOTH the agent and the control root, so a hard restart
# of everything must need nobody. Where there is no keyring (CI, a
# container) the wizard says so, keeps prompt_on_startup, and the same
# restart comes back sealed -- the documented behaviour, asserted rather
# than skipped so the record says which branch ran. Only after a browser
# walked the wizard: the curl path above sets no mode at all.
#
# Before S0 this exact restart came back with the control root sealed on
# every install whose operator had ticked the keyring option, because the
# choice was written to the agent alone behind a comment claiming the root
# ignored the field. Nothing had ever restarted an install the wizard made.
if [ "$BROWSER" = "1" ]; then
  say "2b. every process is killed and the agent started again; nobody signs in"
  KEYRING=$(curl -s "$EP_AGENT_A_URL/v1/auth/status" | jq_ "d.get('keyringAvailable')")
  A_MODE=$(curl -s -H "Authorization: Bearer $ATOK" "$EP_AGENT_A_URL/v1/config" | jq_ "d.get('securityMode', d.get('values', {}).get('securityMode'))")
  C_MODE=$(curl -s -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/config" | jq_ "d.get('securityMode', d.get('values', {}).get('securityMode'))")
  echo "  keyringAvailable=$KEYRING  agent.securityMode=$A_MODE  control.securityMode=$C_MODE"
  kill "$A_PID" 2>/dev/null; wait "$A_PID" 2>/dev/null; A_PID=""
  for url in "$EP_AGENT_A_URL" "$EP_CONTROL_URL" "$EP_GATEWAY_URL" "$EP_LIBRARY_URL"; do kill_port "$(port_of "$url")"; done
  sleep 1
  (cd a && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$A_PORT" "$EP_AGENT_PY" -m eugene_plexus_agent >> ../agent-a.log 2>&1) &
  A_PID=$!
  if wait_healthy "$EP_AGENT_A_URL" && wait_healthy "$EP_CONTROL_URL"; then
    ok "agent A and the control root are back from the same state directory"
  else
    bad "the restart did not come back"; tail -30 agent-a.log
  fi
  UNLOCKED=$(curl -s "$EP_AGENT_A_URL/v1/auth/status" | jq_ "d.get('unlocked')")
  NODES=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/nodes")
  if [ "$KEYRING" = "True" ]; then
    [ "$A_MODE" = "os_keyring" ] && ok "this host has a keyring, so the wizard defaulted the agent to os_keyring" \
      || bad "keyring available but the agent's securityMode is '$A_MODE'"
    [ "$C_MODE" = "os_keyring" ] && ok "and wrote the same to the control root" \
      || bad "keyring available but control's securityMode is '$C_MODE' -- the agent-only write is back"
    [ "$UNLOCKED" = "True" ] && ok "the agent unlocked itself from the keyring" \
      || bad "the agent came back sealed (unlocked=$UNLOCKED)"
    [ "$NODES" = "200" ] && ok "the control root answers its registry with nobody signed in" \
      || bad "the control root came back sealed (HTTP $NODES on /v1/nodes)"
    # Leave the machine as it was found: flipping back deletes this
    # throwaway install's keyring entries. They are scoped per install
    # since S0, so the live install's entry was never in reach -- and a
    # run should not leave secrets behind either way.
    curl -s -o /dev/null -X PATCH "$EP_AGENT_A_URL/v1/config" -H "Authorization: Bearer $ATOK" -H 'content-type: application/json' -d '{"securityMode":"prompt_on_startup"}'
    curl -s -o /dev/null -X PATCH "$EP_CONTROL_URL/v1/config" -H "Authorization: Bearer $CTOK" -H 'content-type: application/json' -d '{"securityMode":"prompt_on_startup"}'
    ok "flipped both back to prompt_on_startup, which deletes the throwaway keyring entries"
  else
    [ "$A_MODE" = "prompt_on_startup" ] && ok "no keyring on this host, so the wizard kept prompt_on_startup and said so" \
      || bad "no keyring but the agent's securityMode is '$A_MODE'"
    [ "$UNLOCKED" = "False" ] && ok "the agent is sealed after the restart, as prompt_on_startup documents" \
      || bad "unlocked=$UNLOCKED after a restart with no keyring"
    [ "$NODES" = "503" ] && ok "the control root is sealed too; sign-in is what opens it" \
      || bad "expected 503 Locked from the sealed root, got $NODES"
    CTOK=$(ctl_login); ATOK=$(login_retry "$EP_AGENT_A_URL")
    [ -n "$CTOK" ] && [ -n "$ATOK" ] && ok "signed in again so the rest of the run has an open install" \
      || bad "could not sign back in after the restart"
  fi
fi

# --- 3. onboarding host B without a browser -------------------------------------
say "3. host B joins with a minted token, on its own terminal"
# No grants: B runs no gateway, so nothing it signs may be `sub: gateway`
# anywhere but on its own machine.
TOKEN=$(curl -s -X POST "$EP_CONTROL_URL/v1/nodes/join-token" -H "Authorization: Bearer $CTOK" -H 'content-type: application/json' -d '{"nodeName":"node-b"}' | jq_ "d.get('token','')")
[ -n "$TOKEN" ] && ok "join token minted at the control root" || { bad "no join token"; exit 1; }

# The refusal first, against a directory that already has a control plane
# in it. Joining there would leave a rival root running, which is the
# exact failure the seeding rule exists to prevent. (Nothing is started
# from `seeded/`, so its declared port is never bound.)
printf 'components:\n  - name: control\n    kind: control\n    url: http://127.0.0.1:9083\n    spawn:\n      configFile: control.yaml\nruntimes: []\n' > seeded/agent.yaml
JOIN_REFUSED=$( (cd seeded && env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml "$EP_AGENT_PY" -m eugene_plexus_agent join --control "$EP_CONTROL_URL" --token "$TOKEN" 2>&1); echo "rc=$?" )
printf '%s' "$JOIN_REFUSED" | grep -q "rc=2" && ok "join refuses a machine that already has components declared" || bad "join did not refuse a seeded machine: $JOIN_REFUSED"
printf '%s' "$JOIN_REFUSED" | grep -q -- "--force" && ok "...and the refusal names the override" || bad "the refusal does not name --force"
[ -f seeded/node.yaml ] && bad "a refused join still wrote node.yaml" || ok "a refused join recorded nothing"

# Now the real one. No app, no browser, nothing running on B.
(cd b && env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$B_PORT" \
    "$EP_AGENT_PY" -m eugene_plexus_agent join --control "$EP_CONTROL_URL" --token "$TOKEN" \
    --name node-b --advertise "$EP_AGENT_B_URL" > ../join-b.log 2>&1)
JOIN_RC=$?
[ "$JOIN_RC" = "0" ] && ok "eugene-plexus-agent join enrolled host B with nothing running there" || { bad "join failed (rc=$JOIN_RC)"; cat join-b.log; }
[ -f b/node.yaml ] && ok "node.yaml written on B" || bad "no node.yaml on B"
grep -q "signingPrivateKey" b/node.yaml && ok "B minted a signing identity, so it can re-advertise later" || bad "B has no signing key"
# What B holds after joining, read the way its agent reads it. Its token
# key never left it; it pinned the root's identity; and the bundle it kept
# beside node.yaml verifies against that pin and already lists B's key.
JOINED=$("$EP_AGENT_PY" - <<'PY'
import json
import yaml
from eugene_plexus_agent import tokens
record = yaml.safe_load(open("b/node.yaml", encoding="utf-8")) or {}
out = {
    "tokenKey": bool(record.get("tokenPrivateKey")),
    "pinned": bool(record.get("controlPublicKey")),
    "installKey": "signingKey" in record or "signingKeyId" in record,
    "tokenPublic": None,
    "bundleListsSelf": False,
    "bundleError": None,
}
if record.get("tokenPrivateKey") and record.get("controlPublicKey"):
    key = tokens.load_private(record["tokenPrivateKey"])
    out["tokenPublic"] = tokens.public_b64(key)
    try:
        kept = json.load(open("b/trust_bundle.json", encoding="utf-8"))["jws"]
        bundle = tokens.parse_bundle(kept, authority=record["controlPublicKey"])
        own = bundle.keys.get(tokens.thumbprint(key))
        out["bundleListsSelf"] = own is not None and own.issuer == "node:node-b"
    except Exception as exc:
        out["bundleError"] = str(exc)
print(json.dumps(out))
PY
)
[ "$(echo "$JOINED" | jq_ "d['tokenKey'] and d['pinned'] and not d['installKey']")" = "True" ] \
  && ok "B generated its own token key and pinned the root's identity; no install key crossed the wire" || bad "B's node.yaml: $JOINED"
[ "$(echo "$JOINED" | jq_ "d['bundleListsSelf']")" = "True" ] \
  && ok "B's kept trust bundle verifies against the pinned root and lists B's own key as node:node-b" || bad "B's kept bundle: $JOINED"
NODE_B=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK")
echo "$NODE_B" | jq_ "d.get('signingPublicKey') and 'yes' or 'no'" | grep -q yes \
  && ok "the root recorded B's signing public key" || bad "the root has no signing key for B"
B_TOKEN_PUBLIC=$(echo "$JOINED" | jq_ "d['tokenPublic']")
[ "$(echo "$NODE_B" | jq_ "d.get('tokenPublicKey')")" = "$B_TOKEN_PUBLIC" ] \
  && ok "the root recorded the public half of the token key in B's node.yaml, and only that" || bad "the root's token key for B differs from B's own"

# --- 4. and the next start does not raise a rival control plane ------------------
say "4. host B starts, and is a worker rather than a second install"
(cd b && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$B_PORT" "$EP_AGENT_PY" -m eugene_plexus_agent > ../agent-b.log 2>&1) &
B_PID=$!
wait_healthy "$EP_AGENT_B_URL" && ok "agent B answering on :$B_PORT" || { bad "agent B never came up"; tail -30 agent-b.log; exit 1; }
grep -q "first boot: declared the default topology" agent-b.log \
  && bad "agent B declared a control plane of its own -- the rival-root failure" \
  || ok "agent B declared nothing; it gets its topology from the install"
# **A joined node has no passphrase of its own, and is a console anyway.**
# Signing in there forwards the passphrase to the control root with B's own
# token as proof of which machine is asking, and the root's session comes
# back addressed to node:node-b and to the root. Until 2026-09-25 this
# answered 503 and named the root instead, because the root's session was
# accepted here only by sharing the install's key.
BTOK=$(login_retry "$EP_AGENT_B_URL")
[ "$(aud_of "$BTOK")" = "node:node-b,control" ] \
  && ok "signing in at a joined node gives a root session addressed to node:node-b and the root" \
  || bad "B's sign-in gave aud=$(aud_of "$BTOK")"
[ "$(code_of "$EP_AGENT_B_URL/v1/node" "$BTOK")" = "200" ] \
  && ok "B's session opens B" || bad "B refused the session its own sign-in got"
[ "$(code_of "$EP_AGENT_B_URL/v1/node" "$CTOK")" = "401" ] \
  && ok "the root's own session (aud control) is refused by B: a session opens only where it is addressed" || bad "B accepted a session addressed only to the root"
curl -s "$EP_AGENT_B_URL/v1/node" -H "Authorization: Bearer $BTOK" | jq_ "d.get('enrolled')" | grep -q True \
  && ok "B reports itself enrolled" || bad "B does not report itself enrolled"

# --- 5. the defect: a node that moves house says so ------------------------------
say "5. a node whose address changes tells the root -- the M9 defect"
BEFORE=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('url','')")
printf '  recorded before: %s\n' "$BEFORE"
[ -n "$BEFORE" ] && ok "the root holds an address for B" || bad "the root has no address for B"

# Change it through the config trio, which is the operator-facing way.
# Deliberately an address nothing is listening on: per the standing rule,
# an expert override has to win *including with a value that will fail*,
# or it is not an override. It also keeps this distinct from the address
# section 6 re-derives, so that section's announcement is a real change
# rather than a no-op -- which the first run of this script got wrong,
# and then reported a correct no-op as a missing announcement.
MOVED="${EP_MOVED_URL%/}"
curl -s -o /dev/null -X PATCH "$EP_AGENT_B_URL/v1/config" -H "Authorization: Bearer $BTOK" \
  -H 'content-type: application/json' -d "{\"advertiseUrl\":\"$MOVED\"}"
for _ in $(seq 1 15); do
  AFTER=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('url','')")
  [ "${AFTER%/}" = "$MOVED" ] && break
  sleep 1
done
[ "${AFTER%/}" = "$MOVED" ] && ok "the root followed B to $MOVED without a re-enrollment" || bad "the root still has $AFTER"
SEQ=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('advertiseSequence',0)")
[ "$SEQ" -ge 1 ] && ok "announcement sequence is $SEQ, recorded in applied state" || bad "sequence did not advance"

# A replay of an old announcement must not move it back. The signature is
# valid -- that is the point; only the counter refuses it.
REPLAY=$(curl -s -o /dev/null -w '%{http_code}' -X PATCH "$EP_CONTROL_URL/v1/nodes/node-b" \
  -H 'content-type: application/json' \
  -d "{\"url\":\"$BEFORE\",\"sequence\":1,\"signature\":\"$(printf 'x%.0s' {1..86})=\"}")
[ "$REPLAY" = "401" ] || [ "$REPLAY" = "409" ] && ok "an unsigned/stale announcement is refused ($REPLAY)" || bad "a forged announcement answered $REPLAY"
STILL=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('url','')")
[ "${STILL%/}" = "$MOVED" ] && ok "...and B is still at $MOVED" || bad "the forged announcement moved B to $STILL"

# --- 6. announce on startup, which is the case that actually matters -------------
say "6. B restarts on a different port and announces it without being asked"
kill "$B_PID" 2>/dev/null; wait "$B_PID" 2>/dev/null; B_PID=""
# Clear the operator's override so the agent re-derives, which is what a
# rebooted host does. The persisted value is deliberately NOT trusted.
python - "$EP_WORKDIR/b/agent.yaml" <<'PY'
import sys, yaml
p = sys.argv[1]
doc = yaml.safe_load(open(p, encoding="utf-8")) or {}
doc.pop("advertiseUrl", None)
open(p, "w", encoding="utf-8").write(yaml.safe_dump(doc, sort_keys=True))
PY
(cd b && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$B2_PORT" "$EP_AGENT_PY" -m eugene_plexus_agent > ../agent-b2.log 2>&1) &
B_PID=$!
wait_healthy "$EP_AGENT_B2_URL" && ok "agent B back on :$B2_PORT" || { bad "agent B never came back"; tail -30 agent-b2.log; }
for _ in $(seq 1 20); do
  REDERIVED=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('url','')")
  printf '%s' "$REDERIVED" | grep -q ":$B2_PORT" && break
  sleep 1
done
printf '%s' "$REDERIVED" | grep -q ":$B2_PORT" \
  && ok "B re-derived its address at boot and announced $REDERIVED" \
  || bad "the root still has $REDERIVED; announce-on-startup did not happen"
grep -q "told the control root this node is now reachable" agent-b2.log \
  && ok "B logged the announcement" || bad "no announcement in agent-b2.log"

# And a restart that has nothing to report must cost the log nothing --
# otherwise every reboot of every node grows it with uptime rather than
# with events.
SEQ_BEFORE=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('advertiseSequence',0)")
kill "$B_PID" 2>/dev/null; wait "$B_PID" 2>/dev/null
(cd b && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$B2_PORT" "$EP_AGENT_PY" -m eugene_plexus_agent > ../agent-b3.log 2>&1) &
B_PID=$!
wait_healthy "$EP_AGENT_B2_URL" && ok "agent B restarted at the same address" || bad "agent B did not come back"
sleep 3
SEQ_AFTER=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('advertiseSequence',0)")
[ "$SEQ_AFTER" = "$SEQ_BEFORE" ] && ok "a restart that did not move recorded nothing (sequence still $SEQ_AFTER)" || bad "an unchanged restart advanced the root's sequence $SEQ_BEFORE -> $SEQ_AFTER"

# --- 7. leaving ------------------------------------------------------------------
say "7. B leaves the install: it stops trusting the root, and the root drops its key"
# A session from B's own sign-in: addressed to node:node-b, so B takes it,
# and to the root, so B can forward it to the root's DELETE unchanged.
BTOK2=$(login_retry "$EP_AGENT_B2_URL")
LEFT=$(curl -s -X POST "$EP_AGENT_B2_URL/v1/node/unenroll" -H "Authorization: Bearer $BTOK2" -H 'content-type: application/json' -d '{}')
printf '%s' "$LEFT" | jq_ "d.get('controlNotified')" | grep -q True && ok "B told the root on the way out" || bad "controlNotified was not true: $LEFT"
printf '%s' "$LEFT" | jq_ "d.get('identity',{}).get('enrolled')" | grep -q False && ok "B reports itself unenrolled" || bad "B still reports enrolled"
LEFT_STATE=$("$EP_AGENT_PY" - <<'PY'
import json
import yaml
from eugene_plexus_agent import tokens
record = yaml.safe_load(open("b/node.yaml", encoding="utf-8")) or {}
out = {
    "pinsRoot": bool(record.get("controlPublicKey") or record.get("controlUrl")),
    "ownKeys": bool(record.get("signingPrivateKey") and record.get("tokenPrivateKey")),
    "selfSigned": False,
    "bundleError": None,
}
try:
    kept = json.load(open("b/trust_bundle.json", encoding="utf-8"))["jws"]
    bundle = tokens.parse_bundle(kept, authority=record.get("signingPublicKey") or "")
    issuers = sorted(k.issuer for k in bundle.keys.values())
    out["selfSigned"] = issuers == ["node:local"]
except Exception as exc:
    out["bundleError"] = str(exc)
print(json.dumps(out))
PY
)
[ "$(echo "$LEFT_STATE" | jq_ "d['pinsRoot']")" = "False" ] && ok "B no longer pins the root: node.yaml names no control root and no root identity" || bad "B still pins the root: $LEFT_STATE"
[ "$(echo "$LEFT_STATE" | jq_ "d['ownKeys']")" = "True" ] && ok "B kept its own keypairs, which are the host's and not the install's" || bad "B discarded its own identity too: $LEFT_STATE"
[ "$(echo "$LEFT_STATE" | jq_ "d['selfSigned']")" = "True" ] && ok "B's kept bundle is its own now: signed by its identity key, naming only itself as node:local" || bad "B's kept bundle after leaving: $LEFT_STATE"
# Revoking drops B's key from the bundle and rotates nothing, so the root's
# registry and bundle forget B while every other session keeps working --
# including the one this run has held since before B left.
curl -s "$EP_CONTROL_URL/v1/nodes" -H "Authorization: Bearer $CTOK" | jq_ "'node-b' in [n['name'] for n in d.get('nodes',[])]" | grep -q False \
  && ok "the root no longer lists node-b -- read with the session minted before B left, which still works" || bad "node-b is still in the registry (or the root session stopped working)"
ROOT_KIDS=$(curl -s "$EP_CONTROL_URL/v1/trust/bundle" | PYTHONUTF8=1 python -c "import sys,json,base64; p=json.load(sys.stdin)['jws'].split('.')[1]; b=json.loads(base64.urlsafe_b64decode(p + '=' * (-len(p) % 4))); print(sorted(k['issuer'] for k in b['keys']))")
printf '%s' "$ROOT_KIDS" | grep -q "node:node-b" && bad "the root's bundle still lists node:node-b: $ROOT_KIDS" || ok "the root's trust bundle no longer lists B's key: $ROOT_KIDS"
[ "$(code_of "$EP_AGENT_A_URL/v1/node" "$ATOK")" = "200" ] && ok "A's session still opens A: nobody else was signed out" || bad "A's session stopped working when B left"

say "done"
if [ "$FAILURES" -eq 0 ]; then
  printf '\nALL %d CHECKS PASSED\n' "$PASSES"
else
  printf '\n%d CHECK(S) FAILED, %d passed\n' "$FAILURES" "$PASSES"
fi
printf '\nlogs in %s\n' "$EP_WORKDIR"
printf 'WHAT THIS PROVES AND DOES NOT\n'
printf '  proves: a fresh machine declares its own control plane with no config file\n'
printf '          and no browser (on the contract ports only); `join` onboards a second\n'
printf '          machine from a terminal and leaves it a worker rather than a rival\n'
printf '          root, holding its own token key; a worker is a console, its sign-in\n'
printf '          the root'"'"'s; a node that moves tells the root, signed, on a config\n'
printf '          change AND on a restart, with replays refused; un-enrolling leaves a\n'
printf '          node trusting only itself, and the root drops its key without signing\n'
printf '          anyone else out.\n'
printf '  cannot: a node genuinely offline while it moves; two real hosts (that is\n'
printf '          m7-acceptance.sh in EP_MODE=two-host); a tailnet address changing\n'
printf '          under a running install, which is what this simulates with a port.\n'
exit "$FAILURES"
