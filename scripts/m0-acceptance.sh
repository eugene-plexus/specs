#!/usr/bin/env bash
#
# M0 acceptance: the whole chain, four processes, nothing simulated.
#
#   watchdog  ->  spawns  ->  gateway
#             ->  spawns  ->  inference-driver
#             ->  spawns  ->  llama-server (a real engine binary)
#
# and then one chat completion travelling gateway -> driver -> engine.
#
# Both existing end-to-end tests stub the other side: the watchdog's
# test_runtime_end_to_end.py supervises a Python stand-in that speaks
# llama-server's /health contract, and the gateway's routes its OpenAI
# surface at a fake driver. Each proves its own half. This proves they
# fit together, which is the one thing neither can.
#
# It is a script and not a pytest because it needs a multi-gigabyte model
# and a platform-specific engine binary, and because a green CI run that
# silently skipped both would be worse than no test at all.
#
# Usage:
#   scripts/m0-acceptance.sh
#
# Configure via environment (all have defaults that suit no one but the
# machine this was written on — set them):
#
#   EP_ROOT          parent directory holding the component clones
#   EP_WATCHDOG_PY   python that has watchdog + gateway + driver installed
#                    (the watchdog's venv IS the runtime venv: it spawns
#                    every component with its own sys.executable, so all
#                    three must be importable from this one interpreter)
#   EP_LLAMA_SERVER  path to llama-server(.exe)
#   EP_MODEL         path to a .gguf chat model
#   EP_WORKDIR       scratch directory for the throwaway install
#
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
EP_WATCHDOG_PY="${EP_WATCHDOG_PY:-$EP_ROOT/watchdog/.venv/Scripts/python.exe}"
EP_LLAMA_SERVER="${EP_LLAMA_SERVER:-C:/Users/troyc/OneDrive/Desktop/llamacpp/llama-server.exe}"
EP_MODEL="${EP_MODEL:-C:/Users/troyc/.lmstudio/models/lmstudio-community/Qwen3.6-27B-GGUF/Qwen3.6-27B-Q4_K_M.gguf}"
EP_WORKDIR="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-m0-acceptance}"

WATCHDOG_PORT=8079
GATEWAY_PORT=8080
DRIVER_PORT=8081
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
# Small JSON reader. `python` here is whatever is on PATH; it only parses
# the responses, and never runs any component.
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }

# --- preflight -------------------------------------------------------------
say "preflight"
[ -f "$EP_WATCHDOG_PY" ] || bad "watchdog venv python not found at $EP_WATCHDOG_PY"
[ -f "$EP_LLAMA_SERVER" ] || bad "llama-server not found at $EP_LLAMA_SERVER"
[ -f "$EP_MODEL" ] || bad "model not found at $EP_MODEL"
if [ "$FAILURES" -ne 0 ]; then
  printf '\nSet EP_WATCHDOG_PY / EP_LLAMA_SERVER / EP_MODEL and retry.\n'
  printf 'Engine acquisition is M1 — until then the binary is the operator'"'"'s to supply.\n'
  exit 1
fi
if ! "$EP_WATCHDOG_PY" -c "import eugene_plexus_watchdog, eugene_plexus_gateway, eugene_plexus_inference_driver" 2>/dev/null; then
  bad "watchdog, gateway and inference-driver must all be importable from $EP_WATCHDOG_PY"
  printf '  (pip install -e %s/gateway -e %s/inference-driver into it)\n' "$EP_ROOT" "$EP_ROOT"
  exit 1
fi
ok "engine binary, model and all three components present"

# --- a throwaway install ---------------------------------------------------
say "a throwaway install in $EP_WORKDIR"
rm -rf "$EP_WORKDIR"
mkdir -p "$EP_WORKDIR"
cd "$EP_WORKDIR" || exit 1

# Backslashes, because these land in argv for a Windows binary. On a
# POSIX host they pass through unchanged.
win_path() { printf '%s' "$1" | sed 's|/|\\|g'; }

cat > watchdog.yaml <<YAML
firstRunComplete: true
components:
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

# The driver fronts the runtime by pointing at its url. That is the whole
# integration — configuration, not code. No API key: a local engine has
# no auth, and requiring one to reach a model on your own machine was the
# defect this run first caught.
cat > driver.yaml <<YAML
provider: openai_compat_custom
baseUrl: http://127.0.0.1:$ENGINE_PORT
modelId: $MODEL_ALIAS
YAML
ok "topology, gateway config and driver config written"

