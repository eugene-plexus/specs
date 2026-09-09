#!/usr/bin/env bash
#
# M3 acceptance: three processes, and a model fetched from the catalogue
# through the UI's own proxy.
#
#   agent  ->  spawns  ->  library
#   ui (next start)  ->  /api/proxy/library/...  ->  agent topology  ->  library
#
# What makes this different from m0/m2-acceptance.sh: every call goes
# through the **UI's** proxy rather than straight at a component port.
# That is the seam M3 adds and the one no single-component test can
# reach — the browser knows no component URLs, so a request has to be
# resolved through the agent's topology by KIND before it arrives.
# M0's equivalent seam had two defects in it.
#
# It also reaches the live HuggingFace hub, deliberately. The library's
# own suite mocks the transport; this one does not, because five of the
# behaviours M3 is built on are upstream's and a mock agrees with
# whatever we believed when we wrote it. Cost: about 15 MB transferred.
#
# The gateway and the inference-driver take no part in discovery and are
# not started. This is not a smaller version of the M2 run; it is the
# M3 surface.
#
# Usage:
#   scripts/m3-acceptance.sh
#
# Configure via environment:
#   EP_ROOT          parent directory holding the component clones
#   EP_AGENT_PY   python with agent + library installed (the
#                    agent spawns children with its own sys.executable,
#                    so the library must import from this one)
#   EP_MODEL_ROOT    a directory downloads may be written into. A
#                    throwaway is created under EP_WORKDIR by default,
#                    because a real download lands real bytes.
#   EP_REPO          the catalogue repo to exercise
#   EP_WORKDIR       scratch directory for the throwaway install
#
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
EP_AGENT_PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
EP_WORKDIR="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-m3-acceptance}"
EP_MODEL_ROOT="${EP_MODEL_ROOT:-$EP_WORKDIR/models}"
EP_REPO="${EP_REPO:-unsloth/Qwen3.8-27B-GGUF}"

# The smallest file in that repo: a 13.6 MB calibration matrix. A real
# transfer, a real digest check, a real atomic rename — without spending
# 16 GB to prove it.
EP_SMALL_FILE="${EP_SMALL_FILE:-imatrix_unsloth.gguf}"
# A large-vocab quant, for the ranged metadata read.
EP_PREFLIGHT_FILE="${EP_PREFLIGHT_FILE:-Qwen3.8-27B-UD-Q4_K_M.gguf}"

AGENT_PORT=8079
LIBRARY_PORT=8082
UI_PORT="${UI_PORT:-3210}"

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

# Path translation, both directions. A Git Bash path like /tmp/x is a
# *mount*, not a directory: hand it to a Python component and it reads
# as the drive-relative \tmp\x and writes somewhere the shell will not
# look. So the config gets a native path, and native paths coming back
# get converted before the shell tests them.
to_native() { cygpath -m "$1" 2>/dev/null || printf '%s' "$1"; }
to_shell() { cygpath -u "$1" 2>/dev/null || printf '%s' "$1"; }

# Every call in this script goes through the UI, which is the point.
ui() { curl -s -m 120 "${AUTH[@]}" "http://127.0.0.1:$UI_PORT/api/proxy/library$1"; }

# --- preflight -------------------------------------------------------------
say "preflight"
[ -f "$EP_AGENT_PY" ] || bad "agent venv python not found at $EP_AGENT_PY"
if ! "$EP_AGENT_PY" -c "import eugene_plexus_agent, eugene_plexus_library, httpx" 2>/dev/null; then
  bad "agent, library AND httpx must import from $EP_AGENT_PY"
  printf '  (pip install -e %s/library into it — the agent venv is the runtime venv,\n' "$EP_ROOT"
  printf '   and M3 added httpx to the library, so that venv needs it too)\n'
fi
[ -d "$EP_ROOT/ui/.next" ] || bad "the UI is not built — run 'npm run build' in $EP_ROOT/ui"
curl -sf -m 10 -o /dev/null "https://huggingface.co/api/models?limit=1" \
  && ok "the catalogue is reachable" \
  || bad "cannot reach huggingface.co — this run needs outbound HTTPS"
[ "$FAILURES" -eq 0 ] || { echo; echo "preflight failed; stopping"; exit 1; }
ok "agent venv imports the library and httpx"

