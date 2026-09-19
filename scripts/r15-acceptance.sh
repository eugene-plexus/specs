#!/usr/bin/env bash
# R1.5 + R1.6 -- the first hour survives a hostile box, and one model on
# two machines is two runtimes. Live.
#
# Roadmap: docs/design/release-roadmap.md §2.5 and §2.6. Findings: review
# §6.1 #5 (`/v1/engines` blocks the event loop), §6.1 #6 (`agent.yaml` is
# rewritten in place and loaded unguarded), §6.1 #7 (a taken port, and no
# issue kind for a component that is down), §6.3 #35 (the wizard's banned
# vocabulary), §6.1 #8 (runtimes merged by bare name across nodes).
#
# **What only a live run can prove.**
#
# The unit gates drive each fix where they put it. What they cannot show
# is the consequence a person meets in the first hour:
#
#   * a REAL `nvidia-smi` that takes seconds to answer, on the loop that
#     also serves the browser its own UI -- the unit check blocks a
#     patched function, this one blocks a subprocess;
#   * a REAL default topology seeded onto a box where 8080 is already
#     taken, spawning real children, and coming up working anyway;
#   * a REAL crash-loop, so the `lastError` the Needs-attention card
#     renders is the sentence the supervisor actually produced rather
#     than a fixture of it;
#   * a REAL agent restarted onto a half-written config file;
#   * and for R1.6, a REAL gateway process over two agents that each
#     declare `qwen` and `qwen-driver` -- the shape the UI produces for
#     one model on two machines and the one the merge could not hold.
#     **The M6 replica run passed because it was one node**; this is the
#     first time two have been in front of a live gateway with one name
#     between them.
#
# The checks:
#   0. isolated from any install on this machine, and from its ports
#   1. **#7**: 8080 is held before first boot. The install seeds around
#      it and the gateway comes up `running` on another port
#   2. **#7**: the library and the control root keep their documented
#      ports, because the walk is a fallback and not a preference
#   3. **#7**: a component declared onto a held port crash-loops, and
#      `Component.lastError` names the port AND the holding process --
#      the body `componentDownIssues` renders
#   4. **#5**: a 2-second `nvidia-smi` on PATH. `/v1/engines` is in
#      flight and `/healthz` answers anyway
#   5. **#5**: the host is resolved ONCE per request, measured by
#      counting the stub's own invocations
#   6. **#6**: the agent is stopped, `agent.yaml` is cut mid-list, and
#      the agent comes back UP: `/healthz` degraded with the reason,
#      `/v1/config` reachable, and a copy of the broken file beside it
#   7. **#6**: that install held a passphrase, so first-run setup is
#      refused rather than offered -- and the refusal names restoring
#   8. **#7**: the already-set-up 409 does not send a person into a
#      YAML file
#   9. **#35**: the built UI carries no banned term in the wizard's
#      error path -- read off the export, not off the source
#  10. **#8**: a real gateway over two agents, both declaring `qwen`.
#      TWO runtimes, one per node, each with its own node recorded
#  11. **#8**: node B's replica is `stopped` and node A's is `ready`.
#      Only node A is routable -- before, B `ready` masked A `stopped`
#  12. **#8**: a completion is served, and the attempt is counted
#      against the replica on the node that answered
#  13. **#8**: an idle unload goes to the agent that owns the runtime,
#      and the OTHER node's replica is untouched
#  14. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped, the agent binds +100, the throwaway install lives under
# $TMPDIR, teardown is by pid. Never `pkill -f eugene_plexus_`: this box
# is a worker node in a real install.
#
# **It does use 8080/8082/8083**, because the seeded topology's ports are
# what check 1 is about. It refuses to start if anything is on them.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
AGENT_PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
GW_PY="${EP_GW_PY:-$EP_ROOT/gateway/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-r15}"

