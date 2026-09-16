#!/usr/bin/env bash
# "Download and run" as ONE action, and as one that survives the tab
# (hobbyist UX plan §6.3, closed 2026-09-16).
#
# Design: docs/design/hobbyist-ux.md §6.3 and §11.8. What this replaces
# is what S6 shipped a few hours earlier: Home offered **Download**, S3's
# **Run** took its place when the file landed, so the person was asked
# twice and the second ask arrived minutes later -- when a
# multi-gigabyte download finishes and they may have walked away.
#
# The checks:
#   0. isolated from any install on this machine, and from any engine it has
#   1. the UI wheel staged from this working tree
#   2. agent + control + gateway + library up, initialized, the agent enrolled
#   3. a FRESH BOX: no models, no llama.cpp, and a one-entry starter list
#      naming a small real model (what `starterModelsFile` is for)
#   4. BROWSER: one click on Home -> the engine question -> ONE tray entry
#      -> a running model -> a first reply
#   5. API: the download carried the intent, and the intent was taken down
#   6. THE CLOSED LAPTOP: the runtime and profile removed, a download
#      started through the API with the intent set and left to finish with
#      NO browser open; then a fresh browser opens Home and the model runs
#      with nobody clicking
#   7. API: exactly one claim wins, and a second gets nothing
#   8. teardown by pid
#
# Safe beside a live install: environment cleared, +100 ports, an engine
# root of its own, teardown by pid. Never `pkill -f eugene_plexus_`.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-download-and-run}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"; CTL_PORT="${EP_CTL_PORT:-8183}"
GW_PORT="${EP_GW_PORT:-8180}"; LIB_PORT="${EP_LIB_PORT:-8182}"
AGENT="http://127.0.0.1:$AGENT_PORT"; CTL="http://127.0.0.1:$CTL_PORT"
GW="http://127.0.0.1:$GW_PORT"; LIB="http://127.0.0.1:$LIB_PORT"
PASS="chain-accept-$$"
OWNED_PORTS="$AGENT_PORT $CTL_PORT $GW_PORT $LIB_PORT"
SKIP_BUILD="${EP_SKIP_BUILD:-0}"
EP_REPO="${EP_REPO:-unsloth/Qwen3-0.6B-GGUF}"
EP_FILE="${EP_FILE:-Qwen3-0.6B-Q4_K_M.gguf}"
EP_RUN_BUDGET_MS="${EP_RUN_BUDGET_MS:-900000}"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
A_PID=""; TOK=""; RUNTIME=""
teardown() {
  if [ -n "$TOK" ] && [ -n "$RUNTIME" ]; then
    curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $TOK" "$AGENT/v1/runtimes/$RUNTIME" || true
    sleep 2
  fi
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 3; }
  for p in $OWNED_PORTS; do for pid in $(listening_pids "$p"); do taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null; done; done
}

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
command -v llama-server >/dev/null 2>&1 && { bad "llama-server is on PATH; this run needs a host that has none"; exit 1; }
ok "agent python; every port free; no llama-server on PATH"
rm -rf "$WORK"; mkdir -p "$WORK/models" "$WORK/engines"; cd "$WORK" || exit 1
trap teardown EXIT

say "0. isolate"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
WORK_NATIVE=$(cygpath -w "$WORK" 2>/dev/null || printf '%s' "$WORK")
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }

say "1. stage this working tree's UI into the wheel the agent serves"
if [ "$SKIP_BUILD" = "1" ]; then
  ok "skipped by EP_SKIP_BUILD=1 (asserting about the already-staged build)"
else
  (cd "$UI_DIR" && npm run build:python > "$WORK/build.log" 2>&1)
  [ $? = 0 ] && ok "npm run build:python staged the export" || { bad "build failed"; tail -30 "$WORK/build.log"; exit 1; }
fi
STATIC="$UI_DIR/python/eugene_plexus_ui/static"
SERVED=$("$PY" -c "from eugene_plexus_ui import static_dir; print(static_dir())" 2>/dev/null | tr -d '\r')
SERVED_NORM=$(printf '%s' "$SERVED" | tr '\\' '/' | tr '[:upper:]' '[:lower:]')
STATIC_NORM=$(cygpath -w "$STATIC" 2>/dev/null | tr '\\' '/' | tr '[:upper:]' '[:lower:]')
[ "$SERVED_NORM" = "$STATIC_NORM" ] && ok "the agent venv's eugene_plexus_ui IS the staged directory" \
  || { bad "the agent venv serves $SERVED, not $STATIC"; exit 1; }

