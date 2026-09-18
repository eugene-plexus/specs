#!/usr/bin/env bash
# R1.3 -- one fit path, and what `-c` and `--parallel` actually do. Live.
#
# Roadmap: docs/design/release-roadmap.md §2.3. Findings: review §6.1 #4,
# §6.3 #36.
#
# What only a live run can prove.
#
# **Check 1 is not a check, it is the measurement the copy rests on.**
# Review §6.3 #36 is a contradiction inside this repo -- the config
# descriptions say `-c` is per-slot and that memory multiplies with
# slots, `fit.py` and `admission.py` compute the opposite -- and the
# review marked it Plausible and explicitly did NOT verify which side is
# right, because it depends on current `llama-server` semantics and
# `--kv-unified` changes them. So the slice opened with a real launch of
# a real engine on a real model, and this re-runs it. Rewriting the copy
# off the unverified premise risked being wrong in the other direction.
#
# The rest is the golden path across process boundaries. The unit checks
# (`library/tests/test_one_fit_path.py`,
# `agent/tests/test_context_and_slots.py`) drive the route and the
# admission helpers in-process. None of them can prove that a real agent
# asking a real library about a real file on disk gets the per-layer
# number, which is what one-click Run writes into the `default` profile.
#
# The checks:
#   0. isolated from any install on this machine, and from its ports
#   1. **the measurement**: `-c 32768 --parallel 1` and `--parallel 4`
#      against the engine store's own llama-server. `n_ctx` -- the
#      allocated cache -- must be 32768 BOTH times, and the per-slot
#      window 32768 then 8192. That is `-c` being a total that slots
#      divide, and it is why the copy said the wrong thing
#   2. a real library, a written GGUF whose `head_count_kv` is an array
#      and whose `sliding_window_pattern` is a bool array, scanned
#   3. `GET /v1/models/{id}/fit` reports under 1 GiB of KV at 16k with
#      `basis: metadata`. Before this slice: tens of GiB, same basis
#   4. **two readers, one file, one number** -- the route's answer
#      against `preflight.shape_from_gguf` over the same bytes in a
#      separate interpreter. That divergence is the finding: 262,144
#      from one path and 4,864 from the other, both `basis: metadata`
#   5. a 65-layer per-layer array survives the scan. `_INLINE_ARRAY_LIMIT`
#      was 64 and the shipped starter block counts are 32, 42, 48 and 65
#   6. **the golden path**: a real agent's admission, consulting that
#      real library over HTTP, carries the same `maxContextLength`
#   7. the admission reason names the divided per-request window when a
#      launch asks for several slots
#   8. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped, ports are +100, teardown is by pid. Never
# `pkill -f eugene_plexus_`: this box is a worker node.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
LIB_PY="${EP_LIB_PY:-$EP_ROOT/library/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-r13}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
LIB_PORT="${EP_LIB_PORT:-8182}"
ENGINE_PORT="${EP_ENGINE_PORT:-8199}"
AGENT="http://127.0.0.1:$AGENT_PORT"
LIB="http://127.0.0.1:$LIB_PORT"
OWNED_PORTS="$AGENT_PORT $LIB_PORT $ENGINE_PORT"
PASSPHRASE="r13-$$"

# The engine and model the measurement uses. Any llama-server this box
# has installed and any small GGUF will do -- the subject is what `-c`
# and `--parallel` mean, which is not model-specific.
SERVER="${EP_LLAMA_SERVER:-}"
MODEL="${EP_GGUF:-}"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
skip() { printf '  SKIP  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }
kill_port() { for pid in $(listening_pids "$1"); do taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null; done; }

A_PID=""
L_PID=""
teardown() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 3; }
  [ -n "$L_PID" ] && kill "$L_PID" 2>/dev/null
  for p in $OWNED_PORTS; do kill_port "$p"; done
}

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
[ -f "$LIB_PY" ] || { bad "no library python at $LIB_PY"; exit 1; }
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
# Newest build NUMERICALLY, not by path. A plain `sort | tail -1` sorts
# the whole path, so an engine store under a later-named directory wins
# regardless of its build number -- the first execution measured b10991
# while b11001 sat beside it.
[ -n "$SERVER" ] || SERVER=$(find /tmp -maxdepth 5 -name llama-server.exe 2>/dev/null | sed -E 's#.*/b([0-9]+)/[^/]*$#\1 &#' | sort -rn | head -1 | cut -d' ' -f2-)
[ -n "$MODEL" ] || MODEL=$(find /tmp "$EP_ROOT/smoke-test" -maxdepth 6 -name '*.gguf' -size +50M 2>/dev/null | sort | head -1)
ok "interpreters present; ports $OWNED_PORTS free"