AGENT_PORT="${EP_AGENT_PORT:-8179}"
SEEDED_PORTS="8080 8082 8083"
BLOCKED_PORT=8080
BUSY_PORT="${EP_BUSY_PORT:-8188}"
GW_PORT="${EP_GW_PORT:-8180}"
STUB_A_PORT="${EP_STUB_A_PORT:-8185}"
STUB_B_PORT="${EP_STUB_B_PORT:-8186}"
DRV_A_PORT="${EP_DRV_A_PORT:-8187}"
DRV_B_PORT="${EP_DRV_B_PORT:-8189}"

AGENT="http://127.0.0.1:$AGENT_PORT"
GW="http://127.0.0.1:$GW_PORT"
CONTROL_PORT="${EP_STUB_CONTROL_PORT:-8190}"
OWNED_PORTS="$AGENT_PORT $BLOCKED_PORT $BUSY_PORT $GW_PORT $STUB_A_PORT $STUB_B_PORT $DRV_A_PORT $DRV_B_PORT $CONTROL_PORT 8082 8083"
PASS="r15-acceptance-passphrase"
MODEL="qwen3-1.7b"
RUNTIME="qwen"
DRIVER="qwen-driver"
REFRESH=3

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

A_PID=""; G_PID=""; S_PID=""; HOLD_PID=""; BUSY_PID=""
teardown() {
  for pid in $A_PID $G_PID $S_PID $HOLD_PID $BUSY_PID; do kill "$pid" 2>/dev/null; done
  sleep 2
  for p in $OWNED_PORTS; do kill_port "$p"; done
}
trap teardown EXIT

# --- 0 ----------------------------------------------------------------------
say "0. isolate this run"
[ -f "$AGENT_PY" ] || { bad "no agent python at $AGENT_PY"; exit 1; }
[ -f "$GW_PY" ] || { bad "no gateway python at $GW_PY"; exit 1; }
# A loop, not a list: a throwaway agent that inherits the live worker's
# config file adopts its identity and re-announces its address to the
# real control root.
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy NO_PROXY no_proxy
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] || { bad "an EUGENE_PLEXUS_* variable leaked"; exit 1; }
for p in $OWNED_PORTS; do
  [ -z "$(listening_pids "$p")" ] || { bad "port $p is already in use; refusing to run"; exit 1; }
done
rm -rf "$WORK"; mkdir -p "$WORK/install" "$WORK/stub" "$WORK/engines"
cd "$WORK" || exit 1
ok "ambient EUGENE_PLEXUS_* cleared; ports $OWNED_PORTS free; work dir $WORK"

# --- the stubs --------------------------------------------------------------
# A slow `nvidia-smi`, so check 4 blocks on a real subprocess rather than
# on a patched function -- and one that COUNTS its invocations, which is
# what makes check 5 a measurement instead of an assertion about source.
cat > "$WORK/stub/nvidia-smi.cmd" <<'CMD'
@echo off
echo %TIME% >> "%EP_R15_COUNT%"
ping -n 3 127.0.0.1 > nul
echo ^| NVIDIA-SMI 610.47   KMD Version: 610.47      CUDA UMD Version: 13.3 ^|
echo NVIDIA GeForce RTX 5090
CMD
STUB_WIN=$(win_path "$WORK/stub")
COUNT_FILE="$WORK/nvidia-smi.calls"
COUNT_WIN=$(win_path "$COUNT_FILE")

# Something that holds a port and answers nothing, for checks 1 and 3.
cat > "$WORK/hold.py" <<'PY'
import socket, sys, time
s = socket.socket()
s.bind(("127.0.0.1", int(sys.argv[1])))
s.listen(8)
while True:
    time.sleep(3600)
PY

say "hold 8080 before anything is seeded"
python "$WORK/hold.py" "$BLOCKED_PORT" & HOLD_PID=$!
python "$WORK/hold.py" "$BUSY_PORT" & BUSY_PID=$!
sleep 2
[ -n "$(listening_pids "$BLOCKED_PORT")" ] || { bad "could not hold $BLOCKED_PORT"; exit 1; }
ok "$BLOCKED_PORT and $BUSY_PORT are held by something that is not us"

