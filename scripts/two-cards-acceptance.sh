#!/usr/bin/env bash
# One model across two cards -- live (2026-09-27).
#
# llama.cpp splits a model's layers across every visible card by default,
# so two 5090s run a model neither can hold alone entirely in GPU memory.
# Admission scored a launch against the largest single card and called
# that model `split` (spilling into system RAM), which a full-offload
# launch refuses. The library could not be told about more than one card,
# and an override kept the library host's own card count, which is zero
# in a container.
#
# **This box has one card, so a stub `nvidia-smi` reports it twice.** The
# stub is a `.cmd` that calls a Python script. It can shadow the real
# tool now only because `devices._run` runs the path `shutil.which`
# resolved (fixed in this slice). R2.3 measured a `.cmd` losing to
# System32's real `nvidia-smi.exe` when `_run` passed the bare name.
# The numbers it reports are this card's own, taken from the real tool
# at the start of the run, so the arithmetic is about a real 5090.
#
# The subject is the real 27B Q6_K_L this box keeps under D:\eugene-models,
# at a context too big for one 5090 (measured 2026-09-15: 41 GiB at
# 262,144 against 30 free, fitting up to about 75k).
#
# The checks:
#   0. isolated from the live install, and from its ports
#   1. one real card: the model at 262,144 is refused, and says the most it fits
#   2. two cards (the stub): the same launch is admitted across both,
#      against their combined free memory
#   3. `splitMode: none` on the same two cards is one card again, refused
#   4. a runtime pinned to one card by CUDA_VISIBLE_DEVICES is one card
#   5. the running library takes gpuCount, and an override is a card
#   6. teardown by pid; no owned port still listening
#
# **What this does not prove**, said rather than implied: that llama.cpp
# splits across two real cards (upstream's default, proved on this box
# across the 5090 and the integrated Radeon with `--device`, recorded in
# docs/acceptance/two-cards-run.md), or any speed at all.
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable is
# dropped, ports are +100, teardown is by pid. Never
# `pkill -f eugene_plexus_`: this box is a worker node.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-two-cards}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
LIB_PORT="${EP_LIB_PORT:-8182}"
AGENT="http://127.0.0.1:$AGENT_PORT"
LIB="http://127.0.0.1:$LIB_PORT"
OWNED_PORTS="$AGENT_PORT $LIB_PORT"
PASS="two-cards-acceptance-passphrase"
MODEL_DIR="${EP_MODEL_DIR:-D:\\eugene-models}"
MODEL_REL='huihui-ai\Huihui-Qwen3.8-27B-abliterated-GGUF\Huihui-Qwen3.8-27B-abliterated-Q6_K_L.gguf'
CONTEXT=262144

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
kill_port() { for p in $(listening_pids "$1"); do taskkill //PID "$p" //F >/dev/null 2>&1 || kill -9 "$p" 2>/dev/null; done; }
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }

A_PID=""
teardown() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 2; }
  for p in $OWNED_PORTS; do kill_port "$p"; done
}
trap teardown EXIT

say "0. isolation"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
for p in $OWNED_PORTS; do
  [ -z "$(listening_pids "$p")" ] || { bad "port $p is already in use; refusing to run"; exit 1; }
done
while IFS='=' read -r name _; do
  case "$name" in EUGENE_PLEXUS_*) unset "$name" ;; esac
done < <(env)
rm -rf "$WORK"; mkdir -p "$WORK/stub"
WORK_WIN=$(win_path "$WORK")
MODEL_PATH="$MODEL_DIR\\$MODEL_REL"
[ -f "$(cygpath -u "$MODEL_PATH")" ] || { bad "the 27B is not at $MODEL_PATH"; exit 1; }
ok "ambient EUGENE_PLEXUS_* cleared; ports $OWNED_PORTS free; model $MODEL_PATH"

# --- the stub: this card, twice --------------------------------------
REAL=$(nvidia-smi --query-gpu=index,name,memory.total,memory.free --format=csv,noheader,nounits | head -1)
NAME=$(printf '%s' "$REAL" | cut -d, -f2 | sed 's/^ *//')
TOTAL_MIB=$(printf '%s' "$REAL" | cut -d, -f3 | tr -d ' ')
FREE_MIB=$(printf '%s' "$REAL" | cut -d, -f4 | tr -d ' ')
BANNER=$(nvidia-smi | grep -m1 "CUDA")
CAP=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d ' ')
DRIVER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | tr -d ' ')
note "the real card: $NAME, $FREE_MIB of $TOTAL_MIB MiB free, compute $CAP"
cat > "$WORK/stub/nvidia_smi_stub.py" <<PYSTUB
import sys
args = " ".join(sys.argv[1:])
rows = [(0, "$NAME"), (1, "$NAME")]
if not args:
    print("$BANNER")
