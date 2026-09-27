#!/usr/bin/env bash
# A second vendor's card beside an NVIDIA one -- live (2026-09-27).
#
# The Windows CUDA and Vulkan builds of one llama.cpp release share
# byte-identical core libraries, and each backend is a plug-in. The
# agent's `+vulkan` variant is the CUDA build with the Vulkan backend
# added: the default for a discrete AMD or Intel card beside NVIDIA, and
# the expert's way to test an integrated GPU as overflow.
#
# **This box has an RTX 5090 and an INTEGRATED Radeon, so the combined
# build is not its default** (an integrated GPU is not a second card:
# llama.cpp keeps it out while a card is present). The run installs it
# by hand, which is the expert's path, and uses the Radeon only where
# the runtime names it. A discrete second card is unit-tested; nothing
# here has one.
#
# The checks:
#   0. isolated from the live install, and from its ports
#   1. the default here is the plain CUDA build; the combined ones are offered
#   2. the agent installs win-cuda-*+vulkan: both backends, one directory,
#      and the installed build lists CUDA0, the 5090 again through Vulkan,
#      and the Radeon
#   3. unpinned, a model loads on the 5090 through CUDA alone: the Vulkan
#      copy of the card is skipped by PCI id, the Radeon left out
#   4. pinned with CUDA_VISIBLE_DEVICES, the runtime is given an empty
#      GGML_VK_VISIBLE_DEVICES and Vulkan finds no device at all
#   5. `devices: CUDA0,Vulkan1` spreads one model across the 5090 and the
#      Radeon, admitted unmeasured (a Vulkan name cannot be matched), and
#      it answers
#   6. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable is
# dropped, ports are +100, the engine root is a throwaway, teardown is by
# pid. Never `pkill -f eugene_plexus_`: this box is a worker node.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-second-vendor}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
LIB_PORT="${EP_LIB_PORT:-8182}"
AGENT="http://127.0.0.1:$AGENT_PORT"
OWNED_PORTS="$AGENT_PORT $LIB_PORT"
PASS="second-vendor-acceptance-passphrase"
MODEL_DIR="${EP_MODEL_DIR:-C:\\Users\\troyc\\.eugene-plexus\\acceptance-models}"
MODEL="$MODEL_DIR\\Qwen3-0.6B-Q4_K_M.gguf"