# --- start the agent on a first boot ---------------------------------------
INSTALL_WIN=$(win_path "$WORK/install")
export EUGENE_PLEXUS_AGENT_CONFIG_FILE="$INSTALL_WIN\\agent.yaml"
export EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT"
export EUGENE_PLEXUS_AGENT_ENGINE_ROOT=$(win_path "$WORK/engines")
export EP_R15_COUNT="$COUNT_WIN"
export PATH="$WORK/stub:$PATH"

say "start a first-boot agent (it seeds the default topology)"
"$AGENT_PY" -m eugene_plexus_agent --unattended > "$WORK/agent.log" 2>&1 & A_PID=$!
for _ in $(seq 40); do
  curl -s -m 2 "$AGENT/healthz" > /dev/null && break
  sleep 1
done
curl -s -m 5 "$AGENT/healthz" > /dev/null || { bad "the agent never answered"; tail -30 "$WORK/agent.log"; exit 1; }
TOKEN=$(curl -s -m 20 -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' \
  -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOKEN" ] || { bad "could not set a passphrase"; tail -30 "$WORK/agent.log"; exit 1; }
AUTH=(-H "Authorization: Bearer $TOKEN")
ok "agent up on $AGENT_PORT with a passphrase"

comp() {
  curl -s -m 10 "${AUTH[@]}" "$AGENT/v1/components" \
    | jq_ "next((c.get('$2') for c in d['components'] if c['name']=='$1'), 'ABSENT')"
}
port_of() { curl -s -m 10 "${AUTH[@]}" "$AGENT/v1/components" \
    | jq_ "next((str(c['url']).rstrip('/').rsplit(':',1)[-1] for c in d['components'] if c['name']=='$1'), 'ABSENT')"; }

# --- 1 ----------------------------------------------------------------------
say "1. #7 -- the gateway is not seeded onto the port something else holds"
GW_SEEDED=$(port_of gateway)
if [ "$GW_SEEDED" = "$BLOCKED_PORT" ]; then
  bad "the gateway was declared on $BLOCKED_PORT, which is held"
elif [ "$GW_SEEDED" = "ABSENT" ]; then
  bad "no gateway was declared at all"
else
  ok "the gateway was declared on $GW_SEEDED, not on the held $BLOCKED_PORT"
fi
grep -q "port $BLOCKED_PORT is already in use" "$WORK/agent.log" \
  && ok "the log says which port was taken and what it did about it" \
  || bad "nothing in the log explains the move"

for _ in $(seq 45); do
  [ "$(comp gateway status)" = "running" ] && break
  sleep 1
done
GW_STATUS=$(comp gateway status)
[ "$GW_STATUS" = "running" ] \
  && ok "the gateway is running -- the install is not silently useless" \
  || bad "the gateway is '$GW_STATUS' (before this slice: crashed, with an empty card)"

# --- 2 ----------------------------------------------------------------------
say "2. #7 -- the walk is a fallback, not a preference"
[ "$(port_of library)" = "8082" ] && ok "library kept 8082" || bad "library moved to $(port_of library)"
[ "$(port_of control)" = "8083" ] && ok "control kept 8083" || bad "control moved to $(port_of control)"

# --- 3 ----------------------------------------------------------------------
say "3. #7 -- a component on a held port says WHY, in Component.lastError"
# The body is written by Python, not interpolated into a shell string: a
# Windows config path is full of backslashes and JSON escapes them, which
# cost this check one execution -- the declaration came back
# `Invalid \escape` and the assertions below then reported on a component
# that had never been created.
python - "$WORK/declare-body.json" "$INSTALL_WIN" "$BUSY_PORT" <<'PY'
import json
import sys

path, install, port = sys.argv[1:4]
with open(path, "w", encoding="utf-8") as f:
    json.dump(
        {
            "name": "doomed",
            "kind": "library",
            "url": f"http://127.0.0.1:{port}",
            "spawn": {"configFile": install + "\\doomed.yaml"},
        },
        f,
    )
PY
DECL=$(curl -s -m 10 "${AUTH[@]}" -X POST "$AGENT/v1/components" \
  -H 'content-type: application/json' --data-binary "@$WORK/declare-body.json")
# A declaration the agent refuses is not a crash-loop, and the checks
# below would then be reporting on a component that never existed.
case "$DECL" in
  *'"name"'*) ok "the component was declared" ;;
  *) bad "the declaration itself was refused: $DECL" ;;
