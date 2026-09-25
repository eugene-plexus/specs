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
# What only a live run can prove. The agent's tests pin the forwarding
# and the audience, the gateway's pin the guard against a mock transport,
# and the UI's pin the recipes; none of them can prove that a string a
# browser copied off Home is accepted by a real gateway over a real
# socket, that it opens nothing else, and that pressing "Turn off" makes
# it stop -- which is the whole claim.
#
# **Moved onto per-node token keys on 2026-09-25**
# (docs/design/per-node-token-keys.md), and onto A3's install-wide
# registry, which this script predated. A client key is minted by the
# CONTROL ROOT, not by the agent: the enrolled agent forwards the
# request, the root signs an `ep-client+jwt` addressed to `gateway` with
# its own token key, and records the key in its replicated registry --
# so the record lives in the root's state, and the agent keeps no
# `client_keys.json` at all. The node is joined with the `gateway` grant
# (the wizard's join for the machine that runs the gateway), and every
# sign-in on the enrolled agent is the root's, addressed to `node:node-a`
# and `control`. The gateway learns revocations by polling its agent's
# `/v1/auth/client-keys/policy`, which forwards to the root, and keeps
# what it read in `gateway.client-keys.json` beside its config.
# Removed: the checks that the agent's own `client_keys.json` keeps the
# tail and not the token, because an enrolled agent writes no such file
# (the same property is now checked on the root's state and on every file
# the run leaves behind); and "an enrolled node keeps the install's
# signing key", because no node holds one -- a key survives a restart
# because the root's token key is sealed in its state.
#
# The checks:
#   0. isolated from any install on this machine, and from its ports
#   1. the UI wheel staged from this working tree AND served by this agent
#   2. agent + control + gateway + library up, the root initialized and
#      this node ENROLLED with the gateway grant; a driver on a local
#      llama.cpp
#   3. no client keys yet, in the install's registry; the revoked set is
#      empty; the agent keeps no record file of its own
#   4. a minted key is the root's, returns its token ONCE, and no file
#      anywhere in the run carries it; the root's log keeps the tail
#   5. the key completes a chat through the gateway, as a harness would
#   6. the key opens NOTHING else: gateway config/admin/metrics, the
#      agent, the library, the control root
#   7. the record list shows the name and the tail, not the token
#   8. revoking makes it stop, within the refresh interval, and says so
#   9. revoking one key leaves another working
#  10. the gateway really reads the revocation policy (its own cache
#      file says so); a client key cannot read the revoked set and the
#      operator can
#  11. a key survives an agent restart (the record is in the root's state)
#  12. BROWSER: Home's card, a key made in it, used from the page's own
#      fetch against the gateway's address, then turned off
#  13. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped (install.ps1 sets the config-file var in the USER
# environment, so a throwaway agent would otherwise come up as the live
# worker and announce a dying port to the real control root -- that
# happened, 2026-09-12), ports are +100 and overridable, teardown is by
# pid. Never `pkill -f eugene_plexus_`: this box is a worker node.
#
# Last run 2026-09-25, beside two other acceptance runs holding 81xx, on
# the export staged at ui b879c76 (EP_SKIP_BUILD=1, so a concurrent run's
# UI was not rebuilt underneath it):
#   EP_SKIP_BUILD=1 EP_AGENT_PORT=8284 EP_GW_PORT=8285 EP_LIB_PORT=8286 \
#   EP_CTL_PORT=8287 EP_DRIVER_PORT=8288 EP_ENGINE_PORT=8289 \
#   bash scripts/client-keys-acceptance.sh
# -> 58 PASS, 1 FAILED (second execution): check 12, the browser. Its
#    second test mints two keys on Home and uses each at once, and the
#    gateway answered "401 Key not registered" to a key the root minted a
#    moment ago, until its next policy refresh (1244 ms here with a 3 s
#    refresh; up to 15 s at the default). A gateway defect since A3's
#    positive list (gateway 26cf68e), FIXED in gateway dc71da1 and
#    2f4d8dd: an unlisted key is answered by a policy read begun after
#    it arrived (one a second at most). Check 9 now asserts the first
#    request succeeds. Re-run the same way after the fix: ALL CHECKS
#    PASSED, 60 PASS, browser 5 of 5. The first execution also
#    failed check 10, a harness defect: the gateway refreshes its policy
#    only on a client-key request, so the check now makes one.
# 2026-09-15 (old model): 45 checks, fourth execution.
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
# The backend: a real llama.cpp, not ollama. lib/llama-backend.sh has the
# reasoning, the provider-key trap and the /v1 trap.
. "$(dirname "$0")/lib/llama-backend.sh"
ENGINE_PORT="${EP_ENGINE_PORT:-8192}"
MODEL="${EP_MODEL:-keys-acceptance-model}"
OWNED_PORTS="$AGENT_PORT $GW_PORT $LIB_PORT $CTL_PORT $DRIVER_PORT $ENGINE_PORT"
SKIP_BUILD="${EP_SKIP_BUILD:-0}"
# How often the gateway re-reads the client-key policy here, which is
# also the revocation window the contract promises. Small, so check 8 is
# a run and not a wait. Handed to the gateway through its spawn env: the
# agent passes a child its own non-credential EUGENE_PLEXUS_GATEWAY_*.
REFRESH=3

