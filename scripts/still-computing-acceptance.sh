#!/usr/bin/env bash
# R2.5 -- a backend that is still computing has not failed. Live.
#
# Roadmap: docs/design/release-roadmap.md §3.5. Findings: review §6.2 #13,
# §6.2 #16.
#
# What only a live run can prove.
#
# The unit checks drive `_is_cascade_eligible`, the engine's exception
# handling and `serve_while_connected` in process. Three of this slice's
# four claims are about things that only exist between processes:
#
#   * **the ORDER of two deadlines**, which no single repo can see. The
#     defect was that the driver's 120 s fired before the gateway's
#     180 s, so the knob the UI and the docs point an operator at
#     governed nothing. Here both numbers are read from the two running
#     processes' own `GET /v1/config`, not from either source tree.
#   * **that nothing recomputes**, which needs a second replica on a
#     real socket that can be counted.
#   * **that a cancellation crosses every hop**. A closed client has to
#     reach the gateway, cancel its call to the driver, cancel the
#     driver's call to the engine, and close the socket the engine is
#     writing into. Four processes, three sockets; an in-process test
#     of any one of them cannot claim it.
#   * and **that the knob survives a restart**, which is what "durable"
#     means and what a boot reconcile was silently undoing.
#
# The checks:
#   0. isolated from any install on this machine, and from its ports
#   1. a real gateway over a REAL inference-driver and stub replicas
#   2. the baseline: a completion is served, and the backup replica CAN
#      answer -- without this, "the backup was never called" passes for
#      the wrong reason
#   3. **the order, read from the two running processes**: the driver's
#      deadline is above the gateway's, and the shipped defaults are too
#   4. **§6.2 #13**: the driver's own deadline fires. The caller gets a
#      504 that names seconds and a setting, NOT "Every backend serving
#      'x' failed", and the second replica was never asked
#   5. the gateway's own read deadline fires: same answer, same silence
#      on the second replica
#   6. the control: a DEAD backend still cascades, so failover is intact
#   7. the control: an over-long prompt still hard-fails as a 400
#   8. **§6.2 #16**: the client is killed mid-request. The engine's
#      socket closes before it finishes, so the generation was cancelled
#      rather than left running into nothing
#   9. and it holds one hop down: the driver alone, killed the same way
#  10. **the knob is durable**: a real agent boot-reconciles a companion
#      driver, the operator edits its timeout, the agent restarts, and
#      the edit is still there
#  11. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped, ports are +100, teardown is by pid. Never
# `pkill -f eugene_plexus_`: this box is a worker node.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
GW_PY="${EP_GW_PY:-$EP_ROOT/gateway/.venv/Scripts/python.exe}"
DRV_PY="${EP_DRV_PY:-$EP_ROOT/inference-driver/.venv/Scripts/python.exe}"
AGENT_PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-r25}"

GW_PORT="${EP_GW_PORT:-8190}"
AGENT_PORT="${EP_STUB_AGENT_PORT:-8191}"
DRIVER_PORT="${EP_DRIVER_PORT:-8192}"     # the REAL inference-driver
ENGINE_PORT="${EP_ENGINE_PORT:-8193}"     # the stub engine behind it
BACKUP_PORT="${EP_BACKUP_PORT:-8194}"     # a stub driver: the 2nd replica
STALL_PORT="${EP_STALL_PORT:-8195}"       # a stub driver that never answers
DEAD_PORT="${EP_DEAD_PORT:-8196}"         # nothing listens here, ever
REALAGENT_PORT="${EP_REALAGENT_PORT:-8197}"

GW="http://127.0.0.1:$GW_PORT"
DRV="http://127.0.0.1:$DRIVER_PORT"
OWNED_PORTS="$GW_PORT $AGENT_PORT $DRIVER_PORT $ENGINE_PORT $BACKUP_PORT $STALL_PORT $DEAD_PORT $REALAGENT_PORT"

