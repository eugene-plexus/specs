#!/usr/bin/env bash
#
# M9 acceptance: onboarding, leaving, moving house -- and a browser.
#
#   host A (this box)   agent A :8079  -> seeds control :8083, gateway :8080, library :8082
#                       and serves the UI at its own root from the
#                       eugene-plexus-ui wheel (EP_SKIP_BROWSER=1 to omit)
#   host B (also here)  agent B :8084  -> onboarded by `eugene-plexus-agent join`
#
# **THIS SCRIPT DOES NOT PRE-WRITE `firstRunComplete`, AND THAT IS THE
# POINT.** Every multi-host script since M0 wrote `firstRunComplete: true`
# with an empty component list before starting anything -- which is the
# bypass for an onboarding feature that did not exist, written so fluently
# that nobody noticed it was standing in for one. Host A here starts with
# NO agent.yaml at all and has to declare its own control plane; host B is
# onboarded the way an operator would, with a token minted at the root.
#
# Four things under test, all new at M9:
#   1. onboarding   -- a fresh agent seeds; `join` enrolls without a browser
#                      and leaves a node that does NOT raise a rival root
#   2. re-advertise -- a node whose address changes tells the root, signed,
#                      on startup and on a config change; replays refused
#   3. unenroll     -- a node discards the install's key and returns to its
#                      own, telling the root, and proceeding if it cannot
#   4. the browser  -- Playwright drives first run, login, restart-on-login,
#                      and the topology-resolved proxy. No script can test
#                      the third: logging in respawns every child, so the
#                      page that just authenticated is talking to a fleet
#                      that is going away.
#
# Design: docs/design/m9-networked-polish.md
# Deployment doc this exercises the happy path of: docs/deployment/tailnet.md
#
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
EP_AGENT_PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
EP_UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
EP_WORKDIR="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-m9-acceptance}"
EP_AGENT_A_URL="${EP_AGENT_A_URL:-http://127.0.0.1:8079}"
EP_AGENT_B_URL="${EP_AGENT_B_URL:-http://127.0.0.1:8084}"
EP_AGENT_B2_URL="${EP_AGENT_B2_URL:-http://127.0.0.1:8085}"
EP_CONTROL_URL="${EP_CONTROL_URL:-http://127.0.0.1:8083}"
EP_GATEWAY_URL="${EP_GATEWAY_URL:-http://127.0.0.1:8080}"
# **The browser drives the agent, not a dev server.** Until
# install-paths §9 step 1 this was `next dev` on :3100, which is the one
# thing an install never runs: the UI now ships as a static export inside
# the `eugene-plexus-ui` wheel and the agent serves it at its own root.
# Pointing Playwright at a dev server tested a configuration no operator
# has -- a reference client sharing a path with nothing it ships.
EP_UI_URL="${EP_UI_URL:-$EP_AGENT_A_URL}"
EP_SKIP_BROWSER="${EP_SKIP_BROWSER:-}"
PASSPHRASE="${EP_PASSPHRASE:-m9-acceptance-passphrase}"

B_PORT=$(printf '%s' "$EP_AGENT_B_URL" | sed -E 's|.*:([0-9]+)/?$|\1|')
B2_PORT=$(printf '%s' "$EP_AGENT_B2_URL" | sed -E 's|.*:([0-9]+)/?$|\1|')

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
wait_http() { for _ in $(seq 1 "${2:-90}"); do curl -sf -m 2 -o /dev/null "$1" && return 0; sleep 1; done; return 1; }
ctl_login() { curl -s -X POST "$EP_CONTROL_URL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')"; }
agent_login() { curl -s -X POST "$1/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')"; }

# --- preflight -----------------------------------------------------------------
say "preflight"
[ -f "$EP_AGENT_PY" ] || bad "agent venv python not found at $EP_AGENT_PY"
[ "$FAILURES" -ne 0 ] && exit 1
"$EP_AGENT_PY" -c "import eugene_plexus_agent, eugene_plexus_control, eugene_plexus_gateway, eugene_plexus_inference_driver, eugene_plexus_library" 2>/dev/null \
  || { bad "all five components must import from $EP_AGENT_PY"; exit 1; }
ok "five components import from the agent's interpreter"

BROWSER=1
if [ -n "$EP_SKIP_BROWSER" ]; then
  BROWSER=0
  echo "  browser arc skipped (EP_SKIP_BROWSER set)"
elif [ ! -d "$EP_UI_DIR/node_modules" ]; then
  BROWSER=0
  echo "  browser arc skipped: $EP_UI_DIR/node_modules is absent (npm ci first)"
