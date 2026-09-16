#!/usr/bin/env bash
# Client keys, and "Use it from your apps" (hobbyist UX plan, S4 --
# decision #7).
#
# Design: docs/design/hobbyist-ux.md §7 S4 and §6.1; record §11.5. Its
# §0.8 measured what this replaces: the only bearer a person could paste
# into Continue or Open WebUI was the OPERATOR SESSION TOKEN -- full
# authority over every component, shown only inside a diagnostic panel
# nineteen clicks in, dead fourteen days after sign-in.
#
# What only a live run can prove. The agent's tests pin the store and the
# audience, the gateway's pin the guard against a mock transport, and the
# UI's pin the recipes; none of them can prove that a string a browser
# copied off Home is accepted by a real gateway over a real socket, that
# it opens nothing else, and that pressing "Turn off" makes it stop --
# which is the whole claim.
#
# The checks:
#   0. isolated from any install on this machine, and from its ports
#   1. the UI wheel staged from this working tree AND served by this agent
#   2. agent + control + gateway + library up, the root initialized and
#      this node ENROLLED; a driver on the local ollama
#   3. no client keys yet; the revoked set is empty
#   4. a minted key returns its token ONCE and the record never carries it
#   5. the key completes a chat through the gateway, as a harness would
#   6. the key opens NOTHING else: gateway config/admin/metrics, the
#      agent, the library, the control root
#   7. the record list shows the name and the tail, not the token
#   8. revoking makes it stop, within the refresh interval, and says so
#   9. revoking one key leaves another working
#  10. the gateway is really polling the revoked set; a client key
#      cannot read it and the operator can
#  11. a key survives an agent restart (the record is on disk)
#  12. BROWSER: Home's card, a key made in it, used from the page's own
#      fetch against the gateway's address, then turned off
#  13. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped (install.ps1 sets the config-file var in the USER
# environment, so a throwaway agent would otherwise come up as the live
# worker and announce a dying port to the real control root -- that
# happened, 2026-09-12), ports are +100, teardown is by pid. Never
# `pkill -f eugene_plexus_`: this box is a worker node.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-client-keys}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
GW_PORT="${EP_GW_PORT:-8180}"
LIB_PORT="${EP_LIB_PORT:-8182}"
CTL_PORT="${EP_CTL_PORT:-8183}"
DRIVER_PORT="${EP_DRIVER_PORT:-8191}"
AGENT="http://127.0.0.1:$AGENT_PORT"
GW="http://127.0.0.1:$GW_PORT"
LIB="http://127.0.0.1:$LIB_PORT"
CTL="http://127.0.0.1:$CTL_PORT"
PASS="client-keys-$$"
OLLAMA="${EP_OLLAMA:-http://127.0.0.1:11434}"
MODEL="${EP_MODEL:-qwen3-coder:30b}"
OWNED_PORTS="$AGENT_PORT $GW_PORT $LIB_PORT $CTL_PORT $DRIVER_PORT"
SKIP_BUILD="${EP_SKIP_BUILD:-0}"
# The gateway's routing refresh here, which is also the revocation
# window the contract promises. Small, so check 8 is a run and not a wait.
REFRESH=3

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }

A_PID=""
teardown() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 3; }
  for p in $OWNED_PORTS; do
    for pid in $(listening_pids "$p"); do
      taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
    done
  done
}

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
"$PY" -c "import eugene_plexus_agent, eugene_plexus_control, eugene_plexus_gateway, eugene_plexus_inference_driver, eugene_plexus_library, eugene_plexus_ui" 2>/dev/null \
  || { bad "the five components and eugene_plexus_ui must import from $PY"; exit 1; }
[ -d "$UI_DIR/node_modules/@playwright" ] || { bad "no Playwright in $UI_DIR (npm install)"; exit 1; }
curl -sf -m 3 "$OLLAMA/api/tags" >/dev/null || { bad "ollama is not answering at $OLLAMA"; exit 1; }
curl -s -m 5 "$OLLAMA/api/tags" | grep -q "\"$MODEL\"" || { bad "$MODEL is not pulled into ollama"; exit 1; }
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
ok "agent python with six packages, Playwright, a live ollama with $MODEL, every port free"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

# --- 0 -----------------------------------------------------------------------
say "0. isolate this run"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
WORK_NATIVE=$(cygpath -w "$WORK" 2>/dev/null || printf '%s' "$WORK")
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }

# --- 1 -----------------------------------------------------------------------
say "1. stage this working tree's UI, and prove the agent venv SERVES it"
if [ "$SKIP_BUILD" = "1" ]; then
  ok "skipped by EP_SKIP_BUILD=1"
