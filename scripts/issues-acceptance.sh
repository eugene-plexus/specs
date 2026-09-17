#!/usr/bin/env bash
# "Needs attention" (hobbyist UX plan, S7): the Issues list, live.
#
# Design: docs/design/hobbyist-ux.md §7 S7; record §11.9.
#
# What only a live run can prove. `issues.test.ts` pins the rules against
# bodies taken off the live install, `useIssues.test.tsx` pins the reads
# against a mocked wire, and the two component suites pin the rendering.
# None of them can prove that a real agent PUTS `NodeIdentity.time` on
# the wire, that a real llama.cpp declared with no offload reads back the
# way the rule expects, that two real engine builds serving at once are
# visible as a mixed fleet, or that a genuinely sealed control root can
# be opened from the header of whatever page the person is on.
#
# The checks:
#   0. isolated from any install on this machine, and from its ports
#   1. the UI staged from this working tree AND served by this agent
#   2. the fleet, one passphrase, the agent enrolled
#   3. `NodeIdentity.time` is on the wire, and agrees with this host
#   4. the six reads the poll makes all answer on a healthy install
#   5. vLLM is `manual` / `installable: false` and is NOT an issue --
#      the exclusion, on a host that really reports it
#   6. a Library folder this host cannot open is reported as such
#   7. a runtime declared `gpuLayers: 0` on a machine WITH a card
#   8. a second runtime pinned to an older llama.cpp: a mixed fleet
#   9. BROWSER: the badge counts them, Home's card lists them, and
#      Inference carries the two states
#  10. the control root is restarted and comes back SEALED
#  11. BROWSER: a root that seals UNDER AN OPEN SESSION is opened from
#      the header, without leaving the page -- the slice's *Done when*.
#      A fresh sign-in cannot meet that state: since 2026-09-13 the login
#      page unlocks the root itself, so the first run of this script
#      found nothing to report because there was nothing left to report.
#  12. clock skew: NOT PRODUCIBLE on one box, and said so rather than faked
#  13. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped (install.ps1 sets the config-file var in the USER
# environment, so a throwaway agent would otherwise come up as the live
# worker and announce a dying port to the real control root -- that
# happened, 2026-09-12), ports are +100, teardown is by pid. Never
# `pkill -f eugene_plexus_`: this box is a worker node.
#
# **It reads the existing engine store and model directory, and writes to
# neither.** Runtimes are declared with an explicit `binary`, so the two
# builds under test are the ones named here rather than whatever
# `resolve_binary` would pick.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-issues}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
GW_PORT="${EP_GW_PORT:-8180}"
LIB_PORT="${EP_LIB_PORT:-8182}"
CTL_PORT="${EP_CTL_PORT:-8183}"
AGENT="http://127.0.0.1:$AGENT_PORT"
GW="http://127.0.0.1:$GW_PORT"
LIB="http://127.0.0.1:$LIB_PORT"
CTL="http://127.0.0.1:$CTL_PORT"
PASS="issues-$$"
OWNED_PORTS="$AGENT_PORT $GW_PORT $LIB_PORT $CTL_PORT"
SKIP_BUILD="${EP_SKIP_BUILD:-0}"

# Read, never written. A small GGUF and the two llama.cpp builds this box
# already has: the run needs a model that loads in seconds and two real
# engine versions, not a download.
MODELS_DIR="${EP_MODELS_DIR:-$HOME/.eugene-plexus/acceptance-models}"
MODEL="${EP_MODEL:-$MODELS_DIR/Qwen3-0.6B-Q4_K_M.gguf}"
ENGINE_ROOT="${EP_ENGINE_ROOT:-$HOME/.eugene-plexus/engines}"

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
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }
json_path() { win_path "$1" | sed 's|\\|\\\\|g'; }

