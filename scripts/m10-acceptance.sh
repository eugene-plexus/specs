#!/usr/bin/env bash
#
# M10 acceptance: does a token actually arrive early?
#
# **The check this script exists for is a frame COUNT and a clock.**
# From M0 to M9 `/v1/chat/completions` with `stream: true` returned
# perfectly well-formed SSE -- correct chunk objects, correct
# `data: [DONE]` sentinel -- and delivered the whole answer in a single
# content frame after the generation had finished. Every "is it
# streaming" assertion that checks framing passed the entire time. So
# nothing here is allowed to check framing alone: it counts frames, and
# it measures the gap between the first one and the last.
#
# Ollama is the backend for the same reason M8 used it: it is already
# running on this box, it speaks the OpenAI-compatible SSE the
# `openai_compat_http` engine consumes, and it makes these measurements
# rather than fixtures.
#
# Checks:
#   1. /v1/info reports capabilities.streaming, which nothing populated
#      before M10
#   2. a streamed completion arrives in MANY content frames
#   3. time to first token is a small fraction of the total
#   4. the final frame still carries usage and x_eugene_plexus
#   5. non-streaming is unchanged
#   6. a backend that dies BEFORE the first token still cascades
#   7. a backend that dies AFTER the first token truncates and does NOT
#      cascade -- the commit point, live
#
# Design: docs/design/m10-token-streaming.md
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-m10-live}"
AGENT=http://127.0.0.1:8079
GW=http://127.0.0.1:8080
PASS="m10-live-$$"
OLLAMA="${EP_OLLAMA:-http://127.0.0.1:11434}"
MODEL="${EP_MODEL:-huihui_ai/dolphin3-abliterated:8b-llama3.1-q4_K_M}"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }

free_port() { # port
  # Kill whatever is LISTENING on this port, by port rather than by a
  # pid or a command pattern. Windows will happily let a second process
  # bind an already-bound loopback port, and the OLDEST binder keeps
  # serving -- so a stub left over from a previous run silently answers
  # for the one this run just started, with the previous run's code.
  # That is what happened here: three stale stubs were stacked on 8196
  # and the check under test was reading a two-runs-old reply. Same
  # family as M9's teardown, which killed the pid it held rather than
  # whatever owned the port.
  for pid in $(netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u); do
    taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
  done
}

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
curl -sf -m 3 "$OLLAMA/api/tags" >/dev/null || { bad "ollama is not answering at $OLLAMA"; exit 1; }
ok "agent python and a live ollama"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
export EUGENE_PLEXUS_AGENT_BIND_PORT=8079

# --- a stub backend that dies mid-stream ------------------------------------
# Emits a few real SSE deltas and then drops the connection. This is how
# check 7 gets a genuine mid-answer failure over the wire without killing
# anything that belongs to the operator.
cat > flaky.py <<'PYEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODE = sys.argv[2] if len(sys.argv) > 2 else "midstream"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            body = json.dumps({"object": "list", "data": [{"id": "flaky", "object": "model"}]})
            self._send(200, body, "application/json")
        else:
            self._send(404, "{}", "application/json")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if MODE == "upfront":
            # Dies before producing anything: the cascade may still run.
            self._send(503, json.dumps({"error": "backend down"}), "application/json")
            return
        # Real deltas, then the connection simply goes away.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in ("ZEBRA ", "QUARTZ ", "VELLUM "):
            frame = {"model": "flaky", "choices": [{"delta": {"content": piece}}]}
            self.wfile.write(("data: " + json.dumps(frame) + chr(10) * 2).encode())
            self.wfile.flush()
        self.close_connection = True
        try:
            self.wfile.close()
        except OSError:
            pass

    def _send(self, code, body, ctype):
        raw = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PYEOF

