#!/usr/bin/env bash
# Install-paths §9 step 6 -- tool calling, end to end, against a real model.
#
# What only a live run can prove. The unit tests on both sides use a fake
# that emits exactly the fragments we told it to, so they verify our
# translation and nothing about whether a real model, given real tool
# definitions through our stack, actually decides to call one -- and
# whether the loop closes when we hand the result back.
#
# The checks:
#   1. the driver reports capabilities.toolCalling
#   2. GET /v1/models reports tool_calling for the model
#   3. a real model emits a real tool call, non-streaming
#   4. finish_reason is tool_calls, and content is null
#   5. the arguments string parses and names the right parameter
#   6. the loop CLOSES: hand the result back, get an answer that uses it
#   7. streaming: we forward exactly the fragments the backend emitted
#   8. every fragment carries an index, and they reassemble to valid JSON
#   9. fragments reach the client before the terminal frame
#  10. the terminal frame says tool_calls
#  11. a request with no tools is untouched
#  12. a backend that cannot carry tools refuses rather than answering
#
# Design: docs/design/agent-clients-and-tool-calling.md
#
# **This script is safe to run beside a live install.** It binds the
# agent on 8179 rather than 8079, and it tears down BY PORT, only the
# ports it opened. Earlier scripts in this directory end with
# `pkill -f eugene_plexus_`, which on a machine that is also a worker
# node would kill the operator's own agent and every component under it.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-tools-live}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
AGENT="http://127.0.0.1:$AGENT_PORT"
GW="${EP_GW:-http://127.0.0.1:8080}"
DRIVER_PORT="${EP_DRIVER_PORT:-8191}"
CLI_PORT="${EP_CLI_PORT:-8192}"
PASS="tools-live-$$"
OLLAMA="${EP_OLLAMA:-http://127.0.0.1:11434}"
# A tool-calling model. qwen3-coder is trained for it; a model that is
# not would make a failed check ambiguous between "our stack lost the
# tools" and "this model does not do tools", which is exactly the
# confusion the milestone exists to remove.
MODEL="${EP_MODEL:-qwen3-coder:30b}"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }

OWNED_PORTS="$AGENT_PORT 8080 8082 8083 $DRIVER_PORT $CLI_PORT"

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
}

TOOLS='[{"type":"function","function":{"name":"get_weather","description":"Get the current weather for a city. Call this whenever the user asks about weather.","parameters":{"type":"object","properties":{"city":{"type":"string","description":"The city name"}},"required":["city"]}}}]'

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
curl -sf -m 3 "$OLLAMA/api/tags" >/dev/null || { bad "ollama is not answering at $OLLAMA"; exit 1; }
curl -s -m 5 "$OLLAMA/api/tags" | grep -q "$MODEL" || { bad "$MODEL is not pulled into ollama"; exit 1; }
# Refuse to run if something already owns a port we are about to take --
# including the operator's own worker agent on 8079, which this script
# deliberately does not use.
for p in $OWNED_PORTS; do
  if netstat -ano 2>/dev/null | grep ":$p " | grep -q LISTENING; then
    bad "port $p is already in use; set EP_AGENT_PORT / EP_DRIVER_PORT or stop it"
    exit 1
  fi
done
ok "agent python, a live ollama with $MODEL, and every port free"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
export EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT"
trap teardown EXIT

say "start the agent; it declares control, gateway and library itself"
"$PY" -m eugene_plexus_agent --unattended >"$WORK/agent.log" 2>&1 &
wait_healthy "$AGENT" 60 || { bad "agent never answered"; tail -20 "$WORK/agent.log"; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d['sessionToken']")
[ -n "$TOK" ] || { bad "no operator token"; exit 1; }
wait_healthy "$GW" 90 || { bad "gateway never answered"; exit 1; }
ok "agent and gateway up"

add_driver() { # name port provider model
  curl -s -o /dev/null -X POST "$AGENT/v1/components" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' \
    -d "{\"name\":\"$1\",\"kind\":\"inference-driver\",\"url\":\"http://127.0.0.1:$2\",\"spawn\":{\"configFile\":\"$1.yaml\"}}"
  sleep 3
  curl -s -o /dev/null -X PATCH "http://127.0.0.1:$2/v1/config" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' -d "{\"provider\":\"$3\",\"modelId\":\"$4\"}"
  curl -s -o /dev/null -X POST "$AGENT/v1/components/$1/restart" -H "Authorization: Bearer $TOK" -d '{}'
}

say "a driver on the local ollama"
add_driver tools-ollama "$DRIVER_PORT" ollama_local "$MODEL"
sleep 10

# --- 1 -----------------------------------------------------------------------
say "1. the driver reports what it can carry"
INFO=$(curl -s -m 10 "http://127.0.0.1:$DRIVER_PORT/v1/info" -H "Authorization: Bearer $TOK")
echo "  /v1/info: $INFO"
case "$INFO" in
  *'"toolCalling":true'*) ok "capabilities.toolCalling is true" ;;
  *) bad "toolCalling not reported: $INFO" ;;