A_PID=""
start_agent() {
  (exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" \
    EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 \
    EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
    EUGENE_PLEXUS_AGENT_ENGINE_ROOT="$(win_path "$ENGINE_ROOT")" \
    "$PY" -m eugene_plexus_agent --unattended >> agent.log 2>&1) &
  A_PID=$!
}
teardown() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 3; }
  for p in $OWNED_PORTS; do
    for pid in $(listening_pids "$p"); do
      taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
    done
  done
  # The companion drivers and the two llama-servers are children of the
  # agent and go with it; anything that outlived it is named by port
  # above. Never a name-matching kill on this box.
  rm -f "$UI_DIR/e2e/issues-live.spec.ts" 2>/dev/null
}

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
"$PY" -c "import eugene_plexus_agent, eugene_plexus_control, eugene_plexus_gateway, eugene_plexus_library, eugene_plexus_ui" 2>/dev/null \
  || { bad "the components and eugene_plexus_ui must import from $PY"; exit 1; }
[ -d "$UI_DIR/node_modules/@playwright" ] || { bad "no Playwright in $UI_DIR (npm install)"; exit 1; }
[ -f "$MODEL" ] || { bad "no model at $MODEL (set EP_MODEL)"; exit 1; }
BUILDS=$(ls -1 "$ENGINE_ROOT/llama_cpp" 2>/dev/null | sort)
NEW_BUILD=$(printf '%s\n' "$BUILDS" | tail -1)
OLD_BUILD=$(printf '%s\n' "$BUILDS" | head -1)
[ -n "$NEW_BUILD" ] && [ -f "$ENGINE_ROOT/llama_cpp/$NEW_BUILD/llama-server.exe" ] \
  || { bad "no llama.cpp build under $ENGINE_ROOT/llama_cpp (set EP_ENGINE_ROOT)"; exit 1; }
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
ok "agent python with five packages, Playwright, ports free; model $(basename "$MODEL"); llama.cpp builds: $(echo $BUILDS | tr '\n' ' ')"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

# --- 0 -----------------------------------------------------------------------
say "0. isolate this run"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
WORK_NATIVE=$(win_path "$WORK")
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
grep -qr 'issues-badge' "$STATIC/_next/static/chunks" 2>/dev/null \
  && ok "the staged bundle carries the Issues badge" \
  || bad "no issues-badge in the staged bundle -- the agent would serve a pre-S7 build"
grep -qr 'home-needs-attention' "$STATIC/_next/static/chunks" 2>/dev/null \
  && ok "the staged bundle carries Home's Needs attention card" \
  || bad "no home-needs-attention in the staged bundle"
# Staging is not serving (S3's fourth finding): four runs once asserted
# about a build no browser ever saw, because the agent venv held a WHEEL.
SERVED=$("$PY" -c "from eugene_plexus_ui import static_dir; print(static_dir())" 2>/dev/null | tr -d '\r')
SERVED_NORM=$(printf '%s' "$SERVED" | tr '\\' '/' | tr '[:upper:]' '[:lower:]')
STATIC_NORM=$(win_path "$STATIC" | tr '\\' '/' | tr '[:upper:]' '[:lower:]')
[ -n "$SERVED_NORM" ] && [ "$SERVED_NORM" = "$STATIC_NORM" ] \
  && ok "the agent venv's eugene_plexus_ui IS the staged directory (editable install)" \
  || { bad "the agent venv serves $SERVED, not $STATIC. Run: \"$PY\" -m pip install -e \"$UI_DIR\""; exit 1; }

MISSING_DIR="$WORK/not-mounted"
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
echo "logLevel: INFO" > control.yaml
echo "logLevel: INFO" > gateway.yaml
# Two Library folders: one this host can open, and one nothing ever
# mounted. The second is check 6's subject and is never created.
cat > library.yaml <<YAML
logLevel: INFO
modelRoots:
  - "$(win_path "$MODELS_DIR" | sed 's|\\|\\\\|g')"
  - "$(win_path "$MISSING_DIR" | sed 's|\\|\\\\|g')"
YAML

# --- 2 -----------------------------------------------------------------------
say "2. the fleet, one passphrase, the agent enrolled"
start_agent
wait_healthy "$AGENT" 60 || { bad "agent never answered"; tail -20 agent.log; exit 1; }
wait_healthy "$CTL" 90 && wait_healthy "$LIB" 60 && wait_healthy "$GW" 90 \
  || { bad "a child never came up"; tail -30 agent.log; exit 1; }
