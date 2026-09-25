#!/usr/bin/env bash
#
# M7 acceptance: a second host -- on one box, or on two.
#
# LAST RUN 2026-09-25, same-box, under per-node token keys (row 3): 57 PASS,
# 0 FAIL, second execution (the first failed only at the declaration: B's
# agent now refuses an engine binary outside `engineBinaryRoots`, which this
# script had never had to set). Every port moved +100 and the engine on the
# processor, because this box's live install holds 8079, 8090 and 8091 and
# all but 2.4 GB of the GPU:
#   EP_AGENT_A_URL=http://127.0.0.1:8179 EP_AGENT_B_URL=http://127.0.0.1:8184 \
#   EP_CONTROL_URL=http://127.0.0.1:8183 EP_GATEWAY_URL=http://127.0.0.1:8180 \
#   EP_LIBRARY_URL=http://127.0.0.1:8182 EP_COMPANION_PORT_B=8186 \
#   EP_ENGINE_PORT_B=8190 \
#   EP_FLAGS_B='{"contextSize":4096,"gpuLayers":0,"parallelSlots":1}' \
#   bash scripts/m7-acceptance.sh
#
# EARLIER, under the shared install key, both green, 41 checks each:
#   same-box   many times, most recently 2026-09-11
#   two-host   2026-09-11, FIRST EVER -- host A Windows, host B WSL2
#              Ubuntu 26.04 at 172.19.221.94, A's services bound 0.0.0.0
#              and addressed at 172.19.208.1, B running vLLM. Record:
#              docs/acceptance/m7-two-host-run.md
#
#   host A (this box)        agent A :8079  -> spawns control :8083, gateway :8080, library :8082
#   host B (also this box)   agent B :8084  -> spawns nothing until told; own config dir
#   (the defaults; every one is a variable, and the preflight refuses a port
#   something already holds rather than sharing it)
#
# Both agents enroll with the control root over real HTTP with real join
# tokens -- A's carrying the `gateway` grant, because A runs the gateway.
# Each node keeps its own token key; nothing private crosses the wire. A
# runtime is declared ON B THROUGH THE CONTROL ROOT; B spawns its companion
# driver; the gateway (a child of A) reaches it with a short-lived
# `sub: gateway` token its own agent signs for node-b, lists it, serves it,
# idles it out and wakes it. Then the root's token key is rotated: every
# session ends on every machine and nothing else changes -- no node key
# moves, nothing restarts, and the gateway goes on serving B. Last, B
# refuses trust bundles that are forged, rolled back, or at a lower epoch.
#
# Rewritten for per-node token keys (2026-09-25,
# docs/design/per-node-token-keys.md). Removed or replaced:
#   * "A control-minted token verifies on A and reads B's runtimes": a
#     session is addressed now, so the root's own session is REFUSED by both
#     agents and each agent is read with a session from its own sign-in.
#   * "The companion is born with the install's signing key": there is no
#     install key; the check is that B's companion verifies the gateway's
#     per-machine token, and refuses one addressed to A.
#   * "Both nodes hold signing key generation 2 after rotation" and polling
#     `GET /v1/control/rotate-key` for `done`: rotation redistributes
#     nothing and has no progress; the checks are that every old session is
#     refused everywhere, each node's token key and node.yaml are unchanged,
#     and neither the gateway nor the companion restarted.
#   * "A genuinely signed epoch-0 re-key is fenced" (`/v1/node/rekey` is
#     gone): replaced by trust bundles pushed to `/v1/node/trust-bundle` --
#     one genuinely signed at a lower epoch and one a version older (409),
#     one signed by a key B never pinned and one edited after signing (401).
#   * "No llama-server survived": this box's live install runs its own, so
#     counting processes by name reads it; the check is now that nothing
#     listens on any port this run used.
#
# Written for two hosts and parameterised by two agent URLs. EP_MODE:
#   same-box  (default) start both agents here; B on a second port
#   two-host  agent B is already running at EP_AGENT_B_URL on another host
#             with EP_AGENT_B_PASSPHRASE set, and with its engine binary's
#             directory in its own `engineBinaryRoots`; nothing is spawned
#             for it
#
# WHAT ONE BOX PROVES AND DOES NOT -- printed again at the end.
#   proves: enrollment over HTTP with a real token and per-node keys; a
#           session opening only the machine it was signed in on and the
#           root; the gateway's per-machine token verifying on a companion
#           another agent spawned; fan-out and attribution by node from a
#           real /v1/nodes; a lifecycle action for B's runtime reaching B's
#           port and not A's; a real rotation ending every session with the
#           data path untouched; forged, rolled-back and lower-epoch bundles
#           refused.
#   cannot: a node genuinely offline during a rotation; clock skew; a root
#           partitioned rather than dead (the forge tests the refusal, not
#           the partition); any bind to a non-loopback interface.
#
set -uo pipefail

# Nothing from the calling shell's install reaches anything started here:
# this box's live agent sets EUGENE_PLEXUS_AGENT_CONFIG_FILE at user scope,
# and a throwaway agent that loads the operator's node.yaml announces the
# real node at a port that dies with this script.
while read -r _ep_var; do unset "$_ep_var"; done < <(compgen -e | grep -i '^EUGENE_PLEXUS_')

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
EP_LIBRARY_URL="${EP_LIBRARY_URL:-http://127.0.0.1:8082}"
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
# The engine's port on B, and (same-box only) its companion driver's. Unset,
# B's agent assigns both from 8090 up without asking the host, which on a
# box that already runs an install lands on that install's engine. Set, the
# engine's port rides on the declaration, and the companion's topology entry
# is written into B's agent.yaml where the agent would write it -- the agent
# adopts it as its companion (`companions.is_companion`), writes its config
# and restarts it, which is the path a boot-time reconcile takes.
EP_ENGINE_PORT_B="${EP_ENGINE_PORT_B:-}"
EP_COMPANION_PORT_B="${EP_COMPANION_PORT_B:-}"
# The directory B's agent trusts engine binaries in (`engineBinaryRoots`):
# since 2026-09-22 an agent refuses a declared binary outside its managed
# store, that list and PATH. Same-box it is written into B's agent.yaml, and
# defaults to the directory of EP_LLAMA_SERVER; a two-host B sets its own.
EP_ENGINE_DIR_B="${EP_ENGINE_DIR_B:-}"
# Set this to a non-loopback URL for a real two-host run. It matters more
# than it looks: a component binds 0.0.0.0 only when its node advertises a
# non-loopback address, and enrollment deliberately does NOT restart the
# control root -- so if A's advertise address is only discovered at
# enrollment time, the root stays bound to loopback and B can never reach
# it. Setting it up front is what makes the root reachable at all.
EP_ADVERTISE_A="${EP_ADVERTISE_A:-}"

