#!/usr/bin/env bash
# "Reach it from other devices" (hobbyist UX plan, S5 -- decision #8).
#
# Design: docs/design/hobbyist-ux.md §7 S5 and §6.6; record §11.6.
#
# What only a live run can prove. The agent's tests pin the derivation,
# the verdicts and the refusals against fixtures; the UI's pin the
# sentences. None of them can prove that after one click a second
# address on this machine really answers -- that the components rebound,
# that the agent's own socket moved when it was restarted, and that the
# firewall detector's verdict describes THIS host rather than a fixture.
#
# The checks:
#   0. isolated from any install on this machine, and from its ports
#   1. the UI wheel staged from this working tree AND served by this agent
#   2. the fleet comes up with NOTHING DECLARED about binding -- the run
#      tests the default, which is the rule `easy-default-expert-override`
#      asks for
#   3. before: every process is on loopback and the LAN address refuses
#   4. `reach` proposes this host's real address, derived from the
#      routing table rather than from a control root on loopback
#   5. the switch writes the address, restarts the components, and says
#      the agent itself is still behind
#   6. after: the GATEWAY answers on the LAN address -- the components'
#      half, which needs no agent restart
#   7. the agent restarted by hand answers on the LAN address, and
#      `restartRequired` goes false
#   8. the UI loads from the LAN address (the done-when)
#   9. the off-host witness records the caller
#  10. the firewall verdict is about this host, and `blocked` carries a
#      command; with EP_FIREWALL=1 and elevation, blocked -> allowed
#  11. reach off returns the components to loopback
#  12. BROWSER: Home's card on a loopback-only install, and the switch
#  13. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped (install.ps1 sets the config-file var in the USER
# environment, so a throwaway agent would otherwise come up as the live
# worker and announce a dying port to the real control root -- that
# happened, 2026-09-12), ports are +100, teardown is by pid. Never
# `pkill -f eugene_plexus_`: this box is a worker node.
#
# **It binds 0.0.0.0 on purpose, on a machine that is on a network.**
# That is the subject. It stays up for the length of the run, on ports
# nothing else uses, and the host firewall is left exactly as it was
# unless EP_FIREWALL=1 says otherwise.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-reach}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
GW_PORT="${EP_GW_PORT:-8180}"
LIB_PORT="${EP_LIB_PORT:-8182}"
CTL_PORT="${EP_CTL_PORT:-8183}"
AGENT="http://127.0.0.1:$AGENT_PORT"
GW="http://127.0.0.1:$GW_PORT"
LIB="http://127.0.0.1:$LIB_PORT"
CTL="http://127.0.0.1:$CTL_PORT"
PASS="reach-acceptance-$$"
OWNED_PORTS="$AGENT_PORT $GW_PORT $LIB_PORT $CTL_PORT"
SKIP_BUILD="${EP_SKIP_BUILD:-0}"
# Changing the host firewall needs administrator rights and outlives the
# run, so it is opt-in and reported as skipped rather than quietly not
# done. A check that silently does not run is how "18 checks" once meant
# seventeen.
DO_FIREWALL="${EP_FIREWALL:-0}"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
skip() { printf '  SKIP  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
# A connect that either answers or does not, with a short ceiling: a
# closed port on Windows is DROPPED rather than refused, so this would
# otherwise sit for the full default timeout.
answers() { curl -s -o /dev/null -m 4 "$1" 2>/dev/null; }

A_PID=""
start_agent() {
  # **Nothing is declared about binding.** `EUGENE_PLEXUS_AGENT_BIND_HOST`
  # is deliberately absent: setting it -- even to the default -- lands in
  # pydantic's `model_fields_set` and becomes an explicit operator
  # override, which by `easy-default-expert-override` wins outright and
  # would stop the derived widening this run exists to measure. Every
  # acceptance script that sets it is testing a value rather than a rule.
  (exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" \
    EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
    "$PY" -m eugene_plexus_agent --unattended >> agent.log 2>&1) &
  A_PID=$!
}
stop_agent() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; }
  for p in $OWNED_PORTS; do
    for pid in $(listening_pids "$p"); do
      taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
    done
  done
  sleep 3
}
teardown() {
  stop_agent
  if [ "$DO_FIREWALL" = "1" ]; then
    powershell -NoProfile -Command \
      'Remove-NetFirewallRule -DisplayName "Eugene Plexus" -ErrorAction SilentlyContinue' \
      >/dev/null 2>&1
  fi
}

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
"$PY" -c "import eugene_plexus_agent, eugene_plexus_control, eugene_plexus_gateway, eugene_plexus_library, eugene_plexus_ui" 2>/dev/null \
  || { bad "the components and eugene_plexus_ui must import from $PY"; exit 1; }