say "start the agent; it declares control, gateway and library itself"
"$PY" -m eugene_plexus_agent >"$WORK/agent.log" 2>&1 &
AGENT_PID=$!
trap 'kill -9 $AGENT_PID 2>/dev/null; pkill -f eugene_plexus_ 2>/dev/null; pkill -f flaky.py 2>/dev/null' EXIT
wait_healthy "$AGENT" 60 || { bad "agent never answered"; tail -20 "$WORK/agent.log"; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d['sessionToken']")
[ -n "$TOK" ] || { bad "no operator token"; exit 1; }
wait_healthy "$GW" 90 || { bad "gateway never answered"; exit 1; }
ok "agent and gateway up"

add_driver() { # name port provider model baseUrl
  curl -s -o /dev/null -X POST "$AGENT/v1/components" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' \
    -d "{\"name\":\"$1\",\"kind\":\"inference-driver\",\"url\":\"http://127.0.0.1:$2\",\"spawn\":{\"configFile\":\"$1.yaml\"}}"
  sleep 3
  curl -s -o /dev/null -X PATCH "http://127.0.0.1:$2/v1/config" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' \
    -d "{\"provider\":\"$3\",\"modelId\":\"$4\",\"baseUrl\":\"$5\"}"
  curl -s -o /dev/null -X POST "$AGENT/v1/components/$1/restart" -H "Authorization: Bearer $TOK" -d '{}'
}

# Poll rather than sleep: the gateway's routing table refreshes on an
# interval, so any fixed wait is either too short (the first run of this
# script asked at 10s and got an empty list) or wastefully long.
wait_for_model() { # model, seconds
  # Matches a model ID exactly. An earlier version grepped the raw JSON,
  # so the name "flaky" matched a *driver* name elsewhere in the document
  # and the wait returned before anything was routable -- the request
  # then 404'd, and the checks downstream read the 404's own text as
  # evidence that the thing under test had happened. A wait that can be
  # satisfied by something other than its subject is worse than no wait.
  for _ in $(seq 1 "${2:-45}"); do
    if curl -s "$GW/v1/models" -H "Authorization: Bearer $TOK" | PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if sys.argv[1] in [m['id'] for m in d.get('data',[])] else 1)" "$1"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

say "one ollama driver"
add_driver ollama-stream 8091 ollama_local "$MODEL" "$OLLAMA"
wait_for_model "$MODEL" 60 || { bad "the model never became routable";   echo "  gateway lists: $(curl -s "$GW/v1/models" -H "Authorization: Bearer $TOK" | head -c 300)"; exit 1; }
ok "the model is routable"

# --- 1 ----------------------------------------------------------------------
say "1. capabilities.streaming on /v1/info - contracted at M0, populated at M10"
INFO=$(curl -s "http://127.0.0.1:8091/v1/info" -H "Authorization: Bearer $TOK")
echo "  info: $(printf '%s' "$INFO" | head -c 200)"
STREAMING=$(printf '%s' "$INFO" | jq_ "(d.get('capabilities') or {}).get('streaming')")
[ "$STREAMING" = "True" ] && ok "the driver reports capabilities.streaming=true" \
  || bad "capabilities.streaming was $STREAMING"

# --- 2, 3, 4 ----------------------------------------------------------------
say "2-4. a streamed completion: frame count, time to first token, final frame"
# **The instrument must not buffer.** The first run of this script used
# urllib and reported time-to-first-token at 94% of the request -- while
# also counting 79 content frames, which cannot both be true. urllib
# handed the frames over in a lump. `curl -N` disables its own buffering
# and the reader below takes lines off the pipe as they land, so what is
# timed is the gateway rather than the client. Same shape as M4, where
# the first socket instrument counted the 200 that means "ready" as a
# probe refuting the claim it was written to test.
curl -sN -m 300 -X POST "$GW/v1/chat/completions"   -H "Authorization: Bearer $TOK" -H 'content-type: application/json'   -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Count slowly from 1 to 40, one number per line.\"}],\"max_tokens\":200,\"stream\":true}"   | PYTHONUTF8=1 python -u -c "
import json, sys, time
started = time.monotonic()
first = None
frames = content_frames = 0
text = []
final = {}
while True:
    raw = sys.stdin.buffer.readline()
    if not raw:
        break
    line = raw.decode('utf-8', 'replace').strip()
    if not line.startswith('data:'):
        continue
    payload = line[5:].strip()
    if payload == '[DONE]':
        continue
    frames += 1
    try:
        chunk = json.loads(payload)
    except ValueError:
        continue
    if chunk.get('usage') or chunk.get('x_eugene_plexus'):
        final = chunk
    delta = ((chunk.get('choices') or [{}])[0].get('delta') or {}).get('content')
    if delta:
        content_frames += 1
        text.append(delta)
        if first is None:
            first = time.monotonic() - started
total = time.monotonic() - started
json.dump({'frames': frames, 'contentFrames': content_frames, 'ttft': first,
           'total': total, 'chars': len(''.join(text)),
           'usage': final.get('usage'), 'routing': final.get('x_eugene_plexus')}, sys.stdout)
" > stream.json
cat stream.json | PYTHONUTF8=1 python -c "
import sys,json; d=json.load(sys.stdin)
print('  frames=%d contentFrames=%d chars=%d' % (d['frames'], d['contentFrames'], d['chars']))
print('  ttft=%.2fs total=%.2fs (%.1f%% of the request)' % (d['ttft'] or -1, d['total'], 100*(d['ttft'] or 0)/d['total']))
print('  usage=%s routing.driver=%s' % (d['usage'], (d['routing'] or {}).get('driver')))
"
CF=$(cat stream.json | jq_ "d['contentFrames']")
[ "${CF:-0}" -gt 1 ] && ok "*** $CF CONTENT FRAMES - it is genuinely streaming (M0-M9 produced exactly 1) ***" \
  || bad "only $CF content frame(s): this is the pre-M10 behaviour"

RATIO=$(cat stream.json | PYTHONUTF8=1 python -c "
import sys,json; d=json.load(sys.stdin)
t=d['ttft']; print(0 if t is None else int(100*t/d['total']))
")
[ "${RATIO:-100}" -lt 50 ] && ok "*** first token at ${RATIO}% of the request - early delivery is real ***" \
  || bad "first token arrived at ${RATIO}% of the request"

HAS_ROUTING=$(cat stream.json | jq_ "bool(d.get('routing'))")
[ "$HAS_ROUTING" = "True" ] && ok "the final frame still carries x_eugene_plexus" || bad "no routing extension"
HAS_USAGE=$(cat stream.json | jq_ "bool(d.get('usage'))")
[ "$HAS_USAGE" = "True" ] && ok "the final frame still carries usage" || bad "no usage on the final frame"

# --- 5 ----------------------------------------------------------------------
say "5. non-streaming is unchanged"
R=$(curl -s -m 180 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word OK.\"}],\"max_tokens\":16}")
[ -n "$(printf '%s' "$R" | jq_ "d.get('choices',[{}])[0].get('message',{}).get('content','')" 2>/dev/null)" ] \
  && ok "a non-streamed completion still works" || bad "non-streaming broke: $(printf '%s' "$R" | head -c 200)"

# --- 6 ----------------------------------------------------------------------
say "6. a backend that dies BEFORE the first token still cascades"
free_port 8195
"$PY" flaky.py 8195 upfront >/dev/null 2>&1 &
sleep 2
add_driver flaky-upfront 8092 openai_compat_custom "$MODEL" "http://127.0.0.1:8195"
sleep 20  # one refresh interval, so the dead backend is in the table
# One slot, two tiers: the dead stub first, ollama behind it.
curl -s -o /dev/null -X PATCH "$GW/v1/config" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"modelSlots\":{\"cascade-test\":[\"$MODEL\"]}}"
sleep 3
CASCADE=$(curl -s -N -m 180 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK.\"}],\"max_tokens\":24,\"stream\":true}")
GOT=$(printf '%s\n' "$CASCADE" | grep -c '^data: ')
[ "${GOT:-0}" -gt 1 ] && ok "the stream still served ($GOT frames) with a dead backend in the install" \
  || bad "no stream came back: $(printf '%s' "$CASCADE" | head -c 200)"
pkill -f "flaky.py 8195" 2>/dev/null

# --- 7 ----------------------------------------------------------------------
say "7. THE COMMIT POINT: a backend that dies AFTER the first token truncates"
free_port 8196
"$PY" flaky.py 8196 midstream >/dev/null 2>&1 &
sleep 2
add_driver flaky-mid 8093 openai_compat_custom flaky "http://127.0.0.1:8196"
wait_for_model flaky 60 || bad "the flaky stub never became routable"
echo "  gateway models: $(curl -s "$GW/v1/models" -H "Authorization: Bearer $TOK" | jq_ "[m['id'] for m in d['data']]")"
echo "  flaky driver info: $(curl -s -m 5 http://127.0.0.1:8093/v1/info -H "Authorization: Bearer $TOK" | head -c 200)"
MID=$(curl -s -N -m 120 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"model\":\"flaky\",\"messages\":[{\"role\":\"user\",\"content\":\"anything\"}],\"max_tokens\":64,\"stream\":true}")
echo "  what came back (first 400 chars, newlines shown as |):"
printf '    %s
' "$(printf '%s' "$MID" | tr '
' '|' | head -c 400)"
# The stub's tokens are nonsense words on purpose. The first version of
# this check asserted on "The ", which also appears in the gateway's own
# 404 text -- so it passed against an error instead of against a truncated
# stream, and only a fixed diagnostic line caught it. An assertion whose
# subject also appears in the failure it is meant to catch is not an
# assertion.
DELIVERED=$(printf '%s' "$MID" | grep -c 'ZEBRA')
HAS_ERROR=$(printf '%s' "$MID" | grep -c 'upstream_error')
if [ "${DELIVERED:-0}" -ge 1 ]; then ok "the tokens delivered before the failure survived"; else bad "no streamed token reached the client; this is not the case under test"; fi
if [ "${HAS_ERROR:-0}" -ge 1 ]; then ok "*** the truncation is reported as an error frame, not a silent stop ***"; else bad "a mid-stream death produced no upstream_error frame"; fi
# And the whole point of a commit point: the answer must NOT have been
# finished off by the other backend sitting right there in the install.
if [ "${DELIVERED:-0}" -ge 1 ] && printf '%s' "$MID" | grep -q 'dolphin3'; then bad "the slot failed over mid-answer: another backend output is in this stream"; elif [ "${DELIVERED:-0}" -ge 1 ]; then ok "*** no second backend was spliced onto the half-sent answer ***"; else bad "no stream to check for splicing"; fi
pkill -f "flaky.py 8196" 2>/dev/null

say "done"
if [ "$FAILURES" -eq 0 ]; then
  echo; echo "ALL CHECKS PASSED"
else
  echo; echo "$FAILURES CHECK(S) FAILED"
fi
echo
echo "logs in $WORK"
echo "WHAT THIS PROVES AND DOES NOT"
echo "  proves: tokens reach the client as they are generated, measured by frame"
echo "          count and by a clock rather than by framing; the final frame still"
echo "          carries usage and routing; non-streaming is unchanged; and a"
echo "          backend that dies mid-answer truncates with an error frame instead"
echo "          of silently splicing another model's output onto a half-sent reply."
echo "  cannot: the CLI subscription backends (claude_code_cli streams for real,"
echo "          codex does not and says so) -- both need live subscriptions, and"
echo "          claude costs ~31k prompt tokens a request. The browser half is"
echo "          ui's own vitest suite plus the playground by hand."
exit $([ "$FAILURES" -eq 0 ] && echo 0 || echo 1)