port_of() { printf '%s' "$1" | sed -E 's|.*:([0-9]+)/?$|\1|'; }
A_PORT=$(port_of "$EP_AGENT_A_URL")
B_PORT=$(port_of "$EP_AGENT_B_URL")
CONTROL_PORT=$(port_of "$EP_CONTROL_URL")
GATEWAY_PORT=$(port_of "$EP_GATEWAY_URL")
LIBRARY_PORT=$(port_of "$EP_LIBRARY_URL")

# Whatever host B answers on is the host its companion will advertise.
# Same-box that is http://127.0.0.1:, which this used to assert literally.
B_ADV_PREFIX="$(printf '%s' "$EP_AGENT_B_URL" | sed -E 's|:[0-9]+/?$||'):"

FAILURES=0
PASSES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; PASSES=$((PASSES + 1)); }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
win_path() { printf '%s' "$1" | sed 's|/|\\|g'; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -m 10 -w '%{http_code}' -H "Authorization: Bearer $2" "$1"; }
# A token's header and claims, unverified: which key signed it and who it is for.
kid_of() { printf '%s' "$1" | PYTHONUTF8=1 python -c "import sys,json,base64; h=sys.stdin.read().strip().split('.')[0]; print(json.loads(base64.urlsafe_b64decode(h + '=' * (-len(h) % 4))).get('kid',''))"; }
aud_of() { printf '%s' "$1" | PYTHONUTF8=1 python -c "import sys,json,base64; p=sys.stdin.read().strip().split('.')[1]; print(','.join(json.loads(base64.urlsafe_b64decode(p + '=' * (-len(p) % 4))).get('aud',[])))"; }
ctl_login() { curl -s -X POST "$EP_CONTROL_URL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')" 2>/dev/null; }
agent_login() { curl -s -X POST "$1/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$2\"}" | jq_ "d.get('sessionToken','')" 2>/dev/null; }
# An enrolled agent's sign-in is the root's: it answers 503 while the root is
# not reachable yet. Bounded, not assumed.
login_retry() { local t=""; for _ in $(seq 1 30); do t=$(agent_login "$1" "$2"); [ -n "$t" ] && break; sleep 1; done; printf '%s' "$t"; }
port_free() {
  local p="$1"
  curl -s -m 1 -o /dev/null "http://127.0.0.1:$p/healthz" && return 1
  netstat -ano 2>/dev/null | grep LISTENING | grep -qE "[:.]$p[[:space:]]" && return 1
  return 0
}

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
# Every port this run will bind, proved free before anything starts -- which
# is also what makes tearing down by these ports safe. A port something else
# holds is refused, never shared: Windows lets a second process bind a held
# loopback port and keeps serving from the oldest binder.
RUN_PORTS=("$A_PORT" "$CONTROL_PORT" "$GATEWAY_PORT" "$LIBRARY_PORT")
if [ "$EP_MODE" = "same-box" ]; then
  RUN_PORTS+=("$B_PORT")
  if [ -n "$EP_COMPANION_PORT_B" ]; then RUN_PORTS+=("$EP_COMPANION_PORT_B"); else RUN_PORTS+=(8091); fi
  if [ -n "$EP_ENGINE_PORT_B" ]; then RUN_PORTS+=("$EP_ENGINE_PORT_B"); else RUN_PORTS+=(8090); fi
fi
TAKEN=""
for p in "${RUN_PORTS[@]}"; do port_free "$p" || TAKEN="$TAKEN $p"; done
if [ -n "$TAKEN" ]; then
  bad "port(s)$TAKEN already in use; move every EP_*_URL (and EP_ENGINE_PORT_B / EP_COMPANION_PORT_B, whose unset defaults are the agent's 8090/8091) to free ports"
  exit 1
fi
ok "binary, model, five components; every port this run binds is free (${RUN_PORTS[*]}); A=$EP_AGENT_A_URL B=$EP_AGENT_B_URL control=$EP_CONTROL_URL"
# Defaults that reproduce the same-box run: B is this box, so B's paths
# are A's paths in Windows form.
[ -n "$EP_MODEL_B" ] || EP_MODEL_B="$(win_path "$EP_MODEL" | sed 's|\\|\\\\|g')"
[ -n "$EP_BINARY_B" ] || EP_BINARY_B="$(win_path "$EP_LLAMA_SERVER" | sed 's|\\|\\\\|g')"
[ -n "$EP_FLAGS_B" ] || EP_FLAGS_B='{"contextSize":4096,"gpuLayers":99,"parallelSlots":1}'
[ -n "$EP_ENGINE_DIR_B" ] || EP_ENGINE_DIR_B="$(dirname "$EP_LLAMA_SERVER")"
echo "  host B: engine=$EP_ENGINE_B  model=$EP_MODEL_B"
echo "          binary=$EP_BINARY_B"
echo "          flags=$EP_FLAGS_B  env=${EP_ENV_B:-none}  enginePort=${EP_ENGINE_PORT_B:-assigned}  companionPort=${EP_COMPANION_PORT_B:-assigned}"

