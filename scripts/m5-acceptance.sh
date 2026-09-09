#!/usr/bin/env bash
#
# M5 acceptance: kill the control root, and the inference keeps serving.
#
#   agent  ->  spawns  ->  control        (the trust root, port 8083)
#             ->  spawns  ->  gateway
#             ->  spawns  ->  inference-driver
#             ->  spawns  ->  llama-server (a real engine binary)
#
# and then, with a real chat completion already flowing:
#
#   kill the control root  ->  management stops  ->  inference continues
#
# **This is the second required deliverable of M5**, and it is here
# rather than in the control repo because it cannot honestly live there.
# A version that stood up stubs for the gateway, the driver and the
# engine would assert that our stubs do not call us. This one asserts
# that a real model on a real GPU keeps answering when the process
# holding the install's trust root is gone.
#
# The design says the surviving data path "is currently an accident, not
# a designed property", and that this test is what turns it into a
# guarantee. So the useful failure mode is the interesting one: if
# somebody later routes a request through the control root, this run goes
# red and the guarantee is what caught it.
#
# What it deliberately does NOT test: a second host. Enrollment,
# revocation-as-rotation and per-node sealing are exercised by the
# control repo's own suite against fake agents, because "one node answers
# and the other does not" is the case that matters and a single dev box
# cannot arrange it. Multi-host is still unverified on real hardware.
#
# Usage:
#   scripts/m5-acceptance.sh
#
# Configure via environment (defaults suit the machine this was written
# on and nobody else — set them):
#
#   EP_ROOT          parent directory holding the component clones
#   EP_AGENT_PY      python with agent + control + gateway + driver
#                    installed (the agent spawns every component with its
#                    own sys.executable, so all four must import from it)
#   EP_LLAMA_SERVER  path to llama-server(.exe)
#   EP_MODEL         path to a .gguf chat model
#   EP_WORKDIR       scratch directory for the throwaway install
#
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
EP_AGENT_PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
EP_LLAMA_SERVER="${EP_LLAMA_SERVER:-C:/Users/troyc/OneDrive/Desktop/llamacpp/llama-server.exe}"
EP_MODEL="${EP_MODEL:-C:/Users/troyc/.lmstudio/models/lmstudio-community/Qwen3.6-27B-GGUF/Qwen3.6-27B-Q4_K_M.gguf}"
EP_WORKDIR="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-m5-acceptance}"

AGENT_PORT=8079
GATEWAY_PORT=8080
DRIVER_PORT=8081
CONTROL_PORT=8083
ENGINE_PORT=8090
MODEL_ALIAS=qwen3.6-27b
RUNTIME_NAME=qwen3-27b
DRIVER_NAME=qwen-driver

# Generated, not committed: a literal in the repo is a secret-scanner
# finding waiting to happen, and this install is deleted at the end.
PASSPHRASE="acceptance-$(date +%s)-$$"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() {
  printf '  FAIL  %s\n' "$*"
  FAILURES=$((FAILURES + 1))
}
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }

# --- preflight -------------------------------------------------------------
say "preflight"
[ -f "$EP_AGENT_PY" ] || bad "agent venv python not found at $EP_AGENT_PY"
[ -f "$EP_LLAMA_SERVER" ] || bad "llama-server not found at $EP_LLAMA_SERVER"
[ -f "$EP_MODEL" ] || bad "model not found at $EP_MODEL"
if [ "$FAILURES" -ne 0 ]; then
  printf '\nSet EP_AGENT_PY / EP_LLAMA_SERVER / EP_MODEL and retry.\n'
  exit 1
fi
if ! "$EP_AGENT_PY" -c "import eugene_plexus_agent, eugene_plexus_control, eugene_plexus_gateway, eugene_plexus_inference_driver" 2>/dev/null; then
  bad "agent, control, gateway and inference-driver must all import from $EP_AGENT_PY"
  printf '  (pip install -e %s/control -e %s/gateway -e %s/inference-driver into it)\n' \
    "$EP_ROOT" "$EP_ROOT" "$EP_ROOT"
  exit 1
fi
ok "engine binary, model and all four components present"

# --- a throwaway install ---------------------------------------------------
say "a throwaway install in $EP_WORKDIR"
rm -rf "$EP_WORKDIR"
mkdir -p "$EP_WORKDIR"
cd "$EP_WORKDIR" || exit 1