esac
LAST=""
for _ in $(seq 40); do
  LAST=$(comp doomed lastError)
  case "$LAST" in *"already held by"*) break ;; esac
  sleep 1
done
case "$LAST" in
  *"already held by"*)
    ok "lastError: $LAST"
    case "$LAST" in *"pid "*) ok "and it names the holding process" ;; *) bad "no holder named" ;; esac
    ;;
  *) bad "lastError after 40s was: ${LAST:-<empty>}" ;;
esac
DOOMED_STATUS=$(comp doomed status)
case "$DOOMED_STATUS" in
  crashed|starting|exited) ok "status '$DOOMED_STATUS' -- the state the card reports on" ;;
  *) bad "status '$DOOMED_STATUS'" ;;
esac
curl -s -m 10 "${AUTH[@]}" -X DELETE "$AGENT/v1/components/doomed" > /dev/null

# --- 4 ----------------------------------------------------------------------
say "4. #5 -- /v1/engines is in flight and /healthz answers anyway"
: > "$COUNT_FILE"
curl -s -m 60 "${AUTH[@]}" "$AGENT/v1/engines" > "$WORK/engines.json" &
ENGINES_JOB=$!
sleep 0.4
HSTART=$(python -c 'import time; print(time.perf_counter())')
HCODE=$(curl -s -m 20 -o /dev/null -w '%{http_code}' "$AGENT/healthz")
HWAIT=$(python -c "import time; print(round(time.perf_counter()-$HSTART, 3))")
wait $ENGINES_JOB
[ "$HCODE" = "200" ] || bad "/healthz answered $HCODE"
UNDER=$(python -c "print(1 if $HWAIT < 1.0 else 0)")
[ "$UNDER" = "1" ] \
  && ok "/healthz answered in ${HWAIT}s while /v1/engines was resolving a 2s probe" \
  || bad "/healthz waited ${HWAIT}s behind /v1/engines"
grep -q '"engines"' "$WORK/engines.json" && ok "and /v1/engines answered" || bad "/v1/engines did not answer"

# --- 5 ----------------------------------------------------------------------
say "5. #5 -- the host is resolved once per request, counted"
CALLS=$(grep -c . "$COUNT_FILE" 2>/dev/null || echo 0)
# Two invocations per `detect_host()` at most on this box: the banner
# read, then the name query only if the banner did not parse. The stub
# parses, so one resolution is one call.
if [ "$CALLS" -le 2 ]; then
  ok "nvidia-smi ran $CALLS time(s) for one /v1/engines (three resolutions would be 3+)"
else
  bad "nvidia-smi ran $CALLS times for one /v1/engines"
fi

# --- 6 ----------------------------------------------------------------------
say "6. #6 -- a half-written agent.yaml comes up degraded, not dead"
kill "$A_PID" 2>/dev/null; wait "$A_PID" 2>/dev/null; A_PID=""
sleep 2
for p in $SEEDED_PORTS; do [ "$p" = "$BLOCKED_PORT" ] || kill_port "$p"; done
kill_port "$GW_SEEDED"
CONF="$WORK/install/agent.yaml"
cp "$CONF" "$WORK/agent.yaml.whole"
# Cut inside the components list, which is what a write interrupted
# part-way through leaves -- `yaml.safe_dump` sorts keys, so `auth` is
# written first and survives while the tail does not.
python - "$CONF" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8")
marker = "components:"
cut = text.index(marker) + len(marker) + 40
p.write_text(text[:cut], encoding="utf-8")
PY
grep -q "masterSalt" "$CONF" && ok "the cut file still carries the auth block, as a real cut does" \
  || note "the cut landed before the auth block; check 7 is then about a fresh install"

"$AGENT_PY" -m eugene_plexus_agent --unattended > "$WORK/agent2.log" 2>&1 & A_PID=$!
for _ in $(seq 40); do curl -s -m 2 "$AGENT/healthz" > /dev/null && break; sleep 1; done
HEALTH=$(curl -s -m 10 "$AGENT/healthz")
if [ -z "$HEALTH" ]; then
  bad "the agent did not come up at all -- the defect, verbatim"
