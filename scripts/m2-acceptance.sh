#!/usr/bin/env bash
#
# M2 acceptance: five processes, and a model launched from the library.
#
#   watchdog  ->  spawns  ->  gateway
#             ->  spawns  ->  inference-driver
#             ->  spawns  ->  library
#             ->  spawns  ->  llama-server   (declared at runtime, not in the topology)
#
# What makes this different from m0-acceptance.sh: the engine runtime is
# NOT written into watchdog.yaml. It is created the way the UI's Launch
# button creates one — read a profile from the library, POST a runtime to
# the watchdog with the model's path and the profile's flags. That
# composition lives in the caller and crosses two components, so it is
# exactly the seam no single-component test covers.
#
# The M0 run found two defects in its equivalent seam. This one is
# written to find rather than to pass: where the flow needs a human step
# today, the script performs that step explicitly and says so, instead of
# pre-arranging the install so the gap cannot show.
#
# Usage:
#   scripts/m2-acceptance.sh
#
# Configure via environment:
#   EP_ROOT          parent directory holding the component clones
#   EP_WATCHDOG_PY   python with watchdog + gateway + driver + library installed
#                    (the watchdog spawns every component with its own
#                    sys.executable, so all four must import from this one)
#   EP_LLAMA_SERVER  path to llama-server(.exe)
#   EP_MODEL_ROOT    a directory holding real models, scanned for real
#   EP_MODEL_NAME    which scanned model to launch (substring match)
#   EP_WORKDIR       scratch directory for the throwaway install
#
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
EP_WATCHDOG_PY="${EP_WATCHDOG_PY:-$EP_ROOT/watchdog/.venv/Scripts/python.exe}"
EP_LLAMA_SERVER="${EP_LLAMA_SERVER:-C:/Users/troyc/OneDrive/Desktop/llamacpp/llama-server.exe}"
EP_MODEL_ROOT="${EP_MODEL_ROOT:-C:/Users/troyc/.lmstudio/models}"
EP_MODEL_NAME="${EP_MODEL_NAME:-Qwen3.6-27B}"
EP_WORKDIR="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-m2-acceptance}"

WATCHDOG_PORT=8079
GATEWAY_PORT=8080
DRIVER_PORT=8081
LIBRARY_PORT=8082
DRIVER_NAME=qwen-driver

# Deliberately wrong at boot. The driver comes up degraded, which proves
# the config endpoints stay reachable, and stage 8 repoints it at the
# runtime the library launched — a port nobody could have known in
# advance, because the watchdog assigns it.
PLACEHOLDER_URL="http://127.0.0.1:9"

