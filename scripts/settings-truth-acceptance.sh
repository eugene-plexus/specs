#!/usr/bin/env bash
# Settings never lie (Troy, 2026-09-29: fundamental), against a real install.
#
# Design: docs/design/settings-accuracy.md. A throwaway install whose files
# hold the states that used to lie -- an update channel never saved, a
# hand-edited value no dropdown offers, a number out of range, a restart
# saved but not taken, a share login with and without a password, a
# provider saved on a backend that has not restarted -- then the API says
# what each component serves, and a browser (the system Chrome) says what
# the Settings page shows for it.
#
# The checks:
#   0. isolated from any install on this machine
#   1. the UI staged from this working tree, and SERVED by the agent
#   2. agent + control + gateway + library up, initialized, enrolled
#   3. API: an update channel never saved is pending, not a default
#   4. API: the gateway says what unset means and where the root is
#   5. API: a restart is pending per PATCH, and says what runs meanwhile
#   6. API: share logins say whether a password is stored
#   7. API: a backend's saved provider waits for a restart; its address is the provider's own
#   8. API: securityMode is not requiresRestart
#   9. BROWSER: e2e/settings-truth.spec.ts
#  10. the channel the browser chose is in agent.yaml, and settled
#  11. teardown by pid
#
# Safe beside a live install: environment cleared, +400 ports, teardown by
# pid. Never `pkill -f eugene_plexus_`.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-settings-truth}"
AGENT_PORT="${EP_AGENT_PORT:-8479}"; CTL_PORT="${EP_CTL_PORT:-8483}"
GW_PORT="${EP_GW_PORT:-8480}"; LIB_PORT="${EP_LIB_PORT:-8482}"; DRV_PORT="${EP_DRV_PORT:-8481}"
AGENT="http://127.0.0.1:$AGENT_PORT"; CTL="http://127.0.0.1:$CTL_PORT"
GW="http://127.0.0.1:$GW_PORT"; LIB="http://127.0.0.1:$LIB_PORT"; DRV="http://127.0.0.1:$DRV_PORT"
PASS="settings-truth-$$"
NODE=truth-node
DRIVER=truth-probe
OWNED_PORTS="$AGENT_PORT $CTL_PORT $GW_PORT $LIB_PORT $DRV_PORT"
SKIP_BUILD="${EP_SKIP_BUILD:-0}"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
get() { curl -s -H "Authorization: Bearer $TOK" "$1"; }
patch() { curl -s -X PATCH -H "Authorization: Bearer $TOK" -H 'content-type: application/json' "$1" -d "$2"; }
field_of() { PYTHONUTF8=1 python -c "import sys,json; f=[x for x in json.load(sys.stdin)['fields'] if x['key']=='$1'][0]; print($2)"; }
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

say "1. stage this working tree's UI, and check the agent serves it"
if [ "$SKIP_BUILD" = "1" ]; then
  ok "skipped by EP_SKIP_BUILD=1"
else
  (cd "$UI_DIR" && npm run build:python > "$WORK/build.log" 2>&1)
  [ $? = 0 ] && ok "npm run build:python staged the export" || { bad "build failed"; tail -30 "$WORK/build.log"; exit 1; }
fi