[ -d "$UI_DIR/node_modules/@playwright" ] || { bad "no Playwright in $UI_DIR (npm install)"; exit 1; }
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
# This host's own address, worked out the way the agent works it out, so
# the run and the thing it measures cannot disagree about the subject.
LAN=$("$PY" -c "from eugene_plexus_agent.reach import proposed_host; print(proposed_host() or '')" | tr -d '\r')
[ -n "$LAN" ] || { bad "this machine has no non-loopback address; the whole run is about one"; exit 1; }
ok "agent python with five packages, Playwright, every port free, this host at $LAN"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

# --- 0 -----------------------------------------------------------------------
say "0. isolate this run"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
WORK_NATIVE=$(cygpath -w "$WORK" 2>/dev/null || printf '%s' "$WORK")
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }

# --- 1 -----------------------------------------------------------------------
say "1. stage this working tree's UI, and prove the agent venv SERVES it"
if [ "$SKIP_BUILD" = "1" ]; then
  skip "build skipped by EP_SKIP_BUILD=1"
else
  (cd "$UI_DIR" && npm run build:python > "$WORK/build.log" 2>&1)
  [ $? = 0 ] && ok "npm run build:python staged the export" || { bad "build failed"; tail -30 "$WORK/build.log"; exit 1; }
fi
STATIC="$UI_DIR/python/eugene_plexus_ui/static"
grep -qr 'home-reach' "$STATIC/_next/static/chunks" 2>/dev/null \
  && ok "the staged bundle carries the Reach card" \
  || bad "no home-reach in the staged bundle -- the agent would serve a pre-S5 build"
# Staging is not serving (S3's fourth finding): four runs asserted about
# a build no browser ever saw because the agent venv held a WHEEL.
SERVED=$("$PY" -c "from eugene_plexus_ui import static_dir; print(static_dir())" 2>/dev/null | tr -d '\r')
SERVED_NORM=$(printf '%s' "$SERVED" | tr '\\' '/' | tr '[:upper:]' '[:lower:]')
STATIC_NORM=$(cygpath -w "$STATIC" 2>/dev/null | tr '\\' '/' | tr '[:upper:]' '[:lower:]')
[ -n "$SERVED_NORM" ] && [ "$SERVED_NORM" = "$STATIC_NORM" ] \
  && ok "the agent venv's eugene_plexus_ui IS the staged directory (editable install)" \
  || { bad "the agent venv serves $SERVED, not $STATIC. Run: \"$PY\" -m pip install -e \"$UI_DIR\""; exit 1; }

cat > agent.yaml <<YAML
firstRunComplete: true
components:
  - name: control
    kind: control
    url: http://127.0.0.1:$CTL_PORT
    spawn:
      configFile: control.yaml
  - name: gateway
    kind: gateway
    url: http://127.0.0.1:$GW_PORT
    spawn:
      configFile: gateway.yaml
  - name: library
    kind: library
    url: http://127.0.0.1:$LIB_PORT
    spawn:
      configFile: library.yaml
runtimes: []
YAML
echo "logLevel: INFO" > gateway.yaml
echo "logLevel: INFO" > control.yaml
printf 'logLevel: INFO\nmodelRoots: []\n' > library.yaml