rm -rf "$WORK"; mkdir -p "$WORK/models"; cd "$WORK" || exit 1
trap teardown EXIT

# --- 0 -----------------------------------------------------------------------
say "0. isolate this run"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy NO_PROXY no_proxy
WORK_NATIVE=$(win_path "$WORK")
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }

# --- 1 -----------------------------------------------------------------------
say "1. THE MEASUREMENT: what -c and --parallel do to a real llama-server"
# Review §6.3 #36 marked this Plausible and did not verify it. Both
# halves of the contradiction cannot be right, and which one is wrong
# decides whether this slice edits two sentences or the arithmetic every
# launch is admitted against.
if [ -z "$SERVER" ] || [ ! -f "$SERVER" ] || [ -z "$MODEL" ] || [ ! -f "$MODEL" ]; then
  skip "no llama-server or GGUF on this box (set EP_LLAMA_SERVER / EP_GGUF)"
  note "the copy in llama_cpp.py rests on this; a run that skips it proves nothing about §6.3 #36"
else
  note "engine: $("$SERVER" --version 2>&1 | head -1)"
  note "model:  $(basename "$MODEL")"
  MODEL_NATIVE=$(win_path "$MODEL")
  for SLOTS in 1 4; do
    "$SERVER" -m "$MODEL_NATIVE" --host 127.0.0.1 --port "$ENGINE_PORT" \
      -c 32768 --parallel "$SLOTS" -ngl 99 --no-webui -v > "engine-$SLOTS.log" 2>&1 &
    for _ in $(seq 1 60); do curl -sf -m 2 "http://127.0.0.1:$ENGINE_PORT/health" >/dev/null 2>&1 && break; sleep 1; done
    SLOT_CTX=$(curl -s -m 5 "http://127.0.0.1:$ENGINE_PORT/props" \
      | jq_ "(d.get('default_generation_settings') or {}).get('n_ctx')" 2>/dev/null)
    # The allocated cache, off the engine's own log. `/props` does not
    # expose it -- `props.n_ctx` was absent on both builds measured --
    # which is exactly why a runtime reads back the divided number and
    # nothing says so. **`-v` is required**: without it the engine never
    # prints this line and the check reads an empty string, which is how
    # the first execution reported a correct engine as a failure.
    ALLOCATED=$(grep -oE "llama_context: +n_ctx +=+ary? *[0-9]+" "engine-$SLOTS.log"       | grep -oE "[0-9]+$" | head -1)
    [ -n "$ALLOCATED" ] || ALLOCATED=$(grep -E "llama_context: +n_ctx +=" "engine-$SLOTS.log"       | head -1 | grep -oE "[0-9]+$")
    note "--parallel $SLOTS: allocated n_ctx=$ALLOCATED, per-slot n_ctx=$SLOT_CTX"
    kill_port "$ENGINE_PORT"; sleep 2
    if [ "$ALLOCATED" = "32768" ]; then
      ok "--parallel $SLOTS: the cache is allocated for the full 32768 -- memory does not multiply"
    else
      bad "--parallel $SLOTS: allocated n_ctx is '$ALLOCATED', not 32768 -- the copy may have been right after all"
    fi
    EXPECT=$((32768 / SLOTS))
    if [ "$SLOT_CTX" = "$EXPECT" ]; then
      ok "--parallel $SLOTS: each request gets $EXPECT tokens -- the slots divide the context"
    else
      bad "--parallel $SLOTS: per-slot window is '$SLOT_CTX', expected $EXPECT"
    fi
  done