else
  STATUS=$(printf '%s' "$HEALTH" | jq_ "d.get('status')")
  REASON=$(printf '%s' "$HEALTH" | jq_ "(d.get('details') or {}).get('configError','')")
  [ "$STATUS" = "degraded" ] && ok "it is up and reports degraded" || bad "status was '$STATUS'"
  [ -n "$REASON" ] && ok "and says why: $REASON" || bad "no reason on the wire"
  CODE=$(curl -s -m 10 -o /dev/null -w '%{http_code}' "$AGENT/v1/config")
  case "$CODE" in
    401|403) ok "/v1/config is reachable (it asks for a token, which is the point)" ;;
    200) ok "/v1/config answers" ;;
    *) bad "/v1/config answered $CODE, so the UI cannot repair the file" ;;
  esac
  [ -f "$CONF.unreadable" ] && ok "a copy of the broken file is beside it" || bad "nothing was preserved"
fi

# --- 7 ----------------------------------------------------------------------
say "7. #6 -- an install that held a passphrase is not offered the wizard"
BODY=$(curl -s -m 20 -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' \
  -d '{"passphrase":"a-second-passphrase-entirely"}')
CODE=$(curl -s -m 20 -o /dev/null -w '%{http_code}' -X POST "$AGENT/v1/auth/initialize" \
  -H 'content-type: application/json' -d '{"passphrase":"a-third-passphrase"}')
DETAIL=$(printf '%s' "$BODY" | jq_ "(d.get('detail') or {}).get('detail','')")
if [ "$CODE" = "409" ]; then
  ok "409: $DETAIL"
  case "$DETAIL" in
    *[Rr]estore*) ok "and it names restoring the file rather than starting over" ;;
    *) bad "the refusal does not say what to do: $DETAIL" ;;
  esac
else
  bad "first-run setup answered $CODE on an install whose keys are missing"
fi

# --- 8 ----------------------------------------------------------------------
say "8. #7 -- the already-set-up 409 does not send a person into a YAML file"
cp "$WORK/agent.yaml.whole" "$CONF"
rm -f "$CONF.unreadable"
kill "$A_PID" 2>/dev/null; wait "$A_PID" 2>/dev/null; A_PID=""
sleep 2
for p in $SEEDED_PORTS $GW_SEEDED; do [ "$p" = "$BLOCKED_PORT" ] || kill_port "$p"; done
"$AGENT_PY" -m eugene_plexus_agent --unattended > "$WORK/agent3.log" 2>&1 & A_PID=$!
for _ in $(seq 40); do curl -s -m 2 "$AGENT/healthz" > /dev/null && break; sleep 1; done
BODY=$(curl -s -m 20 -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' \
  -d '{"passphrase":"yet-another-passphrase"}')
DETAIL=$(printf '%s' "$BODY" | jq_ "(d.get('detail') or {}).get('detail','')")
case "$DETAIL" in
  *agent.yaml*|*"by hand"*) bad "the 409 still says: $DETAIL" ;;
  "") bad "no refusal at all -- a second passphrase was accepted" ;;
  *) ok "409: $DETAIL" ;;
esac
case "$DETAIL" in *[Ss]ign\ in*) ok "and names signing in as the remedy" ;; *) bad "no remedy named" ;; esac
kill "$A_PID" 2>/dev/null; wait "$A_PID" 2>/dev/null; A_PID=""
sleep 2
for p in $SEEDED_PORTS $GW_SEEDED; do [ "$p" = "$BLOCKED_PORT" ] || kill_port "$p"; done

# --- 9 ----------------------------------------------------------------------
say "9. #35 -- the BUILT UI carries no banned term in the wizard's error path"
# Read off the export, not off the source: S10's finding was a fix that
# was on `main`, tested, merged -- and in no build.
EXPORT="$EP_ROOT/ui/out"
if [ -d "$EXPORT" ]; then
  if grep -rl "trust root would not accept" "$EXPORT" > /dev/null 2>&1; then
    bad "the built UI still carries the old sentence"
  else
    ok "no 'trust root would not accept' anywhere in $EXPORT"
  fi
  if grep -rl "control root did not take the passphrase" "$EXPORT" > /dev/null 2>&1; then
    ok "and the new sentence is in the build"
  else
    bad "the new sentence is not in the build -- it would ship to nobody"
  fi
