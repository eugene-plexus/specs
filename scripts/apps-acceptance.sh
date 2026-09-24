#!/usr/bin/env bash
# Optional apps: the hub and its spokes (docs/design/apps-and-spokes.md).
#
# What only a live run can prove. The agent's tests install a real
# package with uv and run it, and pin every rule against fakes; none of
# them can prove that an app installed through the API receives a key a
# REAL gateway accepts, that the key opens nothing else in the install,
# that the app's settings are reached through the agent with a token that
# means nothing to the hub, or that uninstalling really cuts the app off.
# That is the whole claim -- "our spokes get no back doors" -- and it is a
# claim about sockets.
#
# The checks:
#   0. isolated from any install on this machine, and from its ports
#   1. agent + control + gateway + library up, the root initialized and
#      this node ENROLLED; a driver on a local llama.cpp, routable
#   2. the catalogue says why it cannot install before uv is found, and
#      is installable once `uvBinary` names it
#   3. a custom app is refused until `allowCustomApps` is on, then added
#   4. install: watched to `done`, and the app's key appears in the
#      install's key list under its own name
#   5. the app is running, on its own port, answering /healthz
#   6. the app was handed NO hub credential -- only EUGENE_PLEXUS_APP_*
#   7. the app completes a chat through the gateway with ITS key
#   8. that key opens nothing else: gateway config/admin, agent, library,
#      control, minting another key
#   9. the app's settings, read and changed through the agent
#  10. the app refuses the operator's own token, and no token at all:
#      the agent reaches it with an admin token nobody else holds
#  11. an agent restart brings an enabled app back; a stopped one stays
#      stopped
#  12. an unreadable apps.yaml costs the apps and nothing else
# 12b. with the key authority down (a sealed control root), an
#      uninstall is refused and removes nothing
#  13. uninstall: the key stops working at the gateway, the environments
#      are gone, the app's data stays
#  14. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped, ports are +100, teardown is by pid. Never
# `pkill -f eugene_plexus_`: this box is a worker node.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
UV="${EP_UV:-$EP_ROOT/agent/.venv/Scripts/uv.exe}"
FIXTURE="$EP_ROOT/specs/scripts/fixtures/app-fixture"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-apps}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
GW_PORT="${EP_GW_PORT:-8180}"
LIB_PORT="${EP_LIB_PORT:-8182}"
CTL_PORT="${EP_CTL_PORT:-8183}"
DRIVER_PORT="${EP_DRIVER_PORT:-8171}"
AGENT="http://127.0.0.1:$AGENT_PORT"
GW="http://127.0.0.1:$GW_PORT"
LIB="http://127.0.0.1:$LIB_PORT"
CTL="http://127.0.0.1:$CTL_PORT"
PASS="apps-acceptance-$$"
. "$(dirname "$0")/lib/llama-backend.sh"
ENGINE_PORT="${EP_ENGINE_PORT:-8172}"
MODEL="${EP_MODEL:-apps-acceptance-model}"
OWNED_PORTS="$AGENT_PORT $GW_PORT $LIB_PORT $CTL_PORT $DRIVER_PORT $ENGINE_PORT"
REFRESH=3
APP_PORT=""

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
auth() { printf 'Authorization: Bearer %s' "$TOK"; }

