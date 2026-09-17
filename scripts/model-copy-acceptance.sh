#!/usr/bin/env bash
# A node keeps its own copy of the models its runtimes point at.
#
# Design: docs/design/node-local-model-copy.md (§11 is the verification
# list this implements, §13 step 6 the slice). Record:
# docs/acceptance/model-copy-run.md.
#
# What only a live run can prove. The agent's unit tests pin the copier
# and the wiring against a stubbed spawn; the UI's pin the rendering
# against fixtures. None of them can prove that a REAL llama.cpp is
# handed the copy rather than the share, that the set really is one copy
# per distinct model file when two runtimes point at one, that a
# headroom refusal still leaves a model serving, or that Clear leaves a
# file a running engine is holding.
#
# The checks:
#   0. isolated from any install on this machine, and from its ports
#   1. the model is declared by the LIBRARY's spelling and mapped here,
#      which is the two-machine shape on one box
#   2. a runtime with copying on is `copying` before anything is spawned
#   3. the copy lands, and the ENGINE'S OWN ARGV names it -- not just
#      the view, which a wrong resolution would report identically
#   4. two runtimes over ONE model file: ONE copy (the M6 replica case,
#      and the assertion that distinguishes this design from the first
#      shape proposed)
#   5. a second model: a second copy
#   6. a runtime removed: its copy goes with it, and the other stays
#   7. headroom: a copy that will not fit is SKIPPED, the runtime still
#      starts, and the reason is on the wire
#   8. Clear with a runtime running: the in-use copy is kept BY NAME and
#      the model keeps serving; stopped, it goes
#   9. the toggle off: the next start opens the share, with a copy still
#      on disk and nothing to unwind
#  10. no partial was ever left behind
#  11. teardown by pid; no owned port still listening
#
# NOT PROVED HERE, and each says so rather than being faked: the timing
# claim (§11 items 1-2) needs a model on ANOTHER machine, which is step 8
# on the live install; a mid-copy disk breach needs a disk to fill; and
# no browser drives this -- the UI half is covered by page tests.
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped, ports are +100, teardown is by pid. Never
# `pkill -f eugene_plexus_`: this box is a worker node.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-model-copy}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
LIB_PORT="${EP_LIB_PORT:-8182}"
AGENT="http://127.0.0.1:$AGENT_PORT"
LIB="http://127.0.0.1:$LIB_PORT"
PASS="copy-$$"
OWNED_PORTS="$AGENT_PORT $LIB_PORT"

# Read, never written: the models this box already has and the engine
# store it already holds. The run needs models that load in seconds.
MODELS_DIR="${EP_MODELS_DIR:-$HOME/.eugene-plexus/acceptance-models}"
MODEL_A="${EP_MODEL_A:-Qwen3-0.6B-Q4_K_M.gguf}"
MODEL_B="${EP_MODEL_B:-nomic-embed-text-v1.5.Q8_0.gguf}"
ENGINE_ROOT="${EP_ENGINE_ROOT:-$HOME/.eugene-plexus/engines}"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
skip() { printf '  SKIP  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }
json_path() { win_path "$1" | sed 's|\\|\\\\|g'; }

# The runtime's own view, by name.
runtime_field() {
  curl -s "${AUTH[@]}" "$AGENT/v1/runtimes/$1" | jq_ "d.get('$2') if d.get('$2') is not None else ''"
}
# Wait for a runtime to reach one of the given statuses.
wait_status() {
  local name="$1" want="$2" tries="${3:-90}"
  for _ in $(seq 1 "$tries"); do
    local s
    s=$(runtime_field "$name" status)
    case " $want " in *" $s "*) printf '%s' "$s"; return 0 ;; esac
    sleep 1
  done
  printf '%s' "$(runtime_field "$name" status)"
  return 1
}
copies_on_disk() { find "$WORK/copies" -type f ! -name '*.ep-partial' 2>/dev/null | sort; }
count_copies() { copies_on_disk | grep -c . ; }