[ "$(code_of -X POST "$CTL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}")" = "204" ] || { bad "control initialize"; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "agent initialize"; exit 1; }
wait_healthy "$CTL" 90 || { bad "control did not come back after initialize"; exit 1; }
# The control host's own agent enrolls too (M9): unenrolled, it mints a
# fresh key per restart while the root mints the install's, so no browser
# session would reach the root at all -- a different failure from the one
# check 10 is about, and one that has confused a run before.
CTOK=$(curl -s -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
JOIN=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"issues-node"}' | jq_ "d['token']")
[ "$(code_of -X POST -H "Authorization: Bearer $TOK" "$AGENT/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$JOIN\",\"name\":\"issues-node\"}")" = "200" ] || { bad "enroll failed"; tail -20 agent.log; exit 1; }
wait_healthy "$CTL" 90 && wait_healthy "$AGENT" 60 || { bad "fleet did not return after enrollment"; exit 1; }
sleep 2
TOK=$(curl -s -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "no session after enrollment"; exit 1; }
AUTH=(-H "Authorization: Bearer $TOK")
[ "$(code_of "${AUTH[@]}" "$CTL/v1/nodes")" = "200" ] \
  && ok "agent $AGENT, control $CTL, library $LIB, gateway $GW; enrolled as issues-node" \
  || { bad "the root does not answer /v1/nodes after enrollment"; exit 1; }

# --- 3 -----------------------------------------------------------------------
say "3. a host says what time it thinks it is"
# The field S7's contract added, and the only input the clock rule has.
# Pinned in the UI's tests against a fixture; this is the first time a
# real agent has been asked for it.
NODE=$(curl -s "${AUTH[@]}" "$AGENT/v1/node")
NODE_TIME=$(printf '%s' "$NODE" | jq_ "d.get('time','')")
if [ -z "$NODE_TIME" ]; then
  bad "GET /v1/node carries no 'time' -- the clock rule has nothing to measure on a real install"
