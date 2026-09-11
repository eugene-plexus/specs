#!/usr/bin/env bash
#
# Install-paths §9 step 1 acceptance: the agent serves the UI, and the
# proxy that moved into it does not buffer.
#
# **The check this script exists for is a clock on a stream that goes
# through the new proxy.** Every other property here would survive a
# proxy that reads the whole upstream body before answering: the page
# loads, deep links resolve, targets resolve, SSE is framed correctly,
# the playground renders. M10 spent a milestone on exactly that class of
# defect -- nine milestones of perfectly-framed SSE delivered in one
# chunk -- so nothing here is allowed to check framing alone. It counts
# content frames AND measures how far into the request the first one
# arrived, through the proxy and then straight at the gateway, and
# compares them.
#
# **It builds and installs the wheel from the checkout every run**,
# because the whole point is that the browser now arrives as a Python
# distribution. A run against whatever wheel happened to be installed
# would be testing a build of unknown age -- the stale-instrument trap,
# which has already cost this project a misattributed failure.
#
# Ollama is the backend for the same reason M8 and M10 used it: it is
# already on this box, it speaks the OpenAI-compatible SSE the
# `openai_compat_http` engine consumes, and it makes these measurements
# real rather than fixtures.
#
# Checks:
#   1. the wheel builds from the checkout and carries an index.html
#   2. the agent serves the UI at its own root, out of site-packages
#   3. a deep link pasted cold resolves (the trailing-slash convention)
#   4. an API-shaped path is never answered with an HTML page
#   5. the proxy resolves agent / gateway / library / control, and says
#      what it looked for when it cannot
#   6. the proxy carries a completion, and a STREAMED one arrives early
#   7. M9's second credential header is inert
#   8. no UI is a degradation: API up, /healthz up, / explains itself
#
# Design: docs/design/install-paths-and-distribution.md §3, §9, §11
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-uihost-live}"
AGENT=http://127.0.0.1:8079
GW=http://127.0.0.1:8080
BARE=http://127.0.0.1:8086
PASS="uihost-live-$$"
OLLAMA="${EP_OLLAMA:-http://127.0.0.1:11434}"
MODEL="${EP_MODEL:-huihui_ai/dolphin3-abliterated:8b-llama3.1-q4_K_M}"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code() { curl -s -o /dev/null -w '%{http_code}' -m 10 "$@"; }

free_port() { # Windows lets a second process bind an already-bound
  # loopback port and keeps serving from the OLDEST binder, so a leftover
  # process answers for the one this run just started -- with the
  # previous run's code. Kill by port, never by pid or command pattern.
  for pid in $(netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $NF}' | sort -u); do
    taskkill //PID "$pid" //T //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
  done
}

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
[ -d "$UI_DIR/node_modules" ] || { bad "$UI_DIR/node_modules is absent (npm ci first)"; exit 1; }
curl -sf -m 3 "$OLLAMA/api/tags" >/dev/null || { bad "ollama is not answering at $OLLAMA"; exit 1; }
ok "agent python, a ui checkout, and a live ollama"

for p in 8079 8080 8082 8083 8086 8091; do free_port "$p"; done
rm -rf "$WORK"; mkdir -p "$WORK"

# --- 1. the wheel ---------------------------------------------------------------
say "1. the browser half builds from this checkout as a Python wheel"
if (cd "$UI_DIR" && npm run build:python > "$WORK/uibuild.log" 2>&1 \
      && "$PY" -m build --wheel >> "$WORK/uibuild.log" 2>&1); then
  ok "next build -> static export -> staged -> wheel"
else
  bad "the wheel did not build -- see $WORK/uibuild.log"; tail -20 "$WORK/uibuild.log"; exit 1
