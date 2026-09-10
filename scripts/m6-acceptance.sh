#!/usr/bin/env bash
#
# M6 acceptance: lifecycle policy, live, on one box.
#
#   agent  ->  spawns  ->  control, gateway, library
#          ->  declares ->  qwen3-a, qwen3-b   (two llama-server replicas, one GGUF)
#          ->  and their companions, which it declares itself:
#                             qwen3-a-driver, qwen3-b-driver
#
# Seven things, in the order an operator meets them, each of which was
# named at an earlier milestone and deferred to here:
#
#   1. Launch ends routable — no driver config written anywhere.
#   2. Two replicas of one alias are load-balanced (they alternate).
#   3. Kill one replica through the OS; the next completion returns.
#   4. Idle past the timeout; both unload; VRAM comes back in nvidia-smi.
#   5. A request for the sleeping alias wakes it and is served.
#   6. A model that will not fit is refused with the arithmetic (and
#      force-declared anyway, then deleted).
#   7. A configured slot cascades across tiers: a stopped first tier
#      with no wake falls to the second, and the response says `tier: 2`.
#
# What one GPU proves and does not: everything above is about processes,
# routing and memory returned to the device, and one card is enough for
# all of it. What it cannot show is a replica landing on a *second* card
# — the env var is passed and argv shows it, but the observable is
# identical to not pinning. Set EP_DEVICES="0 1" on a two-GPU box.
#
# Usage:
#   scripts/m6-acceptance.sh
#
# Configure via environment (defaults suit the machine this was written
# on and nobody else — set them):
#
#   EP_ROOT          parent directory holding the component clones
#   EP_AGENT_PY      python with agent + control + gateway + driver + library
#                    installed (the agent spawns every component with its
#                    own sys.executable, so all five must import from it)
#   EP_LLAMA_SERVER  path to llama-server(.exe)
#   EP_MODEL         path to a SMALL .gguf chat model (loaded twice)
#   EP_BIG_MODEL     path to a .gguf that will NOT fit beside them at 128k
#   EP_DEVICES       space-separated device indices for the replicas
#                    ("0" on this box; "0 1" with two cards)
#   EP_IDLE_SECONDS  the replicas' idleUnloadSeconds (default 20)
#   EP_WORKDIR       scratch directory for the throwaway install
#
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
EP_AGENT_PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
EP_LLAMA_SERVER="${EP_LLAMA_SERVER:-C:/Users/troyc/OneDrive/Desktop/llamacpp/llama-server.exe}"
EP_MODEL="${EP_MODEL:-D:/py/eugene-plexus/smoke-test/models/Qwen3-1.7B-Q8_0.gguf}"
EP_BIG_MODEL="${EP_BIG_MODEL:-C:/Users/troyc/.lmstudio/models/DavidAU/Qwen3.6-40B-Claude-4.6-Opus-Deckard-Heretic-Uncensored-Thinking-NEO-CODE-Di-IMatrix-MAX-GGUF/Qwen3.6-40B-Deck-Opus-NEO-CODE-HERE-2T-OT-Q4_K_S.gguf}"
EP_DEVICES="${EP_DEVICES:-0}"
EP_IDLE_SECONDS="${EP_IDLE_SECONDS:-20}"
EP_WORKDIR="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-m6-acceptance}"

AGENT_PORT=8079
GATEWAY_PORT=8080
LIBRARY_PORT=8082
CONTROL_PORT=8083
ALIAS=qwen3-1.7b
BIG_NAME=too-big

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
gpu_used_mib() {
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${1:-0}" 2>/dev/null | tr -d ' \r'
}

# --- preflight -------------------------------------------------------------
say "preflight"
[ -f "$EP_AGENT_PY" ] || bad "agent venv python not found at $EP_AGENT_PY"
[ -f "$EP_LLAMA_SERVER" ] || bad "llama-server not found at $EP_LLAMA_SERVER"
[ -f "$EP_MODEL" ] || bad "model not found at $EP_MODEL"
[ -f "$EP_BIG_MODEL" ] || bad "big model not found at $EP_BIG_MODEL"
if [ "$FAILURES" -ne 0 ]; then
  printf '\nSet EP_AGENT_PY / EP_LLAMA_SERVER / EP_MODEL / EP_BIG_MODEL and retry.\n'
  exit 1
