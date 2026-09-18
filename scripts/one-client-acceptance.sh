#!/usr/bin/env bash
# R1.1 — one client, one context, one clock. Live.
#
# Roadmap: docs/design/release-roadmap.md §2.1. Findings: review §6.1 #2,
# §6.2 #23, §6.2 #25.
#
# What only a live run can prove. The unit checks in each repo
# (`test_http_client_reuse.py`) pin client lifetime, the clock and the
# proxy rule against fixtures. None of them can prove that a real agent
# spawns a real gateway and a real driver that together answer a
# completion in single-digit milliseconds of control-plane overhead,
# that the numbers the gateway reports are finer than a 15.6 ms grid, or
# that an install whose environment carries a corporate `HTTP_PROXY`
# comes up at all -- which is the one a Windows user actually meets,
# because the logon task inherits the user environment.
#
# The checks:
#   0. isolated from any install on this machine, and from its ports
#   1. the five packages import, and a COLD interpreter can build its
#      first shared client (the reentrant-lock deadlock, which a warm
#      process cannot reproduce)
#   2. a stub backend with a known think time, so every millisecond
#      above it is ours
#   3. the fleet comes up: agent -> gateway + driver
#   4. one completion end to end
#   5. **the headline**: control-plane overhead per request is single
#      digit. Before this slice the driver alone added ~104 ms, because
#      it built an `httpx.AsyncClient()` per call and constructing one
#      parses certifi's PEM bundle on the event loop
#   6. **the clock**: the reported `*_ms` are not confined to a 15.6 ms
#      lattice. `time.monotonic()` on Windows/CPython 3.12 -- the Python
#      both installers provision -- is `GetTickCount64`, and every
#      duration this project reports rode on it
#   7. **concurrency**: ten at once cost about what one costs. The parse
#      was synchronous CPU, so it froze every in-flight stream
#   8. **the proxy**: the whole install again, with HTTP_PROXY and
#      HTTPS_PROXY pointing at a dead port. It must still come up
#      `running` and still serve. Before this slice every loopback hop
#      went to the proxy, and the install sat at `starting` while
#      actually serving -- a state no screen explains
#   9. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped (install.ps1 sets the config-file var in the USER
# environment, so a throwaway agent would otherwise come up as the live
# worker and announce a dying port to the real control root -- that
# happened, 2026-09-12), ports are +100, teardown is by pid. Never
# `pkill -f eugene_plexus_`: this box is a worker node.
#
# **No GPU, no model, no engine binary.** The subject is HTTP client
# lifetime, clocks and proxy handling; a stub backend with a fixed think
# time is a better instrument than a real engine, whose own variance
# would swamp the thing being measured.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-one-client}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
GW_PORT="${EP_GW_PORT:-8180}"
DRIVER_PORT="${EP_DRIVER_PORT:-8181}"
STUB_PORT="${EP_STUB_PORT:-8188}"
AGENT="http://127.0.0.1:$AGENT_PORT"
GW="http://127.0.0.1:$GW_PORT"
OWNED_PORTS="$AGENT_PORT $GW_PORT $DRIVER_PORT $STUB_PORT"

# The stub sleeps this long before answering. Everything above it, per
# request, is this control plane.
THINK_MS="${EP_THINK_MS:-5}"
# The budget the slice is defended by. Generous against the 104 ms it
# replaces, tight enough that a regression cannot hide: ~2 ms is what
# this box measures.
BUDGET_MS="${EP_BUDGET_MS:-25}"
PASSPHRASE="one-client-$$"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }

A_PID=""
S_PID=""
teardown() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 3; }
  [ -n "$S_PID" ] && kill "$S_PID" 2>/dev/null
  for p in $OWNED_PORTS; do
    for pid in $(listening_pids "$p"); do
      taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
    done
  done
}

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
"$PY" -c "import eugene_plexus_agent, eugene_plexus_gateway, eugene_plexus_inference_driver" 2>/dev/null \
  || { bad "agent, gateway and inference-driver must import from $PY"; exit 1; }
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
ok "agent python with the three packages; ports $OWNED_PORTS free"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