else
  skip "no UI export at $EXPORT; run 'npm run build' in ui first"
fi

# ===========================================================================
# R1.6 -- one model, two machines, one live gateway
# ===========================================================================
say "10-13. #8 -- a real gateway over two agents that both declare '$RUNTIME'"

cat > "$WORK/two_agents.py" <<'PY'
"""Two agents and two drivers, on four ports, in one process.

Each agent declares a driver called `qwen-driver` fronting a runtime
called `qwen` -- the names the UI really produces, because it names a
runtime after the model and a companion after the runtime. Before R1.6
the gateway merged them and the last read won.

`/control/<node>/<status>` sets one node's runtime status.
`/calls` reports every lifecycle action, with the port it arrived on, so
the run can see WHICH agent was asked.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

A_PORT, B_PORT, DA_PORT, DB_PORT = (int(x) for x in sys.argv[1:5])
MODEL, RUNTIME, DRIVER = sys.argv[5:8]

CONTROL_PORT = int(sys.argv[8])
NODES = {A_PORT: "node-a", B_PORT: "node-b"}
DRIVER_PORT = {A_PORT: DA_PORT, B_PORT: DB_PORT}
STATUS = {"node-a": "ready", "node-b": "ready"}
IDLE = {"node-a": None, "node-b": None}
CALLS: list[list[str]] = []


def runtime_body(node: str) -> dict:
    body = {
        "name": RUNTIME,
        "engine": "llama_cpp",
        "modelPath": "/m/qwen.gguf",
        "modelAlias": MODEL,
        "status": STATUS[node],
        "node": node,
        "url": f"http://127.0.0.1:{DA_PORT if node == 'node-a' else DB_PORT}",
        "startOnDemand": True,
    }
    if IDLE[node] is not None:
        body["idleUnloadSeconds"] = IDLE[node]
    return body


class Agent(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    @property
    def node(self) -> str:
        return NODES[self.server.server_address[1]]

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/calls":
            return self._json({"calls": CALLS})
        if path.startswith("/control/"):
            _, _, rest = path.partition("/control/")
            node, _, value = rest.partition("/")
            if value.isdigit():
                IDLE[node] = int(value)
            elif value == "noidle":
                IDLE[node] = None
            else:
                STATUS[node] = value
            return self._json({"status": STATUS, "idle": IDLE})
        if path == "/healthz":
            return self._json({"status": "ok"})
        if path == "/v1/node":
            return self._json({"enrolled": True, "name": self.node})
        if path == "/v1/components":
            return self._json(
                {
                    "components": [
                        {
                            "name": DRIVER,
                            "kind": "inference-driver",
                            "url": f"http://127.0.0.1:{DRIVER_PORT[self.server.server_address[1]]}",
                            "status": "running",
                        }
                    ]
                }
            )
        if path == "/v1/runtimes":
            return self._json({"runtimes": [runtime_body(self.node)]})
        if path == f"/v1/runtimes/{RUNTIME}":
            return self._json(runtime_body(self.node))
        return self._json({"detail": path}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("content-length") or 0)
        if length:
            self.rfile.read(length)
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[1] == "runtimes" and parts[3] in ("stop", "start"):
            CALLS.append([self.node, parts[3], parts[2]])
            STATUS[self.node] = "stopped" if parts[3] == "stop" else "ready"
            return self._json({"scheduled": True, "delayMs": 0}, 202)
        if path == "/v1/runtimes/admission":
            return self._json({"decision": "admit", "fit": "fits", "reason": "ok", "blockers": []})
        return self._json({"detail": path}, 404)


class Control(BaseHTTPRequestHandler):
    """`GET /v1/nodes` only. The gateway finds its agents through the
    control root, so this is how two of them reach a LIVE gateway
    process rather than an in-process `refresh()`."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/healthz":
            body = {"status": "ok"}
        elif path == "/v1/nodes":
            body = {
                "nodes": [
                    {
                        "name": "node-a",
                        "url": f"http://127.0.0.1:{A_PORT}/",
                        "role": "control",
                        "reachable": True,
                    },
                    {
                        "name": "node-b",
                        "url": f"http://127.0.0.1:{B_PORT}",
                        "role": "agent",
                        "reachable": True,
                    },
                ]
            }
        else:
            body = {"detail": path}
        raw = json.dumps(body).encode()
        self.send_response(200 if path in ("/healthz", "/v1/nodes") else 404)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class Driver(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.split("?")[0] == "/v1/info":
            return self._json(
                {
                    "backend": "openai_compat_http",
                    "version": "0.1.0",
                    "modelId": MODEL,
                    "runtime": RUNTIME,
                    "capabilities": {"streaming": True},
                }
            )
        return self._json({"detail": self.path}, 404)

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        if length:
            self.rfile.read(length)
        port = self.server.server_address[1]
        who = "node-a" if port == DA_PORT else "node-b"
        return self._json(
            {
                "id": "gen-1",
                "model": MODEL,
                "content": f"answered by {who}",
                "finishReason": "stop",
                "usage": {"promptTokens": 3, "completionTokens": 3, "totalTokens": 6},
            }
        )


def serve(handler, port):
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


for handler, port in (
    (Agent, A_PORT),
    (Agent, B_PORT),
    (Driver, DA_PORT),
    (Driver, DB_PORT),
    (Control, CONTROL_PORT),
):
    threading.Thread(target=serve, args=(handler, port), daemon=True).start()

threading.Event().wait()
PY

python "$WORK/two_agents.py" "$STUB_A_PORT" "$STUB_B_PORT" "$DRV_A_PORT" "$DRV_B_PORT" \
  "$MODEL" "$RUNTIME" "$DRIVER" "$CONTROL_PORT" > "$WORK/stubs.log" 2>&1 & S_PID=$!
for _ in $(seq 20); do curl -s -m 2 "http://127.0.0.1:$STUB_A_PORT/healthz" >/dev/null && break; sleep 1; done
curl -s -m 5 "http://127.0.0.1:$STUB_A_PORT/healthz" >/dev/null || { bad "the stub agents never came up"; exit 1; }
curl -s -m 5 "http://127.0.0.1:$CONTROL_PORT/v1/nodes" >/dev/null || { bad "the stub root never came up"; exit 1; }

# A real gateway process, finding both agents the way it really does:
# through the control root's `/v1/nodes`.
cat > "$WORK/gateway.yaml" <<YAML
controlUrl: http://127.0.0.1:$CONTROL_PORT
routingRefreshSeconds: $REFRESH
idleCheckSeconds: 2
metricsEnabled: false
YAML
EUGENE_PLEXUS_GATEWAY_CONFIG_FILE=$(win_path "$WORK/gateway.yaml") \
EUGENE_PLEXUS_GATEWAY_BIND_PORT="$GW_PORT" \
  "$GW_PY" -m eugene_plexus_gateway > "$WORK/gateway.log" 2>&1 & G_PID=$!
for _ in $(seq 40); do curl -s -m 2 "$GW/healthz" >/dev/null && break; sleep 1; done
curl -s -m 5 "$GW/healthz" >/dev/null || { bad "the gateway never answered"; tail -30 "$WORK/gateway.log"; exit 1; }
settle() { sleep $((REFRESH * 2 + 1)); }
settle

routing() { curl -s -m 10 "$GW/v1/admin/routing"; }
nodes_routable() {
  routing | jq_ "sorted(str(b.get('node')) for s in d['slots'] for t in s['tiers'] for b in t['backends'] if b.get('eligible'))"
}
nodes_present() {
  routing | jq_ "sorted(str(b.get('node')) for s in d['slots'] for t in s['tiers'] for b in t['backends'])"
}
runtime_names() {
  routing | jq_ "sorted(str(b.get('runtime')) for s in d['slots'] for t in s['tiers'] for b in t['backends'])"
}

say "10. #8 -- two runtimes under one name, each with its own node"
PRESENT=$(nodes_present)
NAMES=$(runtime_names)
[ "$PRESENT" = "['node-a', 'node-b']" ] \
  && ok "the table holds a backend on each node: $PRESENT" \
  || bad "the table holds $PRESENT"
[ "$NAMES" = "['$RUNTIME', '$RUNTIME']" ] \
  && ok "both are the runtime called '$RUNTIME' -- one name, two engines" \
  || bad "runtime names were $NAMES"

say "11. #8 -- a ready replica on one node does not make a stopped one routable"
curl -s -m 5 "http://127.0.0.1:$STUB_A_PORT/control/node-a/stopped" > /dev/null
settle
ROUTABLE=$(nodes_routable)
[ "$ROUTABLE" = "['node-b']" ] \
  && ok "only node-b is routable: $ROUTABLE" \
  || bad "routable nodes were $ROUTABLE (before this slice node-b ready masked node-a stopped)"
curl -s -m 5 "http://127.0.0.1:$STUB_A_PORT/control/node-a/ready" > /dev/null
settle
[ "$(nodes_routable)" = "['node-a', 'node-b']" ] && ok "both routable again" || bad "did not recover"

say "12. #8 -- a completion is served and attributed to the node that answered"
BODY=$(curl -s -m 30 -X POST "$GW/v1/chat/completions" -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":8}")
ANSWER=$(printf '%s' "$BODY" | jq_ "d['choices'][0]['message']['content']")
ENVELOPE_RUNTIME=$(printf '%s' "$BODY" | jq_ "(d.get('x_eugene_plexus') or {}).get('runtime','')")
case "$ANSWER" in
  *"answered by node-"*) ok "served: $ANSWER" ;;
  *) bad "no completion came back: $BODY" ;;