fi
if ! "$EP_AGENT_PY" -c "import eugene_plexus_agent, eugene_plexus_control, eugene_plexus_gateway, eugene_plexus_inference_driver, eugene_plexus_library" 2>/dev/null; then
  bad "agent, control, gateway, inference-driver and library must all import from $EP_AGENT_PY"
  exit 1
fi
if ! command -v nvidia-smi >/dev/null 2>&1; then
  bad "nvidia-smi not on PATH — the VRAM check needs it"
  exit 1
fi
DEVICE_COUNT=$(nvidia-smi -L | wc -l | tr -d ' ')
ok "engine binary, both models, all five components present; $DEVICE_COUNT GPU(s) visible, replicas on: $EP_DEVICES"

# --- a throwaway install ---------------------------------------------------
say "a throwaway install in $EP_WORKDIR"
rm -rf "$EP_WORKDIR"
mkdir -p "$EP_WORKDIR"
cd "$EP_WORKDIR" || exit 1

# Backslashes, because these land in argv for a Windows binary. On a
# POSIX host they pass through unchanged.
win_path() { printf '%s' "$1" | sed 's|/|\\|g'; }

# No runtimes and NO driver config here. Both are what this run proves
# the install produces on its own.
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
  - name: library
    kind: library
    url: http://127.0.0.1:$LIBRARY_PORT
    spawn:
      configFile: library.yaml
runtimes: []
YAML

# Fast refresh and a short idle check so the run finishes in minutes.
cat > gateway.yaml <<YAML
logLevel: INFO
routingRefreshSeconds: 3
idleCheckSeconds: 5
swapWaitSeconds: 120
YAML
echo "logLevel: INFO" > control.yaml
# Both models' directories, so admission gets the library's metadata
# arithmetic (`basis: metadata`) rather than the file-size fallback.
cat > library.yaml <<YAML
logLevel: INFO
modelRoots:
  - $(win_path "$(dirname "$EP_MODEL")")
  - $(win_path "${EP_LIBRARY_ROOT:-$(dirname "$(dirname "$(dirname "$EP_BIG_MODEL")")")}")
YAML
ok "topology written — control, gateway, library; no runtimes, no drivers"

# --- 1. the supervisor and the fleet ----------------------------------------
say "1. start the supervisor"
EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml "$EP_AGENT_PY" \
  -m eugene_plexus_agent > agent-run.log 2>&1 &
WD_PID=$!
trap 'kill "$WD_PID" 2>/dev/null' EXIT

for _ in $(seq 1 60); do
  curl -sf -m 2 "http://127.0.0.1:$AGENT_PORT/healthz" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf -m 2 "http://127.0.0.1:$AGENT_PORT/healthz" >/dev/null && ok "agent answering on :$AGENT_PORT" || { bad "agent never came up"; tail -40 agent-run.log; exit 1; }

for _ in $(seq 1 60); do
  curl -sf -m 2 "http://127.0.0.1:$CONTROL_PORT/healthz" >/dev/null 2>&1 && break
  sleep 1
done
curl -s -o /dev/null -X POST "http://127.0.0.1:$CONTROL_PORT/v1/auth/initialize" \
  -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}"
ATOK=$(curl -s -X POST "http://127.0.0.1:$AGENT_PORT/v1/auth/initialize" \
  -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
if [ -z "$ATOK" ]; then
  bad "no operator session from the agent"
  tail -40 agent-run.log
  exit 1
fi
AUTH=(-H "Authorization: Bearer $ATOK")
ok "install initialized; operator session issued by the agent"

for _ in $(seq 1 120); do
  S=$(curl -s -m 3 "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/components" 2>/dev/null |
    jq_ "' '.join(sorted(c['name']+'='+c['status'] for c in d['components']))" 2>/dev/null)
  case "$S" in *"control=running"*"gateway=running"*"library=running"*) break ;; esac
  sleep 1