# Backslashes, because these land in argv for a Windows binary. On a
# POSIX host they pass through unchanged.
win_path() { printf '%s' "$1" | sed 's|/|\\|g'; }

# The control root is just another component in the agent's topology.
# That is the M5 split working as designed rather than a special case:
# one supervisor implementation per host, and the thing holding the
# trust root is supervised like anything else.
cat > agent.yaml <<YAML
firstRunComplete: true
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
  - name: $DRIVER_NAME
    kind: inference-driver
    url: http://127.0.0.1:$DRIVER_PORT
    spawn:
      configFile: driver.yaml
runtimes:
  - name: $RUNTIME_NAME
    engine: llama_cpp
    modelPath: $(win_path "$EP_MODEL")
    modelAlias: $MODEL_ALIAS
    host: 127.0.0.1
    port: $ENGINE_PORT
    autoStart: true
    binary: $(win_path "$EP_LLAMA_SERVER")
    flags:
      contextSize: 4096
      gpuLayers: 99
      parallelSlots: 1
YAML

echo "logLevel: INFO" > gateway.yaml
echo "logLevel: INFO" > control.yaml

cat > driver.yaml <<YAML
provider: openai_compat_custom
baseUrl: http://127.0.0.1:$ENGINE_PORT
modelId: $MODEL_ALIAS
YAML
ok "topology written — control, gateway, driver, one runtime"

# --- 1. start the supervisor ----------------------------------------------
say "1. start the supervisor — it spawns the control root too"
EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml "$EP_AGENT_PY" \
  -m eugene_plexus_agent > agent-run.log 2>&1 &
WD_PID=$!
trap 'kill "$WD_PID" 2>/dev/null' EXIT

for _ in $(seq 1 60); do
  curl -sf -m 2 "http://127.0.0.1:$AGENT_PORT/healthz" >/dev/null 2>&1 && break
  sleep 1
done
if curl -sf -m 2 "http://127.0.0.1:$AGENT_PORT/healthz" >/dev/null; then
  ok "agent answering on :$AGENT_PORT"
else
  bad "agent never came up"
  tail -40 agent-run.log
  exit 1
fi

# --- 2. the control root ---------------------------------------------------
say "2. the control root, spawned and holding the trust root"
for _ in $(seq 1 60); do
  curl -sf -m 2 "http://127.0.0.1:$CONTROL_PORT/healthz" >/dev/null 2>&1 && break
  sleep 1
done
CH=$(curl -s -m 3 "http://127.0.0.1:$CONTROL_PORT/healthz")
if [ -n "$CH" ]; then
  ok "control root answering on :$CONTROL_PORT"
  echo "  $CH" | head -c 400; echo
else
  bad "control root never came up"
  tail -40 agent-run.log
  exit 1
fi

AS=$(curl -s -m 3 "http://127.0.0.1:$CONTROL_PORT/v1/auth/status" | jq_ "d['initialized']")
[ "$AS" = "False" ] && ok "reports uninitialized before setup" || bad "auth status: $AS"

say "3. initialize the install AT THE CONTROL ROOT"
INIT=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  "http://127.0.0.1:$CONTROL_PORT/v1/auth/initialize" \
  -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}")
[ "$INIT" = "204" ] && ok "passphrase set (204)" || bad "initialize returned $INIT"

