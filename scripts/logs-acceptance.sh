#!/usr/bin/env bash
#
# Every machine's log from one console, and Start after a failed load
# (2026-09-27).
#
#   host A (this box)   agent A :8179 -> control :8183, gateway :8180, library :8182
#   host B (also here)  agent B :8184, trusting the llama-server directory
#
# Both agents enroll with the control root as library-folders-acceptance.sh
# does. Then, from A's console:
#   4. A's own log: every line stamped, the sources A supervises
#   5. B's log through the node hop (node:node-b): B's lines, not A's;
#      no credential, no log
#   6. a token written into B's log comes back masked
#   7. a follow through the hop gets a line B writes after it opened
#   8. a model whose load fails on B: crashed with its engine's lines in
#      B's log, then Start is a new attempt -- it answered "already
#      running; nothing to do" before the fix
#   9. the browser: all machines, one machine, the engine's lines, a live line
#
# **Safe beside a live install.** Ports +100, teardown by pid, refuses to
# run if a port it wants is taken; every ambient EUGENE_PLEXUS_* variable
# is dropped first.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
LLAMA="${EP_LLAMA_SERVER:-C:/Users/troyc/OneDrive/Desktop/llamacpp/llama-server.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-logs}"
A_PORT="${EP_AGENT_A_PORT:-8179}"; GW_PORT="${EP_GATEWAY_PORT:-8180}"
LIB_PORT="${EP_LIBRARY_PORT:-8182}"; CTL_PORT="${EP_CONTROL_PORT:-8183}"
B_PORT="${EP_AGENT_B_PORT:-8184}"
SKIP_BUILD="${EP_SKIP_BUILD:-0}"
PASS="logs-$$-$(date +%s)-acceptance"
RT="broken"
MARKER="logs-live-marker-$$"
# JWT-shaped, so the agent's mask must catch it; not a real token.
FAKE_JWT="eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiJub2JvZHktJCQifQ.bm90LWEtcmVhbC1zaWduYXR1cmU"

ADV_HOST="${EP_ADVERTISE_HOST:-$(PYTHONUTF8=1 python -c "import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
try:
    s.connect(('192.0.2.1',9)); print(s.getsockname()[0])
except OSError:
    print('127.0.0.1')" 2>/dev/null || echo 127.0.0.1)}"
A_URL="http://$ADV_HOST:$A_PORT"; B_URL="http://$ADV_HOST:$B_PORT"
CTL="http://$ADV_HOST:$CTL_PORT"; GW="http://127.0.0.1:$GW_PORT"; LIB="http://127.0.0.1:$LIB_PORT"
HOP="$A_URL/api/proxy/node:node-b"
OWNED_PORTS="$A_PORT $GW_PORT $LIB_PORT $CTL_PORT $B_PORT"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
win_path() { cygpath -m "$1"; }
bs_path() { win_path "$1" | sed 's|/|\\|g'; }
json_bs() { printf '%s' "$1" | sed 's|\\|\\\\|g'; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }

A_PID=""; B_PID=""; FOLLOW_PID=""
teardown() {
  [ -n "$FOLLOW_PID" ] && kill "$FOLLOW_PID" 2>/dev/null
  [ -n "$B_PID" ] && kill "$B_PID" 2>/dev/null
  [ -n "$A_PID" ] && kill "$A_PID" 2>/dev/null
  sleep 3
  for p in $OWNED_PORTS; do for pid in $(listening_pids "$p"); do taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null; done; done
  printf '\n== result\n'
  [ "$FAILURES" = 0 ] && printf '  ALL CHECKS PASSED\n' || printf '  %s CHECK(S) FAILED\n' "$FAILURES"
}