done
echo "  components: $S"
case "$S" in *"control=running"*"gateway=running"*"library=running"*) ok "control, gateway and library running under supervision" ;; *) bad "fleet did not come up"; tail -40 agent-run.log; exit 1 ;; esac

# The agent reports its devices for the first time (M5's agent half).
NODE=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/node")
NDEV=$(echo "$NODE" | jq_ "len([x for x in d.get('devices',[]) if x['kind']!='cpu'])")
[ "$NDEV" -ge 1 ] 2>/dev/null && ok "GET /v1/node reports $NDEV accelerator(s): $(echo "$NODE" | jq_ "', '.join(x['name']+' free='+str(round((x.get('memoryFreeBytes') or 0)/2**30,1))+'GiB' for x in d['devices'] if x['kind']!='cpu')")" \
  || bad "GET /v1/node reports no accelerator: $NODE"

# --- 2. LAUNCH ENDS ROUTABLE -------------------------------------------------
say "2. declare two replicas of one alias — and nothing else"
GPU0_BEFORE=$(gpu_used_mib 0)
i=0
for dev in $EP_DEVICES $EP_DEVICES; do
  name=$([ $i -eq 0 ] && echo qwen3-a || echo qwen3-b)
  [ $i -ge 2 ] && break
  R=$(curl -s -w '\n%{http_code}' -X POST "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes" \
    -H 'content-type: application/json' -d "{
      \"name\": \"$name\", \"engine\": \"llama_cpp\",
      \"modelPath\": \"$(win_path "$EP_MODEL" | sed 's|\\|\\\\|g')\", \"modelAlias\": \"$ALIAS\",
      \"binary\": \"$(win_path "$EP_LLAMA_SERVER" | sed 's|\\|\\\\|g')\",
      \"flags\": {\"contextSize\": 4096, \"gpuLayers\": 99, \"parallelSlots\": 1},
      \"env\": {\"CUDA_VISIBLE_DEVICES\": \"$dev\"},
      \"idleUnloadSeconds\": $EP_IDLE_SECONDS, \"startOnDemand\": true}")
  CODE=$(echo "$R" | tail -1); BODY=$(echo "$R" | sed '$d')
  DRV=$(echo "$BODY" | jq_ "d.get('driver')" 2>/dev/null)
  if [ "$CODE" = "201" ] && [ "$DRV" = "$name-driver" ]; then
    ok "declared $name on CUDA_VISIBLE_DEVICES=$dev; companion driver '$DRV' (admission: $(echo "$BODY" | jq_ "d['status']"))"
  else
    bad "declaring $name returned $CODE: $(echo "$BODY" | head -c 300)"
    exit 1
  fi
  i=$((i + 1))
done

COMPS=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/components" | jq_ "sorted(c['name'] for c in d['components'])")
case "$COMPS" in *"qwen3-a-driver"*"qwen3-b-driver"*) ok "both companions are in the topology: $COMPS" ;; *) bad "companions missing from topology: $COMPS" ;; esac

say "   ...wait for both engines to be ready and the gateway to route the alias"
for _ in $(seq 1 180); do
  RT=$(curl -s -m 3 "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes" | jq_ "' '.join(sorted(r['name']+'='+r['status'] for r in d['runtimes']))" 2>/dev/null)
  case "$RT" in *"qwen3-a=ready"*"qwen3-b=ready"*) break ;; esac
  case "$RT" in *crashed*) break ;; esac
  sleep 1
done
echo "  runtimes: $RT"
case "$RT" in *"qwen3-a=ready"*"qwen3-b=ready"*) ok "both replicas ready" ;; *) bad "replicas never became ready"; curl -s "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes" | jq_ "[r.get('lastError') for r in d['runtimes']]"; tail -30 agent-run.log; exit 1 ;; esac

