#!/usr/bin/env bash
#
# M11 acceptance: compute/storage separation -- a model the library names by
# ITS path, opened where the launching node has it.
#
#   host A (this box)   agent A :8179 -> control :8183, gateway :8180, library :8182
#   host B (also here)  agent B :8184 -> the runtime, and NO library
#
# The library's one root holds a real GGUF (a copy, so the file's identity is
# the library's and nobody else's). Node B carries a second directory with a
# hard link to the same bytes -- the "mount" -- and no library of its own.
# Both agents enroll with the control root exactly as m7-acceptance.sh does;
# that arc is compressed here, not re-proved.
#
# WHAT ONE BOX PROVES AND DOES NOT -- printed again at the end.
#   proves: a declaration of a path this host does not have is REFUSED with the
#           fix, before anything spawns (until M11 it was accepted and crashed);
#           a mapping makes the same declaration launch, the engine opens the
#           MAPPED path while the declaration keeps the library's; the runtime
#           still resolves to its library entry; a worker with no library
#           reaches the install's through the owning node's agent and is
#           measured by metadata; the Test button checks a mapping against
#           real files; the directory listing on both components.
#   cannot: that the mapping was NECESSARY -- both agents can open the
#           library's own path here, so the necessity half is visible only on
#           the live two-machine install; a share mounted read-only or lazily;
#           a Linux `to`.
#
# Design: docs/design/m11-compute-storage-separation.md (§11 is the plan
# this follows, §13 the record).
#
# **Safe beside a live install, in both dimensions.** Ports: every service
# binds +100 from the install defaults, teardown is by the pids this script
# started, and it refuses to run if a port it wants is taken. State: every
# ambient EUGENE_PLEXUS_* variable is dropped first -- `install.ps1` sets
# the agent's config path in the USER environment, and a throwaway agent
# that inherits it comes up as the operator's own node and re-announces
# its address to the real control root (found the hard way, 2026-09-12).
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
LLAMA="${EP_LLAMA_SERVER:-C:/Users/troyc/OneDrive/Desktop/llamacpp/llama-server.exe}"
MODEL="${EP_MODEL:-D:/py/eugene-plexus/smoke-test/models/Qwen3-1.7B-Q8_0.gguf}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-m11-acceptance}"
A_PORT="${EP_AGENT_A_PORT:-8179}"; GW_PORT="${EP_GATEWAY_PORT:-8180}"
LIB_PORT="${EP_LIBRARY_PORT:-8182}"; CTL_PORT="${EP_CONTROL_PORT:-8183}"
B_PORT="${EP_AGENT_B_PORT:-8184}"
PASS="m11-$$-$(date +%s)"
ALIAS="qwen3-1.7b"
RT="qwen-mapped"     # launched from a path that exists nowhere on this box
RT2="qwen-library"   # declared from the library's own path
# The library's path, as a foreign host would state it: POSIX-shaped, so
# on this Windows box `abspath` would read it as C:\srv\models -- a
# different path, not a missing one, which is exactly the trap.
FOREIGN_ROOT="/srv/models"

# A's advertise host. Non-loopback, so the install's registry carries an
# address B can dial for A's agent -- the install-wide library lookup
# refuses to dial a loopback registry entry, correctly ("explained, not
# dialled"). Detected from the interface a default route would use; no
# packet is sent. Override with EP_ADVERTISE_HOST; set it to 127.0.0.1 to
# see check 10 degrade to file size, honestly.
ADV_HOST="${EP_ADVERTISE_HOST:-$(PYTHONUTF8=1 python -c "import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
try:
    s.connect(('192.0.2.1',9)); print(s.getsockname()[0])
except OSError:
    print('127.0.0.1')" 2>/dev/null || echo 127.0.0.1)}"
A_URL="http://$ADV_HOST:$A_PORT"; B_URL="http://$ADV_HOST:$B_PORT"
CTL="http://$ADV_HOST:$CTL_PORT"; GW="http://127.0.0.1:$GW_PORT"; LIB="http://127.0.0.1:$LIB_PORT"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
win_path() { cygpath -m "$1"; }
json_path() { win_path "$1" | sed 's|/|\\\\|g'; }   # C:\\a\\b, JSON-escaped
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

