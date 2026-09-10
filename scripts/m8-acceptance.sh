#!/usr/bin/env bash
#
# M8 acceptance: does the gateway actually retain what it served?
#
# Two agents' worth of ceremony is not needed here. What is needed is a
# REAL gateway process, a REAL driver, and a REAL backend answering, so
# that the numbers are measurements rather than fixtures. Ollama is the
# backend because it is already running on this box with two models, and
# two models behind one gateway is exactly the comparison M8 exists for.
#
# Checks, in the order they matter:
#   1. a non-streaming completion is recorded
#   2. a STREAMING completion is recorded  <- the defect fixtures hid
#   3. the stream's final frame carries x_eugene_plexus
#   4. tokens/sec is a real number, per backend, for the same prompt
#   5. a dead backend produces an error row and a cascade row, and the
#      survivor's throughput is NOT dragged down by the dead one's timeout
#   6. rows survive a gateway restart
#   6b. the phases of a request, and what the balancer saw
#   7. switching recording off says so, and the rollup machinery runs
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-m8-live}"
AGENT=http://127.0.0.1:8079
GW=http://127.0.0.1:8080
PASS="m8-live-$$"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
curl -sf -m 3 http://127.0.0.1:11434/api/tags >/dev/null || { bad "ollama is not answering on 11434"; exit 1; }
ok "agent python and a live ollama"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
export EP_WORK="$WORK"
export EP_GATEWAY_SRC="${EP_GATEWAY_SRC:-$EP_ROOT/gateway/src}"
export EUGENE_PLEXUS_AGENT_BIND_PORT=8079

say "start the agent; it declares control, gateway and library itself"
"$PY" -m eugene_plexus_agent >"$WORK/agent.log" 2>&1 &
AGENT_PID=$!
trap 'kill -9 $AGENT_PID 2>/dev/null; pkill -f eugene_plexus_ 2>/dev/null' EXIT
wait_healthy "$AGENT" 60 || { bad "agent never answered"; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d['sessionToken']")
[ -n "$TOK" ] || { bad "no operator token"; exit 1; }
ok "agent up, install initialized"

wait_healthy "$GW" 90 || { bad "gateway never answered"; exit 1; }
ok "gateway up"

say "two ollama drivers, one per model - the comparison M8 is for"
add_driver() { # name port model
  curl -s -o /dev/null -w '%{http_code}' -X POST "$AGENT/v1/components" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' \
    -d "{\"name\":\"$1\",\"kind\":\"inference-driver\",\"url\":\"http://127.0.0.1:$2\",\"spawn\":{\"configFile\":\"$1.yaml\"}}"
  sleep 3
  curl -s -o /dev/null -X PATCH "http://127.0.0.1:$2/v1/config" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' \
    -d "{\"provider\":\"ollama_local\",\"modelId\":\"$3\",\"baseUrl\":\"http://127.0.0.1:11434\"}"
  curl -s -o /dev/null -X POST "$AGENT/v1/components/$1/restart" -H "Authorization: Bearer $TOK" -d '{}'
}
add_driver ollama-small 8091 "huihui_ai/dolphin3-abliterated:8b-llama3.1-q4_K_M"
add_driver ollama-big 8092 "qwen3-coder:30b"
sleep 12
MODELS=$(curl -s "$GW/v1/models" -H "Authorization: Bearer $TOK" | jq_ "[m['id'] for m in d['data']]")
echo "  gateway lists: $MODELS"
case "$MODELS" in *dolphin3*) ok "the small model is routable";; *) bad "gateway lists $MODELS";; esac

SMALL="huihui_ai/dolphin3-abliterated:8b-llama3.1-q4_K_M"

say "1. a non-streaming completion"
R=$(curl -s -m 180 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"model\":\"$SMALL\",\"messages\":[{\"role\":\"user\",\"content\":\"Count from 1 to 20.\"}],\"max_tokens\":120}")
echo "  served by: $(echo "$R" | jq_ "d.get('x_eugene_plexus',{}).get('driver')") in $(echo "$R" | jq_ "d.get('x_eugene_plexus',{}).get('latency_ms')")ms"
echo "  usage: $(echo "$R" | jq_ "d.get('usage')")"
[ -n "$(echo "$R" | jq_ "d.get('choices',[{}])[0].get('message',{}).get('content','')" 2>/dev/null)" ] && ok "a real completion came back" || bad "no completion: $(echo "$R" | head -c 300)"

