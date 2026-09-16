#!/usr/bin/env bash
# Install-paths §9 step 8 -- the playground as a diagnostic instrument.
#
# What only a live run can prove. The gateway's CORS tests pin the
# headers; the UI's unit tests pin the parser and the panel's helpers;
# neither can prove that a real browser on one origin reaches a real
# gateway on another, through CORS, with a bearer, and streams -- because
# `curl` does not enforce the same-origin policy and jsdom has no network.
# So checks 9-14 drive the system Chrome through the playground's direct
# mode against a real model, and the script reads what the browser
# observed out of a results file the spec writes.
#
# The checks:
#   0. this run is isolated from any install on this machine
#   1. agent, control, gateway, library up; the UI served at /
#   2. a driver on a local llama.cpp; /v1/models lists it with tool_calling
#   3. a browser preflight on /v1/chat/completions is answered with CORS
#   4. a GET /v1/models with an Origin carries Allow-Origin: *
#   5. a preflight on /v1/config is NOT answered with CORS
#   6. corsAllowedOrigins narrows live: listed allowed, other refused
#   7. corsEnabled: false removes the headers, live; restored
#   8. the session token works as the bearer on a direct request
#   9. BROWSER: direct mode prefilled, a turn round-trips, streamed
#  10. BROWSER: the example tool is called; the arguments name the parameter
#  11. BROWSER: the prefilled result closes the loop
#  12. BROWSER: an attached text file is read; prompt_tokens grew
#  13. the browser's curl reproduction replays outside a browser
#  14. BROWSER: the wrong port fails with a named 404; the proxy still works
#  15. teardown by pid; no owned port still listening
#
# Design: docs/design/playground-diagnostic.md
#
# **Safe to run beside a live install, in both dimensions.** Ports: +100
# from the defaults (agent 8179, gateway 8180, library 8182, control
# 8183, driver 8191); it refuses to start if any is taken. State: every
# ambient EUGENE_PLEXUS_* variable is dropped first -- `install.ps1`
# sets EUGENE_PLEXUS_AGENT_CONFIG_FILE in the USER environment, so a
# throwaway agent started from any shell on this account would otherwise
# load the operator's agent.yaml and node.yaml, come up as the live
# worker, and announce a port that dies with this script to the real
# control root (that happened, 2026-09-12). Teardown is by pid: the
# agent's, then the pids holding the ports it opened for its children.
# Never `pkill -f eugene_plexus_`, which on this machine kills the
# operator's own worker node.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-playground-diagnostic}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
GW_PORT="${EP_GW_PORT:-8180}"
LIB_PORT="${EP_LIB_PORT:-8182}"
CTL_PORT="${EP_CTL_PORT:-8183}"
DRIVER_PORT="${EP_DRIVER_PORT:-8191}"
AGENT="http://127.0.0.1:$AGENT_PORT"
GW="http://127.0.0.1:$GW_PORT"
LIB="http://127.0.0.1:$LIB_PORT"
CTL="http://127.0.0.1:$CTL_PORT"
PASS="diag-live-$$"
ENGINE_PORT="${EP_ENGINE_PORT:-8192}"
# The backend: a real llama.cpp, not ollama. lib/llama-backend.sh has the
# reasoning, the provider-key trap and the /v1 trap.
. "$(dirname "$0")/lib/llama-backend.sh"
# A tool-calling model: the same one step 6 proved calls tools, so a
# failure here is ours rather than "this model does not do tools".
MODEL="${EP_MODEL:-diag-acceptance-model}"
# The origin the browser will have, and the one the narrowing check lists.
UI_ORIGIN="http://127.0.0.1:$AGENT_PORT"
OWNED_PORTS="$AGENT_PORT $GW_PORT $LIB_PORT $CTL_PORT $DRIVER_PORT $ENGINE_PORT"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
header_of() { # name, then curl args -- the header's value, lower-cased name match, or empty
  local name="$1"; shift
  curl -s -D - -o /dev/null "$@" | tr -d '\r' | awk -v n="$name" 'BEGIN{IGNORECASE=1} tolower($1)==tolower(n":"){sub(/^[^:]*: */,""); print; exit}'
}
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }

A_PID=""
teardown() {
  llama_stop_all
  # The agent by pid first -- it asks its children to stop -- then
  # whatever still holds a port this run opened, by the pid holding it.
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 3; }
  for p in $OWNED_PORTS; do
    for pid in $(listening_pids "$p"); do
      taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
    done
  done
}