# --- a throwaway install ---------------------------------------------------
say "a throwaway install in $EP_WORKDIR"
rm -rf "$EP_WORKDIR"
mkdir -p "$EP_WORKDIR" "$EP_MODEL_ROOT"
EP_MODEL_ROOT_NATIVE=$(to_native "$EP_MODEL_ROOT")
cd "$EP_WORKDIR" || exit 1

# No runtimes and no engine: M3 is about acquiring models, and nothing
# here launches one.
cat > agent.yaml <<YAML
firstRunComplete: true
components:
  - name: library
    kind: library
    url: http://127.0.0.1:$LIBRARY_PORT
    spawn:
      configFile: library.yaml
YAML

cat > library.yaml <<YAML
modelRoots:
  - $EP_MODEL_ROOT_NATIVE
scanOnStartup: true
catalogueEnabled: true
guidanceContextLength: 32768
logLevel: INFO
YAML
ok "topology written — one component, an empty model directory"
note "model root as the library will read it: $EP_MODEL_ROOT_NATIVE"

# --- 1. the supervisor and the library -------------------------------------
say "1. start the supervisor; it spawns the library"
EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml "$EP_AGENT_PY" \
  -m eugene_plexus_agent > agent-run.log 2>&1 &
WD_PID=$!
UI_PID=""

cleanup() {
  kill "$UI_PID" 2>/dev/null
  kill "$WD_PID" 2>/dev/null
}
trap cleanup EXIT

for _ in $(seq 1 60); do
  curl -sf -m 2 "http://127.0.0.1:$AGENT_PORT/healthz" >/dev/null 2>&1 && break
  sleep 1
done
if curl -sf -m 2 "http://127.0.0.1:$AGENT_PORT/healthz" >/dev/null; then
  ok "agent answering on :$AGENT_PORT"
else
  bad "agent never came up"
  tail -40 agent-run.log
  exit 1
fi

# --- 2. auth ---------------------------------------------------------------
say "2. initialize auth"
TOK=$(curl -s -X POST "http://127.0.0.1:$AGENT_PORT/v1/auth/initialize" \
  -H 'content-type: application/json' \
  -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
if [ -n "${TOK:-}" ]; then
  ok "operator session token issued"
else
  bad "no session token"
  tail -30 agent-run.log
  exit 1
fi
AUTH=(-H "Authorization: Bearer $TOK")

# Initializing auth restarts every supervised child on purpose — that is
# how they receive the master key — so the library seen above is already
# gone and a fresh one is coming up. `library exited rc=1` in the log is
# that restart, not a crash.
note "children are restarted by auth init; waiting for the library to come back"
for _ in $(seq 1 45); do
  S=$(curl -s "${AUTH[@]}" "http://127.0.0.1:$AGENT_PORT/v1/components" \
    | jq_ "' '.join(f\"{c['name']}={c.get('status')}\" for c in d.get('components',[]))" 2>/dev/null)
  case "$S" in *"library=running"*) break ;; esac
  sleep 1
done
case "$S" in
  *"library=running"*) ok "library running, spawned by the supervisor" ;;
  *) bad "library not running (saw: ${S:-nothing})"; tail -40 agent-run.log ;;
esac

# --- 3. the UI ------------------------------------------------------------
say "3. start the UI and load the discovery page"
cd "$EP_ROOT/ui" || exit 1
PORT="$UI_PORT" AGENT_URL="http://127.0.0.1:$AGENT_PORT" \
  npm run start -- --port "$UI_PORT" > "$EP_WORKDIR/ui-run.log" 2>&1 &
UI_PID=$!
cd "$EP_WORKDIR" || exit 1

for _ in $(seq 1 60); do
  curl -sf -m 2 -o /dev/null "http://127.0.0.1:$UI_PORT/discover" 2>/dev/null && break
  sleep 1
done
HTML=$(curl -s -m 10 "http://127.0.0.1:$UI_PORT/discover")
case "$HTML" in
  *"Discover"*) ok "/discover served by the UI" ;;
  *) bad "/discover did not render"; tail -30 "$EP_WORKDIR/ui-run.log" ;;
esac
case "$HTML" in
  *"search models"*) ok "the search box is in the markup" ;;
  *) bad "the discovery page rendered without its search box" ;;
esac