# --- 2 -----------------------------------------------------------------------
say "2. the fleet, with nothing declared about binding"
start_agent
wait_healthy "$AGENT" 60 || { bad "agent never answered"; tail -20 agent.log; exit 1; }
wait_healthy "$CTL" 90 && wait_healthy "$LIB" 60 && wait_healthy "$GW" 90 \
  && ok "agent $AGENT, control $CTL, library $LIB, gateway $GW" \
  || { bad "a child never came up"; tail -30 agent.log; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "no operator token"; exit 1; }
wait_healthy "$GW" 90 || { bad "gateway did not come back after initialize"; exit 1; }
ok "operator session; nothing set EUGENE_PLEXUS_AGENT_BIND_HOST"

# --- 3 -----------------------------------------------------------------------
say "3. before: loopback only"
answers "$AGENT/healthz" && ok "the agent answers on 127.0.0.1:$AGENT_PORT" || bad "the agent does not answer on loopback"
if answers "http://$LAN:$AGENT_PORT/healthz"; then
  bad "the agent already answers on $LAN before anything was turned on"
else
  ok "the agent does NOT answer on $LAN:$AGENT_PORT -- this is the state a phone meets"
fi
if answers "http://$LAN:$GW_PORT/healthz"; then
  bad "the gateway already answers on $LAN"
else
  ok "the gateway does NOT answer on $LAN:$GW_PORT"
fi

# --- 4 -----------------------------------------------------------------------
say "4. reach proposes this host's real address"
NODE=$(curl -s "$AGENT/v1/node" -H "Authorization: Bearer $TOK")
ENABLED=$(printf '%s' "$NODE" | jq_ "d['reach']['enabled']")
PROPOSED=$(printf '%s' "$NODE" | jq_ "d['reach'].get('proposedUrl','')")
[ "$ENABLED" = "False" ] && ok "reach.enabled is false" || bad "reach.enabled=$ENABLED"
case "$PROPOSED" in
  *"$LAN"*) ok "reach.proposedUrl is $PROPOSED" ;;
  *) bad "proposedUrl=$PROPOSED does not name $LAN" ;;
esac
# The measurement the whole slice turns on. On a standalone install the
# control root is on loopback, so the M7 derivation -- the local end of a
# socket to the root -- answers 127.0.0.1, which is the one address that
# cannot be it.
case "$PROPOSED" in
  *127.0.0.1*) bad "proposedUrl is loopback; the routing-table derivation did not happen" ;;
  *) ok "proposedUrl is NOT loopback, on a box whose control root is" ;;
esac
BOUND=$(printf '%s' "$NODE" | jq_ "','.join(sorted('%s=%s' % (b['process'], b['host']) for b in d['reach']['boundAddresses']))")
note "bound: $BOUND"
case "$BOUND" in
  *"agent=127.0.0.1"*) ok "boundAddresses reports the agent on loopback, from the bind" ;;
  *) bad "boundAddresses says agent is not on loopback: $BOUND" ;;
esac

# --- 5 -----------------------------------------------------------------------
say "5. the switch"
RESULT=$(curl -s -X POST "$AGENT/v1/node/reach" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' -d '{"enabled":true}')
STEPS=$(printf '%s' "$RESULT" | jq_ "','.join('%s=%s' % (s['step'], s['ok']) for s in d['steps'])")
note "steps: $STEPS"
case "$STEPS" in *"advertise=True"*) ok "the address was written" ;; *) bad "advertise step: $STEPS" ;; esac
case "$STEPS" in *"restart_components=True"*) ok "the components were restarted" ;; *) bad "restart step: $STEPS" ;; esac
ADV=$(printf '%s' "$RESULT" | jq_ "d['reach'].get('advertiseUrl','')")
case "$ADV" in *"$LAN"*) ok "advertiseUrl is now $ADV" ;; *) bad "advertiseUrl=$ADV" ;; esac
# The honest half: the setting moved and this agent's socket did not.
[ "$(printf '%s' "$RESULT" | jq_ "d['reach']['restartRequired']")" = "True" ] \
  && ok "restartRequired is true -- the agent says the change is half done" \
  || bad "restartRequired is false while the agent is still on loopback"