CTOK=$(curl -s -X POST "http://127.0.0.1:$CONTROL_PORT/v1/auth/login" \
  -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('token','')")
if [ -n "$CTOK" ]; then
  ok "operator session issued by the control root"
else
  bad "no session token from the control root"
  exit 1
fi
CAUTH=(-H "Authorization: Bearer $CTOK")

ST=$(curl -s "${CAUTH[@]}" "http://127.0.0.1:$CONTROL_PORT/v1/control/status")
echo "  $ST"
ROLE=$(echo "$ST" | jq_ "d['role']")
EPOCH=$(echo "$ST" | jq_ "d['epoch']")
[ "$ROLE" = "control" ] && ok "role=control, epoch=$EPOCH" || bad "role: $ROLE"

# The install identity has to be durable before anything else is worth
# checking — it is what a standby would be promoted from.
SNAP=$(curl -s "${CAUTH[@]}" "http://127.0.0.1:$CONTROL_PORT/v1/control/snapshot")
for field in salt passphraseVerifier sealedSigningKey sealedControlKey controlPublicKey sealedRecoveryKey; do
  V=$(echo "$SNAP" | jq_ "bool(d.get('$field'))")
  [ "$V" = "True" ] && ok "snapshot carries $field" || bad "snapshot is missing $field"
done

# --- 4. the rest of the fleet ---------------------------------------------
# The agent still holds the auth trio for the other components in M5's
# first half, so this is the agent's session, not the control root's.
say "4. the gateway and the driver, spawned by the same supervisor"
ATOK=$(curl -s -X POST "http://127.0.0.1:$AGENT_PORT/v1/auth/initialize" \
  -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
if [ -z "$ATOK" ]; then
  ATOK=$(curl -s -X POST "http://127.0.0.1:$AGENT_PORT/v1/auth/login" \
    -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
fi
AUTH=(-H "Authorization: Bearer $ATOK")

for _ in $(seq 1 90); do
  S=$(curl -s -m 3 "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/components" 2>/dev/null |
    jq_ "' '.join(sorted(c['name']+'='+c['status'] for c in d['components']))" 2>/dev/null)
  case "$S" in *"control=running"*"gateway=running"*"$DRIVER_NAME=running"*) break ;; esac
  sleep 1
done
echo "  components: $S"
case "$S" in *"control=running"*) ok "control running under supervision" ;; *) bad "control not running" ;; esac
case "$S" in *"gateway=running"*) ok "gateway running" ;; *) bad "gateway not running" ;; esac
case "$S" in *"$DRIVER_NAME=running"*) ok "inference-driver running" ;; *) bad "driver not running" ;; esac

# --- 5. the engine ---------------------------------------------------------
say "5. the engine reaches ready — real binary, real /health probe"
for _ in $(seq 1 900); do
  R=$(curl -s -m 3 "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes")
  RST=$(echo "$R" | jq_ "d['runtimes'][0]['status']" 2>/dev/null)
  [ "$RST" = "ready" ] && break
  [ "$RST" = "crashed" ] && break
  sleep 1
done
echo "  status: $RST"
if [ "$RST" = "ready" ]; then
  ok "runtime '$RUNTIME_NAME' is ready"
else
  bad "runtime never became ready (status=$RST)"
  echo "$R" | jq_ "d['runtimes'][0].get('lastError')" 2>/dev/null
  tail -30 agent-run.log
  exit 1
fi

# --- 6. a completion, with the control root alive -------------------------
say "6. a chat completion with the control root ALIVE — the baseline"
complete() {
  curl -s -m 900 -X POST "http://127.0.0.1:$GATEWAY_PORT/v1/chat/completions" "${AUTH[@]}" \
    -H 'content-type: application/json' \
    -d "{\"model\":\"$MODEL_ALIAS\",\"messages\":[{\"role\":\"user\",\"content\":\"$1\"}],\"max_tokens\":1024,\"temperature\":0.1}"
}
C=$(complete "What is 17 times 23? Answer with just the number.")
TEXT=$(echo "$C" | jq_ "d['choices'][0]['message']['content'].strip() if d.get('choices') else ''" 2>/dev/null)
if [ -n "$TEXT" ]; then
  ok "baseline completion succeeded: '$TEXT'"
else
  bad "baseline completion failed — nothing after this is meaningful"
  echo "$C" | head -c 600; echo
  exit 1
fi

# --- 7. KILL THE CONTROL ROOT ---------------------------------------------
# The whole point of the run. Killed rather than stopped cleanly, and
# through the OS rather than through the API, because "the box holding
# the control root died" is the case the design is about.
say "7. KILL the control root"
CPID=$(curl -s -m 3 "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/components" |
  jq_ "next((c.get('pid') for c in d['components'] if c['name']=='control'), None)")
echo "  control root pid: $CPID"
if [ -z "$CPID" ] || [ "$CPID" = "None" ]; then
  bad "no pid for the control root — cannot kill what was never spawned"
  exit 1
fi

# The supervisor would respawn it, which would defeat the test. Take it
# out of the topology first, so "down" stays down for the duration.
DEL=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "${AUTH[@]}" \
  "http://127.0.0.1:$AGENT_PORT/v1/components/control")
echo "  removed from topology (HTTP $DEL) so the supervisor does not respawn it"

if command -v powershell.exe >/dev/null 2>&1; then
  powershell.exe -NoProfile -Command "Stop-Process -Id $CPID -Force -ErrorAction SilentlyContinue" >/dev/null 2>&1