# Routable means both drivers listed AND both counted ready — the
# first run checked only the list and the completions met a table that
# was still a refresh behind about readiness.
for _ in $(seq 1 60); do
  M=$(curl -s -m 5 "${AUTH[@]}" "http://127.0.0.1:$GATEWAY_PORT/v1/models")
  DRIVERS=$(echo "$M" | jq_ "next((sorted(m['x_eugene_plexus']['drivers']) for m in d.get('data',[]) if m['id']=='$ALIAS'), [])" 2>/dev/null)
  READYN=$(echo "$M" | jq_ "next((m['x_eugene_plexus'].get('ready_backends') for m in d.get('data',[]) if m['id']=='$ALIAS'), 0)" 2>/dev/null)
  case "$DRIVERS" in *"qwen3-a-driver"*"qwen3-b-driver"*) [ "$READYN" = "2" ] && break ;; esac
  sleep 1
done
case "$DRIVERS" in
  *"qwen3-a-driver"*"qwen3-b-driver"*)
    ok "*** LAUNCH ENDS ROUTABLE: gateway /v1/models lists '$ALIAS' behind $DRIVERS (ready_backends=$READYN) with no driver config written by hand ***"
    echo "  $(echo "$M" | jq_ "next(m['x_eugene_plexus'] for m in d['data'] if m['id']=='$ALIAS')")" ;;
  *) bad "gateway never listed both companions for '$ALIAS' (saw $DRIVERS)"; exit 1 ;;
esac

# The cost of the companion, measured rather than assumed (design §9).
for c in qwen3-a-driver qwen3-b-driver; do
  CPID=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/components/$c" | jq_ "d.get('pid')")
  if command -v powershell.exe >/dev/null 2>&1 && [ -n "$CPID" ] && [ "$CPID" != "None" ]; then
    # The venv's python.exe on Windows is a launcher whose child is the
    # real interpreter, so sum the tree rather than read the stub's 5 MB.
    RSS=$(powershell.exe -NoProfile -Command "\$ids=@($CPID); \$ids+=(Get-CimInstance Win32_Process -Filter \"ParentProcessId=$CPID\").ProcessId; [math]::Round(((Get-Process -Id \$ids -ErrorAction SilentlyContinue | Measure-Object WorkingSet64 -Sum).Sum)/1MB)" 2>/dev/null | tr -d '\r')
    echo "  companion $c: pid $CPID (+children), resident ${RSS} MB"
  fi
done
GPU0_LOADED=$(gpu_used_mib 0)
echo "  GPU 0 memory.used: ${GPU0_BEFORE} MiB before -> ${GPU0_LOADED} MiB with both replicas loaded"

# --- 3. LOAD BALANCING -------------------------------------------------------
say "3. six completions — the replicas should alternate"
complete() {
  curl -s -m 300 -X POST "http://127.0.0.1:$GATEWAY_PORT/v1/chat/completions" "${AUTH[@]}" \
    -H 'content-type: application/json' \
    -d "{\"model\":\"${2:-$ALIAS}\",\"messages\":[{\"role\":\"user\",\"content\":\"$1 /no_think\"}],\"max_tokens\":32,\"temperature\":0.1}"
}
SEQ=""
RUNTIMES_SEEN=""
for n in 1 2 3 4 5 6; do
  C=$(complete "Reply with the single word OK.")
  DRV=$(echo "$C" | jq_ "(d.get('x_eugene_plexus') or {}).get('driver','?')" 2>/dev/null)
  RTN=$(echo "$C" | jq_ "(d.get('x_eugene_plexus') or {}).get('runtime','?')" 2>/dev/null)
  TXT=$(echo "$C" | jq_ "(d.get('choices') or [{}])[0].get('message',{}).get('content','').strip()[:40]" 2>/dev/null)
  echo "  #$n -> driver=$DRV runtime=$RTN text=$(printf '%q' "$TXT")"
  SEQ="$SEQ $DRV"
  RUNTIMES_SEEN="$RUNTIMES_SEEN $RTN"
done
ALT=$(printf '%s' "$SEQ" | PYTHONUTF8=1 python -c "
import sys; s=sys.stdin.read().split(); print('yes' if len(set(s))==2 and all(a!=b for a,b in zip(s,s[1:])) else 'no')")
[ "$ALT" = "yes" ] && ok "*** ROUND-ROBIN: six completions alternated across both replicas:$SEQ ***" || bad "completions did not alternate:$SEQ"
case "$RUNTIMES_SEEN" in *qwen3-a*qwen3-b*|*qwen3-b*qwen3-a*) ok "each response names the replica that served it (by name, not alias):$RUNTIMES_SEEN" ;; *) bad "runtime attribution missing:$RUNTIMES_SEEN" ;; esac