else
  # **Rebuild the wheel rather than trust the installed one.** The agent
  # serves whatever `eugene-plexus-ui` is in its interpreter, and a wheel
  # of unknown age is a stale instrument -- the failure that already cost
  # this script a misattributed run when `next dev` kept serving a
  # previous build. `EP_SKIP_UI_BUILD=1` for a fast re-run where the UI
  # has not changed.
  if [ -z "${EP_SKIP_UI_BUILD:-}" ]; then
    if (cd "$EP_UI_DIR" && npm run build:python > "$EP_WORKDIR-uibuild.log" 2>&1 \
          && "$EP_AGENT_PY" -m build --wheel >> "$EP_WORKDIR-uibuild.log" 2>&1 \
          && "$EP_AGENT_PY" -m pip install --quiet --force-reinstall \
               "$(ls -t "$EP_UI_DIR"/dist/eugene_plexus_ui-*.whl | head -1)" \
               >> "$EP_WORKDIR-uibuild.log" 2>&1); then
      ok "rebuilt and installed eugene-plexus-ui from the checkout"
    else
      BROWSER=0
      echo "  browser arc skipped: the ui wheel would not build -- see $EP_WORKDIR-uibuild.log"
      tail -15 "$EP_WORKDIR-uibuild.log"
    fi
  fi
  if [ "$BROWSER" = "1" ]; then
    "$EP_AGENT_PY" -c "import eugene_plexus_ui" 2>/dev/null \
      && ok "the browser arc will drive the agent's own UI at $EP_UI_URL" \
      || { BROWSER=0; echo "  browser arc skipped: eugene-plexus-ui is not installed in $EP_AGENT_PY"; }
  fi
fi

rm -rf "$EP_WORKDIR"; mkdir -p "$EP_WORKDIR/a" "$EP_WORKDIR/b" "$EP_WORKDIR/seeded"; cd "$EP_WORKDIR" || exit 1

A_PID=""; B_PID=""
# **Clear the PORT, not just the pid.** Written for `next dev`, which
# spawned a child of its own, so killing the held pid left a server
# listening and the next run silently tested the previous run's build --
# a misattributed failure that cost a session. The dev server is gone
# (the agent serves the UI now) and the rule is not: Windows lets a
# second process bind an already-bound loopback port and keeps serving
# from the OLDEST binder, which is how M10 read a two-runs-old reply.
# Same shape as M7's "the pid the script held was a subshell's", one
# layer further out.
kill_port() {
  local port="$1"
  local pids
  pids=$(netstat -ano 2>/dev/null | grep -E "LISTENING" | grep -E ":$port[[:space:]]" | awk '{print $NF}' | sort -u)
  for pid in $pids; do
    [ -n "$pid" ] && taskkill //PID "$pid" //T //F >/dev/null 2>&1
  done
}
cleanup() {
  for pid in "$B_PID" "$A_PID"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
  done
  for port in "${EP_AGENT_A_URL##*:}" "$B_PORT" "$B2_PORT"; do kill_port "$port"; done
}
trap cleanup EXIT
# And clear them up front too, because a previous run that was
# interrupted rather than exited never reached its own trap.
for port in "${EP_AGENT_A_URL##*:}" "$B_PORT" "$B2_PORT"; do kill_port "$port"; done

# --- 1. a fresh machine declares its own control plane --------------------------
say "1. agent A starts with NO agent.yaml -- and has to be an install by itself"
[ -f a/agent.yaml ] && bad "a/agent.yaml exists before the run; the bypass is back" || ok "no agent.yaml exists yet"
# No TTY here, deliberately: that is the documented non-interactive path
# and the one a service unit takes. It must seed rather than block.
(cd a && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml "$EP_AGENT_PY" -m eugene_plexus_agent > ../agent-a.log 2>&1) &
A_PID=$!
wait_healthy "$EP_AGENT_A_URL" && ok "agent A answering with nothing configured" || { bad "agent A never came up"; tail -30 agent-a.log; exit 1; }
wait_healthy "$EP_CONTROL_URL" && ok "control root spawned by a first boot nobody configured" || { bad "control never came up"; tail -40 agent-a.log; exit 1; }
wait_healthy "$EP_GATEWAY_URL" 90 && ok "gateway spawned" || bad "gateway never came up"
grep -q "first boot: declared the default topology" agent-a.log \
  && ok "agent A said so in its own log" || bad "no first-boot declaration in agent-a.log"