FAILURES=0
PASSES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; PASSES=$((PASSES + 1)); }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
b64json() {  # one JWT segment ($2: 1 header, 2 payload) of $1, as JSON
  printf '%s' "$1" | cut -d. -f"$2" | tr '_-' '/+' \
    | python -c "import sys,base64,json;s=sys.stdin.read().strip();print(json.dumps(json.loads(base64.b64decode(s+'='*(-len(s)%4)))))"
}
# An enrolled agent's sign-in is the root's. Right after the agent (and
# so the root it supervises) starts, the root may not answer yet and the
# agent says 503 "Control root unreachable"; that is a wait, not a fail.
login_agent() {
  local out
  for _ in $(seq 1 60); do
    out=$(curl -s -m 20 -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' \
      -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')" 2>/dev/null)
    [ -n "$out" ] && { printf '%s' "$out"; return 0; }
    sleep 2
  done
  return 1
}

A_PID=""
teardown() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 3; }
  llama_stop_all
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
llama_preflight || exit 1
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
ok "agent python with six packages, Playwright, llama.cpp $(llama_build), a model on disk, every port free"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

# --- 0 -----------------------------------------------------------------------
say "0. isolate this run"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
# No OS keyring: a throwaway install must never read or write the live one.
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
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
      env:
        EUGENE_PLEXUS_GATEWAY_CLIENT_KEY_REFRESH_SECONDS: "$REFRESH"
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
say "2. the fleet, and a driver on a local llama.cpp"
llama_start "$ENGINE_PORT" "$MODEL"   && ok "llama-server $(llama_build) serves $MODEL on $ENGINE_PORT"   || { bad "the engine never came up"; tail -20 "llama-$ENGINE_PORT.log"; exit 1; }

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
# everything and never looked at the token. The first run of this
# script measured exactly that -- a 503 read as "not 401" and the check
# reported a defect that was not there.
curl -s -o /dev/null -X POST "$CTL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}"
CTOK=$(curl -s -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$CTOK" ] && ok "the control root is initialized, so its refusals are about the token"   || { bad "control would not initialize; check 6's control case would prove nothing"; exit 1; }
# And this node ENROLLS, which is not optional dressing: a client key is
# minted only by the root, and only an enrolled agent forwards the
# request there. With the `gateway` grant, because the gateway runs on
# this machine and reaches the root (and would reach every other node)
# with `sub: gateway` tokens its own agent mints -- the join the wizard
# makes for the control host. Without it the gateway's reads of the root
# are refused and the install routes nothing it does not own.
JOIN=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"node-a","grants":["gateway"]}' | jq_ "d['token']")
[ "$(code_of -X POST -H "Authorization: Bearer $TOK" "$AGENT/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$JOIN\",\"name\":\"node-a\"}")" = "200" ] \
  && ok "this node enrolled as node-a, with the gateway grant; it trusts the root's bundle now" \
  || { bad "enrollment failed"; tail -20 agent.log; exit 1; }
# The standalone session names `node:local`, which nothing trusts once
# the node is enrolled. Sign in again: the agent forwards it to the root.
wait_healthy "$AGENT" 60 || { bad "agent did not come back after enrollment"; exit 1; }
TOK=$(login_agent) || { bad "no operator session after enrollment"; tail -20 agent.log; exit 1; }
[ "$(b64json "$TOK" 2 | jq_ "d['aud']")" = "['node:node-a', 'control']" ] \
  && ok "a sign-in on the enrolled agent is the root's, addressed to node-a and the root" \
  || bad "the session after enrollment: $(b64json "$TOK" 2)"
