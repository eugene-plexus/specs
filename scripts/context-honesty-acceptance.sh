#!/usr/bin/env bash
# Install-paths §9 step 7 -- context-window honesty, against two real engines.
#
# Open call #3 was settled 2026-09-12 as **let the engine refuse**, so
# there is no tokenizer in this stack and nothing counts a prompt. What
# has to be proved live is that the two backends behave the two
# different ways the design assumes, and that we report each honestly:
#
#   * `llama-server` COUNTS and REFUSES. It answers an over-long prompt
#     with HTTP 400 `exceed_context_size_error` naming both numbers. Our
#     job is to get out of the way -- and specifically not to flatten it
#     into a 502, which made the gateway cascade a request no backend
#     could serve and hand the caller a retryable error.
#   * Ollama COUNTS NOTHING and TRUNCATES. It fits an over-long prompt
#     by discarding the middle of the conversation and answers anyway,
#     200, no flag. Our job is to notice, after the fact, from the only
#     number it does report.
#
# A fixture cannot prove either. Both are properties of somebody else's
# server, and the recurring failure in this project is a check that
# asserts a property of its own test double -- step 6's first run
# demanded tool-call fragmentation that no local engine produces.
#
# The checks:
#   0. this run is isolated from any install on this machine
#   1. the llama.cpp driver reports the window /props resolved
#   2. the ollama driver reports the window /api/ps resolved
#   3. GET /v1/models publishes a context_length for both
#   4. llama.cpp refuses an over-long prompt as a 400, not a 502
#   5. that 400 still names both of the backend's own numbers
#   6. it does NOT cascade to a tier that would have answered
#   7. a prompt that fits is still served normally
#   8. ollama truncates instead of refusing -- 200, and the evidence
#   9. the gateway flags it as prompt_truncated
#  10. the completion reports the window that applied to it
#  11. a prompt that arrived intact is NOT flagged
#  12. a streamed request carries the flag on its final frame
#  13. the truncation is in the gateway log too
#
# Design: docs/design/agent-clients-and-tool-calling.md §6
#
# **Safe to run beside a live install, in two dimensions.** Ports: the
# agent binds 8179 rather than 8079, the script refuses to start if a
# port it wants is taken, and it tears down BY PORT -- every other
# script in this directory ends with `pkill -f eugene_plexus_`, which on
# a machine that is also a worker node kills the operator's own agent
# and everything under it.
#
# **And state, which is the dimension the port-only version missed.**
# `install.ps1` sets `EUGENE_PLEXUS_AGENT_CONFIG_FILE` in the USER
# environment on purpose -- a scheduled task inherits the user
# environment, and that is how the installed agent finds its install.
# Every shell on that account inherits it too. So a throwaway agent
# started from one loads the operator's `agent.yaml` and `node.yaml`,
# adopts the real node's identity, and announces its own address to the
# real control root -- repointing a live install at a port that dies
# when the script exits, with nothing in either process saying so.
# Check 0 refuses to run unless the environment is clean. Discovered by
# doing it: this script's first run moved `Amish_Station` to :8179.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-ctx-live}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
AGENT="http://127.0.0.1:$AGENT_PORT"
GW="${EP_GW:-http://127.0.0.1:8080}"
LLAMA_DRIVER_PORT="${EP_LLAMA_DRIVER_PORT:-8193}"
OLLAMA_DRIVER_PORT="${EP_OLLAMA_DRIVER_PORT:-8194}"
PASS="ctx-live-$$"

OLLAMA="${EP_OLLAMA:-http://127.0.0.1:11434}"
# A deliberately small window, so a prompt this script can build in
# memory overruns it. Ollama 0.34 auto-sizes to the model's full trained
# context (131072 for an 8B, ~22 GB of VRAM) with nothing set, which is
# a fine default and useless for provoking truncation -- so the window
# is pinned on a derived model rather than by restarting the operator's
# Ollama, which on this machine is serving a live install.
OLLAMA_MODEL="${EP_OLLAMA_MODEL:-ep-ctx-probe:latest}"
OLLAMA_BASE="${EP_OLLAMA_BASE:-huihui_ai/dolphin3-abliterated:8b-llama3.1-q4_K_M}"
OLLAMA_CTX="${EP_OLLAMA_CTX:-2048}"