# --- 0 -----------------------------------------------------------------------
say "0. isolate this run"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy NO_PROXY no_proxy
WORK_NATIVE=$(win_path "$WORK")
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }
[ -z "$(env | grep -i '^http[s]*_proxy=' || true)" ] && ok "no ambient proxy variable (check 8 sets its own)" || bad "a proxy variable leaked into the clean run"

# --- 1 -----------------------------------------------------------------------
say "1. a COLD interpreter builds its first shared client"
# A warm process cannot reproduce this. The first cut of `_http` guarded
# the SSL-context cache with a plain `threading.Lock` and then called
# `ssl_context()` from inside it -- a deadlock on the FIRST call of a
# process and only the first, because every later caller finds the
# context already built and never reaches the acquire. The whole agent
# suite was green and a cold agent hung on its first engine probe.
for pkg in eugene_plexus_agent eugene_plexus_gateway eugene_plexus_inference_driver; do
  OUT=$(timeout 45 "$PY" -c "
import asyncio
from $pkg import _http
c = _http.shared_internal_client('probe')
assert c is _http.shared_internal_client('probe')
assert _http.ssl_context() is _http.ssl_context()
asyncio.run(_http.aclose_shared())
print('ok')
" 2>&1 | tr -d '\r')
  [ "$OUT" = "ok" ] && ok "$pkg: cold start builds one context and one client" \
    || bad "$pkg: cold start did not finish ($OUT)"
done

# --- 2 -----------------------------------------------------------------------
say "2. a stub backend that thinks for ${THINK_MS}ms"
cat > stub.py <<'PY'
import json, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1])
THINK = float(sys.argv[2]) / 1000.0
BODY = {
    "model": "stub",
    "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        if self.path == "/v1/models":
            self._send(200, {"data": [{"id": "stub"}]})
        else:
            self._send(404, {})
    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(n)
        time.sleep(THINK)
        self._send(200, BODY)

ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
PY
"$PY" stub.py "$STUB_PORT" "$THINK_MS" > stub.log 2>&1 &
S_PID=$!
for _ in $(seq 1 30); do curl -sf -m 2 "http://127.0.0.1:$STUB_PORT/v1/models" >/dev/null 2>&1 && break; sleep 1; done
curl -sf -m 2 "http://127.0.0.1:$STUB_PORT/v1/models" >/dev/null 2>&1 \
  && ok "stub answering on :$STUB_PORT" || { bad "stub never came up"; cat stub.log; exit 1; }

# The stub's own floor, measured rather than assumed: everything above
# this in check 5 is the control plane, and this number is what makes
# that subtraction honest.
STUB_MS=$("$PY" - "$STUB_PORT" <<'PY'
# **Measured through a POOLED client, because the control plane uses one.**
# A fresh connection per request costs a TCP handshake the driver's reused
# client does not pay, and measuring the floor that way made the control
# plane look FASTER than the backend it sits in front of -- a negative
# overhead, which is an instrument fault rather than a result. Two spans
# measured by different instruments is the mistake that produced the
# original "unexplained 116 ms"; it is not repeated here.
import statistics, sys, time

import httpx

port = sys.argv[1]
payload = {"model": "stub", "messages": [{"role": "user", "content": "hi"}]}
with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as c:
    for _ in range(3):
        c.post("/v1/chat/completions", json=payload)
    ms = []
    for _ in range(15):
        t = time.perf_counter()
        c.post("/v1/chat/completions", json=payload)
        ms.append((time.perf_counter() - t) * 1000)
print(round(statistics.median(ms), 1))
PY
)
note "stub's own median round trip: ${STUB_MS}ms"

# --- 3 -----------------------------------------------------------------------
say "3. the fleet: agent spawns gateway and driver"
cat > agent.yaml <<YAML
firstRunComplete: true
components:
  - name: gateway
    kind: gateway
    url: http://127.0.0.1:$GW_PORT
    spawn:
      configFile: gateway.yaml
  - name: stub-driver
    kind: inference-driver
    url: http://127.0.0.1:$DRIVER_PORT
    spawn:
      configFile: driver.yaml
YAML
echo "logLevel: INFO" > gateway.yaml
cat > driver.yaml <<YAML
provider: openai_compat_custom
baseUrl: http://127.0.0.1:$STUB_PORT
modelId: stub
YAML

(exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" \
  EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 \
  EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
  "$PY" -m eugene_plexus_agent --unattended > agent.log 2>&1) &
A_PID=$!

for _ in $(seq 1 60); do curl -sf -m 2 "$AGENT/healthz" >/dev/null 2>&1 && break; sleep 1; done
curl -sf -m 2 "$AGENT/healthz" >/dev/null 2>&1 && ok "agent answering on :$AGENT_PORT" \
  || { bad "agent never came up"; tail -40 agent.log; exit 1; }

# What the wizard's Start button does. Every operator read below carries
# this; the children get service tokens at spawn.
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json'   -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] && ok "operator session issued" || { bad "no session token"; tail -30 agent.log; exit 1; }
AUTH=(-H "Authorization: Bearer $TOK")

for _ in $(seq 1 90); do
  S=$(curl -s -m 3 "${AUTH[@]}" "$AGENT/v1/components" 2>/dev/null | jq_ "' '.join(sorted(c['name']+'='+c['status'] for c in d['components']))" 2>/dev/null)
  case "$S" in *"gateway=running"*"stub-driver=running"*) break ;; esac
  sleep 1