esac
[ "$ENVELOPE_RUNTIME" = "$RUNTIME" ] \
  && ok "the envelope names the runtime '$ENVELOPE_RUNTIME'" \
  || bad "the envelope's runtime was '$ENVELOPE_RUNTIME'"

say "13. #8 -- an idle unload goes to the agent that owns the runtime"
# Only node-b declares a timeout, and the gateway's own idle clock is
# what decides -- so this is the check the merge broke: the surviving
# entry carried node-a, and the stop went to node-a's agent.
curl -s -m 5 "http://127.0.0.1:$STUB_B_PORT/control/node-b/1" > /dev/null
settle
sleep 4
STOPPED=$(curl -s -m 10 "$GW/v1/admin/routing" > /dev/null; curl -s -m 10 "http://127.0.0.1:$STUB_A_PORT/calls" \
  | jq_ "[c for c in d['calls'] if c[1]=='stop']")
for _ in $(seq 20); do
  STOPPED=$(curl -s -m 10 "http://127.0.0.1:$STUB_A_PORT/calls" | jq_ "[c for c in d['calls'] if c[1]=='stop']")
  [ "$STOPPED" != "[]" ] && break
  sleep 2
done
case "$STOPPED" in
  "[['node-b', 'stop', '$RUNTIME']]")
    ok "the stop went to node-b and named '$RUNTIME': $STOPPED" ;;
  *"node-a"*)
    bad "the stop went to the WRONG agent: $STOPPED" ;;
  "[]")
    bad "no idle unload happened within 40s" ;;
  *)
    bad "unexpected lifecycle calls: $STOPPED" ;;
esac
ROUTABLE=$(nodes_routable)
[ "$ROUTABLE" = "['node-a']" ] \
  && ok "node-a is still serving -- the other machine's replica was untouched" \
  || bad "routable nodes after the unload: $ROUTABLE"

say "14. teardown"
teardown
A_PID=""; G_PID=""; S_PID=""; HOLD_PID=""; BUSY_PID=""
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ] && ok "no owned port is still listening" || bad "still listening:$STILL"

printf '\n== summary\n'
printf '  failures: %d   skipped: %d\n' "$FAILURES" "$SKIPPED"
[ "$FAILURES" -eq 0 ] || exit 1