FAILURES=0
SKIPPED=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
skip() { printf '  SKIP  %s\n' "$*"; SKIPPED=$((SKIPPED + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
kill_port() { for p in $(listening_pids "$1"); do taskkill //PID "$p" //F >/dev/null 2>&1 || kill -9 "$p" 2>/dev/null; done; }
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }
json_str() { python -c "import json,sys; print(json.dumps(sys.argv[1]))" "$1"; }

A_PID=""
teardown() {
  if [ -n "$TOK" ] && [ -n "$A_PID" ]; then
    for name in plain pinned overflow; do
      curl -s -m 20 -X DELETE -H "Authorization: Bearer $TOK" "$AGENT/v1/runtimes/$name" >/dev/null 2>&1
    done
  fi
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 2; }
  for p in $OWNED_PORTS; do kill_port "$p"; done
  for p in $(runtime_ports); do kill_port "$p"; done
}
RT_PORTS=""
runtime_ports() { printf '%s' "$RT_PORTS"; }
TOK=""
trap teardown EXIT

say "0. isolation"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
for p in $OWNED_PORTS; do
  [ -z "$(listening_pids "$p")" ] || { bad "port $p is already in use; refusing to run"; exit 1; }
done
while IFS='=' read -r name _; do
  case "$name" in EUGENE_PLEXUS_*) unset "$name" ;; esac
done < <(env)
rm -rf "$WORK"; mkdir -p "$WORK/engines"
WORK_WIN=$(win_path "$WORK")
[ -f "$(cygpath -u "$MODEL")" ] || { bad "no model at $MODEL"; exit 1; }
ok "ambient EUGENE_PLEXUS_* cleared; ports $OWNED_PORTS free; model $MODEL"

cat > "$WORK/agent.yaml" <<YAML
firstRunComplete: true
components:
  - name: library
    kind: library
    url: http://127.0.0.1:$LIB_PORT
    spawn:
      configFile: $WORK_WIN\library.yaml
runtimes: []
YAML
printf 'logLevel: INFO\nmodelRoots:\n  - %s\n' "$MODEL_DIR" > "$WORK/library.yaml"

(
  exec env -u EUGENE_PLEXUS_AGENT_CONFIG_FILE \
    EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_WIN\\agent.yaml" \
    EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 \
    EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
    EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY=0 \
    EUGENE_PLEXUS_AGENT_ENGINE_ROOT="$WORK_WIN\\engines" \
    EUGENE_PLEXUS_LIBRARY_STATE_FILE="$WORK_WIN\\library-state.json" \
    "$PY" -m eugene_plexus_agent --unattended > "$WORK/agent.log" 2>&1
) &
A_PID=$!
for _ in $(seq 1 60); do curl -sf -m 2 "$AGENT/healthz" >/dev/null 2>&1 && break; sleep 1; done
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' \
      -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "no session token"; exit 1; }
AUTH=(-H "Authorization: Bearer $TOK")
# One file: the agent mirrors its console to logs/agent.log too, and a line
# count taken across both is not a position in either.
log_all() { cat "$WORK/agent.log" 2>/dev/null; }
# `-v` is how this run reads which devices llama.cpp chose, and extra
# arguments are behind the launch boundary (R7) on purpose. The throwaway
# agent is the operator's here, so it opens the boundary the way an
# operator would.
curl -s -m 20 -X PATCH "${AUTH[@]}" -H 'content-type: application/json' \
  -d '{"allowUnrestrictedEngineLaunch":true}' "$AGENT/v1/config" > "$WORK/config.json"
grep -q '"allowUnrestrictedEngineLaunch"' "$WORK/config.json" || note "config PATCH said: $(head -c 200 "$WORK/config.json")"

# --------------------------------------------------------------------- #
say "1. the default here, and what is offered"
ENGINES=$(curl -s -m 60 "${AUTH[@]}" "$AGENT/v1/engines")
VARIANT=$(printf '%s' "$ENGINES" | jq_ "next((e.get('acquisition') or {}).get('variant') for e in d['engines'] if e['engine']=='llama_cpp')")
COMBINED=$(printf '%s' "$ENGINES" | jq_ "next((v for v in (next((e.get('acquisition') or {}).get('alternatives') or [] for e in d['engines'] if e['engine']=='llama_cpp')) if v.endswith('+vulkan') and v.startswith('win-cuda-13')), '')")
case "$VARIANT" in
  win-cuda-*+vulkan) bad "an integrated GPU made the combined build the default ($VARIANT)" ;;
  win-cuda-*) ok "the default is $VARIANT: an integrated GPU is not a second card" ;;
  None|"") skip "upstream did not answer" ;;
  *) bad "unexpected default '$VARIANT'" ;;
esac
[ -n "$COMBINED" ] && ok "offered: $COMBINED" || bad "no +vulkan build on the menu"

# --------------------------------------------------------------------- #
say "2. the agent installs the combined build"
curl -s -m 60 -X POST "${AUTH[@]}" -H 'content-type: application/json' \
  -d "{\"variant\":\"$COMBINED\"}" "$AGENT/v1/engines/llama_cpp/install" > /dev/null
STATE=""
for _ in $(seq 1 300); do
  STATE=$(curl -s -m 10 "${AUTH[@]}" "$AGENT/v1/engines/llama_cpp/install" | jq_ "d.get('state')")
  case "$STATE" in done|failed|cancelled) break ;; esac
  sleep 2
done
if [ "$STATE" != "done" ]; then
  bad "the install ended '$STATE': $(curl -s "${AUTH[@]}" "$AGENT/v1/engines/llama_cpp/install" | jq_ "d.get('error')")"
  exit 1