done
note "components: $S"
case "$S" in *"gateway=running"*) ok "gateway running" ;; *) bad "gateway not running" ;; esac
case "$S" in *"stub-driver=running"*) ok "driver running" ;; *) bad "driver not running" ;; esac

# --- 4 -----------------------------------------------------------------------
say "4. one completion, end to end"
for _ in $(seq 1 40); do
  M=$(curl -s -m 3 "${AUTH[@]}" "$GW/v1/models" 2>/dev/null | jq_ "len(d.get('data') or [])" 2>/dev/null)
  [ "${M:-0}" -gt 0 ] && break
  sleep 1
done
BODY='{"model":"stub","messages":[{"role":"user","content":"hi"}]}'
R=$(curl -s -m 20 "${AUTH[@]}" -H 'Content-Type: application/json' -d "$BODY" "$GW/v1/chat/completions")
CONTENT=$(printf '%s' "$R" | jq_ "d['choices'][0]['message']['content']" 2>/dev/null)
[ "$CONTENT" = "ok" ] && ok "a completion came back through the gateway" || { bad "no completion: $R"; }

# --- 5 -----------------------------------------------------------------------
say "5. control-plane overhead per request is single digit"
MEASURE=$("$PY" - "$GW_PORT" "$STUB_MS" "$TOK" <<'PY'
import json, statistics, sys, time

import httpx

port, stub_ms, tok = sys.argv[1], float(sys.argv[2]), sys.argv[3]
payload = {"model": "stub", "messages": [{"role": "user", "content": "hi"}]}
totals, reported = [], []
with httpx.Client(
    base_url=f"http://127.0.0.1:{port}",
    headers={"Authorization": f"Bearer {tok}"},
    timeout=30.0,
    trust_env=False,
) as c:
    for _ in range(3):
        c.post("/v1/chat/completions", json=payload)
    for _ in range(15):
        t = time.perf_counter()
        body = c.post("/v1/chat/completions", json=payload).json()
        totals.append((time.perf_counter() - t) * 1000)
        env = body.get("x_eugene_plexus") or {}
        if env.get("latency_ms") is not None:
            reported.append(env["latency_ms"])
median = statistics.median(totals)
print(json.dumps({
    "median_total_ms": round(median, 1),
    "stub_floor_ms": stub_ms,
    "overhead_ms": round(median - stub_ms, 1),
    "reported": sorted(reported),
}))
PY
)
note "$MEASURE"
OVERHEAD=$(printf '%s' "$MEASURE" | jq_ "d['overhead_ms']")
OVER_INT=$(printf '%.0f' "${OVERHEAD:-99999}")
if [ "$OVER_INT" -lt -2 ]; then
  # The gateway cannot be faster than the backend it forwards to. A
  # negative number means the floor and the total were measured by
  # different instruments -- the exact mistake that produced the
  # original "unexplained 116 ms", so it fails rather than passing.
  bad "overhead ${OVERHEAD}ms is negative -- the floor and the total were not measured the same way"