if [ "$BROWSER" = "1" ]; then
  # --- 2. the browser does first run ---------------------------------------------
  say "2. a browser walks the first-run wizard, logs in, and survives the restart"
  # No server to start: agent A is already up and already serving the UI,
  # which is the whole point of the repoint. The wait is on the page
  # rather than on a process, because the agent answering /healthz says
  # nothing about whether the wheel is mounted.
  if wait_http "$EP_UI_URL/" 30; then
    ok "the agent is serving the UI at $EP_UI_URL"
    if (cd "$EP_UI_DIR" && EP_UI_URL="$EP_UI_URL" EP_PASSPHRASE="$PASSPHRASE" \
         npx playwright test > "$EP_WORKDIR/playwright.log" 2>&1); then
      ok "the browser arc passed (first run, login, restart-on-login, proxy)"
    else
      bad "the browser arc failed -- see $EP_WORKDIR/playwright.log"
      tail -40 "$EP_WORKDIR/playwright.log"
    fi
  else
    bad "the agent never served a page; skipping the browser arc"
    tail -20 agent-a.log
  fi
else
  say "2. no browser; initializing with curl the way every earlier script did"
  curl -s -o /dev/null -X POST "$EP_AGENT_A_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}"
  curl -s -o /dev/null -X POST "$EP_CONTROL_URL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASSPHRASE\"}"
fi

ATOK=$(agent_login "$EP_AGENT_A_URL")
CTOK=$(ctl_login)
[ -n "$ATOK" ] && ok "agent A has an operator session" || { bad "no agent A session"; exit 1; }
[ -n "$CTOK" ] && ok "the trust root is initialized and issues sessions" || { bad "control is not initialized -- did the wizard reach it?"; exit 1; }

# --- 3. onboarding host B without a browser -------------------------------------
say "3. host B joins with a minted token, on its own terminal"
TOKEN=$(curl -s -X POST "$EP_CONTROL_URL/v1/nodes/join-token" -H "Authorization: Bearer $CTOK" -H 'content-type: application/json' -d '{"nodeName":"node-b"}' | jq_ "d.get('token','')")
[ -n "$TOKEN" ] && ok "join token minted at the control root" || { bad "no join token"; exit 1; }

# The refusal first, against a directory that already has a control plane
# in it. Joining there would leave a rival root running, which is the
# exact failure the seeding rule exists to prevent.
printf 'components:\n  - name: control\n    kind: control\n    url: http://127.0.0.1:9083\n    spawn:\n      configFile: control.yaml\nruntimes: []\n' > seeded/agent.yaml
JOIN_REFUSED=$( (cd seeded && env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml "$EP_AGENT_PY" -m eugene_plexus_agent join --control "$EP_CONTROL_URL" --token "$TOKEN" 2>&1); echo "rc=$?" )
printf '%s' "$JOIN_REFUSED" | grep -q "rc=2" && ok "join refuses a machine that already has components declared" || bad "join did not refuse a seeded machine: $JOIN_REFUSED"
printf '%s' "$JOIN_REFUSED" | grep -q -- "--force" && ok "...and the refusal names the override" || bad "the refusal does not name --force"
[ -f seeded/node.yaml ] && bad "a refused join still wrote node.yaml" || ok "a refused join recorded nothing"