# llama.cpp, started by this script so the window is ours to choose.
LLAMA_BIN="${EP_LLAMA_BIN:-/c/Users/troyc/OneDrive/Desktop/llamacpp/llama-server.exe}"
LLAMA_GGUF="${EP_LLAMA_GGUF:-/c/Users/troyc/.lmstudio/models/lmstudio-community/Qwen3.6-27B-GGUF/Qwen3.6-27B-Q4_K_M.gguf}"
LLAMA_PORT="${EP_LLAMA_PORT:-8299}"
LLAMA_CTX="${EP_LLAMA_CTX:-512}"
LLAMA_MODEL="ctx-probe"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }

OWNED_PORTS="$AGENT_PORT 8080 8082 8083 $LLAMA_DRIVER_PORT $OLLAMA_DRIVER_PORT $LLAMA_PORT"
STARTED_LLAMA=0
CREATED_OLLAMA_MODEL=0

free_port() { # port
  # By port, never by pid or command pattern. Windows lets a second
  # process bind an already-bound loopback port while the OLDEST binder
  # keeps serving, so a leftover from a previous run answers for the one
  # this run just started -- M10 read a two-runs-old reply that way.
  for pid in $(netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u); do
    taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
  done
}

teardown() {
  for p in $OWNED_PORTS; do free_port "$p"; done
  # Leave the operator's Ollama exactly as we found it. The derived
  # model is the only thing this script adds to it.
  if [ "$CREATED_OLLAMA_MODEL" = "1" ]; then
    curl -s -m 30 -X DELETE "$OLLAMA/api/delete" \
      -H 'content-type: application/json' -d "{\"model\":\"$OLLAMA_MODEL\"}" >/dev/null 2>&1
  fi
}

# --------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------- #

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
[ -f "$LLAMA_BIN" ] || { bad "no llama-server at $LLAMA_BIN (set EP_LLAMA_BIN)"; exit 1; }
[ -f "$LLAMA_GGUF" ] || { bad "no gguf at $LLAMA_GGUF (set EP_LLAMA_GGUF)"; exit 1; }
curl -sf -m 3 "$OLLAMA/api/tags" >/dev/null || { bad "ollama is not answering at $OLLAMA"; exit 1; }
curl -s -m 5 "$OLLAMA/api/tags" | grep -q "$OLLAMA_BASE" || { bad "$OLLAMA_BASE is not pulled into ollama"; exit 1; }
for p in $OWNED_PORTS; do
  if netstat -ano 2>/dev/null | grep ":$p " | grep -q LISTENING; then
    bad "port $p is already in use; set the matching EP_* variable or stop it"
    exit 1
  fi
done
ok "agent python, llama-server, a gguf, a live ollama, and every port free"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

# **Isolate the state, not just the port.** `install.ps1` sets
# `EUGENE_PLEXUS_AGENT_CONFIG_FILE` in the USER environment on purpose --
# a scheduled task inherits the user environment and that is how the
# installed agent finds its install. The consequence is that every shell
# on that account inherits it too, so a throwaway agent started here
# loads the operator's `agent.yaml` AND `node.yaml`: it adopts the real
# node's identity, tries to spawn the real components on their real
# ports, and -- since M9 -- **announces its own address to the real
# control root**, silently repointing a live install at a port that dies
# when this script exits. Binding 8179 does not help with any of that.
#
# So: drop every ambient EUGENE_PLEXUS_* variable, then set only what
# this run needs. The loop is the load-bearing part; naming the two
# known variables would go stale the first time a third one appears.
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
# A native path, because the value is read by a Windows Python that does
# not know what `/tmp` means. `cygpath` where it exists, `$WORK`
# unchanged where the shell and the interpreter already agree.
WORK_NATIVE=$(cygpath -w "$WORK" 2>/dev/null || printf '%s' "$WORK")
export EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml"
export EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1
export EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT"

say "0. this run is isolated from any install on this machine"
LEAKED=$(env | grep '^EUGENE_PLEXUS_' | grep -Fv -e "EUGENE_PLEXUS_AGENT_CONFIG_FILE=$WORK_NATIVE/agent.yaml" -e 'EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1' -e "EUGENE_PLEXUS_AGENT_BIND_PORT=$AGENT_PORT")
[ -z "$LEAKED" ] && ok "no ambient EUGENE_PLEXUS_* variable survives into this run"   || bad "ambient config leaked in, and would point this run at a real install: $LEAKED"