fi
MANAGED=$(curl -s -m 60 "${AUTH[@]}" "$AGENT/v1/engines" | jq_ "json.dumps(next((e.get('managed') or {}) for e in d['engines'] if e['engine']=='llama_cpp'))")
MV=$(printf '%s' "$MANAGED" | jq_ "d.get('variant')")
BIN=$(printf '%s' "$MANAGED" | jq_ "d.get('binaryPath')")
DIR=$(dirname "$(cygpath -u "$BIN")")
[ "$MV" = "$COMBINED" ] && ok "installed $MV" || bad "installed '$MV'"
[ -f "$DIR/ggml-cuda.dll" ] && [ -f "$DIR/ggml-vulkan.dll" ] && ok "both backends in one directory" \
  || bad "the directory lacks a backend: $(ls "$DIR" | grep ggml- | tr '\n' ' ')"
LISTED=$("$DIR/llama-server.exe" --list-devices 2>&1 | grep -E "^\s+(CUDA|Vulkan)[0-9]+:" | sed 's/^ *//' | tr '\n' ';')
note "$LISTED"
case "$LISTED" in *CUDA0:*Vulkan0:*Vulkan1:*) ok "it lists CUDA0, the 5090 through Vulkan, and the Radeon" ;;
  *) bad "the combined build lists: $LISTED" ;; esac

# declare <name> <extra json fields>; waits for ready; prints the port
declare_runtime() {
  local name=$1 extra=$2
  local code
  code=$(curl -s -o "$WORK/declare-$name.json" -w '%{http_code}' -m 60 -X POST "${AUTH[@]}" \
    -H 'content-type: application/json' "$AGENT/v1/runtimes" \
    -d "{\"name\":\"$name\",\"engine\":\"llama_cpp\",\"modelPath\":$(json_str "$MODEL"),\"modelAlias\":\"$name\",\"extraArgs\":[\"-v\"]$extra}")
  [ "$code" = "201" ] || { printf 'declare %s: %s %s\n' "$name" "$code" "$(head -c 300 "$WORK/declare-$name.json")" >&2; return 1; }
  local status=""
  for _ in $(seq 1 120); do
    status=$(curl -s -m 5 "${AUTH[@]}" "$AGENT/v1/runtimes" | jq_ "next((r['status'] for r in d['runtimes'] if r['name']=='$name'), '')")
    case "$status" in ready|crashed|exited|stopped) break ;; esac
    sleep 1
  done
  [ "$status" = "ready" ] || { printf '%s ended %s: %s\n' "$name" "$status" "$(curl -s "${AUTH[@]}" "$AGENT/v1/runtimes" | jq_ "[r.get('lastError') for r in d['runtimes'] if r['name']=='$name']")" >&2; return 1; }
  curl -s -m 5 "${AUTH[@]}" "$AGENT/v1/runtimes" | jq_ "next(r.get('port') for r in d['runtimes'] if r['name']=='$name')"
}
answer() {
  curl -s -m 120 "http://127.0.0.1:$1/completion" -H 'content-type: application/json' \
    -d '{"prompt":"The capital of France is","n_predict":8}' | jq_ "d.get('content','')"
}
stop_runtime() { curl -s -m 30 -X DELETE "${AUTH[@]}" "$AGENT/v1/runtimes/$1" >/dev/null; sleep 3; }
# One runtime's lines: the agent prefixes each engine's output with its
# name, and logs what it injected under the same name.
lines_of() { log_all | grep -a -e "\[engine: $1\]" -e "$1: GGML_"; }
# **Checked with here-strings, never `printf "$LINES" | grep -q`.** Under
# `pipefail`, `grep -q` exits at its first match, `printf` dies of SIGPIPE
# writing the rest of a megabyte of `-v` output, and the pipeline reports
# failure for a line that was there. Four executions of this script failed
# every device check that way, on a product doing exactly what it should
# (the lines were in the log each time), and two wrong explanations were
# written here first: log positions, then output arriving late.