# --- 1. start the supervisor ----------------------------------------------
say "1. start the supervisor — it spawns everything else"
EUGENE_PLEXUS_WATCHDOG_CONFIG_FILE=watchdog.yaml "$EP_WATCHDOG_PY" \
  -m eugene_plexus_watchdog > watchdog-run.log 2>&1 &
WD_PID=$!
trap 'kill "$WD_PID" 2>/dev/null' EXIT

for _ in $(seq 1 60); do
  curl -sf -m 2 "http://127.0.0.1:$WATCHDOG_PORT/healthz" >/dev/null 2>&1 && break
  sleep 1
done
if curl -sf -m 2 "http://127.0.0.1:$WATCHDOG_PORT/healthz" >/dev/null; then
  ok "watchdog answering on :$WATCHDOG_PORT"
else
  bad "watchdog never came up"
  tail -40 watchdog-run.log
  exit 1
fi

# --- 2. auth ---------------------------------------------------------------
say "2. initialize auth — what the wizard's Start button does"
TOK=$(curl -s -X POST "http://127.0.0.1:$WATCHDOG_PORT/v1/auth/initialize" \
  -H 'content-type: application/json' \
  -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
if [ -n "$TOK" ]; then
  ok "operator session issued; children get service tokens at spawn"
else
  bad "no session token"
  exit 1
fi
AUTH=(-H "Authorization: Bearer $TOK")

# --- 3. the components -----------------------------------------------------
say "3. the gateway and the driver, spawned by the supervisor"
for _ in $(seq 1 60); do
  S=$(curl -s -m 3 "${AUTH[@]}" "http://127.0.0.1:$WATCHDOG_PORT/v1/components" 2>/dev/null |
    jq_ "' '.join(sorted(c['name']+'='+c['status'] for c in d['components']))" 2>/dev/null)
  case "$S" in *"gateway=running"*"$DRIVER_NAME=running"*) break ;; esac
  sleep 1
done
echo "  components: $S"
case "$S" in *"gateway=running"*) ok "gateway running" ;; *) bad "gateway not running" ;; esac
case "$S" in *"$DRIVER_NAME=running"*) ok "inference-driver running" ;; *) bad "driver not running" ;; esac

# --- 4. the engine ---------------------------------------------------------
say "4. the engine reaches ready — real binary, real /health probe"
for _ in $(seq 1 600); do
  R=$(curl -s -m 3 "${AUTH[@]}" "http://127.0.0.1:$WATCHDOG_PORT/v1/runtimes")
  ST=$(echo "$R" | jq_ "d['runtimes'][0]['status']" 2>/dev/null)
  [ "$ST" = "ready" ] && break
  [ "$ST" = "crashed" ] && break
  sleep 1
done
echo "  status: $ST"
if [ "$ST" = "ready" ]; then
  ok "runtime '$RUNTIME_NAME' is ready"
else
  bad "runtime never became ready (status=$ST)"
  echo "$R" | jq_ "d['runtimes'][0].get('lastError')" 2>/dev/null
  tail -30 watchdog-run.log
fi
echo "$R" | PYTHONUTF8=1 python -c "
import sys, json
r = json.load(sys.stdin)['runtimes'][0]
print('  pid', r.get('pid'), '| engine build', r.get('engineVersion'), '| url', r.get('url'))
print('  capabilities, read back from the loaded engine:', r.get('capabilities'))
print('  argv:', ' '.join(r.get('argv') or []))
" 2>/dev/null
PID=$(echo "$R" | jq_ "d['runtimes'][0].get('pid')" 2>/dev/null)
if [ -n "$PID" ] && [ "$PID" != "None" ]; then
  ok "a real OS process (pid $PID)"
else
  bad "no pid — nothing was actually spawned"
fi

# --- 5. routing ------------------------------------------------------------
say "5. the gateway's routing table, derived from the topology"
M=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$GATEWAY_PORT/v1/models")
echo "$M" | PYTHONUTF8=1 python -m json.tool 2>/dev/null | sed 's/^/  /'
MID=$(echo "$M" | jq_ "d['data'][0]['id'] if d.get('data') else ''" 2>/dev/null)
if [ "$MID" = "$MODEL_ALIAS" ]; then
  ok "routable as '$MID' — nothing configured that; it came from the topology"
else
  bad "expected $MODEL_ALIAS, got '$MID'"
fi

