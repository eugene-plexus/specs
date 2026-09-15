#!/usr/bin/env bash
#
# Library folders and their reach: a folder says ONCE where nodes find it,
# a node inherits the mount of its own kind, and a node runs only what the
# Library catalogues (2026-09-14).
#
#   host A (this box)   agent A :8179 -> control :8183, gateway :8180, library :8182
#   host B (also here)  agent B :8184 -> the runtime, NO library, NO pathMappings
#
# The library's one folder holds a real GGUF. Its record carries two
# mounts: B's mount directory (Windows-shaped, a hard link to the same
# bytes) and a POSIX decoy that must NOT be chosen on this Windows host.
# Node B carries nothing about paths at all; what it opens, it inherits.
# Both agents enroll with the control root exactly as m11-acceptance.sh
# does; that arc is compressed here, not re-proved.
#
# WHAT ONE BOX PROVES AND DOES NOT -- printed again at the end.
#   proves: B inherits the folder's Windows mount with no configuration of
#           its own, the engine opens the MOUNT while the declaration keeps
#           the library's path, and a completion is served; a declaration
#           under no Library folder is refused 400 with the remedy, before
#           any companion exists, and force does not bypass it; an override
#           on B wins over the inherited mount and clears back; an override
#           whose from is no Library folder is rejected at PATCH; the check
#           endpoint says which rule applied; a bad mount is rejected on the
#           library; the browser sees B under Library, reads B's Folders
#           page, and its Browse lists B'S disk from A's console -- proved
#           from B's own access log, because on one box both agents can
#           open every directory.
#   cannot: that the inherited rule was NECESSARY -- both agents can open
#           the library's own path here (M11's caveat, unchanged); a Linux
#           node taking the POSIX mount (this host is Windows; the decoy is
#           asserted NOT taken, which is the same classifier from the other
#           side); a share mounted read-only or lazily.
#
# Design: docs/design/library-folders-and-reach.md (§10 is the plan this
# follows).
#
# **Safe beside a live install, in both dimensions.** Ports +100, teardown
# by pid, refuses to run if a port it wants is taken; every ambient
# EUGENE_PLEXUS_* variable is dropped first.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
LLAMA="${EP_LLAMA_SERVER:-C:/Users/troyc/OneDrive/Desktop/llamacpp/llama-server.exe}"
MODEL="${EP_MODEL:-D:/py/eugene-plexus/smoke-test/models/Qwen3-1.7B-Q8_0.gguf}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-library-folders}"
A_PORT="${EP_AGENT_A_PORT:-8179}"; GW_PORT="${EP_GATEWAY_PORT:-8180}"
LIB_PORT="${EP_LIBRARY_PORT:-8182}"; CTL_PORT="${EP_CONTROL_PORT:-8183}"
B_PORT="${EP_AGENT_B_PORT:-8184}"
SKIP_BUILD="${EP_SKIP_BUILD:-0}"
PASS="folders-$$-$(date +%s)"
ALIAS="qwen3-1.7b"
RT="qwen-inherited"   # declared from the library's path; B opens the inherited mount
RT2="qwen-override"   # declared from the library's path; B opens its override
STRAY="stray"         # declared from a path under no Library folder: refused
FOREIGN_ROOT="/srv/models"
MARKER="only-on-b"

ADV_HOST="${EP_ADVERTISE_HOST:-$(PYTHONUTF8=1 python -c "import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
try:
    s.connect(('192.0.2.1',9)); print(s.getsockname()[0])
except OSError:
    print('127.0.0.1')" 2>/dev/null || echo 127.0.0.1)}"
A_URL="http://$ADV_HOST:$A_PORT"; B_URL="http://$ADV_HOST:$B_PORT"
CTL="http://$ADV_HOST:$CTL_PORT"; GW="http://127.0.0.1:$GW_PORT"; LIB="http://127.0.0.1:$LIB_PORT"
OWNED_PORTS="$A_PORT $GW_PORT $LIB_PORT $CTL_PORT $B_PORT"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
win_path() { cygpath -m "$1"; }
bs_path() { win_path "$1" | sed 's|/|\\|g'; }           # C:\a\b, as the agent spells a local path
json_bs() { printf '%s' "$1" | sed 's|\\|\\\\|g'; }     # JSON-escape backslashes
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }

