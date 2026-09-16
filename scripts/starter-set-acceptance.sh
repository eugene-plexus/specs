#!/usr/bin/env bash
# Discover, recommendation-first: the starter set, a pasted link, and the
# review that keeps the list honest (hobbyist UX plan, S6 — decision #4).
#
# Design: docs/design/hobbyist-ux.md §7 S6, §6.3, §6.5; record §11.7.
# Its §0.5 measured what this replaces: a person with no candidate in
# mind, opening a screen whose empty state is "whatever the hub sorted to
# the top today", four hundred thousand rows deep — and then, having
# picked a repo, eleven near-identical rows with no primary action.
#
# The checks:
#   0. isolated from any install on this machine
#   1. the UI wheel staged from this working tree, so the agent serves THIS build
#   2. agent + control + gateway + library up, initialized, the agent enrolled
#   3. API: the starter set is served, scored, and every entry can be scored
#      from its own recorded shape rather than from a guess
#   4. API: it answers with the CATALOGUE DISABLED — the property the whole
#      shape exists for, since choosing a first model must not need the hub
#   5. API: the recommendation moves with the machine it is scored against,
#      and with the context
#   6. API: an operator's own empty list recommends nothing, and says it is theirs
#   7. API: a pasted URL resolves; a URL that misses is a 404 naming the repo;
#      a bare owner/name that misses falls through to a search
#   8. BROWSER: Discover's empty view is the suggestions, the badge names the
#      context, the control changes it, a pasted link opens one repo with a
#      suggested version above "All versions"
#   9. BROWSER: Home names one model and its primary button fetches that file
#  10. the review CLI runs end to end against the live hub and files a report
#  11. teardown by pid
#
# Safe beside a live install: environment cleared, +100 ports, teardown by
# pid. Never `pkill -f eugene_plexus_` — the live worker is one.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
LIB_PY="${EP_LIB_PY:-$EP_ROOT/library/.venv/Scripts/python.exe}"
UI_DIR="${EP_UI_DIR:-$EP_ROOT/ui}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-starter-set}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"; CTL_PORT="${EP_CTL_PORT:-8183}"
GW_PORT="${EP_GW_PORT:-8180}"; LIB_PORT="${EP_LIB_PORT:-8182}"
AGENT="http://127.0.0.1:$AGENT_PORT"; CTL="http://127.0.0.1:$CTL_PORT"
GW="http://127.0.0.1:$GW_PORT"; LIB="http://127.0.0.1:$LIB_PORT"
PASS="starter-accept-$$"
OWNED_PORTS="$AGENT_PORT $CTL_PORT $GW_PORT $LIB_PORT"
SKIP_BUILD="${EP_SKIP_BUILD:-0}"
# A small real repo for the pasted-link checks. Small because nothing is
# downloaded here — only its metadata is read.
EP_DISCOVER_REPO="${EP_DISCOVER_REPO:-unsloth/Qwen3-0.6B-GGUF}"
GIB=1073741824

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
wait_healthy() { for _ in $(seq 1 "${2:-60}"); do curl -sf -m 2 "$1/healthz" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
A_PID=""; TOK=""
teardown() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 3; }
  for p in $OWNED_PORTS; do for pid in $(listening_pids "$p"); do taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null; done; done
}

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
[ -f "$LIB_PY" ] || { bad "no library python at $LIB_PY"; exit 1; }
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
ok "both interpreters; every port free"
rm -rf "$WORK"; mkdir -p "$WORK/models"; cd "$WORK" || exit 1
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
# Staging is not serving: the agent serves whatever `eugene_plexus_ui`
# resolves to in ITS venv, and an S2-era wheel install once made four
# runs assert about a build no browser ever saw.
SERVED=$("$PY" -c "from eugene_plexus_ui import static_dir; print(static_dir())" 2>/dev/null | tr -d '\r')
SERVED_NORM=$(printf '%s' "$SERVED" | tr '\\' '/' | tr '[:upper:]' '[:lower:]')
STATIC_NORM=$(cygpath -w "$STATIC" 2>/dev/null | tr '\\' '/' | tr '[:upper:]' '[:lower:]')
[ -n "$SERVED_NORM" ] && [ "$SERVED_NORM" = "$STATIC_NORM" ] \
  && ok "the agent venv's eugene_plexus_ui IS the staged directory (editable install)" \
  || { bad "the agent venv serves $SERVED, not the staged $STATIC. Install the UI editable: \"$PY\" -m pip install -e \"$UI_DIR\""; exit 1; }

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
(exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
  "$PY" -m eugene_plexus_agent --unattended > agent.log 2>&1) &