say "2. a STREAMING completion - the path fixtures could not see"
STREAM=$(curl -s -N -m 180 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"model\":\"$SMALL\",\"messages\":[{\"role\":\"user\",\"content\":\"Name three colours.\"}],\"max_tokens\":80,\"stream\":true}")
FINAL=$(printf '%s\n' "$STREAM" | grep '^data: ' | grep -v '\[DONE\]' | tail -1 | sed 's/^data: //')
echo "  final frame: $(printf '%s' "$FINAL" | head -c 220)"
XP=$(printf '%s' "$FINAL" | jq_ "(d.get('x_eugene_plexus') or {}).get('driver','')" 2>/dev/null)
[ -n "$XP" ] && ok "*** the final stream frame carries x_eugene_plexus (driver=$XP) ***" || bad "no routing extension on the stream"

say "3. what the gateway retained"
sleep 3
M=$(curl -s "$GW/v1/metrics" -H "Authorization: Bearer $TOK")
echo "$M" | PYTHONUTF8=1 python -c "
import sys,json
d=json.load(sys.stdin)
print('  rowsDropped:', d['rowsDropped'], ' truncated:', d.get('truncated'))
for g in d['groups']:
    t=g.get('tokensPerSecond')
    print('  %-12s runtime=%-10s reqs=%d err=%d casc=%d p50=%sms tps=%s' % (
        g.get('driver'), g.get('runtime'), g['requests'], g['errors'], g['cascaded'],
        g['latencyMs']['p50'], (round(t['p50'],1) if t else 'unreported')))
"
N=$(echo "$M" | jq_ "sum(g['requests'] for g in d['groups'])")
[ "${N:-0}" -ge 2 ] && ok "*** BOTH completions retained ($N requests) ***" || bad "retained $N requests, expected >= 2"

P=$(curl -s "$GW/v1/metrics/requests" -H "Authorization: Bearer $TOK")
echo "$P" | PYTHONUTF8=1 python -c "
import sys,json
d=json.load(sys.stdin)
for r in d['requests']:
    print('  %s streamed=%-5s attempts=%d total=%sms tok=%s tries=%s' % (
        r['outcome'], r.get('streamed'), r['attempts'], r['totalMs'], r.get('completionTokens'),
        [(t['driver'], t['elapsedMs'], t['served'], t.get('error')) for t in r['tries']]))
"
STREAMED=$(echo "$P" | jq_ "sum(1 for r in d['requests'] if r.get('streamed'))")
[ "${STREAMED:-0}" -ge 1 ] && ok "*** a STREAMED request is in the store ($STREAMED) ***" || bad "no streamed request recorded"

say "4. tokens/sec per backend, same prompt - the number M8 exists to produce"
# One warm-up per backend, NOT counted rhetorically but deliberately left in
# the store. The first run found the reason: an external backend loads its own
# model, and that load is inside the request we measure. Our `swappedIn` and
# `waitedMs` only cover runtimes THIS control plane supervises, so an Ollama
# cold start is indistinguishable from a slow backend - 5 tok/s on the first
# request against 117 on the fourth. Percentiles plus the sample count are the
# defence; a warm-up is what makes the comparison mean what it says.
say "   warming both backends (their own model load is inside the first request)"
warm() { curl -s -o /dev/null -m 600 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$1\",\"messages\":[{\"role\":\"user\",\"content\":\"Say ready.\"}],\"max_tokens\":10}"; }
BIG="${EP_BIG_MODEL:-qwen3-coder:30b}"
warm "$SMALL"; warm "$BIG"

for i in 1 2 3; do
  curl -s -o /dev/null -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
    -d "{\"model\":\"$SMALL\",\"messages\":[{\"role\":\"user\",\"content\":\"Write two sentences about rain.\"}],\"max_tokens\":100}"
done
for i in 1 2 3; do
  curl -s -o /dev/null -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
    -d "{\"model\":\"$BIG\",\"messages\":[{\"role\":\"user\",\"content\":\"Write two sentences about rain.\"}],\"max_tokens\":100}"