A_PID=""; B_PID=""
teardown() {
  [ -n "$B_PID" ] && kill "$B_PID" 2>/dev/null
  [ -n "$A_PID" ] && kill "$A_PID" 2>/dev/null
  sleep 3
  for p in $OWNED_PORTS; do for pid in $(listening_pids "$p"); do taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null; done; done
}

# --- 1. preflight -----------------------------------------------------------------
say "1. preflight"
[ -f "$PY" ] || { bad "agent python not found at $PY"; exit 1; }
[ -f "$LLAMA" ] || { bad "llama-server not found at $LLAMA"; exit 1; }
[ -f "$MODEL" ] || { bad "model not found at $MODEL"; exit 1; }
"$PY" -c "import eugene_plexus_agent, eugene_plexus_control, eugene_plexus_gateway, eugene_plexus_inference_driver, eugene_plexus_library" 2>/dev/null || { bad "all five components must import from $PY"; exit 1; }
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p is in use; stop it or set EP_*_PORT"; exit 1; }; done
ok "binary, model, five components; A=$A_URL B=$B_URL control=$CTL; every port free"
[ "$ADV_HOST" = "127.0.0.1" ] && note "no non-loopback address detected: B cannot reach the install's library, so the inheritance checks will degrade (see the header)"

for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }
rm -rf "$WORK"; mkdir -p "$WORK/a" "$WORK/b" "$WORK/nas/models" "$WORK/node-b/mnt/models/$MARKER" "$WORK/node-b/override/models"; cd "$WORK" || exit 1
trap teardown EXIT

# The library's copy of the model, B's "mount" of the same bytes, and a
# second directory for B's override.
BASENAME="$(basename "$MODEL")"
cp "$MODEL" "nas/models/$BASENAME"
ln "nas/models/$BASENAME" "node-b/mnt/models/$BASENAME" 2>/dev/null || cp "nas/models/$BASENAME" "node-b/mnt/models/$BASENAME"
ln "nas/models/$BASENAME" "node-b/override/models/$BASENAME" 2>/dev/null || cp "nas/models/$BASENAME" "node-b/override/models/$BASENAME"
LIB_ROOT_BS="$(bs_path "$WORK/nas/models")"          # the folder, as the library (Windows) spells it
MOUNT_BS="$(bs_path "$WORK/node-b/mnt/models")"       # B's mount, as B spells a local path
OVERRIDE_BS="$(bs_path "$WORK/node-b/override/models")"
ok "folder $LIB_ROOT_BS; B's mount $MOUNT_BS (with $MARKER/ under it); B's override dir $OVERRIDE_BS"

# --- 2. this working tree's UI ------------------------------------------------------
say "2. stage this working tree's UI into the wheel the agent serves"
if [ "$SKIP_BUILD" = "1" ]; then
  ok "skipped by EP_SKIP_BUILD=1 (asserting about the already-staged build)"
else
  (cd "$UI_DIR" && npm run build:python > "$WORK/build.log" 2>&1)
  [ $? = 0 ] && ok "npm run build:python staged the export" || { bad "build failed"; tail -30 "$WORK/build.log"; exit 1; }
fi
STATIC="$UI_DIR/python/eugene_plexus_ui/static"
[ -f "$STATIC/library/folders/index.html" ] || [ -f "$STATIC/library/folders.html" ] \
  && ok "the staged export carries /library/folders" \
  || bad "no /library/folders in the staged export -- the agent would serve a pre-folders build"

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
printf 'logLevel: INFO\nroutingRefreshSeconds: 3\nidleCheckSeconds: 5\nswapWaitSeconds: 120\n' > a/gateway.yaml
echo "logLevel: INFO" > a/control.yaml
# THE FOLDER RECORD, stated once: the folder as the library spells it, and
# where Windows nodes and POSIX nodes find it. The POSIX entry is a decoy
# on this Windows host: a node takes the mount of ITS shape.
cat > a/library.yaml <<YAML
logLevel: INFO
modelRoots:
  - path: '$LIB_ROOT_BS'
    mounts:
      - '/mnt/decoy-models'
      - '$MOUNT_BS'
YAML
# B: enrolled, no library, and NOTHING about paths.
printf 'firstRunComplete: true\ncomponents: []\nruntimes: []\n' > b/agent.yaml