MODEL="r25-model"        # real driver + backup replica
STALLED="r25-stalled"    # stub that never answers + backup replica
CASCADE="r25-cascade"    # dead backend, tier 1 of its own slot
BACKUP_MODEL="r25-backup"
# **The backup serves a model id of its OWN, reached only as tier 2 of a
# slot.** It used to answer for `r25-model`, which made check 5's "the
# second replica was never asked" vacuous: `r25-stalled` had exactly one
# backend, so there was nothing to cascade TO and the check passed with
# the defect put back. The sabotage pass found that.

# The two deadlines, deliberately close together so the run is short,
# and deliberately in the SHIPPED order: the gateway's below the
# driver's. Check 3 asserts the shipped defaults keep that order too.
GW_TIMEOUT=9
DRV_TIMEOUT=12
ENGINE_SLEEP=40          # longer than either, so the engine is always
                         # still computing when a deadline fires

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }
kill_port() { for pid in $(listening_pids "$1"); do taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null; done; }

G_PID=""; D_PID=""; S_PID=""; A_PID=""
teardown() {
  for p in "$G_PID" "$D_PID" "$A_PID"; do [ -n "$p" ] && kill "$p" 2>/dev/null; done
  sleep 2
  [ -n "$S_PID" ] && kill "$S_PID" 2>/dev/null
  for p in $OWNED_PORTS; do kill_port "$p"; done
}

say "preflight"
for py in "$GW_PY" "$DRV_PY" "$AGENT_PY"; do
  [ -f "$py" ] || { bad "no interpreter at $py"; exit 1; }
done
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
ok "three interpreters present; ports $OWNED_PORTS free"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

# --- 0 -----------------------------------------------------------------------
say "0. isolate this run"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy NO_PROXY no_proxy
WORK_NATIVE=$(win_path "$WORK")
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }

# --- the stubs ---------------------------------------------------------------
# One process, four ports:
#
#   AGENT_PORT   the topology the gateway reads
#   ENGINE_PORT  an OpenAI-compatible ENGINE behind the real driver. It
#                sleeps, in one-second steps, writing nothing -- so a
#                read deadline is the only way the call ever ends, and
#                it can tell the difference between "I finished" and
#                "the socket under me closed". That last fact is the
#                whole of check 8.
#   BACKUP_PORT  a stub inference-driver that answers instantly: the
#                second replica nothing may recompute onto
#   STALL_PORT   a stub inference-driver that never answers at all, so
#                the GATEWAY's own read deadline is the one that fires
cat > stubs.py <<'PY'
from __future__ import annotations

import json
import select
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AGENT_PORT = int(sys.argv[1])
ENGINE_PORT = int(sys.argv[2])
BACKUP_PORT = int(sys.argv[3])
STALL_PORT = int(sys.argv[4])
DRIVER_PORT = int(sys.argv[5])
DEAD_PORT = int(sys.argv[6])
MODEL, STALLED, CASCADE = sys.argv[7], sys.argv[8], sys.argv[9]
ENGINE_SLEEP = float(sys.argv[10])
BACKUP_MODEL = sys.argv[11]

LOCK = threading.Lock()
# What the engine did with each call it was given. "cut" means the
# socket under it closed before its sleep was up -- which is the only
# evidence a cancellation reached all the way down.
ENGINE_CALLS: list[str] = []
BACKUP_CALLS: list[str] = []