# A one-entry starter list naming a small real model. This is exactly
# what `starterModelsFile` exists for, and it keeps the run to a 400 MB
# download instead of the shipped list's smallest at 2.7 GB.
cat > starter.yaml <<YAML
reviewed: $(date -u +%Y-%m-%d)
engine: llama_cpp acceptance
classes:
  - class: 4B
    baseModel: Qwen/Qwen3-0.6B
    repo: $EP_REPO
    why: a small real model, for this acceptance run only
    license: apache-2.0
    parameters: 596049920
    architecture: qwen3
    contextLength: 40960
    recommended:
      file: $EP_FILE
      label: Q4_K_M
      sizeBytes: 397809632
    shape:
      blockCount: 28
      attentionLayers: 28
      headCountKv: 8
      keyLength: 128
      valueLength: 128
YAML

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
printf 'logLevel: INFO\nmodelRoots:\n  - %s\nstarterModelsFile: %s\n' \
  "$WORK_NATIVE\\models" "$WORK_NATIVE\\starter.yaml" > library.yaml

say "2. four processes, one passphrase, the agent enrolled"
(exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
  EUGENE_PLEXUS_AGENT_ENGINE_ROOT="$WORK_NATIVE/engines" \
  "$PY" -m eugene_plexus_agent --unattended > agent.log 2>&1) &