else
  (cd "$UI_DIR" && npm run build:python > "$WORK/build.log" 2>&1)
  [ $? = 0 ] && ok "npm run build:python staged the export" || { bad "build failed"; tail -30 "$WORK/build.log"; exit 1; }
fi
STATIC="$UI_DIR/python/eugene_plexus_ui/static"
grep -qr 'home-use-from-apps' "$STATIC/_next/static/chunks" 2>/dev/null \
  && ok "the staged bundle carries the Use-it-from-your-apps card" \
  || bad "no home-use-from-apps in the staged bundle -- the agent would serve a pre-S4 build"
# Staging is not serving (2026-09-15, S3's fourth finding): four runs
# asserted about a build no browser ever saw because the agent venv held
# a WHEEL, not the editable install.
SERVED=$("$PY" -c "from eugene_plexus_ui import static_dir; print(static_dir())" 2>/dev/null | tr -d '\r')
SERVED_NORM=$(printf '%s' "$SERVED" | tr '\\' '/' | tr '[:upper:]' '[:lower:]')
STATIC_NORM=$(cygpath -w "$STATIC" 2>/dev/null | tr '\\' '/' | tr '[:upper:]' '[:lower:]')
[ -n "$SERVED_NORM" ] && [ "$SERVED_NORM" = "$STATIC_NORM" ] \
  && ok "the agent venv's eugene_plexus_ui IS the staged directory (editable install)" \
  || { bad "the agent venv serves $SERVED, not $STATIC. Run: \"$PY\" -m pip install -e \"$UI_DIR\""; exit 1; }

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

# --- 2 -----------------------------------------------------------------------
say "2. the fleet, and a driver on the local ollama"
(exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
  "$PY" -m eugene_plexus_agent --unattended > agent.log 2>&1) &
A_PID=$!
wait_healthy "$AGENT" 60 || { bad "agent never answered"; tail -20 agent.log; exit 1; }
wait_healthy "$CTL" 90 && wait_healthy "$LIB" 60 && wait_healthy "$GW" 90 \
  && ok "agent $AGENT, control $CTL, library $LIB, gateway $GW" \
  || { bad "a child never came up"; tail -30 agent.log; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "no operator token"; exit 1; }
wait_healthy "$GW" 90 || { bad "gateway did not come back after initialize"; exit 1; }
# The control root is initialized too, and NOT for its own sake: an
# uninitialized root 503s every path, so check 6's "the control root
# refuses a client key" would have passed against a root that refuses
# everything and never looked at the audience. The first run of this
# script measured exactly that -- a 503 read as "not 401" and the check
# reported a defect that was not there.
curl -s -o /dev/null -X POST "$CTL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}"
CTOK=$(curl -s -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$CTOK" ] && ok "the control root is initialized, so its refusals are about the token"   || { bad "control would not initialize; check 6's control case would prove nothing"; exit 1; }
# And this node ENROLLS, which is not optional dressing.
#
# M7 settled that every node enrolls the same way, the control host's
# included -- and M9 recorded what happens when one does not: an
# unenrolled agent mints its own random signing key per restart while the
# root mints the install's, so the root refuses every session the agent
# issues. The browser then meets a 401 from `control` on a page whose
# other reads are fine, `lib/api.ts` treats any 401 as "this session is
# over", clears it and bounces to /login -- and every browser test in
# this script failed at sign-in with a form that had just succeeded.
# That was execution 2 and 3 here, and the install shape that produced
# it (root initialized, local agent not enrolled) is one the wizard
# stopped creating at M9. It is also why `clientKeyTarget` gets a real
# node name to reason about rather than a null.
JOIN=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"node-a"}' | jq_ "d['token']")
[ "$(code_of -X POST -H "Authorization: Bearer $TOK" "$AGENT/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$JOIN\",\"name\":\"node-a\"}")" = "200" ]   && ok "this node enrolled as node-a; the install has one signing key"   || { bad "enrollment failed"; tail -20 agent.log; exit 1; }
# Enrollment replaces the signing key, so the session that asked for it
# is dead by design (tailnet.md says so). Log in again.
sleep 3
wait_healthy "$AGENT" 60 || { bad "agent did not come back after enrollment"; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "no operator token after enrollment"; exit 1; }
wait_healthy "$GW" 120 || { bad "gateway did not come back after enrollment"; exit 1; }