# --------------------------------------------------------------------- #
# the two engines
# --------------------------------------------------------------------- #

say "an ollama model with a pinned $OLLAMA_CTX-token window"
# Derived rather than configured globally: OLLAMA_CONTEXT_LENGTH would
# mean restarting the operator's Ollama, and on this machine that is the
# backend a live install routes to.
curl -s -m 120 -X POST "$OLLAMA/api/create" -H 'content-type: application/json' \
  -d "{\"model\":\"$OLLAMA_MODEL\",\"from\":\"$OLLAMA_BASE\",\"parameters\":{\"num_ctx\":$OLLAMA_CTX}}" \
  | tail -1
CREATED_OLLAMA_MODEL=1
curl -s -m 10 "$OLLAMA/api/tags" | grep -q "${OLLAMA_MODEL%%:*}" \
  && ok "created $OLLAMA_MODEL" || { bad "could not create $OLLAMA_MODEL"; exit 1; }

say "llama-server with -c $LLAMA_CTX"
"$LLAMA_BIN" -m "$LLAMA_GGUF" -c "$LLAMA_CTX" -ngl 99 \
  --host 127.0.0.1 --port "$LLAMA_PORT" --alias "$LLAMA_MODEL" >"$WORK/llama.log" 2>&1 &
STARTED_LLAMA=1
for _ in $(seq 1 180); do
  curl -sf -m 2 "http://127.0.0.1:$LLAMA_PORT/props" >/dev/null 2>&1 && break
  sleep 1
done
RESOLVED=$(curl -s -m 5 "http://127.0.0.1:$LLAMA_PORT/props" | jq_ "(d.get('default_generation_settings') or {}).get('n_ctx')" 2>/dev/null)
[ "$RESOLVED" = "$LLAMA_CTX" ] && ok "llama-server resolved n_ctx=$RESOLVED" \
  || { bad "llama-server did not come up with n_ctx=$LLAMA_CTX (got '$RESOLVED')"; tail -5 "$WORK/llama.log"; exit 1; }

# --------------------------------------------------------------------- #
# the control plane
# --------------------------------------------------------------------- #

say "start the agent; it declares control, gateway and library itself"
"$PY" -m eugene_plexus_agent --unattended >"$WORK/agent.log" 2>&1 &
wait_healthy "$AGENT" 60 || { bad "agent never answered"; tail -20 "$WORK/agent.log"; exit 1; }
# A 409 here means the agent found an already-initialized install --
# i.e. the isolation above failed and this run is sitting on somebody's
# real state. Stop rather than carry on against it.
INIT=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}")
TOK=$(printf '%s' "$INIT" | jq_ "d.get('sessionToken') or ''" 2>/dev/null)
[ -n "$TOK" ] || { bad "no operator token -- the agent may have adopted an existing install: $INIT"; exit 1; }
wait_healthy "$GW" 90 || { bad "gateway never answered"; exit 1; }
ok "agent and gateway up"

add_driver() { # name port provider model [baseUrl]
  curl -s -o /dev/null -X POST "$AGENT/v1/components" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' \
    -d "{\"name\":\"$1\",\"kind\":\"inference-driver\",\"url\":\"http://127.0.0.1:$2\",\"spawn\":{\"configFile\":\"$1.yaml\"}}"
  sleep 3
  local body="{\"provider\":\"$3\",\"modelId\":\"$4\""
  [ -n "${5:-}" ] && body="$body,\"baseUrl\":\"$5\""
  body="$body}"
  curl -s -o /dev/null -X PATCH "http://127.0.0.1:$2/v1/config" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' -d "$body"
  curl -s -o /dev/null -X POST "$AGENT/v1/components/$1/restart" -H "Authorization: Bearer $TOK" -d '{}'
}

say "two drivers: one on llama.cpp, one on ollama"
add_driver ctx-llama "$LLAMA_DRIVER_PORT" openai_compat_custom "$LLAMA_MODEL" "http://127.0.0.1:$LLAMA_PORT"
add_driver ctx-ollama "$OLLAMA_DRIVER_PORT" ollama_local "$OLLAMA_MODEL"
sleep 10

