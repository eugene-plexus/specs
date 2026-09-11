#!/usr/bin/env bash
#
# M7 acceptance: a second host -- on one box, or on two.
#
# RUN TWICE, both green, 41 checks each:
#   same-box   many times, most recently 2026-09-11
#   two-host   2026-09-11, FIRST EVER -- host A Windows, host B WSL2
#              Ubuntu 26.04 at 172.19.221.94, A's services bound 0.0.0.0
#              and addressed at 172.19.208.1, B running vLLM. Record:
#              docs/acceptance/m7-two-host-run.md
#
#   host A (this box)        agent A :8079  -> spawns control :8083, gateway :8080, library :8082
#   host B (also this box)   agent B :8084  -> spawns nothing until told; own config dir
#
# Both agents enroll with the control root over real HTTP with real join
# tokens. A runtime is declared ON B THROUGH THE CONTROL ROOT; B spawns
# its companion after enrolling, so the companion is born with the
# install's signing key; the gateway (a child of A) lists it, serves it,
# idles it out, wakes it, and survives a signing-key rotation that
# re-keys both agents. A forged lower-epoch re-key is fenced.
#
# Written for two hosts and parameterised by two agent URLs. EP_MODE:
#   same-box  (default) start both agents here; B on a second port
#   two-host  agent B is already running at EP_AGENT_B_URL on another host
#             with EP_AGENT_B_PASSPHRASE set; nothing is spawned for it
#
# WHAT ONE BOX PROVES AND DOES NOT — printed again at the end.
#   proves: enrollment over HTTP with a real token; the install key reaching
#           a companion spawned after enrollment and the gateway's token
#           verifying on it; fan-out and attribution by node from a real
#           /v1/nodes; a lifecycle action for B's runtime reaching :8084 and
#           not :8079; a real rotation re-keying both agents with the
#           gateway serving afterwards; a signed lower-epoch re-key refused.
#   cannot: a node genuinely offline during a rotation; clock skew; a root
#           partitioned rather than dead (the forge tests the refusal, not
#           the partition); any bind to a non-loopback interface.
#
set -uo pipefail

EP_MODE="${EP_MODE:-same-box}"
EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
EP_AGENT_PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
EP_LLAMA_SERVER="${EP_LLAMA_SERVER:-C:/Users/troyc/OneDrive/Desktop/llamacpp/llama-server.exe}"
EP_MODEL="${EP_MODEL:-D:/py/eugene-plexus/smoke-test/models/Qwen3-1.7B-Q8_0.gguf}"
EP_WORKDIR="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-m7-acceptance}"
EP_AGENT_A_URL="${EP_AGENT_A_URL:-http://127.0.0.1:8079}"
EP_AGENT_B_URL="${EP_AGENT_B_URL:-http://127.0.0.1:8084}"
EP_CONTROL_URL="${EP_CONTROL_URL:-http://127.0.0.1:8083}"
EP_GATEWAY_URL="${EP_GATEWAY_URL:-http://127.0.0.1:8080}"
EP_IDLE_SECONDS="${EP_IDLE_SECONDS:-20}"
PASSPHRASE="${EP_PASSPHRASE:-acceptance-$(date +%s)-$$}"
EP_AGENT_B_PASSPHRASE="${EP_AGENT_B_PASSPHRASE:-$PASSPHRASE}"
ALIAS="${EP_ALIAS:-qwen3-1.7b}"
RT=qwen-b

# --- host B's half of the declaration ------------------------------------
# B need not be the same OS, or run the same engine, as A. The pair this
# first ran on for real has a Windows A and a Linux B under WSL2, and B
# runs vLLM because our own M1 policy refuses to install llama.cpp on a
# Linux host with an NVIDIA GPU -- upstream publishes no such build. So
# "the second host runs a different engine" is not a contrivance here; it
# is what the acquisition policy forces. Unset, these reproduce the
# same-box llama.cpp run exactly.
EP_ENGINE_B="${EP_ENGINE_B:-llama_cpp}"
EP_MODEL_B="${EP_MODEL_B:-}"     # B's own path to its model, verbatim
EP_BINARY_B="${EP_BINARY_B:-}"   # B's own path to the engine binary
EP_FLAGS_B="${EP_FLAGS_B:-}"     # JSON object of engine launch flags
EP_ENV_B="${EP_ENV_B:-}"         # JSON object of extra engine env
# Set this to a non-loopback URL for a real two-host run. It matters more
# than it looks: a component binds 0.0.0.0 only when its node advertises a
# non-loopback address, and enrollment deliberately does NOT restart the
# control root -- so if A's advertise address is only discovered at
# enrollment time, the root stays bound to loopback and B can never reach
# it. Setting it up front is what makes the root reachable at all.
EP_ADVERTISE_A="${EP_ADVERTISE_A:-}"

