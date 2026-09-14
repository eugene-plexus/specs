#!/usr/bin/env bash
# One navigation, everywhere, in the architecture page's own vocabulary.
#
# Design: docs/design/ui-navigation.md. Its §0 measured what this replaces:
# seven screens with seven different hand-written header rows, /metrics and
# /nodes reachable only by going back to the playground, "Back" meaning two
# different places, Sign out on exactly one screen, and zero occurrences of
# aria-current, usePathname or a skip link anywhere in the app.
#
# The checks:
#   0. isolated from any install on this machine
#   1. the UI wheel staged from this working tree, so the agent serves THIS build
#   2. agent + control + gateway + library up, initialized, the agent enrolled
#   3. the agent serves the UI at / and every screen's route exists
#   4. BROWSER: every screen reachable from every screen; each link arrives
#   5. BROWSER: sign out on all seven
#   6. BROWSER: the icons and colours are the website's
#   7. BROWSER: every screen names its layer; /inference names three, in three colours
#   8. BROWSER: the layer map holds all eight layers and all seven screens; Escape closes it
#   9. BROWSER: the skip link is the first thing Tab reaches
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
grep -qr 'data-icon' "$STATIC/_next/static/chunks" 2>/dev/null \
  && ok "the staged bundle carries the nav's data-icon contract" \
  || bad "no data-icon in the staged bundle -- the agent would serve a pre-navigation build"

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

say "3. the agent serves every screen's route"
[ "$(code_of "$AGENT/")" = "200" ] && ok "the agent serves the UI at /" || bad "no UI at /"
MISSING=""
for r in library discover inference metrics nodes config login setup runtimes; do
  [ "$(code_of "$AGENT/$r/")" = "200" ] || MISSING="$MISSING /$r"
done
[ -z "$MISSING" ] && ok "every route is served: /, /library, /discover, /inference, /metrics, /nodes, /config, /login, /setup, /runtimes" || bad "not served:$MISSING"

say "4-9. the browser drives the navigation"
(cd "$UI_DIR" && EP_UI_URL="$AGENT" EP_PASSPHRASE="$PASS" npx playwright test e2e/navigation.spec.ts > "$WORK/playwright.log" 2>&1)
PW=$?
sed -n '/Running/,$p' "$WORK/playwright.log" | grep -E '^\s+[✓✘×]|passed|failed' | head -20
if [ "$PW" = "0" ]; then
  for t in \
    "every screen is reachable from every screen" \
    "each link actually navigates to its screen" \
    "sign out is on every screen" \
    "the icons and colours are the architecture page's" \
    "each screen says which layer it is in" \
    "inference shows all three of its layers, in three colours" \
    "the layer map shows the whole system, and Escape closes it" \
    "the skip link is the first thing a keyboard reaches"; do
    grep -qF "$t" "$WORK/playwright.log" && ok "browser: $t" || bad "browser: '$t' did not run"
  done
else
  bad "the navigation spec failed"
  tail -60 "$WORK/playwright.log"
fi

say "result"
if [ "$FAILURES" = "0" ]; then printf '  ALL CHECKS PASSED\n'; else printf '  %d CHECK(S) FAILED\n' "$FAILURES"; fi
exit "$FAILURES"