# --- 1 -----------------------------------------------------------------------
say "1. the llama.cpp driver reports the window /props resolved"
A_INFO=$(curl -s -m 15 "http://127.0.0.1:$LLAMA_DRIVER_PORT/v1/info" -H "Authorization: Bearer $TOK")
A_CTX=$(printf '%s' "$A_INFO" | jq_ "(d.get('capabilities') or {}).get('maxContextTokens')" 2>/dev/null)
echo "  maxContextTokens: $A_CTX"
[ "$A_CTX" = "$LLAMA_CTX" ] && ok "llama.cpp driver advertises $A_CTX" \
  || bad "expected $LLAMA_CTX, got '$A_CTX': $A_INFO"

# --- 2 -----------------------------------------------------------------------
say "2. the ollama driver reports the window /api/ps resolved"
# The headline of the advertising half. Ollama's OpenAI-compatible
# surface carries no window at all and /api/show carries only the trained
# maximum; /api/ps is the only place the number it actually chose
# appears. Before this, every unsupervised backend reported nothing.
# `/api/ps` is empty until something loads the model, so warm it first --
# the same thing a first real request does.
curl -s -o /dev/null -m 300 -X POST "$OLLAMA/v1/chat/completions" -H 'content-type: application/json' \
  -d "{\"model\":\"$OLLAMA_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":2}"
curl -s -o /dev/null -X POST "$AGENT/v1/components/ctx-ollama/restart" -H "Authorization: Bearer $TOK" -d '{}'
sleep 8
B_INFO=$(curl -s -m 15 "http://127.0.0.1:$OLLAMA_DRIVER_PORT/v1/info" -H "Authorization: Bearer $TOK")
B_CTX=$(printf '%s' "$B_INFO" | jq_ "(d.get('capabilities') or {}).get('maxContextTokens')" 2>/dev/null)
echo "  maxContextTokens: $B_CTX"
[ "$B_CTX" = "$OLLAMA_CTX" ] && ok "ollama driver advertises $B_CTX" \
  || bad "expected $OLLAMA_CTX, got '$B_CTX': $B_INFO"

# --- 3 -----------------------------------------------------------------------
say "3. GET /v1/models publishes a context_length for both"
sleep 16
MODELS=$(curl -s -m 20 "$GW/v1/models" -H "Authorization: Bearer $TOK")
printf '%s' "$MODELS" | PYTHONUTF8=1 python -c "
import sys, json
d = json.load(sys.stdin)
for m in d['data']:
    print('  %-28s context_length=%s' % (m['id'], m.get('x_eugene_plexus', {}).get('context_length')))
"
MISSING=$(printf '%s' "$MODELS" | jq_ "len([m for m in d['data'] if m.get('x_eugene_plexus',{}).get('context_length') is None])" 2>/dev/null)
[ "$MISSING" = "0" ] && ok "every served model publishes a window" \
  || bad "$MISSING model(s) still publish no window"

# --------------------------------------------------------------------- #
# llama.cpp: it counts, and it refuses
# --------------------------------------------------------------------- #

say "a two-tier slot: llama.cpp first, ollama behind it"
# Check 6 needs somewhere for a cascade to GO. Without a second tier,
# "did not cascade" and "had nowhere to cascade to" look identical.
curl -s -o /dev/null -X PATCH "$GW/v1/config" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d "{\"modelSlots\":[{\"model\":\"$LLAMA_MODEL\",\"targets\":[\"$LLAMA_MODEL\",\"$OLLAMA_MODEL\"]}]}"
sleep 18

say "4-6. an over-long prompt to an engine that counts"
BIG=$(PYTHONUTF8=1 python -c "
import json
print(json.dumps({
  'model': '$LLAMA_MODEL',
  'messages': [{'role': 'user', 'content': 'the quick brown fox jumps over the lazy dog. ' * 1500}],
  'max_tokens': 8,
}))
")
printf '%s' "$BIG" > big.json
CODE=$(curl -s -m 300 -o refusal.json -w '%{http_code}' -X POST "$GW/v1/chat/completions" \
  -H "Authorization: Bearer $TOK" -H 'content-type: application/json' -d @big.json)
echo "  HTTP $CODE"
echo "  body: $(head -c 400 refusal.json)"

# --- 4 -----------------------------------------------------------------------
# 400 is itself the proof it did not cascade: the gateway returns 400
# only on the hard-fail path, and a cascade that exhausted every tier
# returns 502. Before this milestone the driver flattened the backend's
# 400 into a 502, so this request was retried against every tier and came
# back retryable -- which is what makes a harness loop.
[ "$CODE" = "400" ] && ok "refused as 400 invalid_request_error, not a retryable 502" \
  || bad "got HTTP $CODE; a 502 here means the backend's 4xx was flattened again"

# --- 5 -----------------------------------------------------------------------
DETAIL=$(cat refusal.json)
BOTH=0
case "$DETAIL" in *"$LLAMA_CTX"*) BOTH=$((BOTH + 1)) ;; esac
case "$DETAIL" in *exceed_context_size_error*) BOTH=$((BOTH + 1)) ;; esac
case "$DETAIL" in *n_prompt_tokens*) BOTH=$((BOTH + 1)) ;; esac
[ "$BOTH" = "3" ] && ok "the caller sees the backend's own count, window and error type" \
  || bad "the backend's numbers did not survive the trip: $DETAIL"