else
  DRIFT=$("$PY" -c "
import sys, datetime
t = datetime.datetime.fromisoformat(sys.argv[1].replace('Z', '+00:00'))
now = datetime.datetime.now(datetime.timezone.utc)
print(round(abs((t - now).total_seconds()), 3))
" "$NODE_TIME" 2>/dev/null | tr -d '\r')
  ok "GET /v1/node reports time=$NODE_TIME"
  # It is this host's own clock, so against this shell's it is noise.
  "$PY" -c "import sys; sys.exit(0 if float(sys.argv[1]) < 5 else 1)" "$DRIFT" 2>/dev/null \
    && ok "it agrees with this host's clock to ${DRIFT}s -- a console comparing two nodes has a real quantity" \
    || bad "the reported time is ${DRIFT}s from this shell's clock on the same machine"
fi
# The accelerator comes off the SAME body the on-CPU rule reads, so the
# run and the thing it measures cannot disagree about the subject.
HAS_GPU=$(printf '%s' "$NODE" | jq_ "'yes' if any(x.get('kind') != 'cpu' for x in d.get('devices',[])) else 'no'")
[ "$HAS_GPU" = "yes" ] \
  && ok "this host reports an accelerator, so check 7 is about a card going unused" \
  || note "no accelerator on this host: check 7 would be a state, not an issue"

# --- 4 -----------------------------------------------------------------------
say "4. the six reads the Issues poll makes"
POLL_OK=1
for probe in "gateway $GW/v1/admin/routing" "control $CTL/v1/nodes" "agent $AGENT/v1/node" \
             "runtimes $AGENT/v1/runtimes" "engines $AGENT/v1/engines"; do
  what=${probe%% *}; url=${probe#* }
  c=$(code_of "${AUTH[@]}" "$url")
  [ "$c" = "200" ] || { bad "$what: $url answered $c"; POLL_OK=0; }
done
FOLDERS=$(curl -s -X POST "${AUTH[@]}" "$AGENT/v1/library/folders/check" -H 'content-type: application/json' -d '{}')
printf '%s' "$FOLDERS" | grep -q 'libraryConsulted' || { bad "folders/check returned $(printf '%s' "$FOLDERS" | head -c 200)"; POLL_OK=0; }
[ "$POLL_OK" = "1" ] && ok "all six answer: routing, nodes, node, runtimes, engines, folders/check"

# --- 5 -----------------------------------------------------------------------
say "5. vLLM is uninstallable here, and is NOT an issue"
ENGINES=$(curl -s "${AUTH[@]}" "$AGENT/v1/engines")
VLLM=$(printf '%s' "$ENGINES" | jq_ "next((e for e in d['engines'] if e['engine']=='vllm'), None)" 2>/dev/null)
if [ "$VLLM" = "None" ] || [ -z "$VLLM" ]; then
  skip "this agent lists no vllm descriptor, so the exclusion cannot be exercised here"
else
  POLICY=$(printf '%s' "$ENGINES" | jq_ "next((e.get('acquisition',{}).get('policy') for e in d['engines'] if e['engine']=='vllm'), '')")
  INST=$(printf '%s' "$ENGINES" | jq_ "next((e.get('acquisition',{}).get('installable') for e in d['engines'] if e['engine']=='vllm'), None)")
  # The rule that would be permanently wrong if it counted this: vLLM's
  # unit of installation is a Python environment this project does not
  # own, so `installable` is false on EVERY host that will ever run.
  [ "$POLICY" = "manual" ] && [ "$INST" = "False" ] \
    && ok "vllm: policy=manual installable=False -- a real host reporting the case the rule must skip" \
    || bad "vllm reports policy=$POLICY installable=$INST; the exclusion is about manual/False"
fi
LLAMA_INSTALLED=$(printf '%s' "$ENGINES" | jq_ "next((e.get('version','') for e in d['engines'] if e['engine']=='llama_cpp'), '')")
[ -n "$LLAMA_INSTALLED" ] \
  && ok "llama.cpp reports installed version $LLAMA_INSTALLED" \
  || note "llama.cpp reports no version; check 8 compares the replicas with each other instead"

# --- 6 -----------------------------------------------------------------------
say "6. a Library folder this host cannot open"
REACH=$(curl -s -X POST "${AUTH[@]}" "$AGENT/v1/library/folders/check" -H 'content-type: application/json' -d '{}')
BADF=$(printf '%s' "$REACH" | jq_ "next((f for f in d.get('folders',[]) if not f.get('exists')), None)" 2>/dev/null)
if [ "$BADF" = "None" ] || [ -z "$BADF" ]; then
  bad "every folder exists; the missing one was meant to be $MISSING_DIR"
else
  PROB=$(printf '%s' "$REACH" | jq_ "next((f.get('problem','') for f in d.get('folders',[]) if not f.get('exists')), '')")
  GOODN=$(printf '%s' "$REACH" | jq_ "sum(1 for f in d.get('folders',[]) if f.get('exists'))")
  ok "one folder missing with a reason ('$(printf '%s' "$PROB" | head -c 70)'), $GOODN reachable -- the rule's inputs are real"
fi

# --- 7 -----------------------------------------------------------------------
say "7. a model told to use no card, on a machine that has one"
MODEL_J=$(json_path "$MODEL")
NEW_BIN=$(json_path "$ENGINE_ROOT/llama_cpp/$NEW_BUILD/llama-server.exe")
R=$(curl -s -w '\n%{http_code}' -X POST "${AUTH[@]}" "$AGENT/v1/runtimes" -H 'content-type: application/json' -d "{
  \"name\": \"on-cpu\", \"engine\": \"llama_cpp\",
  \"modelPath\": \"$MODEL_J\", \"modelAlias\": \"qwen3-cpu\",
  \"binary\": \"$NEW_BIN\",
  \"flags\": {\"contextSize\": 2048, \"gpuLayers\": 0, \"parallelSlots\": 1}}")
CODE=$(echo "$R" | tail -1)
[ "$CODE" = "201" ] || { bad "declaring the on-CPU runtime returned $CODE: $(echo "$R" | sed '$d' | head -c 300)"; }
for _ in $(seq 1 120); do
  S=$(curl -s -m 3 "${AUTH[@]}" "$AGENT/v1/runtimes" | jq_ "next((r['status'] for r in d['runtimes'] if r['name']=='on-cpu'), '')" 2>/dev/null)
  case "$S" in ready) break ;; crashed|exited) break ;; esac
  sleep 1