def record(bucket: list[str], value: str) -> None:
    with LOCK:
        bucket.append(value)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # noqa: A002
        pass

    def _json(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    # -- the agent's topology --------------------------------------------
    def _components(self):
        return {
            "components": [
                {"name": "r25-driver", "kind": "inference-driver",
                 "url": f"http://127.0.0.1:{DRIVER_PORT}/", "status": "running"},
                {"name": "r25-backup", "kind": "inference-driver",
                 "url": f"http://127.0.0.1:{BACKUP_PORT}/", "status": "running"},
                {"name": "r25-stall", "kind": "inference-driver",
                 "url": f"http://127.0.0.1:{STALL_PORT}/", "status": "running"},
                {"name": "r25-dead", "kind": "inference-driver",
                 "url": f"http://127.0.0.1:{DEAD_PORT}/", "status": "running"},
            ]
        }

    def _info_for(self, port):
        model = {BACKUP_PORT: BACKUP_MODEL, STALL_PORT: STALLED, DEAD_PORT: CASCADE}[port]
        return {
            "backend": "openai_compat_http",
            "modelId": model,
            "version": "0.0.0-stub",
            "capabilities": {"streaming": True, "maxContextTokens": 4096},
        }

    def do_GET(self):  # noqa: N802
        port = self.server.server_address[1]
        path = self.path.split("?")[0]
        if port == AGENT_PORT:
            if path == "/v1/components":
                return self._json(self._components())
            if path == "/v1/runtimes":
                return self._json({"runtimes": []})
            if path == "/v1/node":
                return self._json({"name": "r25-node", "enrolled": False})
            if path == "/control/engine-calls":
                with LOCK:
                    return self._json({"calls": list(ENGINE_CALLS)})
            if path == "/control/reset-engine-calls":
                # Checks 4 and 5 leave a 40 s sleeper running, whose
                # eventual `finished` would otherwise land in the middle
                # of check 8 and be read as check 8's own answer.
                with LOCK:
                    ENGINE_CALLS.clear()
                return self._json({"calls": []})
            if path == "/control/backup-calls":
                with LOCK:
                    return self._json({"calls": list(BACKUP_CALLS)})
            if path == "/healthz":
                return self._json({"status": "ok"})
            return self._json({"title": "not found"}, status=404)

        if port == STALL_PORT and path == "/v1/info":
            # A driver that answers `info` (so the gateway routes to it)
            # and then never answers a generation.
            return self._json(self._info_for(STALL_PORT))
        if path == "/v1/info":
            return self._json(self._info_for(port))
        if path == "/healthz":
            return self._json({"status": "ok"})
        if path == "/v1/models":
            return self._json({"data": [{"id": MODEL}]})
        return self._json({"title": "not found"}, status=404)

    def do_POST(self):  # noqa: N802
        port = self.server.server_address[1]
        path = self.path.split("?")[0]
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length)

        # -- the ENGINE behind the real driver ---------------------------
        if port == ENGINE_PORT and path == "/v1/chat/completions":
            text = body.decode("utf-8", "replace")
            if "OVERLONG" in text:
                # llama.cpp's own answer to a prompt past the window: a
                # 400 naming both numbers. Must still hard-fail.
                return self._json(
                    {"error": {"message": "n_prompt_tokens 20597 > n_ctx 512"}}, status=400
                )
            if "FAST" in text:
                return self._json({
                    "id": "c1", "object": "chat.completion", "created": 1,
                    "model": MODEL,
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": "engine answer"}}],
                })
            # The slow path: sleep in steps, and notice if the socket
            # under us goes away.
            #
            # **The instrument, and the first execution got it wrong.** A
            # zero-length `send()` on a socket whose peer has closed
            # returns 0 on Windows without raising, so the first version
            # of this probe reported every cancelled call as `finished`
            # and both disconnect checks failed against a working fix.
            # A readable socket that peeks empty is the portable answer:
            # nothing is ever sent to us on this connection, so readable
            # can only mean FIN.
            started = time.monotonic()
            deadline = started + ENGINE_SLEEP
            while time.monotonic() < deadline:
                time.sleep(0.25)
                readable, _, _ = select.select([self.connection], [], [], 0)
                if readable:
                    try:
                        peeked = self.connection.recv(1, socket.MSG_PEEK)
                    except OSError:
                        peeked = b""
                    if peeked == b"":
                        # **The elapsed time is load-bearing, and the
                        # sabotage pass is why.** A socket also closes
                        # when a DEADLINE fires and httpx drops the
                        # connection, so a bare "cut" cannot tell a
                        # cancelled request from a timed-out one -- and
                        # checks 8 and 9 passed with the fix removed,
                        # reading the driver's own 12 s deadline as
                        # evidence of a cancellation. The number lets
                        # them require a cut far below either deadline.
                        record(ENGINE_CALLS, f"cut@{time.monotonic() - started:.1f}")
                        return
            record(ENGINE_CALLS, "finished")
            return self._json({
                "id": "c1", "object": "chat.completion", "created": 1, "model": MODEL,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "too late"}}],
            })

        # -- the stub DRIVER that never answers --------------------------
        if port == STALL_PORT:
            time.sleep(ENGINE_SLEEP)
            return self._json({"title": "never"}, status=500)

        # -- the stub DRIVER that is the second replica ------------------
        if port == BACKUP_PORT and path in ("/v1/generate", "/v1/generate/stream"):
            record(BACKUP_CALLS, path)
            return self._json({
                "content": "backup reply", "finishReason": "stop",
                "backend": "openai_compat_http", "modelId": MODEL, "latencyMs": 1,
            })
        return self._json({"title": "not found"}, status=404)