# --- preflight ---------------------------------------------------------------
say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
"$PY" -c "import eugene_plexus_agent, eugene_plexus_control, eugene_plexus_gateway, eugene_plexus_inference_driver, eugene_plexus_library, eugene_plexus_ui" 2>/dev/null \
  || { bad "the five components and eugene_plexus_ui must import from $PY"; exit 1; }
[ -d "$UI_DIR/node_modules/@playwright" ] || { bad "no Playwright in $UI_DIR (npm install)"; exit 1; }
llama_preflight || exit 1
for p in $OWNED_PORTS; do
  if [ -n "$(listening_pids "$p")" ]; then bad "port $p is already in use; set EP_*_PORT or stop it"; exit 1; fi
done
ok "agent python with six packages, Playwright, llama.cpp $(llama_build), a model on disk, every port free"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

# --- 0 -----------------------------------------------------------------------
say "0. isolate this run from any install on this machine"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
WORK_NATIVE=$(cygpath -w "$WORK" 2>/dev/null || printf '%s' "$WORK")
LEAKED=$(env | grep '^EUGENE_PLEXUS_' || true)
if [ -z "$LEAKED" ]; then ok "no ambient EUGENE_PLEXUS_* variable survives into this run"; else bad "ambient config leaked: $LEAKED"; exit 1; fi

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
printf 'logLevel: INFO\nroutingRefreshSeconds: 3\n' > gateway.yaml
echo "logLevel: INFO" > control.yaml
printf 'logLevel: INFO\nmodelRoots: []\n' > library.yaml

# --- 1 -----------------------------------------------------------------------
say "1. the agent and its three children, and the UI at /"
(exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
  "$PY" -m eugene_plexus_agent --unattended > agent.log 2>&1) &
A_PID=$!
wait_healthy "$AGENT" 60 || { bad "agent never answered"; tail -20 agent.log; exit 1; }
wait_healthy "$CTL" 90 && wait_healthy "$LIB" 60 && wait_healthy "$GW" 90 && ok "agent $AGENT, control $CTL, library $LIB, gateway $GW" \
  || { bad "a child never came up"; tail -30 agent.log; exit 1; }
curl -s -m 5 "$AGENT/" | grep -qi "<html" && ok "the agent serves the UI at /" || bad "no HTML at $AGENT/"
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "no operator token"; exit 1; }
wait_healthy "$GW" 90 || { bad "gateway did not come back after initialize"; exit 1; }

# --- 2 -----------------------------------------------------------------------
say "2. a driver on a local llama.cpp; the gateway lists the model with tool_calling"
llama_start "$ENGINE_PORT" "$MODEL" || { bad "the engine never came up"; tail -20 "llama-$ENGINE_PORT.log"; exit 1; }
curl -s -o /dev/null -X POST "$AGENT/v1/components" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"name\":\"diag-llama\",\"kind\":\"inference-driver\",\"url\":\"http://127.0.0.1:$DRIVER_PORT\",\"spawn\":{\"configFile\":\"diag-llama.yaml\"}}"
wait_healthy "http://127.0.0.1:$DRIVER_PORT" 60 || { bad "driver never came up"; tail -20 agent.log; exit 1; }
curl -s -o /dev/null -X PATCH "http://127.0.0.1:$DRIVER_PORT/v1/config" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"provider\":\"openai_compat_custom\",\"modelId\":\"$MODEL\",\"baseUrl\":\"$(llama_base_url "$ENGINE_PORT")\"}"
curl -s -o /dev/null -X POST "$AGENT/v1/components/diag-llama/restart" -H "Authorization: Bearer $TOK" -d '{}'
# A bounded wait on the condition, not a sleep: the routing refresh is 3 s
# here, and a fixed sleep is either too long or -- the embeddings run's
# first failure -- one second too short.
TC=""
for _ in $(seq 1 60); do
  MODELS=$(curl -s -m 10 "$GW/v1/models" -H "Authorization: Bearer $TOK")
  TC=$(printf '%s' "$MODELS" | jq_ "next((str(m.get('x_eugene_plexus',{}).get('tool_calling')) for m in d.get('data',[]) if m['id']=='$MODEL'), '')" 2>/dev/null)
  [ "$TC" = "True" ] && break; sleep 1
done
[ "$TC" = "True" ] && ok "GET /v1/models lists $MODEL with tool_calling: true" || { bad "model not routable with tools: $MODELS"; exit 1; }