A_PID=""
teardown() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 3; }
  llama_stop_all
  for p in $OWNED_PORTS $APP_PORT; do
    for pid in $(listening_pids "$p"); do
      taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
    done
  done
}
start_agent() {
  (exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 \
    EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" "$PY" -m eugene_plexus_agent --unattended > "$1" 2>&1) &
  A_PID=$!
}
stop_agent() {
  kill "$A_PID" 2>/dev/null; sleep 4
  for p in $OWNED_PORTS $APP_PORT; do
    [ "$p" = "$ENGINE_PORT" ] && continue
    for pid in $(listening_pids "$p"); do taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null; done
  done
  sleep 2
}
agent_login() { curl -s -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')"; }
# A restarted agent restarts the control root, which comes back SEALED:
# this throwaway install has no keyring, so nothing unlocks it but a
# sign-in -- the same thing the console's login does. The key registry
# lives there, so until it is unlocked every key read and revocation is
# a 503. Found by this script's first execution, whose check 13 failed
# whole for exactly that reason.
unlock_control() {
  for _ in $(seq 1 60); do
    [ "$(code_of -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}")" = "200" ] && return 0
    sleep 1
  done
  return 1
}
login() { unlock_control >/dev/null; agent_login; }

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
"$PY" -c "import eugene_plexus_agent.apps, eugene_plexus_control, eugene_plexus_gateway, eugene_plexus_inference_driver, eugene_plexus_library" 2>/dev/null \
  || { bad "the agent (with apps) and four components must import from $PY"; exit 1; }
[ -f "$UV" ] || { bad "no uv at $UV (pip install -e '.[dev]' in the agent repo)"; exit 1; }
[ -f "$FIXTURE/pyproject.toml" ] || { bad "no fixture app at $FIXTURE"; exit 1; }
llama_preflight || exit 1
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
ok "agent python with apps, uv, the fixture app, llama.cpp $(llama_build), every port free"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

# --- 0 -----------------------------------------------------------------------
say "0. isolate this run"
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
printf 'logLevel: INFO\nroutingRefreshSeconds: %s\n' "$REFRESH" > gateway.yaml
echo "logLevel: INFO" > control.yaml
printf 'logLevel: INFO\nmodelRoots: []\n' > library.yaml

# --- 1 -----------------------------------------------------------------------
say "1. the fleet, enrolled, and a driver on a local llama.cpp"
llama_start "$ENGINE_PORT" "$MODEL" && ok "llama-server $(llama_build) serves $MODEL on $ENGINE_PORT" \
  || { bad "the engine never came up"; tail -20 "llama-$ENGINE_PORT.log"; exit 1; }
start_agent agent.log
wait_healthy "$AGENT" 60 || { bad "agent never answered"; tail -20 agent.log; exit 1; }
wait_healthy "$CTL" 90 && wait_healthy "$LIB" 60 && wait_healthy "$GW" 90 \
  && ok "agent $AGENT, control $CTL, library $LIB, gateway $GW" || { bad "a child never came up"; tail -30 agent.log; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "no operator token"; exit 1; }
wait_healthy "$GW" 90 || { bad "gateway did not come back after initialize"; exit 1; }
curl -s -o /dev/null -X POST "$CTL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}"
CTOK=$(curl -s -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$CTOK" ] || { bad "control would not initialize"; exit 1; }
# Enrolled, because an app's key is refused on an agent that is not: an
# unenrolled agent signs with a key that changes at every start. This is
# also the shape every install that finished the wizard has.
JOIN=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"node-a"}' | jq_ "d['token']")
[ "$(code_of -X POST -H "$(auth)" "$AGENT/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$JOIN\",\"name\":\"node-a\"}")" = "200" ] \
  && ok "this node enrolled as node-a" || { bad "enrollment failed"; tail -20 agent.log; exit 1; }
sleep 3
wait_healthy "$AGENT" 60 || { bad "agent did not come back after enrollment"; exit 1; }
TOK=$(login)
[ -n "$TOK" ] || { bad "no operator token after enrollment"; exit 1; }
wait_healthy "$GW" 120 || { bad "gateway did not come back after enrollment"; exit 1; }
curl -s -o /dev/null -X POST "$AGENT/v1/components" -H "$(auth)" -H 'content-type: application/json' \
  -d "{\"name\":\"apps-llama\",\"kind\":\"inference-driver\",\"url\":\"http://127.0.0.1:$DRIVER_PORT\",\"spawn\":{\"configFile\":\"apps-llama.yaml\"}}"
wait_healthy "http://127.0.0.1:$DRIVER_PORT" 60 || { bad "driver never came up"; tail -20 agent.log; exit 1; }
llama_configure_driver "http://127.0.0.1:$DRIVER_PORT" "$TOK" "$MODEL" "$ENGINE_PORT" && ok "the driver took provider, baseUrl and modelId" || exit 1
curl -s -o /dev/null -X POST "$AGENT/v1/components/apps-llama/restart" -H "$(auth)" -d '{}'
ROUTABLE=""
for _ in $(seq 1 60); do
  curl -s -m 10 "$GW/v1/models" -H "$(auth)" | grep -q "\"$MODEL\"" && { ROUTABLE=1; break; }; sleep 1
done
[ -n "$ROUTABLE" ] && ok "the gateway routes to $MODEL" || { bad "not routable"; exit 1; }

# --- 2 -----------------------------------------------------------------------
say "2. the catalogue says why it cannot install, until it can"
CAT=$(curl -s "$AGENT/v1/app-catalogue" -H "$(auth)")
if [ "$(printf '%s' "$CAT" | jq_ "d['installable']")" = "False" ]; then
  printf '%s' "$CAT" | jq_ "d['reason']" | grep -q "uv" && ok "not installable, and the reason names uv" || bad "reason: $CAT"
else
  note "uv is on this agent's PATH, so the not-found case cannot be shown here"
fi
UV_NATIVE=$(cygpath -m "$UV")
C=$(code_of -X PATCH "$AGENT/v1/config" -H "$(auth)" -H 'content-type: application/json' -d "{\"uvBinary\":\"$UV_NATIVE\"}")
CAT=$(curl -s "$AGENT/v1/app-catalogue" -H "$(auth)")
[ "$C" = "200" ] && [ "$(printf '%s' "$CAT" | jq_ "d['installable']")" = "True" ] \
  && ok "uvBinary set; installable" || bad "PATCH $C, catalogue: $CAT"
[ "$(printf '%s' "$CAT" | jq_ "len(d['apps'])")" = "0" ] && ok "this release ships an empty catalogue" || note "catalogue: $CAT"

# --- 3 -----------------------------------------------------------------------
say "3. a custom app waits for the expert switch"
FIXTURE_NATIVE=$(cygpath -m "$FIXTURE")
MANIFEST="{\"id\":\"fixture\",\"name\":\"Fixture\",\"source\":\"$FIXTURE_NATIVE\",\"version\":\"dev-1\",\"package\":\"eugene-plexus-app-fixture\",\"entry\":\"eugene_plexus_app_fixture\",\"ui\":true,\"configTrio\":true,\"uses\":[\"inference\"]}"
C=$(code_of -X POST "$AGENT/v1/app-catalogue/custom" -H "$(auth)" -H 'content-type: application/json' -d "$MANIFEST")
[ "$C" = "403" ] && ok "refused with allowCustomApps off (403)" || bad "custom add: $C"
curl -s -o /dev/null -X PATCH "$AGENT/v1/config" -H "$(auth)" -H 'content-type: application/json' -d '{"allowCustomApps":true}'
C=$(code_of -X POST "$AGENT/v1/app-catalogue/custom" -H "$(auth)" -H 'content-type: application/json' -d "$MANIFEST")
[ "$C" = "201" ] && ok "added once the switch is on (201)" || bad "custom add after the switch: $C"

# --- 4 -----------------------------------------------------------------------
say "4. install, watched to its end; the key is in the install's list"
C=$(code_of -X POST "$AGENT/v1/apps/fixture/install" -H "$(auth)")
[ "$C" = "202" ] && ok "install accepted (202)" || { bad "install: $C"; exit 1; }
STATE=""
for _ in $(seq 1 300); do
  STATE=$(curl -s "$AGENT/v1/apps/fixture/install" -H "$(auth)" | jq_ "d['state']")
  case "$STATE" in done|failed|cancelled) break ;; esac
  sleep 1
done
[ "$STATE" = "done" ] && ok "install state: done" \
  || { bad "install ended $STATE: $(curl -s "$AGENT/v1/apps/fixture/install" -H "$(auth)" | head -c 800)"; exit 1; }
KEYS=$(curl -s "$AGENT/v1/auth/client-keys" -H "$(auth)")
printf '%s' "$KEYS" | grep -q '"app:fixture@node-a"' && ok "the key app:fixture@node-a is in the install's list" || bad "keys: $KEYS"
KEY_FILE="$WORK/apps/fixture/data/client_key"
[ -f "$KEY_FILE" ] && ok "the token is in the app's own data directory" || { bad "no key file at $KEY_FILE"; exit 1; }
APP_KEY=$(cat "$KEY_FILE")
grep -q "$APP_KEY" "$WORK/apps.yaml" "$WORK/agent.yaml" 2>/dev/null && bad "THE TOKEN IS IN A CONFIG FILE" || ok "apps.yaml and agent.yaml carry the key's id, not the token"

# --- 5 -----------------------------------------------------------------------
say "5. running, on its own port"
RUNNING=""
for _ in $(seq 1 60); do
  APP=$(curl -s "$AGENT/v1/apps/fixture" -H "$(auth)")
  [ "$(printf '%s' "$APP" | jq_ "d['status']")" = "running" ] && { RUNNING=1; break; }; sleep 1
done
APP_PORT=$(printf '%s' "$APP" | jq_ "d['port']")
APP_URL="http://127.0.0.1:$APP_PORT"
[ -n "$RUNNING" ] && ok "status running on port $APP_PORT" || { bad "app never ran: $APP"; tail -30 agent.log; exit 1; }
[ "$(code_of "$APP_URL/healthz")" = "200" ] && ok "the app answers /healthz itself" || bad "no /healthz on $APP_URL"
printf '%s' "$APP" | jq_ "d.get('uiUrl','')" | grep -q ":$APP_PORT/" && ok "uiUrl names its own port: $(printf '%s' "$APP" | jq_ "d['uiUrl']")" || bad "uiUrl: $APP"

# --- 6 -----------------------------------------------------------------------
say "6. handed no hub credential"
ENVS=$(curl -s "$APP_URL/env")
echo "  the app's EUGENE_PLEXUS_* names: $ENVS"
printf '%s' "$ENVS" | jq_ "all(n.startswith('EUGENE_PLEXUS_APP_') for n in d) and len(d) > 0" | grep -q True \
  && ok "every EUGENE_PLEXUS_* variable it holds is an APP one" || bad "a hub variable reached the app: $ENVS"

# --- 7 -----------------------------------------------------------------------
say "7. the app talks to the gateway with its own key"
ASK=$(curl -s -m 300 "$APP_URL/ask?model=$MODEL")
[ "$(printf '%s' "$ASK" | jq_ "d.get('status')")" = "200" ] && [ "$(printf '%s' "$ASK" | jq_ "d.get('driver')")" = "apps-llama" ] \
  && ok "a completion served by apps-llama, with the app's key as the only credential" || bad "ask: $ASK"

# --- 8 -----------------------------------------------------------------------
say "8. the key opens nothing else"
for path in /v1/config /v1/admin/drivers /v1/metrics; do
  C=$(code_of -H "Authorization: Bearer $APP_KEY" "$GW$path")
  [ "$C" = "401" ] && ok "gateway $path: 401" || bad "gateway $path: $C"
done
for path in /v1/components /v1/apps /v1/config; do
  C=$(code_of -H "Authorization: Bearer $APP_KEY" "$AGENT$path")
  [ "$C" = "401" ] && ok "agent $path: 401" || bad "agent $path: $C"
done
[ "$(code_of -H "Authorization: Bearer $APP_KEY" "$LIB/v1/models")" = "401" ] && ok "library: 401" || bad "the library accepted an app's key"
[ "$(code_of -H "Authorization: Bearer $APP_KEY" "$CTL/v1/nodes")" = "401" ] && ok "control: 401" || bad "control accepted an app's key"
C=$(code_of -X POST -H "Authorization: Bearer $APP_KEY" -H 'content-type: application/json' -d '{"name":"x"}' "$AGENT/v1/auth/client-keys")
[ "$C" = "401" ] && ok "an app cannot mint a key ($C)" || bad "an app's key is a key factory: $C"
C=$(code_of -X POST -H "Authorization: Bearer $APP_KEY" "$AGENT/v1/apps/fixture/install")
[ "$C" = "401" ] && ok "an app cannot install apps ($C)" || bad "an app's key installs apps: $C"

# --- 9 -----------------------------------------------------------------------
say "9. the app's settings, through the agent"
DOC=$(curl -s "$AGENT/v1/apps/fixture/config" -H "$(auth)")
[ "$(printf '%s' "$DOC" | jq_ "d.get('greeting')")" = "hello" ] && ok "GET /v1/apps/fixture/config: the app's own document" || bad "config: $DOC"
SCHEMA=$(curl -s "$AGENT/v1/apps/fixture/config/schema" -H "$(auth)")
[ "$(printf '%s' "$SCHEMA" | jq_ "d['fields'][0]['key']")" = "greeting" ] && ok "its schema comes through" || bad "schema: $SCHEMA"
R=$(curl -s -X PATCH "$AGENT/v1/apps/fixture/config" -H "$(auth)" -H 'content-type: application/json' -d '{"greeting":"from the console"}')
[ "$(printf '%s' "$R" | jq_ "d['applied']")" = "['greeting']" ] && ok "PATCH applied" || bad "patch: $R"
curl -s "$APP_URL/" | grep -q "from the console" && ok "and the app itself says so" || bad "the app did not take the change"
R=$(curl -s -X PATCH "$AGENT/v1/apps/fixture/config" -H "$(auth)" -H 'content-type: application/json' -d '{"greeting":null}')
curl -s "$APP_URL/" | grep -q "hello" && ok "a null reset it to the default, through the agent" || bad "reset: $R"

# --- 10 ----------------------------------------------------------------------
say "10. the app accepts only the agent's admin token"
[ "$(code_of -H "$(auth)" "$APP_URL/v1/config")" = "401" ] && ok "the operator's token is refused by the app" || bad "the app accepted a hub credential"
[ "$(code_of "$APP_URL/v1/config")" = "401" ] && ok "no token is refused" || bad "the app's settings are open"

# --- 11 ----------------------------------------------------------------------
say "11. restarts: enabled comes back, stopped stays stopped"
stop_agent
start_agent agent2.log
wait_healthy "$AGENT" 90 || { bad "agent did not come back"; tail -20 agent2.log; exit 1; }
TOK=$(login)
BACK=""
for _ in $(seq 1 90); do
  [ "$(curl -s "$AGENT/v1/apps/fixture" -H "$(auth)" | jq_ "d['status']")" = "running" ] && { BACK=1; break; }; sleep 1
done
[ -n "$BACK" ] && ok "the app came back with the agent" || bad "the app did not come back"
[ "$(curl -s "$AGENT/v1/apps/fixture/stop" -X POST -H "$(auth)" | jq_ "d['enabled']")" = "False" ] && ok "stopped" || bad "stop"
stop_agent
start_agent agent3.log
wait_healthy "$AGENT" 90 || { bad "agent did not come back"; exit 1; }
TOK=$(login)
sleep 5
S=$(curl -s "$AGENT/v1/apps/fixture" -H "$(auth)" | jq_ "(d['enabled'], d['status'])")
[ "$S" = "(False, 'exited')" ] && ok "and stayed stopped across the restart" || bad "stopped app state after restart: $S"
[ "$(code_of "$APP_URL/healthz")" = "000" ] && ok "nothing on its port" || bad "something answers on $APP_PORT"
curl -s -o /dev/null -X POST "$AGENT/v1/apps/fixture/start" -H "$(auth)"

# --- 12 ----------------------------------------------------------------------
say "12. an unreadable apps.yaml costs the apps and nothing else"
stop_agent
cp apps.yaml apps.yaml.good
printf 'installed: [ {manifest: 3}\n' > apps.yaml
start_agent agent4.log
wait_healthy "$AGENT" 90 || true
H=$(curl -s "$AGENT/healthz")
[ "$(printf '%s' "$H" | jq_ "d['status']")" = "degraded" ] && printf '%s' "$H" | grep -q appsError \
  && ok "healthz: degraded, with appsError" || bad "healthz: $H"
TOK=$(login)
N=$(curl -s "$AGENT/v1/components" -H "$(auth)" | jq_ "sorted(c['name'] for c in d['components'])")
printf '%s' "$N" | grep -q "gateway" && ok "the topology is intact: $N" || bad "components: $N"
[ "$(curl -s "$AGENT/v1/apps" -H "$(auth)" | jq_ "len(d['apps'])")" = "0" ] && ok "and there are no apps" || bad "apps listed from a broken file"
[ -f "$WORK/apps.yaml.unreadable" ] && ok "the broken file was kept as apps.yaml.unreadable" || bad "no preserved copy"
stop_agent
cp apps.yaml.good apps.yaml
start_agent agent5.log
wait_healthy "$AGENT" 90 || { bad "agent did not come back"; exit 1; }
# Signed in to the agent only: the control root stays sealed for 12b.
TOK=$(agent_login)
for _ in $(seq 1 90); do
  [ "$(curl -s "$AGENT/v1/apps/fixture" -H "$(auth)" | jq_ "d['status']")" = "running" ] && break; sleep 1
done
[ "$(curl -s "$AGENT/v1/apps/fixture" -H "$(auth)" | jq_ "d['status']")" = "running" ] && ok "the restored file brings it back" || bad "not back after restore"

say "12b. an uninstall that cannot revoke the key removes nothing"
# The control root is sealed right now -- nothing has signed in to it
# since the restart -- so the key registry cannot be reached. The rule is
# that an app is never gone while its key still works.
C=$(code_of -X DELETE "$AGENT/v1/apps/fixture" -H "$(auth)")
[ "$C" = "503" ] && ok "refused with the authority down ($C)" || bad "uninstall with a sealed root answered $C"
[ "$(curl -s "$AGENT/v1/apps/fixture" -H "$(auth)" | jq_ "d['status']")" = "running" ] && [ -f "$KEY_FILE" ]   && ok "the app is still installed, still running, key file in place" || bad "something was removed"
unlock_control && ok "control unlocked by signing in, as the console does" || { bad "control would not unlock"; exit 1; }
wait_healthy "$GW" 120 || note "gateway slow to return"

# --- 13 ----------------------------------------------------------------------
say "13. uninstall cuts it off"
ROUTED=""
for _ in $(seq 1 60); do
  [ "$(code_of -H "Authorization: Bearer $APP_KEY" "$GW/v1/models")" = "200" ] && { ROUTED=1; break; }; sleep 1
done
[ -n "$ROUTED" ] && ok "before: the app's key is accepted at the gateway" || bad "the key was not accepted before uninstall"
[ "$(code_of -X DELETE "$AGENT/v1/apps/fixture" -H "$(auth)")" = "204" ] && ok "DELETE /v1/apps/fixture: 204" || bad "uninstall failed"
STOPPED=""
for i in $(seq 1 30); do
  [ "$(code_of -H "Authorization: Bearer $APP_KEY" "$GW/v1/models")" = "401" ] && { STOPPED=$i; break; }; sleep 1
done
[ -n "$STOPPED" ] && ok "after: the gateway refuses the key (${STOPPED}s; refresh ${REFRESH}s)" || bad "the key still works 30s after uninstall"
[ ! -d "$WORK/apps/fixture/versions" ] && ok "its environments are gone" || bad "versions left behind"
[ -d "$WORK/apps/fixture/data" ] && [ ! -f "$KEY_FILE" ] && ok "its data stays, without the dead key" || bad "data dir state wrong"
[ "$(code_of "$APP_URL/healthz")" = "000" ] && ok "nothing on its port" || bad "something still answers on $APP_PORT"

# --- 14 ----------------------------------------------------------------------
say "14. teardown by pid"
teardown; A_PID=""
LEFT=""
for p in $OWNED_PORTS $APP_PORT; do [ -n "$(listening_pids "$p")" ] && LEFT="$LEFT $p"; done
[ -z "$LEFT" ] && ok "no owned port still listening" || bad "still listening:$LEFT"

say "done"
if [ "$FAILURES" -eq 0 ]; then
  printf '\nALL CHECKS PASSED\n'
else
  printf '\n%s CHECK(S) FAILED\n' "$FAILURES"
  exit 1
fi