done
RT=$(curl -s "${AUTH[@]}" "$AGENT/v1/runtimes")
GPUL=$(printf '%s' "$RT" | jq_ "next((r.get('flags',{}).get('gpuLayers') for r in d['runtimes'] if r['name']=='on-cpu'), 'absent')")
if [ "$S" = "ready" ] && [ "$GPUL" = "0" ] && [ "$HAS_GPU" = "yes" ]; then
  ok "on-cpu is ready with gpuLayers=0 on a machine with an accelerator -- the issue's exact shape"
else
  bad "on-cpu status=$S gpuLayers=$GPUL accelerator=$HAS_GPU"
  printf '%s' "$RT" | jq_ "[r.get('lastError') for r in d['runtimes']]" 2>/dev/null
fi

# --- 8 -----------------------------------------------------------------------
say "8. two engine builds serving at once"
if [ "$OLD_BUILD" = "$NEW_BUILD" ]; then
  skip "only one llama.cpp build under $ENGINE_ROOT; a mixed fleet needs two"
else
  OLD_BIN=$(json_path "$ENGINE_ROOT/llama_cpp/$OLD_BUILD/llama-server.exe")
  R=$(curl -s -w '\n%{http_code}' -X POST "${AUTH[@]}" "$AGENT/v1/runtimes" -H 'content-type: application/json' -d "{
    \"name\": \"old-build\", \"engine\": \"llama_cpp\",
    \"modelPath\": \"$MODEL_J\", \"modelAlias\": \"qwen3-old\",
    \"binary\": \"$OLD_BIN\",
    \"flags\": {\"contextSize\": 2048, \"gpuLayers\": 99, \"parallelSlots\": 1}}")
  [ "$(echo "$R" | tail -1)" = "201" ] || bad "declaring the old-build runtime returned $(echo "$R" | tail -1)"
  for _ in $(seq 1 120); do
    S2=$(curl -s -m 3 "${AUTH[@]}" "$AGENT/v1/runtimes" | jq_ "next((r['status'] for r in d['runtimes'] if r['name']=='old-build'), '')" 2>/dev/null)
    case "$S2" in ready|crashed|exited) break ;; esac
    sleep 1
  done
  RT=$(curl -s "${AUTH[@]}" "$AGENT/v1/runtimes")
  V_OLD=$(printf '%s' "$RT" | jq_ "next((r.get('engineVersion','') for r in d['runtimes'] if r['name']=='old-build'), '')")
  V_NEW=$(printf '%s' "$RT" | jq_ "next((r.get('engineVersion','') for r in d['runtimes'] if r['name']=='on-cpu'), '')")
  # Nothing detected this before S7: installing a build never touches a
  # running engine, and `resolve_binary` runs at spawn, so an upgrade
  # with two replicas serving leaves the gateway balancing across two
  # versions silently.
  if [ -n "$V_OLD" ] && [ -n "$V_NEW" ] && [ "$V_OLD" != "$V_NEW" ]; then
    ok "two runtimes serving on different builds: on-cpu=$V_NEW old-build=$V_OLD"
  else
    bad "expected two different engineVersions, got on-cpu='$V_NEW' old-build='$V_OLD' (status $S2)"
  fi
fi

