#!/usr/bin/env bash
# One-click run: a model on disk to `ready` with one button and one
# question, on a fresh box (hobbyist UX plan, S3 — decisions #5 and #6).
#
# Design: docs/design/hobbyist-ux.md §7 S3, §6.3; record §11.4. Its §0.5
# measured what this replaces: an engine "installed from the Inference
# page" four clicks away, a profile the person does not have, and a load
# watched on a screen nobody said to open.
#
# The checks:
#   0. isolated from any install on this machine, and from any engine it has
#   1. the UI wheel staged from this working tree, so the agent serves THIS build
#   2. agent + control + gateway + library up, initialized, the agent enrolled
#   3. a FRESH BOX: llama.cpp is not installed here and can be
#   4. one model on disk, fetched through the library (or copied from EP_LOCAL_GGUF)
#   5. BROWSER: Home offers to run the one model; a finished download offers Run
#   6. BROWSER: Run → the one question → Skip → stopped on Inference, with the reason
#   7. BROWSER: Run → Install → llama.cpp fetched for real → the same runtime → ready
#   8. BROWSER: the first reply lands on Home
#   9. API: one profile named `default`; the engine installed; the model routable;
#      a completion through the gateway
#  10. teardown: the runtime removed through the API, then the fleet by pid
#
# Safe beside a live install: environment cleared, +100 ports, an engine
# root of its own (so the live install's llama.cpp is neither found nor
# touched), teardown by pid. Never `pkill -f eugene_plexus_`, never kill
# llama-server by name — the live worker is serving one.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-one-click-run}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"; CTL_PORT="${EP_CTL_PORT:-8183}"
GW_PORT="${EP_GW_PORT:-8180}"; LIB_PORT="${EP_LIB_PORT:-8182}"
AGENT="http://127.0.0.1:$AGENT_PORT"; CTL="http://127.0.0.1:$CTL_PORT"
GW="http://127.0.0.1:$GW_PORT"; LIB="http://127.0.0.1:$LIB_PORT"
PASS="run-acceptance-$$"
OWNED_PORTS="$AGENT_PORT $CTL_PORT $GW_PORT $LIB_PORT"
SKIP_BUILD="${EP_SKIP_BUILD:-0}"
# The model: a small real chat GGUF from the hub, or a local file copied in.
EP_REPO="${EP_REPO:-unsloth/Qwen3-0.6B-GGUF}"
EP_FILE="${EP_FILE:-Qwen3-0.6B-Q4_K_M.gguf}"
EP_LOCAL_GGUF="${EP_LOCAL_GGUF:-}"
# Whether the model arrived by download (the finished-download row is a
# browser check only then). Set below.
DOWNLOADED=0
# A real llama.cpp install plus a model load, in the browser's budget.
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
  # The runtime first, through the API: the agent stops its engine and
  # forgets the companion. Then the fleet by pid.
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
# The fresh box is made by pointing the engine root at an empty directory;
# a llama-server on PATH would still be found (discovery's last resort)
# and the Install path could not be exercised.
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
grep -qr 'run-dialog' "$STATIC/_next/static/chunks" 2>/dev/null \
  && ok "the staged bundle carries the run dialog" \
  || bad "no run-dialog in the staged bundle -- the agent would serve a pre-S3 build"
# Staging is not serving. The agent serves whatever `eugene_plexus_ui`
# resolves to in ITS venv, and on 2026-09-15 that was a wheel installed
# from ui/dist six hours earlier -- four runs asserted about a build no
# browser ever saw, while this check, which read the staged directory,
# passed every time. So: the package the agent imports must BE the
# staged directory (an editable install), and step 2 re-reads the served
# page for the same marker.
SERVED=$("$PY" -c "from eugene_plexus_ui import static_dir; print(static_dir())" 2>/dev/null | tr -d '\r')
SERVED_NORM=$(printf '%s' "$SERVED" | tr '\\' '/' | tr '[:upper:]' '[:lower:]')
STATIC_NORM=$(cygpath -w "$STATIC" 2>/dev/null | tr '\\' '/' | tr '[:upper:]' '[:lower:]')
[ -n "$SERVED_NORM" ] && [ "$SERVED_NORM" = "$STATIC_NORM" ] \
  && ok "the agent venv's eugene_plexus_ui IS the staged directory (editable install)" \
  || { bad "the agent venv serves $SERVED, not the staged $STATIC. Install the UI editable into the agent venv: \"$PY\" -m pip install -e \"$UI_DIR\" (or uv pip install --python \"$PY\" -e \"$UI_DIR\")"; exit 1; }

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
printf 'logLevel: INFO\nmodelRoots:\n  - %s\n' "$WORK_NATIVE\\models" > library.yaml