wait_healthy "$GW" 120 || { bad "gateway did not come back after enrollment"; exit 1; }

curl -s -o /dev/null -X POST "$AGENT/v1/components" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"name\":\"keys-llama\",\"kind\":\"inference-driver\",\"url\":\"http://127.0.0.1:$DRIVER_PORT\",\"spawn\":{\"configFile\":\"keys-llama.yaml\"}}"
wait_healthy "http://127.0.0.1:$DRIVER_PORT" 60 || { bad "driver never came up"; tail -20 agent.log; exit 1; }
llama_configure_driver "http://127.0.0.1:$DRIVER_PORT" "$TOK" "$MODEL" "$ENGINE_PORT"   && ok "the driver took provider, baseUrl and modelId" || exit 1
curl -s -o /dev/null -X POST "$AGENT/v1/components/keys-llama/restart" -H "Authorization: Bearer $TOK" -d '{}'
ROUTABLE=""
for _ in $(seq 1 60); do
  MODELS=$(curl -s -m 10 "$GW/v1/models" -H "Authorization: Bearer $TOK")
  printf '%s' "$MODELS" | grep -q "\"$MODEL\"" && { ROUTABLE=1; break; }; sleep 1
done
[ -n "$ROUTABLE" ] && ok "the gateway routes to $MODEL" || { bad "not routable: $MODELS"; exit 1; }

# --- 3 -----------------------------------------------------------------------
say "3. a fresh install has no client keys"
LIST=$(curl -s "$AGENT/v1/auth/client-keys" -H "Authorization: Bearer $TOK")
[ "$(printf '%s' "$LIST" | jq_ "(len(d['keys']), d.get('scope'))")" = "(0, 'install')" ] \
  && ok "GET /v1/auth/client-keys: [], from the install's registry at the root" || bad "list: $LIST"
REV=$(curl -s "$AGENT/v1/auth/client-keys/revoked" -H "Authorization: Bearer $TOK")
[ "$(printf '%s' "$REV" | jq_ "len(d['ids'])")" = "0" ] && ok "the revoked set is empty" || bad "revoked: $REV"
[ -f "$WORK/client_keys.json" ] && bad "an enrolled agent keeps a client_keys.json of its own" \
  || ok "the agent keeps no record file of its own: the registry is the root's"

# --- 4 -----------------------------------------------------------------------
say "4. mint: the root signs it, the token comes back once, and is nowhere on disk"
MADE=$(curl -s -X POST "$AGENT/v1/auth/client-keys" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d '{"name":"Continue on the laptop"}')
KEY=$(printf '%s' "$MADE" | jq_ "d['token']")
KEY_ID=$(printf '%s' "$MADE" | jq_ "d['key']['id']")
TAIL=$(printf '%s' "$MADE" | jq_ "d['key']['tail']")
[ -n "$KEY" ] && [ "$(printf '%s' "$KEY" | awk -F. '{print NF}')" = "3" ] \
  && ok "a JWT came back (id $KEY_ID, tail $TAIL)" || { bad "mint: $MADE"; exit 1; }
HEADER=$(b64json "$KEY" 1); CLAIMS=$(b64json "$KEY" 2)
echo "  header: $HEADER"
echo "  claims: $CLAIMS"
[ "$(printf '%s' "$HEADER" | jq_ "(d['alg'], d['typ'])")" = "('EdDSA', 'ep-client+jwt')" ] \
  && ok "typ ep-client+jwt, alg EdDSA" || bad "wrong header: $HEADER"
[ "$(printf '%s' "$CLAIMS" | jq_ "(d['iss'], d['aud'])")" = "('control', ['gateway'])" ] \
  && ok "issued by the root, addressed to the gateway" || bad "wrong issuer or audience: $CLAIMS"
[ "$(printf '%s' "$CLAIMS" | jq_ "d['jti']")" = "$KEY_ID" ] && ok "jti is the record's id" || bad "jti mismatch"
[ -f "$WORK/client_keys.json" ] && bad "minting wrote a client_keys.json on the agent" \
  || ok "and minting wrote no record file on the agent"
LEAKS=$(grep -rlF "$KEY" "$WORK" 2>/dev/null)
[ -z "$LEAKS" ] && ok "no file the run has written carries the token -- not the root's log, not a config, not a process log" \
  || bad "THE TOKEN IS ON DISK: $LEAKS"