A_PID=""; B_PID=""
teardown() {
  [ -n "$A_PID" ] && kill "$A_PID" 2>/dev/null
  [ -n "$B_PID" ] && kill "$B_PID" 2>/dev/null
}

# --- 1. preflight ---------------------------------------------------------------
say "1. preflight"
[ -f "$PY" ] || { bad "agent python not found at $PY"; exit 1; }
[ -f "$LLAMA" ] || { bad "llama-server not found at $LLAMA"; exit 1; }
[ -f "$MODEL" ] || { bad "model not found at $MODEL"; exit 1; }
"$PY" -c "import eugene_plexus_agent, eugene_plexus_control, eugene_plexus_gateway, eugene_plexus_inference_driver, eugene_plexus_library" 2>/dev/null || { bad "all five components must import from $PY"; exit 1; }
for p in $A_PORT $GW_PORT $LIB_PORT $CTL_PORT $B_PORT; do
  if netstat -ano 2>/dev/null | grep ":$p " | grep -q LISTENING; then bad "port $p is in use; stop it or set EP_*_PORT"; exit 1; fi
done
ok "binary, model, five components; A=$A_URL B=$B_URL control=$CTL; every port free"
[ "$ADV_HOST" = "127.0.0.1" ] && note "no non-loopback address detected; check 10's metadata basis cannot pass on loopback (see the header)"

for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
rm -rf "$WORK"; mkdir -p "$WORK/a" "$WORK/b" "$WORK/nas/models" "$WORK/node-b/mnt/models"; cd "$WORK" || exit 1
trap teardown EXIT

# The library's copy of the model, and B's "mount" of the same bytes.
cp "$MODEL" "nas/models/$(basename "$MODEL")"
ln "nas/models/$(basename "$MODEL")" "node-b/mnt/models/$(basename "$MODEL")" 2>/dev/null || cp "nas/models/$(basename "$MODEL")" "node-b/mnt/models/$(basename "$MODEL")"
LIB_ROOT="$(win_path "$WORK/nas/models")"             # C:/.../nas/models  (what the library is configured with)
MOUNT="$(win_path "$WORK/node-b/mnt/models")"         # C:/.../node-b/mnt/models
MOUNT_BS="$(printf '%s' "$MOUNT" | sed 's|/|\\|g')"   # C:\...\node-b\mnt\models  (how the agent spells a local path)
BASENAME="$(basename "$MODEL")"
ok "library root $LIB_ROOT holds the model; B's mount $MOUNT holds the same bytes"

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
printf 'logLevel: INFO\nroutingRefreshSeconds: 3\nidleCheckSeconds: 5\nswapWaitSeconds: 120\ncontrolUrl: http://127.0.0.1:%s\n' "$CTL_PORT" > a/gateway.yaml
echo "logLevel: INFO" > a/control.yaml
printf 'logLevel: INFO\nmodelRoots:\n  - %s\n' "$(printf '%s' "$LIB_ROOT" | sed 's|/|\\|g')" > a/library.yaml
printf 'firstRunComplete: true\ncomponents: []\nruntimes: []\n' > b/agent.yaml

BIND=()
[ "$ADV_HOST" != "127.0.0.1" ] && BIND=(EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0)