# Context comes from capabilities the engine only reports once loaded,
# and the routing table refreshes on a timer (routingRefreshSeconds).
# The gateway normally finishes its first refresh BEFORE a large quant
# finishes loading, so this is eventually-true, not immediately-true.
for _ in $(seq 1 25); do
  M=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$GATEWAY_PORT/v1/models")
  CTX=$(echo "$M" | jq_ "d['data'][0]['x_eugene_plexus'].get('context_length')" 2>/dev/null)
  [ -n "$CTX" ] && [ "$CTX" != "None" ] && break
  sleep 1
done
if [ -n "$CTX" ] && [ "$CTX" != "None" ]; then
  ok "context window ($CTX) reported, sourced from the runtime"
else
  bad "no context_length after a full refresh interval"
fi

# --- 6. the completion -----------------------------------------------------
say "6. one chat completion: gateway -> driver -> llama-server"
START=$(date +%s)
C=$(curl -s -m 900 -X POST "http://127.0.0.1:$GATEWAY_PORT/v1/chat/completions" "${AUTH[@]}" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL_ALIAS\",\"messages\":[{\"role\":\"user\",\"content\":\"What is 17 times 23? Answer with just the number.\"}],\"max_tokens\":1024,\"temperature\":0.1}")
echo "$C" | PYTHONUTF8=1 python -m json.tool 2>/dev/null | sed 's/^/  /'
TEXT=$(echo "$C" | jq_ "d['choices'][0]['message']['content'].strip() if d.get('choices') else ''" 2>/dev/null)
if [ -n "$TEXT" ]; then
  ok "the model produced text: '$TEXT'"
else
  bad "empty completion"
fi
DRV=$(echo "$C" | jq_ "(d.get('x_eugene_plexus') or {}).get('driver')" 2>/dev/null)
RT=$(echo "$C" | jq_ "(d.get('x_eugene_plexus') or {}).get('runtime')" 2>/dev/null)
[ "$DRV" = "$DRIVER_NAME" ] && ok "attributed to driver '$DRV'" || bad "driver attribution: $DRV"
[ "$RT" = "$RUNTIME_NAME" ] && ok "attributed to runtime '$RT'" || bad "runtime attribution: $RT"
echo "  wall clock: $(($(date +%s) - START))s"

# --- 7. an unmodified OpenAI client ---------------------------------------
# "OpenAI-compatible" is worth nothing unless an SDK nobody patched can
# point base_url at us and work. Anything else is a private protocol that
# happens to resemble one.
say "7. an unmodified OpenAI SDK against the same endpoint"
SDK_PY="$EP_WORKDIR/.sdkcheck/Scripts/python.exe"
[ -x "$SDK_PY" ] || SDK_PY="$EP_WORKDIR/.sdkcheck/bin/python"
if [ ! -x "$SDK_PY" ]; then
  python -m venv "$EP_WORKDIR/.sdkcheck" >/dev/null 2>&1
  [ -x "$EP_WORKDIR/.sdkcheck/Scripts/python.exe" ] && SDK_PY="$EP_WORKDIR/.sdkcheck/Scripts/python.exe"
  [ -x "$EP_WORKDIR/.sdkcheck/bin/python" ] && SDK_PY="$EP_WORKDIR/.sdkcheck/bin/python"
  "$SDK_PY" -m pip install -q openai >/dev/null 2>&1
fi
if [ -x "$SDK_PY" ] && "$SDK_PY" -c "import openai" 2>/dev/null; then
  OUT=$("$SDK_PY" - "$TOK" "$GATEWAY_PORT" "$MODEL_ALIAS" <<'PY'
import sys
from openai import OpenAI

token, port, model = sys.argv[1], sys.argv[2], sys.argv[3]
client = OpenAI(base_url=f"http://127.0.0.1:{port}/v1", api_key=token)
print("models:", [m.id for m in client.models.list()])
reply = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "Say OK and nothing else."}],
    max_tokens=512,
)
print("reply:", repr(reply.choices[0].message.content))
PY
  )
  echo "$OUT" | sed 's/^/  /'
  if echo "$OUT" | grep -q "$MODEL_ALIAS"; then
    ok "the OpenAI SDK listed and called our model without modification"
  else
    bad "OpenAI SDK round trip failed"
  fi
else
  echo "  could not build a venv with the openai package — skipped"
fi

# --- 8. teardown -----------------------------------------------------------
say "8. teardown — does the engine die with the supervisor?"
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
  echo "M0 acceptance PASSED — four processes, one real completion."
else
  echo "$FAILURES check(s) FAILED"
fi
echo "install left at $EP_WORKDIR (watchdog-run.log has every child's output)"
exit "$FAILURES"