def serve(port):
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


for extra in (AGENT_PORT, BACKUP_PORT, STALL_PORT):
    threading.Thread(target=serve, args=(extra,), daemon=True).start()
serve(ENGINE_PORT)
PY

python stubs.py "$AGENT_PORT" "$ENGINE_PORT" "$BACKUP_PORT" "$STALL_PORT" \
  "$DRIVER_PORT" "$DEAD_PORT" "$MODEL" "$STALLED" "$CASCADE" "$ENGINE_SLEEP"   "$BACKUP_MODEL" > stubs.log 2>&1 &
S_PID=$!
for _ in $(seq 1 30); do curl -sf -m 2 "http://127.0.0.1:$AGENT_PORT/v1/components" >/dev/null 2>&1 && break; sleep 1; done

# --- the real inference-driver ------------------------------------------------
cat > driver.yaml <<YAML
provider: openai_compat_custom
baseUrl: http://127.0.0.1:$ENGINE_PORT
modelId: $MODEL
requestTimeoutSeconds: $DRV_TIMEOUT
logLevel: INFO
YAML

(exec env EUGENE_PLEXUS_DRIVER_CONFIG_FILE="$WORK_NATIVE/driver.yaml" \
  EUGENE_PLEXUS_DRIVER_BIND_HOST=127.0.0.1 \
  EUGENE_PLEXUS_DRIVER_BIND_PORT="$DRIVER_PORT" \
  "$DRV_PY" -m eugene_plexus_inference_driver > driver.log 2>&1) &
D_PID=$!
for _ in $(seq 1 60); do curl -sf -m 2 "$DRV/healthz" >/dev/null 2>&1 && break; sleep 1; done

# Two slots, so there is somewhere for a cascade to GO. Without them
# checks 5 and 6 are assertions about a one-backend model and cannot
# tell a cascade from its absence.
cat > gateway.yaml <<YAML
routingRefreshSeconds: 3
requestTimeoutSeconds: $GW_TIMEOUT
metricsEnabled: true
metricsRetentionDays: 1
modelSlots:
  - model: $STALLED
    targets: [$BACKUP_MODEL]
  - model: $CASCADE
    targets: [$BACKUP_MODEL]
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
say "1. a real gateway over a real driver, with a second replica"
for _ in $(seq 1 40); do
  IDS=$(curl -s -m 5 "$GW/v1/models" | jq_ "' '.join(sorted(m['id'] for m in d.get('data') or []))" 2>/dev/null)
  case "$IDS" in *"$MODEL"*"$STALLED"*) break ;; esac
  sleep 1
done
echo "  models: $IDS"
case "$IDS" in *"$MODEL"*) ok "the gateway serves $MODEL" ;; *) bad "no model routable"; tail -20 gateway.log; exit 1 ;; esac
case "$IDS" in
  *"$BACKUP_MODEL"*"$CASCADE"*"$MODEL"*"$STALLED"*)
    ok "all four are routable: the real driver, the backup, the stalled stub and the dead one" ;;
  *) bad "expected four models, got: $IDS" ;;
esac
SLOTS=$(curl -s -m 5 "$GW/v1/config" | jq_ "' '.join(sorted(s['model'] for s in d.get('modelSlots') or []))")
case "$SLOTS" in
  *"$CASCADE"*"$STALLED"*) ok "both fallback slots are loaded: $SLOTS -> $BACKUP_MODEL" ;;
  *) bad "the slots are not configured, so checks 5 and 6 would have nowhere to cascade: $SLOTS" ;;