curl -s -o /dev/null -X POST "$AGENT/v1/components" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"name\":\"keys-ollama\",\"kind\":\"inference-driver\",\"url\":\"http://127.0.0.1:$DRIVER_PORT\",\"spawn\":{\"configFile\":\"keys-ollama.yaml\"}}"
wait_healthy "http://127.0.0.1:$DRIVER_PORT" 60 || { bad "driver never came up"; tail -20 agent.log; exit 1; }
curl -s -o /dev/null -X PATCH "http://127.0.0.1:$DRIVER_PORT/v1/config" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"provider\":\"ollama_local\",\"modelId\":\"$MODEL\"}"
curl -s -o /dev/null -X POST "$AGENT/v1/components/keys-ollama/restart" -H "Authorization: Bearer $TOK" -d '{}'
ROUTABLE=""
for _ in $(seq 1 60); do
  MODELS=$(curl -s -m 10 "$GW/v1/models" -H "Authorization: Bearer $TOK")
  printf '%s' "$MODELS" | grep -q "\"$MODEL\"" && { ROUTABLE=1; break; }; sleep 1
done
[ -n "$ROUTABLE" ] && ok "the gateway routes to $MODEL" || { bad "not routable: $MODELS"; exit 1; }

# --- 3 -----------------------------------------------------------------------
say "3. a fresh install has no client keys"
LIST=$(curl -s "$AGENT/v1/auth/client-keys" -H "Authorization: Bearer $TOK")
[ "$(printf '%s' "$LIST" | jq_ "len(d['keys'])")" = "0" ] && ok "GET /v1/auth/client-keys: []" || bad "list: $LIST"
REV=$(curl -s "$AGENT/v1/auth/client-keys/revoked" -H "Authorization: Bearer $TOK")
[ "$(printf '%s' "$REV" | jq_ "len(d['ids'])")" = "0" ] && ok "the revoked set is empty" || bad "revoked: $REV"
[ -f "$WORK/client_keys.json" ] && bad "a record file exists before any key was minted" || ok "no record file until one is minted"

# --- 4 -----------------------------------------------------------------------
say "4. mint: the token comes back once, and is nowhere on disk"
MADE=$(curl -s -X POST "$AGENT/v1/auth/client-keys" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d '{"name":"Continue on the laptop"}')
KEY=$(printf '%s' "$MADE" | jq_ "d['token']")
KEY_ID=$(printf '%s' "$MADE" | jq_ "d['key']['id']")
TAIL=$(printf '%s' "$MADE" | jq_ "d['key']['tail']")
[ -n "$KEY" ] && [ "$(printf '%s' "$KEY" | awk -F. '{print NF}')" = "3" ] \
  && ok "a JWT came back (id $KEY_ID, tail $TAIL)" || { bad "mint: $MADE"; exit 1; }