# --- 4. the proxy resolves the library by KIND ----------------------------
say "4. through the UI's proxy — no component URL is known to the browser"
HW=$(ui /v1/hardware)
HOSTNAME_=$(printf '%s' "$HW" | jq_ "d.get('hostname','')" 2>/dev/null)
if [ -n "${HOSTNAME_:-}" ]; then
  ok "GET /api/proxy/library/v1/hardware → $HOSTNAME_"
else
  bad "the proxy could not reach the library: $(printf '%s' "$HW" | head -c 200)"
fi
GPUS=$(printf '%s' "$HW" | jq_ "len(d.get('gpus') or [])" 2>/dev/null)
FREE=$(printf '%s' "$HW" | jq_ "((d.get('gpus') or [{}])[0].get('vramFreeBytes') or 0)//2**20" 2>/dev/null)
TOTAL=$(printf '%s' "$HW" | jq_ "((d.get('gpus') or [{}])[0].get('vramTotalBytes') or 0)//2**20" 2>/dev/null)
note "${GPUS:-0} GPU(s); first reports ${FREE:-0} MiB free of ${TOTAL:-0} MiB"
if [ "${TOTAL:-0}" -gt 0 ] && [ "${FREE:-0}" -lt "${TOTAL:-0}" ]; then
  ok "free VRAM is below total — the number fit verdicts are scored against"
elif [ "${TOTAL:-0}" -eq 0 ]; then
  note "no GPU here; fit will be scored against host memory"
else
  bad "free VRAM equals total, which no desktop reports"
fi

TIERS=$(ui /v1/quants | jq_ "len(d.get('tiers') or [])" 2>/dev/null)
[ "${TIERS:-0}" -ge 10 ] && ok "the quant table came through the proxy ($TIERS tiers)" \
  || bad "quant table looks wrong (tiers=${TIERS:-0})"

# --- 5. search ------------------------------------------------------------
say "5. search the catalogue"
SEARCH=$(ui "/v1/catalogue/search?q=qwen3&format=gguf&limit=5")
COUNT=$(printf '%s' "$SEARCH" | jq_ "len(d.get('results') or [])" 2>/dev/null)
if [ "${COUNT:-0}" -gt 0 ]; then
  ok "$COUNT repos returned"
  note "$(printf '%s' "$SEARCH" | jq_ "d['results'][0]['repo']" 2>/dev/null)"
else
  bad "search returned nothing: $(printf '%s' "$SEARCH" | head -c 200)"
fi
HAS_SIZE=$(printf '%s' "$SEARCH" | jq_ "any('sizeBytes' in r for r in (d.get('results') or []))" 2>/dev/null)
[ "$HAS_SIZE" = "False" ] && ok "no sizes on a search row — upstream does not send them" \
  || bad "a search row carried a size, which upstream cannot have provided"

# --- 6. detail, grouped into choices, each scored ------------------------
say "6. one repo → launchable choices, with the fit attached"
DETAIL=$(ui "/v1/catalogue/model?repo=$EP_REPO&contextLength=32768")
CANDS=$(printf '%s' "$DETAIL" | jq_ "len(d.get('candidates') or [])" 2>/dev/null)
PROJ=$(printf '%s' "$DETAIL" | jq_ "len(d.get('projectors') or [])" 2>/dev/null)
OTHER=$(printf '%s' "$DETAIL" | jq_ "len(d.get('otherFiles') or [])" 2>/dev/null)
if [ "${CANDS:-0}" -gt 1 ]; then
  ok "$CANDS candidates, $PROJ projector(s), $OTHER other file(s)"
else
  bad "no candidates: $(printf '%s' "$DETAIL" | head -c 300)"
fi

UNIQUE=$(printf '%s' "$DETAIL" | jq_ "len({c['label'] for c in (d.get('candidates') or [])})" 2>/dev/null)
if [ "${UNIQUE:-0}" = "${CANDS:-1}" ]; then
  ok "every label is distinct — this is the bug the first live run found"
else
  bad "$CANDS candidates but only $UNIQUE distinct labels"
fi

SCORED=$(printf '%s' "$DETAIL" | jq_ "sum(1 for c in (d.get('candidates') or []) if c.get('fit'))" 2>/dev/null)
[ "${SCORED:-0}" = "${CANDS:-1}" ] && ok "all $SCORED carry a fit verdict on the same response" \
  || bad "only $SCORED of $CANDS were scored"