esac

# --- 2 -----------------------------------------------------------------------
say "2. baseline: a completion is served, and the backup CAN be reached"
FAST=$(curl -s -m 30 -X POST "$GW/v1/chat/completions" -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"FAST please\"}]}")
CONTENT=$(printf '%s' "$FAST" | jq_ "(d.get('choices') or [{}])[0].get('message',{}).get('content')" 2>/dev/null)
[ "$CONTENT" = "engine answer" ] && ok "the real driver serves a completion through the real engine" \
  || bad "no completion from the real driver: $(printf '%s' "$FAST" | head -c 300)"
# **Without this, "the backup was never asked" means nothing.** The
# backup is tier 2 of two slots; if it could not answer at all, every
# non-cascade check below would pass for the wrong reason.
DIRECTB=$(curl -s -m 30 -X POST "$GW/v1/chat/completions" -H 'content-type: application/json' \
  -d "{\"model\":\"$BACKUP_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}")
BCONTENT=$(printf '%s' "$DIRECTB" | jq_ "(d.get('choices') or [{}])[0].get('message',{}).get('content')" 2>/dev/null)
[ "$BCONTENT" = "backup reply" ] && ok "the tier-2 backup answers when it IS asked" \
  || bad "the backup cannot answer at all: $(printf '%s' "$DIRECTB" | head -c 300)"

# --- 3 -----------------------------------------------------------------------
say "3. THE ORDER, read from the two running processes"
GW_T=$(curl -s -m 5 "$GW/v1/config" | jq_ "d['requestTimeoutSeconds']")
DRV_T=$(curl -s -m 5 "$DRV/v1/config" | jq_ "d['requestTimeoutSeconds']")
echo "  gateway=$GW_T  driver=$DRV_T"
python - "$GW_T" "$DRV_T" <<'PY' && ok "the driver's deadline sits above the gateway's, live" || bad "the driver would fire first: the gateway's knob governs nothing"
import sys
sys.exit(0 if float(sys.argv[1]) < float(sys.argv[2]) else 1)
PY
# And the same for what an install actually ships, which is the half the
# review found wrong: 120 s against 180 s.
GW_DEF=$(curl -s -m 5 "$GW/v1/config/schema" | jq_ "next(f['default'] for f in d['fields'] if f['key']=='requestTimeoutSeconds')")
DRV_DEF=$(curl -s -m 5 "$DRV/v1/config/schema" | jq_ "next(f['default'] for f in d['fields'] if f['key']=='requestTimeoutSeconds')")
echo "  shipped defaults: gateway=$GW_DEF driver=$DRV_DEF"
python - "$GW_DEF" "$DRV_DEF" <<'PY' && ok "the SHIPPED defaults are in the same order ($GW_DEF < $DRV_DEF)" || bad "shipped defaults are inverted: $GW_DEF vs $DRV_DEF"
import sys
sys.exit(0 if float(sys.argv[1]) < float(sys.argv[2]) else 1)
PY
python - "$GW_DEF" <<'PY' && ok "the gateway's shipped deadline is minutes, not seconds ($GW_DEF s)" || bad "the shipped deadline is too short for a model on the processor: $GW_DEF s"
import sys
sys.exit(0 if float(sys.argv[1]) >= 300 else 1)
PY

# --- 4 -----------------------------------------------------------------------
# The driver's deadline is 12 s and the gateway's is 9 s, so to make the
# DRIVER the one that fires the gateway has to be given longer for this
# one request -- which curl cannot do. Instead: the driver is asked
# DIRECTLY, exactly as the gateway asks it, so the 504 and its words are
# the driver's own answer on a real socket.
say "4. §6.2 #13 -- the driver's own deadline, on a real socket"
T0=$(date +%s)
DIRECT=$(curl -s -m 60 -w '\n%{http_code}' -X POST "$DRV/v1/generate" -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"slow please"}]}')
T1=$(date +%s)
CODE=$(printf '%s' "$DIRECT" | tail -1)
BODY=$(printf '%s' "$DIRECT" | sed '$d')
echo "  HTTP $CODE after $((T1 - T0))s"
[ "$CODE" = "504" ] && ok "a deadline that fired is 504, not 502" || bad "expected 504, got $CODE: $(printf '%s' "$BODY" | head -c 300)"
DETAIL=$(printf '%s' "$BODY" | jq_ "json.dumps(d.get('detail'))" 2>/dev/null)
case "$DETAIL" in
  *"request failed: \""*|*"request failed: ,"*) bad "the anonymous message is back: $DETAIL" ;;
  *"$DRV_TIMEOUT"*) ok "the message names the deadline that fired (${DRV_TIMEOUT}s)" ;;
  *) bad "the message names no deadline: $DETAIL" ;;