PASSPHRASE="acceptance-$(date +%s)-$$"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() {
  printf '  FAIL  %s\n' "$*"
  FAILURES=$((FAILURES + 1))
}
note() { printf '  NOTE  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }

# --- preflight -------------------------------------------------------------
say "preflight"
[ -f "$EP_WATCHDOG_PY" ] || bad "watchdog venv python not found at $EP_WATCHDOG_PY"
[ -f "$EP_LLAMA_SERVER" ] || bad "llama-server not found at $EP_LLAMA_SERVER"
[ -d "$EP_MODEL_ROOT" ] || bad "model root not found at $EP_MODEL_ROOT"
if [ "$FAILURES" -ne 0 ]; then
  printf '\nSet EP_WATCHDOG_PY / EP_LLAMA_SERVER / EP_MODEL_ROOT and retry.\n'
  exit 1
fi
if ! "$EP_WATCHDOG_PY" -c "import eugene_plexus_watchdog, eugene_plexus_gateway, eugene_plexus_inference_driver, eugene_plexus_library" 2>/dev/null; then
  bad "watchdog, gateway, inference-driver AND library must import from $EP_WATCHDOG_PY"
  printf '  (pip install -e %s/library into it — the watchdog venv is the runtime venv)\n' "$EP_ROOT"
  exit 1
fi
ok "engine binary, model root and all four components present"

# A runtime created from a library profile carries NO `binary`: the UI
# has no business asking for a path, which is the whole point of M1's
# acquisition. So the engine has to be discoverable, and discovery
# precedence is explicit binary > managed install > PATH. A real
# first-run reaches the managed branch; this run uses PATH so it does
# not re-download 500 MB on every invocation. Both are real origins —
# what would NOT be real is writing the path into the runtime spec,
# because the UI never does.
# POSIX form, deliberately. Git Bash rewrites PATH into Windows form
# when it spawns a native process, and a `C:/...` entry does not survive
# that conversion — `shutil.which` in the child returns None and the
# engine reads as not installed. Cost this run one confusing failure.
ENGINE_DIR=$(dirname "$EP_LLAMA_SERVER")
if command -v cygpath >/dev/null 2>&1; then
  ENGINE_DIR=$(cygpath -u "$ENGINE_DIR")
fi
export PATH="$ENGINE_DIR:$PATH"
note "llama-server on PATH at $ENGINE_DIR; a real first run installs it via POST /v1/engines/llama_cpp/install"

# --- a throwaway install ---------------------------------------------------
say "a throwaway install in $EP_WORKDIR"
rm -rf "$EP_WORKDIR"
mkdir -p "$EP_WORKDIR"
cd "$EP_WORKDIR" || exit 1

win_path() { printf '%s' "$1" | sed 's|/|\\|g'; }

# Note what is NOT here: a `runtimes:` block. M0's topology declared the
# engine up front. Here the operator has not chosen a model yet — that is
# what the library is for.
cat > watchdog.yaml <<YAML
firstRunComplete: true
components:
  - name: gateway
    kind: gateway
    url: http://127.0.0.1:$GATEWAY_PORT
    spawn:
      configFile: gateway.yaml
  - name: $DRIVER_NAME
    kind: inference-driver
    url: http://127.0.0.1:$DRIVER_PORT
    spawn:
      configFile: driver.yaml
  - name: library
    kind: library
    url: http://127.0.0.1:$LIBRARY_PORT
    spawn:
      configFile: library.yaml
YAML

echo "logLevel: INFO" > gateway.yaml

cat > driver.yaml <<YAML
provider: openai_compat_custom
baseUrl: $PLACEHOLDER_URL
YAML

cat > library.yaml <<YAML
modelRoots:
  - $EP_MODEL_ROOT
scanOnStartup: true
logLevel: INFO
YAML
ok "topology written — three components, zero runtimes"

# --- 1. the supervisor -----------------------------------------------------
say "1. start the supervisor"
EUGENE_PLEXUS_WATCHDOG_CONFIG_FILE=watchdog.yaml "$EP_WATCHDOG_PY" \
  -m eugene_plexus_watchdog > watchdog-run.log 2>&1 &
WD_PID=$!
trap 'kill "$WD_PID" 2>/dev/null' EXIT

for _ in $(seq 1 60); do
  curl -sf -m 2 "http://127.0.0.1:$WATCHDOG_PORT/healthz" >/dev/null 2>&1 && break
  sleep 1
done
if curl -sf -m 2 "http://127.0.0.1:$WATCHDOG_PORT/healthz" >/dev/null; then
  ok "watchdog answering on :$WATCHDOG_PORT"
else
  bad "watchdog never came up"
  tail -40 watchdog-run.log
  exit 1
fi

# --- 2. auth ---------------------------------------------------------------
say "2. initialize auth"
TOK=$(curl -s -X POST "http://127.0.0.1:$WATCHDOG_PORT/v1/auth/initialize" \
  -H 'content-type: application/json' \
  -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
if [ -n "$TOK" ]; then
  ok "operator session issued"
else
  bad "no session token"
  exit 1
fi
AUTH=(-H "Authorization: Bearer $TOK")

# --- 3. three components ---------------------------------------------------
say "3. the gateway, the driver and the library, all spawned by the supervisor"
for _ in $(seq 1 60); do
  S=$(curl -s -m 3 "${AUTH[@]}" "http://127.0.0.1:$WATCHDOG_PORT/v1/components" 2>/dev/null |
    jq_ "' '.join(sorted(c['name']+'='+c['status'] for c in d['components']))" 2>/dev/null)
  case "$S" in *"gateway=running"*"library=running"*) break ;; esac
  sleep 1
done
echo "  components: $S"
case "$S" in *"gateway=running"*) ok "gateway running" ;; *) bad "gateway not running" ;; esac
case "$S" in *"$DRIVER_NAME=running"*) ok "driver running" ;; *) bad "driver not running" ;; esac
case "$S" in *"library=running"*) ok "library running — a new ComponentKind the supervisor knows" ;; *) bad "library not running" ;; esac

