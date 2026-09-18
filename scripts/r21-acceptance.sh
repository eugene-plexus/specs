#!/usr/bin/env bash
# R2.1 -- a node that did not answer is not a node with nothing on it. Live.
#
# Roadmap: docs/design/release-roadmap.md §3.1. Findings: review §6.1 #9,
# §6.2 #18, §6.2 #17.
#
# What only a live run can prove.
#
# The unit checks drive `RoutingTable.refresh()` against a MockTransport
# and see the failure exactly where they put it. What they cannot show
# is the consequence a user meets: a real gateway process, a real agent
# read that fails the way a real one fails, and a completion crossing
# the wire **during** the failure. #6.1 #9's sharp end in particular is
# a resource-lifetime bug -- the refresh closing an HTTP client under a
# request that is using it -- and a request that is genuinely in flight
# across a refresh is the only honest way to see it.
#
# The checks:
#   0. isolated from any install on this machine, and from its ports
#   1. a real gateway over a stub agent and a stub driver, routing
#   2. the baseline: a completion is served, and the engine is `ready`
#   3. **§6.2 #18**: the engine is STOPPED and the agent stops answering
#      `/v1/runtimes`. The model must not become routable. Before this
#      slice one missed read meant `runtime is None`, which the
#      eligibility rule reads as "route to it whenever it is reachable"
#   4. **§6.1 #9**: the agent stops answering `/v1/components`. The
#      node's models stay routable and a completion still succeeds --
#      before, the refresh concluded every driver had left
#   5. **the sharp end of #9**: a completion is in flight ACROSS a
#      refresh that fails that read. Its driver client must not be
#      closed underneath it
#   6. both reads recover: the agent answers again and the fresh facts
#      replace the kept ones
#   7. **§6.2 #17**: a request arriving while an idle unload is in
#      flight is not routed to the engine being stopped
#   8. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped, ports are +100, teardown is by pid. Never
# `pkill -f eugene_plexus_`: this box is a worker node.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
GW_PY="${EP_GW_PY:-$EP_ROOT/gateway/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-r21}"
GW_PORT="${EP_GW_PORT:-8180}"
AGENT_PORT="${EP_STUB_AGENT_PORT:-8179}"
DRIVER_PORT="${EP_STUB_DRIVER_PORT:-8181}"
GW="http://127.0.0.1:$GW_PORT"
STUB="http://127.0.0.1:$AGENT_PORT"
OWNED_PORTS="$GW_PORT $AGENT_PORT $DRIVER_PORT"
MODEL="r21-model"
DRIVER_NAME="r21-driver"
RUNTIME_NAME="r21-runtime"
REFRESH=3

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }
kill_port() { for pid in $(listening_pids "$1"); do taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null; done; }

# One backend view out of the admin routing table.
backend_field() {
  curl -s -m 5 "$GW/v1/admin/routing" \
    | jq_ "next((b.get('$1') for s in d['slots'] for t in s['tiers'] for b in t['backends'] if b['driver']=='$DRIVER_NAME'), 'ABSENT')" 2>/dev/null
}
models_listed() { curl -s -m 5 "$GW/v1/models" | jq_ "len(d.get('data') or [])" 2>/dev/null; }
complete() {
  curl -s -m 30 -o /dev/null -w '%{http_code}' -X POST "$GW/v1/chat/completions" \
    -H 'content-type: application/json' \
    -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":8}"
}
# Two refreshes, so a change made now is certainly in the table.
settle() { sleep $((REFRESH * 2 + 1)); }

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
# An agent whose two topology reads can be switched off independently,
# and the driver it declares. Switching a read OFF is the whole subject:
# `/control/components/off` makes `/v1/components` refuse the connection
# the way an agent mid-restart does, and `/control/runtimes/401` answers
# the way one does when the clocks have drifted half a second apart.
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

STATE = {
    "components": "ok",   # ok | refuse
    "runtimes": "ok",     # ok | refuse | 401
    "status": "ready",    # what /v1/runtimes reports for the runtime
    "idle": None,         # idleUnloadSeconds, when check 7 turns it on
    "slow_stop": 0.0,     # seconds the stop call takes to answer
}
STOPPED: list[str] = []
DURING_STOP: list[int] = []
"""How many backends the gateway called eligible, sampled from inside
the stop call -- the only place the race is visible."""
GATEWAY = f"http://127.0.0.1:{int(sys.argv[6])}"