REC=$(printf '%s' "$DETAIL" | jq_ "(d.get('recommended') or {}).get('label','')" 2>/dev/null)
if [ -n "${REC:-}" ]; then
  ok "recommended: $REC"
  note "$(printf '%s' "$DETAIL" | jq_ "(d.get('recommended') or {}).get('reason','')" 2>/dev/null | head -c 220)"
else
  note "nothing fits this machine at 32k — a legible outcome, not a failure"
fi

SPLIT=$(printf '%s' "$DETAIL" | jq_ "max([len(c['files']) for c in (d.get('candidates') or [])] or [0])" 2>/dev/null)
[ "${SPLIT:-0}" -gt 1 ] && ok "a split candidate is one row of $SPLIT files, summed" \
  || note "no split candidate in this repo"

BPW=$(printf '%s' "$DETAIL" | jq_ "sum(1 for c in (d.get('candidates') or []) if c.get('bitsPerWeight'))" 2>/dev/null)
[ "${BPW:-0}" -gt 0 ] && ok "$BPW candidates carry a measured bits-per-weight" \
  || bad "no candidate reported bits per weight"

# --- 7. the ranged metadata read -----------------------------------------
say "7. preflight — read the real metadata without downloading the model"
T0=$(date +%s)
PF=$(ui "/v1/catalogue/model/preflight?repo=$EP_REPO&file=$EP_PREFLIGHT_FILE&contextLength=32768")
T1=$(date +%s)
READ=$(printf '%s' "$PF" | jq_ "d.get('bytesRead',0)" 2>/dev/null)
FT=$(printf '%s' "$PF" | jq_ "d.get('fileType')" 2>/dev/null)
BLOCKS=$(printf '%s' "$PF" | jq_ "d.get('blockCount')" 2>/dev/null)
ATTN=$(printf '%s' "$PF" | jq_ "d.get('attentionLayers')" 2>/dev/null)
BASIS=$(printf '%s' "$PF" | jq_ "(d.get('fit') or {}).get('basis','')" 2>/dev/null)
if [ -n "${FT:-}" ] && [ "$FT" != "None" ]; then
  ok "quant read from the file's own metadata (file_type=$FT), $((READ / 1000000)) MB in $((T1 - T0))s"
else
  bad "preflight did not return a machine-read quant: $(printf '%s' "$PF" | head -c 300)"
fi
if [ -n "${ATTN:-}" ] && [ "$ATTN" != "None" ] && [ "${ATTN:-0}" -lt "${BLOCKS:-1}" ]; then
  ok "hybrid attention detected: $ATTN of $BLOCKS layers hold a KV cache"
  note "assuming all $BLOCKS would over-estimate the cache by $((BLOCKS / ATTN))x"
else
  note "attentionLayers=$ATTN blockCount=$BLOCKS — not a hybrid model, or not reported"
fi
[ "$BASIS" = "metadata" ] && ok "the fit is now arithmetic rather than an estimate" \
  || bad "fit basis is '$BASIS' after a preflight"

# --- 8. a real download, through the proxy -------------------------------
say "8. download $EP_SMALL_FILE into $EP_MODEL_ROOT"
START=$(curl -s -m 60 "${AUTH[@]}" -X POST \
  -H 'content-type: application/json' \
  -d "{\"repo\":\"$EP_REPO\",\"files\":[\"$EP_SMALL_FILE\"]}" \
  "http://127.0.0.1:$UI_PORT/api/proxy/library/v1/downloads")
DID=$(printf '%s' "$START" | jq_ "d.get('id','')" 2>/dev/null)
DEST=$(printf '%s' "$START" | jq_ "d.get('destinationDirectory','')" 2>/dev/null)
COMMIT=$(printf '%s' "$START" | jq_ "d.get('resolvedCommit','')" 2>/dev/null)
if [ -n "${DID:-}" ]; then
  ok "accepted: $DID"
  [ -n "${DEST:-}" ] && ok "destination resolved before any bytes moved: $DEST" \
    || bad "no destination on the accepted record"
  [ -n "${COMMIT:-}" ] && ok "pinned to commit ${COMMIT:0:12} rather than a moving branch" \
    || bad "no commit pinned"
else
  bad "download refused: $(printf '%s' "$START" | head -c 300)"
fi

STATE=""
for _ in $(seq 1 120); do
  REC_JSON=$(ui "/v1/downloads/$DID")
  STATE=$(printf '%s' "$REC_JSON" | jq_ "d.get('state','')" 2>/dev/null)
  case "$STATE" in done|failed|cancelled) break ;; esac
  sleep 1
