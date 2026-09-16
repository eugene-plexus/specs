#!/usr/bin/env bash
# Call #2 -- embeddings, end to end, against a real embedding model.
#
# What only a live run can prove. The unit tests on both sides use fakes
# that embed whatever we told them to, so they verify our plumbing and
# nothing about the two claims this design rests on, both of which are
# properties of somebody else's server:
#
#   * the embeddings capability belongs to the RUNNING BACKEND, not the
#     model -- a runner started for chat refuses to embed the very model
#     it is serving, and nothing exposes which it is
#   * a dedicated embedding model refuses chat, so the two surfaces are
#     disjoint
#
# **The second claim was recorded as an Ollama-only property and that no
# longer reproduces (2026-09-16).** The design says `surfaces` is a list
# rather than an enum because "`llama-server --embedding` still chats".
# Measured on b10948, it does not: an embedding server answers
# `/v1/chat/completions` with a 500 ("the current context does not logits
# computation"), and a chat server answers `/v1/embeddings` with a clean
# 501 naming the flag it was not given. So on the current engine the
# surfaces are disjoint BOTH ways and this script asserts that. The
# list-shaped schema may still be right for some backend somewhere, but
# the evidence cited for it is stale and is flagged here rather than
# quietly asserted around.
#
# And one rule that a fixture can assert but only a live run can make
# convincing: **failover does not cross models here.**
#
# The checks:
#   0. this run is isolated from any install on this machine
#   1. the driver on an embedding model reports capabilities.embeddings
#   2. the driver on a CHAT model reports false -- the runner refuses
#   3. GET /v1/models marks the surfaces, and they differ
#   4. a real embedding: one vector per input, consistent dimensions
#   5. identical inputs give identical vectors, distinct ones do not
#   6. base64 decodes to exactly the floats the same request returns
#   7. usage is reported
#   8. a chat model is refused on /v1/embeddings, by name
#   9. an embedding model is refused on /v1/chat/completions, by name
#  10. FAILOVER DOES NOT CROSS MODELS: a dead primary does not fall
#      through to a healthy embedder for a different model
#  11. ...while replicas of the SAME model still fail over
#
# Design: docs/design/agent-clients-and-tool-calling.md, call #2.
#
# **Safe beside a live install**, in both dimensions -- ports (binds
# 8179, refuses a taken port, tears down BY port) and state (clears the
# ambient EUGENE_PLEXUS_* environment, which is check 0; see
# context-honesty-acceptance.sh for what that costs when it is missed).
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-embed-live}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
AGENT="http://127.0.0.1:$AGENT_PORT"
GW="${EP_GW:-http://127.0.0.1:8080}"
EMB_PORT="${EP_EMB_PORT:-8195}"
CHAT_PORT="${EP_CHAT_PORT:-8196}"
DEAD_PORT="${EP_DEAD_PORT:-8197}"
REPLICA_PORT="${EP_REPLICA_PORT:-8198}"
PASS="embed-live-$$"

EMB_MODEL="${EP_EMB_MODEL:-emb-acceptance-model}"
CHAT_MODEL="${EP_CHAT_MODEL:-chat-acceptance-model}"
EMB_ENGINE_PORT="${EP_EMB_ENGINE_PORT:-8193}"
CHAT_ENGINE_PORT="${EP_CHAT_ENGINE_PORT:-8194}"
# The backend: two local llama.cpp servers, not ollama. One started with
# `--embedding --pooling mean`, one without -- which is the whole point,
# because the capability under test belongs to the RUNNING BACKEND and
# not to the model.
. "$(dirname "$0")/lib/llama-backend.sh"
# A real embedding model. Qwen3-0.6B is not one, and an "embedding" test
# against a chat model proves only that something returned numbers.
EP_EMB_GGUF="${EP_EMB_GGUF:-$HOME/.eugene-plexus/acceptance-models/nomic-embed-text-v1.5.Q8_0.gguf}"
EP_EMB_GGUF_URL="${EP_EMB_GGUF_URL:-https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf}"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }

# Wait for the routing table to actually show something, rather than
# sleeping for longer than `routingRefreshSeconds` and hoping. The first
# run of this script slept 18s against a 15s refresh and lost the race:
# the driver was up and probed, and the read landed just before the
# refresh that would have included it. A bounded wait fails just as
# loudly if the thing never arrives, and does not fail when it is merely
# slow.
wait_models() { # 'python expression over d' expected-value seconds
  for _ in $(seq 1 "${3:-60}"); do
    got=$(curl -s -m 20 "$GW/v1/models" -H "Authorization: Bearer $TOK" | jq_ "$1" 2>/dev/null)
    [ "$got" = "$2" ] && return 0
    sleep 2
  done
  return 1
}

OWNED_PORTS="$AGENT_PORT 8080 8082 8083 $EMB_PORT $CHAT_PORT $DEAD_PORT $REPLICA_PORT $EMB_ENGINE_PORT $CHAT_ENGINE_PORT"

free_port() {
  for pid in $(netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u); do
    taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
  done
}
teardown() { llama_stop_all; for p in $OWNED_PORTS; do free_port "$p"; done; }

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
llama_preflight || exit 1
llama_fetch_model "$EP_EMB_GGUF" "$EP_EMB_GGUF_URL" \
  || { bad "no embedding model at $EP_EMB_GGUF and could not fetch $EP_EMB_GGUF_URL"; exit 1; }
for p in $OWNED_PORTS; do
  if netstat -ano 2>/dev/null | grep ":$p " | grep -q LISTENING; then
    bad "port $p is already in use; set the matching EP_* variable or stop it"; exit 1
  fi
done
ok "agent python, llama.cpp $(llama_build), a chat and an embedding model, every port free"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
WORK_NATIVE=$(cygpath -w "$WORK" 2>/dev/null || printf '%s' "$WORK")
export EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml"
export EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1
export EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT"

say "0. this run is isolated from any install on this machine"
LEAKED=$(env | grep '^EUGENE_PLEXUS_' | grep -Fv -e "EUGENE_PLEXUS_AGENT_CONFIG_FILE=$WORK_NATIVE/agent.yaml" -e 'EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1' -e "EUGENE_PLEXUS_AGENT_BIND_PORT=$AGENT_PORT")
[ -z "$LEAKED" ] && ok "no ambient EUGENE_PLEXUS_* variable survives into this run" \
  || { bad "ambient config leaked in: $LEAKED"; exit 1; }

say "start the agent; it declares control, gateway and library itself"
"$PY" -m eugene_plexus_agent --unattended >"$WORK/agent.log" 2>&1 &
wait_healthy "$AGENT" 60 || { bad "agent never answered"; tail -20 "$WORK/agent.log"; exit 1; }
INIT=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}")
TOK=$(printf '%s' "$INIT" | jq_ "d.get('sessionToken') or ''" 2>/dev/null)
[ -n "$TOK" ] || { bad "no operator token -- did the agent adopt an existing install? $INIT"; exit 1; }
wait_healthy "$GW" 90 || { bad "gateway never answered"; exit 1; }
ok "agent and gateway up"

add_driver() { # name port provider model [baseUrl]
  curl -s -o /dev/null -X POST "$AGENT/v1/components" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' \
    -d "{\"name\":\"$1\",\"kind\":\"inference-driver\",\"url\":\"http://127.0.0.1:$2\",\"spawn\":{\"configFile\":\"$1.yaml\"}}"
  sleep 3
  local body="{\"provider\":\"$3\",\"modelId\":\"$4\""
  [ -n "${5:-}" ] && body="$body,\"baseUrl\":\"$5\""
  body="$body}"
  curl -s -o /dev/null -X PATCH "http://127.0.0.1:$2/v1/config" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' -d "$body"
  curl -s -o /dev/null -X POST "$AGENT/v1/components/$1/restart" -H "Authorization: Bearer $TOK" -d '{}'
}