fi

# --- 2 -----------------------------------------------------------------------
say "2. a real library over a per-layer GGUF"
# The shape a real current 12B declares: `head_count_kv` an ARRAY, five
# layers in every six sliding over a 1024-token window with their own
# shorter key/value lengths, `sliding_window_pattern` a BOOL array. The
# writer below is the library's own test encoder, lifted so the run
# builds the file rather than needing one to exist.
cat > mkgguf.py <<'PY'
"""Write a GGUF with a per-layer attention shape. No model weights."""
import struct
import sys

T_UINT32, T_FLOAT32, T_BOOL, T_STRING, T_ARRAY, T_INT32 = 4, 6, 7, 8, 9, 5


def s(text):
    raw = text.encode()
    return struct.pack("<Q", len(raw)) + raw


def value(v):
    if isinstance(v, str):
        return struct.pack("<I", T_STRING) + s(v)
    if isinstance(v, bool):
        return struct.pack("<I", T_BOOL) + struct.pack("<?", v)
    if isinstance(v, int):
        return struct.pack("<I", T_UINT32) + struct.pack("<I", v)
    if isinstance(v, float):
        return struct.pack("<I", T_FLOAT32) + struct.pack("<f", v)
    if isinstance(v, list):
        # bool BEFORE int: a bool IS an int in Python, and a real file's
        # sliding_window_pattern is a bool array.
        if isinstance(v[0], bool):
            return (
                struct.pack("<I", T_ARRAY) + struct.pack("<I", T_BOOL)
                + struct.pack("<Q", len(v)) + b"".join(struct.pack("<?", x) for x in v)
            )
        if isinstance(v[0], str):
            return (
                struct.pack("<I", T_ARRAY) + struct.pack("<I", T_STRING)
                + struct.pack("<Q", len(v)) + b"".join(s(x) for x in v)
            )
        return (
            struct.pack("<I", T_ARRAY) + struct.pack("<I", T_INT32)
            + struct.pack("<Q", len(v)) + b"".join(struct.pack("<i", x) for x in v)
        )
    raise TypeError(type(v))