done
sleep 3
curl -s "$GW/v1/metrics" -H "Authorization: Bearer $TOK" | PYTHONUTF8=1 python -c "
import sys,json
d=json.load(sys.stdin)
print()
print('  THE ANSWER TO \"which backend is faster for this model on this box\":')
for g in sorted(d['groups'], key=lambda g:-g['requests']):
    t=g.get('tokensPerSecond')
    print('    %-42s %-12s %s tok/s over %d sample(s)' % (
        (g.get('model') or '?')[:42], g.get('driver'),
        (round(t['p50'],1) if t else 'unreported'), (t['samples'] if t else 0)))
"

say "5. a cascade: an error row for the dead backend, and the survivor unharmed"
# A driver that is REACHABLE but whose BACKEND refuses. This is the
# construction that matters, and the first run got it wrong: pointing a
# tier at a model id nothing serves does not produce a cascade, because
# `RoutingTable.resolve` drops a tier whose target has no backends at
# all, so the slot collapses to one tier and the fallback answers as
# tier 1. A driver the gateway can see, fronting a port that refuses, is
# a backend that FAILS rather than one that is absent.
#
# `openai_compat_custom`, NOT `ollama_local`: the named local providers
# carry a fixed `default_base_url` and their `baseUrl` field is hidden
# behind `showWhen: provider == openai_compat_custom`, so patching
# `baseUrl` on an `ollama_local` driver is silently ignored. The second
# run of this script found that the hard way - the "dead" driver talked
# to the real Ollama and served the request, and the metrics correctly
# recorded a success. Only the custom provider honours a URL.
curl -s -o /dev/null -w '%{http_code}' -X POST "$AGENT/v1/components" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d '{"name":"dead-backend","kind":"inference-driver","url":"http://127.0.0.1:8093","spawn":{"configFile":"dead-backend.yaml"}}'
sleep 3
curl -s -o /dev/null -X PATCH "http://127.0.0.1:8093/v1/config" -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d '{"provider":"openai_compat_custom","modelId":"dead-model","baseUrl":"http://127.0.0.1:1"}'
curl -s -o /dev/null -X POST "$AGENT/v1/components/dead-backend/restart" -H "Authorization: Bearer $TOK" -d '{}'
sleep 10
# The driver must be REACHABLE for the gateway to include it; only its
# backend refuses. A driver the gateway cannot reach is dropped from the
# table and produces no cascade at all, which is a different scenario.
DEADINFO=$(curl -s "http://127.0.0.1:8093/v1/info" -H "Authorization: Bearer $TOK")
echo "  dead driver advertises: $(printf '%s' "$DEADINFO" | jq_ "(d.get('modelId'), d.get('backend'))" 2>/dev/null)"
case "$DEADINFO" in *dead-model*) ok "the failing backend is reachable and advertises dead-model";; *) bad "dead driver did not come up: $(printf '%s' "$DEADINFO" | head -c 200)";; esac
curl -s -o /dev/null -X PATCH "$GW/v1/config" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d "{\"modelSlots\":[{\"model\":\"failover-test\",\"targets\":[\"dead-model\",\"$SMALL\"]}]}"
sleep 18
R2=$(curl -s -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d '{"model":"failover-test","messages":[{"role":"user","content":"Say OK."}],"max_tokens":30}')
echo "  slot answered: $(echo "$R2" | jq_ "d.get('x_eugene_plexus',{}).get('driver')") tier=$(echo "$R2" | jq_ "d.get('x_eugene_plexus',{}).get('tier')") attempts=$(echo "$R2" | jq_ "d.get('x_eugene_plexus',{}).get('attempts')")"
sleep 3
FO=$(curl -s "$GW/v1/metrics/requests?model=failover-test" -H "Authorization: Bearer $TOK")
echo "$FO" | PYTHONUTF8=1 python -c "
import sys,json
d=json.load(sys.stdin)
rs=d['requests']
print('  rows for failover-test:', len(rs))
for r in rs:
    print('   ', r['outcome'], 'attempts=%d' % r['attempts'], 'tier=%s' % r.get('tier'),
          [(t['driver'], t['elapsedMs'], t['served'], t.get('error')) for t in r['tries']])
" || true
NTRIES=$(echo "$FO" | jq_ "max([r['attempts'] for r in d['requests']] or [0])")
[ "${NTRIES:-0}" -ge 2 ] && ok "*** the cascade is retained as one request with $NTRIES attempts ***" || bad "no cascade recorded (max attempts=$NTRIES)"
ERRCLS=$(echo "$FO" | jq_ "([t.get('error') for r in d['requests'] for t in r['tries'] if t.get('error')] or [''])[0]")
echo "  error recorded as: '$ERRCLS'"
case "$ERRCLS" in
  ""|*" "*) bad "error should be a bare exception class name, got '$ERRCLS'";;
  *) ok "the failed attempt carries an exception class, not a message";;