# --- 9 -----------------------------------------------------------------------
say "9. the browser: the badge, Home's card, and Inference's two states"
write_spec() {
cat > "$UI_DIR/e2e/issues-live.spec.ts" <<'SPEC'
import { expect, test } from "@playwright/test";

const BASE = process.env.EP_BASE ?? "http://127.0.0.1:8179";
const PASS = process.env.EP_PASS ?? "";
const PHASE = process.env.EP_PHASE ?? "healthy";

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

test.skip(PHASE !== "healthy", "phase");

test("the badge counts what is wrong, and Home lists it", async ({ page }) => {
  await signIn(page);
  await page.goto(BASE);

  const badge = page.getByTestId("issues-badge");
  await badge.waitFor({ state: "visible", timeout: 60000 });
  await badge.click();
  const popover = page.getByTestId("issues-popover");
  await popover.waitFor({ state: "visible" });
  const kinds = await popover.locator("[data-issue-kind]").evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-issue-kind")),
  );
  // Three real ones, produced by this install rather than by a fixture.
  expect(kinds).toContain("runtime-on-cpu");
  expect(kinds).toContain("folder-unreachable");
  expect(kinds).toContain("engine-build-stale");
  // And never the one the exclusion exists for.
  expect(kinds).not.toContain("engine-unavailable");
  await page.keyboard.press("Escape");

  const card = page.getByTestId("home-needs-attention");
  await card.waitFor({ state: "visible" });
  await expect(card).not.toContainText("Nothing.");
  await expect(card.locator("[data-issue-kind]").first()).toBeVisible();
});

test("Inference says a model is on the processor, and why", async ({ page }) => {
  await signIn(page);
  await page.goto(`${BASE}/inference`);
  const line = page.getByTestId("compute-detail").first();
  await line.waitFor({ state: "visible", timeout: 60000 });
  await expect(line).toContainText("on the processor");
  await expect(line).toContainText("no layers on the card");
  // `flags` lives on the node's own runtime record and on nothing the
  // control root serves, so this line existing is the per-node read.
  await expect(line).toHaveAttribute("title", /read from what it was started with/);
});
SPEC
}
write_spec
(cd "$UI_DIR" && EP_BASE="$AGENT" EP_PASS="$PASS" EP_PHASE=healthy npx playwright test e2e/issues-live.spec.ts --reporter=line > "$WORK/e2e-healthy.log" 2>&1)
PW=$?; echo "  $(grep -E 'passed|failed' "$WORK/e2e-healthy.log" | tail -1)"
[ "$PW" = "0" ] && ok "browser: the badge names all three, Home lists them, Inference explains the processor" \
  || { bad "browser (healthy) failed"; tail -40 "$WORK/e2e-healthy.log"; }

# --- 10 ----------------------------------------------------------------------
say "10. the control root comes back sealed"
curl -s -o /dev/null -X POST "${AUTH[@]}" "$AGENT/v1/components/control/restart" -d '{}'
sleep 3; wait_healthy "$CTL" 90 || { bad "control did not come back"; exit 1; }
R=$(curl -s -w '\n%{http_code}' "${AUTH[@]}" "$CTL/v1/nodes"); CODE=$(echo "$R" | tail -1); BODY=$(echo "$R" | sed '$d')
if [ "$CODE" = "503" ] && printf '%s' "$BODY" | grep -q '"Locked"'; then
  # Every health check says ok while nothing routes: the state this whole
  # list exists for, and one this install has produced for real.
  ok "503 Locked on /v1/nodes while its own /healthz says '$(curl -s "$CTL/healthz" | jq_ "d['status']")'"
else
  bad "expected 503 Locked, got $CODE $(printf '%s' "$BODY" | head -c 200)"; exit 1
fi
# Put it back, because the browser check below has to meet this state
# from an ALREADY-OPEN session and cannot get one past a locked root by
# signing in -- see the note on check 11.
curl -s -o /dev/null -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}"
[ "$(code_of "${AUTH[@]}" "$CTL/v1/nodes")" = "200" ] || { bad "could not reopen the root for check 11"; exit 1; }

# --- 11 ----------------------------------------------------------------------
say "11. the browser: an already-open session meets a sealed root"
# **A fresh sign-in cannot meet this state.** Since 2026-09-13 the login
# page posts the passphrase to the control root as well as the agent, so
# signing in UNLOCKS it -- the first run of this script sealed the root,
# signed in, and found nothing to report, because there was nothing left
# to report. The case the badge exists for is the other one, and it is
# the one the live install produced: a person already signed in when the
# root came back sealed under them. CLAUDE.md recorded it as still open
# ("an already-open browser session still does not unlock it -- sign out
# and in"); this is what closes it.
#
# So the seal happens INSIDE the test, from the page, with the session
# the browser already holds.
cat > "$UI_DIR/e2e/issues-live.spec.ts" <<'SPEC'
import { expect, test } from "@playwright/test";