fi
WHEEL=$(ls -t "$UI_DIR"/dist/eugene_plexus_ui-*.whl 2>/dev/null | head -1)
[ -n "$WHEEL" ] && ok "built $(basename "$WHEEL")" || { bad "no wheel in $UI_DIR/dist"; exit 1; }
"$PY" - "$WHEEL" <<'PYEOF'
import sys, zipfile
names = zipfile.ZipFile(sys.argv[1]).namelist()
assert "eugene_plexus_ui/static/index.html" in names, "no index.html in the wheel"
assert any(n.startswith("eugene_plexus_ui/static/_next/") for n in names), "no bundles in the wheel"
assert any(n.endswith("static/nodes/index.html") for n in names), "no per-route index.html"
print(f"  {len(names)} files, including a per-route index.html")
PYEOF
[ $? -eq 0 ] && ok "the wheel carries a UI, not an empty directory" || bad "the wheel is hollow"
"$PY" -m pip install --quiet --force-reinstall "$WHEEL" >> "$WORK/uibuild.log" 2>&1 \
  && ok "installed into the agent's own interpreter" || bad "pip install failed"

# --- the install ----------------------------------------------------------------
say "start the agent; it declares control, gateway and library itself"
cd "$WORK" || exit 1
"$PY" -m eugene_plexus_agent >"$WORK/agent.log" 2>&1 &
AGENT_PID=$!
BARE_PID=""
cleanup() {
  kill -9 "$AGENT_PID" "$BARE_PID" 2>/dev/null
  pkill -f eugene_plexus_ 2>/dev/null
  for p in 8079 8080 8082 8083 8086 8091; do free_port "$p"; done
}
trap cleanup EXIT
wait_healthy "$AGENT" 60 || { bad "agent never answered"; tail -20 "$WORK/agent.log"; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d['sessionToken']")
[ -n "$TOK" ] || { bad "no operator token"; exit 1; }
wait_healthy "$GW" 90 || { bad "gateway never answered"; exit 1; }
# **The trust root needs its own passphrase, and forgetting it cost three
# checks on the first run.** An uninitialized control root 503s its
# entire surface by design -- which is the same status the proxy uses for
# "that target is not in the topology". This script read control's own
# refusal as a resolution failure and reported the proxy broken. Hence
# both this line and the `component` assertion below: a status code alone
# cannot tell those two apart, and the body can.
curl -s -o /dev/null -X POST "http://127.0.0.1:8083/v1/auth/initialize" \
  -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}"
ok "agent and gateway up, trust root initialized"
grep -q "serving the web UI from" "$WORK/agent.log" \
  && ok "the agent said where it found the UI: $(grep -o 'serving the web UI from.*' "$WORK/agent.log" | head -1)" \
  || bad "the agent logged no UI location"

# --- 2, 3, 4. the static bundle -------------------------------------------------
say "2. the UI is served at the agent's own root"
ROOT_CODE=$(code "$AGENT/")
ROOT_TYPE=$(curl -s -o /dev/null -w '%{content_type}' "$AGENT/")
[ "$ROOT_CODE" = "200" ] && ok "GET / -> 200 ($ROOT_TYPE)" || bad "GET / -> $ROOT_CODE"
curl -s "$AGENT/" | grep -qi "<!DOCTYPE html" && ok "...and it is the application's HTML" || bad "/ did not return HTML"
# The bundle, not just the shell: a page whose scripts 404 renders a blank
# body and still answers 200, which is the failure this catches.
BUNDLE=$(curl -s "$AGENT/" | grep -o '/_next/static/[^"]*\.js' | head -1)
[ -n "$BUNDLE" ] && [ "$(code "$AGENT$BUNDLE")" = "200" ] \
  && ok "the client bundle it references is served too ($BUNDLE)" \
  || bad "the page references a bundle the agent does not serve: $BUNDLE"

say "3. a deep link pasted cold resolves -- the trailing-slash convention"
DEEP=$(curl -s -o /dev/null -w '%{http_code}' "$AGENT/nodes")
DEEP_TO=$(curl -s -o /dev/null -w '%{redirect_url}' "$AGENT/nodes")
[ "$DEEP" = "307" ] || [ "$DEEP" = "301" ] || [ "$DEEP" = "308" ] \
  && ok "/nodes -> $DEEP -> $DEEP_TO" || bad "/nodes -> $DEEP (expected a redirect)"
