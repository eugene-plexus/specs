#!/usr/bin/env bash
# R1.4 -- a stream that ends leaves nothing behind. Live.
#
# Roadmap: docs/design/release-roadmap.md §2.4. Findings: review §6.1 #3,
# §6.3 #38.
#
# What only a live run can prove.
#
# The unit checks (`gateway/tests/test_stream_bookkeeping.py`) drive
# `TieredClient.stream` in-process and close the generator by hand. That
# is the right shape for the mechanism, and it cannot prove the thing
# the finding is actually about: a REAL client on a REAL socket going
# away mid-answer, the cancellation arriving through starlette and
# uvicorn as they are installed here, and the counter the lifecycle
# manager reads coming back to zero afterwards. The whole premise of
# §6.1 #3 is a claim about two libraries' behaviour -- starlette takes
# its disconnect-listening task group for any ASGI spec below (2, 4) and
# uvicorn advertises 2.3 -- so an in-process test of our own code cannot
# be the last word on it.
#
# The checks:
#   0. isolated from any install on this machine, and from its ports
#   1. a real gateway over a stub agent and a stub driver, routing
#   2. a streamed completion arrives in frames (the baseline: if nothing
#      streams, every check below passes for the wrong reason)
#   3. **the finding**: curl is KILLED mid-stream. `GET /v1/admin/routing`
#      reports `in_flight: 0` afterwards. Before this slice it stayed 1
#      for the life of the process
#   4. the counter is per attempt, not a latch: three killed streams in a
#      row still leave zero
#   5. **the consequence**: after a killed stream, the agent is really
#      asked to unload the idle runtime. A leaked counter skips it every
#      sweep and the memory is never given back
#   6. **§6.3 #38**: a driver that stops without a `done` event. The
#      client still gets a terminal frame carrying a `finish_reason`
#      before `[DONE]`, and the answer is not recorded served
#   7. a complete stream is still recorded served -- the guard on 6
#   8. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped, ports are +100, teardown is by pid. Never
# `pkill -f eugene_plexus_`: this box is a worker node.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
GW_PY="${EP_GW_PY:-$EP_ROOT/gateway/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-r14}"
GW_PORT="${EP_GW_PORT:-8180}"
AGENT_PORT="${EP_STUB_AGENT_PORT:-8179}"
DRIVER_PORT="${EP_STUB_DRIVER_PORT:-8181}"
GW="http://127.0.0.1:$GW_PORT"
OWNED_PORTS="$GW_PORT $AGENT_PORT $DRIVER_PORT"
MODEL="r14-model"
DRIVER_NAME="r14-driver"
RUNTIME_NAME="r14-runtime"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
# The LAST NON-EMPTY line. An SSE frame ends with a blank line, so
# `tail -1` is that blank line and a `[DONE]` assertion written against
# it fails on a perfectly well-formed stream -- which is what the first
# execution of this script did, on two checks, while the product was
# right.
last_frame() { grep -v '^[[:space:]]*$' "$1" | tail -1; }
# The last recorded request, as the row the metrics store actually
# keeps. `attempts` on that row is a COUNT; the per-attempt facts are
# under `tries[]`, and `outcome` is derived from whether any of them
# served -- which is the whole subject of §6.3 #38.
last_request() { curl -s -m 5 "$GW/v1/metrics/requests?limit=1" | jq_ "json.dumps((d.get('requests') or [{}])[0])"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }
kill_port() { for pid in $(listening_pids "$1"); do taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null; done; }

G_PID=""
S_PID=""
teardown() {
  [ -n "$G_PID" ] && { kill "$G_PID" 2>/dev/null; sleep 2; }
  [ -n "$S_PID" ] && kill "$S_PID" 2>/dev/null
  for p in $OWNED_PORTS; do kill_port "$p"; done
}

say "preflight"
[ -f "$GW_PY" ] || { bad "no gateway python at $GW_PY"; exit 1; }
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
ok "interpreter present; ports $OWNED_PORTS free"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