esac
case "$DETAIL" in *requestTimeoutSeconds*) ok "and names the setting that moves it" ;; *) bad "no setting named: $DETAIL" ;; esac

# --- 5 -----------------------------------------------------------------------
say "5. the gateway's own deadline fires, and nothing is recomputed"
# `$STALLED` is tier 1 of a slot whose tier 2 is the backup, so there IS
# somewhere to cascade to and "never asked" is a real answer. It was not
# until the sabotage pass: the backup used to serve a different model,
# `$STALLED` had one backend, and this check passed with the defect in.
BEFORE=$(curl -s -m 5 "http://127.0.0.1:$AGENT_PORT/control/backup-calls" | jq_ "len(d['calls'])")
T0=$(date +%s)
STALL=$(curl -s -m 60 -w '\n%{http_code}' -X POST "$GW/v1/chat/completions" -H 'content-type: application/json' \
  -d "{\"model\":\"$STALLED\",\"messages\":[{\"role\":\"user\",\"content\":\"slow please\"}]}")
T1=$(date +%s)
CODE=$(printf '%s' "$STALL" | tail -1)
BODY=$(printf '%s' "$STALL" | sed '$d')
ELAPSED=$((T1 - T0))
echo "  HTTP $CODE after ${ELAPSED}s"
[ "$CODE" = "504" ] && ok "the gateway answers 504" || bad "expected 504, got $CODE: $(printf '%s' "$BODY" | head -c 300)"
MSG=$(printf '%s' "$BODY" | jq_ "d.get('error',{}).get('message','')" 2>/dev/null)
case "$MSG" in
  *"Every backend serving"*) bad "still reported as a total backend failure: $MSG" ;;
  *requestTimeoutSeconds*) ok "the message names the gateway's own setting" ;;
  *) bad "the message names no setting: $MSG" ;;
esac
# **The heart of the finding.** One deadline, one wait -- not two, not
# three. Before this slice a stalled backend cost 9 s here and then 9 s
# on the next replica, and the caller was told everything had failed.
[ "$ELAPSED" -lt $((GW_TIMEOUT * 2)) ] \
  && ok "one deadline was waited out, not a cascade of them (${ELAPSED}s < $((GW_TIMEOUT * 2))s)" \
  || bad "the request waited out more than one deadline: ${ELAPSED}s"
AFTER=$(curl -s -m 5 "http://127.0.0.1:$AGENT_PORT/control/backup-calls" | jq_ "len(d['calls'])")
[ "$AFTER" = "$BEFORE" ] && ok "the second replica was never asked to recompute ($BEFORE calls before and after)" \
  || bad "the prompt was recomputed on the second replica: $BEFORE -> $AFTER"

# --- 6 -----------------------------------------------------------------------
say "6. control: a DEAD backend still cascades, to the SAME backup"
# The mirror image of check 5, over the same slot shape and the same
# second backend: `$CASCADE` is tier 1 (a driver whose port nothing
# listens on) and the backup is tier 2. If this slice had broken
# failover — the plausible over-correction, refusing to cascade any
# `TimeoutException` including a connect timeout — the backup would go
# unasked here exactly as it does in check 5, and the two checks
# together are what tell the fix from the over-correction.
BEFORE=$(curl -s -m 5 "http://127.0.0.1:$AGENT_PORT/control/backup-calls" | jq_ "len(d['calls'])")
DEADR=$(curl -s -m 60 -w '\n%{http_code}' -X POST "$GW/v1/chat/completions" -H 'content-type: application/json' \
  -d "{\"model\":\"$CASCADE\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}")