grep -rqE "\"tail\": ?\"$TAIL\"" "$WORK/control-state" 2>/dev/null \
  && ok "the root's replicated state keeps the tail, which identifies it" || bad "no tail in the root's state under $WORK/control-state"

# --- 5 -----------------------------------------------------------------------
say "5. the key works on the front door, exactly as a harness uses it"
R=$(curl -s -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ok\"}],\"max_tokens\":20}")
DRV=$(printf '%s' "$R" | jq_ "d.get('x_eugene_plexus',{}).get('driver','')" 2>/dev/null)
[ "$DRV" = "keys-llama" ] && ok "a completion with the client key as the only credential, served by $DRV" \
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
[ "$C" = "401" ] && ok "a client key cannot mint another at the agent ($C)" || bad "a leaked key is a key factory: $C"
C=$(code_of -X POST -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"name":"escalation"}' "$CTL/v1/auth/client-keys")
[ "$C" = "401" ] && ok "nor at the root, which is where keys are really made ($C)" || bad "the root minted on a client key's say-so: $C"

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
printf '%s' "$BODY" | grep -qi "turned off\|revok" && ok "the 401 says the key was turned off, not 'invalid token'" || bad "unhelpful 401: $(printf '%s' "$BODY" | head -c 200)"
[ "$(code_of -X DELETE -H "Authorization: Bearer $TOK" "$AGENT/v1/auth/client-keys/$KEY_ID")" = "204" ] && ok "revoking again is 204, not an error" || bad "second delete"