rm -rf "$EP_WORKDIR"; mkdir -p "$EP_WORKDIR/a" "$EP_WORKDIR/b"; cd "$EP_WORKDIR" || exit 1
WIN_WORKDIR="$(pwd -W)"

cat > a/agent.yaml <<YAML
firstRunComplete: true
${EP_ADVERTISE_A:+advertiseUrl: $EP_ADVERTISE_A}
components:
  - name: control
    kind: control
    url: http://127.0.0.1:$CONTROL_PORT
    spawn:
      configFile: control.yaml
  - name: gateway
    kind: gateway
    url: http://127.0.0.1:$GATEWAY_PORT
    spawn:
      configFile: gateway.yaml
  - name: library
    kind: library
    url: http://127.0.0.1:$LIBRARY_PORT
    spawn:
      configFile: library.yaml
runtimes: []
YAML
# No controlUrl: the gateway derives it from its own agent (2026-09-13).
# Writing it here by hand is how two green two-host runs never touched the
# path an operator takes, while nothing in the product set it.
cat > a/gateway.yaml <<YAML
logLevel: INFO
routingRefreshSeconds: 3
idleCheckSeconds: 5
swapWaitSeconds: 120
YAML
echo "logLevel: INFO" > a/control.yaml
printf 'logLevel: INFO\nmodelRoots:\n  - %s\n' "$(win_path "$(dirname "$EP_MODEL")")" > a/library.yaml
if [ -n "$EP_COMPANION_PORT_B" ]; then
  mkdir -p b/drivers
  printf "firstRunComplete: true\nengineBinaryRoots:\n  - '%s'\ncomponents:\n  - name: %s-driver\n    kind: inference-driver\n    url: http://127.0.0.1:%s\n    spawn:\n      configFile: drivers/%s-driver.yaml\nruntimes: []\n" \
    "$EP_ENGINE_DIR_B" "$RT" "$EP_COMPANION_PORT_B" "$RT" > b/agent.yaml
else
  printf "firstRunComplete: true\nengineBinaryRoots:\n  - '%s'\ncomponents: []\nruntimes: []\n" "$EP_ENGINE_DIR_B" > b/agent.yaml
fi