# --- 3b. engine discovery --------------------------------------------------
say "3b. can the watchdog find an engine at all?"
E=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$WATCHDOG_PORT/v1/engines")
echo "$E" | PYTHONUTF8=1 python -c "
import sys, json
for e in json.load(sys.stdin)['engines']:
    print(f\"  {e['engine']}: available={e['available']} origin={e.get('origin')} \"
          f\"formats={e.get('modelFormats')} build={e.get('version')}\")
    if e.get('error'): print('   ', e['error'])
" 2>/dev/null
AVAIL=$(echo "$E" | jq_ "d['engines'][0]['available']" 2>/dev/null)
FORMATS=$(echo "$E" | jq_ "','.join(d['engines'][0].get('modelFormats') or [])" 2>/dev/null)
[ "$AVAIL" = "True" ] && ok "an engine binary is discoverable — a runtime needs no explicit path" \
  || bad "no engine discoverable; a library launch cannot succeed"
[ "$FORMATS" = "gguf" ] && ok "llama_cpp declares modelFormats=[gguf] — the join the browser uses" \
  || bad "unexpected modelFormats: $FORMATS"

# --- 4. the library scans a real directory ---------------------------------
say "4. the library scans $EP_MODEL_ROOT — real files, real headers"
for _ in $(seq 1 120); do
  SC=$(curl -s -m 5 "${AUTH[@]}" "http://127.0.0.1:$LIBRARY_PORT/v1/scan" 2>/dev/null)
  ST=$(echo "$SC" | jq_ "d['state']" 2>/dev/null)
  case "$ST" in done | failed | cancelled) break ;; esac
  sleep 1
done
echo "$SC" | PYTHONUTF8=1 python -c "
import sys, json
d = json.load(sys.stdin)
print('  state', d['state'], '|', d.get('modelsFound'), 'models from', d.get('filesScanned'), 'files')
reasons = {}
for s in d.get('skipped') or []:
    reasons[s['reason']] = reasons.get(s['reason'], 0) + 1
if reasons:
    print('  skipped:', ', '.join(f'{k} x{v}' for k, v in sorted(reasons.items())))
" 2>/dev/null
[ "$ST" = "done" ] && ok "scan completed" || bad "scan state=$ST"

MODELS=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$LIBRARY_PORT/v1/models")
COUNT=$(echo "$MODELS" | jq_ "len(d['models'])" 2>/dev/null)
[ "${COUNT:-0}" -gt 0 ] && ok "$COUNT models in the library" || bad "no models found"

# The skip list is the feature, not diagnostics: every entry is a file
# somebody can see in a file browser and cannot see in the library.
echo "$SC" | PYTHONUTF8=1 python -c "
import sys, json
d = json.load(sys.stdin)
missing_detail = [s['path'] for s in (d.get('skipped') or []) if not s.get('detail')]
print('  every skipped path carries a reason and a detail:', 'yes' if not missing_detail else f'NO — {missing_detail[:3]}')
" 2>/dev/null