CLAIMS=$(printf '%s' "$KEY" | cut -d. -f2 | tr '_-' '/+' | python -c "import sys,base64,json;s=sys.stdin.read().strip();print(json.dumps(json.loads(base64.b64decode(s+'='*(-len(s)%4)))))")
echo "  claims: $CLAIMS"
[ "$(printf '%s' "$CLAIMS" | jq_ "d['aud']")" = "client" ] && ok "aud: client" || bad "wrong audience: $CLAIMS"
[ "$(printf '%s' "$CLAIMS" | jq_ "d['jti']")" = "$KEY_ID" ] && ok "jti is the record's id" || bad "jti mismatch"
grep -q "$KEY" "$WORK/client_keys.json" 2>/dev/null && bad "THE TOKEN IS ON DISK" || ok "client_keys.json does not contain the token"
grep -q "$TAIL" "$WORK/client_keys.json" 2>/dev/null && ok "the record keeps the tail, which identifies it" || bad "no tail in the record file"
grep -q "$KEY" "$WORK"/*.yaml 2>/dev/null && bad "the token leaked into a config file" || ok "no config file carries it"

# --- 5 -----------------------------------------------------------------------
say "5. the key works on the front door, exactly as a harness uses it"
R=$(curl -s -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ok\"}],\"max_tokens\":20}")
DRV=$(printf '%s' "$R" | jq_ "d.get('x_eugene_plexus',{}).get('driver','')" 2>/dev/null)
[ "$DRV" = "keys-ollama" ] && ok "a completion with the client key as the only credential, served by $DRV" \
  || bad "completion: $(printf '%s' "$R" | head -c 300)"
[ "$(code_of -H "Authorization: Bearer $KEY" "$GW/v1/models")" = "200" ] && ok "GET /v1/models: 200" || bad "models refused"

# --- 6 -----------------------------------------------------------------------
say "6. and opens nothing else, anywhere in the install"
for path in /v1/config /v1/config/schema /v1/admin/drivers /v1/admin/routing /v1/metrics; do
  C=$(code_of -H "Authorization: Bearer $KEY" "$GW$path")
  [ "$C" = "401" ] && ok "gateway $path: 401" || bad "gateway $path: $C"
done
for path in /v1/components /v1/runtimes /v1/config /v1/node /v1/auth/client-keys; do
  C=$(code_of -H "Authorization: Bearer $KEY" "$AGENT$path")
  [ "$C" = "401" ] && ok "agent $path: 401" || bad "agent $path: $C"
done
[ "$(code_of -H "Authorization: Bearer $KEY" "$LIB/v1/models")" = "401" ] && ok "library /v1/models: 401" || bad "the library accepted a client key"
C=$(code_of -H "Authorization: Bearer $KEY" "$CTL/v1/nodes")
[ "$C" = "401" ] && ok "control /v1/nodes: 401" || bad "control /v1/nodes: $C (401 expected; 503 means the root is not initialized and this check proved nothing)"
C=$(code_of -X POST -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"name":"escalation"}' "$AGENT/v1/auth/client-keys")
[ "$C" = "401" ] && ok "a client key cannot mint another ($C)" || bad "a leaked key is a key factory: $C"

# --- 7 -----------------------------------------------------------------------
say "7. the list shows the name and the tail, never the token"
LIST=$(curl -s "$AGENT/v1/auth/client-keys" -H "Authorization: Bearer $TOK")
printf '%s' "$LIST" | grep -q "Continue on the laptop" && ok "the name is in the list" || bad "list: $LIST"
printf '%s' "$LIST" | grep -q "$TAIL" && ok "the tail is in the list" || bad "no tail"
printf '%s' "$LIST" | grep -q "$KEY" && bad "THE LIST RETURNED THE TOKEN" || ok "the token is not in the list"

# --- 8 -----------------------------------------------------------------------
say "8. revoking makes it stop, inside the refresh interval"
[ "$(code_of -X DELETE -H "Authorization: Bearer $TOK" "$AGENT/v1/auth/client-keys/$KEY_ID")" = "204" ] && ok "DELETE: 204" || bad "delete failed"
REV=$(curl -s "$AGENT/v1/auth/client-keys/revoked" -H "Authorization: Bearer $TOK")
printf '%s' "$REV" | grep -q "$KEY_ID" && ok "the id is in the revoked set" || bad "revoked: $REV"
STOPPED=""; WAITED=0
for i in $(seq 1 30); do
  C=$(code_of -H "Authorization: Bearer $KEY" "$GW/v1/models")
  [ "$C" = "401" ] && { STOPPED=1; WAITED=$i; break; }; sleep 1
done
[ -n "$STOPPED" ] && ok "the gateway refused it after ${WAITED}s (refresh interval ${REFRESH}s)" || bad "still accepted 30s after revoking"
BODY=$(curl -s -H "Authorization: Bearer $KEY" "$GW/v1/models")
printf '%s' "$BODY" | grep -qi "revok" && ok "the 401 says the key was turned off, not 'invalid token'" || bad "unhelpful 401: $(printf '%s' "$BODY" | head -c 200)"
[ "$(code_of -X DELETE -H "Authorization: Bearer $TOK" "$AGENT/v1/auth/client-keys/$KEY_ID")" = "204" ] && ok "revoking again is 204, not an error" || bad "second delete"

# --- 9 -----------------------------------------------------------------------
say "9. revoking one key leaves another working"
A=$(curl -s -X POST "$AGENT/v1/auth/client-keys" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' -d '{"name":"keeper"}')
B=$(curl -s -X POST "$AGENT/v1/auth/client-keys" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' -d '{"name":"doomed"}')
A_KEY=$(printf '%s' "$A" | jq_ "d['token']"); B_KEY=$(printf '%s' "$B" | jq_ "d['token']"); B_ID=$(printf '%s' "$B" | jq_ "d['key']['id']")
curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $TOK" "$AGENT/v1/auth/client-keys/$B_ID"
for _ in $(seq 1 30); do [ "$(code_of -H "Authorization: Bearer $B_KEY" "$GW/v1/models")" = "401" ] && break; sleep 1; done
[ "$(code_of -H "Authorization: Bearer $B_KEY" "$GW/v1/models")" = "401" ] && ok "the revoked one is refused" || bad "doomed key still works"
[ "$(code_of -H "Authorization: Bearer $A_KEY" "$GW/v1/models")" = "200" ] && ok "the other one still works -- which is the reason to mint more than one" \
  || bad "revoking one took them all down; this would be the signing-key rotation with extra steps"

# --- 10 ----------------------------------------------------------------------
say "10. who may read the revoked set"
# The narrow audiences -- `service:gateway` yes, `service:library` no --
# are held down by the agent's own tests, which can mint any token they
# like. What only a live run shows is that the GATEWAY is really reaching
# this endpoint rather than the whole mechanism being dead code that
# check 8 passed by coincidence; the agent's access log is the evidence.
C=$(code_of -H "Authorization: Bearer $KEY" "$AGENT/v1/auth/client-keys/revoked")
[ "$C" = "401" ] && ok "a client key may not read the revoked set ($C)" || bad "client key read it: $C"
[ "$(code_of -H "Authorization: Bearer $TOK" "$AGENT/v1/auth/client-keys/revoked")" = "200" ] && ok "the operator may" || bad "the operator was refused"
grep -qi "client-keys/revoked" agent.log && ok "the gateway is really polling the endpoint (seen in the agent's log)" \
  || note "no /v1/auth/client-keys/revoked line in agent.log at this log level"

# --- 11 ----------------------------------------------------------------------
say "11. a key survives a restart of the agent"
kill "$A_PID" 2>/dev/null; sleep 4
for p in $OWNED_PORTS; do for pid in $(listening_pids "$p"); do taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null; done; done
sleep 2
(exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
  "$PY" -m eugene_plexus_agent --unattended > agent2.log 2>&1) &
A_PID=$!
wait_healthy "$AGENT" 90 || { bad "agent did not come back"; tail -20 agent2.log; exit 1; }
TOK2=$(curl -s -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
LIST=$(curl -s "$AGENT/v1/auth/client-keys" -H "Authorization: Bearer $TOK2")
printf '%s' "$LIST" | grep -q "keeper" && ok "the record survived the restart" || bad "records lost: $LIST"
REV=$(curl -s "$AGENT/v1/auth/client-keys/revoked" -H "Authorization: Bearer $TOK2")
printf '%s' "$REV" | grep -q "$B_ID" && ok "so did the revocation -- a restart must not un-revoke a key" || bad "revocation lost: $REV"
# And the KEY still works, which is the property a person cares about:
# a key pasted into Continue must survive a reboot. It does because this
# node is enrolled and so persists the INSTALL's signing key in
# node.yaml rather than minting a fresh one per start -- the difference
# M7 built and M9 found the hard way. On an unenrolled single box the
# same key would die with the process, exactly as the operator's own
# session does there.
wait_healthy "$GW" 180 || note "gateway slow to return after the restart"
SURVIVED=""
for _ in $(seq 1 60); do
  [ "$(code_of -H "Authorization: Bearer $A_KEY" "$GW/v1/models")" = "200" ] && { SURVIVED=1; break; }; sleep 1
done
[ -n "$SURVIVED" ] && ok "a key minted before the restart still works after it -- an enrolled node keeps the install's signing key"   || bad "the key died with the process: $(code_of -H "Authorization: Bearer $A_KEY" "$GW/v1/models")"
for _ in $(seq 1 30); do [ "$(code_of -H "Authorization: Bearer $B_KEY" "$GW/v1/models")" = "401" ] && break; sleep 1; done
[ "$(code_of -H "Authorization: Bearer $B_KEY" "$GW/v1/models")" = "401" ] && ok "and the revoked one is STILL refused after the restart"   || bad "a restart un-revoked a key"

# --- 12 ----------------------------------------------------------------------
say "12. the browser: Home's card, a real key, a real request, a real revoke"
(cd "$UI_DIR" && EP_UI_URL="$AGENT" EP_PASSPHRASE="$PASS" EP_GATEWAY_URL="$GW" \
  npx playwright test e2e/client-keys.spec.ts > "$WORK/playwright.log" 2>&1)
PW_EXIT=$?
echo "  playwright exit $PW_EXIT; $(grep -E 'passed|failed|skipped' "$WORK/playwright.log" | tail -1)"
[ "$PW_EXIT" = "0" ] && ok "the browser made a key on Home, used it against the gateway, and turned it off" \
  || { bad "the browser run failed"; tail -40 "$WORK/playwright.log"; }

# --- 13 ----------------------------------------------------------------------
say "13. teardown by pid"
teardown; A_PID=""
LEFT=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && LEFT="$LEFT $p"; done
[ -z "$LEFT" ] && ok "no owned port still listening" || bad "still listening:$LEFT"

say "done"
if [ "$FAILURES" -eq 0 ]; then
  printf '\nALL CHECKS PASSED\n'
else
  printf '\n%s CHECK(S) FAILED\n' "$FAILURES"
  exit 1
fi