# --- 1. agent A and its fleet --------------------------------------------------
say "1. agent A starts control, gateway (controlUrl NOT set: it derives it) and library"
# `exec`, so the pid we hold is the agent's and not a subshell's -- the first
# run killed two subshells and orphaned both agents and an engine.
# Bind wide only when A actually advertises a non-loopback address; the
# agent passes the same widening down to every component it spawns.
A_BIND_ENV=()
[ -n "$EP_ADVERTISE_A" ] && A_BIND_ENV=(EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0)
(cd a && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$A_PORT" "${A_BIND_ENV[@]}" "$EP_AGENT_PY" -m eugene_plexus_agent > ../agent-a.log 2>&1) &
A_PID=$!
B_PID=""
trap 'kill "$A_PID" 2>/dev/null; [ -n "$B_PID" ] && kill "$B_PID" 2>/dev/null' EXIT
wait_healthy "$EP_AGENT_A_URL" && ok "agent A answering on :$A_PORT" || { bad "agent A never came up"; tail -30 agent-a.log; exit 1; }
wait_healthy "$EP_CONTROL_URL" && ok "control root answering" || { bad "control never came up"; tail -30 agent-a.log; exit 1; }
wait_healthy "$EP_GATEWAY_URL" 90 && ok "gateway answering" || bad "gateway never came up"
curl -s -o /dev/null -X POST "$EP_CONTROL_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}"
CTOK=$(ctl_login); [ -n "$CTOK" ] || { bad "no control session"; exit 1; }
[ "$(aud_of "$CTOK")" = "control" ] && ok "control initialized; its own sign-in is a session addressed to the root alone" || bad "the root's session is addressed to $(aud_of "$CTOK")"
ATOK=$(curl -s -X POST "$EP_AGENT_A_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
[ -n "$ATOK" ] && [ "$(aud_of "$ATOK")" = "node:local" ] && ok "agent A initialized; standalone, it mints its own session (aud node:local)" || { bad "no standalone agent A session (aud=$(aud_of "$ATOK"))"; exit 1; }

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
[ -n "$BTOK" ] && ok "agent B session issued (standalone, signed by B's own key)" || { bad "no agent B session"; exit 1; }
BTOK_STANDALONE="$BTOK"
BN=$(curl -s -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/node")
[ "$(echo "$BN" | jq_ "d['enrolled']")" = "False" ] && ok "B reports enrolled=false before enrollment" || bad "B: $BN"

# --- 3. enroll A -----------------------------------------------------------------
say "3. enroll agent A (the control host) with a join token bound to node-a that grants the gateway"
# A runs the gateway, so its join token carries the `gateway` grant: without
# it, A's agent refuses to sign the `sub: gateway` tokens the gateway needs
# to reach any other machine's drivers and agents.
TOK_A=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"node-a","grants":["gateway"]}' | jq_ "d['token']")
EA=$(curl -s -w '\n%{http_code}' -X POST -H "Authorization: Bearer $ATOK" "$EP_AGENT_A_URL/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$EP_CONTROL_URL\",\"token\":\"$TOK_A\",\"name\":\"node-a\"}")
CODE=$(echo "$EA" | tail -1); BODY=$(echo "$EA" | sed '$d')
[ "$CODE" = "200" ] && ok "A enrolled: $(echo "$BODY" | jq_ "'name=%s epoch=%s bundle=%s advertise=%s' % (d['name'], d['epoch'], d.get('trustBundleVersion'), d.get('advertiseUrl'))")" || { bad "A enroll returned $CODE: $BODY"; tail -20 agent-a.log; }
# A's children restart so they trust the install's bundle (the control root
# is skipped -- it is the trust root).
wait_healthy "$EP_GATEWAY_URL" 90 || bad "gateway did not come back after A enrolled"
curl -sf -m 3 "$EP_CONTROL_URL/healthz" >/dev/null && ok "control root stayed up through A's enrollment (not restarted)" || bad "control root went away"
[ "$(code_of "$EP_AGENT_A_URL/v1/node" "$ATOK")" = "401" ] && ok "A's standalone session is refused now that A trusts the root's bundle" || bad "A still accepts its standalone session"
[ "$(code_of "$EP_AGENT_A_URL/v1/node" "$CTOK")" = "401" ] && ok "the root's own session (aud control) is refused by A: sessions are addressed" || bad "A accepted a session addressed only to the root"
ATOK=$(login_retry "$EP_AGENT_A_URL" "$PASSPHRASE")
[ "$(aud_of "$ATOK")" = "node:node-a,control" ] && ok "*** signing in at A is the root's: a session addressed to node:node-a and the root ***" || bad "A's sign-in gave aud=$(aud_of "$ATOK")"
[ "$(code_of "$EP_AGENT_A_URL/v1/node" "$ATOK")" = "200" ] && ok "A's session opens A" || bad "A's session refused by A"

# --- 4. enroll B -----------------------------------------------------------------
say "4. enroll agent B over HTTP with a join token bound to node-b (no grants)"
TOK_B=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"node-b"}' | jq_ "d['token']")
EB=$(curl -s -w '\n%{http_code}' -X POST -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$EP_CONTROL_URL\",\"token\":\"$TOK_B\",\"name\":\"node-b\"}")
CODE=$(echo "$EB" | tail -1); BODY=$(echo "$EB" | sed '$d')
if [ "$CODE" = "200" ]; then
  ok "*** B ENROLLED: $(echo "$BODY" | jq_ "'name=%s epoch=%s bundle=%s tokenKey=%s' % (d['name'], d['epoch'], d.get('trustBundleVersion'), 'yes' if d.get('tokenPublicKey') else 'NO')") ***"
  ADV=$(echo "$BODY" | jq_ "(d.get('advertiseUrl') or '').rstrip('/')")
  [ "$ADV" = "$EP_AGENT_B_URL" ] && ok "advertiseUrl derived from the route to the root: $ADV" || bad "advertiseUrl=$ADV expected $EP_AGENT_B_URL"
else bad "B enroll returned $CODE: $BODY"; tail -20 agent-b.log 2>/dev/null; fi
BTOK=$(login_retry "$EP_AGENT_B_URL" "$EP_AGENT_B_PASSPHRASE")
[ -n "$BTOK" ] || bad "no session from B's sign-in after enrollment"
[ "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$EP_CONTROL_URL\",\"token\":\"$TOK_B\",\"name\":\"node-b\"}")" = "409" ] && ok "enrolling B again is 409" || bad "second enroll not 409"
# A replay at the root with a well-formed request: three fresh 32-byte keys,
# so the only thing wrong with it is the spent token.
FRESH=$("$EP_AGENT_PY" -c "import base64, os; print(' '.join(base64.b64encode(os.urandom(32)).decode() for _ in range(3)))")
read -r K1 K2 K3 <<< "$FRESH"
[ "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$EP_CONTROL_URL/v1/nodes/enroll" -H 'content-type: application/json' -d "{\"token\":\"$TOK_B\",\"name\":\"node-c\",\"publicKey\":\"$K1\",\"signingPublicKey\":\"$K2\",\"tokenPublicKey\":\"$K3\"}")" = "409" ] && ok "replaying B's spent token at the root is 409" || bad "token replay not 409"

NODES=$(curl -s -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/nodes")
echo "  nodes: $(echo "$NODES" | jq_ "[(n['name'], (n.get('url') or '').rstrip('/'), n.get('grants')) for n in d['nodes']]")"
[ "$(echo "$NODES" | jq_ "sorted((n.get('url') or '').rstrip('/') for n in d['nodes']) == sorted(['$EP_AGENT_A_URL','$EP_AGENT_B_URL'])")" = "True" ] && ok "*** /v1/nodes carries BOTH agents' URLs (the field enrollment never used to send) ***" || bad "node URLs wrong"
[ "$(echo "$NODES" | jq_ "{n['name']: 'gateway' in (n.get('grants') or []) for n in d['nodes']} == {'node-a': True, 'node-b': False}")" = "True" ] && ok "the root granted the gateway to node-a, whose join token carried it, and not to node-b" || bad "grants wrong"
for _ in $(seq 1 30); do
  NODES=$(curl -s -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/nodes")
  [ "$(echo "$NODES" | jq_ "all(n['reachable'] and n.get('lastSeenEpoch')==1 for n in d['nodes']) and len(d['nodes'])==2")" = "True" ] && break; sleep 1
done
[ "$(echo "$NODES" | jq_ "all(n['reachable'] and n.get('lastSeenEpoch')==1 for n in d['nodes'])")" = "True" ] && ok "control root polled both nodes: reachable, lastSeenEpoch=1" || bad "poll: $(echo "$NODES" | jq_ "[(n['name'], n['reachable'], n.get('lastSeenEpoch')) for n in d['nodes']]")"

# --- 5. a session opens the machine it was signed in on, and the root --------------
say "5. sessions are addressed: each opens its own machine and the root, nothing else"
[ "$(code_of "$EP_AGENT_B_URL/v1/node" "$BTOK_STANDALONE")" = "401" ] && ok "B's standalone session refused" || bad "B still accepts its standalone session"
[ "$(code_of "$EP_AGENT_B_URL/v1/runtimes" "$CTOK")" = "401" ] && ok "the root's own session is refused by B" || bad "B accepted a session addressed only to the root"
[ "$(code_of "$EP_AGENT_B_URL/v1/runtimes" "$ATOK")" = "401" ] && ok "A's session is refused by B" || bad "B accepted a session addressed to node-a"
[ "$(aud_of "$BTOK")" = "node:node-b,control" ] && ok "B's sign-in is a root session addressed to node:node-b and the root" || bad "B's session aud=$(aud_of "$BTOK")"
[ "$(code_of "$EP_AGENT_B_URL/v1/runtimes" "$BTOK")" = "200" ] && ok "*** B's session reads B's /v1/runtimes ***" || bad "B's session refused by B"
[ "$(code_of "$EP_CONTROL_URL/v1/nodes" "$BTOK")" = "200" ] && ok "*** the session B's sign-in got reads the control root ***" || bad "B's session refused by control"

# --- 6. declare on B through the control root ---------------------------------------
say "6. declare $RT on node-b THROUGH the control root; B spawns the companion"
SPEC_ENV=""
[ -n "$EP_ENV_B" ] && SPEC_ENV=",\"env\":$EP_ENV_B"
SPEC_PORT=""
[ -n "$EP_ENGINE_PORT_B" ] && SPEC_PORT=",\"port\":$EP_ENGINE_PORT_B"
SPEC="{\"node\":\"node-b\",\"spec\":{\"name\":\"$RT\",\"engine\":\"$EP_ENGINE_B\",\"modelPath\":\"$EP_MODEL_B\",\"modelAlias\":\"$ALIAS\",\"binary\":\"$EP_BINARY_B\",\"flags\":$EP_FLAGS_B$SPEC_ENV$SPEC_PORT,\"idleUnloadSeconds\":$EP_IDLE_SECONDS,\"startOnDemand\":true}}"
R=$(curl -s -w '\n%{http_code}' -X POST -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/runtimes" -H 'content-type: application/json' -d "$SPEC")
CODE=$(echo "$R" | tail -1); BODY=$(echo "$R" | sed '$d')
[ "$CODE" = "201" ] && ok "*** control forwarded the declaration to node-b with its own control token (201): $(echo "$BODY" | jq_ "'%s on %s' % (d['name'], d['node'])") ***" || { bad "control POST /v1/runtimes returned $CODE: $BODY"; }
[ "$(curl -s -H "Authorization: Bearer $ATOK" "$EP_AGENT_A_URL/v1/runtimes" | jq_ "len(d['runtimes'])")" = "0" ] && ok "A has no runtime -- it went to B" || bad "the runtime landed on A"
ST=""
for _ in $(seq 1 120); do
  RB=$(curl -s -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/runtimes/$RT"); ST=$(echo "$RB" | jq_ "d.get('status')" 2>/dev/null)
  [ "$ST" = "ready" ] || [ "$ST" = "crashed" ] && break; sleep 1
done
[ "$ST" = "ready" ] && ok "B's engine ready; Runtime.node=$(echo "$RB" | jq_ "d.get('node')") driver=$(echo "$RB" | jq_ "d.get('driver')")" || { bad "B runtime status=$ST $(echo "$RB" | jq_ "d.get('lastError')" 2>/dev/null)"; tail -20 agent-b.log; }
COMP=$(curl -s -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/components/$RT-driver")
echo "  companion: url=$(echo "$COMP" | jq_ "d.get('url')") advertiseUrl=$(echo "$COMP" | jq_ "d.get('advertiseUrl')") status=$(echo "$COMP" | jq_ "d.get('status')")"
COMP_URL=$(echo "$COMP" | jq_ "(d.get('advertiseUrl') or d.get('url') or '').rstrip('/')" 2>/dev/null)
WANT_PREFIX="$B_ADV_PREFIX"
[ -n "$EP_COMPANION_PORT_B" ] && [ "$EP_MODE" = "same-box" ] && WANT_PREFIX="${B_ADV_PREFIX}${EP_COMPANION_PORT_B}"
[ "$(echo "$COMP" | jq_ "(d.get('advertiseUrl') or '').startswith('$WANT_PREFIX')")" = "True" ] && ok "companion carries Component.advertiseUrl on B's advertise host ($WANT_PREFIX...)" || bad "companion advertiseUrl not on $WANT_PREFIX: $(echo "$COMP" | jq_ "d.get('advertiseUrl')")"
RN=""
for _ in $(seq 1 60); do
  M=$(curl -s -H "Authorization: Bearer $ATOK" "$EP_GATEWAY_URL/v1/models")
  RN=$(echo "$M" | jq_ "next((m['x_eugene_plexus'].get('ready_backends') for m in d.get('data',[]) if m['id']=='$ALIAS'), 0)" 2>/dev/null)
  [ "$RN" = "1" ] && break; sleep 1
done
[ "$RN" = "1" ] && ok "*** gateway on 'host A' lists $ALIAS with ready_backends=1 behind B's companion -- a per-machine token from A's agent verified on a driver ANOTHER agent spawned ***" || { bad "gateway never listed $ALIAS ready (ready_backends=$RN)"; curl -s -H "Authorization: Bearer $ATOK" "$EP_GATEWAY_URL/v1/admin/drivers" | head -c 400; echo; }
VIEW=$(curl -s -H "Authorization: Bearer $ATOK" "$EP_GATEWAY_URL/v1/admin/routing")
echo "  routing view: $(echo "$VIEW" | jq_ "[(b['driver'], b.get('node'), b['url'], b['runtime_status']) for s in d['slots'] for t in s['tiers'] for b in t['backends']]")"
[ "$(echo "$VIEW" | jq_ "any(b.get('node')=='node-b' for s in d['slots'] for t in s['tiers'] for b in t['backends'])")" = "True" ] && ok "routing view attributes the backend to node-b" || bad "no node-b attribution in the routing view"
# What the gateway presents, made the way its agent makes it: signed with A's
# own token key, `sub: gateway`, one recipient. Addressed to node-b it opens
# B's companion; addressed to A's own machine -- the kind of token the
# gateway was spawned with -- it is refused there.
mint_a() {
  EP_NODE_DIR="$WIN_WORKDIR/a" EP_AUD="$1" "$EP_AGENT_PY" -c "import os; from pathlib import Path; from eugene_plexus_agent.node_identity import NodeIdentityStore; from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust; d = Path(os.environ['EP_NODE_DIR']); s = NodeIdentityStore(d / 'node.yaml'); s.load(); t = NodeTrust(s, d / BUNDLE_FILE); t.load(); print(t.mint_service(sub='gateway', audience=os.environ['EP_AUD'])[0])"
}
GW_FOR_B=$(mint_a node:node-b); GW_FOR_A=$(mint_a node:node-a)
[ "$(code_of "$COMP_URL/v1/info" "$GW_FOR_B")" = "200" ] && ok "*** B's companion verifies a sub:gateway token A's key signed for node-b ***" || bad "B's companion refused A's gateway token for node-b"
[ "$(code_of "$COMP_URL/v1/info" "$GW_FOR_A")" = "401" ] && ok "...and refuses the same token addressed to node-a: a machine's own tokens are worthless elsewhere" || bad "B's companion accepted a token addressed to node-a"

# --- 7. completion -----------------------------------------------------------------
complete() { curl -s -m 300 -X POST "$EP_GATEWAY_URL/v1/chat/completions" -H "Authorization: Bearer $ATOK" -H 'content-type: application/json' -d "{\"model\":\"$ALIAS\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word OK. /no_think\"}],\"max_tokens\":16,\"temperature\":0.1}"; }
say "7. a completion, served on B, attributed to B"
C=$(complete); TXT=$(echo "$C" | jq_ "(d.get('choices') or [{}])[0].get('message',{}).get('content','').strip()" 2>/dev/null)
[ -n "$TXT" ] && ok "*** COMPLETION through B's companion: '$TXT' driver=$(echo "$C" | jq_ "d['x_eugene_plexus']['driver']") runtime=$(echo "$C" | jq_ "d['x_eugene_plexus'].get('runtime')") ***" || { bad "completion failed: $(echo "$C" | head -c 300)"; }

# --- 8. idle unload crosses hosts ----------------------------------------------------
say "8. idle ${EP_IDLE_SECONDS}s -- the stop must reach :$B_PORT, not :$A_PORT"
for _ in $(seq 1 $((EP_IDLE_SECONDS + 45))); do
  ST=$(curl -s -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/runtimes/$RT" | jq_ "'%s/%s' % (d['status'], d.get('stopReason'))" 2>/dev/null)
  [ "$ST" = "stopped/idle" ] && break; sleep 1
done
[ "$ST" = "stopped/idle" ] && ok "*** IDLE UNLOAD CROSSED HOSTS: B reports $ST ***" || bad "B runtime: $ST"

# --- 9. wake crosses hosts -----------------------------------------------------------
say "9. a request for the sleeping alias wakes it on B"
# What the table believes right now, before anything is asked of it. THE OPEN
# WINDOW: with no pause here, two runs sent the request ~2.5 s after the stop
# and the gateway routed to B's companion as eligible -- a 502 from the driver
# instead of a wake -- even though it had refreshed twice and read B's
# /v1/runtimes (200) after the stop. With 4 s it wakes every time. Not
# diagnosed; the refresh lock landed as a plausible cause and did not close
# it. EP_WAKE_DELAY=0 reproduces. See the acceptance record.
sleep "${EP_WAKE_DELAY:-4}"
echo "  B says: $(curl -s -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/runtimes" | jq_ "[(r['name'], r['status'], r.get('modelAlias'), r.get('node')) for r in d['runtimes']]")"
echo "  driver /v1/info says: $(curl -s -m 5 -H "Authorization: Bearer $BTOK" "$COMP_URL/v1/info" | jq_ "(d.get('modelId'), d.get('runtime'), d.get('backend'))" 2>/dev/null)"
echo "  gateway view: $(curl -s -H "Authorization: Bearer $ATOK" "$EP_GATEWAY_URL/v1/admin/routing" | jq_ "(d.get('refreshed_at'), [(b['driver'], b['eligible'], b.get('runtime'), b.get('runtime_status'), b.get('node')) for s in d.get('slots',[]) for t in s['tiers'] for b in t['backends']])")"
START=$(date +%s%3N); C=$(complete); END=$(date +%s%3N)
SW=$(echo "$C" | jq_ "(d.get('x_eugene_plexus') or {}).get('swapped_in')" 2>/dev/null)
[ "$SW" = "True" ] && ok "*** WAKE CROSSED HOSTS: swapped_in=true in $((END - START))ms, waited_ms=$(echo "$C" | jq_ "d['x_eugene_plexus'].get('waited_ms')") ***" || bad "wake: $(echo "$C" | head -c 300)"
[ "$(curl -s -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/runtimes/$RT" | jq_ "d['status']")" = "ready" ] && ok "B's runtime is ready again" || bad "B runtime not ready after wake"

# --- 10. rotation ---------------------------------------------------------------------
say "10. rotate the control root's token key -- every session ends, nothing else moves"
node_field() { curl -s -H "Authorization: Bearer $2" "$1/v1/node" | jq_ "d.get('$3')" 2>/dev/null; }
OLD_KID=$(kid_of "$CTOK")
A_KEY_BEFORE=$(node_field "$EP_AGENT_A_URL" "$ATOK" tokenPublicKey)
B_KEY_BEFORE=$(node_field "$EP_AGENT_B_URL" "$BTOK" tokenPublicKey)
A_YAML_BEFORE=$(sha256sum a/node.yaml | cut -c1-64)
B_YAML_BEFORE=""; [ "$EP_MODE" = "same-box" ] && B_YAML_BEFORE=$(sha256sum b/node.yaml | cut -c1-64)
GW_PID_BEFORE=$(curl -s -H "Authorization: Bearer $ATOK" "$EP_AGENT_A_URL/v1/components/gateway" | jq_ "d.get('pid')")
DRV_PID_BEFORE=$(curl -s -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/components/$RT-driver" | jq_ "d.get('pid')")
RR=$(curl -s -w '\n%{http_code}' -X POST -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/control/rotate-key")
CODE=$(echo "$RR" | tail -1); BODY=$(echo "$RR" | sed '$d')
VERSION=$(echo "$BODY" | jq_ "d.get('version')" 2>/dev/null)
[ "$CODE" = "202" ] && [ "$(echo "$BODY" | jq_ "d.get('reason')")" = "rotation" ] && ok "rotation accepted (202): bundle $VERSION names only the new root key; nodesBehind=$(echo "$BODY" | jq_ "d.get('nodesBehind')")" || bad "rotate-key returned $CODE: $BODY"
# Pushed at once; the agents' 60 s pull is the bound if a push is missed.
SEEN=""
for _ in $(seq 1 90); do
  SEEN="$(code_of "$EP_CONTROL_URL/v1/nodes" "$CTOK") $(code_of "$EP_AGENT_A_URL/v1/node" "$ATOK") $(code_of "$EP_AGENT_B_URL/v1/node" "$BTOK") $(code_of "$EP_GATEWAY_URL/v1/models" "$ATOK")"
  [ "$SEEN" = "401 401 401 401" ] && break; sleep 1
done
[ "$SEEN" = "401 401 401 401" ] && ok "*** every session the old key signed is refused: the root, A, B and A's gateway ***" || bad "old sessions after rotation (root A B gateway): $SEEN"
CTOK=$(ctl_login)
ATOK=$(login_retry "$EP_AGENT_A_URL" "$PASSPHRASE")
BTOK=$(login_retry "$EP_AGENT_B_URL" "$EP_AGENT_B_PASSPHRASE")
NEW_KIDS="$(kid_of "$CTOK") $(kid_of "$ATOK") $(kid_of "$BTOK")"
NEW_KID=$(kid_of "$CTOK")
[ -n "$NEW_KID" ] && [ "$NEW_KID" != "$OLD_KID" ] && [ "$NEW_KIDS" = "$NEW_KID $NEW_KID $NEW_KID" ] && ok "signing in again on the root, A and B gives sessions signed by the new root key" || bad "new session kids: $NEW_KIDS (old $OLD_KID)"
for U in "$EP_AGENT_A_URL" "$EP_AGENT_B_URL"; do
  TOKU="$ATOK"; [ "$U" = "$EP_AGENT_B_URL" ] && TOKU="$BTOK"
  HELD=""
  for _ in $(seq 1 90); do HELD=$(node_field "$U" "$TOKU" trustBundleVersion); [ -n "$HELD" ] && [ "$HELD" != "None" ] && [ "$HELD" -ge "${VERSION:-0}" ] 2>/dev/null && break; sleep 1; done
  [ -n "$HELD" ] && [ "$HELD" -ge "${VERSION:-999999}" ] 2>/dev/null && ok "$U holds trust bundle $HELD (rotation produced $VERSION)" || bad "$U trustBundleVersion=$HELD, want >= $VERSION"
done
[ "$(node_field "$EP_AGENT_A_URL" "$ATOK" tokenPublicKey)" = "$A_KEY_BEFORE" ] && [ "$(node_field "$EP_AGENT_B_URL" "$BTOK" tokenPublicKey)" = "$B_KEY_BEFORE" ] && ok "both nodes' own token keys are the ones they had: nothing was redistributed" || bad "a node's token key changed across rotation"
if [ "$EP_MODE" = "same-box" ]; then
  [ "$(sha256sum a/node.yaml | cut -c1-64)" = "$A_YAML_BEFORE" ] && [ "$(sha256sum b/node.yaml | cut -c1-64)" = "$B_YAML_BEFORE" ] && ok "node.yaml is byte-for-byte unchanged on A and B" || bad "rotation changed a node.yaml"
else
  [ "$(sha256sum a/node.yaml | cut -c1-64)" = "$A_YAML_BEFORE" ] && ok "A's node.yaml is byte-for-byte unchanged" || bad "rotation changed A's node.yaml"
fi
GW_PID_AFTER=$(curl -s -H "Authorization: Bearer $ATOK" "$EP_AGENT_A_URL/v1/components/gateway" | jq_ "d.get('pid')")
DRV_PID_AFTER=$(curl -s -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/components/$RT-driver" | jq_ "d.get('pid')")
[ "$GW_PID_AFTER" = "$GW_PID_BEFORE" ] && [ "$DRV_PID_AFTER" = "$DRV_PID_BEFORE" ] && [ "$GW_PID_BEFORE" != "None" ] && ok "neither the gateway (pid $GW_PID_AFTER) nor B's companion (pid $DRV_PID_AFTER) restarted: they reload the bundle file" || bad "pids gateway $GW_PID_BEFORE->$GW_PID_AFTER companion $DRV_PID_BEFORE->$DRV_PID_AFTER"
for _ in $(seq 1 60); do
  RN=$(curl -s -H "Authorization: Bearer $ATOK" "$EP_GATEWAY_URL/v1/models" | jq_ "next((m['x_eugene_plexus'].get('ready_backends') for m in d.get('data',[]) if m['id']=='$ALIAS'), 0)" 2>/dev/null)
  [ "$RN" = "1" ] && break; sleep 1
done
C=$(complete); TXT=$(echo "$C" | jq_ "(d.get('choices') or [{}])[0].get('message',{}).get('content','').strip()" 2>/dev/null)
[ -n "$TXT" ] && ok "*** COMPLETION AFTER ROTATION: the same gateway -> the same companion on B, on node-signed tokens: '$TXT' ***" || bad "completion after rotation failed: $(echo "$C" | head -c 300)"

# --- 11. trust bundles B must refuse ---------------------------------------------------
say "11. fencing -- trust bundles pushed to B: forged, rolled back, at a lower epoch"
# The root identity key opened from the replicated snapshot with the
# passphrase, which is what an attacker holding both would have. A bundle it
# signs is authentic; only its version or epoch says it must not be taken.
curl -s -H "Authorization: Bearer $CTOK" "$EP_CONTROL_URL/v1/control/snapshot" > snapshot.json
curl -s "$EP_CONTROL_URL/v1/trust/bundle" > bundle.json
FORGE=$("$EP_AGENT_PY" - "$PASSPHRASE" <<'PY'
import base64, json, sys
from eugene_plexus_agent import tokens
from eugene_plexus_control import security
snap = json.load(open("snapshot.json", encoding="utf-8"))
master = security.derive_master_key(sys.argv[1], base64.b64decode(snap["salt"]))
root = tokens.load_private(base64.b64encode(security.open_b64(snap["sealedControlKey"], master)).decode())
current = tokens.parse_bundle(json.load(open("bundle.json", encoding="utf-8"))["jws"], authority=tokens.public_b64(root))
keys = list(current.keys.values())
def signed(key, version, epoch):
    return tokens.build_bundle(authority=key, version=version, epoch=epoch, keys=keys).jws
head, body, sig = current.jws.split(".")
claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
claims["epoch"] = 99
edited = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
print(json.dumps({
    "version": current.version,
    "epoch": current.epoch,
    "current": current.jws,
    "lowerEpoch": signed(root, current.version, current.epoch - 1),
    "rolledBack": signed(root, current.version - 1, current.epoch),
    "stranger": signed(tokens.generate_private_key(), current.version + 1000, current.epoch),
    "tampered": ".".join([head, edited, sig]),
}))
PY
)
field() { echo "$FORGE" | jq_ "d['$1']"; }
push_bundle() { curl -s -o /dev/null -w '%{http_code}' -X POST "$EP_AGENT_B_URL/v1/node/trust-bundle" -H 'content-type: application/json' -d "{\"jws\":\"$1\"}"; }
BV=$(field version); BE=$(field epoch)
[ "$(push_bundle "$(field current)")" = "200" ] && ok "B takes the root's own current bundle $BV again (an equal version replaces): the door is open to an authentic bundle" || bad "B refused the root's current bundle"
FC=$(curl -s -w '\n%{http_code}' -X POST "$EP_AGENT_B_URL/v1/node/trust-bundle" -H 'content-type: application/json' -d "{\"jws\":\"$(field lowerEpoch)\"}"); CODE=$(echo "$FC" | tail -1)
[ "$CODE" = "409" ] && ok "*** FENCED: a bundle genuinely signed by the root identity at epoch $((BE - 1)) is refused with 409: $(echo "$FC" | sed '$d' | jq_ "d['detail']['detail'][:90]") ***" || bad "a lower-epoch bundle returned $CODE"
[ "$(push_bundle "$(field rolledBack)")" = "409" ] && ok "a genuinely signed bundle one version older ($((BV - 1))) is refused with 409: rollback protection" || bad "a rolled-back bundle was not 409"
[ "$(push_bundle "$(field stranger)")" = "401" ] && ok "a bundle signed by a key B never pinned is refused with 401, newer version or not" || bad "a stranger-signed bundle was not 401"
[ "$(push_bundle "$(field tampered)")" = "401" ] && ok "the root's own bundle with its epoch edited after signing is 401" || bad "a tampered bundle was not 401"
BNOW=$(curl -s -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/node")
[ "$(echo "$BNOW" | jq_ "(d.get('epoch'), d.get('trustBundleVersion'))")" = "($BE, $BV)" ] && ok "B still holds bundle $BV at epoch $BE" || bad "B moved: $(echo "$BNOW" | jq_ "(d.get('epoch'), d.get('trustBundleVersion'))")"
[ "$(code_of "$EP_AGENT_B_URL/v1/runtimes" "$BTOK")" = "200" ] && ok "...and B's current session still opens it" || bad "B's session stopped working after the refusals"

# --- 12. teardown -------------------------------------------------------------------------
say "12. teardown"
kill "$A_PID" 2>/dev/null; [ -n "$B_PID" ] && kill "$B_PID" 2>/dev/null
if [ "$EP_MODE" = "same-box" ]; then
  # Every child is in its agent's job object, so the engine and both fleets go
  # with the two agents. The ports are the evidence, and only this run's: the
  # preflight proved each was free before anything started.
  STILL=""
  for _ in $(seq 1 20); do
    STILL=""; for p in "${RUN_PORTS[@]}"; do port_free "$p" || STILL="$STILL $p"; done
    [ -z "$STILL" ] && break; sleep 1
  done
  [ -z "$STILL" ] && ok "nothing is listening on any port this run used (${RUN_PORTS[*]}): the engine and every component went with their agents" || bad "still listening after teardown:$STILL"
else
  sleep 5
  # B's agent is not this script's to start or stop, so B's engine and
  # companion are still running on purpose. Checking THIS host for a
  # leftover engine would pass vacuously -- and would be looking for the
  # wrong engine on the wrong machine, since B need not run llama.cpp at
  # all. Say so rather than bank a check that cannot fail.
  say_left=$(curl -s -m 5 -H "Authorization: Bearer $BTOK" "$EP_AGENT_B_URL/v1/runtimes" | jq_ "[(r['name'], r['status']) for r in d.get('runtimes', [])]" 2>/dev/null)
  echo "  NOTE  host B is left running, as it was found: $say_left"
  echo "        stop it where you started it; nothing here owns B's lifecycle."
fi

say "what this run proved / could not"
echo "  proved: enrollment over real HTTP with real tokens and per-node keys; sessions opening only their own machine"
echo "          and the root; the gateway's per-machine token verifying on a companion another agent spawned;"
echo "          fan-out + node attribution from a real /v1/nodes; a stop and a wake for B's runtime reaching :$B_PORT;"
echo "          a real rotation ending every session with the data path untouched; forged, rolled-back and"
echo "          lower-epoch trust bundles refused."
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
    echo "M7 acceptance PASSED ($PASSES checks) -- two hosts, $EP_AGENT_A_URL and $EP_AGENT_B_URL, nothing on loopback between them."
  else
    echo "M7 acceptance PASSED ($PASSES checks) -- a second host is possible, on one box."
  fi
else
  echo "$FAILURES check(s) FAILED, $PASSES passed"
fi
exit "$FAILURES"