say "2. four processes, one passphrase, the agent enrolled"
# EUGENE_PLEXUS_AGENT_ENGINE_ROOT: managed builds go under the work dir,
# so this agent finds no llama.cpp (the fresh box) and the one it fetches
# never lands beside the live install's.
(exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
  EUGENE_PLEXUS_AGENT_ENGINE_ROOT="$WORK_NATIVE/engines" \
  "$PY" -m eugene_plexus_agent --unattended > agent.log 2>&1) &
A_PID=$!
wait_healthy "$AGENT" 60 && wait_healthy "$CTL" 90 || { bad "agent/control never came up"; tail -20 agent.log; exit 1; }
[ "$(code_of -X POST "$CTL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}")" = "204" ] || { bad "control initialize"; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "agent initialize"; exit 1; }
wait_healthy "$CTL" 90 || { bad "control did not come back after initialize"; exit 1; }
CTOK=$(curl -s -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
JOIN=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"run-node"}' | jq_ "d['token']")
[ "$(code_of -X POST -H "Authorization: Bearer $TOK" "$AGENT/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$JOIN\",\"name\":\"run-node\"}")" = "200" ] || { bad "enroll failed"; tail -20 agent.log; exit 1; }
wait_healthy "$CTL" 90 && wait_healthy "$AGENT" 60 && wait_healthy "$LIB" 60 && wait_healthy "$GW" 60 || { bad "fleet did not come back after enrollment"; exit 1; }
sleep 2
TOK=$(curl -s -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "no session after enrollment"; exit 1; }
AUTH=(-H "Authorization: Bearer $TOK")
[ "$(code_of "${AUTH[@]}" "$CTL/v1/nodes")" = "200" ] && ok "four processes; enrolled; the session reaches the root" || bad "root not answering"
# What the browser will actually load: the page the agent serves at /,
# and the chunks it names. The marker must be in one of THOSE.
SERVED_CHUNKS=$(curl -s "$AGENT/" | grep -o '_next/static/chunks/[^"]*\.js' | sort -u)
FOUND=0
for c in $SERVED_CHUNKS; do curl -s "$AGENT/$c" | grep -q 'run-dialog' && FOUND=1 && break; done
[ "$FOUND" = "1" ] && ok "the agent SERVES a bundle with the run dialog ($(echo "$SERVED_CHUNKS" | wc -l | tr -d ' ') chunks)" \
  || { bad "the agent serves a bundle without the run dialog -- the browser would test a pre-S3 build"; exit 1; }

say "3. a fresh box: llama.cpp is not installed here, and can be"
ENG=$(curl -s "${AUTH[@]}" "$AGENT/v1/engines")
AVAIL=$(echo "$ENG" | jq_ "[e for e in d['engines'] if e['engine']=='llama_cpp'][0]['available']")
INST=$(echo "$ENG" | jq_ "[e for e in d['engines'] if e['engine']=='llama_cpp'][0]['acquisition']['installable']")
[ "$AVAIL" = "False" ] && ok "llama.cpp: available=false (the engine root is this run's own, empty)" || { bad "llama.cpp reads available=$AVAIL -- not a fresh box; is PATH or a configured binary leaking in?"; echo "$ENG" | head -c 600; }
[ "$INST" = "True" ] && ok "llama.cpp: installable=true on this host (variant $(echo "$ENG" | jq_ "[e for e in d['engines'] if e['engine']=='llama_cpp'][0]['acquisition'].get('variant','?')"), release $(echo "$ENG" | jq_ "[e for e in d['engines'] if e['engine']=='llama_cpp'][0]['acquisition'].get('latestVersion','?')"))"   || { bad "llama.cpp is not installable here (installable=$INST); the Install path cannot be exercised. The agent's reason: $(echo "$ENG" | jq_ "[e for e in d['engines'] if e['engine']=='llama_cpp'][0]['acquisition'].get('reason','(none)')")"; exit 1; }