elif [ "$OVER_INT" -le "$BUDGET_MS" ]; then
  ok "control-plane overhead ${OVERHEAD}ms (budget ${BUDGET_MS}ms; ~104ms before this slice, per client construction)"
else
  bad "control-plane overhead ${OVERHEAD}ms exceeds ${BUDGET_MS}ms -- a client is being built per call again"
fi

# --- 6 -----------------------------------------------------------------------
say "6. the reported durations are finer than a 15.6ms grid"
# `time.monotonic()` on Windows/CPython 3.12 is `GetTickCount64`: 20
# distinct values in 300ms. Against a backend this fast, every reported
# number would be 0 or 15 or 31 -- and subtracting two such spans is how
# a 104ms cost came out as an unexplained 116ms.
GRID=$(printf '%s' "$MEASURE" | "$PY" -c "
import json, sys
d = json.load(sys.stdin)
vals = d['reported']
off = [v for v in vals if v % 15 not in (0, 14) and v % 16 != 0]
print(json.dumps({'n': len(vals), 'distinct': len(set(vals)), 'off_grid': len(off), 'values': vals[:8]}))
")
note "$GRID"
OFFGRID=$(printf '%s' "$GRID" | jq_ "d['off_grid']")
DISTINCT=$(printf '%s' "$GRID" | jq_ "d['distinct']")
if [ "${OFFGRID:-0}" -ge 1 ] || [ "${DISTINCT:-0}" -ge 3 ]; then
  ok "reported latencies are not confined to the GetTickCount64 lattice (${DISTINCT} distinct, ${OFFGRID} off-grid)"
else
  bad "every reported latency sits on a 15.6ms grid -- a duration is still measured with monotonic()"
fi

# --- 7 -----------------------------------------------------------------------
say "7. ten concurrent completions do not serialise"
CONC=$("$PY" - "$GW_PORT" "$TOK" <<'PY'
import json, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
port, tok = sys.argv[1], sys.argv[2]
body = json.dumps({"model": "stub", "messages": [{"role": "user", "content": "hi"}]}).encode()
HEAD = {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}

def one(_):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
                                 headers=HEAD)
    t = time.perf_counter()
    urllib.request.urlopen(req, timeout=60).read()
    return (time.perf_counter() - t) * 1000

with ThreadPoolExecutor(max_workers=10) as pool:
    list(pool.map(one, range(10)))          # warm
    t = time.perf_counter()
    each = list(pool.map(one, range(10)))
    wall = (time.perf_counter() - t) * 1000
print(json.dumps({"wall_ms": round(wall, 1), "slowest_ms": round(max(each), 1)}))
PY
)
note "$CONC"
WALL=$(printf '%s' "$CONC" | jq_ "d['wall_ms']")
WALL_INT=$(printf '%.0f' "${WALL:-99999}")
# Ten at once used to mean ten certifi parses queued behind each other on
# one event loop: over a second of pure CPU, whatever the backend did.
if [ "$WALL_INT" -lt 1000 ]; then
  ok "ten concurrent completions in ${WALL}ms (ten client builds alone would be ~1000ms of blocked loop)"