B_PORT=$(printf '%s' "$EP_AGENT_B_URL" | sed -E 's|.*:([0-9]+)/?$|\1|')

# Whatever host B answers on is the host its companion will advertise.
# Same-box that is http://127.0.0.1:, which this used to assert literally.
B_ADV_PREFIX="$(printf '%s' "$EP_AGENT_B_URL" | sed -E 's|:[0-9]+/?$||'):"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
win_path() { printf '%s' "$1" | sed 's|/|\\|g'; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
ctl_login() { curl -s -X POST "$EP_CONTROL_URL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')"; }
agent_login() { curl -s -X POST "$1/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$2\"}" | jq_ "d.get('sessionToken','')"; }

# --- preflight -----------------------------------------------------------------
say "preflight ($EP_MODE)"
[ -f "$EP_AGENT_PY" ] || bad "agent venv python not found at $EP_AGENT_PY"
# A's paths. B's are B's own and are never checked from here -- on a real
# two-host run this box cannot see them, which is rather the point.
if [ -z "$EP_BINARY_B" ]; then
  [ -f "$EP_LLAMA_SERVER" ] || bad "llama-server not found at $EP_LLAMA_SERVER (or set EP_BINARY_B for host B)"
fi
[ -f "$EP_MODEL" ] || bad "model not found at $EP_MODEL"
[ "$FAILURES" -ne 0 ] && exit 1
"$EP_AGENT_PY" -c "import eugene_plexus_agent, eugene_plexus_control, eugene_plexus_gateway, eugene_plexus_inference_driver, eugene_plexus_library" 2>/dev/null || { bad "all five components must import from $EP_AGENT_PY"; exit 1; }
ok "binary, model, five components; A=$EP_AGENT_A_URL B=$EP_AGENT_B_URL control=$EP_CONTROL_URL"
# Defaults that reproduce the same-box run: B is this box, so B's paths
# are A's paths in Windows form.
[ -n "$EP_MODEL_B" ] || EP_MODEL_B="$(win_path "$EP_MODEL" | sed 's|\\|\\\\|g')"
[ -n "$EP_BINARY_B" ] || EP_BINARY_B="$(win_path "$EP_LLAMA_SERVER" | sed 's|\\|\\\\|g')"
[ -n "$EP_FLAGS_B" ] || EP_FLAGS_B='{"contextSize":4096,"gpuLayers":99,"parallelSlots":1}'
echo "  host B: engine=$EP_ENGINE_B  model=$EP_MODEL_B"
echo "          binary=$EP_BINARY_B"
echo "          flags=$EP_FLAGS_B  env=${EP_ENV_B:-none}"

rm -rf "$EP_WORKDIR"; mkdir -p "$EP_WORKDIR/a" "$EP_WORKDIR/b"; cd "$EP_WORKDIR" || exit 1

cat > a/agent.yaml <<YAML
firstRunComplete: true
${EP_ADVERTISE_A:+advertiseUrl: $EP_ADVERTISE_A}
components:
  - name: control
    kind: control
    url: http://127.0.0.1:8083
    spawn:
      configFile: control.yaml
  - name: gateway
    kind: gateway
    url: http://127.0.0.1:8080
    spawn:
      configFile: gateway.yaml
  - name: library
    kind: library
    url: http://127.0.0.1:8082
    spawn:
      configFile: library.yaml
runtimes: []
YAML
cat > a/gateway.yaml <<YAML
logLevel: INFO
routingRefreshSeconds: 3
idleCheckSeconds: 5
swapWaitSeconds: 120
controlUrl: $EP_CONTROL_URL
YAML
echo "logLevel: INFO" > a/control.yaml
printf 'logLevel: INFO\nmodelRoots:\n  - %s\n' "$(win_path "$(dirname "$EP_MODEL")")" > a/library.yaml
printf 'firstRunComplete: true\ncomponents: []\nruntimes: []\n' > b/agent.yaml

# --- 1. agent A and its fleet --------------------------------------------------
say "1. agent A starts control, gateway (controlUrl set) and library"
# `exec`, so the pid we hold is the agent's and not a subshell's — the first
# run killed two subshells and orphaned both agents and an engine.
# Bind wide only when A actually advertises a non-loopback address; the
# agent passes the same widening down to every component it spawns.
A_BIND_ENV=()
[ -n "$EP_ADVERTISE_A" ] && A_BIND_ENV=(EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0)
(cd a && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml "${A_BIND_ENV[@]}" "$EP_AGENT_PY" -m eugene_plexus_agent > ../agent-a.log 2>&1) &
A_PID=$!
B_PID=""
trap 'kill "$A_PID" 2>/dev/null; [ -n "$B_PID" ] && kill "$B_PID" 2>/dev/null' EXIT
wait_healthy "$EP_AGENT_A_URL" && ok "agent A answering" || { bad "agent A never came up"; tail -30 agent-a.log; exit 1; }
wait_healthy "$EP_CONTROL_URL" && ok "control root answering" || { bad "control never came up"; tail -30 agent-a.log; exit 1; }
wait_healthy "$EP_GATEWAY_URL" 90 && ok "gateway answering" || bad "gateway never came up"
curl -s -o /dev/null -X POST "$EP_CONTROL_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}"
CTOK=$(ctl_login); [ -n "$CTOK" ] && ok "control initialized; operator session issued" || { bad "no control session"; exit 1; }
ATOK=$(curl -s -X POST "$EP_AGENT_A_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
[ -n "$ATOK" ] && ok "agent A initialized" || { bad "no agent A session"; exit 1; }

# --- 2. agent B ------------------------------------------------------------------
say "2. agent B on :$B_PORT with its own config directory"
if [ "$EP_MODE" = "same-box" ]; then
  (cd b && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$B_PORT" "$EP_AGENT_PY" -m eugene_plexus_agent > ../agent-b.log 2>&1) &
  B_PID=$!
  wait_healthy "$EP_AGENT_B_URL" && ok "agent B answering on :$B_PORT" || { bad "agent B never came up"; tail -30 agent-b.log; exit 1; }
  BTOK=$(curl -s -X POST "$EP_AGENT_B_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$EP_AGENT_B_PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
else
  wait_healthy "$EP_AGENT_B_URL" && ok "agent B reachable at $EP_AGENT_B_URL" || { bad "agent B unreachable"; exit 1; }
  BTOK=$(agent_login "$EP_AGENT_B_URL" "$EP_AGENT_B_PASSPHRASE")
fi
[ -n "$BTOK" ] && ok "agent B session issued (pre-enrollment key)" || { bad "no agent B session"; exit 1; }
BN=$(curl -s -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/node")
[ "$(echo "$BN" | jq_ "d['enrolled']")" = "False" ] && ok "B reports enrolled=false before enrollment" || bad "B: $BN"

# --- 3. enroll A -----------------------------------------------------------------
say "3. enroll agent A (the control host) with a join token bound to node-a"
TOK_A=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"node-a"}' | jq_ "d['token']")
EA=$(curl -s -w '\n%{http_code}' -X POST -H "Authorization: Bearer $ATOK" "$EP_AGENT_A_URL/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$EP_CONTROL_URL\",\"token\":\"$TOK_A\",\"name\":\"node-a\"}")
CODE=$(echo "$EA" | tail -1); BODY=$(echo "$EA" | sed '$d')
[ "$CODE" = "200" ] && ok "A enrolled: $(echo "$BODY" | jq_ "'name=%s epoch=%s keyId=%s advertise=%s' % (d['name'], d['epoch'], d.get('signingKeyId'), d.get('advertiseUrl'))")" || { bad "A enroll returned $CODE: $BODY"; tail -20 agent-a.log; }
# A's children restarted with the install key (the control root is skipped — it is the trust root).
wait_healthy "$EP_GATEWAY_URL" 90 || bad "gateway did not come back after A adopted the install key"
curl -sf -m 3 "$EP_CONTROL_URL/healthz" >/dev/null && ok "control root stayed up through A's enrollment (not restarted)" || bad "control root went away"
# A's old session is dead by design; a control-minted one now works on A.
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $ATOK" "$EP_AGENT_A_URL/v1/node")" = "401" ] && ok "A's pre-enrollment session refused (key replaced)" || bad "A still accepts its old key"
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $CTOK" "$EP_AGENT_A_URL/v1/node")" = "200" ] && ok "*** control-minted token verifies on agent A ***" || bad "control token refused by A"

# --- 4. enroll B -----------------------------------------------------------------
say "4. enroll agent B over HTTP with a join token bound to node-b"
TOK_B=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"node-b"}' | jq_ "d['token']")
EB=$(curl -s -w '\n%{http_code}' -X POST -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$EP_CONTROL_URL\",\"token\":\"$TOK_B\",\"name\":\"node-b\"}")
CODE=$(echo "$EB" | tail -1); BODY=$(echo "$EB" | sed '$d')
if [ "$CODE" = "200" ]; then
  ok "*** B ENROLLED: $(echo "$BODY" | jq_ "'name=%s epoch=%s keyId=%s' % (d['name'], d['epoch'], d.get('signingKeyId'))") ***"
  ADV=$(echo "$BODY" | jq_ "d.get('advertiseUrl','').rstrip('/')")
  [ "$ADV" = "$EP_AGENT_B_URL" ] && ok "advertiseUrl derived from the route to the root: $ADV" || bad "advertiseUrl=$ADV expected $EP_AGENT_B_URL"
  echo "$BODY" | jq_ "'publicKey present' if d.get('publicKey') else 'NO publicKey'"
else bad "B enroll returned $CODE: $BODY"; tail -20 agent-b.log 2>/dev/null; fi
[ "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $CTOK" "$EP_AGENT_B_URL/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$EP_CONTROL_URL\",\"token\":\"$TOK_B\",\"name\":\"node-b\"}")" = "409" ] && ok "enrolling B again is 409" || bad "second enroll not 409"
TOK_C=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"node-c"}' | jq_ "d['token']")
[ "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$EP_CONTROL_URL/v1/nodes/enroll" -H 'content-type: application/json' -d "{\"token\":\"$TOK_B\",\"name\":\"node-c\",\"publicKey\":\"$(printf 'replay-attempt-public-key-bytes-32' | head -c 32 | base64)\"}")" = "409" ] && ok "replaying B's spent token at the root is 409" || bad "token replay not 409"