say "4. one model on disk"
if [ -n "$EP_LOCAL_GGUF" ]; then
  cp "$EP_LOCAL_GGUF" "$WORK/models/" && ok "copied $(basename "$EP_LOCAL_GGUF") into the library's folder" || { bad "copy failed"; exit 1; }
  curl -s -o /dev/null -X POST "${AUTH[@]}" -H 'content-type: application/json' "$LIB/v1/scan" -d '{"full":false}'
  for _ in $(seq 1 60); do [ "$(curl -s "${AUTH[@]}" "$LIB/v1/scan" | jq_ "d['state']")" != "scanning" ] && break; sleep 1; done
else
  DL=$(curl -s -X POST "${AUTH[@]}" -H 'content-type: application/json' "$LIB/v1/downloads" -d "{\"repo\":\"$EP_REPO\",\"files\":[\"$EP_FILE\"]}")
  DL_ID=$(echo "$DL" | jq_ "d.get('id','')")
  [ -n "$DL_ID" ] || { bad "download did not start: $(echo "$DL" | head -c 300)"; exit 1; }
  STATE=""
  for _ in $(seq 1 600); do
    STATE=$(curl -s "${AUTH[@]}" "$LIB/v1/downloads/$DL_ID" | jq_ "d['state']")
    case "$STATE" in done|failed|cancelled) break;; esac
    sleep 2
  done
  [ "$STATE" = "done" ] && ok "downloaded $EP_REPO $EP_FILE through the library" || { bad "download ended $STATE: $(curl -s "${AUTH[@]}" "$LIB/v1/downloads/$DL_ID" | head -c 400)"; exit 1; }
  # The library's post-completion scan names the entry on the record.
  for _ in $(seq 1 30); do
    MID=$(curl -s "${AUTH[@]}" "$LIB/v1/downloads/$DL_ID" | jq_ "d.get('modelId') or ''")
    [ -n "$MID" ] && break; sleep 1
  done
  [ -n "$MID" ] && ok "the download record carries modelId=$MID (what the Run-in-place row reads)" || bad "no modelId on the finished download"
  DOWNLOADED=1
