#!/usr/bin/env bash
#
# The CLI subscription backends, through the gateway.
#
# Differentiator #7's other half: "one endpoint over local models AND
# the subscriptions the user already pays for". The claude_code_cli and
# codex_cli engines date from the v0.2 consciousness era and have NEVER
# been exercised under the control plane - no acceptance script mentions
# them.
#
# Deliberately small: one short completion each. This spends the
# operator's real subscription quota, so it asks each backend for a
# single word.
#
# What it is looking for, beyond "it answers":
#   * does the gateway route to a subprocess backend at all
#   * do the metrics record it like any other backend
#   * DO THEY REPORT TOKEN USAGE - the claim I got wrong in the docs and
#     corrected by reading the mapper rather than running it
#   * is `backend` recorded as claude_code_cli / codex_cli, not as the
#     HTTP kind
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-cli-backends}"
AGENT=http://127.0.0.1:8079
GW=http://127.0.0.1:8080
PASS="cli-check-$$"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  --    %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
command -v claude >/dev/null || { bad "claude is not on PATH"; exit 1; }
command -v codex >/dev/null || { bad "codex is not on PATH"; exit 1; }
ok "both CLIs on PATH"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
export EUGENE_PLEXUS_AGENT_BIND_PORT=8079

say "start the control plane"
"$PY" -m eugene_plexus_agent >"$WORK/agent.log" 2>&1 &
AGENT_PID=$!
trap 'kill -9 $AGENT_PID 2>/dev/null; pkill -f eugene_plexus_ 2>/dev/null' EXIT
wait_healthy "$AGENT" 60 || { bad "agent never answered"; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d['sessionToken']")
[ -n "$TOK" ] || { bad "no operator token"; exit 1; }
wait_healthy "$GW" 90 || { bad "gateway never answered"; exit 1; }
ok "agent and gateway up"

add_cli_driver() { # name port provider modelId
  curl -s -o /dev/null -X POST "$AGENT/v1/components" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' \
    -d "{\"name\":\"$1\",\"kind\":\"inference-driver\",\"url\":\"http://127.0.0.1:$2\",\"spawn\":{\"configFile\":\"$1.yaml\"}}"
  sleep 3
  curl -s -o /dev/null -X PATCH "http://127.0.0.1:$2/v1/config" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' \
    -d "{\"provider\":\"$3\",\"modelId\":\"$4\",\"requestTimeoutSeconds\":180}"
  curl -s -o /dev/null -X POST "$AGENT/v1/components/$1/restart" -H "Authorization: Bearer $TOK" -d '{}'
  sleep 6
}

say "a driver per subscription CLI"
add_cli_driver claude-cli 8094 claude_subscription "claude-sonnet-4-5"
add_cli_driver codex-cli  8095 chatgpt_subscription "gpt-5"

for d in claude-cli:8094 codex-cli:8095; do
  name="${d%%:*}"; port="${d##*:}"
  INFO=$(curl -s -m 10 "http://127.0.0.1:$port/v1/info" -H "Authorization: Bearer $TOK")
  echo "  $name /v1/info: $(printf '%s' "$INFO" | jq_ "(d.get('backend'), d.get('modelId'), d.get('provider'))" 2>/dev/null || printf '%s' "$INFO" | head -c 160)"
done

sleep 8
MODELS=$(curl -s "$GW/v1/models" -H "Authorization: Bearer $TOK" | jq_ "[m['id'] for m in d['data']]")
echo "  gateway lists: $MODELS"
case "$MODELS" in *claude*) ok "the Claude subscription is routable through the gateway";; *) bad "gateway does not list a claude model: $MODELS";; esac
case "$MODELS" in *gpt*) ok "the ChatGPT subscription is routable through the gateway";; *) bad "gateway does not list a gpt model: $MODELS";; esac

complete() { # model
  curl -s -m 300 -X POST "$GW/v1/chat/completions" -H "Authorization: Bearer $TOK" \
    -H 'content-type: application/json' \
    -d "{\"model\":\"$1\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly one word: ready\"}],\"max_tokens\":40}"
}

say "one short completion through each - this spends real quota"
for m in claude-sonnet-4-5 gpt-5; do
  R=$(complete "$m")
  TEXT=$(echo "$R" | jq_ "d.get('choices',[{}])[0].get('message',{}).get('content','')" 2>/dev/null)
  XP=$(echo "$R" | jq_ "(d.get('x_eugene_plexus') or {})" 2>/dev/null)
  if [ -n "$TEXT" ]; then
    ok "*** $m answered through the gateway: '$(printf '%s' "$TEXT" | head -c 60)' ***"
    echo "    routing: $XP"
    echo "    usage:   $(echo "$R" | jq_ "d.get('usage')")"
  else
    bad "$m returned no completion: $(echo "$R" | head -c 400)"
  fi
done

say "what the metrics kept"
sleep 4
curl -s "$GW/v1/metrics" -H "Authorization: Bearer $TOK" | PYTHONUTF8=1 python -c "
import sys,json
d=json.load(sys.stdin)
for g in d['groups']:
    t=g.get('tokensPerSecond'); o=g.get('overheadMs')
    print('  %-12s backend=%-18s reqs=%d p50=%sms tps=%s overhead=%s' % (
        g.get('driver'), g.get('backend'), g['requests'], g['latencyMs']['p50'],
        (round(t['p50'],1) if t else 'unreported'),
        (str(o['p50'])+'ms' if o else 'unreported')))
"
P=$(curl -s "$GW/v1/metrics/requests" -H "Authorization: Bearer $TOK")
echo "$P" | PYTHONUTF8=1 python -c "
import sys,json
d=json.load(sys.stdin)
for r in d['requests']:
    print('  %-22s %s tok=%s/%s backend=%s' % (
        r['requestedModel'][:22], r['outcome'], r.get('promptTokens'), r.get('completionTokens'),
        [t.get('backend') for t in r['tries']]))
"
NREC=$(echo "$P" | jq_ "len(d['requests'])")
[ "${NREC:-0}" -ge 2 ] && ok "both CLI completions are in the store ($NREC rows)" || bad "expected 2 recorded requests, got $NREC"

# THE question the docs got wrong an hour ago, now asked of the real CLIs.
WITHTOK=$(echo "$P" | jq_ "sum(1 for r in d['requests'] if r.get('completionTokens'))")
if [ "${WITHTOK:-0}" -ge 1 ]; then
  ok "*** the CLI backends DO report token usage ($WITHTOK of $NREC requests) - the corrected docs are right ***"
else
  note "neither CLI reported token counts on this run - the ORIGINAL doc claim was closer to true"
  note "(design says absence is a per-request fact; this is evidence about these CLI versions)"
fi
KIND=$(echo "$P" | jq_ "sorted({t.get('backend') for r in d['requests'] for t in r['tries'] if t.get('backend')})")
echo "  backend kinds recorded: $KIND"
case "$KIND" in *claude_code_cli*) ok "recorded as claude_code_cli, not as an HTTP backend";; *) bad "expected claude_code_cli in $KIND";; esac
case "$KIND" in *codex_cli*) ok "recorded as codex_cli, not as an HTTP backend";; *) bad "expected codex_cli in $KIND";; esac

say "result"
if [ "$FAILURES" -eq 0 ]; then
  echo "CLI subscription backends PASSED - one endpoint over local models AND subscriptions."
else
  echo "CLI subscription backends FAILED with $FAILURES failure(s)."
fi
exit "$FAILURES"