elif "compute_cap" in args and "memory" not in args:
    print("\n".join("$CAP" for _ in rows))
elif args.startswith("--query-gpu=name"):
    print("\n".join(n for _, n in rows))
elif "compute_cap,driver_version" in args:
    print("\n".join(f"{i}, {n}, $TOTAL_MIB, $FREE_MIB, $CAP, $DRIVER" for i, n in rows))
elif "memory.total" in args:
    print("\n".join(f"{i}, {n}, $TOTAL_MIB, $FREE_MIB" for i, n in rows))
else:
    print("$BANNER")
PYSTUB
printf '@"%s" "%%~dp0nvidia_smi_stub.py" %%*\r\n' "$(win_path "$PY")" > "$WORK/stub/nvidia-smi.cmd"
STUB_PATH="$WORK/stub:$PATH"

write_topology() {
  cat > "$WORK/agent.yaml" <<YAML
firstRunComplete: true
updateChecks: false
components:
  - name: library
    kind: library
    url: http://127.0.0.1:$LIB_PORT
    spawn:
      configFile: $WORK_WIN\library.yaml
runtimes: []
YAML
  printf 'logLevel: INFO\nmodelRoots:\n  - %s\n' "$MODEL_DIR" > "$WORK/library.yaml"
}

wait_healthy() {
  local url=$1 n=${2:-40}
  for _ in $(seq 1 "$n"); do
    curl -sf -m 2 "$url/healthz" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

TOK=""
start_agent() {
  local use_path=$1; shift
  teardown; A_PID=""
  write_topology
  (
    exec env -u EUGENE_PLEXUS_AGENT_CONFIG_FILE \
      PATH="$use_path" \
      EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_WIN\\agent.yaml" \
      EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 \
      EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
      EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY=0 \
      EUGENE_PLEXUS_AGENT_ENGINE_ROOT="$WORK_WIN\\engines" \
      EUGENE_PLEXUS_LIBRARY_STATE_FILE="$WORK_WIN\\library-state.json" \
      "$PY" -m eugene_plexus_agent --unattended > "$WORK/agent.log" 2>&1
  ) &
  A_PID=$!
  wait_healthy "$AGENT" 60 || { bad "the agent never came up"; tail -20 "$WORK/agent.log"; return 1; }
  TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' \
        -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
  [ -n "$TOK" ] || TOK=$(curl -s -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' \
        -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
  [ -n "$TOK" ] || { bad "no session token"; return 1; }
  wait_healthy "$LIB" 60 || { bad "the library never came up"; return 1; }
  # The model has to be catalogued before admission can ask about it.
  for _ in $(seq 1 60); do
    [ "$(curl -s -m 10 -H "Authorization: Bearer $TOK" "$LIB/v1/models" | jq_ "len(d.get('models') or [])")" -ge 1 ] 2>/dev/null && return 0
    sleep 1
  done
  bad "the library never catalogued the 27B"; return 1
}

# admit <extra json for the spec> -> writes $WORK/admission.json
admit() {
  local extra=$1
  local path_json
  path_json=$(python -c "import json,sys; print(json.dumps(sys.argv[1]))" "$MODEL_PATH")
  curl -s -m 60 -X POST -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
    -d "{\"name\":\"big\",\"engine\":\"llama_cpp\",\"modelPath\":$path_json,\"flags\":{\"contextSize\":$CONTEXT$extra}}" \
    "$AGENT/v1/runtimes/admission" > "$WORK/admission.json"
}
field() { jq_ "$1" < "$WORK/admission.json"; }

# --------------------------------------------------------------------- #
say "1. one real card: the model at $CONTEXT context is refused"
start_agent "$PATH" || exit 1
admit ""
DECISION=$(field "d.get('decision')"); DEVICES=$(field "len(d.get('devices') or [])")
MAXCTX=$(field "d.get('maxContextLength')")
[ "$DECISION" = "refuse" ] && ok "refused on one card (max context here: $MAXCTX)" \
  || bad "expected refuse on one card, got '$DECISION': $(field "d.get('reason')")"
[ "$DEVICES" = "0" ] && ok "and it is about one card" || bad "devices on a one-card box: $DEVICES"

# --------------------------------------------------------------------- #
say "2. two cards: the same launch is admitted across both"
start_agent "$STUB_PATH" || exit 1
NODE_CARDS=$(curl -s -m 20 -H "Authorization: Bearer $TOK" "$AGENT/v1/node" | jq_ "len([x for x in d.get('devices') or [] if x['kind']=='cuda'])")
[ "$NODE_CARDS" = "2" ] && ok "the agent reads two cards through the stub" \
  || bad "the agent sees $NODE_CARDS cards; the stub did not land ($(tail -3 "$WORK/agent.log"))"
admit ""
DECISION=$(field "d.get('decision')")
IDX=$(field "','.join(str(x.get('index')) for x in d.get('devices') or [])")
FREE=$(field "d.get('freeBytes')")
REASON=$(field "d.get('reason')")
WANT_FREE=$((FREE_MIB * 2 * 1024 * 1024))
[ "$DECISION" = "admit" ] && ok "admitted: $REASON" || bad "expected admit across two cards, got '$DECISION': $REASON"
[ "$IDX" = "0,1" ] && ok "devices 0,1" || bad "devices '$IDX'"
[ "$FREE" = "$WANT_FREE" ] && ok "freeBytes is both cards' ($FREE)" || bad "freeBytes $FREE, want $WANT_FREE"
case "$REASON" in *"2 cards (device 0"*"between them"*) ok "the reason says so" ;; *) bad "the reason does not name the pair" ;; esac