# --------------------------------------------------------------------- #
say "3. unpinned: the 5090 through CUDA alone"
RT=plain
PORT=$(declare_runtime plain ',"flags":{"contextSize":2048}') && RT_PORTS="$RT_PORTS $PORT"
if [ -n "${PORT:-}" ]; then
  A=$(answer "$PORT"); [ -n "$A" ] && ok "it answers: '$A'" || bad "no answer"
  stop_runtime plain
  LINES=$(lines_of "$RT")
  grep -q "using device CUDA0" <<<"$LINES" && ok "using device CUDA0" || bad "CUDA0 not used"
  grep -q "skipping device Vulkan0" <<<"$LINES" && ok "the Vulkan copy of the 5090 skipped by its PCI id" \
    || bad "no sign the duplicate was skipped"
  grep -q "using device Vulkan1" <<<"$LINES" && bad "the Radeon was used without being named" \
    || ok "the integrated Radeon left out"
else
  bad "the plain runtime did not come up"
fi

# --------------------------------------------------------------------- #
say "4. pinned: no Vulkan device at all"
RT=pinned
PORT=$(declare_runtime pinned ',"flags":{"contextSize":2048},"env":{"CUDA_VISIBLE_DEVICES":"0"}') && RT_PORTS="$RT_PORTS $PORT"
if [ -n "${PORT:-}" ]; then
  stop_runtime pinned
  LINES=$(lines_of "$RT")
  grep -qi "GGML_VK_VISIBLE_DEVICES" <<<"$LINES" && ok "the agent says it set GGML_VK_VISIBLE_DEVICES" \
    || bad "the injection was not logged"
  grep -q "using device CUDA0" <<<"$LINES" && ok "using device CUDA0" || bad "CUDA0 not used"
  grep -qE "Vulkan[0-9]+ \(" <<<"$LINES" && bad "a Vulkan device appeared for a pinned runtime" \
    || ok "no Vulkan device named: the pin means one card"
else
  bad "the pinned runtime did not come up"
fi

# --------------------------------------------------------------------- #
say "5. named: one model across the 5090 and the Radeon"
ADM=$(curl -s -m 60 -X POST "${AUTH[@]}" -H 'content-type: application/json' "$AGENT/v1/runtimes/admission" \
  -d "{\"name\":\"overflow\",\"engine\":\"llama_cpp\",\"modelPath\":$(json_str "$MODEL"),\"flags\":{\"contextSize\":2048,\"devices\":\"CUDA0,Vulkan1\",\"tensorSplit\":\"3,1\"}}")
FIT=$(printf '%s' "$ADM" | jq_ "d.get('fit')"); DEC=$(printf '%s' "$ADM" | jq_ "d.get('decision')")
[ "$DEC" = "admit" ] && [ "$FIT" = "unknown" ] && ok "admitted unmeasured: a Vulkan name matches no card measured here" \
  || bad "admission said $DEC / $FIT"
RT=overflow
PORT=$(declare_runtime overflow ',"flags":{"contextSize":2048,"devices":"CUDA0,Vulkan1","tensorSplit":"3,1"}') && RT_PORTS="$RT_PORTS $PORT"
if [ -n "${PORT:-}" ]; then
  A=$(answer "$PORT"); [ -n "$A" ] && ok "it answers: '$A'" || bad "no answer"
  stop_runtime overflow
  LINES=$(lines_of "$RT")
  grep -q "using device CUDA0" <<<"$LINES" && grep -q "using device Vulkan1" <<<"$LINES" \
    && ok "both the 5090 and the Radeon hold part of it" || bad "not split across both"
else
  bad "the overflow runtime did not come up"
fi

# --------------------------------------------------------------------- #
say "6. teardown"
teardown
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ] && ok "no owned port still listening" || bad "still listening:$STILL"
A_PID=""; TOK=""

printf '\n'
[ "$SKIPPED" != 0 ] && printf 'second-vendor: %s check(s) SKIPPED\n' "$SKIPPED"
if [ "$FAILURES" = 0 ]; then printf 'second-vendor: all checks passed\n'; exit 0; fi
printf 'second-vendor: %s FAILED\n' "$FAILURES"
exit 1