else
  bad "ten concurrent completions took ${WALL}ms -- something synchronous is on the event loop"
fi

# --- 8 -----------------------------------------------------------------------
say "8. the same install, with a corporate HTTP_PROXY in the environment"
# The one a Windows user actually meets: the logon task inherits the USER
# environment, so `HTTP_PROXY` reaches every component. With httpx's
# default `trust_env`, every loopback hop went to a proxy that cannot
# reach 127.0.0.1 -- health probes, topology reads, gateway->driver --
# and the install sat at `starting` while actually serving.
kill "$A_PID" 2>/dev/null; sleep 4
for p in $AGENT_PORT $GW_PORT $DRIVER_PORT; do
  for pid in $(listening_pids "$p"); do taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null; done
done
DEAD_PROXY="http://127.0.0.1:9"   # discard port: nothing listens, ever
(exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" \
  EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 \
  EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
  HTTP_PROXY="$DEAD_PROXY" HTTPS_PROXY="$DEAD_PROXY" \
  http_proxy="$DEAD_PROXY" https_proxy="$DEAD_PROXY" \
  "$PY" -m eugene_plexus_agent --unattended > agent-proxy.log 2>&1) &
A_PID=$!
for _ in $(seq 1 60); do curl -sf -m 2 --noproxy '*' "$AGENT/healthz" >/dev/null 2>&1 && break; sleep 1; done
curl -sf -m 2 --noproxy '*' "$AGENT/healthz" >/dev/null 2>&1 \
  && ok "agent came up with a dead proxy in its environment" || { bad "agent never came up under a proxy"; tail -30 agent-proxy.log; }

# Sign in again. The restarted agent re-derives the install's signing key,
# and a session minted before the restart is not valid against it --
# reusing it would report a stale credential as the proxy defect this
# check exists to find, which is how the first execution read.
TOK=$(curl -s --noproxy '*' -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
if [ -n "$TOK" ]; then AUTH=(-H "Authorization: Bearer $TOK"); ok "signed in again after the restart"; else bad "could not sign in after the restart"; tail -30 agent-proxy.log; fi

for _ in $(seq 1 90); do
  S=$(curl -s -m 3 --noproxy '*' "${AUTH[@]}" "$AGENT/v1/components" 2>/dev/null | jq_ "' '.join(sorted(c['name']+'='+c['status'] for c in d['components']))" 2>/dev/null)
  case "$S" in *"gateway=running"*"stub-driver=running"*) break ;; esac
  sleep 1
done
note "components under a dead proxy: $S"
case "$S" in
  *"gateway=running"*"stub-driver=running"*)
    ok "both components reach RUNNING -- the health poller is not going through the proxy" ;;
  *)
    bad "components did not reach running under a proxy: $S (this is review §6 #25: the install sits at 'starting' while serving)" ;;
esac

R=$(curl -s -m 20 --noproxy '*' "${AUTH[@]}" -H 'Content-Type: application/json' -d "$BODY" "$GW/v1/chat/completions")
CONTENT=$(printf '%s' "$R" | jq_ "d['choices'][0]['message']['content']" 2>/dev/null)
[ "$CONTENT" = "ok" ] \
  && ok "a completion still crosses gateway -> driver -> backend with a dead proxy set" \
  || bad "no completion under a proxy: $R"

# --- 9 -----------------------------------------------------------------------
say "9. teardown"
teardown
A_PID=""; S_PID=""
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ] && ok "no owned port still listening" || bad "still listening:$STILL"

printf '\n'
if [ "$FAILURES" = 0 ]; then
  printf 'ALL CHECKS PASSED\n'
else
  printf '%d CHECK(S) FAILED\n' "$FAILURES"
fi
exit "$FAILURES"