[ "$(code -L "$AGENT/nodes")" = "200" ] && ok "...and following it lands on the page" || bad "/nodes does not resolve"
[ "$(code "$AGENT/nodes/")" = "200" ] && ok "/nodes/ serves directly" || bad "/nodes/ does not serve"

say "4. an API-shaped path is never answered with a page"
TYPO_TYPE=$(curl -s -o /dev/null -w '%{content_type}' "$AGENT/v1/no-such-thing")
TYPO_CODE=$(code "$AGENT/v1/no-such-thing")
[ "$TYPO_CODE" = "404" ] && ok "/v1/no-such-thing -> 404" || bad "/v1/no-such-thing -> $TYPO_CODE"
printf '%s' "$TYPO_TYPE" | grep -q json \
  && ok "...as a Problem document, not the UI's HTML 404" || bad "content-type was $TYPO_TYPE"
[ "$(code "$AGENT/healthz")" = "200" ] && ok "/healthz still answers with a UI mounted" || bad "/healthz broke"

# --- 5. the proxy ---------------------------------------------------------------
say "5. the proxy resolves every target, in process"
INIT=$(curl -s "$AGENT/api/proxy/agent/v1/auth/status" | jq_ "d.get('initialized')")
[ "$INIT" = "True" ] && ok "agent target: /v1/auth/status through the proxy, unauthenticated" \
  || bad "agent target returned $INIT"
for target in gateway library; do
  C=$(code "$AGENT/api/proxy/$target/v1/config" -H "Authorization: Bearer $TOK")
  [ "$C" = "200" ] && ok "$target target resolved by kind -> $C" || bad "$target target -> $C"
done
# **Control takes a different token, and that is the point of this
# check.** Until this host's agent enrolls, the agent mints its own
# random per-restart signing key while the root mints the install's, so
# the browser's agent session does not verify at the root -- M9's finding
# with the longest reach. What M9 then needed was TWO credentials on one
# call, because the old Next proxy spent the request's `Authorization`
# resolving where the root was. This is that same call with one header:
# the root's token, and nothing spent finding the root.
CTOK=$(curl -s -X POST "$AGENT/api/proxy/control/v1/auth/login" -H 'content-type: application/json' \
  -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$CTOK" ] && ok "logged in at the trust root THROUGH the proxy" || bad "no control session through the proxy"
C=$(code "$AGENT/api/proxy/control/v1/config" -H "Authorization: Bearer $CTOK")
[ "$C" = "200" ] && ok "control target resolved by kind, with ONE credential -> $C" \
  || bad "control target -> $C"
CN=$(code "$AGENT/api/proxy/control/v1/nodes" -H "Authorization: Bearer $CTOK")
[ "$CN" = "200" ] && ok "...and the root's own node registry reads through it" || bad "control /v1/nodes -> $CN"
MISSING=$(curl -s "$AGENT/api/proxy/no-such-driver/v1/info" -H "Authorization: Bearer $TOK")
printf '%s' "$MISSING" | grep -q "no-such-driver" \
  && ok "an unknown target names what it looked for" || bad "unhelpful miss: $MISSING"
# Not the status: the body. `component` says who refused, and that is the
# only thing distinguishing the proxy's "not in the topology" from an
# upstream component's own 503.
printf '%s' "$MISSING" | grep -q '"component":"agent"' \
  && ok "...and the refusal is the proxy's own, not an upstream's" \
  || bad "the miss did not come from the agent: $MISSING"
[ "$(code "$AGENT/api/proxy/control/v1/nodes")" = "401" ] \
  && ok "the proxy confers no authority: no bearer, no answer" || bad "an unauthenticated control read was not refused"

# --- 7. the second credential is gone -------------------------------------------
say "7. M9's second credential header is inert, not deprecated"
HDR_ONLY=$(code "$AGENT/api/proxy/control/v1/nodes" -H "x-eugene-plexus-upstream-authorization: Bearer $TOK")
[ "$HDR_ONLY" = "401" ] \
  && ok "a request carrying ONLY the old header is refused -- nothing reads it" \
  || bad "the old header still authenticates something ($HDR_ONLY)"

# --- 6. a completion, and a stream, through the proxy ----------------------------
say "6. a real completion through the proxy -- and then a streamed one"
add_driver() { # name port provider model baseUrl
  curl -s -o /dev/null -X POST "$AGENT/v1/components" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' \
    -d "{\"name\":\"$1\",\"kind\":\"inference-driver\",\"url\":\"http://127.0.0.1:$2\",\"spawn\":{\"configFile\":\"$1.yaml\"}}"
  sleep 3
  curl -s -o /dev/null -X PATCH "http://127.0.0.1:$2/v1/config" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' \
    -d "{\"provider\":\"$3\",\"modelId\":\"$4\",\"baseUrl\":\"$5\"}"
  curl -s -o /dev/null -X POST "$AGENT/v1/components/$1/restart" -H "Authorization: Bearer $TOK" -d '{}'
}
wait_for_model() { # Matches a model ID exactly: grepping raw JSON lets a
  # driver's NAME satisfy a wait whose subject is a model id, and then the
  # checks downstream read a 404's own text as evidence.
  for _ in $(seq 1 "${2:-60}"); do
    if curl -s "$GW/v1/models" -H "Authorization: Bearer $TOK" | PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if sys.argv[1] in [m['id'] for m in d.get('data',[])] else 1)" "$1"; then
      return 0
    fi
    sleep 1
  done
  return 1
}
add_driver ollama-proxied 8091 ollama_local "$MODEL" "$OLLAMA"
wait_for_model "$MODEL" 60 || { bad "the model never became routable"; exit 1; }
ok "the model is routable"