# --- 1. preflight -------------------------------------------------------------------
say "1. preflight"
[ -f "$PY" ] || { bad "agent python not found at $PY"; exit 1; }
[ -f "$LLAMA" ] || { bad "llama-server not found at $LLAMA"; exit 1; }
"$PY" -c "import eugene_plexus_agent, eugene_plexus_control, eugene_plexus_gateway, eugene_plexus_library" 2>/dev/null || { bad "components must import from $PY"; exit 1; }
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p is in use"; exit 1; }; done
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "every port free, no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }
rm -rf "$WORK"; mkdir -p "$WORK/a" "$WORK/b" "$WORK/nas/models"; cd "$WORK" || exit 1
trap teardown EXIT
# A model file llama.cpp cannot load: the load fails before the engine is ready.
head -c 4096 /dev/urandom > "nas/models/broken.gguf"
LIB_ROOT_BS="$(bs_path "$WORK/nas/models")"
ok "a Library folder holding a model that cannot load: $LIB_ROOT_BS\\broken.gguf"

# --- 2. this working tree's UI --------------------------------------------------------
say "2. stage this working tree's UI into the wheel the agent serves"
if [ "$SKIP_BUILD" = "1" ]; then
  ok "skipped by EP_SKIP_BUILD=1"
else
  (cd "$UI_DIR" && npm run build:python > "$WORK/build.log" 2>&1)
  [ $? = 0 ] && ok "npm run build:python staged the export" || { bad "build failed"; tail -30 "$WORK/build.log"; exit 1; }
fi
STATIC="$UI_DIR/python/eugene_plexus_ui/static"
[ -f "$STATIC/logs/index.html" ] || [ -f "$STATIC/logs.html" ] \
  && ok "the staged export carries /logs" || bad "no /logs in the staged export"

cat > a/agent.yaml <<YAML
firstRunComplete: true
advertiseUrl: $A_URL
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
printf 'logLevel: INFO\nroutingRefreshSeconds: 3\n' > a/gateway.yaml
echo "logLevel: INFO" > a/control.yaml
printf "logLevel: INFO\nmodelRoots:\n  - path: '%s'\n    mounts: []\n" "$LIB_ROOT_BS" > a/library.yaml
printf "firstRunComplete: true\nengineBinaryRoots:\n  - '%s'\ncomponents: []\nruntimes: []\n" \
  "$(dirname "$LLAMA")" > b/agent.yaml
BIND=()
[ "$ADV_HOST" != "127.0.0.1" ] && BIND=(EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0)