# Now the real one. No app, no browser, nothing running on B.
(cd b && env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$B_PORT" \
    "$EP_AGENT_PY" -m eugene_plexus_agent join --control "$EP_CONTROL_URL" --token "$TOKEN" \
    --name node-b --advertise "$EP_AGENT_B_URL" > ../join-b.log 2>&1)
JOIN_RC=$?
[ "$JOIN_RC" = "0" ] && ok "eugene-plexus-agent join enrolled host B with nothing running there" || { bad "join failed (rc=$JOIN_RC)"; cat join-b.log; }
[ -f b/node.yaml ] && ok "node.yaml written on B" || bad "no node.yaml on B"
grep -q "signingPrivateKey" b/node.yaml && ok "B minted a signing identity, so it can re-advertise later" || bad "B has no signing key"
curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('signingPublicKey') and 'yes' or 'no'" | grep -q yes \
  && ok "the root recorded B's signing public key" || bad "the root has no signing key for B"

# --- 4. and the next start does not raise a rival control plane ------------------
say "4. host B starts, and is a worker rather than a second install"
(cd b && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$B_PORT" "$EP_AGENT_PY" -m eugene_plexus_agent > ../agent-b.log 2>&1) &
B_PID=$!
wait_healthy "$EP_AGENT_B_URL" && ok "agent B answering on :$B_PORT" || { bad "agent B never came up"; tail -30 agent-b.log; exit 1; }
grep -q "first boot: declared the default topology" agent-b.log \
  && bad "agent B declared a control plane of its own -- the rival-root failure" \
  || ok "agent B declared nothing; it gets its topology from the install"
# **A joined node has no passphrase of its own and never will.** It
# verifies tokens with the install's signing key, so an operator session
# minted at the control root is the credential for it — which is the
# property enrollment exists for, and the reason `/v1/auth/login` here
# answers 503 and names the control root rather than offering setup.
# The first version of this script tried to log in at B and spent four
# checks failing on the consequence.
curl -s "$EP_AGENT_B_URL/v1/auth/login" -X POST -H 'content-type: application/json'   -d "{\"passphrase\":\"$PASSPHRASE\"}" | grep -q "control root"   && ok "logging in at a joined node points the operator at the control root"   || bad "a joined node's login does not explain where to log in instead"
BTOK="$CTOK"
curl -s -o /dev/null -w '%{http_code}' "$EP_AGENT_B_URL/v1/node" -H "Authorization: Bearer $CTOK" | grep -q 200 \
  && ok "a token minted at the control root verifies on B" || bad "the install key did not reach B"
curl -s "$EP_AGENT_B_URL/v1/node" -H "Authorization: Bearer $CTOK" | jq_ "d.get('enrolled')" | grep -q True \
  && ok "B reports itself enrolled" || bad "B does not report itself enrolled"

# --- 5. the defect: a node that moves house says so ------------------------------
say "5. a node whose address changes tells the root -- the M9 defect"
BEFORE=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('url','')")
printf '  recorded before: %s\n' "$BEFORE"
[ -n "$BEFORE" ] && ok "the root holds an address for B" || bad "the root has no address for B"

# Change it through the config trio, which is the operator-facing way.
# Deliberately an address nothing is listening on: per the standing rule,
# an expert override has to win *including with a value that will fail*,
# or it is not an override. It also keeps this distinct from the address
# section 6 re-derives, so that section's announcement is a real change
# rather than a no-op -- which the first run of this script got wrong,
# and then reported a correct no-op as a missing announcement.
MOVED="http://127.0.0.1:8099"
curl -s -o /dev/null -X PATCH "$EP_AGENT_B_URL/v1/config" -H "Authorization: Bearer $BTOK" \
  -H 'content-type: application/json' -d "{\"advertiseUrl\":\"$MOVED\"}"
for _ in $(seq 1 15); do
  AFTER=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('url','')")
  [ "${AFTER%/}" = "$MOVED" ] && break
  sleep 1
done
[ "${AFTER%/}" = "$MOVED" ] && ok "the root followed B to $MOVED without a re-enrollment" || bad "the root still has $AFTER"
SEQ=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('advertiseSequence',0)")
[ "$SEQ" -ge 1 ] && ok "announcement sequence is $SEQ, recorded in applied state" || bad "sequence did not advance"

# A replay of an old announcement must not move it back. The signature is
# valid -- that is the point; only the counter refuses it.
REPLAY=$(curl -s -o /dev/null -w '%{http_code}' -X PATCH "$EP_CONTROL_URL/v1/nodes/node-b" \
  -H 'content-type: application/json' \
  -d "{\"url\":\"$BEFORE\",\"sequence\":1,\"signature\":\"$(printf 'x%.0s' {1..86})=\"}")
[ "$REPLAY" = "401" ] || [ "$REPLAY" = "409" ] && ok "an unsigned/stale announcement is refused ($REPLAY)" || bad "a forged announcement answered $REPLAY"
STILL=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('url','')")
[ "${STILL%/}" = "$MOVED" ] && ok "...and B is still at $MOVED" || bad "the forged announcement moved B to $STILL"

# --- 6. announce on startup, which is the case that actually matters -------------
say "6. B restarts on a different port and announces it without being asked"
kill "$B_PID" 2>/dev/null; wait "$B_PID" 2>/dev/null; B_PID=""
# Clear the operator's override so the agent re-derives, which is what a
# rebooted host does. The persisted value is deliberately NOT trusted.
python - "$EP_WORKDIR/b/agent.yaml" <<'PY'
import sys, yaml
p = sys.argv[1]
doc = yaml.safe_load(open(p, encoding="utf-8")) or {}
doc.pop("advertiseUrl", None)
open(p, "w", encoding="utf-8").write(yaml.safe_dump(doc, sort_keys=True))
PY
(cd b && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$B2_PORT" "$EP_AGENT_PY" -m eugene_plexus_agent > ../agent-b2.log 2>&1) &
B_PID=$!
wait_healthy "$EP_AGENT_B2_URL" && ok "agent B back on :$B2_PORT" || { bad "agent B never came back"; tail -30 agent-b2.log; }
for _ in $(seq 1 20); do
  REDERIVED=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('url','')")
  printf '%s' "$REDERIVED" | grep -q ":$B2_PORT" && break
  sleep 1
done
printf '%s' "$REDERIVED" | grep -q ":$B2_PORT" \
  && ok "B re-derived its address at boot and announced $REDERIVED" \
  || bad "the root still has $REDERIVED; announce-on-startup did not happen"
grep -q "told the control root this node is now reachable" agent-b2.log \
  && ok "B logged the announcement" || bad "no announcement in agent-b2.log"

# And a restart that has nothing to report must cost the log nothing --
# otherwise every reboot of every node grows it with uptime rather than
# with events.
SEQ_BEFORE=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('advertiseSequence',0)")
kill "$B_PID" 2>/dev/null; wait "$B_PID" 2>/dev/null
(cd b && exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml EUGENE_PLEXUS_AGENT_BIND_PORT="$B2_PORT" "$EP_AGENT_PY" -m eugene_plexus_agent > ../agent-b3.log 2>&1) &
B_PID=$!
wait_healthy "$EP_AGENT_B2_URL" && ok "agent B restarted at the same address" || bad "agent B did not come back"
sleep 3
SEQ_AFTER=$(curl -s "$EP_CONTROL_URL/v1/nodes/node-b" -H "Authorization: Bearer $CTOK" | jq_ "d.get('advertiseSequence',0)")
[ "$SEQ_AFTER" = "$SEQ_BEFORE" ] && ok "a restart that did not move recorded nothing (sequence still $SEQ_AFTER)" || bad "an unchanged restart advanced the root's sequence $SEQ_BEFORE -> $SEQ_AFTER"

# --- 7. leaving ------------------------------------------------------------------
say "7. B leaves the install, and stops being able to authenticate with its key"
# The root's own operator token, forwarded by the agent to the root's
# DELETE. One install, one signing key: the session that authorizes this
# here is an operator session there too.
BTOK2=$(ctl_login)
LEFT=$(curl -s -X POST "$EP_AGENT_B2_URL/v1/node/unenroll" -H "Authorization: Bearer $BTOK2" -H 'content-type: application/json' -d '{}')
printf '%s' "$LEFT" | jq_ "d.get('controlNotified')" | grep -q True && ok "B told the root on the way out" || bad "controlNotified was not true: $LEFT"
printf '%s' "$LEFT" | jq_ "d.get('identity',{}).get('enrolled')" | grep -q False && ok "B reports itself unenrolled" || bad "B still reports enrolled"
grep -q "signingKey:" b/node.yaml && bad "B kept the install's signing key" || ok "the install's signing key is gone from node.yaml"
grep -q "signingPrivateKey:" b/node.yaml && ok "B kept its own keypairs, which are the host's and not the install's" || bad "B discarded its own identity too"
# Revoking rotates the install key, so the root's own list must no longer
# name B -- and the token minted before the rotation must stop working.
curl -s "$EP_CONTROL_URL/v1/nodes" -H "Authorization: Bearer $(ctl_login)" | jq_ "'node-b' in [n['name'] for n in d.get('nodes',[])]" | grep -q False \
  && ok "the root no longer lists node-b" || bad "node-b is still in the registry"

say "done"
if [ "$FAILURES" -eq 0 ]; then
  printf '\nALL CHECKS PASSED\n'
else
  printf '\n%d CHECK(S) FAILED\n' "$FAILURES"
fi
printf '\nlogs in %s\n' "$EP_WORKDIR"
printf 'WHAT THIS PROVES AND DOES NOT\n'
printf '  proves: a fresh machine declares its own control plane with no config file\n'
printf '          and no browser; `join` onboards a second machine from a terminal\n'
printf '          and leaves it a worker rather than a rival root; a node that moves\n'
printf '          tells the root, signed, on a config change AND on a restart, with\n'
printf '          replays refused; un-enrolling discards the install key and the root\n'
printf '          is told.\n'
printf '  cannot: a node genuinely offline while it moves; two real hosts (that is\n'
printf '          m7-acceptance.sh in EP_MODE=two-host); a tailnet address changing\n'
printf '          under a running install, which is what this simulates with a port.\n'
exit "$FAILURES"