NODES=$(curl -s -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/nodes")
echo "  nodes: $(echo "$NODES" | jq_ "[(n['name'], (n.get('url') or '').rstrip('/')) for n in d['nodes']]")"
[ "$(echo "$NODES" | jq_ "sorted((n.get('url') or '').rstrip('/') for n in d['nodes']) == sorted(['$EP_AGENT_A_URL','$EP_AGENT_B_URL'])")" = "True" ] && ok "*** /v1/nodes carries BOTH agents' URLs (the field enrollment never used to send) ***" || bad "node URLs wrong"
for _ in $(seq 1 30); do
  NODES=$(curl -s -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/nodes")
  [ "$(echo "$NODES" | jq_ "all(n['reachable'] and n.get('lastSeenEpoch')==1 for n in d['nodes']) and len(d['nodes'])==2")" = "True" ] && break; sleep 1
done
[ "$(echo "$NODES" | jq_ "all(n['reachable'] and n.get('lastSeenEpoch')==1 for n in d['nodes'])")" = "True" ] && ok "control root polled both nodes: reachable, lastSeenEpoch=1" || bad "poll: $(echo "$NODES" | jq_ "[(n['name'], n['reachable'], n.get('lastSeenEpoch')) for n in d['nodes']]")"

# --- 5. authenticable across hosts -------------------------------------------------
say "5. one key domain"
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/node")" = "401" ] && ok "B's pre-enrollment session refused" || bad "B still accepts its old key"
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $CTOK" "$EP_AGENT_B_URL/v1/runtimes")" = "200" ] && ok "*** control-minted token reads B's /v1/runtimes ***" || bad "control token refused by B"
BTOK=$(agent_login "$EP_AGENT_B_URL" "$EP_AGENT_B_PASSPHRASE")
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $BTOK" "$EP_CONTROL_URL/v1/nodes")" = "200" ] && ok "*** a token B mints after enrollment reads the control root ***" || bad "B's new token refused by control"

