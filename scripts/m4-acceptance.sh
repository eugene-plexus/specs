#!/usr/bin/env bash
#
# M4 acceptance: a second engine, and a driver that follows it by name.
#
#   agent  ->  spawns  ->  gateway
#             ->  spawns  ->  inference-driver   (runtimeName, no baseUrl)
#             ->  spawns  ->  vllm serve         (declared at runtime, not in the topology)
#
# **THIS SCRIPT HAS NEVER BEEN RUN.** It was written 2026-09-09 on a
# Windows box where vLLM cannot run (no Windows build; WSL not installed),
# alongside an adapter verified only against upstream source at v0.29.0
# and against fixtures. It exists so the first Linux session — the WSL2
# run that also answers M5's multi-host question — starts from a script
# rather than from a blank terminal. Expect it to find defects; every
# prior milestone's live run did. Where it does, fix the script and the
# adapter together and record what was learned in the design doc's §8.
#
# The three things the fixtures could not prove, and this run can:
#
#   1. §2's rule. While vLLM loads, its port is bound but not listening,
#      so a connection is REFUSED — and the runtime must read `loading`,
#      not `starting` and not `crashed`, because the supervisor holds the
#      pid. Stage 7 probes the port itself while the agent says `loading`
#      and records what the socket did. "Refused, not accepted-and-hung"
#      is the one claim the design marked as needing confirmation.
#   2. The wall clock. STARTUP_BUDGET_SECONDS is 600, a design estimate.
#      Stage 7 records how long `loading` actually lasted for this model
#      with `enforceEager: true` (the short path) so the budget can be set
#      from a number rather than a guess. Run it again without
#      `enforceEager` for the long path if there is time.
#   3. That the twelve curated flag names are accepted by 0.29.0's CLI,
#      that `/health` 200 means servable, and that `/v1/models` carries
#      `max_model_len` back — all read off source, none observed.
#
# Plus the M2 routing gap, closed end to end: the driver is written with
# `runtimeName` and NO `baseUrl`, comes up degraded because the runtime it
# follows does not exist yet (stage 3 — that is the designed behaviour,
# config endpoints reachable), and resolves it on restart after the
# runtime is declared (stage 8). Nobody types a port.
#
# Usage:
#   scripts/m4-acceptance.sh
#
# Configure via environment:
#   EP_ROOT        parent directory holding the component clones
#   EP_AGENT_PY    python with agent + gateway + inference-driver installed
#                  (the agent spawns every component with its own
#                  sys.executable, so all three must import from this one)
#   EP_VLLM_BIN    the `vllm` console script inside the operator's venv
#                  — NOT a python interpreter, NOT a venv directory
#   EP_MODEL_DIR   a local safetensors model directory: config.json plus
#                  *.safetensors. Something small for the first run
#                  (Qwen/Qwen3-0.6B is ~1.2 GB); a real model for the
#                  timing measurement.
#   EP_WORKDIR     scratch directory for the throwaway install
#
set -uo pipefail

EP_ROOT="${EP_ROOT:-$HOME/eugene-plexus}"
EP_AGENT_PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/bin/python}"
EP_VLLM_BIN="${EP_VLLM_BIN:-$HOME/vllm/.venv/bin/vllm}"
EP_MODEL_DIR="${EP_MODEL_DIR:-$HOME/models/Qwen3-0.6B}"
EP_WORKDIR="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-m4-acceptance}"

AGENT_PORT=8079
GATEWAY_PORT=8080
DRIVER_PORT=8081
DRIVER_NAME=vllm-driver

# How long stage 7 waits for `ready`. Generous: this is the measurement.
READY_TIMEOUT_SECONDS=1200

PASSPHRASE="acceptance-$(date +%s)-$$"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() {
  printf '  FAIL  %s\n' "$*"
  FAILURES=$((FAILURES + 1))
}
note() { printf '  NOTE  %s\n' "$*"; }
# JSON helper through the agent's own interpreter, so the script does not
# depend on a system `python` existing.
jq_() { PYTHONUTF8=1 "$EP_AGENT_PY" -c "import sys,json; d=json.load(sys.stdin); print($1)"; }