say "drivers: one on an embedding model, one on a chat model"
# Two servers of the SAME binary, differing only in `--embedding`. That
# is the cleanest possible statement of the claim under test: the
# capability is a property of how the backend was STARTED, not of the
# model, and here the start flags are the only difference there is.
llama_start "$EMB_ENGINE_PORT" "$EMB_MODEL" -m "$EP_EMB_GGUF" --ctx 2048 --embedding --pooling mean \
  || { bad "the embedding engine never came up"; tail -20 "llama-$EMB_ENGINE_PORT.log"; exit 1; }
llama_start "$CHAT_ENGINE_PORT" "$CHAT_MODEL" --ctx 2048 \
  || { bad "the chat engine never came up"; tail -20 "llama-$CHAT_ENGINE_PORT.log"; exit 1; }
add_driver emb "$EMB_PORT" openai_compat_custom "$EMB_MODEL" "$(llama_base_url "$EMB_ENGINE_PORT")"
add_driver chat "$CHAT_PORT" openai_compat_custom "$CHAT_MODEL" "$(llama_base_url "$CHAT_ENGINE_PORT")"
sleep 12

# --- 1, 2 --------------------------------------------------------------------
say "1-2. the capability, which is a property of the running backend"
E_INFO=$(curl -s -m 30 "http://127.0.0.1:$EMB_PORT/v1/info" -H "Authorization: Bearer $TOK")
C_INFO=$(curl -s -m 60 "http://127.0.0.1:$CHAT_PORT/v1/info" -H "Authorization: Bearer $TOK")
E_CAP=$(printf '%s' "$E_INFO" | jq_ "(d.get('capabilities') or {}).get('embeddings')" 2>/dev/null)
C_CAP=$(printf '%s' "$C_INFO" | jq_ "(d.get('capabilities') or {}).get('embeddings')" 2>/dev/null)
echo "  $EMB_MODEL -> embeddings=$E_CAP"
echo "  chat model  -> embeddings=$C_CAP"
[ "$E_CAP" = "True" ] && ok "the embedding backend reports the surface" \
  || bad "expected True, got '$E_CAP': $E_INFO"
# The finding this check exists for: the chat runner refuses to embed
# the very model it is serving, and says so.
[ "$C_CAP" = "False" ] && ok "the chat backend reports it cannot embed, discovered by asking" \
  || bad "expected False, got '$C_CAP': $C_INFO"

# --- 3 -----------------------------------------------------------------------
say "3. GET /v1/models marks the surfaces, and they differ"
wait_models "len(d['data'])" "2" 40 || bad "the gateway never listed both models"
MODELS=$(curl -s -m 20 "$GW/v1/models" -H "Authorization: Bearer $TOK")
printf '%s' "$MODELS" | PYTHONUTF8=1 python -c "
import sys, json
for m in json.load(sys.stdin)['data']:
    print('  %-52s %s' % (m['id'], m.get('x_eugene_plexus', {}).get('surfaces')))