# --- 9 -----------------------------------------------------------------------
say "9. revoking one key leaves another working"
A=$(curl -s -X POST "$AGENT/v1/auth/client-keys" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' -d '{"name":"keeper"}')
B=$(curl -s -X POST "$AGENT/v1/auth/client-keys" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' -d '{"name":"doomed"}')
A_KEY=$(printf '%s' "$A" | jq_ "d['token']"); B_KEY=$(printf '%s' "$B" | jq_ "d['token']"); B_ID=$(printf '%s' "$B" | jq_ "d['key']['id']")
# A key the root has just minted works on its FIRST request, whatever the
# policy refresh interval: a key the gateway's policy does not list makes
# it re-read once before refusing (gateway dc71da1, 2f4d8dd). Until then it was
# "401 Key not registered" for up to a refresh, 1244 ms here with a 3 s
# refresh, and the refusal told the person to make a new key.
R=$(curl -s -w '\n%{http_code}' -H "Authorization: Bearer $A_KEY" "$GW/v1/models")
FIRST="$(printf '%s' "$R" | tail -1)"
[ "$FIRST" = "200" ] && ok "a key minted a moment ago works on its first request" \
  || bad "a key minted a moment ago answered $FIRST: $(printf '%s' "$R" | sed '$d' | head -c 200)"
# Both are live before either is touched, or "the other still works"
# below could be a key that never worked.
for _ in $(seq 1 30); do
  [ "$(code_of -H "Authorization: Bearer $A_KEY" "$GW/v1/models")" = "200" ] \
    && [ "$(code_of -H "Authorization: Bearer $B_KEY" "$GW/v1/models")" = "200" ] && break; sleep 1
done
{ [ "$(code_of -H "Authorization: Bearer $A_KEY" "$GW/v1/models")" = "200" ] \
    && [ "$(code_of -H "Authorization: Bearer $B_KEY" "$GW/v1/models")" = "200" ]; } \
  && ok "two fresh keys both open the front door" || bad "a freshly minted key was refused"
curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $TOK" "$AGENT/v1/auth/client-keys/$B_ID"
for _ in $(seq 1 30); do [ "$(code_of -H "Authorization: Bearer $B_KEY" "$GW/v1/models")" = "401" ] && break; sleep 1; done
[ "$(code_of -H "Authorization: Bearer $B_KEY" "$GW/v1/models")" = "401" ] && ok "the revoked one is refused" || bad "doomed key still works"
[ "$(code_of -H "Authorization: Bearer $A_KEY" "$GW/v1/models")" = "200" ] && ok "the other one still works -- which is the reason to mint more than one" \
  || bad "revoking one took them all down; this would be the root-key rotation with extra steps"

# --- 10 ----------------------------------------------------------------------
say "10. who may read the revocations, and whether the gateway really does"
# The narrow rule -- the gateway yes, the library and drivers no -- is
# held down by the agent's own tests, which can mint any token they
# like. What only a live run shows is that the GATEWAY is really reading
# the policy rather than the whole mechanism being dead code that check 8
# passed by coincidence; the policy it last read, which it keeps beside
# its config, is the evidence.
C=$(code_of -H "Authorization: Bearer $KEY" "$AGENT/v1/auth/client-keys/revoked")
[ "$C" = "401" ] && ok "a client key may not read the revoked set ($C)" || bad "client key read it: $C"
C=$(code_of -H "Authorization: Bearer $KEY" "$AGENT/v1/auth/client-keys/policy")
[ "$C" = "401" ] && ok "nor the policy the gateway polls ($C)" || bad "client key read the policy: $C"
[ "$(code_of -H "Authorization: Bearer $TOK" "$AGENT/v1/auth/client-keys/revoked")" = "200" ] && ok "the operator may" || bad "the operator was refused"
CACHED=""
for _ in $(seq 1 20); do
  # The gateway has no background poll: it refreshes the policy on a
  # client-key request, at most once per refresh interval. So a request
  # with the key that still works is what makes it read again.
  code_of -H "Authorization: Bearer $A_KEY" "$GW/v1/models" >/dev/null
  CACHED=$(PYTHONUTF8=1 python -c "
import json, sys
saved = json.load(open('gateway.client-keys.json', encoding='utf-8'))
print(sorted(k['id'] for k in saved['policy']['keys'] if k.get('revokedAt')))
" 2>/dev/null)
  printf '%s' "$CACHED" | grep -q "$KEY_ID" && printf '%s' "$CACHED" | grep -q "$B_ID" && break; sleep 1
done
{ printf '%s' "$CACHED" | grep -q "$KEY_ID" && printf '%s' "$CACHED" | grep -q "$B_ID"; } \
  && ok "the gateway's own policy cache lists both revoked ids -- it is reading the policy, through its agent, from the root" \
  || bad "the gateway's policy cache does not show the revocations: ${CACHED:-no gateway.client-keys.json in $WORK}"

# --- 11 ----------------------------------------------------------------------
say "11. a key survives a restart of the agent"
kill "$A_PID" 2>/dev/null; sleep 4
for p in $OWNED_PORTS; do [ "$p" = "$ENGINE_PORT" ] && continue; for pid in $(listening_pids "$p"); do taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null; done; done
sleep 2
(exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
  "$PY" -m eugene_plexus_agent --unattended > agent2.log 2>&1) &
A_PID=$!
wait_healthy "$AGENT" 90 || { bad "agent did not come back"; tail -20 agent2.log; exit 1; }
# The root came back sealed: the agent's sign-in, forwarded, unlocks it.
TOK2=$(login_agent) || { bad "no sign-in after the restart"; tail -20 agent2.log; exit 1; }
LIST=$(curl -s "$AGENT/v1/auth/client-keys" -H "Authorization: Bearer $TOK2")
printf '%s' "$LIST" | grep -q "keeper" && ok "the record survived the restart" || bad "records lost: $LIST"
REV=$(curl -s "$AGENT/v1/auth/client-keys/revoked" -H "Authorization: Bearer $TOK2")
printf '%s' "$REV" | grep -q "$B_ID" && ok "so did the revocation -- a restart must not un-revoke a key" || bad "revocation lost: $REV"
# And the KEY still works, which is the property a person cares about:
# a key pasted into Continue must survive a reboot. It does because the
# root signed it with its own token key, which the root keeps sealed in
# its state and opens again at sign-in, and the bundle the gateway reads
# still names that key. No node holds a key that could sign one.
wait_healthy "$GW" 180 || note "gateway slow to return after the restart"
SURVIVED=""
for _ in $(seq 1 60); do
  [ "$(code_of -H "Authorization: Bearer $A_KEY" "$GW/v1/models")" = "200" ] && { SURVIVED=1; break; }; sleep 1
done
[ -n "$SURVIVED" ] && ok "a key minted before the restart still works after it -- the root's token key outlives the process"   || bad "the key died with the process: $(code_of -H "Authorization: Bearer $A_KEY" "$GW/v1/models")"
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
printf '\n%s PASS\n' "$PASSES"
if [ "$FAILURES" -eq 0 ]; then
  printf '\nALL CHECKS PASSED\n'
else
  printf '\n%s CHECK(S) FAILED\n' "$FAILURES"
  exit 1
fi