# --- preflight -------------------------------------------------------------
say "preflight"
[ -f "$EP_AGENT_PY" ] || bad "agent venv python not found at $EP_AGENT_PY"
[ -f "$EP_VLLM_BIN" ] || bad "vllm console script not found at $EP_VLLM_BIN"
[ -f "$EP_MODEL_DIR/config.json" ] || bad "no config.json in $EP_MODEL_DIR — not a safetensors model directory"
ls "$EP_MODEL_DIR"/*.safetensors >/dev/null 2>&1 || bad "no *.safetensors in $EP_MODEL_DIR"
if [ "$FAILURES" -ne 0 ]; then
  printf '\nSet EP_AGENT_PY / EP_VLLM_BIN / EP_MODEL_DIR and retry.\n'
  exit 1
fi
if ! "$EP_AGENT_PY" -c "import eugene_plexus_agent, eugene_plexus_gateway, eugene_plexus_inference_driver" 2>/dev/null; then
  bad "agent, gateway AND inference-driver must import from $EP_AGENT_PY"
  printf '  (pip install -e each into it — the agent venv is the runtime venv)\n'
  exit 1
fi
if ! head -c 2 "$EP_VLLM_BIN" | grep -q '#!'; then
  bad "$EP_VLLM_BIN has no shebang — point EP_VLLM_BIN at the console script, not an interpreter or a directory"
  exit 1
fi
ok "vllm console script, model directory and all three components present"
if command -v nvidia-smi >/dev/null 2>&1; then
  note "nvidia-smi present: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)"
else
  note "no nvidia-smi — expect a CPU-only vLLM, and expect it to be slow"
fi
MODEL_ALIAS=$(basename "$EP_MODEL_DIR")
RUNTIME_NAME=$(echo "$MODEL_ALIAS" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9]\+/-/g; s/^-//; s/-$//' | cut -c1-40)

# --- a throwaway install ---------------------------------------------------
say "a throwaway install in $EP_WORKDIR"
rm -rf "$EP_WORKDIR"
mkdir -p "$EP_WORKDIR"
cd "$EP_WORKDIR" || exit 1

# No `runtimes:` block and no `vllmBinary`: both are set through the API
# below, the way the UI sets them. The driver names the runtime it will
# front BEFORE that runtime exists — the order an operator actually does
# things in when they wire the driver first.
cat > agent.yaml <<YAML
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
YAML

echo "logLevel: INFO" > gateway.yaml

# The M4 shape: a runtime by name, no baseUrl, no port anywhere.
cat > driver.yaml <<YAML
provider: openai_compat_custom
runtimeName: $RUNTIME_NAME
modelId: $MODEL_ALIAS
YAML
ok "topology written — two components, zero runtimes, a driver that names a runtime which does not exist yet"

# --- 1. the supervisor -----------------------------------------------------
say "1. start the supervisor"
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

# --- 2. auth ---------------------------------------------------------------
say "2. initialize auth"
TOK=$(curl -s -X POST "http://127.0.0.1:$AGENT_PORT/v1/auth/initialize" \
  -H 'content-type: application/json' \
  -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
if [ -n "$TOK" ]; then
  ok "operator session issued"
else
  bad "no session token"
  exit 1
fi
AUTH=(-H "Authorization: Bearer $TOK")

# --- 3. components, and a driver that is honestly degraded -----------------
say "3. the gateway and the driver, spawned by the supervisor"
for _ in $(seq 1 60); do
  S=$(curl -s -m 3 "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/components" 2>/dev/null |
    jq_ "' '.join(sorted(c['name']+'='+c['status'] for c in d['components']))" 2>/dev/null)
  case "$S" in *"gateway=running"*"$DRIVER_NAME="*) break ;; esac
  sleep 1
done
echo "  components: $S"
case "$S" in *"gateway=running"*) ok "gateway running" ;; *) bad "gateway not running" ;; esac

# The runtime it follows is not declared yet, so resolution 404s and the
# driver comes up degraded — with the reason on /healthz and its config
# endpoints reachable. That is the design, not a failure of this run.
H=$(curl -s -m 3 "http://127.0.0.1:$DRIVER_PORT/healthz")
HS=$(echo "$H" | jq_ "d['status']" 2>/dev/null)
HE=$(echo "$H" | jq_ "(d.get('details') or {}).get('adapter_error','')" 2>/dev/null)
echo "  driver /healthz: $HS — $HE"
[ "$HS" = "degraded" ] && ok "driver is degraded, because '$RUNTIME_NAME' is not declared yet" \
  || bad "expected the driver degraded before the runtime exists, got $HS"
case "$HE" in *"$RUNTIME_NAME"*"not declared"*) ok "and it names the missing runtime" ;; *) bad "adapter_error does not name the runtime: $HE" ;; esac
CI=$(curl -s -o /dev/null -w '%{http_code}' "${AUTH[@]}" "http://127.0.0.1:$DRIVER_PORT/v1/config")
[ "$CI" = "200" ] && ok "driver config endpoints reachable while degraded" || bad "driver /v1/config returned $CI"
IR=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$DRIVER_PORT/v1/info" | jq_ "d.get('runtime','')" 2>/dev/null)
[ "$IR" = "$RUNTIME_NAME" ] && ok "degraded /v1/info still says which runtime it was meant to front" \
  || bad "/v1/info runtime=$IR"

# --- 4. the engine: not installed by us, found through vllmBinary ---------
say "4. vLLM is a manual engine; point the agent at the operator's venv"
E0=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/engines")
echo "$E0" | PYTHONUTF8=1 "$EP_AGENT_PY" -c "
import sys, json
for e in json.load(sys.stdin)['engines']:
    if e['engine'] != 'vllm': continue
    a = e.get('acquisition') or {}
    m = a.get('manualInstall') or {}
    print(f\"  before: available={e['available']} policy={a.get('policy')} installable={a.get('installable')}\")
    print(f\"  manualInstall.command: {m.get('command')}\")
    print(f\"  manualInstall.docsUrl: {m.get('docsUrl')}\")
    if e.get('error'): print('  error:', e['error'])
"
POL=$(echo "$E0" | jq_ "next(e for e in d['engines'] if e['engine']=='vllm')['acquisition']['policy']" 2>/dev/null)
[ "$POL" = "manual" ] && ok "acquisition.policy is manual — the UI owes instructions, not an install button" \
  || bad "policy=$POL"
CMD=$(echo "$E0" | jq_ "next(e for e in d['engines'] if e['engine']=='vllm')['acquisition']['manualInstall'].get('command') or ''" 2>/dev/null)
if command -v nvidia-smi >/dev/null 2>&1; then
  [ "$CMD" = "uv pip install vllm --torch-backend=auto" ] && ok "the refusal names upstream's CUDA command for this host" \
    || bad "unexpected command for a Linux+NVIDIA host: '$CMD'"
else
  note "command for this host: '$CMD'"
fi

INST=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${AUTH[@]}" \
  "http://127.0.0.1:$AGENT_PORT/v1/engines/vllm/install" -H 'content-type: application/json' -d '{}')
[ "$INST" = "422" ] && ok "POST /v1/engines/vllm/install is 422 — we do not install this one, anywhere" \
  || bad "expected 422 from the install endpoint, got $INST"

PC=$(curl -s -X PATCH "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/config" \
  -H 'content-type: application/json' -d "{\"vllmBinary\":\"$EP_VLLM_BIN\"}" | jq_ "d.get('applied')" 2>/dev/null)
echo "  PATCH /v1/config vllmBinary -> applied: $PC"

E1=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/engines")
echo "$E1" | PYTHONUTF8=1 "$EP_AGENT_PY" -c "
import sys, json
for e in json.load(sys.stdin)['engines']:
    if e['engine'] != 'vllm': continue
    p = e.get('python') or {}
    print(f\"  after:  available={e['available']} origin={e.get('origin')} version={e.get('version')} formats={e.get('modelFormats')}\")
    print(f\"  python: {p.get('interpreter')} ({p.get('pythonVersion')}) vllm={p.get('packageVersion')} torch={p.get('torchVersion')} accelerator={p.get('accelerator')}\")
    if e.get('error'): print('  error:', e['error'])
"
V=$(echo "$E1" | jq_ "next(e for e in d['engines'] if e['engine']=='vllm')" 2>/dev/null)
AV=$(echo "$E1" | jq_ "next(e for e in d['engines'] if e['engine']=='vllm')['available']" 2>/dev/null)
OR=$(echo "$E1" | jq_ "next(e for e in d['engines'] if e['engine']=='vllm').get('origin')" 2>/dev/null)
PV=$(echo "$E1" | jq_ "(next(e for e in d['engines'] if e['engine']=='vllm').get('python') or {}).get('packageVersion') or ''" 2>/dev/null)
TA=$(echo "$E1" | jq_ "(next(e for e in d['engines'] if e['engine']=='vllm').get('python') or {}).get('accelerator') or ''" 2>/dev/null)
[ "$AV" = "True" ] && ok "vllm is available through the install-wide path — nobody put it on PATH" || bad "vllm still unavailable"
[ "$OR" = "configured" ] && ok "origin is configured" || bad "origin=$OR"
[ -n "$PV" ] && ok "vllm $PV read from distribution metadata, not from \`vllm --version\`" || bad "no packageVersion — the interpreter probe did not work"
case "$TA" in
  cuda) ok "PyTorch build tag says CUDA" ;;
  unknown) note "torch accelerator is 'unknown' — an untagged (PyPI) wheel; honest, see the adapter" ;;
  *) note "torch accelerator: '$TA'" ;;
esac

# --- 5. declare the runtime ------------------------------------------------
say "5. declare a vLLM runtime — no binary, no port, the alias is the directory name"
# enforceEager is the short-start path; gpuMemoryUtilization 0.5 leaves
# room for a second runtime on the same card, which is the M5 case.
SPEC="{\"name\":\"$RUNTIME_NAME\",\"engine\":\"vllm\",\"modelPath\":\"$EP_MODEL_DIR\",
  \"flags\":{\"maxModelLen\":4096,\"gpuMemoryUtilization\":0.5,\"maxNumSeqs\":4,\"enforceEager\":true},
  \"autoStart\":true}"
echo "  POST /v1/runtimes $SPEC"
RT=$(curl -s -X POST "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes" \
  -H 'content-type: application/json' -d "$SPEC")
RT_NAME=$(echo "$RT" | jq_ "d.get('name','')" 2>/dev/null)
if [ -n "$RT_NAME" ]; then
  ok "runtime '$RT_NAME' declared"
else
  bad "runtime not created: $RT"
  exit 1
fi
RT_URL=$(echo "$RT" | jq_ "(d.get('url') or '').rstrip('/')" 2>/dev/null)
RT_PORT=${RT_URL##*:}
echo "  url $RT_URL (port assigned by the agent)"
echo "  argv: $(echo "$RT" | jq_ "' '.join(d.get('argv') or ['(not spawned yet)'])" 2>/dev/null)"

# --- 6. the wrong flag is refused before anything spawns ------------------
say "6. an unknown flag is a 400 with the known list, not a crash minutes later"
WRONG=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${AUTH[@]}" \
  "http://127.0.0.1:$AGENT_PORT/v1/runtimes" -H 'content-type: application/json' \
  -d "{\"name\":\"wrong-key-check\",\"engine\":\"vllm\",\"modelPath\":\"$EP_MODEL_DIR\",\"flags\":{\"gpuLayers\":99}}")
[ "$WRONG" = "400" ] && ok "llama.cpp's gpuLayers is refused on a vLLM runtime" || bad "expected 400, got $WRONG"

# --- 7. the load: starting -> loading -> ready, with the port watched -----
say "7. watch the load. This is the measurement the whole milestone is missing."
T0=$(date +%s)
FIRST_LOADING=""
FIRST_READY=""
REFUSED_WHILE_LOADING=0
ANSWERED_WHILE_LOADING=0
LAST_ST=""
LAST_ERR=""
for _ in $(seq 1 "$READY_TIMEOUT_SECONDS"); do
  R=$(curl -s -m 3 "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes/$RT_NAME")
  ST=$(echo "$R" | jq_ "d['status']" 2>/dev/null)
  if [ "$ST" != "$LAST_ST" ]; then
    printf '  t+%4ds  %s\n' "$(($(date +%s) - T0))" "$ST"
    LAST_ST=$ST
  fi
  if [ "$ST" = "loading" ]; then
    [ -z "$FIRST_LOADING" ] && FIRST_LOADING=$(($(date +%s) - T0))
    # §2's claim: bound but not listening => refused. curl exit 7 is
    # "failed to connect". Anything else means the socket accepted.
    if curl -s -m 2 -o /dev/null "http://127.0.0.1:$RT_PORT/health" 2>/dev/null; then
      ANSWERED_WHILE_LOADING=$((ANSWERED_WHILE_LOADING + 1))
    else
      RC=$?
      [ "$RC" = "7" ] && REFUSED_WHILE_LOADING=$((REFUSED_WHILE_LOADING + 1))
    fi
    LE=$(echo "$R" | jq_ "d.get('lastError') or ''" 2>/dev/null)
    [ -n "$LE" ] && [ "$LE" != "$LAST_ERR" ] && { echo "  lastError: $LE"; LAST_ERR=$LE; }
  fi
  [ "$ST" = "ready" ] && { FIRST_READY=$(($(date +%s) - T0)); break; }
  [ "$ST" = "crashed" ] && break
  sleep 1
done
echo "$R" | PYTHONUTF8=1 "$EP_AGENT_PY" -c "
import sys, json
r = json.load(sys.stdin)
print('  status', r['status'], '| pid', r.get('pid'), '| vllm', r.get('engineVersion'))
print('  capabilities read back off /v1/models:', r.get('capabilities'))
print('  argv:', ' '.join(r.get('argv') or []))
if r.get('lastError'): print('  lastError:', r['lastError'])
"
if [ "$ST" = "ready" ]; then
  ok "the model is loaded and serving"
else
  bad "runtime never became ready (status=$ST)"
  tail -60 agent-run.log
fi
echo
echo "  TIMING  first 'loading' at t+${FIRST_LOADING:-never}s, 'ready' at t+${FIRST_READY:-never}s"
echo "  TIMING  loading phase: $(( ${FIRST_READY:-0} - ${FIRST_LOADING:-0} ))s against a 600s budget (enforceEager on)"
echo "  SOCKET  while 'loading': refused $REFUSED_WHILE_LOADING probe(s), answered $ANSWERED_WHILE_LOADING"
if [ -n "$FIRST_LOADING" ]; then
  ok "'loading' was reported — from the process handle, since the port was answering nothing"
else
  bad "'loading' was never observed: either the load was faster than a poll, or §2's rule is not working"
fi
if [ "$REFUSED_WHILE_LOADING" -gt 0 ] && [ "$ANSWERED_WHILE_LOADING" = "0" ]; then
  ok "bound-but-not-listening confirmed: every probe during the load was refused, none hung"
elif [ "$ANSWERED_WHILE_LOADING" -gt 0 ]; then
  note "the port ANSWERED $ANSWERED_WHILE_LOADING time(s) during 'loading' — §1 Trap 1 needs revisiting for this version"
fi
CL=$(echo "$R" | jq_ "(d.get('capabilities') or {}).get('contextLength')" 2>/dev/null)
[ "$CL" = "4096" ] && ok "contextLength 4096 read back from /v1/models max_model_len" || note "contextLength read back as '$CL' (asked for 4096)"
echo "$R" | jq_ "' '.join(d.get('argv') or [])" 2>/dev/null | grep -q -- "--served-model-name $MODEL_ALIAS" \
  && ok "--served-model-name is on the argv, so the model id is '$MODEL_ALIAS' and not the path" \
  || bad "--served-model-name $MODEL_ALIAS missing from argv"

# --- 8. the driver resolves the runtime by name ---------------------------
say "8. restart the driver: it resolves '$RUNTIME_NAME' from the agent, nobody typed a port"
curl -s -o /dev/null -X POST "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/components/$DRIVER_NAME/restart" \
  -H 'content-type: application/json' -d '{}'
for _ in $(seq 1 60); do
  HS=$(curl -s -m 2 "http://127.0.0.1:$DRIVER_PORT/healthz" 2>/dev/null | jq_ "d.get('status','')" 2>/dev/null)
  [ "$HS" = "ok" ] && break
  sleep 1
done
[ "$HS" = "ok" ] && ok "driver healthy" || { bad "driver status=$HS"; curl -s "http://127.0.0.1:$DRIVER_PORT/healthz"; echo; }
INFO=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$DRIVER_PORT/v1/info")
echo "  /v1/info: $INFO"
[ "$(echo "$INFO" | jq_ "d.get('runtime','')" 2>/dev/null)" = "$RUNTIME_NAME" ] \
  && ok "/v1/info reports the runtime it follows" || bad "/v1/info does not report runtime=$RUNTIME_NAME"
grep -q "resolves to $RT_URL" agent-run.log && ok "the driver logged the URL it resolved: $RT_URL" \
  || note "no 'resolves to' line found in agent-run.log for $RT_URL"

# --- 9. routing + one completion ------------------------------------------
say "9. the gateway's routing table, then one completion"
for _ in $(seq 1 60); do
  M=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$GATEWAY_PORT/v1/models")
  MID=$(echo "$M" | jq_ "d['data'][0]['id'] if d.get('data') else ''" 2>/dev/null)
  [ -n "$MID" ] && break
  sleep 2
done
echo "  routable as: '$MID'"
[ "$MID" = "$MODEL_ALIAS" ] && ok "the model is routable under its alias" || bad "gateway lists '$MID', expected '$MODEL_ALIAS'"

DH=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$GATEWAY_PORT/v1/admin/drivers")
DR=$(echo "$DH" | jq_ "next((x.get('runtime') for x in d['drivers'] if x['name']=='$DRIVER_NAME'), '')" 2>/dev/null)
[ "$DR" = "$RUNTIME_NAME" ] && ok "gateway /v1/admin/drivers carries runtime=$RUNTIME_NAME" || bad "DriverHealth.runtime=$DR"

START=$(date +%s)
C=$(curl -s -m 600 -X POST "http://127.0.0.1:$GATEWAY_PORT/v1/chat/completions" "${AUTH[@]}" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$MID\",\"messages\":[{\"role\":\"user\",\"content\":\"What is 17 times 23? Answer with just the number.\"}],\"max_tokens\":64,\"temperature\":0.1}")
TEXT=$(echo "$C" | jq_ "d['choices'][0]['message']['content'].strip() if d.get('choices') else ''" 2>/dev/null)
if [ -n "$TEXT" ]; then
  ok "completion through gateway -> driver -> vllm: '$TEXT'"
else
  bad "empty completion: $(echo "$C" | head -c 400)"
fi
echo "  wall clock: $(($(date +%s) - START))s"

# --- 10. stop releases the GPU -------------------------------------------
say "10. stop the runtime; the declaration stays, the VRAM goes"
curl -s -o /dev/null -X POST "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes/$RT_NAME/stop" \
  -H 'content-type: application/json' -d '{}'
for _ in $(seq 1 30); do
  ST=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes/$RT_NAME" | jq_ "d['status']" 2>/dev/null)
  [ "$ST" = "stopped" ] && break
  sleep 1
done
[ "$ST" = "stopped" ] && ok "runtime stopped and still declared" || bad "status after stop: $ST"
sleep 3
LEFT=$(pgrep -fc "vllm serve" 2>/dev/null || echo 0)
[ "$LEFT" = "0" ] && ok "no vllm serve process left behind" || note "$LEFT 'vllm serve' process(es) still alive — the EngineCore child may outlive the API server; check"

# --- 11. teardown ----------------------------------------------------------
say "11. teardown"
kill "$WD_PID" 2>/dev/null
for _ in $(seq 1 20); do
  kill -0 "$WD_PID" 2>/dev/null || break
  sleep 1
done

say "result"
if [ "$FAILURES" -eq 0 ]; then
  echo "M4 acceptance PASSED — four processes, a second engine, a driver that found it by name."
else
  echo "$FAILURES check(s) FAILED"
fi
echo "Record the TIMING and SOCKET lines above in docs/design/m4-second-engine-vllm.md §8."
echo "install left at $EP_WORKDIR (agent-run.log has every child's output)"
exit "$FAILURES"