# --- 5. pick a model, exactly as the browser does --------------------------
say "5. pick a model and read what the library says it is"
PICK=$(echo "$MODELS" | PYTHONUTF8=1 python -c "
import sys, json
want = '''$EP_MODEL_NAME'''.lower()
for m in json.load(sys.stdin)['models']:
    if want in m['name'].lower() and m['format'] == 'gguf' and m['status'] == 'present':
        print(json.dumps(m)); break
" 2>/dev/null)
if [ -z "$PICK" ]; then
  bad "no present GGUF model matching '$EP_MODEL_NAME'"
  exit 1
fi
MODEL_ID=$(echo "$PICK" | jq_ "d['id']")
MODEL_PATH=$(echo "$PICK" | jq_ "d['path']")
MODEL_NAME=$(echo "$PICK" | jq_ "d['name']")
echo "$PICK" | PYTHONUTF8=1 python -c "
import sys, json
m = json.load(sys.stdin)
g = m.get('gguf') or {}
c = m.get('capabilities') or {}
print(f\"  {m['name']}\")
print(f\"    id {m['id']}  ·  {m['format']}  ·  {g.get('quantization')} (file_type {g.get('fileType')})\")
print(f\"    arch {m.get('architecture')}  ·  context {m.get('contextLength')}  ·  vocab {g.get('vocabSize')}\")
print(f\"    {(m.get('sizeBytes') or 0)/1e9:.1f} GB across {m.get('fileCount')} file(s)\")
print(f\"    capabilities: {', '.join(k for k, v in c.items() if v)}\")
if g.get('projectorPath'):
    print(f\"    projector attached, not listed as its own model\")
" 2>/dev/null
ok "the library described a real model without anyone typing its path"

# The reverse lookup the runtime dashboard uses to get from a modelPath
# back to a library entry.
RL=$(curl -s -G "${AUTH[@]}" "http://127.0.0.1:$LIBRARY_PORT/v1/models" \
  --data-urlencode "path=$MODEL_PATH" | jq_ "len(d['models'])" 2>/dev/null)
[ "$RL" = "1" ] && ok "reverse lookup by path resolves to exactly this entry" || bad "reverse lookup returned $RL"

# --- 6. save a profile, as the editor does ---------------------------------
say "6. save a launch profile"
PROFILE=$(curl -s -X POST "${AUTH[@]}" \
  "http://127.0.0.1:$LIBRARY_PORT/v1/models/$MODEL_ID/profiles" \
  -H 'content-type: application/json' \
  -d '{"name":"acceptance","engine":"llama_cpp","default":true,
       "flags":{"contextSize":4096,"gpuLayers":99,"parallelSlots":1},
       "notes":"created by the M2 acceptance run"}')
PROFILE_ID=$(echo "$PROFILE" | jq_ "d.get('id','')" 2>/dev/null)
[ -n "$PROFILE_ID" ] && ok "profile saved (id $PROFILE_ID, default)" || bad "profile not saved: $PROFILE"

# The library validates no flags — the watchdog does, when a runtime is
# created. Prove both halves rather than asserting the design.
BADP=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${AUTH[@]}" \
  "http://127.0.0.1:$LIBRARY_PORT/v1/models/$MODEL_ID/profiles" \
  -H 'content-type: application/json' \
  -d '{"name":"wrong-key","engine":"llama_cpp","flags":{"nGpuLayers":99}}')
[ "$BADP" = "201" ] && ok "a profile with an unknown flag is stored, not rejected (the library validates nothing)" \
  || bad "expected 201 storing an unknown flag, got $BADP"

WRONG=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${AUTH[@]}" \
  "http://127.0.0.1:$WATCHDOG_PORT/v1/runtimes" -H 'content-type: application/json' \
  -d "{\"name\":\"wrong-key-check\",\"engine\":\"llama_cpp\",\"modelPath\":\"$(echo "$MODEL_PATH" | sed 's|\\|\\\\|g')\",\"flags\":{\"nGpuLayers\":99}}")
[ "$WRONG" = "400" ] && ok "and the watchdog refuses the runtime that uses it (400) — one validator, in the right place" \
  || bad "expected 400 from the watchdog for an unknown flag, got $WRONG"

# --- 7. launch: the composition the UI performs ----------------------------
say "7. launch — read the profile, POST a runtime. Field names line up; nothing translates."
RUNTIME_NAME=$(echo "$MODEL_NAME" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9]\+/-/g; s/^-//; s/-$//' | cut -c1-40)
SPEC=$(PYTHONUTF8=1 python -c "
import json, sys
profile = json.loads(sys.argv[1])
print(json.dumps({
    'name': sys.argv[2],
    'engine': profile['engine'],
    'modelPath': sys.argv[3],
    'flags': profile.get('flags') or None,
    'extraArgs': profile.get('extraArgs') or None,
    'env': profile.get('env') or None,
    'autoStart': True,
    # No host, no port: the watchdog binds loopback and assigns a port.
    # Restating either here would put a second copy of the supervisor's
    # rule in the caller.
}))
" "$PROFILE" "$RUNTIME_NAME" "$MODEL_PATH")
echo "  POST /v1/runtimes $SPEC"
RT=$(curl -s -X POST "${AUTH[@]}" "http://127.0.0.1:$WATCHDOG_PORT/v1/runtimes" \
  -H 'content-type: application/json' -d "$SPEC")
RT_NAME=$(echo "$RT" | jq_ "d.get('name','')" 2>/dev/null)
if [ -n "$RT_NAME" ]; then
  ok "runtime '$RT_NAME' declared from the profile"
else
  bad "runtime not created: $RT"
  exit 1
fi

# --- 8. the engine ---------------------------------------------------------
say "8. the engine reaches ready"
for _ in $(seq 1 900); do
  R=$(curl -s -m 3 "${AUTH[@]}" "http://127.0.0.1:$WATCHDOG_PORT/v1/runtimes")
  ST=$(echo "$R" | PYTHONUTF8=1 python -c "
import sys, json
for r in json.load(sys.stdin)['runtimes']:
    if r['name'] == '''$RT_NAME''': print(r['status']); break
" 2>/dev/null)
  [ "$ST" = "ready" ] && break
  [ "$ST" = "crashed" ] && break
  sleep 1
done
ENGINE_URL=$(echo "$R" | PYTHONUTF8=1 python -c "
import sys, json
for r in json.load(sys.stdin)['runtimes']:
    if r['name'] == '''$RT_NAME''':
        print(r.get('url') or '')
        break
" 2>/dev/null)
echo "$R" | PYTHONUTF8=1 python -c "
import sys, json
for r in json.load(sys.stdin)['runtimes']:
    if r['name'] == '''$RT_NAME''':
        print('  status', r['status'], '| pid', r.get('pid'), '| build', r.get('engineVersion'))
        print('  url', r.get('url'), '(port assigned by the watchdog)')
        print('  capabilities read back off the loaded engine:', r.get('capabilities'))
        print('  argv:', ' '.join(r.get('argv') or []))
        if r.get('lastError'): print('  lastError:', r['lastError'])
" 2>/dev/null
if [ "$ST" = "ready" ]; then
  ok "the model the library found is loaded and serving"
else
  bad "runtime never became ready (status=$ST)"
  tail -30 watchdog-run.log
fi

# --- 9. the gap ------------------------------------------------------------
say "9. is it routable yet?"
# The gateway builds its routing table from the DRIVERS, not from the
# runtimes. Launching declared an engine; nothing pointed a driver at it.
M=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$GATEWAY_PORT/v1/models")
IDS=$(echo "$M" | jq_ "','.join(x['id'] for x in d.get('data') or [])" 2>/dev/null)
echo "  gateway /v1/models: [${IDS}]"
if [ -n "$IDS" ]; then
  note "already routable — a driver was pointing at it"
else
  note "NOT routable. The gateway routes via drivers, and nothing wired one"
  note "to a port the watchdog only chose at launch. This is the step a"
  note "human closes by hand today; stage 10 does it explicitly."
fi

# --- 10. close it by hand --------------------------------------------------
say "10. point the driver at the runtime the library launched"
echo "  PATCH driver baseUrl -> $ENGINE_URL"
PR=$(curl -s -X PATCH "${AUTH[@]}" "http://127.0.0.1:$DRIVER_PORT/v1/config" \
  -H 'content-type: application/json' \
  -d "{\"baseUrl\":\"$ENGINE_URL\",\"modelId\":\"$MODEL_NAME\"}")
echo "  applied: $(echo "$PR" | jq_ "d.get('applied')" 2>/dev/null)"
curl -s -o /dev/null -X POST "${AUTH[@]}" "http://127.0.0.1:$DRIVER_PORT/v1/admin/restart" \
  -H 'content-type: application/json' -d '{}'
for _ in $(seq 1 60); do
  curl -sf -m 2 "http://127.0.0.1:$DRIVER_PORT/healthz" >/dev/null 2>&1 && break
  sleep 1
done
ok "driver restarted against the runtime's assigned port"

# --- 11. routing + one completion ------------------------------------------
say "11. the gateway's routing table, then one completion"
for _ in $(seq 1 60); do
  M=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$GATEWAY_PORT/v1/models")
  MID=$(echo "$M" | jq_ "d['data'][0]['id'] if d.get('data') else ''" 2>/dev/null)
  [ -n "$MID" ] && break
  sleep 2
done
echo "  routable as: '$MID'"
[ -n "$MID" ] && ok "the launched model is routable" || bad "gateway lists no models"

START=$(date +%s)
C=$(curl -s -m 900 -X POST "http://127.0.0.1:$GATEWAY_PORT/v1/chat/completions" "${AUTH[@]}" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$MID\",\"messages\":[{\"role\":\"user\",\"content\":\"What is 17 times 23? Answer with just the number.\"}],\"max_tokens\":1024,\"temperature\":0.1}")
TEXT=$(echo "$C" | jq_ "d['choices'][0]['message']['content'].strip() if d.get('choices') else ''" 2>/dev/null)
if [ -n "$TEXT" ]; then
  ok "completion through gateway -> driver -> engine: '$TEXT'"
else
  bad "empty completion: $(echo "$C" | head -c 400)"
fi
echo "  wall clock: $(($(date +%s) - START))s"

# --- 12. the library still knows what it launched --------------------------
say "12. the library and the runtime agree about the same file"
LP=$(curl -s -G "${AUTH[@]}" "http://127.0.0.1:$LIBRARY_PORT/v1/models" \
  --data-urlencode "path=$MODEL_PATH" | jq_ "d['models'][0]['profileCount'] if d['models'] else -1" 2>/dev/null)
[ "${LP:-0}" -ge 1 ] && ok "the entry still carries its $LP profile(s)" || bad "profileCount=$LP"

# --- 13. teardown ----------------------------------------------------------
say "13. teardown"
kill "$WD_PID" 2>/dev/null
for _ in $(seq 1 20); do
  kill -0 "$WD_PID" 2>/dev/null || break
  sleep 1
done
sleep 3
if command -v powershell.exe >/dev/null 2>&1; then
  LEFT=$(powershell.exe -NoProfile -Command \
    "(Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue | Measure-Object).Count" \
    2>/dev/null | tr -d '\r')
else
  LEFT=$(pgrep -c llama-server 2>/dev/null || echo 0)
fi
[ "$LEFT" = "0" ] && ok "llama-server exited with the supervisor" || bad "$LEFT engine process(es) survived"

say "result"
if [ "$FAILURES" -eq 0 ]; then
  echo "M2 acceptance PASSED — five processes, a model found by scanning and launched from a profile."
else
  echo "$FAILURES check(s) FAILED"
fi
echo "install left at $EP_WORKDIR (watchdog-run.log has every child's output)"
exit "$FAILURES"
