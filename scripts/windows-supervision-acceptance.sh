#!/usr/bin/env bash
#
# Install-paths §9 step 2 acceptance: stopping a child on Windows.
#
# **The check this script exists for is a log line from INSIDE the
# child.** "It restarted" was always true — `TerminateProcess` restarts
# things perfectly. What was never true on Windows is that the child got
# to run its shutdown: uvicorn's "Application shutdown complete." is
# emitted by the ASGI lifespan, which is where the gateway closes its
# metrics database and the control root closes its log. So nothing here
# checks that a component came back; it checks what the component said
# on its way out, and it checks that from the tail of the log written
# after the restart was asked for, never from the whole file.
#
# The second subject is an accounting defect nobody had written down: a
# console-stopped CPython child exits 3, the supervision loop counted any
# non-zero exit as a crash, and so **every operator restart on Windows
# bought itself a back-off sleep** — and enough in a row tripped the
# crash threshold and dropped the component into safe mode for doing
# exactly what it was asked.
#
# Checks:
#   1. a restart asks with a console event, not TerminateProcess
#   2. the child runs its ASGI lifespan shutdown -- it said so itself
#   3. the restart is not counted as a crash, three times running
#   4. the component is healthy again afterwards, not in safe mode
#   5. a port collision names the port AND who is holding it
#   6. a collision that has cleared says so differently
#
# Design: docs/design/install-paths-and-distribution.md §9 step 2, §11.1
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-winsup-live}"
AGENT=http://127.0.0.1:8079
GW=http://127.0.0.1:8080
LIB_PORT=8082
PASS="winsup-live-$$"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }

free_port() {
  for pid in $(netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $NF}' | sort -u); do
    taskkill //PID "$pid" //T //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
  done
}

# Everything below reads the agent log from a mark, never from the top.
# An earlier restart in the same run writes the same lines, so a whole-
# file grep would report the previous restart's success as this one's.
mark() { wc -l < "$WORK/agent.log" | tr -d ' '; }
since() { tail -n "+$(( $1 + 1 ))" "$WORK/agent.log"; }

say "preflight"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) ok "running on Windows, which is the subject" ;;
  *) echo "  SKIP: this script tests Windows-specific supervision"; exit 0 ;;
esac
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
ok "agent python present"

for p in 8079 8080 8082 8083; do free_port "$p"; done
rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1

STUB_PID=""
cleanup() {
  [ -n "$STUB_PID" ] && kill -9 "$STUB_PID" 2>/dev/null
  [ -n "${AGENT_PID:-}" ] && taskkill //PID "$AGENT_PID" //T //F >/dev/null 2>&1
  pkill -f eugene_plexus_ 2>/dev/null
  for p in 8079 8080 8082 8083; do free_port "$p"; done
}
trap cleanup EXIT