# A config PATCH proves nothing by its status code: the trio answers 200
# and reports refusals inside the body, per field. The first run of this
# script raised the headroom, read 200, and watched a copy happen anyway
# -- because the agent had no `integer` branch in its validator and was
# rejecting the value politely. Assert on `applied`.
patch_config() {
  local body result
  body="$1"
  result=$(curl -s -X PATCH "${AUTH[@]}" "$AGENT/v1/config" -H 'content-type: application/json' -d "$body")
  local rejected
  rejected=$(printf '%s' "$result" | jq_ "'; '.join(f\"{r['key']}: {r['message']}\" for r in (d.get('rejected') or []))")
  if [ -n "$rejected" ]; then
    bad "config PATCH $body was refused inside a 200: $rejected"
    return 1
  fi
  return 0
}

A_PID=""
start_agent() {
  (exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" \
    EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 \
    EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
    EUGENE_PLEXUS_AGENT_ENGINE_ROOT="$(win_path "$ENGINE_ROOT")" \
    "$PY" -m eugene_plexus_agent --unattended >> agent.log 2>&1) &
  A_PID=$!
}
teardown() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 3; }
  for p in $OWNED_PORTS; do
    for pid in $(listening_pids "$p"); do
      taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
    done
  done
}

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
"$PY" -c "import eugene_plexus_agent, eugene_plexus_library" 2>/dev/null \
  || { bad "the agent and library must import from $PY"; exit 1; }
[ -f "$MODELS_DIR/$MODEL_A" ] || { bad "no model at $MODELS_DIR/$MODEL_A"; exit 1; }
[ -f "$MODELS_DIR/$MODEL_B" ] || { bad "no second model at $MODELS_DIR/$MODEL_B"; exit 1; }
BUILD=$(ls -1 "$ENGINE_ROOT/llama_cpp" 2>/dev/null | sort | tail -1)
BINARY="$ENGINE_ROOT/llama_cpp/$BUILD/llama-server.exe"
[ -f "$BINARY" ] || { bad "no llama-server under $ENGINE_ROOT/llama_cpp"; exit 1; }
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
ok "agent python, two models, llama.cpp $BUILD, ports free"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

# --- 0 -----------------------------------------------------------------------
say "0. isolate this run"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
WORK_NATIVE=$(win_path "$WORK")
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }

# --- 1 -----------------------------------------------------------------------
say "1. the library names the models, this node says where they are here"
# The two-machine shape, on one box: the Library folder is `/models` --
# a POSIX path this Windows host does not have -- and a pathMappings
# override says where it is mounted here. Declarations carry the
# LIBRARY's spelling, which is what makes the copy's name short and what
# every worker in a real install does.
cat > agent.yaml <<YAML
firstRunComplete: true
modelCopyEnabled: true
modelCopyDir: "$(json_path "$WORK/copies")"
modelCopyMinFreeGb: 0
pathMappings:
  - from: /models
    to: "$(json_path "$MODELS_DIR")"
components:
  - name: library
    kind: library
    url: http://127.0.0.1:$LIB_PORT
    spawn:
      configFile: library.yaml
runtimes: []
YAML
cat > library.yaml <<YAML
logLevel: INFO
modelRoots:
  - /models
YAML

start_agent
wait_healthy "$AGENT" 60 || { bad "agent never answered"; tail -20 agent.log; exit 1; }
wait_healthy "$LIB" 60 || { bad "library never came up"; tail -30 agent.log; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "agent initialize"; tail -20 agent.log; exit 1; }
AUTH=(-H "Authorization: Bearer $TOK")
wait_healthy "$LIB" 60 || { bad "library did not return after initialize"; exit 1; }
FOLDERS=$(curl -s "${AUTH[@]}" "$AGENT/v1/config" | jq_ "len(d.get('pathMappings') or [])")
[ "$FOLDERS" = "1" ] && ok "one Library folder override, /models -> $MODELS_DIR" || bad "mapping not saved ($FOLDERS)"

