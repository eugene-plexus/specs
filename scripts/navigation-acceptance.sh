#!/usr/bin/env bash
# The install as a tree, and a page menu for whatever is selected.
#
# Design: docs/design/ui-tree-navigation.md. Its §0 measured what this
# replaces: a Config tab strip that grew as `1 + nodes + up-to-3
# singletons + every driver` -- 54 buttons on a ten-node install with
# four models each -- because one screen held every object.
#
# The checks:
#   0. isolated from any install on this machine
#   1. the UI wheel staged from this working tree, so the agent serves THIS build
#   2. agent + control + gateway + library up, initialized, the agent enrolled
#   3. a driver declared, so the deepest path in the tree has something in it
#   4. the agent serves the UI at / and every screen's route exists
#   5. BROWSER: the install and its five branches
#   6. BROWSER: every object selects and arrives, walking what the tree offers
#   7. BROWSER: each object's page menu, and moving between one object's pages
#   8. BROWSER: a driver under its machine; a legacy ?tab= link
#   9. BROWSER: the layer colours; sign out everywhere; the phone drawer; the map
#  10. teardown by pid
#
# Safe beside a live install: environment cleared, +100 ports, teardown by
# pid. Never `pkill -f eugene_plexus_`.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-navigation}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"; CTL_PORT="${EP_CTL_PORT:-8183}"
GW_PORT="${EP_GW_PORT:-8180}"; LIB_PORT="${EP_LIB_PORT:-8182}"
AGENT="http://127.0.0.1:$AGENT_PORT"; CTL="http://127.0.0.1:$CTL_PORT"
PASS="nav-accept-$$"
OWNED_PORTS="$AGENT_PORT $CTL_PORT $GW_PORT $LIB_PORT"
SKIP_BUILD="${EP_SKIP_BUILD:-0}"

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
# install.ps1 writes EUGENE_PLEXUS_AGENT_CONFIG_FILE into the USER
# environment, so every shell on this account inherits it and a throwaway
# agent would adopt the live install's identity -- and, since M9's
# announce-on-start, tell the real control root the node had moved here.
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
WORK_NATIVE=$(cygpath -w "$WORK" 2>/dev/null || printf '%s' "$WORK")
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }

say "1. stage this working tree's UI into the wheel the agent serves"
# The agent venv on this box has eugene-plexus-ui installed EDITABLE from
# the ui checkout, so it serves whatever build:python last staged. Without
# this step the run would assert about the previously staged build.
if [ "$SKIP_BUILD" = "1" ]; then
  ok "skipped by EP_SKIP_BUILD=1 (asserting about the already-staged build)"
else
  (cd "$UI_DIR" && npm run build:python > "$WORK/build.log" 2>&1)
  [ $? = 0 ] && ok "npm run build:python staged the export" || { bad "build failed"; tail -30 "$WORK/build.log"; exit 1; }
fi
STATIC="$UI_DIR/python/eugene_plexus_ui/static"
grep -qr 'data-tree-sel' "$STATIC/_next/static/chunks" 2>/dev/null \
  && ok "the staged bundle carries the tree's data-tree-sel contract" \
  || bad "no data-tree-sel in the staged bundle -- the agent would serve a pre-tree build"

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
echo "logLevel: INFO" > control.yaml
echo "logLevel: INFO" > gateway.yaml
printf 'logLevel: INFO\nmodelRoots: []\n' > library.yaml

say "2. four processes, one passphrase, the agent enrolled"
(exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
  "$PY" -m eugene_plexus_agent --unattended > agent.log 2>&1) &