say "start the agent; it declares control, gateway and library itself"
# Spawned into its OWN process group, so check 7 can aim a console event
# at it. The launcher prints the pid and exits; the agent outlives it.
"$PY" -c "
import subprocess, sys
out = open(sys.argv[2], 'w')
p = subprocess.Popen([sys.argv[1], '-m', 'eugene_plexus_agent'],
                     stdout=out, stderr=subprocess.STDOUT,
                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
print(p.pid)
" "$PY" "$WORK/agent.log" > "$WORK/agent.pid"
AGENT_PID=$(tr -d '\r\n' < "$WORK/agent.pid")
wait_healthy "$AGENT" 60 || { bad "agent never answered"; tail -20 "$WORK/agent.log"; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d['sessionToken']")
[ -n "$TOK" ] || { bad "no operator token"; exit 1; }
wait_healthy "$GW" 90 || { bad "gateway never came up"; exit 1; }
ok "agent and gateway up"

# --- 1-4. three restarts in a row -----------------------------------------------
say "1-4. restarting the gateway three times: graceful, and not a crash"
for attempt in 1 2 3; do
  M=$(mark)
  curl -s -o /dev/null -X POST "$AGENT/v1/components/gateway/restart" \
    -H "Authorization: Bearer $TOK" -H 'content-type: application/json' -d '{}'
  # Wait for the RESPAWN line rather than sleeping: the thing being
  # timed is a process going away and coming back, and a fixed sleep is
  # either a flake or a waste.
  for _ in $(seq 1 60); do
    since "$M" | grep -q "spawning gateway" && break
    sleep 0.5
  done
  TAIL=$(since "$M")

  if [ "$attempt" = "1" ]; then
    printf '%s' "$TAIL" | grep -q "sent CTRL_BREAK_EVENT" \
      && ok "asked with CTRL_BREAK_EVENT, not TerminateProcess" \
      || bad "no console event in the log: $(printf '%s' "$TAIL" | grep -i 'restart requested' | head -1)"

    # THE CHECK THIS SCRIPT EXISTS FOR. uvicorn prints this from inside
    # the ASGI lifespan shutdown; TerminateProcess never gets there.
    #
    # The `[gateway]` prefix is load-bearing, not decoration: it is the
    # agent's own stamp on a piped CHILD line, and an unprefixed match
    # would be the AGENT's own shutdown. Check 7 below was first written
    # with the bare string and passed against this very line — the
    # parent's property asserted from the child's log.
    printf '%s' "$TAIL" | grep -q "\[gateway\].*Application shutdown complete" \
      && ok "*** the gateway ran its ASGI lifespan shutdown -- it said so itself ***" \
      || bad "no lifespan shutdown from the child; it was killed, not asked"
    printf '%s' "$TAIL" | grep -q "\[gateway\].*Waiting for application shutdown" \
      && ok "...and it waited for in-flight work first" || bad "no graceful wait"
  fi

  printf '%s' "$TAIL" | grep -q "exited on request" \
    && ok "restart $attempt: recorded as a request, not a crash" \
    || bad "restart $attempt: not recorded as requested -- $(printf '%s' "$TAIL" | grep -i 'exited' | head -1)"
  printf '%s' "$TAIL" | grep -q "consecutive crashes" \
    && bad "restart $attempt: the loop counted a crash" \
    || ok "restart $attempt: no crash counted"
done

wait_healthy "$GW" 90 && ok "the gateway is healthy after three restarts" || bad "gateway did not come back"
SAFE=$(curl -s "$AGENT/v1/components/gateway" -H "Authorization: Bearer $TOK" | jq_ "d.get('status','?')")
[ "$SAFE" = "running" ] && ok "...and reports 'running', not safe mode ($SAFE)" || bad "gateway status is $SAFE"

# --- 5. a port collision names its holder ---------------------------------------
say "5. a component whose port is taken says who has it"
# Stop the library, take its port, then let the agent try to respawn it.
curl -s -o /dev/null -X DELETE "$AGENT/v1/components/library" -H "Authorization: Bearer $TOK"
sleep 2
free_port "$LIB_PORT"
"$PY" -c "
import http.server, sys
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(204); self.end_headers()
    def log_message(self, *a): pass
http.server.HTTPServer(('127.0.0.1', $LIB_PORT), H).serve_forever()
" > /dev/null 2>&1 &
STUB_PID=$!
for _ in $(seq 1 20); do curl -s -o /dev/null -m 1 "http://127.0.0.1:$LIB_PORT/" && break; sleep 0.5; done
HOLDER_PID=$(netstat -ano 2>/dev/null | grep ":$LIB_PORT " | grep LISTENING | awk '{print $NF}' | head -1)
[ -n "$HOLDER_PID" ] && ok "a squatter is listening on $LIB_PORT (pid $HOLDER_PID)" || { bad "could not occupy $LIB_PORT"; }

M=$(mark)
curl -s -o /dev/null -X POST "$AGENT/v1/components" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d "{\"name\":\"library\",\"kind\":\"library\",\"url\":\"http://127.0.0.1:$LIB_PORT\",\"spawn\":{\"configFile\":\"library.yaml\"}}"
for _ in $(seq 1 40); do
  since "$M" | grep -q "already held by" && break
  sleep 0.5
done
TAIL=$(since "$M")
printf '%s' "$TAIL" | grep -q "port $LIB_PORT is already held by" \
  && ok "the agent named the port" || bad "no collision message: $(printf '%s' "$TAIL" | grep -i 'librar' | tail -3)"
printf '%s' "$TAIL" | grep -q "pid $HOLDER_PID" \
  && ok "*** and named the process holding it (pid $HOLDER_PID) ***" \
  || bad "the message does not name the holder"
printf '%s' "$TAIL" | grep -q "Nothing is killed for you" \
  && ok "...and says it will not kill it, which is the decision, not a limitation" \
  || bad "the message does not say what it will not do"
ERR=$(curl -s "$AGENT/v1/components/library" -H "Authorization: Bearer $TOK" | jq_ "repr(d.get('lastError'))")
printf '%s' "$ERR" | grep -q "already held by" \
  && ok "the operator sees it on /v1/components too, not only in the log" \
  || bad "lastError is $ERR"

# --- 6. the collision clears ----------------------------------------------------
say "6. the squatter leaves and the component takes its port"
kill -9 "$STUB_PID" 2>/dev/null; STUB_PID=""
free_port "$LIB_PORT"
wait_healthy "http://127.0.0.1:$LIB_PORT" 90 \
  && ok "the library started once the port was free -- no operator action needed" \
  || bad "the library never recovered"

# --- 7. stopping the AGENT stops everything ------------------------------------
say "7. a graceful stop of the agent takes its children with it"
# **The property any service integration depends on**, and one the
# process-group change could have broken: children now live in their own
# groups, so a console event no longer reaches them directly -- they go
# only through the agent's own shutdown path. If that path were wrong,
# the Job Object would still reap them when the agent died, which would
# hide the bug behind a safety net. So this asks the agent to stop
# GRACEFULLY and watches the ports, rather than killing it and watching
# the net work.
CHILD_PORTS="8080 8082 8083"
"$PY" -c "
import os, signal, sys
pid = int(sys.argv[1])
try:
    os.kill(pid, signal.CTRL_BREAK_EVENT)
    print('sent CTRL_BREAK to the agent')
except OSError as e:
    print('could not signal the agent:', e)
" "$AGENT_PID"
for _ in $(seq 1 40); do
  curl -sf -m 1 -o /dev/null "$AGENT/healthz" || break
  sleep 0.5
done
curl -sf -m 2 -o /dev/null "$AGENT/healthz" \
  && bad "the agent is still answering" || ok "the agent stopped"
sleep 2
LEFT=""
for p in $CHILD_PORTS; do
  netstat -ano 2>/dev/null | grep ":$p " | grep -q LISTENING && LEFT="$LEFT $p"
done
[ -z "$LEFT" ] && ok "*** no child left listening on $CHILD_PORTS ***" \
  || bad "orphans still listening on:$LEFT"
# **Unprefixed, and that is the whole assertion.** Every `[name] ...`
# line in this log is a CHILD's output piped through the agent; the
# agent's own uvicorn lines carry no prefix. The first version of this
# check grepped the whole file for the bare string and passed against
# `[gateway] INFO: Application shutdown complete.` written by step 1 —
# the parent's property read off the child's log, which is this
# project's recurring defect and now its own check.
grep -qE "^INFO: +Application shutdown complete" "$WORK/agent.log" \
  && ok "the AGENT ran its own shutdown, so children were stopped rather than reaped" \
  || bad "the agent did not shut down gracefully; the Job Object may have covered for it"

say "result"
if [ "$FAILURES" -eq 0 ]; then
  printf '\n  ALL CHECKS PASSED\n\n'
else
  printf '\n  %d CHECK(S) FAILED\n\n' "$FAILURES"
  echo "  agent log: $WORK/agent.log"
fi
exit "$FAILURES"