const BASE = process.env.EP_BASE ?? "http://127.0.0.1:8179";
const PASS = process.env.EP_PASS ?? "";

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

// THE SLICE'S *DONE WHEN*: "a sealed root shows as one issue with the
// unlock as its action, from any page". So this sits on a page that is
// neither Home nor /nodes, and never navigates.
test("from any page, the header opens a root that sealed under you", async ({ page }) => {
  await signIn(page);
  await page.goto(`${BASE}/library`);
  await page.getByTestId("issues-badge").waitFor({ state: "visible", timeout: 60000 });

  // Restart the root from inside the page, with the browser's own
  // session -- the same call the Config screen makes. It comes back
  // sealed, under a session that is still perfectly valid.
  const status = await page.evaluate(async () => {
    const token = sessionStorage.getItem("eugene-session-token");
    const r = await fetch("/api/proxy/agent/v1/components/control/restart", {
      method: "POST",
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
      body: "{}",
    });
    return r.status;
  });
  expect(status).toBeLessThan(400);

  const badge = page.getByTestId("issues-badge");
  await expect(badge).toHaveAttribute("data-severity", "blocking", { timeout: 90000 });
  await badge.click();

  const popover = page.getByTestId("issues-popover");
  const sealed = popover.locator('[data-issue-kind="control-sealed"]');
  await sealed.waitFor({ state: "visible", timeout: 90000 });
  await expect(sealed).toContainText("locked");
  // The fix is here. A link to /nodes would be a door that is shut.
  await expect(sealed.getByRole("link", { name: "Go and fix it" })).toHaveCount(0);

  await sealed.getByTestId("issues-unlock-passphrase").fill(PASS);
  await sealed.getByTestId("issues-unlock-submit").click();

  // The list is pulled forward, so the row goes rather than sitting there
  // for the rest of the poll interval.
  await expect(page.locator('[data-issue-kind="control-sealed"]')).toHaveCount(0, {
    timeout: 90000,
  });
  // And we never left the page we were on.
  expect(new URL(page.url()).pathname.replace(/\/$/, "")).toBe("/library");
});
SPEC
(cd "$UI_DIR" && EP_BASE="$AGENT" EP_PASS="$PASS" npx playwright test e2e/issues-live.spec.ts --reporter=line > "$WORK/e2e-sealed.log" 2>&1)
PW=$?; echo "  $(grep -E 'passed|failed' "$WORK/e2e-sealed.log" | tail -1)"
[ "$PW" = "0" ] && ok "browser: a root that sealed under an open session was opened from /library, without leaving it"   || { bad "browser (sealed) failed"; tail -40 "$WORK/e2e-sealed.log"; }
wait_healthy "$CTL" 90
[ "$(code_of "${AUTH[@]}" "$CTL/v1/nodes")" = "200" ]   && ok "confirmed from the shell: the root is unlocked"   || bad "the root is still sealed after the browser said it unlocked it"

say "12. clock skew"
# Not producible here, and faking it would be worse than not running it.
# The rule compares two HOSTS, and this box has one clock; moving the
# system clock to manufacture a second one would change the clock every
# other process on this machine is using, including the live worker
# install's, whose tokens would then be refused by a control root two
# hundred miles of network away. Two machines with independent clocks is
# the instrument, and this is not it.
skip "NOT PRODUCED: one box has one clock, and the rule compares two hosts"
note "to produce it: two enrolled machines, one with its time service stopped and set 60s ahead"

# --- 13 ----------------------------------------------------------------------
say "13. teardown by pid"
teardown; A_PID=""
LEFT=""; for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && LEFT="$LEFT $p"; done
[ -z "$LEFT" ] && ok "no owned port still listening" || bad "still listening:$LEFT"

say "done"
if [ "$FAILURES" -eq 0 ]; then printf '\nALL CHECKS PASSED\n'; else printf '\n%s CHECK(S) FAILED\n' "$FAILURES"; exit 1; fi