A_PID=$!
wait_healthy "$AGENT" 60 && wait_healthy "$CTL" 90 || { bad "agent/control never came up"; tail -20 agent.log; exit 1; }
[ "$(code_of -X POST "$CTL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}")" = "204" ] || { bad "control initialize"; exit 1; }
TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "agent initialize"; exit 1; }
wait_healthy "$CTL" 90 || { bad "control did not come back after initialize"; exit 1; }
CTOK=$(curl -s -X POST "$CTL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
JOIN=$(curl -s -X POST -H "Authorization: Bearer $CTOK" "$CTL/v1/nodes/join-token" -H 'content-type: application/json' -d '{"nodeName":"starter-node"}' | jq_ "d['token']")
[ "$(code_of -X POST -H "Authorization: Bearer $TOK" "$AGENT/v1/node/enroll" -H 'content-type: application/json' -d "{\"controlUrl\":\"$CTL\",\"token\":\"$JOIN\",\"name\":\"starter-node\"}")" = "200" ] || { bad "enroll failed"; tail -20 agent.log; exit 1; }
wait_healthy "$CTL" 90 && wait_healthy "$AGENT" 60 && wait_healthy "$LIB" 60 && wait_healthy "$GW" 60 || { bad "fleet did not come back after enrollment"; exit 1; }
sleep 2
TOK=$(curl -s -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] || { bad "no session after enrollment"; exit 1; }
AUTH=(-H "Authorization: Bearer $TOK")
[ "$(code_of "${AUTH[@]}" "$CTL/v1/nodes")" = "200" ] && ok "four processes; enrolled; the session reaches the root" || bad "root not answering"
# What the browser will actually load. Per PAGE, because the export
# code-splits by route: the suggestion card lives in Discover's chunks
# and Home's new state in Home's, and grepping only `/` would have
# reported a pre-S6 build as present or absent for the wrong reason.
served_carries() { # <page path> <marker>
  local chunks found=0 c
  chunks=$(curl -s "$AGENT$1" | grep -o '_next/static/chunks/[^"]*\.js' | sort -u)
  for c in $chunks; do curl -s "$AGENT/$c" | grep -q "$2" && { found=1; break; }; done
  printf '%s %s' "$found" "$(printf '%s' "$chunks" | wc -l | tr -d ' ')"
}
read -r FOUND N <<< "$(served_carries "/discover/" 'starter-recommended')"
[ "$FOUND" = "1" ] && ok "the agent SERVES a Discover bundle carrying the suggestion card ($N chunks)" \
  || { bad "the served Discover bundle has no suggestion card -- the browser would test a pre-S6 build"; exit 1; }
read -r FOUND N <<< "$(served_carries "/" 'no-models-recommended')"
[ "$FOUND" = "1" ] && ok "and a Home bundle carrying the suggested-model state ($N chunks)" \
  || { bad "the served Home bundle has no suggested-model state"; exit 1; }

say "3. the starter set is served, scored, and scored from real metadata"
SET=$(curl -s "${AUTH[@]}" "$LIB/v1/catalogue/starter?contextLength=16384")
COUNT=$(echo "$SET" | jq_ "len(d['models'])")
[ "${COUNT:-0}" -gt 0 ] && ok "$COUNT suggestions, source=$(echo "$SET" | jq_ "d['source']"), engine=$(echo "$SET" | jq_ "d.get('engine','?')")" || { bad "no suggestions: $(echo "$SET" | head -c 300)"; exit 1; }
REVIEWED=$(echo "$SET" | jq_ "d['reviewed']")
AGE=$(echo "$SET" | jq_ "d.get('reviewedDaysAgo', -1)")
ok "reviewed $REVIEWED, $AGE days ago"
[ "$AGE" -le 30 ] && ok "the list is inside the 30-day window a release is allowed" || bad "the shipped list is $AGE days old -- the release gate would refuse it"
# Every entry must carry enough shape to compute a real KV cache. `basis:
# estimate` here would mean the card's headline number is a guess with
# nothing behind it, which is exactly what this endpoint exists to avoid.
ESTIMATES=$(echo "$SET" | jq_ "len([m for m in d['models'] if (m.get('fit') or {}).get('basis') != 'metadata'])")
[ "$ESTIMATES" = "0" ] && ok "every entry scores from its own recorded shape (basis=metadata), not from its size" || bad "$ESTIMATES entr(ies) fall back to an estimate"
MISSING=$(echo "$SET" | jq_ "len([m for m in d['models'] if not m.get('why') or not m.get('file') or not m.get('sizeBytes')])")
[ "$MISSING" = "0" ] && ok "every entry names a file, a size and why it is there" || bad "$MISSING entr(ies) are incomplete"
REC=$(echo "$SET" | jq_ "(d.get('recommended') or {}).get('sizeClass','')")
[ -n "$REC" ] && ok "recommended: $REC -- $(echo "$SET" | jq_ "(d.get('recommended') or {})['reason'][:110]")" || bad "nothing recommended on this machine"

say "4. it answers with the catalogue DISABLED -- no upstream call at all"
curl -s -o /dev/null -X PATCH "${AUTH[@]}" -H 'content-type: application/json' "$LIB/v1/config" -d '{"catalogueEnabled": false}'
OFF=$(curl -s "${AUTH[@]}" "$LIB/v1/catalogue/starter?contextLength=16384")
[ "$(echo "$OFF" | jq_ "len(d['models'])")" = "$COUNT" ] && ok "the same $COUNT suggestions with the catalogue off" || bad "the set changed when the catalogue was disabled: $(echo "$OFF" | head -c 300)"
SEARCH_CODE=$(code_of "${AUTH[@]}" "$LIB/v1/catalogue/search?q=qwen")
[ "$SEARCH_CODE" = "409" ] && ok "and search beside it refuses with 409, as it must -- the two really are different dependencies" || bad "search returned $SEARCH_CODE with the catalogue off"
curl -s -o /dev/null -X PATCH "${AUTH[@]}" -H 'content-type: application/json' "$LIB/v1/config" -d '{"catalogueEnabled": true}'

say "5. the recommendation moves with the machine, and with the context"
BIG=$(curl -s "${AUTH[@]}" "$LIB/v1/catalogue/starter?contextLength=16384&vramBytes=$((80 * GIB))&ramBytes=$((64 * GIB))" | jq_ "(d.get('recommended') or {}).get('sizeClass','')")
SMALL=$(curl -s "${AUTH[@]}" "$LIB/v1/catalogue/starter?contextLength=16384&vramBytes=$((6 * GIB))&ramBytes=$((16 * GIB))" | jq_ "(d.get('recommended') or {}).get('sizeClass','')")
[ -n "$BIG" ] && [ -n "$SMALL" ] && [ "$BIG" != "$SMALL" ] && ok "80 GiB -> $BIG, 6 GiB -> $SMALL: it is scored against the machine, not shipped as one answer" || bad "80 GiB -> '$BIG', 6 GiB -> '$SMALL'"
CPU=$(curl -s "${AUTH[@]}" "$LIB/v1/catalogue/starter?contextLength=16384&vramBytes=0&ramBytes=$((64 * GIB))")
CPU_REASON=$(echo "$CPU" | jq_ "(d.get('recommended') or {}).get('reason','')")
echo "$CPU_REASON" | grep -qi "no graphics card" && ok "with no GPU the rule inverts and says why: $(echo "$CPU_REASON" | head -c 90)" || bad "no-GPU reason: $(echo "$CPU_REASON" | head -c 140)"
# 24 GiB, and the pair was measured rather than assumed. The first run
# asked this on a 12 GiB card and got the same class at both ends --
# correctly, because the 12B in the list is a sliding-window model whose
# cache barely grows with context. That is a real property of the field
# now, and a check that assumes a linear cache is a check asserting the
# arithmetic this slice replaced.
LONG=$(curl -s "${AUTH[@]}" "$LIB/v1/catalogue/starter?contextLength=262144&vramBytes=$((24 * GIB))&ramBytes=$((32 * GIB))" | jq_ "(d.get('recommended') or {}).get('sizeClass','(none)')")
SHORT=$(curl -s "${AUTH[@]}" "$LIB/v1/catalogue/starter?contextLength=4096&vramBytes=$((24 * GIB))&ramBytes=$((32 * GIB))" | jq_ "(d.get('recommended') or {}).get('sizeClass','(none)')")
[ "$LONG" != "$SHORT" ] && ok "the same 24 GiB card at 4k -> $SHORT and at 256k -> $LONG: the context is the number that decides" || bad "4k -> $SHORT, 256k -> $LONG (they should differ on a 24 GiB card)"

say "6. an operator's own list replaces the shipped one"
printf 'reviewed: 2026-09-16\nclasses: []\n' > "$WORK/mine.yaml"
curl -s -o /dev/null -X PATCH "${AUTH[@]}" -H 'content-type: application/json' "$LIB/v1/config" -d "{\"starterModelsFile\": \"$(printf '%s' "$WORK_NATIVE\\mine.yaml" | sed 's/\\/\\\\/g')\"}"
MINE=$(curl -s "${AUTH[@]}" "$LIB/v1/catalogue/starter")
[ "$(echo "$MINE" | jq_ "d['source']")" = "configured" ] && ok "source=configured: an operator who replaced the list can see that they did" || bad "source: $(echo "$MINE" | jq_ "d['source']")"
[ "$(echo "$MINE" | jq_ "len(d['models'])")" = "0" ] && [ "$(echo "$MINE" | jq_ "'recommended' not in d or d['recommended'] is None")" = "True" ] \
  && ok "an empty list recommends nothing, rather than inventing one" || bad "an empty list still recommended something"
curl -s -o /dev/null -X PATCH "${AUTH[@]}" -H 'content-type: application/json' "$LIB/v1/config" -d '{"starterModelsFile": null}'
[ "$(curl -s "${AUTH[@]}" "$LIB/v1/catalogue/starter" | jq_ "d['source']")" = "shipped" ] && ok "clearing it returns to the shipped list" || bad "clearing starterModelsFile did not return to shipped"

say "7. a pasted reference is a lookup, not a query"
BYURL=$(curl -s "${AUTH[@]}" --get "$LIB/v1/catalogue/search" --data-urlencode "q=https://huggingface.co/$EP_DISCOVER_REPO/tree/main")
[ "$(echo "$BYURL" | jq_ "d.get('interpretedAs','')")" = "repo" ] && ok "a pasted URL with a /tree/ tail reads as one repo" || bad "interpretedAs: $(echo "$BYURL" | head -c 250)"
[ "$(echo "$BYURL" | jq_ "d.get('interpretedFrom','')")" = "$EP_DISCOVER_REPO" ] && ok "and it resolves to $EP_DISCOVER_REPO" || bad "interpretedFrom: $(echo "$BYURL" | jq_ "d.get('interpretedFrom','')")"
[ "$(echo "$BYURL" | jq_ "len(d['results'])")" = "1" ] && ok "one result, so the screen can select it rather than ask for a click" || bad "results: $(echo "$BYURL" | jq_ "len(d['results'])")"
BARE=$(curl -s "${AUTH[@]}" --get "$LIB/v1/catalogue/search" --data-urlencode "q=$EP_DISCOVER_REPO")
[ "$(echo "$BARE" | jq_ "d.get('interpretedAs','')")" = "repo" ] && ok "a bare owner/name resolves too" || bad "bare name: $(echo "$BARE" | jq_ "d.get('interpretedAs','')")"
MISS=$(code_of "${AUTH[@]}" --get "$LIB/v1/catalogue/search" --data-urlencode "q=https://huggingface.co/nobody-eugene/nothing-here")
[ "$MISS" = "404" ] && ok "a URL that does not resolve is a 404 naming the repo, not an empty list" || bad "a missing URL returned $MISS"
BAREMISS=$(curl -s "${AUTH[@]}" --get "$LIB/v1/catalogue/search" --data-urlencode "q=nobody-eugene/nothing-here")
[ "$(echo "$BAREMISS" | jq_ "d.get('interpretedAs','')")" = "search" ] && ok "a bare name that does not resolve falls through to a search -- it may be what they meant" || bad "bare miss: $(echo "$BAREMISS" | jq_ "d.get('interpretedAs','')")"
PLAIN=$(curl -s "${AUTH[@]}" --get "$LIB/v1/catalogue/search" --data-urlencode "q=qwen")
[ "$(echo "$PLAIN" | jq_ "d.get('interpretedAs','')")" = "search" ] && ok "an ordinary query is still an ordinary search ($(echo "$PLAIN" | jq_ "len(d['results'])") rows)" || bad "plain query: $(echo "$PLAIN" | jq_ "d.get('interpretedAs','')")"

say "8-9. the browser: Discover's suggestions, the context in the badge, a pasted link, Home"
(cd "$UI_DIR" && EP_UI_URL="$AGENT" EP_PASSPHRASE="$PASS" EP_DISCOVER_REPO="$EP_DISCOVER_REPO" \
  npx playwright test e2e/discover.spec.ts e2e/home.spec.ts > "$WORK/playwright.log" 2>&1)
PW=$?
sed -n '/Running/,$p' "$WORK/playwright.log" | grep -E '^\s+(ok|x|-|[✓✘×])\s+[0-9]|passed|failed|skipped' | head -30
if [ "$PW" = "0" ]; then
  for t in \
    "with nothing typed, the screen suggests models rather than listing the hub" \
    "every verdict names the context it was scored at, and the control changes it" \
    "a pasted link resolves to one model" \
    "a repo opens with one suggested version above the full table" \
    "signing in lands on Home, and Home has a primary action instead of a disabled box"; do
    if grep -E "^\s+(ok|✓)\s+[0-9]+ .*$(printf '%s' "$t" | sed 's/[][\.*^$]/\\&/g')" "$WORK/playwright.log" >/dev/null; then
      ok "browser: $t"
    else
      bad "browser: '$t' did not pass"
    fi
  done
else
  bad "the discover/home specs failed"
  tail -80 "$WORK/playwright.log"
fi

say "10. the review runs end to end against the live hub"
# Captured BEFORE the run, or the comparison at the end of this section
# proves nothing — the recurring shape of a check that cannot fail.
STARTER_FILE="$EP_ROOT/library/src/eugene_plexus_library/starter_models.yaml"
sha_of() { PYTHONUTF8=1 python -c "import hashlib,sys,pathlib; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()[:12])" "$1"; }
SHIPPED_SHA=$(sha_of "$STARTER_FILE")
REVIEW_OUT="$WORK/review.md"
"$LIB_PY" -m eugene_plexus_library starter-review --pages 2 --report "$REVIEW_OUT" --proposed "$WORK/proposed.yaml" > "$WORK/review.log" 2>&1
RC=$?
[ -s "$REVIEW_OUT" ] && ok "a report was written ($(wc -l < "$REVIEW_OUT" | tr -d ' ') lines)" || { bad "no report"; tail -20 "$WORK/review.log"; }
[ -s "$WORK/proposed.yaml" ] && ok "and a proposed list beside it, which nothing applied" || bad "no proposal"
if grep -qi "download count and nothing else" "$REVIEW_OUT" 2>/dev/null; then
  ok "the report says outright what it ranks on, and that it is not quality"
else
  bad "the report does not state its ranking basis"
fi
grep -q "| class | verdict |" "$REVIEW_OUT" && ok "every size class has a verdict" || bad "no verdict table"
grep -q "## New this month" "$REVIEW_OUT" && ok "and a 'new this month' section: the state-of-the-field half of what the review is for" || bad "no 'new this month' section"
# Exit code is the release gate's own signal, not a failure of this run.
if [ "$RC" = "0" ]; then ok "exit 0: every class KEEP -- the shipped list is current"; else ok "exit $RC: at least one class is REPLACE or REVIEW, which is what the release gate reads"; fi
PROPOSED_CLASSES=$(PYTHONUTF8=1 python -c "import yaml,io,sys; d=yaml.safe_load(io.open(sys.argv[1],encoding='utf-8')); print(len(d.get('classes') or []))" "$WORK/proposed.yaml" 2>/dev/null)
[ "${PROPOSED_CLASSES:-0}" -gt 0 ] && ok "the proposal carries $PROPOSED_CLASSES classes" || bad "the proposal is empty"
AFTER_SHA=$(sha_of "$STARTER_FILE")
[ "$SHIPPED_SHA" = "$AFTER_SHA" ] && ok "the review did not touch the file it reviewed ($SHIPPED_SHA) — the hysteresis needs last month's file to compare against" || bad "the review edited the shipped list"

say "result"
if [ "$FAILURES" = "0" ]; then printf '  ALL CHECKS PASSED\n'; else printf '  %d CHECK(S) FAILED\n' "$FAILURES"; fi
exit "$FAILURES"