# And it refuses to stop itself: nothing started this agent.
#
# **This was a NOTE in the first execution and it should have been a
# check.** It fired: a throwaway agent, in a checkout's own virtualenv,
# on ports +100, reported `logon_task` / `canSelfRestart: true` --
# because the LIVE install on this box owns a scheduled task by that
# name, and the detector only asked whether one existed. Requesting a
# restart there would have run `schtasks /End` against the operator's
# real agent. A note is what you write when you do not want to decide,
# and deciding this is the whole reason to run on a box that also holds
# a live install.
SELF=$(printf '%s' "$RESULT" | jq_ "d['reach']['restart']['canSelfRestart']")
MECH=$(printf '%s' "$RESULT" | jq_ "d['reach']['restart']['mechanism']")
[ "$SELF" = "False" ] && [ "$MECH" = "none" ] \
  && ok "mechanism is none and canSelfRestart is false -- nothing started this agent, so nothing may stop it" \
  || bad "mechanism=$MECH canSelfRestart=$SELF: this agent claims a supervisor it does not have, and a restart would hit another install"

# --- 6 -----------------------------------------------------------------------
say "6. after: the components rebound with no agent restart"
REBOUND=""
for _ in $(seq 1 40); do
  answers "http://$LAN:$GW_PORT/healthz" && { REBOUND=1; break; }; sleep 1
done
[ -n "$REBOUND" ] \
  && ok "the gateway answers on $LAN:$GW_PORT -- a spawn is all a component needs" \
  || bad "the gateway never came back on $LAN:$GW_PORT"
answers "http://$LAN:$AGENT_PORT/healthz" \
  && bad "the agent answers on $LAN already; a listening socket should not have moved" \
  || ok "the agent still does NOT answer on $LAN -- its socket is fixed for the life of the process"

# --- 7 -----------------------------------------------------------------------
say "7. the agent restarted by hand"
stop_agent
start_agent
wait_healthy "$AGENT" 60 || { bad "the agent did not come back"; tail -20 agent.log; exit 1; }
answers "http://$LAN:$AGENT_PORT/healthz" \
  && ok "the agent answers on $LAN:$AGENT_PORT" \
  || bad "the agent still does not answer on $LAN after a restart"
grep -q "binding 0.0.0.0 because this node advertises" agent.log \
  && ok "the agent said why it widened its bind" \
  || note "no bind explanation in the log"