VIEW=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$GATEWAY_PORT/v1/admin/routing")
echo "  routing view: $(echo "$VIEW" | jq_ "[(b['driver'], b['eligible'], b['in_flight'], b['runtime_status']) for s in d['slots'] for t in s['tiers'] for b in t['backends']]")"

# --- 4. KILL ONE REPLICA THROUGH THE OS ---------------------------------------
say "4. kill qwen3-b's engine through the OS; the next completion must still return"
BPID=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes/qwen3-b" | jq_ "d.get('pid')")
echo "  qwen3-b engine pid: $BPID"
if command -v powershell.exe >/dev/null 2>&1; then
  powershell.exe -NoProfile -Command "Stop-Process -Id $BPID -Force -ErrorAction SilentlyContinue" >/dev/null 2>&1
else
  kill -9 "$BPID" 2>/dev/null
fi
sleep 0.5
START=$(date +%s%3N)
C=$(complete "Reply with the single word OK.")
END=$(date +%s%3N)
TXT=$(echo "$C" | jq_ "(d.get('choices') or [{}])[0].get('message',{}).get('content','').strip()" 2>/dev/null)
DRV=$(echo "$C" | jq_ "(d.get('x_eugene_plexus') or {}).get('driver','?')" 2>/dev/null)
ATT=$(echo "$C" | jq_ "(d.get('x_eugene_plexus') or {}).get('attempts','?')" 2>/dev/null)
if [ -n "$TXT" ] && [ "$DRV" = "qwen3-a-driver" ]; then
  if [ "$ATT" = "1" ]; then
    ok "*** KILLED REPLICA: completion returned from qwen3-a in $((END - START))ms; the table had already dropped qwen3-b (attempts=1) ***"
  else
    ok "*** KILLED REPLICA: completion returned from qwen3-a in $((END - START))ms after the cascade (attempts=$ATT) ***"
  fi
else
  bad "completion after the kill failed or went to the dead replica: driver=$DRV $(echo "$C" | head -c 300)"
fi
for _ in $(seq 1 90); do
  BS=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes/qwen3-b" | jq_ "d['status']" 2>/dev/null)
  [ "$BS" = "ready" ] && break
  sleep 1
done
[ "$BS" = "ready" ] && ok "the supervisor respawned qwen3-b (status=$BS)" || bad "qwen3-b did not come back (status=$BS)"

# --- 5. IDLE UNLOAD -----------------------------------------------------------
say "5. no requests for a while — both replicas should unload after ${EP_IDLE_SECONDS}s idle"
GPU0_LOADED=$(gpu_used_mib 0)
for _ in $(seq 1 $((EP_IDLE_SECONDS + 60))); do
  RT=$(curl -s -m 3 "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes" | jq_ "' '.join(sorted(r['name']+'='+r['status']+'/'+str(r.get('stopReason')) for r in d['runtimes']))" 2>/dev/null)
  case "$RT" in *"qwen3-a=stopped/idle"*"qwen3-b=stopped/idle"*) break ;; esac
  sleep 1
done
echo "  runtimes: $RT"
case "$RT" in *"qwen3-a=stopped/idle"*"qwen3-b=stopped/idle"*) ok "*** IDLE UNLOAD: both replicas stopped with stopReason=idle by the gateway ***" ;; *) bad "replicas did not idle out: $RT" ;; esac
sleep 2
GPU0_IDLE=$(gpu_used_mib 0)
echo "  GPU 0 memory.used: ${GPU0_LOADED} MiB loaded -> ${GPU0_IDLE} MiB after unload (idle baseline was ${GPU0_BEFORE} MiB)"
if [ -n "$GPU0_LOADED" ] && [ -n "$GPU0_IDLE" ] && [ $((GPU0_LOADED - GPU0_IDLE)) -ge 1500 ]; then
  ok "*** VRAM CAME BACK: nvidia-smi shows $((GPU0_LOADED - GPU0_IDLE)) MiB released ***"