A_PID=$!
wait_healthy "$AGENT" 60 && wait_healthy "$CTL" 90 || { bad "agent/control never came up"; tail -20 agent.log; exit 1; }
[ "$(code_of -X POST "$CTL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}")" = "204" ] || { bad "control initialize"; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "agent initialize"; exit 1; }
wait_healthy "$CTL" 90 || { bad "control did not come back after initialize"; exit 1; }
# The control host's own agent enrolls too (M9): unenrolled, it mints a
# fresh signing key per restart while the root mints the install's, so no
# browser session could reach /nodes at all.
CTOK=$(curl -s -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
JOIN=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"nav-node"}' | jq_ "d['token']")
[ "$(code_of -X POST -H "Authorization: Bearer $TOK" "$AGENT/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$JOIN\",\"name\":\"nav-node\"}")" = "200" ] || { bad "enroll failed"; tail -20 agent.log; exit 1; }
wait_healthy "$CTL" 90 && wait_healthy "$AGENT" 60 || { bad "fleet did not come back after enrollment"; exit 1; }
sleep 2
TOK=$(curl -s -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "no session after enrollment"; exit 1; }
[ "$(code_of -H "Authorization: Bearer $TOK" "$CTL/v1/nodes")" = "200" ] && ok "four processes; enrolled; the session reaches the root" || bad "root not answering"

say "3. a driver, so the tree's deepest path is not empty"
# type -> node -> driver is the only three-level path in the tree, and a
# fleet with no drivers cannot exercise it. An openai_compat_http driver
# pointed at nothing is enough: the tree is about topology, not health.
DRIVER=tree-probe
DRV_CODE=$(code_of -X POST -H "Authorization: Bearer $TOK" -H 'content-type: application/json'   "$AGENT/v1/components"   -d "{\"name\":\"$DRIVER\",\"kind\":\"inference-driver\",\"url\":\"http://127.0.0.1:8181/\",\"spawn\":{\"configFile\":\"$DRIVER.yaml\"}}")
[ "$DRV_CODE" = "201" ] || [ "$DRV_CODE" = "200" ] && ok "declared the driver '$DRIVER'" || bad "declaring a driver returned $DRV_CODE"
sleep 2

say "4. the agent serves every screen's route"
[ "$(code_of "$AGENT/")" = "200" ] && ok "the agent serves the UI at /" || bad "no UI at /"
MISSING=""
for r in playground library discover inference metrics nodes config login setup runtimes; do
  [ "$(code_of "$AGENT/$r/")" = "200" ] || MISSING="$MISSING /$r"
done
[ -z "$MISSING" ] && ok "every route is served: /, /playground, /library, /discover, /inference, /metrics, /nodes, /config, /login, /setup, /runtimes" || bad "not served:$MISSING"

say "5-9. the browser drives the tree, and Home (S1)"
(cd "$UI_DIR" && EP_UI_URL="$AGENT" EP_PASSPHRASE="$PASS" EP_DRIVER_NAME="$DRIVER" npx playwright test e2e/tree.spec.ts e2e/home.spec.ts > "$WORK/playwright.log" 2>&1)
PW=$?
sed -n '/Running/,$p' "$WORK/playwright.log" | grep -E '^\s+[✓✘×]|passed|failed' | head -20
if [ "$PW" = "0" ]; then
  for t in \
    "shows the install and its five branches" \
    "every object in the tree selects and arrives" \
    "the page menu lists the pages each object owns" \
    "moving between one object's pages keeps that object selected" \
    "a driver sits under its machine once there are two, straight under its type with one, and opens its own settings" \
    "a bare /config lands on this machine's agent" \
    "a legacy ?tab= link still lands on its subject" \
    "the layer colours are still the architecture page's" \
    "sign out is reachable from every page" \
    "the tree is a drawer on a phone, and a tap outside closes it" \
    "the layer map still explains all eight layers" \
    "signing in lands on Home, and Home has a primary action instead of a disabled box" \
    "the tasks tray opens, says what is running, and closes on Escape" \
    "the playground still exists, one page over"; do
    grep -qF "$t" "$WORK/playwright.log" && ok "browser: $t" || bad "browser: '$t' did not run"
  done
else
  bad "the navigation spec failed"
  tail -60 "$WORK/playwright.log"
fi

say "result"
if [ "$FAILURES" = "0" ]; then printf '  ALL CHECKS PASSED\n'; else printf '  %d CHECK(S) FAILED\n' "$FAILURES"; fi
exit "$FAILURES"