# --------------------------------------------------------------------- #
say "3. splitMode none on the same two cards is one card, refused"
admit ',"splitMode":"none"'
DECISION=$(field "d.get('decision')")
[ "$DECISION" = "refuse" ] && ok "refused" || bad "splitMode none gave '$DECISION'"

# --------------------------------------------------------------------- #
say "4. pinned to one card is one card"
path_json=$(python -c "import json,sys; print(json.dumps(sys.argv[1]))" "$MODEL_PATH")
curl -s -m 60 -X POST -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"name\":\"big\",\"engine\":\"llama_cpp\",\"modelPath\":$path_json,\"flags\":{\"contextSize\":$CONTEXT},\"env\":{\"CUDA_VISIBLE_DEVICES\":\"1\"}}" \
  "$AGENT/v1/runtimes/admission" > "$WORK/admission.json"
DECISION=$(field "d.get('decision')"); MAIN=$(field "(d.get('device') or {}).get('index')")
[ "$DECISION" = "refuse" ] && [ "$MAIN" = "1" ] && ok "refused, on device 1" \
  || bad "pinned to 1 gave '$DECISION' on device '$MAIN'"

# --------------------------------------------------------------------- #
say "5. the running library takes gpuCount, and an override is a card"
ID=$(curl -s -m 10 -H "Authorization: Bearer $TOK" "$LIB/v1/models" | jq_ "d['models'][0]['id']")
ONE=$(curl -s -m 30 -H "Authorization: Bearer $TOK" "$LIB/v1/models/$ID/fit?contextLength=$CONTEXT&vramBytes=32000000000&ramBytes=60000000000")
TWO=$(curl -s -m 30 -H "Authorization: Bearer $TOK" "$LIB/v1/models/$ID/fit?contextLength=$CONTEXT&vramBytes=64000000000&ramBytes=60000000000&gpuCount=2")
ONE_COUNT=$(printf '%s' "$ONE" | jq_ "d['fit']['budget']['gpuCount']")
TWO_COUNT=$(printf '%s' "$TWO" | jq_ "d['fit']['budget']['gpuCount']")
ONE_OVER=$(printf '%s' "$ONE" | jq_ "d['fit']['overheadBytes']")
TWO_OVER=$(printf '%s' "$TWO" | jq_ "d['fit']['overheadBytes']")
[ "$ONE_COUNT" = "1" ] && ok "a one-card override is one card, not this host's count" \
  || bad "a one-card override reported gpuCount $ONE_COUNT"
[ "$TWO_COUNT" = "2" ] && [ "$TWO_OVER" = "$((ONE_OVER * 2))" ] && ok "two cards, two allowances ($TWO_OVER bytes)" \
  || bad "gpuCount=2 gave count $TWO_COUNT, overhead $TWO_OVER vs $ONE_OVER"

# --------------------------------------------------------------------- #
say "6. teardown"
teardown
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ] && ok "no owned port still listening" || bad "still listening:$STILL"

printf '\n'
if [ "$FAILURES" = 0 ]; then
  printf 'two-cards: all checks passed\n'
  exit 0
fi
printf 'two-cards: %s FAILED\n' "$FAILURES"
exit 1