# --- 2. the install: A's fleet, B, both enrolled ------------------------------------
say "2. agent A (control, gateway, library) and agent B, both enrolled"
(cd a && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$A_PORT" "${BIND[@]}" "$PY" -m eugene_plexus_agent > ../agent-a.log 2>&1) &
A_PID=$!
wait_healthy "$A_URL" && ok "agent A answering at $A_URL" || { bad "agent A never came up"; tail -30 agent-a.log; exit 1; }
wait_healthy "$CTL" && wait_healthy "$LIB" && wait_healthy "$GW" 90 && ok "control, library and gateway answering" || { bad "A's children never came up"; tail -30 agent-a.log; exit 1; }
curl -s -o /dev/null -X POST "$CTL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}"
CTOK=$(curl -s -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
ATOK=$(curl -s -X POST "$A_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$CTOK" ] && [ -n "$ATOK" ] && ok "control and agent A initialized" || { bad "no sessions"; exit 1; }

(cd b && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$B_PORT" "${BIND[@]}" "$PY" -m eugene_plexus_agent > ../agent-b.log 2>&1) &
B_PID=$!
wait_healthy "$B_URL" && ok "agent B answering at $B_URL" || { bad "agent B never came up"; tail -30 agent-b.log; exit 1; }
BTOK=$(curl -s -X POST "$B_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")

TOK_A=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"node-a"}' | jq_ "d['token']")
[ "$(code_of -X POST -H "Authorization: Bearer $ATOK" "$A_URL/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$TOK_A\",\"name\":\"node-a\"}")" = "200" ] && ok "A enrolled as node-a" || { bad "A enroll failed"; tail -20 agent-a.log; exit 1; }
wait_healthy "$GW" 90 || bad "gateway did not come back after A adopted the install key"
wait_healthy "$LIB" 60 || bad "library did not come back after A adopted the install key"
TOK_B=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"node-b"}' | jq_ "d['token']")
[ "$(code_of -X POST -H "Authorization: Bearer $BTOK" "$B_URL/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$TOK_B\",\"name\":\"node-b\"}")" = "200" ] && ok "B enrolled as node-b" || { bad "B enroll failed"; tail -20 agent-b.log; exit 1; }
for _ in $(seq 1 30); do
  NODES=$(curl -s -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes")
  [ "$(echo "$NODES" | jq_ "all(n['reachable'] for n in d['nodes']) and len(d['nodes'])==2")" = "True" ] && break; sleep 1
done
echo "  nodes: $(echo "$NODES" | jq_ "[(n['name'], (n.get('url') or '').rstrip('/'), n['reachable']) for n in d['nodes']]")"
[ "$(echo "$NODES" | jq_ "all(n['reachable'] for n in d['nodes'])")" = "True" ] && ok "control root reaches both nodes" || bad "a node is unreachable"

# --- 3. the library knows the model; B has no library ---------------------------------
say "3. the library lists the model under A's root; B declares no library"
for _ in $(seq 1 60); do
  LIBM=$(curl -s -H "Authorization: Bearer $CTOK" "$LIB/v1/models")
  [ "$(echo "$LIBM" | jq_ "len(d.get('models',[]))")" = "1" ] && break; sleep 1
done
LIB_PATH=$(echo "$LIBM" | jq_ "d['models'][0]['path']")
LIB_SIZE=$(echo "$LIBM" | jq_ "d['models'][0].get('sizeBytes')")
[ -n "$LIB_PATH" ] && ok "library lists $LIB_PATH ($LIB_SIZE bytes)" || { bad "library never listed the model: $LIBM"; exit 1; }
[ "$(curl -s -H "Authorization: Bearer $CTOK" "$B_URL/v1/components" | jq_ "any(c['kind']=='library' for c in d['components'])")" = "False" ] && ok "B's topology has no library" || bad "B declares a library"
LIB_PATH_JSON=$(printf '%s' "$LIB_PATH" | sed 's|\\|\\\\|g')
LIB_ROOT_BS=$(printf '%s' "$LIB_ROOT" | sed 's|/|\\|g')

# --- 4. a path this host does not have is refused, with the fix -----------------------
say "4. declare $RT on node-b through control: $FOREIGN_ROOT/$BASENAME exists nowhere here"
SPEC_FOREIGN="{\"name\":\"$RT\",\"engine\":\"llama_cpp\",\"modelPath\":\"$FOREIGN_ROOT/$BASENAME\",\"modelAlias\":\"$ALIAS\",\"binary\":\"$(json_path "$LLAMA")\",\"flags\":{\"contextSize\":4096,\"gpuLayers\":99,\"parallelSlots\":1}}"
R=$(curl -s -w '\n%{http_code}' -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/runtimes" -H 'content-type: application/json' -d "{\"node\":\"node-b\",\"spec\":$SPEC_FOREIGN}")
CODE=$(echo "$R" | tail -1); BODY=$(echo "$R" | sed '$d'); DETAIL=$(echo "$BODY" | jq_ "d['detail']['detail']" 2>/dev/null)
[ "$CODE" = "502" ] && ok "control relays the node's refusal as 502" || bad "control answered $CODE: $BODY"
echo "$DETAIL" | grep -q "answered 422" && ok "...and the node answered 422, not 201: nothing was declared" || bad "detail: $DETAIL"
echo "$DETAIL" | grep -q "$FOREIGN_ROOT/$BASENAME is not on node-b" && ok "the refusal names the path and the node" || bad "detail: $DETAIL"
echo "$DETAIL" | grep -q "Model directory mappings" && ok "*** ...and the fix: Config -> Agent @ node-b -> Model directory mappings ***" || bad "detail does not name the fix: $DETAIL"
[ "$(curl -s -H "Authorization: Bearer $CTOK" "$B_URL/v1/runtimes" | jq_ "len(d['runtimes'])")" = "0" ] && ok "B has no runtime and no companion for it" || bad "B declared something"

# --- 5. the dry run says the same, structured ----------------------------------------
say "5. POST node-b /v1/runtimes/admission for the same spec"
ADM=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$B_URL/v1/runtimes/admission" -H 'content-type: application/json' -d "$SPEC_FOREIGN")
[ "$(echo "$ADM" | jq_ "d['decision']")" = "refuse" ] && ok "decision=refuse, fit=$(echo "$ADM" | jq_ "d['fit']")" || bad "admission: $ADM"
[ "$(echo "$ADM" | jq_ "d['location']['exists']")" = "False" ] && [ "$(echo "$ADM" | jq_ "d['location'].get('mapping')")" = "None" ] && ok "location.exists=false, no mapping applied, localPath=$(echo "$ADM" | jq_ "d['location']['localPath']")" || bad "location: $(echo "$ADM" | jq_ "d.get('location')")"

# --- 6. the mapping --------------------------------------------------------------------
say "6. PATCH node-b config: $FOREIGN_ROOT -> $MOUNT_BS"
SCHEMA=$(curl -s -H "Authorization: Bearer $CTOK" "$B_URL/v1/config/schema")
[ "$(echo "$SCHEMA" | jq_ "next((f['valueType'] for f in d['fields'] if f['key']=='pathMappings'), None)")" = "path_mappings" ] && ok "the schema offers pathMappings as path_mappings" || bad "schema: $(echo "$SCHEMA" | head -c 200)"
PATCH=$(curl -s -X PATCH -H "Authorization: Bearer $CTOK" "$B_URL/v1/config" -H 'content-type: application/json' -d "{\"pathMappings\":[{\"from\":\"$FOREIGN_ROOT\",\"to\":\"$(json_path "$WORK/node-b/mnt/models")\"}]}")
[ "$(echo "$PATCH" | jq_ "d['applied']")" = "['pathMappings']" ] && ok "mapping applied: $(curl -s -H "Authorization: Bearer $CTOK" "$B_URL/v1/config" | jq_ "d['pathMappings']")" || bad "patch: $PATCH"
BADPATCH=$(curl -s -X PATCH -H "Authorization: Bearer $CTOK" "$B_URL/v1/config" -H 'content-type: application/json' -d '{"pathMappings":[{"from":"models","to":"Z:\\models"}]}')
[ "$(echo "$BADPATCH" | jq_ "d['rejected'][0]['key'] if d['rejected'] else ''")" = "pathMappings" ] && ok "a relative from is rejected: $(echo "$BADPATCH" | jq_ "d['rejected'][0]['message'][:70]")" || bad "bad patch accepted: $BADPATCH"

# --- 7. the same declaration launches, and opens the MAPPED path -----------------------
say "7. the same declaration on node-b, through control"
R=$(curl -s -w '\n%{http_code}' -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/runtimes" -H 'content-type: application/json' -d "{\"node\":\"node-b\",\"spec\":$SPEC_FOREIGN}")
CODE=$(echo "$R" | tail -1); BODY=$(echo "$R" | sed '$d')
[ "$CODE" = "201" ] && ok "*** 201: the declaration that was refused a minute ago is accepted with the mapping ***" || { bad "control answered $CODE: $BODY"; tail -20 agent-b.log; }
RB=$(curl -s -H "Authorization: Bearer $CTOK" "$B_URL/v1/runtimes/$RT")
[ "$(echo "$RB" | jq_ "d['modelPath']")" = "$FOREIGN_ROOT/$BASENAME" ] && ok "Runtime.modelPath is the declaration, untouched: $FOREIGN_ROOT/$BASENAME" || bad "modelPath: $(echo "$RB" | jq_ "d['modelPath']")"
[ "$(echo "$RB" | jq_ "d.get('localPath')")" = "$MOUNT_BS\\$BASENAME" ] && ok "*** Runtime.localPath is the mount: $MOUNT_BS\\$BASENAME ***" || bad "localPath: $(echo "$RB" | jq_ "d.get('localPath')")"
for _ in $(seq 1 120); do
  RB=$(curl -s -H "Authorization: Bearer $CTOK" "$B_URL/v1/runtimes/$RT"); ST=$(echo "$RB" | jq_ "d.get('status')" 2>/dev/null)
  [ "$ST" = "ready" ] || [ "$ST" = "crashed" ] && break; sleep 1
done
[ "$ST" = "ready" ] && ok "engine ready on node-b" || { bad "runtime status=$ST $(echo "$RB" | jq_ "d.get('lastError')")"; tail -20 agent-b.log; }
[ "$(echo "$RB" | jq_ "'--model' in (d.get('argv') or []) and (d['argv'][d['argv'].index('--model')+1] == r'$MOUNT_BS\\$BASENAME')")" = "True" ] && ok "*** the engine's argv names the MAPPED path, never the declaration ***" || bad "argv: $(echo "$RB" | jq_ "d.get('argv')")"

# --- 8. served ------------------------------------------------------------------------
say "8. a completion through the gateway, served by $RT"
for _ in $(seq 1 60); do
  RN=$(curl -s -H "Authorization: Bearer $CTOK" "$GW/v1/models" | jq_ "next((m['x_eugene_plexus'].get('ready_backends') for m in d.get('data',[]) if m['id']=='$ALIAS'), 0)" 2>/dev/null)
  [ "$RN" = "1" ] && break; sleep 1
done
[ "$RN" = "1" ] && ok "gateway lists $ALIAS with ready_backends=1" || bad "gateway never listed $ALIAS ready (ready_backends=$RN)"
C=$(curl -s -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $CTOK" -H 'content-type: application/json' -d "{\"model\":\"$ALIAS\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word OK. /no_think\"}],\"max_tokens\":16,\"temperature\":0.1}")
TXT=$(echo "$C" | jq_ "(d.get('choices') or [{}])[0].get('message',{}).get('content','').strip()" 2>/dev/null)
[ -n "$TXT" ] && [ "$(echo "$C" | jq_ "d['x_eugene_plexus'].get('runtime')")" = "$RT" ] && ok "*** COMPLETION from a model opened through a mapping: '$TXT' (runtime=$RT) ***" || bad "completion: $(echo "$C" | head -c 300)"

# --- 9. the library's own path, mapped; the join survives --------------------------------
say "9. map the LIBRARY's root to the mount; declare $RT2 from the library's own path"
PATCH=$(curl -s -X PATCH -H "Authorization: Bearer $CTOK" "$B_URL/v1/config" -H 'content-type: application/json' -d "{\"pathMappings\":[{\"from\":\"$FOREIGN_ROOT\",\"to\":\"$(json_path "$WORK/node-b/mnt/models")\"},{\"from\":\"$(printf '%s' "$LIB_ROOT_BS" | sed 's|\\|\\\\|g')\",\"to\":\"$(json_path "$WORK/node-b/mnt/models")\"}]}")
[ "$(echo "$PATCH" | jq_ "d['applied']")" = "['pathMappings']" ] && ok "two mappings applied" || bad "patch: $PATCH"
SPEC_LIB="{\"name\":\"$RT2\",\"engine\":\"llama_cpp\",\"modelPath\":\"$LIB_PATH_JSON\",\"modelAlias\":\"qwen3-lib\",\"binary\":\"$(json_path "$LLAMA")\",\"autoStart\":false,\"flags\":{\"contextSize\":4096,\"gpuLayers\":99}}"
R=$(curl -s -w '\n%{http_code}' -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/runtimes" -H 'content-type: application/json' -d "{\"node\":\"node-b\",\"spec\":$SPEC_LIB}")
CODE=$(echo "$R" | tail -1)
[ "$CODE" = "201" ] && ok "declared $RT2 (autoStart false: the join, not the GPU, is under test)" || bad "control answered $CODE: $(echo "$R" | sed '$d')"
RB2=$(curl -s -H "Authorization: Bearer $CTOK" "$B_URL/v1/runtimes/$RT2")
[ "$(echo "$RB2" | jq_ "d['modelPath']")" = "$LIB_PATH" ] && ok "Runtime.modelPath is the library's spelling" || bad "modelPath: $(echo "$RB2" | jq_ "d['modelPath']")"
[ "$(echo "$RB2" | jq_ "d.get('localPath')")" = "$MOUNT_BS\\$BASENAME" ] && ok "Runtime.localPath is the mount" || bad "localPath: $(echo "$RB2" | jq_ "d.get('localPath')")"
JOIN=$(curl -s -G -H "Authorization: Bearer $CTOK" "$LIB/v1/models" --data-urlencode "path=$(echo "$RB2" | jq_ "d['modelPath']")")
[ "$(echo "$JOIN" | jq_ "len(d.get('models',[]))")" = "1" ] && ok "*** GET library /v1/models?path=<Runtime.modelPath> still finds the entry: the join survives ***" || bad "join lost: $(echo "$JOIN" | head -c 200)"

# --- 10. B reaches A's library through the install ---------------------------------------
say "10. the dry run on node-b for the library's path: metadata basis from a library B does not have"
ADM=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$B_URL/v1/runtimes/admission" -H 'content-type: application/json' -d "$SPEC_LIB")
echo "  admission: decision=$(echo "$ADM" | jq_ "d.get('decision')") fit=$(echo "$ADM" | jq_ "d.get('fit')") basis=$(echo "$ADM" | jq_ "d.get('basis')") location=$(echo "$ADM" | jq_ "d.get('location')")"
if [ "$ADV_HOST" = "127.0.0.1" ]; then
  note "loopback registry: the lookup cannot dial node-a's agent, so basis=$(echo "$ADM" | jq_ "d.get('basis')") is the honest fallback"
else
  [ "$(echo "$ADM" | jq_ "d.get('basis')")" = "metadata" ] && ok "*** basis=metadata: B measured by the library's arithmetic, reached through node-a's agent ***" || bad "basis=$(echo "$ADM" | jq_ "d.get('basis')") -- the install-wide lookup did not reach the library; see agent-b.log"
  [ "$(echo "$ADM" | jq_ "d['location'].get('sizeMatchesLibrary')")" = "True" ] && ok "location.sizeMatchesLibrary=true ($(echo "$ADM" | jq_ "d['location'].get('sizeBytes')") bytes both sides)" || bad "size check: $(echo "$ADM" | jq_ "d.get('location')")"
fi
[ "$(echo "$ADM" | jq_ "d['location']['mapping']['from'] if d.get('location') and d['location'].get('mapping') else None")" = "$LIB_ROOT_BS" ] && ok "the rule that applied is the library-root mapping" || bad "mapping: $(echo "$ADM" | jq_ "d.get('location',{}).get('mapping')")"
[ "$(echo "$ADM" | jq_ "d.get('decision')")" = "admit" ] && ok "decision=admit" || bad "decision: $(echo "$ADM" | jq_ "d.get('reason')")"

# --- 11. the Test button -------------------------------------------------------------------
say "11. POST node-b /v1/config/test with the mapping as an override"
T=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$B_URL/v1/config/test" -H 'content-type: application/json' -d "{\"overrides\":{\"pathMappings\":[{\"from\":\"$(printf '%s' "$LIB_ROOT_BS" | sed 's|\\|\\\\|g')\",\"to\":\"$(json_path "$WORK/node-b/mnt/models")\"}]}}")
echo "  summary: $(echo "$T" | jq_ "d.get('summary')")"
if [ "$ADV_HOST" = "127.0.0.1" ]; then
  [ "$(echo "$T" | jq_ "d['ok']")" = "True" ] && ok "ok=true (directories checked; the library could not be consulted over loopback)" || bad "test: $T"
else
  [ "$(echo "$T" | jq_ "d['ok']")" = "True" ] && echo "$T" | jq_ "d.get('summary','')" | grep -q "1 of 1 library model" && ok "*** ok=true and '1 of 1 library model ... reachable' -- checked against the library's real files ***" || bad "test: $T"
  echo "$T" | jq_ "d.get('summary','')" | grep -q "sizes match" && ok "...and the sizes match" || bad "no size confirmation: $(echo "$T" | jq_ "d.get('summary')")"
fi
T2=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$B_URL/v1/config/test" -H 'content-type: application/json' -d "{\"overrides\":{\"pathMappings\":[{\"from\":\"$FOREIGN_ROOT\",\"to\":\"$(json_path "$WORK/node-b/nowhere")\"}]}}")
[ "$(echo "$T2" | jq_ "d['ok']")" = "False" ] && echo "$T2" | jq_ "d.get('error','')" | grep -q "does not exist on this host" && ok "a mapping to a missing directory fails the test and names it" || bad "test: $T2"

# --- 12. the directory listing, both components ---------------------------------------------
say "12. GET /v1/directories on the library and on node-b"
listing_checks() { # who url dir expected-subdirectory
  local who=$1 url=$2 dir=$3 sub=$4
  ROOTS=$(curl -s -H "Authorization: Bearer $CTOK" "$url/v1/directories")
  [ "$(echo "$ROOTS" | jq_ "any(e['name']=='Home' for e in d['entries']) and 'path' not in d")" = "True" ] && ok "$who: the starting points include Home; no path listed" || bad "$who roots: $(echo "$ROOTS" | head -c 200)"
  L=$(curl -s -G -H "Authorization: Bearer $CTOK" "$url/v1/directories" --data-urlencode "path=$dir")
  [ "$(echo "$L" | jq_ "[e['name'] for e in d['entries']]")" = "['$sub']" ] && ok "$who: $dir lists its one subdirectory ($sub); host=$(echo "$L" | jq_ "d['host']") parent=$(echo "$L" | jq_ "d.get('parent')")" || bad "$who listing: $(echo "$L" | head -c 300)"
  [ "$(echo "$L" | jq_ "'hidden' in d['entries'][0]")" = "False" ] && ok "$who: hidden is absent unless asked for" || bad "$who: hidden present"
  [ "$(code_of -G -H "Authorization: Bearer $CTOK" "$url/v1/directories" --data-urlencode "path=$dir/nope")" = "404" ] && ok "$who: a missing directory is 404" || bad "$who: missing dir not 404"
  [ "$(code_of -G -H "Authorization: Bearer $CTOK" "$url/v1/directories" --data-urlencode "path=$LIB_ROOT/$BASENAME")" = "400" ] && ok "$who: a file is 400" || bad "$who: file not 400"
  [ "$(code_of "$url/v1/directories")" = "401" ] && ok "$who: no token is 401" || bad "$who: anonymous listing not 401"
}
listing_checks library "$LIB" "$(win_path "$WORK/nas")" models
listing_checks node-b "$B_URL" "$(win_path "$WORK/node-b")" mnt

# --- 13. teardown ----------------------------------------------------------------------------
say "13. teardown"
kill "$A_PID" 2>/dev/null; kill "$B_PID" 2>/dev/null; A_PID=""; B_PID=""
sleep 6
LEFT=$(powershell.exe -NoProfile -Command "(Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue | Where-Object { \$_.Path -eq '$(win_path "$LLAMA" | sed 's|/|\\|g')' } | Measure-Object).Count" 2>/dev/null | tr -d '\r')
[ "${LEFT:-0}" = "0" ] && ok "no llama-server from this run survived" || bad "$LEFT llama-server process(es) survived"

say "what this run proved / could not"
echo "  proved: a declaration of a path this host does not have is refused before anything spawns, naming the fix;"
echo "          with a mapping the same declaration launches and the engine opens the MAPPED path while the"
echo "          declaration keeps the library's; the runtime still resolves to its library entry; node-b, with no"
echo "          library, was measured by the library's metadata through node-a's agent; the Test button checked a"
echo "          mapping against the library's real files; the directory listing on both components."
echo "  cannot: that the mapping was NECESSARY -- both agents can open the library's own path on one box. That"
echo "          half is visible only on the live two-machine install: mount the NAS share on the worker, map"
echo "          /models to it, launch from the root's console. Also: a read-only or lazily mounted share; a Linux to."
say "result"
if [ "$FAILURES" -eq 0 ]; then echo "M11 acceptance PASSED — the library's path, opened where the launching node has it."; else echo "$FAILURES check(s) FAILED"; fi
exit "$FAILURES"