def eligible_now() -> int:
    import urllib.request

    try:
        with urllib.request.urlopen(f"{GATEWAY}/v1/admin/routing", timeout=5) as r:
            body = json.load(r)
    except Exception:
        return -1
    return sum(
        1
        for s in body.get("slots", [])
        for t in s.get("tiers", [])
        for b in t.get("backends", [])
        if b.get("eligible")
    )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _json(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/control/"):
            _, _, rest = path.partition("/control/")
            key, _, value = rest.partition("/")
            if key in ("components", "runtimes", "status", "slow_stop", "idle"):
                if key == "slow_stop":
                    STATE[key] = float(value)
                elif key == "idle":
                    STATE[key] = None if value == "off" else int(value)
                else:
                    STATE[key] = value
                return self._json({key: STATE[key]})
            if key == "stops":
                return self._json({"stopped": list(STOPPED), "duringStop": list(DURING_STOP)})
            return self._json({"title": "no such control"}, status=404)

        if path == "/v1/components":
            if STATE["components"] == "refuse":
                # The connection dies, which is what an agent being
                # restarted looks like from here.
                self.close_connection = True
                return
            return self._json(
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
        if path == "/v1/runtimes":
            if STATE["runtimes"] == "refuse":
                self.close_connection = True
                return
            if STATE["runtimes"] == "401":
                return self._json(
                    {"detail": {"title": "Unauthorized", "detail": "not yet valid (iat)"}},
                    status=401,
                )
            runtime = {
                "name": RUNTIME_NAME,
                "status": STATE["status"],
                "engine": "llama_cpp",
                "modelPath": "/models/r21.gguf",
                "url": f"http://127.0.0.1:{DRIVER_PORT}/",
                "capabilities": {"contextLength": 4096, "parallelSlots": 1},
            }
            if STATE["idle"] is not None:
                runtime["idleUnloadSeconds"] = STATE["idle"]
            return self._json({"runtimes": [runtime]})
        if path == "/v1/node":
            return self._json({"name": "r21-node", "enrolled": False})
        if path == "/v1/info":
            return self._json(
                {
                    "backend": "openai_compat_http",
                    "modelId": MODEL,
                    "runtime": RUNTIME_NAME,
                    "version": "0.0.0-stub",
                    "capabilities": {"streaming": True, "maxContextTokens": 4096},
                }
            )
        if path == "/healthz":
            return self._json({"status": "ok"})
        return self._json({"title": "not found"}, status=404)

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        if path == "/v1/generate":
            return self._json(
                {
                    "content": "hello from r21",
                    "finishReason": "stop",
                    "backend": "openai_compat_http",
                    "modelId": MODEL,
                    "latencyMs": 1,
                }
            )
        if path.startswith("/v1/runtimes/") and path.endswith("/stop"):
            name = path.split("/")[3]
            # Sampled from INSIDE the stop: this is the window a request
            # used to be routed into.
            DURING_STOP.append(eligible_now())
            if STATE["slow_stop"]:
                time.sleep(STATE["slow_stop"])
            STOPPED.append(name)
            STATE["status"] = "stopped"
            return self._json({"status": "stopped"}, status=202)
        if path == "/v1/runtimes/admission":
            return self._json({"decision": "admit", "fit": "fits", "reason": "ok", "blockers": []})
        return self._json({"title": "not found"}, status=404)


def serve(port):
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


threading.Thread(target=serve, args=(AGENT_PORT,), daemon=True).start()
serve(DRIVER_PORT)
PY

python stubs.py "$DRIVER_PORT" "$AGENT_PORT" "$MODEL" "$DRIVER_NAME" "$RUNTIME_NAME" "$GW_PORT" \
  > stubs.log 2>&1 &
S_PID=$!
for _ in $(seq 1 30); do curl -sf -m 2 "$STUB/v1/components" >/dev/null 2>&1 && break; sleep 1; done

cat > gateway.yaml <<YAML
routingRefreshSeconds: $REFRESH
idleCheckSeconds: 2
metricsEnabled: false
YAML

(exec env EUGENE_PLEXUS_GATEWAY_CONFIG_FILE="$WORK_NATIVE/gateway.yaml" \
  EUGENE_PLEXUS_GATEWAY_METRICS_FILE="$WORK_NATIVE/metrics.sqlite3" \
  EUGENE_PLEXUS_GATEWAY_BIND_HOST=127.0.0.1 \
  EUGENE_PLEXUS_GATEWAY_BIND_PORT="$GW_PORT" \
  EUGENE_PLEXUS_GATEWAY_AGENT_URL="$STUB" \
  "$GW_PY" -m eugene_plexus_gateway > gateway.log 2>&1) &
G_PID=$!
for _ in $(seq 1 60); do curl -sf -m 2 "$GW/healthz" >/dev/null 2>&1 && break; sleep 1; done

# --- 1 -----------------------------------------------------------------------
say "1. a real gateway routes to the stub driver"
for _ in $(seq 1 30); do [ "$(models_listed)" = "1" ] && break; sleep 1; done
[ "$(models_listed)" = "1" ] && ok "the gateway serves $MODEL" || bad "no model routable"

# --- 2 -----------------------------------------------------------------------
say "2. the baseline: it serves, and the engine is ready"
[ "$(complete)" = "200" ] && ok "a completion is served" || bad "the baseline request failed"
[ "$(backend_field eligible)" = "True" ] && ok "the backend is eligible" || bad "not eligible to begin with"

# --- 3 -----------------------------------------------------------------------
say "3. §6.2 #18: a stopped engine whose agent stops answering /v1/runtimes"
curl -sf -m 5 "$STUB/control/status/stopped" >/dev/null
settle
[ "$(backend_field eligible)" = "False" ] && ok "a stopped engine is not routed to" \
  || bad "a stopped engine is eligible before the read even failed"

curl -sf -m 5 "$STUB/control/runtimes/refuse" >/dev/null
settle
AFTER=$(backend_field eligible)
REASON=$(backend_field ineligible_reason)
note "eligible=$AFTER reason=$REASON"
[ "$AFTER" = "False" ] && ok "the previous facts were kept, not the faith (review §6.2 #18)" \
  || bad "one missed read made a stopped engine routable"
# 503, not 404: the model IS served by something this gateway knows
# about, and none of it can take a request — which is a different
# sentence from "no such model", and the right one. (The first
# execution of this script asserted 404 and reported the product broken
# for saying the more accurate thing.)
CODE=$(complete)
note "a request for a stopped engine returns $CODE"
[ "$CODE" = "503" ] && ok "and a request is told the engine is not ready, not routed to it" \
  || bad "a request for a stopped engine returned $CODE"

say "3b. and a 401 -- the trigger this install has actually produced"
curl -sf -m 5 "$STUB/control/runtimes/401" >/dev/null
settle
[ "$(backend_field eligible)" = "False" ] && ok "half a second of clock skew does not un-gate a node" \
  || bad "a 401 read as 'this node has no runtimes'"
curl -sf -m 5 "$STUB/control/runtimes/ok" >/dev/null
curl -sf -m 5 "$STUB/control/status/ready" >/dev/null
settle

# --- 4 -----------------------------------------------------------------------
say "4. §6.1 #9: the agent stops answering /v1/components"
[ "$(backend_field eligible)" = "True" ] || bad "the engine did not come back ready"
curl -sf -m 5 "$STUB/control/components/refuse" >/dev/null
settle
LISTED=$(models_listed)
note "models listed with the components read failing: $LISTED"
[ "$LISTED" = "1" ] && ok "the node's models stay routable (review §6.1 #9)" \
  || bad "one missed read un-routed every model on the node"
[ "$(complete)" = "200" ] && ok "and a completion still succeeds" \
  || bad "a completion failed while the agent was merely quiet"

# --- 5 -----------------------------------------------------------------------
say "5. the sharp end: a request in flight ACROSS the failing refresh"
# The refresh closes the HTTP clients of drivers it believes have left.
# A request already dispatched is holding one, so closing it turns a
# served completion into a transport error. Ten requests spanning
# several refresh intervals, with the read still failing.
FAILED=0
for _ in $(seq 1 10); do
  [ "$(complete)" = "200" ] || FAILED=$((FAILED + 1))
  sleep 1
done
note "$FAILED of 10 completions failed while /v1/components was refusing"
[ "$FAILED" = "0" ] && ok "no client was closed under a request" \
  || bad "$FAILED completions died because a refresh closed their driver client"

# --- 6 -----------------------------------------------------------------------
say "6. both reads recover"
curl -sf -m 5 "$STUB/control/components/ok" >/dev/null
settle
[ "$(models_listed)" = "1" ] && [ "$(complete)" = "200" ] \
  && ok "the fresh answer replaces the kept one" || bad "the node did not recover"

# --- 7 -----------------------------------------------------------------------
say "7. §6.2 #17: a request arriving while an idle unload is in flight"
# The stub samples the gateway's own admin view from INSIDE the stop
# handler, which is the only vantage point the window is visible from.
curl -sf -m 5 "$STUB/control/slow_stop/2.0" >/dev/null
curl -sf -m 5 "$STUB/control/idle/1" >/dev/null
settle
for _ in $(seq 1 20); do
  STOPS=$(curl -s -m 5 "$STUB/control/stops" | jq_ "d['stopped']" 2>/dev/null)
  printf '%s' "$STOPS" | grep -q "$RUNTIME_NAME" && break
  sleep 1
done
DURING=$(curl -s -m 5 "$STUB/control/stops" | jq_ "d['duringStop']" 2>/dev/null)
note "stops=$STOPS eligible-backends-sampled-during-the-stop=$DURING"
printf '%s' "$STOPS" | grep -q "$RUNTIME_NAME" || bad "the idle unload never happened"
if printf '%s' "$DURING" | grep -q '\-1'; then
  bad "the sample could not read the gateway; check 7 proves nothing"
elif printf '%s' "$DURING" | grep -qE '[1-9]'; then
  bad "a backend was still eligible while its engine was being stopped (review §6.2 #17)"
else
  ok "nothing was routable to the engine being stopped"
fi

# --- 8 -----------------------------------------------------------------------
say "8. teardown"
teardown
G_PID=""; S_PID=""
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ] && ok "every owned port released" || bad "still listening:$STILL"

printf '\n== %s\n' "$([ "$FAILURES" -eq 0 ] && echo 'ALL CHECKS PASSED' || echo "$FAILURES CHECK(S) FAILED")"
exit "$FAILURES"