# --- 3 -----------------------------------------------------------------------
say "3. the browser's preflight, exactly as Chrome sends it"
PRE=(-X OPTIONS -H "Origin: $UI_ORIGIN" -H 'Access-Control-Request-Method: POST' -H 'Access-Control-Request-Headers: authorization,content-type')
CODE=$(code_of "${PRE[@]}" "$GW/v1/chat/completions")
ACAO=$(header_of access-control-allow-origin "${PRE[@]}" "$GW/v1/chat/completions")
ACAH=$(header_of access-control-allow-headers "${PRE[@]}" "$GW/v1/chat/completions")
echo "  OPTIONS /v1/chat/completions -> $CODE, allow-origin='$ACAO', allow-headers='$ACAH'"
[ "$CODE" = "204" ] && [ "$ACAO" = "*" ] && ok "answered 204 with Access-Control-Allow-Origin: * (was 405 with nothing, measured 2026-09-13)" || bad "preflight: $CODE / '$ACAO'"
printf '%s' "$ACAH" | grep -qi authorization && ok "the requested headers are echoed back, authorization included" || bad "allow-headers: '$ACAH'"

# --- 4 -----------------------------------------------------------------------
say "4. a real cross-origin response carries the header"
ACAO=$(header_of access-control-allow-origin -H "Origin: $UI_ORIGIN" -H "Authorization: Bearer $TOK" "$GW/v1/models")
[ "$ACAO" = "*" ] && ok "GET /v1/models with an Origin: Access-Control-Allow-Origin: *" || bad "no header on the real response: '$ACAO'"

# --- 5 -----------------------------------------------------------------------
say "5. operator paths do not answer browsers from another origin"
CODE=$(code_of "${PRE[@]}" "$GW/v1/config")
ACAO=$(header_of access-control-allow-origin "${PRE[@]}" "$GW/v1/config")
echo "  OPTIONS /v1/config -> $CODE, allow-origin='$ACAO'"
[ "$CODE" != "204" ] && [ -z "$ACAO" ] && ok "/v1/config: no CORS answer ($CODE, no header)" || bad "operator path answered CORS: $CODE '$ACAO'"