path, blocks = sys.argv[1], int(sys.argv[2])
pattern = [(i % 6) != 5 for i in range(blocks)]
kv = {
    "general.architecture": "llama",
    "general.type": "model",
    "general.name": f"R13 {blocks}L",
    "general.file_type": 15,
    "llama.block_count": blocks,
    "llama.context_length": 262144,
    "llama.embedding_length": 4096,
    "llama.attention.head_count": 32,
    "llama.attention.head_count_kv": [1 if p else 8 for p in pattern],
    "llama.attention.sliding_window_pattern": pattern,
    "llama.attention.sliding_window": 1024,
    "llama.attention.key_length": 128,
    "llama.attention.value_length": 128,
    "llama.attention.key_length_swa": 128,
    "llama.attention.value_length_swa": 128,
    "tokenizer.ggml.tokens": [f"t{i}" for i in range(128)],
}
body = bytearray(b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", len(kv)))
for key, v in kv.items():
    body += s(key) + value(v)
# Pad to something a scan will not dismiss as a stub.
body += b"\x00" * (8 * 1024 * 1024)
open(path, "wb").write(bytes(body))
print(path)
PY
"$LIB_PY" mkgguf.py "$WORK/models/per-layer-48.gguf" 48 >/dev/null
"$LIB_PY" mkgguf.py "$WORK/models/per-layer-65.gguf" 65 >/dev/null
ok "two GGUFs written: 48 and 65 blocks, per-layer head counts and a bool slide pattern"

cat > library.yaml <<YAML
modelRoots:
  - $WORK_NATIVE\\models
catalogueEnabled: false
scanOnStartup: true
YAML
(exec env EUGENE_PLEXUS_LIBRARY_CONFIG_FILE="$WORK_NATIVE/library.yaml" \
  EUGENE_PLEXUS_LIBRARY_BIND_HOST=127.0.0.1 \
  EUGENE_PLEXUS_LIBRARY_BIND_PORT="$LIB_PORT" \
  EUGENE_PLEXUS_LIBRARY_AUTH_DISABLED=1 \
  "$LIB_PY" -m eugene_plexus_library > library.log 2>&1) &
L_PID=$!
for _ in $(seq 1 60); do curl -sf -m 2 "$LIB/healthz" >/dev/null 2>&1 && break; sleep 1; done
for _ in $(seq 1 60); do
  [ "$(curl -s -m 3 "$LIB/v1/scan" | jq_ "d.get('state')" 2>/dev/null)" != "scanning" ] && break
  sleep 1
done
MODELS=$(curl -s -m 10 "$LIB/v1/models")
ID48=$(printf '%s' "$MODELS" | jq_ "next(m['id'] for m in d['models'] if '48' in m['path'])" 2>/dev/null)
ID65=$(printf '%s' "$MODELS" | jq_ "next(m['id'] for m in d['models'] if '65' in m['path'])" 2>/dev/null)
[ -n "$ID48" ] && [ -n "$ID65" ] && ok "both scanned" || { bad "scan found: $(printf '%s' "$MODELS" | head -c 300)"; }

# --- 3 -----------------------------------------------------------------------
say "3. the on-disk fit route reads the per-layer cache"
FIT=$(curl -s -m 10 "$LIB/v1/models/$ID48/fit?contextLength=16384")
KV=$(printf '%s' "$FIT" | jq_ "d['fit']['kvCacheBytes']")
BASIS=$(printf '%s' "$FIT" | jq_ "d['fit']['basis']")
MAXCTX=$(printf '%s' "$FIT" | jq_ "d.get('maxContextLength')")
note "kvCacheBytes=$KV basis=$BASIS maxContextLength=$MAXCTX"
if [ "${KV:-0}" -lt 1073741824 ]; then
  ok "KV at 16k is $(python -c "print(f'{$KV/1024**3:.3f}')") GiB -- the sliding layers are counted"
else
  bad "KV at 16k is $(python -c "print(f'{$KV/1024**3:.1f}')") GiB -- the scalar reader answered (review §6.1 #4)"
fi
[ "$BASIS" = "metadata" ] && ok "basis: metadata" || bad "basis is '$BASIS'"

# --- 4 -----------------------------------------------------------------------
say "4. two readers, one file, one number"
# The finding was 262,144 from one path and 4,864 from another for the
# same bytes, both `basis: metadata`. This reads the file a second time
# through `preflight.shape_from_gguf` -- the reader every OTHER fit path
# uses -- in its own interpreter, and compares.
EXPECT_KV=$("$LIB_PY" - "$WORK/models/per-layer-48.gguf" <<'PY'
import sys
from pathlib import Path

from eugene_plexus_library import preflight
from eugene_plexus_library._generated.models import KvCacheType
from eugene_plexus_library.formats import gguf

meta = gguf.read_metadata(Path(sys.argv[1]))
shape = preflight.shape_from_gguf(meta)
print(shape.kv_bytes(16384, KvCacheType.f16))
PY
)
note "route says $KV, preflight.shape_from_gguf says $EXPECT_KV"
[ "$KV" = "$EXPECT_KV" ] && ok "the two readers agree exactly" \
  || bad "the two readers disagree: $KV vs $EXPECT_KV -- there are two shape builders again"

# --- 5 -----------------------------------------------------------------------
say "5. a 65-layer per-layer array survives the scan"
# `_INLINE_ARRAY_LIMIT` was 64. The shipped starter block counts are 32,
# 42, 48 and 65, so the limit missed by one on a model in the product's
# own starter file -- the array was stepped over, the scalars answered,
# and the fit still said `basis: metadata`.
FIT65=$(curl -s -m 10 "$LIB/v1/models/$ID65/fit?contextLength=16384")
KV65=$(printf '%s' "$FIT65" | jq_ "d['fit']['kvCacheBytes']")
BASIS65=$(printf '%s' "$FIT65" | jq_ "d['fit']['basis']")
note "65-layer: kvCacheBytes=$KV65 basis=$BASIS65"
if [ "${KV65:-0}" -lt 1073741824 ] && [ "$BASIS65" = "metadata" ]; then
  ok "the 65-element array was stored and read"
else
  bad "the 65-layer array did not survive the scan: $KV65 bytes, basis $BASIS65"
fi

# --- 6 -----------------------------------------------------------------------
say "6. the golden path: a real agent's admission asks that real library"
cat > agent.yaml <<YAML
firstRunComplete: true
components:
  - name: library
    kind: library
    url: $LIB
YAML
(exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" \
  EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 \
  EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
  "$PY" -m eugene_plexus_agent --unattended > agent.log 2>&1) &
A_PID=$!
for _ in $(seq 1 60); do curl -sf -m 2 "$AGENT/healthz" >/dev/null 2>&1 && break; sleep 1; done
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' \
  -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] && ok "agent up, operator session issued" || { bad "no session"; tail -20 agent.log; }
AUTH=(-H "Authorization: Bearer $TOK")

SPEC=$(python -c "
import json, sys
print(json.dumps({'name':'r13','engine':'llama_cpp',
  'modelPath': r'''$(win_path "$WORK/models/per-layer-48.gguf")''',
  'flags': {'contextSize': 16384}}))
")
ADM=$(curl -s -m 30 "${AUTH[@]}" -H 'Content-Type: application/json' -d "$SPEC" \
  "$AGENT/v1/runtimes/admission")
A_BASIS=$(printf '%s' "$ADM" | jq_ "d.get('basis')")
A_MAX=$(printf '%s' "$ADM" | jq_ "d.get('maxContextLength')")
note "admission basis=$A_BASIS maxContextLength=$A_MAX (library said $MAXCTX)"
if [ "$A_BASIS" = "metadata" ]; then
  ok "admission measured against library metadata, not file size"
else
  note "admission basis is '$A_BASIS' -- it did not reach the library; the comparison below is weak"
fi
if [ -n "$A_MAX" ] && [ "$A_MAX" != "None" ] && [ "$A_MAX" = "$MAXCTX" ]; then
  ok "the agent and the library print the SAME maxContextLength ($A_MAX)"
elif [ "$A_MAX" = "None" ] || [ -z "$A_MAX" ]; then
  bad "admission carried no maxContextLength: $(printf '%s' "$ADM" | head -c 300)"
else
  bad "the agent says $A_MAX and the library says $MAXCTX for the same file"
fi

# --- 7 -----------------------------------------------------------------------
say "7. the admission reason names the divided per-request window"
SPEC4=$(python -c "
import json
print(json.dumps({'name':'r13b','engine':'llama_cpp',
  'modelPath': r'''$(win_path "$WORK/models/per-layer-48.gguf")''',
  'flags': {'contextSize': 32768, 'parallelSlots': 4}}))
")
ADM4=$(curl -s -m 30 "${AUTH[@]}" -H 'Content-Type: application/json' -d "$SPEC4" \
  "$AGENT/v1/runtimes/admission")
REASON=$(printf '%s' "$ADM4" | jq_ "d.get('reason','')")
note "reason: $(printf '%s' "$REASON" | head -c 220)"
case "$REASON" in
  *"8,192"*) ok "the reason states the per-request window measured in check 1" ;;
  *) bad "the reason does not name the divided window: $REASON" ;;
esac

# --- 8 -----------------------------------------------------------------------
say "8. teardown"
teardown
A_PID=""; L_PID=""
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ] && ok "no owned port still listening" || bad "still listening:$STILL"

printf '\n===============================================\n'
if [ "$FAILURES" -eq 0 ]; then
  printf 'R1.3 ACCEPTANCE: all checks passed\n'
else
  printf 'R1.3 ACCEPTANCE: %d FAILURE(S)\n' "$FAILURES"
fi
printf '===============================================\n'
exit "$FAILURES"