# --- 0 -----------------------------------------------------------------------
say "0. isolate this run"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy NO_PROXY no_proxy
WORK_NATIVE=$(win_path "$WORK")
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }

# --- the stubs ---------------------------------------------------------------
# One process serving both the agent's topology surface and the driver's
# generate/stream, on two ports. Deliberately NOT our own components: the
# subject is what the GATEWAY does when a client goes away, and a real
# driver would put an engine's own behaviour between the two.
#
# `/v1/generate/stream` emits a token, then SLEEPS -- so a client can be
# killed while the gateway is genuinely mid-answer rather than racing the
# end of a fast response. `?truncate=1` ends the SSE body with no `done`
# event at all, which is §6.3 #38's case.
cat > stubs.py <<'PY'
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DRIVER_PORT = int(sys.argv[1])
AGENT_PORT = int(sys.argv[2])
MODEL = sys.argv[3]
DRIVER_NAME = sys.argv[4]
RUNTIME_NAME = sys.argv[5]

TRUNCATE = threading.Event()
# Declared to the gateway as the runtime's `idleUnloadSeconds`. Off for
# most of the run: the idle pass would otherwise fire after any check's
# completed stream and check 5 would read someone else's unload.
IDLE_SECONDS = [None]
STOPPED: list[str] = []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # noqa: A002 - quiet
        pass

    def _json(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/v1/components":
            self._json(
                {
                    "components": [
                        {
                            "name": DRIVER_NAME,
                            "kind": "inference-driver",
                            "url": f"http://127.0.0.1:{DRIVER_PORT}/",
                            "status": "running",
                        }
                    ]
                }
            )
        elif path == "/v1/runtimes":
            self._json(
                {
                    "runtimes": [
                        {
                            "name": RUNTIME_NAME,
                            "status": "ready",
                            "engine": "llama_cpp",
                            "modelPath": "/models/r14.gguf",
                            "url": f"http://127.0.0.1:{DRIVER_PORT}/",
                            "idleUnloadSeconds": IDLE_SECONDS[0],
                            "capabilities": {"contextLength": 4096, "parallelSlots": 1},
                        }
                    ]
                }
            )
        elif path == "/v1/node":
            self._json({"name": "r14-node", "enrolled": False})
        elif path == "/v1/info":
            self._json(
                {
                    "backend": "openai_compat_http",
                    "modelId": MODEL,
                    "runtime": RUNTIME_NAME,
                    "version": "0.0.0-stub",
                    "capabilities": {"streaming": True, "maxContextTokens": 4096},
                }
            )
        elif path == "/control/truncate":
            TRUNCATE.set()
            self._json({"truncate": True})
        elif path == "/control/complete":
            TRUNCATE.clear()
            self._json({"truncate": False})
        elif path == "/control/idle-on":
            # Start declaring an idle timeout, and forget any stop the
            # earlier checks provoked, so what check 5 reads is its own.
            IDLE_SECONDS[0] = 5
            STOPPED.clear()
            self._json({"idleUnloadSeconds": IDLE_SECONDS[0]})
        elif path == "/control/stops":
            self._json({"stopped": list(STOPPED)})
        elif path == "/healthz":
            self._json({"status": "ok"})
        else:
            self._json({"title": "not found"}, status=404)

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        if path == "/v1/generate/stream":
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.end_headers()
            try:
                for index in range(20):
                    frame = json.dumps({"text": f"token{index} "})
                    self.wfile.write(f"event: token\ndata: {frame}\n\n".encode())
                    self.wfile.flush()
                    if TRUNCATE.is_set() and index == 2:
                        # The connection simply ends. No `done`, no
                        # error -- what a backend killed mid-answer
                        # looks like on the wire.
                        return
                    # Slow enough that a client can be killed while the
                    # gateway is genuinely mid-answer.
                    time.sleep(0.4)
                done = json.dumps(
                    {
                        "content": "".join(f"token{i} " for i in range(20)),
                        "finishReason": "stop",
                        "backend": "openai_compat_http",
                        "modelId": MODEL,
                        "latencyMs": 1,
                    }
                )
                self.wfile.write(f"event: done\ndata: {done}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
        elif path.startswith("/v1/runtimes/") and path.endswith("/stop"):
            STOPPED.append(path.split("/")[3])
            self._json({"status": "stopped"}, status=202)
        elif path == "/v1/generate":
            self._json(
                {
                    "content": "not streamed",
                    "finishReason": "stop",
                    "backend": "openai_compat_http",
                    "modelId": MODEL,
                    "latencyMs": 1,
                }
            )
        else:
            self._json({"title": "not found"}, status=404)


def serve(port):
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


threading.Thread(target=serve, args=(AGENT_PORT,), daemon=True).start()
serve(DRIVER_PORT)
PY

python stubs.py "$DRIVER_PORT" "$AGENT_PORT" "$MODEL" "$DRIVER_NAME" "$RUNTIME_NAME" > stubs.log 2>&1 &
S_PID=$!
for _ in $(seq 1 30); do curl -sf -m 2 "http://127.0.0.1:$AGENT_PORT/v1/components" >/dev/null 2>&1 && break; sleep 1; done

cat > gateway.yaml <<YAML
routingRefreshSeconds: 3
idleCheckSeconds: 2
metricsEnabled: true
metricsRetentionDays: 1
YAML

(exec env EUGENE_PLEXUS_GATEWAY_CONFIG_FILE="$WORK_NATIVE/gateway.yaml" \
  EUGENE_PLEXUS_GATEWAY_METRICS_FILE="$WORK_NATIVE/metrics.sqlite3" \
  EUGENE_PLEXUS_GATEWAY_BIND_HOST=127.0.0.1 \
  EUGENE_PLEXUS_GATEWAY_BIND_PORT="$GW_PORT" \
  EUGENE_PLEXUS_GATEWAY_AGENT_URL="http://127.0.0.1:$AGENT_PORT" \
  "$GW_PY" -m eugene_plexus_gateway > gateway.log 2>&1) &
G_PID=$!
for _ in $(seq 1 60); do curl -sf -m 2 "$GW/healthz" >/dev/null 2>&1 && break; sleep 1; done

# --- 1 -----------------------------------------------------------------------
say "1. a real gateway routes to the stub driver"
for _ in $(seq 1 30); do
  [ "$(curl -s -m 5 "$GW/v1/models" | jq_ "len(d.get('data') or [])" 2>/dev/null)" = "1" ] && break
  sleep 1
done
MODELS=$(curl -s -m 5 "$GW/v1/models")
[ "$(printf '%s' "$MODELS" | jq_ "d['data'][0]['id']" 2>/dev/null)" = "$MODEL" ] \
  && ok "the gateway serves $MODEL" || bad "no model routable: $(printf '%s' "$MODELS" | head -c 200)"

inflight() {
  curl -s -m 5 "$GW/v1/admin/routing" \
    | jq_ "next((b['in_flight'] for s in d['slots'] for t in s['tiers'] for b in t['backends'] if b['driver']=='$DRIVER_NAME'), None)" 2>/dev/null
}
note "in_flight before anything: $(inflight)"

# --- 2 -----------------------------------------------------------------------
say "2. the baseline: a streamed completion really streams"
curl -s -N -m 30 -X POST "$GW/v1/chat/completions" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":true,\"max_tokens\":64}" \
  > full.sse 2>/dev/null
FRAMES=$(grep -c '^data: ' full.sse)
CONTENT_FRAMES=$(grep '^data: ' full.sse | grep -c '"content"')
note "$FRAMES SSE frames, $CONTENT_FRAMES carrying content"
[ "${CONTENT_FRAMES:-0}" -ge 5 ] && ok "$CONTENT_FRAMES content frames -- this is a stream, not one chunk" \
  || bad "only $CONTENT_FRAMES content frames; every check below would pass for the wrong reason"
last_frame full.sse | grep -q '\[DONE\]' && ok "terminated with [DONE]" || bad "no [DONE]"
AFTER_FULL=$(inflight)
[ "${AFTER_FULL:-x}" = "0" ] && ok "a completed stream leaves in_flight 0" || bad "in_flight is $AFTER_FULL after a clean stream"

# --- 3 -----------------------------------------------------------------------
say "3. THE FINDING: a client killed mid-stream"
# curl is started in the background and killed while the gateway is
# still forwarding tokens -- the closed tab, on a real socket. Before
# this slice the cancellation arrived as a BaseException, neither the
# `except Exception` nor the `else` arm ran, and the counter stayed up
# for the life of the process.
curl -s -N -m 30 -X POST "$GW/v1/chat/completions" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":true,\"max_tokens\":64}" \
  > killed.sse 2>/dev/null &
C_PID=$!
sleep 2
DURING=$(inflight)
note "in_flight while streaming: $DURING"
[ "${DURING:-0}" -ge 1 ] && ok "the request is counted while it runs" \
  || bad "in_flight is $DURING mid-stream -- nothing is being counted, so check 3 proves nothing"
kill -9 "$C_PID" 2>/dev/null
wait "$C_PID" 2>/dev/null
sleep 4
AFTER=$(inflight)
note "in_flight after the client was killed: $AFTER"
[ "${AFTER:-x}" = "0" ] && ok "the abandoned attempt was closed (review §6.1 #3)" \
  || bad "in_flight is $AFTER -- the counter leaked; this runtime can never idle-unload again"

# --- 4 -----------------------------------------------------------------------
say "4. three killed streams in a row, and it is still zero"
for _ in 1 2 3; do
  curl -s -N -m 20 -X POST "$GW/v1/chat/completions" \
    -H 'content-type: application/json' \
    -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":true,\"max_tokens\":64}" \
    > /dev/null 2>&1 &
  P=$!
  sleep 1.5
  kill -9 "$P" 2>/dev/null
  wait "$P" 2>/dev/null
done
sleep 4
REPEAT=$(inflight)
[ "${REPEAT:-x}" = "0" ] && ok "in_flight is 0 after three abandonments" \
  || bad "in_flight is $REPEAT -- it accumulates, one per closed tab"

# --- 5 -----------------------------------------------------------------------
say "5. THE CONSEQUENCE: the engine is actually unloaded afterwards"
# `idle_pass` gates on `runtime_inflight(name) > 0`, so a leaked counter
# does not merely look wrong on a page -- the runtime is skipped every
# sweep, for the life of the process, and the memory is never given back.
#
# This is the check that had to be rewritten. The first version read
# `idle_seconds` off the admin view, which is computed from the
# last-served mark and has nothing to do with the in-flight counter: it
# PASSED against a deliberately sabotaged gateway, which is this
# project's recurring "the assertion matched the failure it was meant to
# catch". What cannot be faked is the agent being asked to stop.
curl -sf -m 5 "http://127.0.0.1:$DRIVER_PORT/control/idle-on" >/dev/null
sleep 4  # the routing refresh has to pick the new idleUnloadSeconds up
curl -s -N -m 30 -X POST "$GW/v1/chat/completions" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":true,\"max_tokens\":64}" \
  > /dev/null 2>&1 &
K_PID=$!
sleep 2
kill -9 "$K_PID" 2>/dev/null
wait "$K_PID" 2>/dev/null
STOPS=""
for _ in $(seq 1 20); do
  STOPS=$(curl -s -m 5 "http://127.0.0.1:$DRIVER_PORT/control/stops" | jq_ "d['stopped']" 2>/dev/null)
  printf '%s' "$STOPS" | grep -q "$RUNTIME_NAME" && break
  sleep 1
done
note "stops the agent was asked for: $STOPS"
printf '%s' "$STOPS" | grep -q "$RUNTIME_NAME" \
  && ok "the runtime whose client went away was unloaded -- the memory came back" \
  || bad "the agent was never asked to unload it: a leaked counter keeps it resident forever"

# --- 6 -----------------------------------------------------------------------
say "6. §6.3 #38: a driver that stops without a done event"
curl -sf -m 5 "http://127.0.0.1:$DRIVER_PORT/control/truncate" >/dev/null
curl -s -N -m 30 -X POST "$GW/v1/chat/completions" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":true,\"max_tokens\":64}" \
  > truncated.sse 2>/dev/null
last_frame truncated.sse | grep -q '\[DONE\]' && ok "the stream still terminates with [DONE]" || bad "no [DONE]"
LAST_CHUNK=$(grep '^data: ' truncated.sse | grep -v '\[DONE\]' | tail -1 | sed 's/^data: //')
FINISH=$(printf '%s' "$LAST_CHUNK" | jq_ "d['choices'][0]['finish_reason']" 2>/dev/null)
note "terminal frame finish_reason: $FINISH"
if [ -n "$FINISH" ] && [ "$FINISH" != "None" ]; then
  ok "the client is told the answer ended -- a terminal frame carries $FINISH"
else
  bad "no finish_reason anywhere: an OpenAI client cannot tell this from a complete answer"
fi
sleep 2
ROW=$(last_request)
TRY_SERVED=$(printf '%s' "$ROW" | jq_ "d['tries'][0]['served']" 2>/dev/null)
TRY_ERROR=$(printf '%s' "$ROW" | jq_ "d['tries'][0].get('error')" 2>/dev/null)
OUTCOME=$(printf '%s' "$ROW" | jq_ "d['outcome']" 2>/dev/null)
note "tries[0].served=$TRY_SERVED error=$TRY_ERROR outcome=$OUTCOME"
[ "$TRY_SERVED" = "False" ] \
  && ok "the truncated attempt is recorded served=False (review §6.3 #38)" \
  || bad "the truncation is recorded as a completion"
# `outcome` is what a person reading the metrics page sees, and it is
# derived from the attempt rows -- so this is the same fact one layer
# up, and the layer that would have hidden it.
[ "$OUTCOME" = "error" ] && ok "and the request reads 'error', not 'served'" \
  || bad "the request's outcome is '$OUTCOME'"

# --- 7 -----------------------------------------------------------------------
say "7. the guard: a complete stream is still recorded served"
curl -sf -m 5 "http://127.0.0.1:$DRIVER_PORT/control/complete" >/dev/null
curl -s -N -m 30 -X POST "$GW/v1/chat/completions" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":true,\"max_tokens\":64}" \
  > full2.sse 2>/dev/null
sleep 2
ROW2=$(last_request)
SERVED2=$(printf '%s' "$ROW2" | jq_ "d['tries'][0]['served']" 2>/dev/null)
OUTCOME2=$(printf '%s' "$ROW2" | jq_ "d['outcome']" 2>/dev/null)
note "tries[0].served=$SERVED2 outcome=$OUTCOME2"
[ "$SERVED2" = "True" ] \
  && ok "a complete stream is served -- saw_done did not turn every stream into a failure" \
  || bad "a complete stream is not recorded served"
[ "$OUTCOME2" = "served" ] && ok "and the request reads 'served'" \
  || bad "the request's outcome is '$OUTCOME2'"
LAST2=$(grep '^data: ' full2.sse | grep -v '\[DONE\]' | tail -1 | sed 's/^data: //')
[ "$(printf '%s' "$LAST2" | jq_ "d['choices'][0]['finish_reason']" 2>/dev/null)" = "stop" ] \
  && ok "and its terminal frame still says stop" || bad "the normal terminal frame changed"

# --- 8 -----------------------------------------------------------------------
say "8. teardown"
teardown
G_PID=""; S_PID=""
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ] && ok "every owned port released" || bad "still listening:$STILL"

printf '\n== %s\n' "$([ "$FAILURES" -eq 0 ] && echo 'ALL CHECKS PASSED' || echo "$FAILURES CHECK(S) FAILED")"
exit "$FAILURES"