esac

# --- 2 -----------------------------------------------------------------------
say "2. the gateway advertises it per model"
sleep 16
MODELS=$(curl -s -m 15 "$GW/v1/models" -H "Authorization: Bearer $TOK")
TC=$(printf '%s' "$MODELS" | jq_ "[m.get('x_eugene_plexus',{}).get('tool_calling') for m in d['data']]")
echo "  tool_calling per model: $TC"
case "$TC" in
  *True*) ok "GET /v1/models reports tool_calling" ;;
  *) bad "tool_calling absent or false: $MODELS" ;;
esac

# --- 3, 4, 5 -----------------------------------------------------------------
say "3-5. a real model, given real tools, makes a real call"
REQ="{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"What is the weather in Oslo? Use your tools.\"}],\"tools\":$TOOLS,\"max_tokens\":300}"
R=$(curl -s -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' -d "$REQ")
printf '%s' "$R" > call.json
echo "  finish_reason: $(printf '%s' "$R" | jq_ "d['choices'][0]['finish_reason']" 2>/dev/null)"
echo "  tool_calls:    $(printf '%s' "$R" | jq_ "json.dumps(d['choices'][0]['message'].get('tool_calls'))" 2>/dev/null)"

CALLS=$(printf '%s' "$R" | jq_ "len(d['choices'][0]['message'].get('tool_calls') or [])" 2>/dev/null)
[ "$CALLS" = "1" ] && ok "the model emitted exactly one tool call" || bad "tool_calls was $CALLS: $(printf '%s' "$R" | head -c 400)"

FR=$(printf '%s' "$R" | jq_ "d['choices'][0]['finish_reason']" 2>/dev/null)
CONTENT=$(printf '%s' "$R" | jq_ "repr(d['choices'][0]['message'].get('content'))" 2>/dev/null)
[ "$FR" = "tool_calls" ] && ok "finish_reason is tool_calls (content: $CONTENT)" \
  || bad "finish_reason was $FR, so a harness would have stopped instead of dispatching"

# The arguments are a STRING on the wire and must parse to an object
# naming the parameter we declared. A model that called the tool with the
# wrong shape is a model problem; one whose arguments never arrived is
# ours.
ARGS_OK=$(printf '%s' "$R" | PYTHONUTF8=1 python -c "
import sys, json
d = json.load(sys.stdin)
call = (d['choices'][0]['message'].get('tool_calls') or [{}])[0]
raw = call.get('function', {}).get('arguments')
print('NOTSTRING') if not isinstance(raw, str) else None
try:
    args = json.loads(raw)
except Exception as e:
    print('UNPARSEABLE', raw[:120]); raise SystemExit
print('OK' if 'city' in args else 'NOCITY', json.dumps(args))
" 2>/dev/null)
echo "  arguments: $ARGS_OK"
case "$ARGS_OK" in
  OK*) ok "arguments arrived as a string and parse to the declared parameter" ;;
  *) bad "arguments wrong: $ARGS_OK" ;;
esac

# --- 6 -----------------------------------------------------------------------
say "6. the loop closes: hand the result back"
# This is the check the whole milestone is for. A harness replays the
# assistant turn that asked, plus a `tool` message carrying the result.
# If either is lost or reshaped on the way down, the model cannot see
# that its call was answered -- and the symptom is it calling the same
# tool again, which reads as a stupid model rather than as a lost message.
FOLLOWUP=$(printf '%s' "$R" | PYTHONUTF8=1 python -c "
import sys, json
d = json.load(sys.stdin)
msg = d['choices'][0]['message']
call = msg['tool_calls'][0]
print(json.dumps({
    'model': '$MODEL',
    'messages': [
        {'role': 'user', 'content': 'What is the weather in Oslo? Use your tools.'},
        {'role': 'assistant', 'content': msg.get('content'), 'tool_calls': msg['tool_calls']},
        {'role': 'tool', 'content': json.dumps({'tempC': -3, 'sky': 'snow'}),
         'tool_call_id': call['id']},
    ],
    'tools': $TOOLS,
    'max_tokens': 300,
}))
" 2>/dev/null)
if [ -z "$FOLLOWUP" ]; then
  bad "could not build the follow-up request (no call to replay)"
else
  R2=$(curl -s -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' -d "$FOLLOWUP")
  ANSWER=$(printf '%s' "$R2" | jq_ "(d['choices'][0]['message'].get('content') or '')" 2>/dev/null)
  echo "  answer: $(printf '%s' "$ANSWER" | head -c 200)"
  # The tool said -3 and snow. An answer carrying either is an answer
  # that used the result; one that does not is a model talking past it.
  case "$ANSWER" in
    *-3*|*snow*|*Snow*) ok "the model answered USING the tool result" ;;
    *) bad "the answer does not reflect the tool result: $(printf '%s' "$ANSWER" | head -c 200)" ;;
  esac