A_PID=$!
wait_healthy "$AGENT" 60 && wait_healthy "$CTL" 90 || { bad "agent/control never came up"; tail -20 agent.log; exit 1; }
[ "$(code_of -X POST "$CTL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}")" = "204" ] || { bad "control initialize"; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "agent initialize"; exit 1; }
wait_healthy "$CTL" 90 || { bad "control did not come back"; exit 1; }
CTOK=$(curl -s -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
JOIN=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"chain-node"}' | jq_ "d['token']")
[ "$(code_of -X POST -H "Authorization: Bearer $TOK" "$AGENT/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$JOIN\",\"name\":\"chain-node\"}")" = "200" ] || { bad "enroll failed"; tail -20 agent.log; exit 1; }
wait_healthy "$CTL" 90 && wait_healthy "$AGENT" 60 && wait_healthy "$LIB" 60 && wait_healthy "$GW" 60 || { bad "fleet did not come back"; exit 1; }
sleep 2
TOK=$(curl -s -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
AUTH=(-H "Authorization: Bearer $TOK")
[ "$(code_of "${AUTH[@]}" "$CTL/v1/nodes")" = "200" ] && ok "four processes; enrolled; the session reaches the root" || bad "root not answering"

say "3. a fresh box, and a one-entry starter list"
[ "$(curl -s "${AUTH[@]}" "$LIB/v1/models" | jq_ "len([m for m in d['models'] if m['status']=='present'])")" = "0" ] \
  && ok "no models on disk" || bad "this box is not fresh"
ENG=$(curl -s "${AUTH[@]}" "$AGENT/v1/engines")
[ "$(echo "$ENG" | jq_ "[e for e in d['engines'] if e['engine']=='llama_cpp'][0]['available']")" = "False" ] \
  && ok "llama.cpp is not installed here, so the question will be asked" || bad "llama.cpp is already available"
SET=$(curl -s "${AUTH[@]}" "$LIB/v1/catalogue/starter")
[ "$(echo "$SET" | jq_ "d['source']")" = "configured" ] && [ "$(echo "$SET" | jq_ "len(d['models'])")" = "1" ] \
  && ok "the starter list is this run's own: $(echo "$SET" | jq_ "d['models'][0]['baseModel']") $(echo "$SET" | jq_ "d['models'][0]['label']")" \
  || { bad "starter list: $(echo "$SET" | head -c 300)"; exit 1; }

say "4. the browser: one click from Home to a running model"
(cd "$UI_DIR" && EP_UI_URL="$AGENT" EP_PASSPHRASE="$PASS" EP_RUN_BUDGET_MS="$EP_RUN_BUDGET_MS" \
  npx playwright test e2e/download-and-run.spec.ts > "$WORK/pw1.log" 2>&1)
PW=$?
sed -n '/Running/,$p' "$WORK/pw1.log" | grep -E '^\s+(ok|x|-|[✓✘×])\s+[0-9]|passed|failed|skipped' | head -10
if grep -E "^\s+(ok|✓)\s+[0-9]+ .*one click on Home gets the model and runs it" "$WORK/pw1.log" >/dev/null; then
  ok "browser: one click on Home gets the model and runs it -- the engine question, ONE tray entry, a first reply"
else
  bad "the chain spec did not pass"; tail -60 "$WORK/pw1.log"
fi

say "5. what the components hold: the intent was carried, and taken down"
DL=$(curl -s "${AUTH[@]}" "$LIB/v1/downloads")
COUNT=$(echo "$DL" | jq_ "len(d['downloads'])")
[ "$COUNT" = "1" ] && ok "exactly one download: the chain did not start a second" || bad "downloads: $COUNT"
D_ID=$(echo "$DL" | jq_ "d['downloads'][0]['id']")
[ "$(echo "$DL" | jq_ "d['downloads'][0]['state']")" = "done" ] && ok "it finished" || bad "state: $(echo "$DL" | jq_ "d['downloads'][0]['state']")"
# The flag is DOWN, which is the half that stops a console opening
# tomorrow from launching this model a second time.
[ "$(echo "$DL" | jq_ "d['downloads'][0].get('runWhenReady')")" = "False" ] \
  && ok "runWhenReady is down: the browser that ran it claimed it" || bad "runWhenReady: $(echo "$DL" | jq_ "d['downloads'][0].get('runWhenReady')")"
MODEL_ID=$(echo "$DL" | jq_ "d['downloads'][0].get('modelId','')")
[ -n "$MODEL_ID" ] && ok "the record names the model it produced ($MODEL_ID)" || bad "no modelId"
RTS=$(curl -s "${AUTH[@]}" "$AGENT/v1/runtimes")
RUNTIME=$(echo "$RTS" | jq_ "d['runtimes'][0]['name'] if d['runtimes'] else ''")
[ "$(echo "$RTS" | jq_ "len(d['runtimes'])")" = "1" ] && ok "exactly one runtime: $RUNTIME" || bad "runtimes: $(echo "$RTS" | head -c 300)"
[ "$(echo "$RTS" | jq_ "d['runtimes'][0]['status']")" = "ready" ] && ok "and it is ready" || bad "status: $(echo "$RTS" | jq_ "d['runtimes'][0]['status']")"
[ "$(curl -s "${AUTH[@]}" "$LIB/v1/models/$MODEL_ID/profiles" | jq_ "d['profiles'][0]['name']")" = "default" ] \
  && ok "one profile named default, made by the chain" || bad "no default profile"
[ "$(echo "$ENG" | jq_ "1")" = "1" ] && ENG2=$(curl -s "${AUTH[@]}" "$AGENT/v1/engines")
[ "$(echo "$ENG2" | jq_ "[e for e in d['engines'] if e['engine']=='llama_cpp'][0]['available']")" = "True" ] \
  && ok "llama.cpp was installed inside the chain: $(echo "$ENG2" | jq_ "[e for e in d['engines'] if e['engine']=='llama_cpp'][0].get('version','?')")" \
  || bad "llama.cpp still not available"

say "6. the closed laptop: a finished download picks itself up"
# Take the install back to "the file is here, nothing runs it", then
# start a download that carries the intent and let it finish with NO
# browser anywhere. The state a person leaves behind when they shut the
# laptop lid mid-transfer.
curl -s -o /dev/null -X DELETE "${AUTH[@]}" "$AGENT/v1/runtimes/$RUNTIME"; RUNTIME=""
sleep 3
PROFILE_ID=$(curl -s "${AUTH[@]}" "$LIB/v1/models/$MODEL_ID/profiles" | jq_ "d['profiles'][0]['id']")
curl -s -o /dev/null -X DELETE "${AUTH[@]}" "$LIB/v1/models/$MODEL_ID/profiles/$PROFILE_ID"
curl -s -o /dev/null -X DELETE "${AUTH[@]}" "$LIB/v1/downloads/$D_ID"
[ "$(curl -s "${AUTH[@]}" "$AGENT/v1/runtimes" | jq_ "len(d['runtimes'])")" = "0" ] \
  && ok "back to nothing running, and no profile" || bad "the runtime did not go away"
NEW=$(curl -s -X POST "${AUTH[@]}" -H 'content-type: application/json' "$LIB/v1/downloads" \
  -d "{\"repo\":\"$EP_REPO\",\"files\":[\"$EP_FILE\"],\"runWhenReady\":true}")
N_ID=$(echo "$NEW" | jq_ "d['id']")
[ "$(echo "$NEW" | jq_ "d.get('runWhenReady')")" = "True" ] && ok "a download started with the intent set, and no browser open" || bad "the record did not carry the intent"
STATE=""
for _ in $(seq 1 300); do
  STATE=$(curl -s "${AUTH[@]}" "$LIB/v1/downloads/$N_ID" | jq_ "d['state']")
  case "$STATE" in done|failed|cancelled) break;; esac
  sleep 2