# An install from before the channel had a default: a file with no
# updateChannel and no settled marker. Checks are off, so nothing settles
# it behind the run's back (a check would ask GitHub).
cat > agent.yaml <<YAML
firstRunComplete: true
updateChecks: false
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
# Hand-edited: a strategy no dropdown offers, a limit past its maximum.
printf 'logLevel: INFO\nloadBalancing: beta\nmaxImagesPerRequest: 1000\n' > gateway.yaml
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
CTOK=$(curl -s -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
JOIN=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d "{\"nodeName\":\"$NODE\"}" | jq_ "d['token']")
[ "$(code_of -X POST -H "Authorization: Bearer $TOK" "$AGENT/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$JOIN\",\"name\":\"$NODE\"}")" = "200" ] || { bad "enroll failed"; tail -20 agent.log; exit 1; }
wait_healthy "$CTL" 90 && wait_healthy "$AGENT" 60 && wait_healthy "$GW" 60 && wait_healthy "$LIB" 60 || { bad "fleet did not come back after enrollment"; exit 1; }
sleep 2
TOK=$(curl -s -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "no session after enrollment"; exit 1; }
ok "four processes; enrolled as $NODE"
FOUND=0
# The settings widget is a chunk the Settings page loads on demand, so it is
# named in no page's HTML: find it in what was STAGED, then require the agent
# to SERVE that same file with the marker in it (staging is not serving).
STAGED_CHUNKS="$UI_DIR/python/eugene_plexus_ui/static/_next/static/chunks"
for f in $(grep -l 'not one of the choices' "$STAGED_CHUNKS"/*.js 2>/dev/null); do
  curl -s "$AGENT/_next/static/chunks/$(basename "$f")" | grep -q 'not one of the choices' && FOUND=1 && break
done
[ "$FOUND" = "1" ] && ok "the agent SERVES this build (it carries 'not one of the choices')" || { bad "the agent serves another build -- is eugene-plexus-ui installed editable in the agent venv?"; exit 1; }

say "3. an update channel never saved is pending"
V=$(get "$AGENT/v1/config" | jq_ "d.get('updateChannel')")
[ "$V" = "None" ] && ok "GET /v1/config: updateChannel is null, not a default" || bad "updateChannel read '$V'"
M=$(get "$AGENT/v1/config/schema" | field_of updateChannel "f.get('unsetMeans') or ''")
case "$M" in *"Not decided yet"*) ok "the schema says what an unsaved channel means: $M" ;; *) bad "unsetMeans: '$M'" ;; esac
S=$(get "$AGENT/v1/node" | jq_ "(d['update'].get('channelSource'), d['update'].get('channel'))")
[ "$S" = "('pending', None)" ] && ok "GET /v1/node: channelSource pending, no channel guessed" || bad "update: $S"
[ -e "$WORK/.update-channel-settled" ] && bad "a settled marker exists before anything settled" || ok "nothing marked settled"

say "4. the gateway says what unset means, and where the root is"
GS=$(get "$GW/v1/config/schema")
C=$(printf '%s' "$GS" | field_of corsAllowedOrigins "f.get('unsetMeans') or ''")
case "$C" in *"any website"*) ok "an empty origin list is any website" ;; *) bad "corsAllowedOrigins unsetMeans: '$C'" ;; esac
R=""
for _ in $(seq 1 30); do
  R=$(get "$GW/v1/config/schema" | field_of controlUrl "f.get('unsetResolvesTo') or ''")
  [ -n "$R" ] && break; sleep 1
done
[ "$R" = "$CTL" ] && ok "an unset controlUrl names the root the last refresh found: $R" || bad "controlUrl unsetResolvesTo: '$R' (expected $CTL)"
LB=$(get "$GW/v1/config" | jq_ "d.get('loadBalancing')")
[ "$LB" = "beta" ] && ok "the hand-edited strategy is served as itself ('beta') for the page to show" || bad "loadBalancing: $LB"

say "5. a restart is pending per PATCH, and says what runs meanwhile"
P1=$(patch "$GW/v1/config" '{"logLevel":"DEBUG"}' | jq_ "(d['requiresRestart'], d.get('pendingRestart'))")
[ "$P1" = "(True, ['logLevel'])" ] && ok "a restart key: requiresRestart, pending [logLevel]" || bad "first PATCH: $P1"
P2=$(patch "$GW/v1/config" '{"maxToolCalls":6}' | jq_ "(d['requiresRestart'], d.get('pendingRestart'))")
[ "$P2" = "(False, [])" ] && ok "a live key afterwards: no restart asked for" || bad "second PATCH: $P2 (the old cumulative result)"
E=$(get "$GW/v1/config/schema" | field_of logLevel "(f.get('pendingRestart'), f.get('inEffect'))")
[ "$E" = "(True, 'INFO')" ] && ok "the schema: logLevel pending, INFO in effect" || bad "logLevel: $E"

say "6. share logins say whether a password is stored"
SC=$(patch "$AGENT/v1/config" '{"shareCredentials":[{"host":"nas","username":"u","password":"hunter2"},{"host":"other","username":"v"}]}' | jq_ "d.get('rejected')")
[ "$SC" = "[]" ] && ok "two logins saved" || bad "saving logins: $SC"
HP=$(get "$AGENT/v1/config" | jq_ "[(r['host'], r.get('hasPassword')) for r in d['shareCredentials']]")
[ "$HP" = "[('nas', True), ('other', False)]" ] && ok "hasPassword: nas yes, other no" || bad "rows: $HP"
get "$AGENT/v1/config" | grep -q hunter2 && bad "the password left the machine" || ok "the password never leaves the machine"

say "7. a backend: a saved provider waits for a restart; its address is the provider's own"
DRV_CODE=$(code_of -X POST -H "Authorization: Bearer $TOK" -H 'content-type: application/json' "$AGENT/v1/components" \
  -d "{\"name\":\"$DRIVER\",\"kind\":\"inference-driver\",\"url\":\"$DRV/\",\"spawn\":{\"configFile\":\"$DRIVER.yaml\"}}")
[ "$DRV_CODE" = "201" ] || [ "$DRV_CODE" = "200" ] && ok "declared $DRIVER" || bad "declaring the backend returned $DRV_CODE"
wait_healthy "$DRV" 60 || bad "the backend never answered"
DP=$(patch "$DRV/v1/config" '{"provider":"openrouter"}' | jq_ "d.get('pendingRestart')")
[ "$DP" = "['provider']" ] && ok "provider saved, pending a restart" || bad "provider PATCH: $DP"
DS=$(get "$DRV/v1/config/schema")
B=$(printf '%s' "$DS" | field_of baseUrl "(f.get('unsetResolvesTo'), 'openrouter' in (f.get('showWhen') or {}).get('equals', []))")
[ "$B" = "('https://openrouter.ai/api', True)" ] && ok "baseUrl: shown for openrouter, and unset means https://openrouter.ai/api" || bad "baseUrl: $B"
INFO=$(get "$DRV/v1/info" | jq_ "d.get('provider')")
[ "$INFO" = "claude_subscription" ] && ok "/v1/info names the provider running, not the one saved" || bad "/v1/info provider: $INFO"

say "8. securityMode is not requiresRestart"
SM=$(get "$AGENT/v1/config/schema" | field_of securityMode "f.get('requiresRestart')")
CM=$(get "$CTL/v1/config/schema" | field_of securityMode "f.get('requiresRestart')")
[ "$SM $CM" = "False False" ] && ok "agent and control: securityMode needs no restart" || bad "requiresRestart agent=$SM control=$CM"

say "9. the browser reads the Settings page"
(cd "$UI_DIR" && EP_UI_URL="$AGENT" EP_PASSPHRASE="$PASS" EP_DRIVER_NAME="$DRIVER" EP_NODE_NAME="$NODE" \
  npx playwright test e2e/settings-truth.spec.ts > "$WORK/playwright.log" 2>&1)
PW=$?
sed -n '/Running/,$p' "$WORK/playwright.log" | grep -E '^\s+[✓✘×]|passed|failed' | head -20
if [ "$PW" = "0" ]; then
  for t in \
    "an update channel never saved is not decided, never shown as a choice" \
    "choosing a channel saves it, and it reads back as itself" \
    "a value no dropdown offers is shown as itself, with why" \
    "a number out of range is shown, and said" \
    "unset values say what they do, in each component's words" \
    "a saved value not yet in effect says what runs meanwhile" \
    "a share login says whether a password is stored" \
    "a backend's address says whose it is, and a saved provider waits for a restart"; do
    grep -qF "$t" "$WORK/playwright.log" && ok "browser: $t" || bad "browser: '$t' did not run"
  done
else
  bad "the settings spec failed"
  tail -80 "$WORK/playwright.log"
fi

say "10. the channel chosen in the browser is saved, and settled"
grep -q '^updateChannel: releases' "$WORK/agent.yaml" && ok "agent.yaml holds updateChannel: releases" || bad "agent.yaml: $(grep updateChannel "$WORK/agent.yaml" || echo 'no updateChannel')"
[ -e "$WORK/.update-channel-settled" ] && ok "marked settled, so a later reset stays a reset" || bad "no settled marker"
S2=$(get "$AGENT/v1/node" | jq_ "(d['update'].get('channelSource'), d['update'].get('channel'))")
[ "$S2" = "('setting', 'releases')" ] && ok "GET /v1/node: releases, from the setting" || bad "update after the choice: $S2"

say "result"
if [ "$FAILURES" = "0" ]; then printf '  ALL CHECKS PASSED\n'; else printf '  %d CHECK(S) FAILED\n' "$FAILURES"; fi
exit "$FAILURES"