CODE=$(printf '%s' "$DEADR" | tail -1)
BODY=$(printf '%s' "$DEADR" | sed '$d')
CONTENT=$(printf '%s' "$BODY" | jq_ "(d.get('choices') or [{}])[0].get('message',{}).get('content')" 2>/dev/null)
AFTER=$(curl -s -m 5 "http://127.0.0.1:$AGENT_PORT/control/backup-calls" | jq_ "len(d['calls'])")
echo "  HTTP $CODE, backup calls $BEFORE -> $AFTER"
[ "$CODE" = "200" ] && [ "$CONTENT" = "backup reply" ] \
  && ok "a refused connection cascaded and the backup served the request" \
  || bad "the dead backend did not cascade: HTTP $CODE, $(printf '%s' "$BODY" | head -c 200)"
[ "$AFTER" -gt "$BEFORE" ] && ok "and the backup really was the one asked" \
  || bad "the backup was never reached: $BEFORE -> $AFTER"

# --- 7 -----------------------------------------------------------------------
say "7. control: an over-long prompt still hard-fails as 400"
OVER=$(curl -s -m 60 -w '\n%{http_code}' -X POST "$DRV/v1/generate" -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"OVERLONG"}]}')
CODE=$(printf '%s' "$OVER" | tail -1)
[ "$CODE" = "400" ] && ok "the backend's own refusal is still a 400 that does not cascade" \
  || bad "expected 400 for an over-long prompt, got $CODE"

# --- 8 -----------------------------------------------------------------------
say "8. §6.2 #16 -- the client is killed, and the ENGINE's socket closes"
curl -s -m 5 "http://127.0.0.1:$AGENT_PORT/control/reset-engine-calls" >/dev/null
curl -s -m 60 -X POST "$GW/v1/chat/completions" -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"slow please\"}]}" > killed.json 2>&1 &
C_PID=$!
sleep 2
kill -9 "$C_PID" 2>/dev/null
wait "$C_PID" 2>/dev/null
# Three hops have to carry the cancellation: curl -> gateway ->
# driver -> engine. The stub notices within a quarter second of the FIN.
for _ in $(seq 1 6); do
  CALLS=$(curl -s -m 5 "http://127.0.0.1:$AGENT_PORT/control/engine-calls" | jq_ "json.dumps(d['calls'])")
  case "$CALLS" in *cut*) break ;; esac
  sleep 1
done
echo "  engine calls: $CALLS"
# **WHEN it was cut is the whole assertion.** A socket also closes when
# a deadline fires, so a bare "cut" is satisfied by the gateway's 9 s or
# the driver's 12 s doing the work — which is how this check passed with
# the fix removed, on the sabotage pass. Requiring it inside 5 s leaves
# no deadline that could have produced it.
check_cut_before() {
  python - "$1" "$2" "$3" <<'PY'
import json, re, sys
calls = json.loads(sys.argv[1])
limit = float(sys.argv[2])
cuts = [float(m.group(1)) for c in calls if (m := re.match(r"cut@([\d.]+)", str(c)))]
if not cuts:
    print(f"    no cut at all: {calls}")
    sys.exit(1)
if min(cuts) >= limit:
    print(f"    cut at {min(cuts):.1f}s -- that is a DEADLINE firing, not a cancellation")
    sys.exit(1)
print(f"    cut at {min(cuts):.1f}s, well inside the {sys.argv[3]}")
PY
}
check_cut_before "$CALLS" 5 "9s gateway and 12s driver deadlines" \
  && ok "the engine's socket closed before it finished: the generation was cancelled, three hops up" \
  || bad "the engine was not cancelled for a client that had gone: $CALLS"