# A driver's own surface, by name, is the target shape nothing else here
# covers -- and the one an operator's config page uses most.
DRV=$(curl -s "$AGENT/api/proxy/ollama-proxied/v1/info" -H "Authorization: Bearer $TOK" | jq_ "d.get('modelId','')")
[ "$DRV" = "$MODEL" ] && ok "a driver resolved by NAME through the proxy reports its model" \
  || bad "driver-by-name returned modelId=$DRV"

PLAIN=$(curl -s -m 300 -X POST "$AGENT/api/proxy/gateway/v1/chat/completions" \
  -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello in five words.\"}],\"max_tokens\":40}")
printf '%s' "$PLAIN" | jq_ "d['choices'][0]['message']['content'][:60]" >/dev/null 2>&1 \
  && ok "a non-streamed completion came back through the proxy: $(printf '%s' "$PLAIN" | jq_ "repr(d['choices'][0]['message']['content'][:50])")" \
  || bad "no completion through the proxy: $(printf '%s' "$PLAIN" | head -c 200)"

# **The instrument must not buffer.** M10's first run used urllib and
# reported time-to-first-token at 94% of a request in which it had also
# counted 79 frames -- both cannot be true. `curl -N` disables its own
# buffering and the reader takes lines off the pipe as they land, so
# what is timed is the server rather than the client.
measure() { # url -> json on stdout
  curl -sN -m 300 -X POST "$1" \
    -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
    -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Count slowly from 1 to 40, one number per line.\"}],\"max_tokens\":200,\"stream\":true}" \
  | PYTHONUTF8=1 python -u -c "
import json, sys, time
started = time.monotonic(); first = None; content = 0; chars = 0
while True:
    raw = sys.stdin.buffer.readline()
    if not raw:
        break
    line = raw.decode('utf-8', 'replace').strip()
    if not line.startswith('data:'):
        continue
    payload = line[5:].strip()
    if payload == '[DONE]':
        continue
    try:
        chunk = json.loads(payload)
    except ValueError:
        continue
    delta = ((chunk.get('choices') or [{}])[0].get('delta') or {}).get('content')
    if delta:
        content += 1; chars += len(delta)
        if first is None:
            first = time.monotonic() - started
total = time.monotonic() - started
json.dump({'contentFrames': content, 'chars': chars, 'ttft': first, 'total': total}, sys.stdout)
"
}
ratio() { PYTHONUTF8=1 python -c "
import sys,json; d=json.load(open(sys.argv[1]))
t=d['ttft']; print(100 if t is None else int(100*t/d['total']))
" "$1"; }

measure "$AGENT/api/proxy/gateway/v1/chat/completions" > "$WORK/via-proxy.json"
measure "$GW/v1/chat/completions" > "$WORK/direct.json"
for f in via-proxy direct; do
  PYTHONUTF8=1 python -c "
import sys,json; d=json.load(open(sys.argv[1]))
print('  %-9s contentFrames=%d chars=%d ttft=%.2fs total=%.2fs (%.1f%%)' % (
    sys.argv[2], d['contentFrames'], d['chars'], d['ttft'] or -1, d['total'],
    100*(d['ttft'] or 0)/d['total']))
" "$WORK/$f.json" "$f"
done
PCF=$(jq_ "d['contentFrames']" < "$WORK/via-proxy.json")
PRATIO=$(ratio "$WORK/via-proxy.json")
DRATIO=$(ratio "$WORK/direct.json")
[ "${PCF:-0}" -gt 1 ] && ok "$PCF content frames arrived through the proxy" \
  || bad "only $PCF content frame(s) through the proxy"
[ "${PRATIO:-100}" -lt 50 ] \
  && ok "*** first token at ${PRATIO}% of the request THROUGH THE PROXY -- it does not buffer ***" \
  || bad "first token through the proxy arrived at ${PRATIO}% of the request: it buffers"
# The comparison is what makes the number mean something: a proxy that
# buffered would still deliver every frame, so the frame count alone
# cannot tell the two apart -- only the clock can, and only against the
# same measurement taken without the proxy in the way.
printf '  direct %s%% vs proxied %s%%\n' "$DRATIO" "$PRATIO"
[ $(( PRATIO - DRATIO )) -lt 25 ] \
  && ok "the proxy adds no meaningful delay to the first token" \
  || bad "the proxy delayed the first token by $(( PRATIO - DRATIO )) points of the request"

# --- 8. degraded ----------------------------------------------------------------
say "8. an agent with no UI serves the API and says so"
# Pointed at a directory that is not there, which reaches the same
# degraded branch as an uninstalled distribution by a different route.
# It does NOT prove the "package absent" message -- the agent's own unit
# suite does that, by refusing the import -- and saying so here is
# cheaper than discovering later that this check meant less than it read.
mkdir -p "$WORK/bare" && cd "$WORK/bare" || exit 1
env EUGENE_PLEXUS_AGENT_BIND_PORT=8086 EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml \
    EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY=0 EUGENE_PLEXUS_AGENT_UI_DIR="$WORK/nope" \
    "$PY" -m eugene_plexus_agent > "$WORK/bare.log" 2>&1 &
BARE_PID=$!
wait_healthy "$BARE" 40 || { bad "the UI-less agent never came up"; tail -10 "$WORK/bare.log"; }
[ "$(code "$BARE/healthz")" = "200" ] && ok "its API is up" || bad "its API is not up"
BARE_ROOT=$(code "$BARE/")
[ "$BARE_ROOT" = "503" ] && ok "GET / -> 503 rather than a connection reset" || bad "GET / -> $BARE_ROOT"
curl -s "$BARE/" | grep -q "eugene-plexus-ui" \
  && ok "...and the page names what to install" || bad "the page does not name the distribution"
grep -q "no web UI will be served" "$WORK/bare.log" \
  && ok "and it said so in its log at startup" || bad "nothing in the log"

say "result"
if [ "$FAILURES" -eq 0 ]; then
  printf '\n  ALL CHECKS PASSED\n\n'
else
  printf '\n  %d CHECK(S) FAILED\n\n' "$FAILURES"
fi
exit "$FAILURES"