done
[ "$STATE" = "done" ] && ok "it finished with nobody watching" || { bad "download ended $STATE"; }
for _ in $(seq 1 60); do
  MODEL_ID=$(curl -s "${AUTH[@]}" "$LIB/v1/downloads/$N_ID" | jq_ "d.get('modelId') or ''")
  [ -n "$MODEL_ID" ] && break; sleep 1
done
[ -n "$MODEL_ID" ] && ok "and the library catalogued it ($MODEL_ID)" || bad "no modelId on the finished download"
[ "$(curl -s "${AUTH[@]}" "$LIB/v1/downloads/$N_ID" | jq_ "d.get('runWhenReady')")" = "True" ] \
  && ok "the intent is still on the record, waiting for a console" || bad "the intent went missing"

(cd "$UI_DIR" && EP_UI_URL="$AGENT" EP_PASSPHRASE="$PASS" EP_RUN_BUDGET_MS="$EP_RUN_BUDGET_MS" EP_RESUME_ONLY=1 \
  npx playwright test e2e/download-and-run.spec.ts > "$WORK/pw2.log" 2>&1)
sed -n '/Running/,$p' "$WORK/pw2.log" | grep -E '^\s+(ok|x|-|[✓✘×])\s+[0-9]|passed|failed|skipped' | head -10
if grep -E "^\s+(ok|✓)\s+[0-9]+ .*picks itself up in a browser that never saw it" "$WORK/pw2.log" >/dev/null; then
  ok "browser: a fresh console ran it with nobody clicking"
else
  bad "the resumption spec did not pass"; tail -60 "$WORK/pw2.log"
fi
RTS=$(curl -s "${AUTH[@]}" "$AGENT/v1/runtimes")
RUNTIME=$(echo "$RTS" | jq_ "d['runtimes'][0]['name'] if d['runtimes'] else ''")
[ -n "$RUNTIME" ] && ok "a runtime exists that no human asked for in this browser: $RUNTIME" || bad "nothing was started"
[ "$(curl -s "${AUTH[@]}" "$LIB/v1/downloads/$N_ID" | jq_ "d.get('runWhenReady')")" = "False" ] \
  && ok "and the intent came down when it was claimed" || bad "the intent is still set after a resume"

say "7. exactly one claim wins"
C1=$(curl -s -X POST "${AUTH[@]}" "$LIB/v1/downloads/$N_ID/claim" | jq_ "d['claimed']")
[ "$C1" = "False" ] && ok "a claim after the winner gets nothing" || bad "a second claim returned $C1"
FRESH=$(curl -s -X POST "${AUTH[@]}" -H 'content-type: application/json' "$LIB/v1/downloads" \
  -d "{\"repo\":\"$EP_REPO\",\"files\":[\"$EP_FILE\"],\"runWhenReady\":true}" | jq_ "d['id']")
A=$(curl -s -X POST "${AUTH[@]}" "$LIB/v1/downloads/$FRESH/claim" | jq_ "d['claimed']")
B=$(curl -s -X POST "${AUTH[@]}" "$LIB/v1/downloads/$FRESH/claim" | jq_ "d['claimed']")
[ "$A" = "True" ] && [ "$B" = "False" ] && ok "first caller True, second False -- two consoles cannot both launch" || bad "claims: $A then $B"
[ "$(code_of -X POST "${AUTH[@]}" "$LIB/v1/downloads/nosuchthing/claim")" = "404" ] \
  && ok "claiming a download that does not exist is a 404" || bad "unknown claim did not 404"
curl -s -o /dev/null -X DELETE "${AUTH[@]}" "$LIB/v1/downloads/$FRESH"

say "result"
if [ "$FAILURES" = "0" ]; then printf '  ALL CHECKS PASSED\n'; else printf '  %d CHECK(S) FAILED\n' "$FAILURES"; fi
exit "$FAILURES"