fi
MODELS=$(curl -s "${AUTH[@]}" "$LIB/v1/models")
COUNT=$(echo "$MODELS" | jq_ "len([m for m in d['models'] if m['status']=='present'])")
MODEL_ID=$(echo "$MODELS" | jq_ "[m for m in d['models'] if m['status']=='present'][0]['id']")
MODEL_NAME=$(echo "$MODELS" | jq_ "[m for m in d['models'] if m['status']=='present'][0]['name']")
[ "$COUNT" = "1" ] && ok "exactly one model on disk: $MODEL_NAME ($MODEL_ID)" || { bad "expected one present model, found $COUNT"; exit 1; }
RUNTIME=$(printf '%s' "$MODEL_NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-//; s/-$//')
[ "$(curl -s "${AUTH[@]}" "$LIB/v1/models/$MODEL_ID/profiles" | jq_ "len(d['profiles'])")" = "0" ] && ok "no profile yet: the person has never heard the word" || bad "a profile already exists"

say "5-8. the browser: Home's Run, Run in place, the one question, Skip, Install, ready, the first reply"
(cd "$UI_DIR" && EP_UI_URL="$AGENT" EP_PASSPHRASE="$PASS" EP_MODEL_ID="$MODEL_ID" EP_MODEL_NAME="$MODEL_NAME" EP_RUN_BUDGET_MS="$EP_RUN_BUDGET_MS" EP_DOWNLOADED="$DOWNLOADED" \
  npx playwright test e2e/one-click-run.spec.ts > "$WORK/playwright.log" 2>&1)
PW=$?
sed -n '/Running/,$p' "$WORK/playwright.log" | grep -E '^\s+(ok|x|-|[✓✘×])\s+[0-9]|passed|failed|skipped' | head -20
if [ "$PW" = "0" ]; then
  for t in \
    "Home offers to run the one model on disk, in one click" \
    "a finished download offers Run in place, beside the library link" \
    "Skip leaves the model listed on Inference as stopped, with the reason" \
    "Run again installs llama.cpp on Install, starts the same runtime, and reaches ready" \
    "the first reply lands on Home"; do
    if grep -E "^\s+(ok|✓)\s+[0-9]+ .*$(printf '%s' "$t" | sed 's/[][\.*^$]/\\&/g')" "$WORK/playwright.log" >/dev/null; then
      ok "browser: $t"
    elif [ "$DOWNLOADED" = "0" ] && [ "$t" = "a finished download offers Run in place, beside the library link" ]; then
      ok "browser: $t -- SKIPPED: the model was copied in (EP_LOCAL_GGUF), so there was no download to finish"
    else
      bad "browser: '$t' did not pass"
    fi
  done
else
  bad "the one-click-run spec failed"
  tail -80 "$WORK/playwright.log"
fi

say "9. what the components hold afterwards"
PROFILES=$(curl -s "${AUTH[@]}" "$LIB/v1/models/$MODEL_ID/profiles")
[ "$(echo "$PROFILES" | jq_ "len(d['profiles'])")" = "1" ] && ok "exactly one profile was made" || bad "profiles: $(echo "$PROFILES" | head -c 300)"
[ "$(echo "$PROFILES" | jq_ "d['profiles'][0]['name'] + ':' + str(d['profiles'][0]['default'])")" = "default:True" ] && ok "it is named default and is the default" || bad "the profile is not the default one"
ENG=$(curl -s "${AUTH[@]}" "$AGENT/v1/engines")
[ "$(echo "$ENG" | jq_ "[e for e in d['engines'] if e['engine']=='llama_cpp'][0]['available']")" = "True" ] && ok "llama.cpp is installed now: $(echo "$ENG" | jq_ "[e for e in d['engines'] if e['engine']=='llama_cpp'][0].get('version','?')")" || bad "llama.cpp still not available"
ls "$WORK/engines" >/dev/null 2>&1 && [ -n "$(ls -A "$WORK/engines" 2>/dev/null)" ] && ok "the build landed under this run's own engine root, not the live install's" || bad "nothing under $WORK/engines"
RTS=$(curl -s "${AUTH[@]}" "$AGENT/v1/runtimes")
[ "$(echo "$RTS" | jq_ "len(d['runtimes'])")" = "1" ] && ok "exactly one runtime: Run after Skip started it rather than declaring a second" || bad "runtimes: $(echo "$RTS" | head -c 400)"
[ "$(echo "$RTS" | jq_ "d['runtimes'][0]['status']")" = "ready" ] && ok "runtime $RUNTIME is ready" || bad "runtime status: $(echo "$RTS" | jq_ "d['runtimes'][0]['status']")"
ALIAS=$(echo "$RTS" | jq_ "d['runtimes'][0].get('modelAlias','')")
for _ in $(seq 1 30); do
  curl -s "${AUTH[@]}" "$GW/v1/models" | grep -q "\"$ALIAS\"" && break; sleep 2
done
curl -s "${AUTH[@]}" "$GW/v1/models" | grep -q "\"$ALIAS\"" && ok "the gateway lists $ALIAS" || bad "the gateway does not list $ALIAS"
REPLY=$(curl -s -m 180 "${AUTH[@]}" -H 'content-type: application/json' "$GW/v1/chat/completions" -d "{\"model\":\"$ALIAS\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ok\"}],\"max_tokens\":40}")
echo "$REPLY" | grep -q '"content"' && ok "a completion through the gateway: $(echo "$REPLY" | jq_ "d['choices'][0]['message']['content'][:60].replace(chr(10),' ')")" || bad "no completion: $(echo "$REPLY" | head -c 300)"

say "result"
if [ "$FAILURES" = "0" ]; then printf '  ALL CHECKS PASSED\n'; else printf '  %d CHECK(S) FAILED\n' "$FAILURES"; fi
exit "$FAILURES"