# --- 6 -----------------------------------------------------------------------
say "6. corsAllowedOrigins narrows without a restart"
R=$(curl -s -X PATCH "$GW/v1/config" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' -d "{\"corsAllowedOrigins\":[\"$UI_ORIGIN\"]}")
[ "$(printf '%s' "$R" | jq_ "d['applied']==['corsAllowedOrigins'] and d['requiresRestart']==False")" = "True" ] && ok "PATCH applied, requiresRestart: false" || bad "patch: $R"
ACAO=$(header_of access-control-allow-origin "${PRE[@]}" "$GW/v1/chat/completions")
VARY=$(header_of vary "${PRE[@]}" "$GW/v1/chat/completions")
[ "$ACAO" = "$UI_ORIGIN" ] && [ "$(printf '%s' "$VARY" | tr 'A-Z' 'a-z')" = "origin" ] && ok "the listed origin is echoed, with Vary: Origin" || bad "listed origin: '$ACAO' vary '$VARY'"
OTHER=(-X OPTIONS -H 'Origin: http://evil.example' -H 'Access-Control-Request-Method: POST')
CODE=$(code_of "${OTHER[@]}" "$GW/v1/chat/completions")
BODY=$(curl -s "${OTHER[@]}" "$GW/v1/chat/completions")
[ "$CODE" = "403" ] && printf '%s' "$BODY" | grep -q corsAllowedOrigins && ok "an unlisted origin gets 403 naming corsAllowedOrigins: $(printf '%s' "$BODY" | jq_ "d['detail']" | head -c 120)..." || bad "unlisted origin: $CODE $BODY"
curl -s -o /dev/null -X PATCH "$GW/v1/config" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' -d '{"corsAllowedOrigins":[]}'
[ "$(header_of access-control-allow-origin "${PRE[@]}" "$GW/v1/chat/completions")" = "*" ] && ok "cleared: any origin again" || bad "did not return to any-origin"

# --- 7 -----------------------------------------------------------------------
say "7. corsEnabled: false, live"
curl -s -o /dev/null -X PATCH "$GW/v1/config" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' -d '{"corsEnabled":false}'
CODE=$(code_of "${PRE[@]}" "$GW/v1/chat/completions")
BODY=$(curl -s "${PRE[@]}" "$GW/v1/chat/completions")
[ "$CODE" = "403" ] && printf '%s' "$BODY" | grep -q corsEnabled && ok "off: preflight 403 naming corsEnabled" || bad "off: $CODE $BODY"
curl -s -o /dev/null -X PATCH "$GW/v1/config" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' -d '{"corsEnabled":true}'
[ "$(code_of "${PRE[@]}" "$GW/v1/chat/completions")" = "204" ] && ok "on again: 204, same process" || bad "did not come back on"

# --- 8 -----------------------------------------------------------------------
say "8. the session token is the bearer a harness uses"
R=$(curl -s -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" -H "Origin: $UI_ORIGIN" -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ok\"}],\"max_tokens\":20}")
DRV=$(printf '%s' "$R" | jq_ "d.get('x_eugene_plexus',{}).get('driver','')" 2>/dev/null)
[ "$DRV" = "diag-llama" ] && ok "a completion with the session token as bearer, served by $DRV" || bad "direct completion: $(printf '%s' "$R" | head -c 300)"

# --- 9-14 (browser) ----------------------------------------------------------
say "9-14. the system Chrome drives the playground's direct mode"
RESULTS="$WORK/browser.json"
(cd "$UI_DIR" && EP_UI_URL="$AGENT" EP_PASSPHRASE="$PASS" EP_EXPECTED_BASE_URL="$GW/v1" EP_WRONG_BASE_URL="$AGENT/v1" \
  EP_RESULTS_FILE="$(cygpath -w "$RESULTS" 2>/dev/null || printf '%s' "$RESULTS")" \
  npx playwright test e2e/diagnostic.spec.ts > "$WORK/playwright.log" 2>&1)
PW_EXIT=$?
echo "  playwright exit $PW_EXIT; $(grep -E 'passed|failed|skipped' "$WORK/playwright.log" | tail -1)"
browser_check() { # key, label
  local v; v=$(jq_ "d.get('$1',{}).get('ok','missing')" < "$RESULTS" 2>/dev/null)
  local detail; detail=$(jq_ "d.get('$1',{}).get('detail','')" < "$RESULTS" 2>/dev/null)
  if [ "$v" = "True" ]; then ok "$2: $detail"; else bad "$2 ($v): $detail"; fi
}
if [ ! -f "$RESULTS" ]; then
  bad "the browser wrote no results file"; tail -40 "$WORK/playwright.log"
else
  say "9. direct mode, prefilled, one streamed turn"
  browser_check prefill "the base URL is prefilled from the topology"
  browser_check key-is-session-token "the key is this session's token"
  browser_check direct-turn "a turn round-trips direct, streamed, with the envelope"
  say "10. the example tool is called"
  browser_check tool-call "a get_weather card with parseable arguments naming city"
  say "11. the loop closes"
  browser_check tool-loop-closed "the answer used the typed result"
  say "12. an attachment is read"
  browser_check attachment "the canary came back and prompt_tokens grew"
  browser_check curl-present "the report offers a curl line"
fi

# --- 13 ----------------------------------------------------------------------
say "13. the browser's curl replays outside a browser"
if [ -f "$RESULTS.curl" ]; then
  CURL_LINE=$(cat "$RESULTS.curl")
  echo "  $(printf '%s' "$CURL_LINE" | head -c 160)..."
  # The key is a shell variable in the copied text; supply it and run the
  # line verbatim -- what a person pasting it into a terminal would do.
  REPLAY=$(EUGENE_PLEXUS_TOKEN="$TOK" bash -c "$CURL_LINE" 2>/dev/null)
  FRAMES=$(printf '%s' "$REPLAY" | grep -c '^data: ')
  printf '%s' "$REPLAY" | grep -q 'x_eugene_plexus' && printf '%s' "$REPLAY" | grep -q '\[DONE\]' \
    && ok "the replay streamed $FRAMES frames with the envelope and [DONE]: the browser's request works from a shell" \
    || bad "replay: $(printf '%s' "$REPLAY" | head -c 300)"
else
  bad "no curl line was written by the browser"
fi

# --- 14 ----------------------------------------------------------------------
say "14. pointed at the wrong port, direct fails and says so; the proxy still works"
if [ -f "$RESULTS" ]; then
  browser_check wrong-port "the agent's port answers 404 and the report names the URL"
  browser_check proxy-still-works "the same message works through the proxy"
fi
[ "$PW_EXIT" = "0" ] || note "playwright exited $PW_EXIT; see $WORK/playwright.log"

# --- 15 ----------------------------------------------------------------------
say "15. teardown by pid"
teardown; A_PID=""
LEFT=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && LEFT="$LEFT $p"; done
[ -z "$LEFT" ] && ok "no owned port still listening" || bad "still listening:$LEFT"

say "done"
if [ "$FAILURES" -eq 0 ]; then
  printf '\nALL CHECKS PASSED\n'
else
  printf '\n%s CHECK(S) FAILED\n' "$FAILURES"
  exit 1
fi