BIND=()
[ "$ADV_HOST" != "127.0.0.1" ] && BIND=(EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0)

# --- 3. the install ------------------------------------------------------------------
say "3. agent A (control, gateway, library) and agent B, both enrolled"
(cd a && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$A_PORT" "${BIND[@]}" "$PY" -m eugene_plexus_agent --unattended > ../agent-a.log 2>&1) &
A_PID=$!
wait_healthy "$A_URL" && ok "agent A answering at $A_URL" || { bad "agent A never came up"; tail -30 agent-a.log; exit 1; }
wait_healthy "$CTL" && wait_healthy "$LIB" && wait_healthy "$GW" 90 && ok "control, library and gateway answering" || { bad "A's children never came up"; tail -30 agent-a.log; exit 1; }
curl -s -o /dev/null -X POST "$CTL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}"
CTOK=$(curl -s -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
ATOK=$(curl -s -X POST "$A_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$CTOK" ] && [ -n "$ATOK" ] && ok "control and agent A initialized" || { bad "no sessions"; exit 1; }

(cd b && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$B_PORT" "${BIND[@]}" "$PY" -m eugene_plexus_agent --unattended > ../agent-b.log 2>&1) &
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
[ "$(echo "$NODES" | jq_ "all(n['reachable'] for n in d['nodes']) and len(d['nodes'])==2")" = "True" ] && ok "control root reaches both nodes" || bad "nodes: $NODES"
# The operator's session, as a browser would hold it, minted by A.
sleep 2
TOK=$(curl -s -X POST "$A_URL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "no operator session after enrollment"; exit 1; }

# --- 4. the folder record, the labels ---------------------------------------------------
say "4. the Library's folder carries its mounts; the labels say Library"
for _ in $(seq 1 60); do
  LIBM=$(curl -s -H "Authorization: Bearer $CTOK" "$LIB/v1/models")
  [ "$(echo "$LIBM" | jq_ "len(d.get('models',[]))")" = "1" ] && break; sleep 1
done
LIB_PATH=$(echo "$LIBM" | jq_ "d['models'][0]['path']")
[ -n "$LIB_PATH" ] && ok "library lists $LIB_PATH" || { bad "library never listed the model: $LIBM"; exit 1; }
LIB_PATH_JSON=$(json_bs "$LIB_PATH")
F=$(curl -s -H "Authorization: Bearer $CTOK" "$LIB/v1/folders")
[ "$(echo "$F" | jq_ "len(d['folders'])==1 and d['folders'][0]['path']==r'$LIB_ROOT_BS' and sorted(d['folders'][0]['mounts'])==sorted(['/mnt/decoy-models', r'$MOUNT_BS'])")" = "True" ] && ok "GET library /v1/folders: one folder, two mounts, in the object form the file did not use" || bad "folders: $F"
[ "$(curl -s -H "Authorization: Bearer $CTOK" "$LIB/v1/config/schema" | jq_ "next((f['valueType'] for f in d['fields'] if f['key']=='modelRoots'), None)")" = "library_folders" ] && ok "the library's schema: modelRoots is library_folders" || bad "library schema"
[ "$(curl -s -H "Authorization: Bearer $CTOK" "$LIB/v1/config" | jq_ "d['modelRoots'][0]['path']")" = "$LIB_ROOT_BS" ] && ok "GET library /v1/config answers the object form" || bad "config form"
SCHEMA=$(curl -s -H "Authorization: Bearer $TOK" "$B_URL/v1/config/schema")
[ "$(echo "$SCHEMA" | jq_ "next((f['label'] for f in d['fields'] if f['key']=='pathMappings'), None)")" = "Library folder overrides" ] && ok "B's schema labels pathMappings 'Library folder overrides'" || bad "label: $(echo "$SCHEMA" | jq_ "[f['label'] for f in d['fields'] if f['key']=='pathMappings']")"
[ "$(echo "$SCHEMA" | jq_ "d['categories'].get(next((f['category'] for f in d['fields'] if f['key']=='pathMappings'), ''))")" = "Library" ] && ok "...under the category 'Library'" || bad "category: $(echo "$SCHEMA" | jq_ "d['categories']")"
[ "$(curl -s -H "Authorization: Bearer $TOK" "$B_URL/v1/config" | jq_ "d['pathMappings']")" = "[]" ] && ok "B carries NO overrides" || bad "B has pathMappings"

# --- 5. B inherits ------------------------------------------------------------------------
say "5. POST node-b /v1/library/folders/check: what B would open, and which rule said so"
CHK=$(curl -s -X POST -H "Authorization: Bearer $TOK" "$B_URL/v1/library/folders/check" -H 'content-type: application/json' -d '{}')
echo "  check: $(echo "$CHK" | head -c 400)"
if [ "$ADV_HOST" = "127.0.0.1" ]; then
  note "loopback registry: B cannot dial node-a's agent for the library, so libraryConsulted=$(echo "$CHK" | jq_ "d['libraryConsulted']") is the honest answer; the inheritance checks below will degrade"
else
  [ "$(echo "$CHK" | jq_ "d['libraryConsulted']")" = "True" ] && ok "*** libraryConsulted=true: B read the Library's folders through node-a's agent ***" || bad "B did not consult the library: $CHK"
fi
ROW=$(echo "$CHK" | jq_ "next((f for f in d['folders'] if f['path']==r'$LIB_ROOT_BS'), None)")
[ "$(echo "$CHK" | jq_ "next((f['source'] for f in d['folders'] if f['path']==r'$LIB_ROOT_BS'), None)")" = "inherited" ] && ok "*** source=inherited: B has no mapping of its own and opens the folder through the mount the FOLDER stated ***" || bad "row: $ROW"
[ "$(echo "$CHK" | jq_ "next((f['localPath'] for f in d['folders'] if f['path']==r'$LIB_ROOT_BS'), None)")" = "$MOUNT_BS" ] && ok "localPath is the Windows-shaped mount, NOT the POSIX decoy: $MOUNT_BS" || bad "localPath: $ROW"
[ "$(echo "$CHK" | jq_ "next((f['exists'] and f.get('isDirectory') for f in d['folders'] if f['path']==r'$LIB_ROOT_BS'), None)")" = "True" ] && ok "exists and is a directory on B" || bad "exists: $ROW"
[ "$(echo "$CHK" | jq_ "next(((f.get('modelsUnder'), f.get('modelsReachable')) for f in d['folders'] if f['path']==r'$LIB_ROOT_BS'), None)")" = "(1, 1)" ] && ok "1 of 1 library models under the folder reachable on B" || { [ "$ADV_HOST" = "127.0.0.1" ] && note "model counts need the library (loopback)" || bad "models: $ROW"; }
[ -f "b/library_folders.json" ] && ok "B wrote its copy of the folder list beside agent.yaml (library_folders.json)" || bad "no library_folders.json in B's directory"

# --- 6. the inherited launch ---------------------------------------------------------------
say "6. declare $RT on node-b from the LIBRARY's path, through control; B has nothing configured"
SPEC_LIB="{\"name\":\"$RT\",\"engine\":\"llama_cpp\",\"modelPath\":\"$LIB_PATH_JSON\",\"modelAlias\":\"$ALIAS\",\"binary\":\"$(win_path "$LLAMA" | sed 's|/|\\\\|g')\",\"flags\":{\"contextSize\":4096,\"gpuLayers\":99,\"parallelSlots\":1}}"
R=$(curl -s -w '\n%{http_code}' -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/runtimes" -H 'content-type: application/json' -d "{\"node\":\"node-b\",\"spec\":$SPEC_LIB}")
CODE=$(echo "$R" | tail -1); BODY=$(echo "$R" | sed '$d')
[ "$CODE" = "201" ] && ok "*** 201: declared with NO mapping on B ***" || { bad "control answered $CODE: $BODY"; tail -20 agent-b.log; }
RB=$(curl -s -H "Authorization: Bearer $TOK" "$B_URL/v1/runtimes/$RT")
[ "$(echo "$RB" | jq_ "d['modelPath']")" = "$LIB_PATH" ] && ok "Runtime.modelPath is the library's spelling, untouched" || bad "modelPath: $(echo "$RB" | jq_ "d.get('modelPath')")"
[ "$(echo "$RB" | jq_ "d.get('localPath')")" = "$MOUNT_BS\\$BASENAME" ] && ok "*** Runtime.localPath is the INHERITED mount: $MOUNT_BS\\$BASENAME ***" || bad "localPath: $(echo "$RB" | jq_ "d.get('localPath')")"
for _ in $(seq 1 120); do
  RB=$(curl -s -H "Authorization: Bearer $TOK" "$B_URL/v1/runtimes/$RT"); ST=$(echo "$RB" | jq_ "d.get('status')" 2>/dev/null)
  [ "$ST" = "ready" ] || [ "$ST" = "crashed" ] && break; sleep 1
done
[ "$ST" = "ready" ] && ok "engine ready on node-b" || { bad "runtime status=$ST $(echo "$RB" | jq_ "d.get('lastError')")"; tail -20 agent-b.log; }
[ "$(echo "$RB" | jq_ "'--model' in (d.get('argv') or []) and (d['argv'][d['argv'].index('--model')+1] == r'$MOUNT_BS\\$BASENAME')")" = "True" ] && ok "*** the engine's argv names the mount, and nobody typed it on B ***" || bad "argv: $(echo "$RB" | jq_ "d.get('argv')")"
[ "$(curl -s -H "Authorization: Bearer $TOK" "$B_URL/v1/config" | jq_ "d['pathMappings']")" = "[]" ] && ok "B still carries no overrides" || bad "B gained pathMappings"

say "7. a completion through the gateway, served by $RT"
for _ in $(seq 1 60); do
  RN=$(curl -s -H "Authorization: Bearer $CTOK" "$GW/v1/models" | jq_ "next((m['x_eugene_plexus'].get('ready_backends') for m in d.get('data',[]) if m['id']=='$ALIAS'), 0)" 2>/dev/null)
  [ "$RN" = "1" ] && break; sleep 1
done
[ "$RN" = "1" ] && ok "gateway lists $ALIAS with ready_backends=1" || bad "gateway never listed $ALIAS ready (ready_backends=$RN)"
C=$(curl -s -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $CTOK" -H 'content-type: application/json' -d "{\"model\":\"$ALIAS\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word OK. /no_think\"}],\"max_tokens\":16,\"temperature\":0.1}")
TXT=$(echo "$C" | jq_ "(d.get('choices') or [{}])[0].get('message',{}).get('content','').strip()" 2>/dev/null)
[ -n "$TXT" ] && [ "$(echo "$C" | jq_ "d['x_eugene_plexus'].get('runtime')")" = "$RT" ] && ok "*** COMPLETION from a model opened through the folder's own mount: '$TXT' (runtime=$RT) ***" || bad "completion: $(echo "$C" | head -c 300)"

# --- 8. not a Library model ----------------------------------------------------------------
say "8. declare $STRAY on node-b from $FOREIGN_ROOT/$BASENAME: under no Library folder"
SPEC_STRAY="{\"name\":\"$STRAY\",\"engine\":\"llama_cpp\",\"modelPath\":\"$FOREIGN_ROOT/$BASENAME\",\"modelAlias\":\"stray\",\"binary\":\"$(win_path "$LLAMA" | sed 's|/|\\\\|g')\",\"flags\":{\"contextSize\":4096}}"
R=$(curl -s -w '\n%{http_code}' -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/runtimes" -H 'content-type: application/json' -d "{\"node\":\"node-b\",\"spec\":$SPEC_STRAY}")
CODE=$(echo "$R" | tail -1); BODY=$(echo "$R" | sed '$d'); DETAIL=$(echo "$BODY" | jq_ "d['detail']['detail']" 2>/dev/null)
if [ "$ADV_HOST" = "127.0.0.1" ]; then
  note "loopback: B has never read the folder list, so the rule is skipped with a warning (control answered $CODE)"
  grep -q "was not checked against the Library's folders" agent-b.log && ok "...and B's log says so" || bad "B did not warn"
else
  [ "$CODE" = "502" ] && ok "control relays the node's refusal as 502" || bad "control answered $CODE: $BODY"
  echo "$DETAIL" | grep -q "answered 400" && ok "*** ...and the node answered 400, not 201 and not 422: not a Library model ***" || bad "detail: $DETAIL"
  echo "$DETAIL" | grep -q "is not under any Library folder" && ok "the refusal says why" || bad "detail: $DETAIL"
  echo "$DETAIL" | grep -q "Library -> Folders" && ok "*** ...and the fix: add the directory to the Library (Library -> Folders) ***" || bad "detail does not name the fix: $DETAIL"
  [ "$(code_of -X POST -H "Authorization: Bearer $TOK" "$B_URL/v1/runtimes?force=true" -H 'content-type: application/json' -d "$SPEC_STRAY")" = "400" ] && ok "force does not bypass it" || bad "force bypassed the folder rule"
  [ "$(curl -s -H "Authorization: Bearer $TOK" "$B_URL/v1/runtimes" | jq_ "[r['name'] for r in d['runtimes']]")" = "['$RT']" ] && ok "B has only $RT; nothing was declared for $STRAY" || bad "B's runtimes changed"
  [ "$(curl -s -H "Authorization: Bearer $TOK" "$B_URL/v1/components" | jq_ "any(c['name']=='$STRAY-driver' for c in d['components'])")" = "False" ] && ok "...and no companion driver was left behind" || bad "$STRAY-driver exists"
  # Built explicitly rather than by sed over the JSON: the first version
  # substituted the library path through sed, whose pattern read the
  # JSON-escaped backslashes as escapes and never matched, so the PATCH
  # carried the library's path and the 200 it got was the right answer to
  # the wrong question.
  SPEC_RT_FOREIGN="{\"name\":\"$RT\",\"engine\":\"llama_cpp\",\"modelPath\":\"$FOREIGN_ROOT/$BASENAME\",\"modelAlias\":\"$ALIAS\",\"binary\":\"$(win_path "$LLAMA" | sed 's|/|\\\\|g')\",\"flags\":{\"contextSize\":4096,\"gpuLayers\":99,\"parallelSlots\":1}}"
  R=$(curl -s -w '\n%{http_code}' -X PATCH -H "Authorization: Bearer $TOK" "$B_URL/v1/runtimes/$RT" -H 'content-type: application/json' -d "$SPEC_RT_FOREIGN")
  [ "$(echo "$R" | tail -1)" = "400" ] && ok "an update to a path outside the Library is refused too" || bad "update answered $(echo "$R" | tail -1)"
  [ "$(curl -s -H "Authorization: Bearer $TOK" "$B_URL/v1/runtimes/$RT" | jq_ "d['modelPath']")" = "$LIB_PATH" ] && ok "...and $RT still names the library's path" || bad "$RT's modelPath changed"
fi

# --- 9. the override ------------------------------------------------------------------------
say "9. B's overrides: a from that is no Library folder is rejected; the folder's is applied and wins"
BAD=$(curl -s -X PATCH -H "Authorization: Bearer $TOK" "$B_URL/v1/config" -H 'content-type: application/json' -d "{\"pathMappings\":[{\"from\":\"$FOREIGN_ROOT\",\"to\":\"$(json_bs "$OVERRIDE_BS")\"}]}")
if [ "$ADV_HOST" = "127.0.0.1" ]; then
  note "loopback: the folder list is unknown to B, so the override is accepted with a warning: $(echo "$BAD" | jq_ "d['applied']")"
  curl -s -o /dev/null -X PATCH -H "Authorization: Bearer $TOK" "$B_URL/v1/config" -H 'content-type: application/json' -d '{"pathMappings":[]}'
else
  [ "$(echo "$BAD" | jq_ "d['applied']")" = "[]" ] && echo "$BAD" | jq_ "d['rejected'][0]['message'] if d['rejected'] else ''" | grep -q "is not a Library folder" && ok "*** rejected: '$FOREIGN_ROOT' is not a Library folder -- an override says where THIS machine mounts a Library folder ***" || bad "bad override: $BAD"
fi
GOOD=$(curl -s -X PATCH -H "Authorization: Bearer $TOK" "$B_URL/v1/config" -H 'content-type: application/json' -d "{\"pathMappings\":[{\"from\":\"$(json_bs "$LIB_ROOT_BS")\",\"to\":\"$(json_bs "$OVERRIDE_BS")\"}]}")
[ "$(echo "$GOOD" | jq_ "d['applied']")" = "['pathMappings']" ] && ok "override applied: $LIB_ROOT_BS -> $OVERRIDE_BS" || bad "override: $GOOD"
CHK=$(curl -s -X POST -H "Authorization: Bearer $TOK" "$B_URL/v1/library/folders/check" -H 'content-type: application/json' -d '{}')
[ "$(echo "$CHK" | jq_ "next((f['source'] for f in d['folders'] if f['path']==r'$LIB_ROOT_BS'), None)")" = "override" ] && ok "*** the check says source=override: B's own rule beats the folder's mount ***" || bad "check after override: $(echo "$CHK" | head -c 300)"
[ "$(echo "$CHK" | jq_ "next((f['localPath'] for f in d['folders'] if f['path']==r'$LIB_ROOT_BS'), None)")" = "$OVERRIDE_BS" ] && ok "localPath is the override directory" || bad "localPath: $(echo "$CHK" | head -c 300)"
SPEC_LIB2="{\"name\":\"$RT2\",\"engine\":\"llama_cpp\",\"modelPath\":\"$LIB_PATH_JSON\",\"modelAlias\":\"qwen3-override\",\"binary\":\"$(win_path "$LLAMA" | sed 's|/|\\\\|g')\",\"autoStart\":false,\"flags\":{\"contextSize\":4096,\"gpuLayers\":99}}"
[ "$(code_of -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/runtimes" -H 'content-type: application/json' -d "{\"node\":\"node-b\",\"spec\":$SPEC_LIB2}")" = "201" ] && ok "declared $RT2 from the library's path (autoStart false: the rule, not the GPU, is under test)" || bad "declare $RT2 failed"
[ "$(curl -s -H "Authorization: Bearer $TOK" "$B_URL/v1/runtimes/$RT2" | jq_ "d.get('localPath')")" = "$OVERRIDE_BS\\$BASENAME" ] && ok "*** Runtime.localPath for $RT2 is the OVERRIDE; $RT, already running, still holds the mount ***" || bad "localPath: $(curl -s -H "Authorization: Bearer $TOK" "$B_URL/v1/runtimes/$RT2" | jq_ "d.get('localPath')")"
# The unsaved-override form of the check: the Test button.
UNSAVED=$(curl -s -X POST -H "Authorization: Bearer $TOK" "$B_URL/v1/library/folders/check" -H 'content-type: application/json' -d "{\"pathMappings\":[{\"from\":\"$(json_bs "$LIB_ROOT_BS")\",\"to\":\"$(json_bs "$WORK/node-b/nowhere" | sed 's|/|\\\\|g')\"}]}")
[ "$(echo "$UNSAVED" | jq_ "next((f['exists'] for f in d['folders'] if f['path']==r'$LIB_ROOT_BS'), None)")" = "False" ] && echo "$UNSAVED" | jq_ "next((f.get('problem') or '' for f in d['folders'] if f['path']==r'$LIB_ROOT_BS'), '')" | grep -q "does not exist on this host" && ok "an unsaved override to a missing directory is reported, not saved" || bad "unsaved check: $(echo "$UNSAVED" | head -c 300)"
[ "$(curl -s -H "Authorization: Bearer $TOK" "$B_URL/v1/config" | jq_ "d['pathMappings'][0]['to']")" = "$OVERRIDE_BS" ] && ok "...and the saved override is untouched" || bad "the check saved something"
curl -s -o /dev/null -X PATCH -H "Authorization: Bearer $TOK" "$B_URL/v1/config" -H 'content-type: application/json' -d '{"pathMappings":[]}'
CHK=$(curl -s -X POST -H "Authorization: Bearer $TOK" "$B_URL/v1/library/folders/check" -H 'content-type: application/json' -d '{}')
[ "$(echo "$CHK" | jq_ "next((f['source'] for f in d['folders'] if f['path']==r'$LIB_ROOT_BS'), None)")" = "inherited" ] && ok "clearing the override returns B to the folder's mount" || bad "after clear: $(echo "$CHK" | head -c 300)"

# --- 10. the library refuses a bad folder record ---------------------------------------------
say "10. PATCH library modelRoots: a relative mount, two mounts of one shape"
R=$(curl -s -X PATCH -H "Authorization: Bearer $CTOK" "$LIB/v1/config" -H 'content-type: application/json' -d "{\"modelRoots\":[{\"path\":\"$(json_bs "$LIB_ROOT_BS")\",\"mounts\":[\"models\"]}]}")
[ "$(echo "$R" | jq_ "d['rejected'][0]['key'] if d['rejected'] else ''")" = "modelRoots" ] && echo "$R" | jq_ "d['rejected'][0]['message']" | grep -q "absolute" && ok "a relative mount is rejected: $(echo "$R" | jq_ "d['rejected'][0]['message'][:80]")" || bad "relative mount accepted: $R"
R=$(curl -s -X PATCH -H "Authorization: Bearer $CTOK" "$LIB/v1/config" -H 'content-type: application/json' -d "{\"modelRoots\":[{\"path\":\"$(json_bs "$LIB_ROOT_BS")\",\"mounts\":[\"/mnt/a\",\"/mnt/b\"]}]}")
echo "$R" | jq_ "d['rejected'][0]['message'] if d['rejected'] else ''" | grep -q "POSIX-shaped" && ok "two POSIX mounts are rejected: a node takes the first of its shape" || bad "two mounts accepted: $R"
[ "$(curl -s -H "Authorization: Bearer $CTOK" "$LIB/v1/folders" | jq_ "len(d['folders'][0]['mounts'])")" = "2" ] && ok "the folder record is unchanged by the refused edits" || bad "folder record changed"

# --- 11. the browser ----------------------------------------------------------------------------
say "11. the browser: node-b under Library, its Folders page, and Browse on B's disk from A's console"
B_LISTINGS_BEFORE=$(grep -c "GET /v1/directories" agent-b.log || true)
(cd "$UI_DIR" && EP_UI_URL="$A_URL" EP_PASSPHRASE="$PASS" EP_NODE_B="node-b" EP_FOLDER="$LIB_ROOT_BS" EP_MOUNT="$MOUNT_BS" EP_MARKER="$MARKER" npx playwright test e2e/library-folders.spec.ts > "$WORK/playwright.log" 2>&1)
PW=$?
sed -n '/Running/,$p' "$WORK/playwright.log" | grep -E '^\s+[✓✘×]|passed|failed' | head -20
if [ "$PW" = "0" ]; then
  for t in \
    "a node sits under Library, and Library's pages include Folders" \
    "the grid shows every node's column, and the worker's cell is inherited" \
    "the worker's Folders page reports the inherited mount with no override" \
    "Browse in the Override box lists the remote node's disk, and the override round-trips" \
    "the agent's own Config names the field as overrides under Library"; do
    grep -qF "$t" "$WORK/playwright.log" && ok "browser: $t" || bad "browser: '$t' did not run"
  done
else
  bad "the folders spec failed"
  tail -60 "$WORK/playwright.log"
fi
B_LISTINGS_AFTER=$(grep -c "GET /v1/directories" agent-b.log || true)
[ "${B_LISTINGS_AFTER:-0}" -gt "${B_LISTINGS_BEFORE:-0}" ] \
  && ok "*** B's OWN access log gained $((B_LISTINGS_AFTER - B_LISTINGS_BEFORE)) directory listing(s) during the browser run: the picker on A's console browsed B's disk ***" \
  || bad "B's log shows no /v1/directories request: the picker did not reach B (before=$B_LISTINGS_BEFORE after=$B_LISTINGS_AFTER)"
[ "$(curl -s -H "Authorization: Bearer $TOK" "$B_URL/v1/config" | jq_ "d['pathMappings']")" = "[]" ] && ok "the browser's override round-trip left B with no overrides" || bad "B still has overrides after the browser run"

# --- 12. result ------------------------------------------------------------------------------
say "result"
cat <<EOF
  proved on one box: B inherited the folder's Windows mount with nothing configured, opened the
    mount while the declaration kept the library's path, served a completion; a model under no
    Library folder was refused 400 with the remedy and force did not bypass it; an override on B
    won and cleared back; the library refused a bad folder record; the browser saw node-b under
    Library, read its Folders page, and its Browse listed B's disk from A's console (B's log).
  not proved: that the inherited rule was NECESSARY (both agents can open every directory here);
    a POSIX node taking the POSIX mount (this host is Windows; the decoy was asserted NOT taken).
EOF
if [ "$FAILURES" = "0" ]; then printf '  ALL CHECKS PASSED\n'; else printf '  %d CHECK(S) FAILED\n' "$FAILURES"; fi
exit "$FAILURES"