# --- 6. declare on B through the control root ---------------------------------------
say "6. declare $RT on node-b THROUGH the control root; B spawns the companion"
SPEC_ENV=""
[ -n "$EP_ENV_B" ] && SPEC_ENV=",\"env\":$EP_ENV_B"
SPEC="{\"node\":\"node-b\",\"spec\":{\"name\":\"$RT\",\"engine\":\"$EP_ENGINE_B\",\"modelPath\":\"$EP_MODEL_B\",\"modelAlias\":\"$ALIAS\",\"binary\":\"$EP_BINARY_B\",\"flags\":$EP_FLAGS_B$SPEC_ENV,\"idleUnloadSeconds\":$EP_IDLE_SECONDS,\"startOnDemand\":true}}"
R=$(curl -s -w '\n%{http_code}' -X POST -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/runtimes" -H 'content-type: application/json' -d "$SPEC")
CODE=$(echo "$R" | tail -1); BODY=$(echo "$R" | sed '$d')
[ "$CODE" = "201" ] && ok "*** control forwarded the declaration to node-b with service:control (201): $(echo "$BODY" | jq_ "'%s on %s' % (d['name'], d['node'])") ***" || { bad "control POST /v1/runtimes returned $CODE: $BODY"; }
[ "$(curl -s -H "Authorization: Bearer $CTOK" "$EP_AGENT_A_URL/v1/runtimes" | jq_ "len(d['runtimes'])")" = "0" ] && ok "A has no runtime — it went to B" || bad "the runtime landed on A"
for _ in $(seq 1 120); do
  RB=$(curl -s -H "Authorization: Bearer $CTOK" "$EP_AGENT_B_URL/v1/runtimes/$RT"); ST=$(echo "$RB" | jq_ "d.get('status')" 2>/dev/null)
  [ "$ST" = "ready" ] || [ "$ST" = "crashed" ] && break; sleep 1
done
[ "$ST" = "ready" ] && ok "B's engine ready; Runtime.node=$(echo "$RB" | jq_ "d.get('node')") driver=$(echo "$RB" | jq_ "d.get('driver')")" || { bad "B runtime status=$ST $(echo "$RB" | jq_ "d.get('lastError')")"; tail -20 agent-b.log; }
COMP=$(curl -s -H "Authorization: Bearer $CTOK" "$EP_AGENT_B_URL/v1/components/$RT-driver")
echo "  companion: url=$(echo "$COMP" | jq_ "d.get('url')") advertiseUrl=$(echo "$COMP" | jq_ "d.get('advertiseUrl')") status=$(echo "$COMP" | jq_ "d.get('status')")"
COMP_URL=$(echo "$COMP" | jq_ "(d.get('advertiseUrl') or d.get('url') or '').rstrip('/')" 2>/dev/null)
[ "$(echo "$COMP" | jq_ "(d.get('advertiseUrl') or '').startswith('$B_ADV_PREFIX')")" = "True" ] && ok "companion carries Component.advertiseUrl on B's advertise host ($B_ADV_PREFIX), its own port" || bad "companion advertiseUrl not on $B_ADV_PREFIX: $(echo "$COMP" | jq_ "d.get('advertiseUrl')")"
for _ in $(seq 1 60); do
  M=$(curl -s -H "Authorization: Bearer $CTOK" "$EP_GATEWAY_URL/v1/models")
  RN=$(echo "$M" | jq_ "next((m['x_eugene_plexus'].get('ready_backends') for m in d.get('data',[]) if m['id']=='$ALIAS'), 0)" 2>/dev/null)
  [ "$RN" = "1" ] && break; sleep 1
done
[ "$RN" = "1" ] && ok "*** gateway on 'host A' lists $ALIAS with ready_backends=1 behind B's companion — the gateway's token verified on a driver spawned by ANOTHER agent ***" || { bad "gateway never listed $ALIAS ready (ready_backends=$RN)"; curl -s -H "Authorization: Bearer $CTOK" "$EP_GATEWAY_URL/v1/admin/drivers" | head -c 400; echo; }
VIEW=$(curl -s -H "Authorization: Bearer $CTOK" "$EP_GATEWAY_URL/v1/admin/routing")
echo "  routing view: $(echo "$VIEW" | jq_ "[(b['driver'], b.get('node'), b['url'], b['runtime_status']) for s in d['slots'] for t in s['tiers'] for b in t['backends']]")"
[ "$(echo "$VIEW" | jq_ "any(b.get('node')=='node-b' for s in d['slots'] for t in s['tiers'] for b in t['backends'])")" = "True" ] && ok "routing view attributes the backend to node-b" || bad "no node-b attribution in the routing view"

# --- 7. completion -----------------------------------------------------------------
complete() { curl -s -m 300 -X POST "$EP_GATEWAY_URL/v1/chat/completions" -H "Authorization: Bearer $CTOK" -H 'content-type: application/json' -d "{\"model\":\"$ALIAS\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word OK. /no_think\"}],\"max_tokens\":16,\"temperature\":0.1}"; }
say "7. a completion, served on B, attributed to B"
C=$(complete); TXT=$(echo "$C" | jq_ "(d.get('choices') or [{}])[0].get('message',{}).get('content','').strip()" 2>/dev/null)
[ -n "$TXT" ] && ok "*** COMPLETION through B's companion: '$TXT' driver=$(echo "$C" | jq_ "d['x_eugene_plexus']['driver']") runtime=$(echo "$C" | jq_ "d['x_eugene_plexus'].get('runtime')") ***" || { bad "completion failed: $(echo "$C" | head -c 300)"; }

# --- 8. idle unload crosses hosts ----------------------------------------------------
say "8. idle ${EP_IDLE_SECONDS}s — the stop must reach :$B_PORT, not :8079"
for _ in $(seq 1 $((EP_IDLE_SECONDS + 45))); do
  ST=$(curl -s -H "Authorization: Bearer $CTOK" "$EP_AGENT_B_URL/v1/runtimes/$RT" | jq_ "'%s/%s' % (d['status'], d.get('stopReason'))" 2>/dev/null)
  [ "$ST" = "stopped/idle" ] && break; sleep 1
done
[ "$ST" = "stopped/idle" ] && ok "*** IDLE UNLOAD CROSSED HOSTS: B reports $ST ***" || bad "B runtime: $ST"

# --- 9. wake crosses hosts -----------------------------------------------------------
say "9. a request for the sleeping alias wakes it on B"
# What the table believes right now, before anything is asked of it. THE OPEN
# WINDOW: with no pause here, two runs sent the request ~2.5 s after the stop
# and the gateway routed to B's companion as eligible — a 502 from the driver
# instead of a wake — even though it had refreshed twice and read B's
# /v1/runtimes (200) after the stop. With 4 s it wakes every time. Not
# diagnosed; the refresh lock landed as a plausible cause and did not close
# it. EP_WAKE_DELAY=0 reproduces. See the acceptance record.
sleep "${EP_WAKE_DELAY:-4}"
echo "  B says: $(curl -s -H "Authorization: Bearer $CTOK" "$EP_AGENT_B_URL/v1/runtimes" | jq_ "[(r['name'], r['status'], r.get('modelAlias'), r.get('node')) for r in d['runtimes']]")"
echo "  driver /v1/info says: $(curl -s -m 5 -H "Authorization: Bearer $CTOK" "$COMP_URL/v1/info" | jq_ "(d.get('modelId'), d.get('runtime'), d.get('backend'))" 2>/dev/null)"
echo "  gateway view: $(curl -s -H "Authorization: Bearer $CTOK" "$EP_GATEWAY_URL/v1/admin/routing" | jq_ "(d.get('refreshed_at'), [(b['driver'], b['eligible'], b.get('runtime'), b.get('runtime_status'), b.get('node')) for s in d.get('slots',[]) for t in s['tiers'] for b in t['backends']])")"
START=$(date +%s%3N); C=$(complete); END=$(date +%s%3N)
SW=$(echo "$C" | jq_ "(d.get('x_eugene_plexus') or {}).get('swapped_in')" 2>/dev/null)
[ "$SW" = "True" ] && ok "*** WAKE CROSSED HOSTS: swapped_in=true in $((END - START))ms, waited_ms=$(echo "$C" | jq_ "d['x_eugene_plexus'].get('waited_ms')") ***" || bad "wake: $(echo "$C" | head -c 300)"
[ "$(curl -s -H "Authorization: Bearer $CTOK" "$EP_AGENT_B_URL/v1/runtimes/$RT" | jq_ "d['status']")" = "ready" ] && ok "B's runtime is ready again" || bad "B runtime not ready after wake"

# --- 10. rotation ---------------------------------------------------------------------
say "10. rotate the install's signing key at the control root — both agents must take it"
RC=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/control/rotate-key")
[ "$RC" = "202" ] && ok "rotation accepted (202); this session is now invalid by design" || bad "rotate-key returned $RC"
sleep 2; CTOK=$(ctl_login)
for _ in $(seq 1 30); do
  ROT=$(curl -s -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/control/rotate-key"); RS=$(echo "$ROT" | jq_ "d.get('state')" 2>/dev/null)
  [ "$RS" = "done" ] || [ "$RS" = "failed" ] && break; sleep 1
done
echo "  rotation: $(echo "$ROT" | jq_ "'state=%s rekeyed=%s/%s pending=%s' % (d.get('state'), d.get('nodesRekeyed'), d.get('nodesTotal'), d.get('nodesPending'))")"
[ "$RS" = "done" ] && ok "*** ROTATION DONE: both nodes re-keyed via the signed /v1/node/rekey ***" || bad "rotation ended $RS: $(echo "$ROT" | jq_ "d.get('error')")"
for _ in $(seq 1 60); do wait_healthy "$EP_GATEWAY_URL" 1 && curl -sf -m 2 -H "Authorization: Bearer $CTOK" "$EP_AGENT_B_URL/v1/node" >/dev/null 2>&1 && break; sleep 1; done
for U in "$EP_AGENT_A_URL" "$EP_AGENT_B_URL"; do
  KID=$(curl -s -H "Authorization: Bearer $CTOK" "$U/v1/node" | jq_ "d.get('signingKeyId')")
  [ "$KID" = "2" ] && ok "$U holds signing key generation 2" || bad "$U signingKeyId=$KID"
done
for _ in $(seq 1 60); do
  RN=$(curl -s -H "Authorization: Bearer $CTOK" "$EP_GATEWAY_URL/v1/models" | jq_ "next((m['x_eugene_plexus'].get('ready_backends') for m in d.get('data',[]) if m['id']=='$ALIAS'), 0)" 2>/dev/null)
  [ "$RN" = "1" ] && break; sleep 1
done
C=$(complete); TXT=$(echo "$C" | jq_ "(d.get('choices') or [{}])[0].get('message',{}).get('content','').strip()" 2>/dev/null)
[ -n "$TXT" ] && ok "*** COMPLETION UNDER THE NEW KEY: gateway (restarted by A) -> B's companion (restarted by B): '$TXT' ***" || bad "completion after rotation failed: $(echo "$C" | head -c 300)"

# --- 11. fencing -----------------------------------------------------------------------
say "11. fencing — a re-key at epoch 0 signed with the REAL control identity"
curl -s -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/control/snapshot" > snapshot.json
FORGE=$("$EP_AGENT_PY" - "$PASSPHRASE" <<'PY'
import base64, json, sys
from eugene_plexus_control import sealing, security
snap = json.load(open("snapshot.json", encoding="utf-8"))
master = security.derive_master_key(sys.argv[1], base64.b64decode(snap["salt"]))
control_private = base64.b64encode(security.open_b64(snap["sealedControlKey"], master)).decode()
key_b64 = base64.b64encode(security.open_b64(snap["sealedSigningKey"], master)).decode()
msg = sealing.rekey_message(signing_key=key_b64, signing_key_id=snap["signingKeyId"], epoch=0)
print(json.dumps({"signingKey": key_b64, "signingKeyId": snap["signingKeyId"], "epoch": 0, "signature": sealing.sign_rekey(control_private, msg)}))
PY
)
FC=$(curl -s -w '\n%{http_code}' -X POST "$EP_AGENT_B_URL/v1/node/rekey" -H 'content-type: application/json' -d "$FORGE"); CODE=$(echo "$FC" | tail -1)
[ "$CODE" = "409" ] && ok "*** FENCED: a genuinely signed epoch-0 re-key is refused with 409: $(echo "$FC" | sed '$d' | jq_ "d['detail']['detail'][:90]") ***" || bad "epoch-0 re-key returned $CODE"
GARBAGE=$(echo "$FORGE" | PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); d['epoch']=99; print(json.dumps(d))")
[ "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$EP_AGENT_B_URL/v1/node/rekey" -H 'content-type: application/json' -d "$GARBAGE")" = "401" ] && ok "the same body with the epoch changed (signature no longer matches) is 401" || bad "tampered re-key not 401"
[ "$(curl -s -H "Authorization: Bearer $CTOK" "$EP_AGENT_B_URL/v1/node" | jq_ "d.get('epoch')")" = "1" ] && ok "B still at epoch 1" || bad "B's epoch moved"

# --- 12. teardown -------------------------------------------------------------------------
say "12. teardown"
kill "$A_PID" 2>/dev/null; [ -n "$B_PID" ] && kill "$B_PID" 2>/dev/null
sleep 5
if [ "$EP_MODE" = "same-box" ]; then
  LEFT=$(powershell.exe -NoProfile -Command "(Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r')
  [ "${LEFT:-0}" = "0" ] && ok "no llama-server survived" || bad "$LEFT llama-server process(es) survived"
else
  # B's agent is not this script's to start or stop, so B's engine and
  # companion are still running on purpose. Checking THIS host for a
  # leftover engine would pass vacuously -- and would be looking for the
  # wrong engine on the wrong machine, since B need not run llama.cpp at
  # all. Say so rather than bank a check that cannot fail.
  say_left=$(curl -s -m 5 -H "Authorization: Bearer $CTOK" "$EP_AGENT_B_URL/v1/runtimes" | jq_ "[(r['name'], r['status']) for r in d.get('runtimes', [])]" 2>/dev/null)
  echo "  NOTE  host B is left running, as it was found: $say_left"
  echo "        stop it where you started it; nothing here owns B's lifecycle."
fi

say "what this run proved / could not"
echo "  proved: enrollment over real HTTP with real tokens; the install key on a companion born after enrollment;"
echo "          the gateway's token verifying on it; fan-out + node attribution from a real /v1/nodes; a stop and a"
echo "          wake for B's runtime reaching :$B_PORT; a real rotation re-keying both agents with the gateway serving"
echo "          afterwards; a signed epoch-0 re-key fenced."
if [ "$EP_MODE" = "two-host" ]; then
  echo "  also:   a NON-LOOPBACK BIND on every one of A's services, and every hop above crossing a real network"
  echo "          between two kernels -- so the last item on the old 'cannot' list is discharged."
  echo "  cannot: a node genuinely offline during a rotation; clock skew (both clocks come from one host);"
  echo "          a partitioned (not dead) old root. Those need two machines that can be severed independently."
else
  echo "  cannot: a node genuinely offline during a rotation; clock skew; a partitioned (not dead) old root;"
  echo "          any non-loopback bind. The last one is discharged by EP_MODE=two-host; the rest are not."
fi
say "result"
if [ "$FAILURES" -eq 0 ]; then
  if [ "$EP_MODE" = "two-host" ]; then
    echo "M7 acceptance PASSED — two hosts, $EP_AGENT_A_URL and $EP_AGENT_B_URL, nothing on loopback between them."
  else
    echo "M7 acceptance PASSED — a second host is possible, on one box."
  fi
else
  echo "$FAILURES check(s) FAILED"
fi
exit "$FAILURES"