else
  bad "VRAM did not come back (loaded=${GPU0_LOADED} idle=${GPU0_IDLE})"
fi
M=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$GATEWAY_PORT/v1/models")
OD=$(echo "$M" | jq_ "next((m['x_eugene_plexus'].get('on_demand') for m in d['data'] if m['id']=='$ALIAS'), None)")
[ "$OD" = "True" ] && ok "the alias is still listed, marked on_demand — a client can still name it" || bad "sleeping alias not listed as on_demand: $OD"

# --- 6. SWAP ON DEMAND ----------------------------------------------------------
say "6. a completion for the sleeping alias — the gateway must wake a replica and serve it"
START=$(date +%s%3N)
C=$(complete "Reply with the single word OK.")
END=$(date +%s%3N)
TXT=$(echo "$C" | jq_ "(d.get('choices') or [{}])[0].get('message',{}).get('content','').strip()" 2>/dev/null)
INFO=$(echo "$C" | jq_ "d.get('x_eugene_plexus')" 2>/dev/null)
SW=$(echo "$C" | jq_ "(d.get('x_eugene_plexus') or {}).get('swapped_in')" 2>/dev/null)
WMS=$(echo "$C" | jq_ "(d.get('x_eugene_plexus') or {}).get('waited_ms',0)" 2>/dev/null)
echo "  $INFO"
if [ -n "$TXT" ] && [ "$SW" = "True" ] && [ "${WMS:-0}" -gt 0 ] 2>/dev/null; then
  ok "*** SWAP ON DEMAND: served in $((END - START))ms wall clock, swapped_in=true, waited_ms=$WMS ***"
else
  bad "swap-in did not happen as expected: $(echo "$C" | head -c 400)"
fi
RT=$(curl -s -m 3 "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes" | jq_ "' '.join(sorted(r['name']+'='+r['status'] for r in d['runtimes']))")
echo "  runtimes: $RT"
case "$RT" in *ready*) ok "exactly the replica that was asked for is back (the other stays asleep): $RT" ;; *) bad "no replica ready after swap-in: $RT" ;; esac

# --- 7. ADMISSION -----------------------------------------------------------------
say "7. a model that will not fit: refused with the arithmetic, force-declared anyway"
BIG_SPEC="{\"name\": \"$BIG_NAME\", \"engine\": \"llama_cpp\", \"modelPath\": \"$(win_path "$EP_BIG_MODEL" | sed 's|\\|\\\\|g')\", \"binary\": \"$(win_path "$EP_LLAMA_SERVER" | sed 's|\\|\\\\|g')\", \"flags\": {\"contextSize\": 131072, \"gpuLayers\": 99}, \"env\": {\"CUDA_VISIBLE_DEVICES\": \"0\"}}"
ADM=$(curl -s -X POST "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes/admission" -H 'content-type: application/json' -d "$BIG_SPEC")
DEC=$(echo "$ADM" | jq_ "d.get('decision')")
echo "  decision=$DEC fit=$(echo "$ADM" | jq_ "d.get('fit')") basis=$(echo "$ADM" | jq_ "d.get('basis')") required=$(echo "$ADM" | jq_ "round((d.get('requiredBytes') or 0)/2**30,1)")GiB free=$(echo "$ADM" | jq_ "round((d.get('freeBytes') or 0)/2**30,1)")GiB blockers=$(echo "$ADM" | jq_ "[b['name'] for b in d.get('blockers',[])]")"
echo "  reason: $(echo "$ADM" | jq_ "d.get('reason')" | head -c 400)"
[ "$DEC" = "refuse" ] && ok "*** ADMISSION: the dry run refuses the 40B at 128k with the numbers ***" || bad "expected refuse, got $DEC"