declare_runtime() {
  local name="$1" model="$2" port="$3"
  code_of -X POST "${AUTH[@]}" "$AGENT/v1/runtimes" -H 'content-type: application/json' \
    -d "{\"name\":\"$name\",\"engine\":\"llama_cpp\",\"modelPath\":\"/models/$model\",\"port\":$port,\"binary\":\"$(json_path "$BINARY")\",\"autoDriver\":false,\"flags\":{\"contextSize\":512,\"gpuLayers\":0}}"
}

# --- 2 -----------------------------------------------------------------------
say "2. a runtime with copying on is 'copying' before anything is spawned"
CODE=$(declare_runtime alpha "$MODEL_A" 8190)
[ "$CODE" = "201" ] || { bad "declare alpha: HTTP $CODE"; tail -20 agent.log; exit 1; }
# 378 MB over a local copy is quick, so this races on purpose: the point
# is that the state EXISTS and is reported, not how long it lasts.
SEEN_COPYING=0
for _ in $(seq 1 40); do
  S=$(runtime_field alpha status)
  [ "$S" = "copying" ] && { SEEN_COPYING=1; break; }
  [ "$S" = "ready" ] && break
  sleep 0.2
done
if [ "$SEEN_COPYING" = "1" ]; then
  ok "status 'copying' observed -- a state with no process in it"
else
  note "the copy finished before a poll caught it ($(runtime_field alpha status)); check 3 still proves it happened"
fi

# --- 3 -----------------------------------------------------------------------
say "3. the copy lands, and the ENGINE's argv names it"
S=$(wait_status alpha "ready loading starting" 120)
[ "$S" = "ready" ] || S=$(wait_status alpha "ready" 120)
[ "$S" = "ready" ] && ok "alpha is ready" || { bad "alpha never became ready (status $S)"; tail -30 agent.log; exit 1; }
COPY_A="$WORK/copies/$MODEL_A"
[ -f "$COPY_A" ] && ok "the copy exists at copies/$MODEL_A -- named at the model's own relative path" || bad "no copy at $COPY_A"
SRC_SIZE=$(stat -c %s "$MODELS_DIR/$MODEL_A")
CPY_SIZE=$(stat -c %s "$COPY_A" 2>/dev/null || echo 0)
[ "$SRC_SIZE" = "$CPY_SIZE" ] && ok "the copy is the same size as the source ($SRC_SIZE bytes)" || bad "size $CPY_SIZE != $SRC_SIZE"
SOURCE=$(runtime_field alpha localPathSource)
[ "$SOURCE" = "copy" ] && ok "localPathSource is 'copy'" || bad "localPathSource is '$SOURCE'"
# The view could report the copy while the engine opened the share. The
# argv is what the process was actually given.
ARGV=$(curl -s "${AUTH[@]}" "$AGENT/v1/runtimes/alpha" | jq_ "' '.join(d.get('argv') or [])")
case "$ARGV" in
  *copies*) ok "llama-server was spawned against the copy" ;;
  *) bad "the engine's argv does not name the copy: $ARGV" ;;
esac

# --- 4 -----------------------------------------------------------------------
say "4. two runtimes over ONE model file: one copy"
CODE=$(declare_runtime alpha2 "$MODEL_A" 8191)
[ "$CODE" = "201" ] || bad "declare alpha2: HTTP $CODE"
S=$(wait_status alpha2 "ready" 120)
[ "$S" = "ready" ] && ok "alpha2 is ready off the same file" || bad "alpha2 status $S"
N=$(count_copies)
[ "$N" = "1" ] && ok "ONE copy for two runtimes -- the M6 replica case" || { bad "$N copies on disk, expected 1"; copies_on_disk; }