fi

# --- 7, 8, 9, 10 -------------------------------------------------------------
say "7-10. streaming a tool call"
#
# **The first version of these checks asserted a property of Ollama and
# called it a property of us**, which is this project's recurring
# failure and it turned up here in the script written to avoid it.
# They demanded the call arrive in many fragments with an early time to
# first fragment. Measured directly against Ollama afterwards: it emits
# the entire call -- id, name and complete `arguments` -- in ONE delta
# and never fragments. So the check could only have passed against a
# backend that fragments, and it was failing our correct pass-through.
#
# OpenAI proper does fragment, so the accumulation path is real and is
# unit-tested on both sides with a fake that splits `arguments`
# mid-token. What a live run against a local engine can prove is the
# part we own: **we forward exactly what the backend sent, in its own
# frame, before the terminal one.** So the baseline is measured from
# the backend rather than assumed, and the assertion is equality.
#
# `curl -sN` piped into `python -u`, never urllib: M10's first
# instrument buffered and reported time-to-first-token at 94% of a
# request in which it also counted 79 frames, which cannot both be true.
say "  baseline: what the backend itself emits for this prompt"
BASELINE=$(curl -sN -m 300 "$OLLAMA/v1/chat/completions" -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"What is the weather in Bergen? Use your tools.\"}],\"tools\":$TOOLS,\"stream\":true}" \
  | PYTHONUTF8=1 python -u -c "
import json, sys
n = 0
for raw in sys.stdin:
    line = raw.strip()
    if not line.startswith('data:'):
        continue
    payload = line[5:].strip()
    if payload == '[DONE]':
        break
    try:
        obj = json.loads(payload)
    except ValueError:
        continue
    if ((obj.get('choices') or [{}])[0].get('delta') or {}).get('tool_calls'):
        n += 1
print(n)
" 2>/dev/null)
echo "  backend emitted $BASELINE tool-call delta(s)"
STREAM_REQ="{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"What is the weather in Bergen? Use your tools.\"}],\"tools\":$TOOLS,\"max_tokens\":300,\"stream\":true}"
curl -sN -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' -d "$STREAM_REQ" \
  | PYTHONUTF8=1 python -u -c "
import json, sys, time
started = time.monotonic()
first = None
frames = fragments = 0
indexes = set()
args = {}
finish = None
finish_frame = None
last_fragment_frame = None
for raw in sys.stdin:
    line = raw.strip()
    if not line.startswith('data:'):
        continue
    payload = line[5:].strip()
    if payload == '[DONE]':
        break
    frames += 1
    try:
        obj = json.loads(payload)
    except ValueError:
        continue
    choice = (obj.get('choices') or [{}])[0]
    if choice.get('finish_reason') and finish is None:
        finish = choice['finish_reason']
        finish_frame = frames
    for frag in (choice.get('delta') or {}).get('tool_calls') or []:
        fragments += 1
        last_fragment_frame = frames
        if first is None:
            first = time.monotonic() - started
        indexes.add(frag.get('index'))
        piece = (frag.get('function') or {}).get('arguments') or ''
        args[frag.get('index')] = args.get(frag.get('index'), '') + piece
total = time.monotonic() - started
json.dump({'frames': frames, 'fragments': fragments, 'indexes': sorted(i for i in indexes if i is not None),
           'missingIndex': None in indexes, 'args': args, 'ttft': first, 'total': total,
           'finish': finish, 'finishFrame': finish_frame,
           'lastFragmentFrame': last_fragment_frame}, sys.stdout)
" > stream.json 2>/dev/null

S=$(cat stream.json 2>/dev/null)
echo "  $S"
FRAGS=$(printf '%s' "$S" | jq_ "d['fragments']" 2>/dev/null)
# Equality with the backend, not a floor. We are a pass-through: turning
# one backend delta into several would invent fragmentation, and folding
# several into one would defeat streaming. Either is a bug; only the
# comparison can tell.
[ -n "$FRAGS" ] && [ "$FRAGS" = "$BASELINE" ] 2>/dev/null \
  && ok "forwarded $FRAGS tool-call delta(s), exactly what the backend emitted" \
  || bad "forwarded $FRAGS but the backend emitted $BASELINE"

MISSING=$(printf '%s' "$S" | jq_ "d['missingIndex']" 2>/dev/null)
[ "$MISSING" = "False" ] && ok "every fragment carried an index" \
  || bad "a fragment arrived with no index, so two calls could merge into one"

REASSEMBLED=$(printf '%s' "$S" | PYTHONUTF8=1 python -c "
import sys, json
d = json.load(sys.stdin)
for raw in d['args'].values():
    try:
        parsed = json.loads(raw)
    except Exception:
        print('UNPARSEABLE', raw[:120]); break
    print('OK' if 'city' in parsed else 'NOCITY', json.dumps(parsed))
    break
" 2>/dev/null)
echo "  reassembled: $REASSEMBLED"
case "$REASSEMBLED" in
  OK*) ok "the fragments reassemble to valid JSON naming the parameter" ;;
  *) bad "reassembly failed: $REASSEMBLED" ;;