done
if [ "$STATE" = "done" ]; then
  ok "transfer complete"
else
  bad "download ended in '$STATE': $(printf '%s' "$REC_JSON" | jq_ "d.get('error','')" 2>/dev/null)"
fi
VERIFIED=$(printf '%s' "$REC_JSON" | jq_ "(d['files'][0].get('verified'))" 2>/dev/null)
[ "$VERIFIED" = "True" ] && ok "digest verified before the rename" \
  || bad "the file was not verified (verified=$VERIFIED)"

LANDED=$(printf '%s' "$REC_JSON" | jq_ "d['files'][0]['destinationPath']" 2>/dev/null)
LANDED_UNIX=$(to_shell "$LANDED")
if [ -f "$LANDED_UNIX" ]; then
  ok "on disk at $LANDED"
else
  bad "not found on disk at $LANDED"
fi
case "$LANDED_UNIX" in
  *"$EP_SMALL_FILE") ok "kept its upstream name — nothing renamed, nothing hashed" ;;
  *) bad "landed under a different name: $LANDED" ;;
esac
[ -f "$LANDED_UNIX.part" ] && bad "a .part survived a completed download" \
  || ok "no .part left behind"
case "$LANDED_UNIX" in
  *"/unsloth/Qwen3.8-27B-GGUF/"*) ok "filed as <root>/<publisher>/<repo>/" ;;
  *) note "layout: $LANDED" ;;
esac

MID=$(printf '%s' "$REC_JSON" | jq_ "d.get('modelId','')" 2>/dev/null)
if [ -n "${MID:-}" ]; then
  ok "the post-download scan found it: model $MID"
else
  bad "no modelId — the download did not become a library entry"
fi

# --- 9. the library now has it, and can measure it ----------------------
say "9. the model the download created"
MODELS=$(ui /v1/models)
FOUND=$(printf '%s' "$MODELS" | jq_ "len(d.get('models') or [])" 2>/dev/null)
[ "${FOUND:-0}" -ge 1 ] && ok "$FOUND model(s) in a directory that was empty at boot" \
  || bad "the library sees no models"

if [ -n "${MID:-}" ]; then
  FIT=$(ui "/v1/models/$MID/fit?contextLength=4096")
  VERDICT=$(printf '%s' "$FIT" | jq_ "(d.get('fit') or {}).get('verdict','')" 2>/dev/null)
  [ -n "${VERDICT:-}" ] && ok "local fit answered: $VERDICT" \
    || bad "no fit for the downloaded model: $(printf '%s' "$FIT" | head -c 200)"
fi

# --- 10. the air-gap switch ----------------------------------------------
say "10. catalogueEnabled=false is a legible refusal"
curl -s -m 20 "${AUTH[@]}" -X PATCH -H 'content-type: application/json' \
  -d '{"catalogueEnabled": false}' \
  "http://127.0.0.1:$UI_PORT/api/proxy/library/v1/config" >/dev/null
CODE=$(curl -s -m 20 -o /dev/null -w '%{http_code}' "${AUTH[@]}" \
  "http://127.0.0.1:$UI_PORT/api/proxy/library/v1/catalogue/search?q=qwen")
[ "$CODE" = "409" ] && ok "409, not a timeout" || bad "expected 409, got $CODE"
curl -s -m 20 "${AUTH[@]}" -X PATCH -H 'content-type: application/json' \
  -d '{"catalogueEnabled": true}' \
  "http://127.0.0.1:$UI_PORT/api/proxy/library/v1/config" >/dev/null

# --- 11. teardown --------------------------------------------------------
say "11. teardown"
kill "$UI_PID" 2>/dev/null
kill "$WD_PID" 2>/dev/null
for _ in $(seq 1 20); do
  kill -0 "$WD_PID" 2>/dev/null || break
  sleep 1
done
ok "processes stopped"
[ -f "$LANDED_UNIX" ] && ok "the downloaded file is still there — deleting us does not delete models" \
  || bad "the model vanished when the processes stopped"

say "result"
if [ "$FAILURES" -eq 0 ]; then
  echo "M3 acceptance PASSED — three processes, a model discovered, scored and fetched through the UI's own proxy."
else
  echo "$FAILURES check(s) FAILED"
fi
echo "install left at $EP_WORKDIR (agent-run.log and ui-run.log have every child's output)"
exit "$FAILURES"