else
  kill -9 "$CPID" 2>/dev/null
fi

for _ in $(seq 1 30); do
  curl -sf -m 2 "http://127.0.0.1:$CONTROL_PORT/healthz" >/dev/null 2>&1 || break
  sleep 1
done
if curl -sf -m 2 "http://127.0.0.1:$CONTROL_PORT/healthz" >/dev/null 2>&1; then
  bad "the control root is still answering — it was not actually killed"
  exit 1
fi
ok "the control root is gone (nothing answers on :$CONTROL_PORT)"

# --- 8. THE ASSERTION ------------------------------------------------------
say "8. management is down. Is inference?"
MG=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "${CAUTH[@]}" \
  "http://127.0.0.1:$CONTROL_PORT/v1/nodes" 2>/dev/null)
if [ "$MG" = "000" ] || [ -z "$MG" ]; then
  ok "management is unavailable, as expected — no node list, no enrollment, no config edits"
else
  bad "the control root answered $MG after being killed"
fi

START=$(date +%s)
C2=$(complete "What is 12 times 12? Answer with just the number.")
TEXT2=$(echo "$C2" | jq_ "d['choices'][0]['message']['content'].strip() if d.get('choices') else ''" 2>/dev/null)
echo "$C2" | PYTHONUTF8=1 python -m json.tool 2>/dev/null | sed 's/^/  /' | head -30
if [ -n "$TEXT2" ]; then
  ok "*** A CHAT COMPLETION SUCCEEDED WITH THE CONTROL ROOT DEAD: '$TEXT2' ***"
else
  bad "*** inference stopped when the control root died — the guarantee is broken ***"
fi
echo "  wall clock: $(($(date +%s) - START))s"

DRV=$(echo "$C2" | jq_ "(d.get('x_eugene_plexus') or {}).get('driver')" 2>/dev/null)
RT=$(echo "$C2" | jq_ "(d.get('x_eugene_plexus') or {}).get('runtime')" 2>/dev/null)
[ "$DRV" = "$DRIVER_NAME" ] && ok "still attributed to driver '$DRV'" || bad "driver attribution: $DRV"
[ "$RT" = "$RUNTIME_NAME" ] && ok "still attributed to runtime '$RT'" || bad "runtime attribution: $RT"

# The routing table is the thing that would quietly depend on the control
# root if anyone ever wired it that way. Checked separately from the
# completion, because a stale-but-working cache and a genuinely
# independent routing path look identical from one request.
M=$(curl -s -m 10 "${AUTH[@]}" "http://127.0.0.1:$GATEWAY_PORT/v1/models")
MID=$(echo "$M" | jq_ "d['data'][0]['id'] if d.get('data') else ''" 2>/dev/null)
[ "$MID" = "$MODEL_ALIAS" ] && ok "the gateway still routes '$MID' without a control root" \
  || bad "routing table lost the model when the control root died (got '$MID')"

# And the engine is still supervised, by the agent, locally. Supervision
# is per-host and does not pass through the control root either.
RS=$(curl -s -m 5 "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes" |
  jq_ "d['runtimes'][0]['status']" 2>/dev/null)
[ "$RS" = "ready" ] && ok "the agent is still supervising the engine (status=$RS)" \
  || bad "runtime status after the control root died: $RS"

# --- 9. teardown -----------------------------------------------------------
say "9. teardown"
kill "$WD_PID" 2>/dev/null
for _ in $(seq 1 20); do
  kill -0 "$WD_PID" 2>/dev/null || break
  sleep 1
done
sleep 3
if command -v powershell.exe >/dev/null 2>&1; then
  LEFT=$(powershell.exe -NoProfile -Command \
    "(Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue | Measure-Object).Count" \
    2>/dev/null | tr -d '\r')
else
  LEFT=$(pgrep -c llama-server 2>/dev/null || echo 0)
fi
if [ "$LEFT" = "0" ]; then
  ok "llama-server exited with the supervisor — no orphaned engine"
else
  bad "$LEFT llama-server process(es) survived the supervisor"
fi

say "result"
if [ "$FAILURES" -eq 0 ]; then
  echo "M5 acceptance PASSED — the control root died and the model kept answering."
  echo "The surviving data path is now a tested guarantee rather than an accident."
else
  echo "$FAILURES check(s) FAILED"
fi
exit "$FAILURES"