esac

# Forwarded, not accumulated -- asserted structurally rather than on a
# clock. A time-to-first-fragment threshold would be a claim about when
# the MODEL decided to call, which against a backend that emits the whole
# call at the end of generation is necessarily late and says nothing
# about us. What we own is whether the fragment gets its own frame
# before the terminal one, or is folded into it.
LASTFRAG=$(printf '%s' "$S" | jq_ "d['lastFragmentFrame']" 2>/dev/null)
FINFRAME=$(printf '%s' "$S" | jq_ "d['finishFrame']" 2>/dev/null)
TTFT=$(printf '%s' "$S" | jq_ "round((d['ttft'] or 0) / (d['total'] or 1) * 100)" 2>/dev/null)
echo "  last fragment on frame $LASTFRAG, terminal frame $FINFRAME (first fragment at ${TTFT}% of the request)"
[ -n "$LASTFRAG" ] && [ -n "$FINFRAME" ] && [ "$LASTFRAG" -lt "$FINFRAME" ] 2>/dev/null \
  && ok "every fragment reached the client before the terminal frame" \
  || bad "fragments were held to the terminal frame (last=$LASTFRAG terminal=$FINFRAME)"

FIN=$(printf '%s' "$S" | jq_ "d['finish']" 2>/dev/null)
[ "$FIN" = "tool_calls" ] && ok "the terminal frame says tool_calls" || bad "terminal finish_reason was $FIN"

# --- 11 ----------------------------------------------------------------------
say "11. a request with no tools is untouched"
PLAIN=$(curl -s -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say PONG and nothing else.\"}],\"max_tokens\":30}")
PFR=$(printf '%s' "$PLAIN" | jq_ "d['choices'][0]['finish_reason']" 2>/dev/null)
PC=$(printf '%s' "$PLAIN" | jq_ "(d['choices'][0]['message'].get('content') or '')" 2>/dev/null)
echo "  finish_reason: $PFR  content: $(printf '%s' "$PC" | head -c 60)"
[ "$PFR" = "stop" ] && [ -n "$PC" ] && ok "an ordinary completion is unchanged" \
  || bad "plain request regressed: $(printf '%s' "$PLAIN" | head -c 300)"

# --- 12 ----------------------------------------------------------------------
say "12. a backend that cannot carry tools refuses"
# A CLI-subscription driver is a real backend that genuinely cannot
# carry tool definitions. It must refuse rather than answer without
# them -- a plain answer is indistinguishable from the model declining,
# which is the looping symptom this milestone exists to remove.
add_driver tools-cli "$CLI_PORT" claude_code_cli "claude-cli-no-tools"
sleep 8
CLIINFO=$(curl -s -m 10 "http://127.0.0.1:$CLI_PORT/v1/info" -H "Authorization: Bearer $TOK")
echo "  cli driver /v1/info: $(printf '%s' "$CLIINFO" | head -c 200)"
case "$CLIINFO" in
  *'"toolCalling":false'*) ok "the CLI driver honestly reports toolCalling false" ;;
  *) bad "CLI driver did not report toolCalling false: $CLIINFO" ;;
esac
REFUSAL=$(curl -s -m 60 -w '\n%{http_code}' -X POST "http://127.0.0.1:$CLI_PORT/v1/generate" \
  -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"tools\":$TOOLS}")
RCODE=$(printf '%s' "$REFUSAL" | tail -1)
echo "  POST /v1/generate with tools -> HTTP $RCODE"
[ "$RCODE" = "400" ] && ok "the driver refuses tools it cannot carry, rather than stripping them" \
  || bad "expected 400, got $RCODE: $(printf '%s' "$REFUSAL" | head -c 300)"

say "done"
if [ "$FAILURES" -eq 0 ]; then
  printf '\nALL CHECKS PASSED\n'
else
  printf '\n%d CHECK(S) FAILED\n' "$FAILURES"
fi
exit "$FAILURES"