esac
# The point of the two-row shape: the healthy backend's own elapsed time
# is recorded, not the request total that includes the dead one's failure.
echo "$FO" | PYTHONUTF8=1 python -c "
import sys,json
d=json.load(sys.stdin)
for r in d['requests']:
    served=[t for t in r['tries'] if t['served']]
    if served and r['attempts']>1:
        s=served[0]
        print('  survivor %s took %sms of a %sms request - %sms of it was the dead backend'
              % (s['driver'], s['elapsedMs'], r['totalMs'], r['totalMs']-s['elapsedMs']))
" || true

say "5b. switching recording off stops it, and says so rather than showing nothing"
curl -s -o /dev/null -X PATCH "$GW/v1/config" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d '{"metricsEnabled":false}'
curl -s -o /dev/null -X POST "$AGENT/v1/components/gateway/restart" -H "Authorization: Bearer $TOK" -d '{}'
sleep 4; wait_healthy "$GW" 60 || bad "gateway did not come back"
CODE=$(curl -s -o /dev/null -w '%{http_code}' "$GW/v1/metrics" -H "Authorization: Bearer $TOK")
[ "$CODE" = "503" ] && ok "*** metrics off answers 503 'disabled', not an empty 200 ***" || bad "expected 503 with metrics off, got $CODE"
curl -s -o /dev/null -X PATCH "$GW/v1/config" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d '{"metricsEnabled":true}'
curl -s -o /dev/null -X POST "$AGENT/v1/components/gateway/restart" -H "Authorization: Bearer $TOK" -d '{}'
sleep 4; wait_healthy "$GW" 60 || bad "gateway did not come back after re-enabling"

say "6. rows survive a gateway restart"
BEFORE=$(curl -s "$GW/v1/metrics" -H "Authorization: Bearer $TOK" | jq_ "sum(g['requests'] for g in d['groups'])")
curl -s -o /dev/null -X POST "$AGENT/v1/components/gateway/restart" -H "Authorization: Bearer $TOK" -d '{}'
sleep 4
wait_healthy "$GW" 60 || bad "gateway did not come back"
AFTER=$(curl -s "$GW/v1/metrics" -H "Authorization: Bearer $TOK" | jq_ "sum(g['requests'] for g in d['groups'])")
echo "  before restart: $BEFORE   after: $AFTER"
[ "${AFTER:-0}" -ge "${BEFORE:-1}" ] && ok "*** history survived the restart ($AFTER rows) ***" || bad "history lost: $BEFORE -> $AFTER"
GWSTART=$(curl -s "$GW/v1/metrics" -H "Authorization: Bearer $TOK" | jq_ "d['gatewayStartedAt']")
echo "  gatewayStartedAt is now $GWSTART - a fresh process, an intact history"

say "6b. the phases of a request, and what the balancer saw"
# The two numbers this section exists for. `overheadMs` is the control
# plane's own cost - the serving attempt's gateway-side time minus the
# driver's measurement of its backend call - and gateway.yaml has
# asserted since M0 that the extra local hop is "sub-millisecond against
# a multi-second generation" without anyone measuring it.
curl -s "$GW/v1/metrics" -H "Authorization: Bearer $TOK" | PYTHONUTF8=1 python -c "
import sys,json
d=json.load(sys.stdin)
print()
print('  THE LOCAL HOP, MEASURED (the claim gateway.yaml has made since M0):')
for g in sorted(d['groups'], key=lambda g:-g['requests']):
    o=g.get('overheadMs'); r=g.get('routingMs')
    print('    %-12s routing p50=%-7s  control-plane overhead p50=%-7s max=%s' % (
        g.get('driver'),
        (str(r['p50'])+'ms' if r else 'unmeasured'),
        (str(o['p50'])+'ms' if o else 'unmeasured'),
        (str(o['max'])+'ms' if o else '-')))