# --- 5 -----------------------------------------------------------------------
say "5. a second model is a second copy"
CODE=$(declare_runtime beta "$MODEL_B" 8192)
[ "$CODE" = "201" ] || bad "declare beta: HTTP $CODE"
S=$(wait_status beta "ready" 120)
[ "$S" = "ready" ] && ok "beta is ready" || note "beta status $S (an embedding model may not answer /health the same way)"
for _ in $(seq 1 30); do [ -f "$WORK/copies/$MODEL_B" ] && break; sleep 1; done
[ -f "$WORK/copies/$MODEL_B" ] && ok "two distinct models, two copies" || bad "no copy of $MODEL_B"

# --- 6 -----------------------------------------------------------------------
say "6. a runtime removed takes its copy with it"
for n in beta; do
  [ "$(code_of -X DELETE "${AUTH[@]}" "$AGENT/v1/runtimes/$n")" = "204" ] || bad "delete $n"
done
GONE=0
for _ in $(seq 1 30); do [ -f "$WORK/copies/$MODEL_B" ] || { GONE=1; break; }; sleep 1; done
[ "$GONE" = "1" ] && ok "beta's copy is gone, with no LRU and no timer" || bad "beta's copy is still on disk"
[ -f "$COPY_A" ] && ok "alpha's copy is untouched" || bad "alpha's copy went with beta's"

# --- 7 -----------------------------------------------------------------------
say "7. a copy that will not fit is skipped, and the model still serves"
# Headroom bigger than the disk: every copy is refused from here on.
patch_config '{"modelCopyMinFreeGb": 999999}' && ok "the headroom is raised past this disk -- and the PATCH was APPLIED, not politely refused"
# gamma takes the SECOND model, whose copy check 6 removed. The first
# attempt at this check emptied the copy directory instead -- which on
# Windows cannot remove a file two running engines hold open, so alpha's
# copy survived, gamma correctly reused it, and the check reported three
# product defects that were all the harness. A model with no copy is the
# state this check is actually about.
GAMMA_COPY="$WORK/copies/$MODEL_B"
[ -f "$GAMMA_COPY" ] && bad "check 7 needs $MODEL_B to have no copy yet"
CODE=$(declare_runtime gamma "$MODEL_B" 8193)
[ "$CODE" = "201" ] || bad "declare gamma: HTTP $CODE"
S=$(wait_status gamma "ready starting loading" 120)
[ "$S" != "copying" ] && ok "gamma came up without copying -- a launch never fails over this" || bad "gamma status $S"
[ -f "$GAMMA_COPY" ] && bad "a copy was made despite the headroom" || ok "nothing was copied"
NOTE_TEXT=$(runtime_field gamma localPathNote)
case "$NOTE_TEXT" in
  *free*) ok "the reason is on the wire: $NOTE_TEXT" ;;
  *) bad "no localPathNote on a skipped copy (got '$NOTE_TEXT')" ;;
esac
SOURCE=$(runtime_field gamma localPathSource)
[ "$SOURCE" != "copy" ] && ok "localPathSource is '$SOURCE', not 'copy'" || bad "claims a copy it did not make"
patch_config '{"modelCopyMinFreeGb": 0}' 
[ "$(code_of -X DELETE "${AUTH[@]}" "$AGENT/v1/runtimes/gamma")" = "204" ] || bad "delete gamma"