# --- 6 -----------------------------------------------------------------------
# If it had cascaded, ollama sits in tier 2 with a window of its own and
# would have TRUNCATED and answered 200 -- so a 200 here is not a
# near-miss, it is the failure: a wrong answer in place of a right error.
SERVED=$(printf '%s' "$DETAIL" | jq_ "d.get('choices') is not None" 2>/dev/null)
[ "$SERVED" != "True" ] && ok "tier 2 was not tried; the refusal stands" \
  || bad "it cascaded and tier 2 answered -- a truncated answer in place of an exact refusal"

# --- 7 -----------------------------------------------------------------------
say "7. a prompt that fits is still served normally"
FITS=$(curl -s -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$LLAMA_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK.\"}],\"max_tokens\":8}")
FIN=$(printf '%s' "$FITS" | jq_ "d['choices'][0]['finish_reason']" 2>/dev/null)
[ -n "$FIN" ] && ok "a fitting prompt answered normally (finish_reason=$FIN)" \
  || bad "the refusal broke ordinary requests too: $(head -c 300 <<<"$FITS")"

# --------------------------------------------------------------------- #
# ollama: it counts nothing, and it truncates
# --------------------------------------------------------------------- #

say "8-10. a prompt far past the window, to an engine that does not refuse"
# Canaries in each message, so "it truncated" is a statement about WHICH
# parts arrived rather than an inference from a token count alone.
TRUNC=$(PYTHONUTF8=1 python -c "
import json
print(json.dumps({
  'model': '$OLLAMA_MODEL',
  'messages': [
    {'role': 'system', 'content': 'CANARY-SYS. ' * 10},
    {'role': 'user', 'content': 'CANARY-FIRST. ' + 'filler text here. ' * 1200},
    {'role': 'assistant', 'content': 'ok. ' + 'more filler. ' * 1200},
    {'role': 'user', 'content': 'CANARY-MID. ' + 'yet more filler. ' * 1200},
    {'role': 'assistant', 'content': 'ok. ' + 'padding. ' * 1200},
    {'role': 'user', 'content': 'CANARY-LAST. Reply with the single word OK.'},
  ],
  'max_tokens': 8,
}))
")
printf '%s' "$TRUNC" > trunc.json
CHARS=$(printf '%s' "$TRUNC" | jq_ "sum(len(m['content']) for m in d['messages'])")
TCODE=$(curl -s -m 300 -o truncated.json -w '%{http_code}' -X POST "$GW/v1/chat/completions" \
  -H "Authorization: Bearer $TOK" -H 'content-type: application/json' -d @trunc.json)
PT=$(jq_ "d.get('usage',{}).get('prompt_tokens')" < truncated.json 2>/dev/null)
FLAG=$(jq_ "d.get('x_eugene_plexus',{}).get('prompt_truncated')" < truncated.json 2>/dev/null)
CL=$(jq_ "d.get('x_eugene_plexus',{}).get('context_length')" < truncated.json 2>/dev/null)
echo "  HTTP $TCODE -- sent $CHARS chars, backend reported prompt_tokens=$PT"
echo "  prompt_truncated=$FLAG  context_length=$CL"

# --- 8 -----------------------------------------------------------------------
# The whole reason this half exists: it is a 200. Nothing about the
# response says the input was thrown away, which is why a harness cannot
# tell this from the model simply being wrong.
[ "$TCODE" = "200" ] && [ -n "$PT" ] && [ "$PT" -lt 1000 ] \
  && ok "ollama answered 200 having consumed only $PT tokens of $CHARS characters" \
  || bad "expected a 200 with a tiny prompt_tokens; got HTTP $TCODE, prompt_tokens=$PT"

# --- 9 -----------------------------------------------------------------------
[ "$FLAG" = "True" ] && ok "the gateway flagged it as prompt_truncated" \
  || bad "prompt_truncated was '$FLAG'; the silent case stayed silent"

# --- 10 ----------------------------------------------------------------------
[ "$CL" = "$OLLAMA_CTX" ] && ok "the completion reports the window that applied ($CL)" \
  || bad "context_length was '$CL', expected $OLLAMA_CTX"

# --- 11 ----------------------------------------------------------------------
say "11. a prompt that arrived intact is NOT flagged"
# The half that makes check 9 worth anything. A detector that fires on
# everything proves nothing, and this is the same shape as step 6's
# fragmentation checks, which passed against a property of the backend
# rather than of our code.
INTACT=$(curl -s -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$OLLAMA_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"$(python -c "print('Summarise this sentence in one word. ' * 60)")\"}],\"max_tokens\":8}")
IFLAG=$(printf '%s' "$INTACT" | jq_ "d.get('x_eugene_plexus',{}).get('prompt_truncated')" 2>/dev/null)
IPT=$(printf '%s' "$INTACT" | jq_ "d.get('usage',{}).get('prompt_tokens')" 2>/dev/null)
echo "  prompt_tokens=$IPT prompt_truncated=$IFLAG"
[ "$IFLAG" = "False" ] && ok "an intact prompt reports prompt_truncated=false" \
  || bad "an intact prompt reported '$IFLAG' -- the detector does not discriminate"

# --- 12 ----------------------------------------------------------------------
say "12. a streamed request carries the flag on its final frame"
# M10's rule is that a stream cannot be unsent, which is exactly why this
# is a flag on both paths rather than an error on one of them.
printf '%s' "$TRUNC" | PYTHONUTF8=1 python -c "
import sys, json
d = json.load(sys.stdin); d['stream'] = True
open('trunc-stream.json', 'w').write(json.dumps(d))
"
curl -s -N -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' -d @trunc-stream.json > stream.sse
SFLAG=$(PYTHONUTF8=1 python -c "
import json
flag = None
for line in open('stream.sse', encoding='utf-8'):
    if not line.startswith('data: ') or line[6:].strip() == '[DONE]':
        continue
    try:
        chunk = json.loads(line[6:])
    except ValueError:
        continue
    if chunk.get('x_eugene_plexus'):
        flag = chunk['x_eugene_plexus'].get('prompt_truncated')
print(flag)
")
echo "  final frame prompt_truncated=$SFLAG"
[ "$SFLAG" = "True" ] && ok "the streamed path reports it too" \
  || bad "the streamed final frame said '$SFLAG' -- one condition, two answers"

# --- 13 ----------------------------------------------------------------------
say "13. the truncation is in the gateway log too"
# The flag rides a namespaced field most clients drop on the floor. An
# operator chasing "the model keeps ignoring my files" needs a line
# somewhere they will actually look.
GWLOG=$(find "$WORK" .. -name 'gateway*.log' 2>/dev/null | head -1)
[ -z "$GWLOG" ] && GWLOG=$(find "$HOME/.eugene-plexus" "$WORK" -name '*.log' 2>/dev/null | xargs grep -l 'discarded most of the prompt' 2>/dev/null | head -1)
if [ -n "$GWLOG" ] && grep -q 'discarded most of the prompt' "$GWLOG" 2>/dev/null; then
  ok "gateway log names it: $(grep -m1 -o 'reported consuming only [0-9]* prompt tokens for [0-9]* characters' "$GWLOG")"
elif grep -rq 'discarded most of the prompt' "$WORK" 2>/dev/null; then
  ok "gateway log names it: $(grep -rhm1 -o 'reported consuming only [0-9]* prompt tokens for [0-9]* characters' "$WORK")"
else
  bad "no warning in any log under $WORK"
fi

# --------------------------------------------------------------------- #

say "result"
if [ "$FAILURES" = "0" ]; then
  printf '\n  ALL CHECKS PASSED\n\n'
else
  printf '\n  %d CHECK(S) FAILED\n\n' "$FAILURES"
fi
exit "$FAILURES"