TOK=$(curl -s -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
wait_healthy "$GW" 120 || { bad "gateway did not come back"; exit 1; }
NODE=$(curl -s "$AGENT/v1/node" -H "Authorization: Bearer $TOK")
[ "$(printf '%s' "$NODE" | jq_ "d['reach']['restartRequired']")" = "False" ] \
  && ok "restartRequired is false: the setting and the socket agree" \
  || bad "restartRequired is still true after the restart"

# --- 8 -----------------------------------------------------------------------
say "8. the UI loads from the second address (the done-when)"
PAGE=$(curl -s -m 10 "http://$LAN:$AGENT_PORT/")
printf '%s' "$PAGE" | grep -q "<html" \
  && ok "http://$LAN:$AGENT_PORT/ serves the UI" \
  || bad "the UI did not load from $LAN"
[ "$(code_of -m 10 -H "Authorization: Bearer $TOK" "http://$LAN:$AGENT_PORT/v1/node")" = "200" ] \
  && ok "the API answers on $LAN too" \
  || bad "the API did not answer on $LAN"
[ "$(code_of -m 10 -H "Authorization: Bearer $TOK" "http://$LAN:$GW_PORT/v1/models")" = "200" ] \
  && ok "the gateway's OpenAI surface answers on $LAN" \
  || bad "the gateway's OpenAI surface did not answer on $LAN"

# --- 9 -----------------------------------------------------------------------
say "9. the off-host witness"
# Every call in check 8 came FROM this host's own LAN address -- the
# kernel picks that source when the destination is that address -- so it
# is a genuine non-loopback caller and the agent has no way to tell it
# apart from a phone. That it is the same machine is worth saying: the
# witness proves the recording works, not that another device connected.
NODE=$(curl -s -m 10 -H "Authorization: Bearer $TOK" "http://$LAN:$AGENT_PORT/v1/node")
FROM=$(printf '%s' "$NODE" | jq_ "d['reach'].get('lastReachedFrom','')")
[ "$FROM" = "$LAN" ] \
  && ok "lastReachedFrom is $FROM -- a connection that arrived, not a rule that should allow one" \
  || bad "lastReachedFrom=$FROM, expected $LAN"
# And a loopback caller does not overwrite it, which is what makes it
# evidence rather than a request counter.
curl -s -o /dev/null -m 10 -H "Authorization: Bearer $TOK" "$AGENT/v1/node"
FROM2=$(curl -s -m 10 -H "Authorization: Bearer $TOK" "http://$LAN:$AGENT_PORT/v1/node" | jq_ "d['reach'].get('lastReachedFrom','')")
[ "$FROM2" = "$LAN" ] && ok "a loopback caller did not overwrite it" || bad "lastReachedFrom became $FROM2"

# --- 10 ----------------------------------------------------------------------
say "10. the firewall verdict is about this host"
FW=$(curl -s -H "Authorization: Bearer $TOK" "$AGENT/v1/node" | jq_ "json.dumps(d['reach']['firewall'])")
note "firewall: $FW"
PRODUCT=$(printf '%s' "$FW" | jq_ "d.get('product','')")
VERDICT=$(printf '%s' "$FW" | jq_ "([p['verdict'] for p in d.get('ports',[]) if p['port']==$AGENT_PORT] or [''])[0]")
[ -n "$PRODUCT" ] && ok "the detector names the product: $PRODUCT" || bad "no product named"
case "$VERDICT" in
  allowed|blocked|unknown) ok "the verdict for $AGENT_PORT is $VERDICT" ;;
  *) bad "no verdict for $AGENT_PORT: $FW" ;;
esac
# A verdict that is not `allowed` must carry the command that would
# change it. An answer with no next step is the state §0.9 measured.
if [ "$VERDICT" != "allowed" ]; then
  REMEDY=$(printf '%s' "$FW" | jq_ "([p.get('remedy','') for p in d.get('ports',[]) if p['port']==$AGENT_PORT] or [''])[0]")
  [ -n "$REMEDY" ] && ok "and it carries a command: $REMEDY" || bad "a non-allowed verdict with no remedy"
fi
# The trap §6.6 named, now measured on this box: the rule that makes the
# live worker reachable is bound to the PROGRAM, not to a port, so a
# port-only detector would report `blocked` on a machine that is not.
SCOPE=$(printf '%s' "$FW" | jq_ "([p.get('scope','') for p in d.get('ports',[]) if p['port']==$AGENT_PORT] or [''])[0]")
[ -n "$SCOPE" ] && note "the deciding rule is scoped to the $SCOPE" || note "no rule decided; the default did"

if [ "$DO_FIREWALL" != "1" ]; then
  skip "blocked -> allowed needs administrator rights and outlives the run (EP_FIREWALL=1)"
else
  powershell -NoProfile -Command \
    'Remove-NetFirewallRule -DisplayName "Eugene Plexus" -ErrorAction SilentlyContinue' >/dev/null 2>&1
  BEFORE=$(curl -s -H "Authorization: Bearer $TOK" "$AGENT/v1/node" | jq_ "([p['verdict'] for p in d['reach']['firewall'].get('ports',[]) if p['port']==$AGENT_PORT] or [''])[0]")
  curl -s -o /dev/null -X POST "$AGENT/v1/node/reach" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' -d '{"enabled":true,"allowFirewall":true}'
  sleep 3
  AFTER=$(curl -s -H "Authorization: Bearer $TOK" "$AGENT/v1/node" | jq_ "([p['verdict'] for p in d['reach']['firewall'].get('ports',[]) if p['port']==$AGENT_PORT] or [''])[0]")
  [ "$AFTER" = "allowed" ] \
    && ok "the firewall verdict went $BEFORE -> allowed after the rule was added" \
    || bad "the verdict is $AFTER after adding the rule (was $BEFORE)"
  RULE_SCOPE=$(curl -s -H "Authorization: Bearer $TOK" "$AGENT/v1/node" | jq_ "([p.get('scope','') for p in d['reach']['firewall'].get('ports',[]) if p['port']==$AGENT_PORT] or [''])[0]")
  [ "$RULE_SCOPE" = "port" ] \
    && ok "and the rule we added is scoped to the PORT, not to the interpreter" \
    || bad "our own rule is scoped to $RULE_SCOPE"
fi

# --- 11 ----------------------------------------------------------------------
say "11. reach off returns the components to loopback"
OFF=$(curl -s -X POST "$AGENT/v1/node/reach" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' -d '{"enabled":false}')
[ "$(printf '%s' "$OFF" | jq_ "d['reach']['enabled']")" = "False" ] && ok "reach.enabled is false again" || bad "still enabled: $OFF"
GONE=""
for _ in $(seq 1 40); do
  answers "http://$LAN:$GW_PORT/healthz" || { GONE=1; break; }; sleep 1
done
[ -n "$GONE" ] && ok "the gateway is back on loopback only" || bad "the gateway still answers on $LAN"
# And turning it off does NOT demand a restart. Nothing outside can
# observe the agent's still-wide socket now that no address is
# advertised, and a restart would cost the console for a change nobody
# can see.
[ "$(printf '%s' "$OFF" | jq_ "d['reach']['restartRequired']")" = "False" ] \
  && ok "restartRequired stayed false -- off is not a reason to restart" \
  || bad "turning reach off asked for a restart"

# --- 12 ----------------------------------------------------------------------
say "12. the browser"
# Back to the state a person meets, and driven from loopback so the page
# under test is the one a standalone install serves.
stop_agent
start_agent
wait_healthy "$AGENT" 60 || { bad "the agent did not come back for the browser"; exit 1; }
wait_healthy "$GW" 120 || note "the gateway was slow to return"
cat > "$UI_DIR/e2e/reach.spec.ts" <<'SPEC'
import { expect, test } from "@playwright/test";

const BASE = process.env.EP_BASE ?? "http://127.0.0.1:8179";
const PASS = process.env.EP_PASS ?? "";

// A login form served by `output: export` is inert HTML until React
// hydrates, and a `fill` landing in that window is silently discarded
// (S4's finding (c)). Re-fill until the value sticks.
async function signIn(page: import("@playwright/test").Page) {
  await page.goto(`${BASE}/login`);
  const box = page.getByLabel(/passphrase/i).first();
  await box.waitFor({ state: "visible" });
  await expect(async () => {
    await box.fill(PASS);
    expect(await box.inputValue()).toBe(PASS);
  }).toPass({ timeout: 15000 });
  await page.getByRole("button", { name: /unlock|sign in/i }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 20000 });
}

test("Home offers the address a phone would use, and the switch turns it on", async ({ page }) => {
  await signIn(page);
  await page.goto(BASE);
  const card = page.getByTestId("home-reach");
  await card.waitFor({ state: "visible", timeout: 20000 });

  const headline = card.getByTestId("reach-headline");
  await expect(headline).toContainText("Only this PC");
  // The address in the card is the one a phone would type, not loopback.
  await expect(headline).not.toContainText("127.0.0.1");

  const toggle = card.getByTestId("reach-switch");
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();

  // The switch does not report success it has not got: the agent's own
  // socket has not moved, and the card says so rather than leaving it to
  // be discovered on a phone.
  await expect(card.getByTestId("reach-headline")).toContainText(/restart/i, { timeout: 30000 });
});
SPEC
(cd "$UI_DIR" && EP_BASE="$AGENT" EP_PASS="$PASS" npx playwright test e2e/reach.spec.ts --reporter=line > "$WORK/e2e.log" 2>&1)
if [ $? = 0 ]; then
  ok "Chrome: the card, the address, and the switch"
else
  bad "the browser test failed"; tail -30 "$WORK/e2e.log"
fi

# --- 13 ----------------------------------------------------------------------
say "13. teardown"
stop_agent
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ] && ok "no owned port still listening" || bad "still listening:$STILL"

printf '\n== %d failure(s)\n' "$FAILURES"
exit $((FAILURES > 0))