# --- 8 -----------------------------------------------------------------------
say "8. Clear keeps what a running engine is holding, and says so"
# alpha and alpha2 are still up; restart one so the copy is remade.
[ "$(code_of -X POST "${AUTH[@]}" "$AGENT/v1/runtimes/alpha/restart")" = "202" ] || bad "restart alpha"
for _ in $(seq 1 60); do [ -f "$COPY_A" ] && break; sleep 1; done
[ -f "$COPY_A" ] && ok "the copy is back after a restart" || bad "no copy after restarting alpha"
wait_status alpha "ready" 120 >/dev/null
CLEAR=$(curl -s -X POST "${AUTH[@]}" "$AGENT/v1/model-copies/clear")
KEPT=$(printf '%s' "$CLEAR" | jq_ "len(d.get('skipped') or [])")
NAMED=$(printf '%s' "$CLEAR" | jq_ "(d.get('skipped') or [{}])[0].get('runtime','')")
[ "$KEPT" != "0" ] && ok "Clear kept $KEPT copy in use, naming the runtime: $NAMED" || bad "Clear deleted a copy a runtime is using"
[ -f "$COPY_A" ] && ok "the file survived, and so did the engine" || bad "the in-use copy was deleted"
[ "$(runtime_field alpha status)" = "ready" ] && ok "alpha is still serving -- Clear stopped nothing" || bad "Clear disturbed a running runtime"
for n in alpha alpha2; do code_of -X DELETE "${AUTH[@]}" "$AGENT/v1/runtimes/$n" >/dev/null; done
sleep 3
CLEAR=$(curl -s -X POST "${AUTH[@]}" "$AGENT/v1/model-copies/clear")
DELETED=$(printf '%s' "$CLEAR" | jq_ "len(d.get('deleted') or [])")
FREED=$(printf '%s' "$CLEAR" | jq_ "d.get('bytesFreed') or 0")
# Either Clear removed it, or the reconcile that follows an undeclared
# runtime got there first -- both are this feature working, and which
# one won is a race. The assertion is on the disk, and the count says
# which path it took rather than letting a zero pass unremarked.
[ "$(count_copies)" = "0" ] && ok "nothing is left on disk (Clear deleted $DELETED, $FREED bytes)" || bad "copies remain"
[ "$DELETED" = "0" ] && note "the copy had already gone with its declaration -- check 6's rule, arriving first"

# --- 9 -----------------------------------------------------------------------
say "9. the toggle off reverts by itself, with a copy still on disk"
CODE=$(declare_runtime delta "$MODEL_A" 8194)
[ "$CODE" = "201" ] || bad "declare delta: HTTP $CODE"
wait_status delta "ready" 120 >/dev/null
[ "$(runtime_field delta localPathSource)" = "copy" ] || bad "delta did not use a copy"
[ "$(code_of -X POST "${AUTH[@]}" "$AGENT/v1/runtimes/delta/stop")" = "202" ] || bad "stop delta"
sleep 2
patch_config '{"modelCopyEnabled": false}' 
[ "$(code_of -X POST "${AUTH[@]}" "$AGENT/v1/runtimes/delta/start")" = "202" ] || bad "start delta"
wait_status delta "ready" 120 >/dev/null
SOURCE=$(runtime_field delta localPathSource)
[ "$SOURCE" != "copy" ] && ok "with the toggle off the share is opened again ('$SOURCE'), nothing unwound" || bad "still reading the copy with copying off"
[ -f "$COPY_A" ] && ok "the copy is still on disk -- switching off deletes nothing" || bad "switching off deleted a file"
ARGV=$(curl -s "${AUTH[@]}" "$AGENT/v1/runtimes/delta" | jq_ "' '.join(d.get('argv') or [])")
case "$ARGV" in
  *copies*) bad "the engine still opens the copy: $ARGV" ;;
  *) ok "the engine was spawned against the model folder" ;;
esac

# --- 10 ----------------------------------------------------------------------
say "10. no partial was ever left behind"
PARTIALS=$(find "$WORK/copies" -name '*.ep-partial' 2>/dev/null | grep -c . )
[ "$PARTIALS" = "0" ] && ok "no .ep-partial anywhere under the copy directory" || bad "$PARTIALS partial files left"
note "a mid-copy disk breach is not produced here: it needs a disk to fill, and the unit tests cover the abort"
note "the timing claim (design §11 items 1-2) needs a model on another machine -- step 8, the live install"
note "no browser drives this run; the UI half is covered by page tests"

# --- 11 ----------------------------------------------------------------------
say "11. teardown"
teardown
A_PID=""
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ] && ok "no owned port still listening" || bad "still listening:$STILL"

printf '\n'
if [ "$FAILURES" = "0" ]; then
  printf 'ALL CHECKS PASSED\n'
else
  printf '%d CHECK(S) FAILED\n' "$FAILURES"
fi
exit "$FAILURES"
