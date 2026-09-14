#!/usr/bin/env bash
# One passphrase, one prompt: signing in to the UI unlocks a sealed control root.
#
# Reported from the live install (2026-09-13): after a container update the
# UI asked for the passphrase at sign-in and /nodes asked for it again --
# only the Nodes screen ever posted it to the control root, which seals its
# signing key on every restart and, in a container, has no keyring to open
# it. The login page posts the same passphrase to the root now.
#
# The checks:
#   0. isolated from any install on this machine
#   1. agent + control up; both initialized with ONE passphrase; the agent enrolled
#   2. the root is restarted and comes back LOCKED (503 Locked on /v1/nodes)
#   3. BROWSER: signing in through the form leaves the root answering 200
#   4. a wrong passphrase at the agent never reaches the root (rate-limit budget intact)
#   5. teardown by pid
#
# Safe beside a live install: environment cleared, +100 ports, teardown by
# pid. Never `pkill -f eugene_plexus_`.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-login-unlock}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"; CTL_PORT="${EP_CTL_PORT:-8183}"
GW_PORT="${EP_GW_PORT:-8180}"; LIB_PORT="${EP_LIB_PORT:-8182}"
AGENT="http://127.0.0.1:$AGENT_PORT"; CTL="http://127.0.0.1:$CTL_PORT"
PASS="unlock-live-$$"
OWNED_PORTS="$AGENT_PORT $CTL_PORT $GW_PORT $LIB_PORT"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
A_PID=""
teardown() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 3; }
  for p in $OWNED_PORTS; do for pid in $(listening_pids "$p"); do taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null; done; done
}

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
ok "agent python; every port free"
rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

say "0. isolate"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
WORK_NATIVE=$(cygpath -w "$WORK" 2>/dev/null || printf '%s' "$WORK")
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }

cat > agent.yaml <<YAML
firstRunComplete: true
components:
  - name: control
    kind: control
    url: http://127.0.0.1:$CTL_PORT
    spawn:
      configFile: control.yaml
  - name: gateway
    kind: gateway
    url: http://127.0.0.1:$GW_PORT
    spawn:
      configFile: gateway.yaml
  - name: library
    kind: library
    url: http://127.0.0.1:$LIB_PORT
    spawn:
      configFile: library.yaml
runtimes: []
YAML
echo "logLevel: INFO" > control.yaml; echo "logLevel: INFO" > gateway.yaml; printf 'logLevel: INFO\nmodelRoots: []\n' > library.yaml

say "1. agent and control, one passphrase"
(exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
  "$PY" -m eugene_plexus_agent --unattended > agent.log 2>&1) &
A_PID=$!
wait_healthy "$AGENT" 60 && wait_healthy "$CTL" 90 || { bad "agent/control never came up"; tail -20 agent.log; exit 1; }
[ "$(code_of -X POST "$CTL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}")" = "204" ] || { bad "control initialize"; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "agent initialize"; exit 1; }
wait_healthy "$CTL" 90 || { bad "control did not come back after initialize"; exit 1; }
# Enroll the agent, as the wizard does for the control host's own agent
# (M9): an unenrolled agent mints its own signing key per restart while the
# root mints the install's, so no session token reaches the root at all --
# which is a different 401 from the one this script is about, and the
# first run of this script confused the two.
CTOK=$(curl -s -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
JOIN=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"root-node"}' | jq_ "d['token']")
[ "$(code_of -X POST -H "Authorization: Bearer $TOK" "$AGENT/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$JOIN\",\"name\":\"root-node\"}")" = "200" ] || { bad "enroll failed"; tail -20 agent.log; exit 1; }
# Enrollment replaced the agent's key, so the session that asked is dead
# (by design); the children restart on the install key.
wait_healthy "$CTL" 90 && wait_healthy "$AGENT" 60 || { bad "fleet did not come back after enrollment"; exit 1; }
sleep 2
TOK=$(curl -s -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "no session after enrollment"; exit 1; }
[ "$(code_of -H "Authorization: Bearer $TOK" "$CTL/v1/nodes")" = "200" ] && ok "enrolled; one passphrase; the agent's session reaches the root's /v1/nodes" || bad "root not answering after init: $(curl -s -H "Authorization: Bearer $TOK" "$CTL/v1/nodes" | head -c 200)"

say "2. restart the root; it comes back sealed"
curl -s -o /dev/null -X POST "$AGENT/v1/components/control/restart" -H "Authorization: Bearer $TOK" -d '{}'
sleep 3; wait_healthy "$CTL" 90 || { bad "control did not come back"; exit 1; }
R=$(curl -s -w '\n%{http_code}' -H "Authorization: Bearer $TOK" "$CTL/v1/nodes"); CODE=$(echo "$R" | tail -1); BODY=$(echo "$R" | sed '$d')
[ "$CODE" = "503" ] && printf '%s' "$BODY" | grep -q '"Locked"' && ok "restarted root: 503 Locked on /v1/nodes (its health says ok: $(curl -s "$CTL/healthz" | jq_ "d['status']"))" || { bad "expected 503 Locked, got $CODE $BODY"; exit 1; }

say "3. the browser signs in through the form; the root is open afterwards"
(cd "$UI_DIR" && EP_UI_URL="$AGENT" EP_PASSPHRASE="$PASS" npx playwright test e2e/login-unlock.spec.ts > "$WORK/playwright.log" 2>&1)
PW=$?; echo "  $(grep -E 'passed|failed' "$WORK/playwright.log" | tail -1)"
[ "$PW" = "0" ] && ok "browser: sign-in left the control root answering /v1/nodes" || { bad "browser spec failed"; tail -30 "$WORK/playwright.log"; }
[ "$(code_of -H "Authorization: Bearer $TOK" "$CTL/v1/nodes")" = "200" ] && ok "confirmed from the shell: the root is unlocked" || bad "root still locked after sign-in"

say "4. a wrong passphrase at the agent never reaches the root"
curl -s -o /dev/null -X POST "$AGENT/v1/components/control/restart" -H "Authorization: Bearer $TOK" -d '{}'
sleep 3; wait_healthy "$CTL" 90
[ "$(code_of -H "Authorization: Bearer $TOK" "$CTL/v1/nodes")" = "503" ] || { bad "root did not re-seal"; }
[ "$(code_of -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' -d '{"passphrase":"wrong"}')" = "401" ] && ok "agent refuses the wrong passphrase" || bad "agent accepted a wrong passphrase?"
# Not a UI check -- the login page only asks the root after the agent says
# yes -- but the root's own rate-limit budget is what a leaked second
# prompt would spend. It stays sealed and unbothered.
[ "$(code_of -H "Authorization: Bearer $TOK" "$CTL/v1/nodes")" = "503" ] && ok "the root is still sealed and was not asked" || bad "root state changed"

say "5. teardown by pid"
teardown; A_PID=""
LEFT=""; for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && LEFT="$LEFT $p"; done
[ -z "$LEFT" ] && ok "no owned port still listening" || bad "still listening:$LEFT"

say "done"
if [ "$FAILURES" -eq 0 ]; then printf '\nALL CHECKS PASSED\n'; else printf '\n%s CHECK(S) FAILED\n' "$FAILURES"; exit 1; fi