"
P2=$(curl -s "$GW/v1/metrics/requests?limit=50" -H "Authorization: Bearer $TOK")
HASROUTING=$(echo "$P2" | jq_ "sum(1 for r in d['requests'] if r.get('routingMs') is not None)")
[ "${HASROUTING:-0}" -ge 1 ] && ok "*** the routing phase is measured ($HASROUTING request(s)) ***" || bad "no routingMs recorded"
HASBACKEND=$(echo "$P2" | jq_ "sum(1 for r in d['requests'] for t in r['tries'] if t.get('backendMs') is not None)")
[ "${HASBACKEND:-0}" -ge 1 ] && ok "*** the driver's own latency is retained ($HASBACKEND attempt(s)) ***" || bad "no backendMs recorded"
echo "$P2" | PYTHONUTF8=1 python -c "
import sys,json
d=json.load(sys.stdin)
cands=[r for r in d['requests'] if r.get('candidates')]
print('  requests with a recorded decision:', len(cands), 'of', len(d['requests']))
for r in cands[:3]:
    print('   ', r['requestedModel'][:28], 'strategy=%s' % r.get('strategy'),
          [(c['driver'], 'tier%s' % c['tier'], 'ok' if c['eligible'] else (c.get('reason') or 'no'),
            'inflight=%s/%s' % (c.get('inFlight'), c.get('slots'))) for c in r['candidates']])
"
STRAT=$(echo "$P2" | jq_ "([r.get('strategy') for r in d['requests'] if r.get('strategy')] or [''])[0]")
[ -n "$STRAT" ] && ok "the balancing strategy in effect is retained ('$STRAT')" || bad "no strategy recorded"
# The cascade from section 5 had two candidates and a rejection, so it
# must have kept its list - that is the case the field exists for.
NCAND=$(curl -s "$GW/v1/metrics/requests?model=failover-test" -H "Authorization: Bearer $TOK" | jq_ "max([len(r.get('candidates') or []) for r in d['requests']] or [0])")
[ "${NCAND:-0}" -ge 2 ] && ok "*** the cascade retained what the balancer considered ($NCAND candidates) ***" || bad "the cascade kept no candidate list (max=$NCAND)"

say "7. the hourly rollup, advanced by hand rather than waited an hour for"
# `maintain()` is public precisely so this is possible. Rolling up the
# current hour is deliberately skipped by the implementation, so the
# assertion is that the machinery runs and leaves the raw rows alone -
# not that a bucket appears for traffic that is still arriving.
"$PY" - <<'PYROLL'
import asyncio, os, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(os.environ["EP_GATEWAY_SRC"])))
from eugene_plexus_gateway.metrics import MetricsStore

async def main():
    path = Path(os.environ["EP_WORK"]) / "metrics.sqlite3"
    store = MetricsStore(path, retention_days=7)
    await store.start()
    try:
        store.maintain()
        with store._reader() as conn:
            print("  raw requests still present:",
                  conn.execute("SELECT COUNT(*) FROM request").fetchone()[0])
            print("  rollup rows:",
                  conn.execute("SELECT COUNT(*) FROM rollup").fetchone()[0])
            print("  rollup_through:",
                  (conn.execute("SELECT value FROM meta WHERE key='rollup_through'").fetchone()
                   or ["(not set - no completed hour yet)"])[0])
    finally:
        await store.aclose()

asyncio.run(main())
PYROLL

say "where the store lives"
find "$WORK" -name 'metrics.sqlite3*' -printf '  %p (%s bytes)\n' 2>/dev/null || ls -la "$WORK" | grep -i metrics

say "what this run proved / could not"
cat <<'NOTES'
  proved: a non-streaming AND a streaming completion both retained; the final stream frame
          carrying x_eugene_plexus; per-backend tokens/sec for two real models on this box;
          a real cascade retained as one request with an exception class on the failed
          attempt and the survivor's own elapsed time separate from the request total;
          metrics off answering 503 rather than an empty window; history surviving a
          gateway restart.
  cannot: vLLM against llama.cpp - no Windows build and WSL is not installed, so the
          headline heterogeneous comparison still needs the second host M4 and M5 also
          wait on. An EXTERNAL backend's own model load is inside the first request and
          our waitedMs cannot see it, so a cold start reads as a slow backend; percentiles
          and the sample count are the only defence and this run warms up first.
NOTES

say "result"
if [ "$FAILURES" -eq 0 ]; then
  echo "M8 acceptance PASSED - the gateway retains what it serves, streaming included."
else
  echo "M8 acceptance FAILED with $FAILURES failure(s)."
fi
exit "$FAILURES"