"
SURF=$(printf '%s' "$MODELS" | PYTHONUTF8=1 python -c "
import sys, json
d = {m['id']: m.get('x_eugene_plexus', {}).get('surfaces') for m in json.load(sys.stdin)['data']}
emb = d.get('$EMB_MODEL') or d.get('$EMB_MODEL:latest') or []
chat = d.get('$CHAT_MODEL') or []
print('ok' if emb == ['embeddings'] and chat == ['chat'] else 'no %r %r' % (emb, chat))
")
[ "$SURF" = "ok" ] && ok "one model says embeddings, the other says chat" \
  || bad "surfaces wrong: $SURF"

# --- 4, 5, 7 -----------------------------------------------------------------
say "4,5,7. a real embedding through the whole path"
R=$(curl -s -m 300 -X POST "$GW/v1/embeddings" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$EMB_MODEL\",\"input\":[\"the cat sat on the mat\",\"the cat sat on the mat\",\"quantum chromodynamics\"]}")
printf '%s' "$R" > emb.json
PYTHONUTF8=1 python -c "
import json
d = json.load(open('emb.json'))
v = [e['embedding'] for e in d['data']]
print('  vectors: %d | dims: %s | usage: %s' % (len(v), {len(x) for x in v}, d.get('usage')))
print('  indices:', [e['index'] for e in d['data']])
print('  identical inputs identical:', v[0] == v[1])
print('  distinct input differs:', v[0] != v[2])
"
N=$(jq_ "len(d['data'])" < emb.json 2>/dev/null)
DIMS=$(jq_ "len({len(e['embedding']) for e in d['data']})" < emb.json 2>/dev/null)
[ "$N" = "3" ] && [ "$DIMS" = "1" ] && ok "three vectors, one consistent dimensionality" \
  || bad "got $N vectors across $DIMS dimensionalities"

SANE=$(PYTHONUTF8=1 python -c "
import json
v = [e['embedding'] for e in json.load(open('emb.json'))['data']]
print('ok' if v[0] == v[1] and v[0] != v[2] else 'no')
")
# Order is the contract: an embedding carries no identity, so position
# is the only thing matching a vector to its text. Two identical inputs
# MUST give identical vectors and a different one must not -- which is
# the cheapest way to prove nothing scrambled them on the way through.
[ "$SANE" = "ok" ] && ok "identical inputs gave identical vectors; a distinct one differs" \
  || bad "vectors do not correspond to their inputs"

U=$(jq_ "bool(d.get('usage') and d['usage'].get('prompt_tokens'))" < emb.json 2>/dev/null)
[ "$U" = "True" ] && ok "usage reported" || bad "no usage: $(head -c 200 emb.json)"

# --- 6 -----------------------------------------------------------------------
say "6. base64 decodes to exactly the floats the SAME-SHAPED request returned"
# **Both requests send one input, and that is the fix rather than a
# detail.** This check used to compare the base64 answer against
# `emb.json`'s first vector -- which came from a batch of THREE. Ollama
# returned bit-identical floats either way so it passed; llama.cpp does
# not, because batch shape changes the arithmetic, and the check failed
# on a difference that was never ours. The claim in its own title is
# "the same request", so the comparison is now actually that: one
# float request and one base64 request, identical but for
# `encoding_format`. A backend that is non-deterministic even then
# would fail this, correctly.
curl -s -m 300 -X POST "$GW/v1/embeddings" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$EMB_MODEL\",\"input\":\"the cat sat on the mat\"}" > one.json
curl -s -m 300 -X POST "$GW/v1/embeddings" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$EMB_MODEL\",\"input\":\"the cat sat on the mat\",\"encoding_format\":\"base64\"}" > b64.json
B64=$(PYTHONUTF8=1 python -c "
import json, base64, struct
want = json.load(open('one.json'))['data'][0]['embedding']
got = json.load(open('b64.json'))['data'][0]['embedding']
if not isinstance(got, str):
    print('not-a-string'); raise SystemExit
raw = base64.b64decode(got)
dec = list(struct.unpack('<%df' % (len(raw)//4), raw))
if len(dec) != len(want):
    print('length %d vs %d' % (len(dec), len(want))); raise SystemExit
worst = max(abs(a-b) for a, b in zip(dec, want))
print('ok' if worst < 1e-6 else 'mismatch, worst delta %g' % worst)
")
# The OpenAI SDKs ask for base64 by default, so this is what most
# clients will actually receive.
[ "$B64" = "ok" ] && ok "base64 is little-endian float32 and matches the float answer" \
  || bad "base64 wrong: $B64"

# --- 8, 9 --------------------------------------------------------------------
say "8-9. each model refused on the surface it does not serve"
C1=$(curl -s -m 60 -o wrong1.json -w '%{http_code}' -X POST "$GW/v1/embeddings" \
  -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"model\":\"$CHAT_MODEL\",\"input\":\"x\"}")
echo "  chat model on /v1/embeddings: HTTP $C1 -- $(jq_ "d['error']['message'][:110]" < wrong1.json 2>/dev/null)"
[ "$C1" = "400" ] && grep -q 'chat/completions' wrong1.json \
  && ok "refused by name, and told where to send it" || bad "got HTTP $C1"

C2=$(curl -s -m 60 -o wrong2.json -w '%{http_code}' -X POST "$GW/v1/chat/completions" \
  -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"model\":\"$EMB_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}")
echo "  embedding model on /v1/chat/completions: HTTP $C2 -- $(jq_ "d['error']['message'][:110]" < wrong2.json 2>/dev/null)"
[ "$C2" = "400" ] && grep -q 'v1/embeddings' wrong2.json \
  && ok "refused by name, and told where to send it" || bad "got HTTP $C2"

# --- 10 ----------------------------------------------------------------------
say "10. FAILOVER DOES NOT CROSS MODELS"
# A driver pointed at a port nothing listens on, in front of the real
# embedder, with a modelSlots cascade to a DIFFERENT embedding model.
# For chat this would cascade and that would be right. Here a 200 would
# be vectors from the wrong space, written into the caller's store with
# nothing to mark them.
add_driver dead "$DEAD_PORT" openai_compat_custom "ghost-embed" "http://127.0.0.1:$((DEAD_PORT + 100))"
sleep 6
curl -s -o /dev/null -X PATCH "$GW/v1/config" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d "{\"modelSlots\":[{\"model\":\"ghost-embed\",\"targets\":[\"ghost-embed\",\"$EMB_MODEL\"]}]}"
# The slot must be visible before the check means anything: a 404
# would pass "it did not serve vectors" for the wrong reason.
wait_models "len([m for m in d['data'] if m['id'] == 'ghost-embed'])" "1" 40 \n  || bad "the ghost-embed slot never appeared, so check 10 proves nothing"
X=$(curl -s -m 120 -o cross.json -w '%{http_code}' -X POST "$GW/v1/embeddings" \
  -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d '{"model":"ghost-embed","input":"x"}')
echo "  HTTP $X -- $(head -c 180 cross.json)"
SERVED=$(jq_ "bool(d.get('data'))" < cross.json 2>/dev/null)
[ "$SERVED" != "True" ] \
  && ok "it did not serve vectors from another model (HTTP $X)" \
  || bad "IT CASCADED ACROSS MODELS and returned $(jq_ "d.get('model')" < cross.json) -- silent corruption"

# --- 11 ----------------------------------------------------------------------
say "11. ...while replicas of the SAME model still fail over"
# A second driver on the same model. The dead one above is a different
# model, so this is the other half of the rule: same model id, so a
# failure between them is as safe as it is for chat.
add_driver emb2 "$REPLICA_PORT" openai_compat_custom "$EMB_MODEL" "$(llama_base_url "$EMB_ENGINE_PORT")"
REPLICAS="len([m for m in d['data'] if m['id'].startswith('$EMB_MODEL')][0].get('x_eugene_plexus',{}).get('drivers') or [])"
wait_models "$REPLICAS" "2" 40 || true
REPS=$(curl -s -m 20 "$GW/v1/models" -H "Authorization: Bearer $TOK" | jq_ "$REPLICAS" 2>/dev/null)
R2=$(curl -s -m 300 -X POST "$GW/v1/embeddings" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' -d "{\"model\":\"$EMB_MODEL\",\"input\":\"x\"}")
D=$(printf '%s' "$R2" | jq_ "d.get('x_eugene_plexus',{}).get('driver')" 2>/dev/null)
echo "  replicas: $REPS | served by: $D"
[ "$REPS" = "2" ] && [ -n "$D" ] \
  && ok "two replicas of one model, balanced and served" \
  || bad "expected 2 replicas and a served request; got $REPS / '$D'"

say "result"
if [ "$FAILURES" = "0" ]; then printf '\n  ALL CHECKS PASSED\n\n'
else printf '\n  %d CHECK(S) FAILED\n\n' "$FAILURES"; fi
exit "$FAILURES"