# --- 9 -----------------------------------------------------------------------
say "9. and one hop down: the driver alone, killed the same way"
curl -s -m 5 "http://127.0.0.1:$AGENT_PORT/control/reset-engine-calls" >/dev/null
curl -s -m 60 -X POST "$DRV/v1/generate" -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"slow please"}]}' > killed2.json 2>&1 &
C_PID=$!
sleep 2
kill -9 "$C_PID" 2>/dev/null
wait "$C_PID" 2>/dev/null
for _ in $(seq 1 6); do
  CALLS=$(curl -s -m 5 "http://127.0.0.1:$AGENT_PORT/control/engine-calls" | jq_ "json.dumps(d['calls'])")
  case "$CALLS" in *cut*) break ;; esac
  sleep 1
done
echo "  engine calls: $CALLS"
check_cut_before "$CALLS" 5 "12s driver deadline" \
  && ok "the driver cancels its engine call too" \
  || bad "the driver kept the engine running: $CALLS"

# --- 10 ----------------------------------------------------------------------
say "10. the knob is DURABLE: a real agent, a real restart"
# A companion driver's config file is written by the agent's boot
# reconcile, and the operator's own edits arrive in the same file from
# the driver's `PATCH /v1/config`. The reconcile used to render the
# three fields it manages and write the result over everything else, so
# the setting this whole slice is about did not survive a restart.
mkdir -p agentdir
AGENT_DIR_NATIVE=$(win_path "$WORK/agentdir")
cat > agentdir/agent.yaml <<YAML
firstRunComplete: true
components: []
runtimes:
  - name: r25-runtime
    engine: llama_cpp
    modelPath: /models/r25.gguf
    autoDriver: false
YAML
start_agent() {
  (exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$AGENT_DIR_NATIVE/agent.yaml" \
    EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 \
    EUGENE_PLEXUS_AGENT_BIND_PORT="$REALAGENT_PORT" \
    "$AGENT_PY" -m eugene_plexus_agent --unattended >> agent.log 2>&1) &
  A_PID=$!
  for _ in $(seq 1 60); do curl -sf -m 2 "http://127.0.0.1:$REALAGENT_PORT/healthz" >/dev/null 2>&1 && return 0; sleep 1; done
  return 1
}
# `autoDriver: false` above so the first boot declares nothing; flip it
# on and restart, which is the path an operator's install really takes.
sed -i 's/autoDriver: false/autoDriver: true/' agentdir/agent.yaml
if start_agent; then
  for _ in $(seq 1 30); do [ -f agentdir/drivers/r25-runtime-driver.yaml ] && break; sleep 1; done
  if [ -f agentdir/drivers/r25-runtime-driver.yaml ]; then
    ok "the boot reconcile wrote the companion's config"
    kill "$A_PID" 2>/dev/null; sleep 3; kill_port "$REALAGENT_PORT"
    printf 'requestTimeoutSeconds: 900\n' >> agentdir/drivers/r25-runtime-driver.yaml
    if start_agent; then
      sleep 3
      SURVIVED=$(grep -c 'requestTimeoutSeconds: 900' agentdir/drivers/r25-runtime-driver.yaml || true)
      MANAGED=$(grep -c 'runtimeName: r25-runtime' agentdir/drivers/r25-runtime-driver.yaml || true)
      [ "$SURVIVED" = "1" ] && ok "the operator's timeout survived the agent restart" \
        || { bad "the boot reconcile discarded it"; cat agentdir/drivers/r25-runtime-driver.yaml; }
      [ "$MANAGED" = "1" ] && ok "and the three fields the agent manages are still right" \
        || bad "the agent stopped managing its own fields"
    else
      bad "the agent did not come back after the restart"; tail -20 agent.log
    fi
  else
    bad "no companion config was written"; tail -30 agent.log
  fi
else
  bad "the agent never came up"; tail -30 agent.log
fi
kill "$A_PID" 2>/dev/null; A_PID=""

# --- 11 ----------------------------------------------------------------------
say "11. teardown"
teardown
G_PID=""; D_PID=""; S_PID=""
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ] && ok "no owned port still listening" || bad "still listening:$STILL"

say "result"
if [ "$FAILURES" -eq 0 ]; then
  printf '  ALL CHECKS PASSED\n'
else
  printf '  %d FAILURE(S)\n' "$FAILURES"
fi
exit "$FAILURES"