# --- 3. the install ------------------------------------------------------------------
say "3. agent A (control, gateway, library) and agent B, both enrolled"
(cd a && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$A_PORT" "${BIND[@]}" "$PY" -m eugene_plexus_agent --unattended > ../agent-a.console 2>&1) &
A_PID=$!
wait_healthy "$A_URL" && wait_healthy "$CTL" && wait_healthy "$LIB" && wait_healthy "$GW" 90 \
  && ok "agent A and its three components answering" || { bad "A never came up"; tail -30 agent-a.console; exit 1; }
curl -s -o /dev/null -X POST "$CTL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}"
CTOK=$(curl -s -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
ATOK=$(curl -s -X POST "$A_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
(cd b && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$B_PORT" "${BIND[@]}" "$PY" -m eugene_plexus_agent --unattended > ../agent-b.console 2>&1) &
B_PID=$!
wait_healthy "$B_URL" || { bad "agent B never came up"; tail -30 agent-b.console; exit 1; }
BTOK=$(curl -s -X POST "$B_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
TOK_A=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"node-a","grants":["gateway"]}' | jq_ "d['token']")
[ "$(code_of -X POST -H "Authorization: Bearer $ATOK" "$A_URL/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$TOK_A\",\"name\":\"node-a\"}")" = "200" ] || { bad "A enroll failed"; exit 1; }
wait_healthy "$GW" 90; wait_healthy "$LIB" 60
TOK_B=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"node-b"}' | jq_ "d['token']")
[ "$(code_of -X POST -H "Authorization: Bearer $BTOK" "$B_URL/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$TOK_B\",\"name\":\"node-b\"}")" = "200" ] || { bad "B enroll failed"; exit 1; }
for _ in $(seq 1 30); do
  NODES=$(curl -s -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes")
  [ "$(echo "$NODES" | jq_ "all(n['reachable'] for n in d['nodes']) and len(d['nodes'])==2")" = "True" ] && break; sleep 1
done
sleep 2
TOK=""; TOKB=""
for _ in $(seq 1 30); do
  TOK=$(curl -s -X POST "$A_URL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
  TOKB=$(curl -s -X POST "$B_URL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
  [ -n "$TOK" ] && [ -n "$TOKB" ] && break; sleep 1
done
[ -n "$TOK" ] && [ -n "$TOKB" ] && ok "both enrolled; a session from each sign-in" || { bad "no sessions after enrollment"; exit 1; }

# --- 4. A's own log ---------------------------------------------------------------------
say "4. A's own log, read by A's operator"
LA=$(curl -s -H "Authorization: Bearer $TOK" "$A_URL/v1/logs?tail=2000")
[ "$(echo "$LA" | jq_ "len(d['lines'])>0 and all(l['time'] for l in d['lines'])")" = "True" ] \
  && ok "$(echo "$LA" | jq_ "len(d['lines'])") lines, every one stamped" || bad "A's lines: $(echo "$LA" | head -c 400)"
[ "$(echo "$LA" | jq_ "all(s in d['sources'] for s in ['agent','control','gateway','library'])")" = "True" ] \
  && ok "sources: $(echo "$LA" | jq_ "', '.join(d['sources'])")" || bad "A's sources: $(echo "$LA" | jq_ "d['sources']")"
[ "$(echo "$LA" | jq_ "any(l['text'].startswith('INFO') and not l['text'][:4].isdigit() for l in d['lines'] if l['source']=='agent')")" = "True" ] \
  && ok "the agent's own lines carry the stamp, not a second local time" || bad "the agent's own lines still start with a local time"

# --- 5. B's log, from A's console ---------------------------------------------------------
say "5. B's log through the node hop, from A's console"
LB=$(curl -s -H "Authorization: Bearer $TOK" "$HOP/v1/logs?tail=2000")
[ "$(echo "$LB" | jq_ "len(d['lines'])>0 and 'gateway' not in d['sources'] and 'agent' in d['sources']")" = "True" ] \
  && ok "B's own lines ($(echo "$LB" | jq_ "len(d['lines'])")), sources $(echo "$LB" | jq_ "d['sources']") -- none of A's" \
  || bad "through the hop: $(echo "$LB" | head -c 400)"
[ "$(code_of "$B_URL/v1/logs")" = "401" ] && [ "$(code_of "$HOP/v1/logs")" = "401" ] \
  && ok "no credential, no log: 401 at B and through the hop" || bad "a log without a credential"

# --- 6. masking -------------------------------------------------------------------------
say "6. a token written into B's log comes back masked"
curl -s -o /dev/null "$B_URL/v1/no-such-route-$$?token=$FAKE_JWT"
sleep 1
LM=$(curl -s -G -H "Authorization: Bearer $TOK" "$HOP/v1/logs" --data-urlencode "contains=no-such-route-$$")
[ "$(echo "$LM" | jq_ "len(d['lines'])>=1 and all('[redacted]' in l['text'] and 'eyJ' not in l['text'] for l in d['lines'])")" = "True" ] \
  && ok "the access line is there, and the token in it is [redacted]" || bad "masking: $(echo "$LM" | head -c 400)"
grep -q "$FAKE_JWT" b/logs/agent.log && ok "(the file itself holds it, as written -- the mask is on the way out)" \
  || bad "the file did not hold the line at all, so the mask proved nothing"

# --- 7. following -----------------------------------------------------------------------
say "7. a follow through the hop gets a line written after it opened"
curl -sN -G -H "Authorization: Bearer $TOK" "$HOP/v1/logs/stream" --data-urlencode "contains=$MARKER" > follow.txt 2>&1 &
FOLLOW_PID=$!
for _ in $(seq 1 20); do grep -q ": following" follow.txt 2>/dev/null && break; sleep 0.5; done
grep -q ": following" follow.txt && ok "the follow is open" || bad "the follow never opened: $(head -c 300 follow.txt)"
curl -s -o /dev/null "$B_URL/v1/$MARKER"
for _ in $(seq 1 20); do grep -q "event: line" follow.txt && break; sleep 0.5; done
grep -q "event: line" follow.txt && grep -q "$MARKER" follow.txt \
  && ok "the line arrived: $(grep -m1 '^data:' follow.txt | cut -c1-140)" || bad "no line followed: $(cat follow.txt | head -c 400)"
kill "$FOLLOW_PID" 2>/dev/null; FOLLOW_PID=""

# --- 8. a model whose load fails, then Start ------------------------------------------------
say "8. a model whose load fails on B, then Start"
MODEL_JSON="$(json_bs "$LIB_ROOT_BS\\broken.gguf")"
BIN_JSON="$(win_path "$LLAMA" | sed 's|/|\\\\|g')"
SPEC="{\"name\":\"$RT\",\"engine\":\"llama_cpp\",\"modelPath\":\"$MODEL_JSON\",\"binary\":\"$BIN_JSON\",\"flags\":{\"contextSize\":2048,\"gpuLayers\":0}}"
R=$(curl -s -w '\n%{http_code}' -X POST -H "Authorization: Bearer $TOKB" "$B_URL/v1/runtimes?force=true" -H 'content-type: application/json' -d "$SPEC")
[ "$(echo "$R" | tail -1)" = "201" ] && ok "declared $RT on B" || { bad "declare: $(echo "$R" | head -c 400)"; exit 1; }
ST=""
for _ in $(seq 1 60); do
  ST=$(curl -s -H "Authorization: Bearer $TOKB" "$B_URL/v1/runtimes/$RT" | jq_ "d.get('status')" 2>/dev/null)
  [ "$ST" = "crashed" ] && break; sleep 1
done
[ "$ST" = "crashed" ] && ok "the load failed and the agent gave up: $ST" || bad "status $ST, not crashed"
FIRST=$(curl -s -H "Authorization: Bearer $TOKB" "$B_URL/v1/runtimes/$RT" | jq_ "d.get('lastRestart')")
LE=$(curl -s -G -H "Authorization: Bearer $TOK" "$HOP/v1/logs" --data-urlencode "source=engine: $RT")
[ "$(echo "$LE" | jq_ "len(d['lines'])>0 and all(l['source']=='engine: $RT' for l in d['lines'])")" = "True" ] \
  && ok "its engine's own lines, by source, from A's console: $(echo "$LE" | jq_ "d['lines'][-1]['text'][:100]")" \
  || bad "engine lines: $(echo "$LE" | head -c 400)"
S=$(curl -s -X POST -H "Authorization: Bearer $TOKB" "$B_URL/v1/runtimes/$RT/start?force=true")
[ "$(echo "$S" | jq_ "d.get('scheduled')")" = "True" ] \
  && ok "Start is a new attempt: $(echo "$S" | jq_ "d.get('message')")" \
  || bad "Start answered: $S"
SECOND=""
for _ in $(seq 1 60); do
  SECOND=$(curl -s -H "Authorization: Bearer $TOKB" "$B_URL/v1/runtimes/$RT" | jq_ "d.get('lastRestart')")
  [ -n "$SECOND" ] && [ "$SECOND" != "$FIRST" ] && break; sleep 1
done
[ -n "$SECOND" ] && [ "$SECOND" != "$FIRST" ] && ok "and it really spawned again ($FIRST -> $SECOND)" || bad "no second spawn: $FIRST / $SECOND"

# --- 9. the browser -----------------------------------------------------------------------
say "9. the browser: all machines, one machine, the engine's lines, a live line"
(cd "$UI_DIR" && EP_UI_URL="$A_URL" EP_PASSPHRASE="$PASS" EP_NODE_A="node-a" EP_NODE_B="node-b" \
  EP_ENGINE_SOURCE="engine: $RT" EP_B_URL="$B_URL" EP_LIVE_MARKER="browser-$MARKER" \
  npx playwright test e2e/logs.spec.ts > "$WORK/playwright.log" 2>&1)
if [ $? = 0 ]; then
  ok "the Logs spec passed: $(grep -E '[0-9]+ passed' "$WORK/playwright.log" | tail -1 | tr -s ' ')"
else
  bad "the Logs spec failed"
  tail -60 "$WORK/playwright.log"
fi
[ "$FAILURES" = 0 ]