CODE=$(curl -s -o /tmp/ep-m6-refused.json -w '%{http_code}' -X POST "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes" -H 'content-type: application/json' -d "$BIG_SPEC")
[ "$CODE" = "422" ] && ok "POST /v1/runtimes refuses it with 422: $(jq_ "d['detail']['detail'][:120]" < /tmp/ep-m6-refused.json)" || bad "expected 422, got $CODE"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes?force=true" -H 'content-type: application/json' -d "$BIG_SPEC")
[ "$CODE" = "201" ] && ok "?force=true declares it anyway (201) — the estimate is an estimate and the model is the operator's" || bad "force returned $CODE"
curl -s -o /dev/null -X DELETE "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes/$BIG_NAME"
ok "and it is deleted again before it finishes loading"

# --- 8. TIERS -----------------------------------------------------------------------
say "8. a configured slot: a stopped first tier with no wake falls to the second"
# `sleeper` serves alias `sleepy`, declared stopped and NOT on demand. Its
# companion driver runs and is reachable, so `sleepy` is a real tier —
# just never an eligible one.
curl -s -o /dev/null -X POST "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/runtimes" -H 'content-type: application/json' -d "{
  \"name\": \"sleeper\", \"engine\": \"llama_cpp\", \"modelPath\": \"$(win_path "$EP_MODEL" | sed 's|\\|\\\\|g')\", \"modelAlias\": \"sleepy\",
  \"binary\": \"$(win_path "$EP_LLAMA_SERVER" | sed 's|\\|\\\\|g')\", \"flags\": {\"contextSize\": 2048}, \"autoStart\": false, \"startOnDemand\": false}"
PC=$(curl -s -o /dev/null -w '%{http_code}' -X PATCH "${AUTH[@]}" "http://127.0.0.1:$GATEWAY_PORT/v1/config" -H 'content-type: application/json' \
  -d "{\"modelSlots\": [{\"model\": \"coder\", \"targets\": [\"sleepy\", \"$ALIAS\"]}]}")
[ "$PC" = "200" ] && ok "gateway modelSlots patched: coder -> [sleepy, $ALIAS]" || bad "PATCH modelSlots returned $PC"
for _ in $(seq 1 30); do
  TIERS=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$GATEWAY_PORT/v1/models" | jq_ "next((m['x_eugene_plexus'].get('tiers') for m in d['data'] if m['id']=='coder'), None)" 2>/dev/null)
  case "$TIERS" in *sleeper-driver*qwen3-*) break ;; esac
  sleep 1
done
echo "  coder tiers: $TIERS"
C=$(complete "Reply with the single word OK." coder)
TIER=$(echo "$C" | jq_ "(d.get('x_eugene_plexus') or {}).get('tier')" 2>/dev/null)
DRV=$(echo "$C" | jq_ "(d.get('x_eugene_plexus') or {}).get('driver')" 2>/dev/null)
SERVED=$(echo "$C" | jq_ "d.get('model')" 2>/dev/null)
echo "  coder -> driver=$DRV tier=$TIER model=$SERVED"
if [ "$TIER" = "2" ] && [ "$SERVED" = "$ALIAS" ]; then
  ok "*** TIERS: 'coder' answered from tier 2 ($DRV) because tier 1 (sleepy) is stopped with no wake, and the response names what answered ***"
else
  bad "expected tier 2 from $ALIAS, got tier=$TIER model=$SERVED: $(echo "$C" | head -c 300)"
fi

# --- 9. teardown -----------------------------------------------------------------
say "9. teardown"
kill "$WD_PID" 2>/dev/null
for _ in $(seq 1 20); do
  kill -0 "$WD_PID" 2>/dev/null || break
  sleep 1
done
sleep 3
if command -v powershell.exe >/dev/null 2>&1; then
  LEFT=$(powershell.exe -NoProfile -Command "(Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r')
else
  LEFT=$(pgrep -c llama-server 2>/dev/null || echo 0)
fi
[ "$LEFT" = "0" ] && ok "no llama-server survived the supervisor" || bad "$LEFT llama-server process(es) survived the supervisor"

say "result"
if [ "$FAILURES" -eq 0 ]; then
  echo "M6 acceptance PASSED — launch is routable, replicas balance, a killed replica is survived,"
  echo "idle models unload and come back on demand, a model that will not fit is refused with numbers,"
  echo "and a configured slot cascades across tiers."
else
  echo "$FAILURES check(s) FAILED"
fi
exit "$FAILURES"
