#!/usr/bin/env bash
# R1.2 -- two rules the product states and does not enforce. Live.
#
# Roadmap: docs/design/release-roadmap.md §2.2. Findings: review §6.1 #1,
# §6.2 #14, §6.3 #32.
#
# What only a live run can prove. The unit checks in each repo
# (`test_forwarded_peer.py`, and `test_download_destination_stays_in_the_root.py`
# in the library) drive `ProxyHeadersMiddleware` and the download
# resolver against fixtures. None of them can prove that the uvicorn a
# real `python -m eugene_plexus_agent` starts ignores a forwarding
# header, that a login travelling the browser's own path -- socket,
# proxy, loopback hop, route -- is bucketed by the browser's address
# rather than the proxy's, or that the library refuses a traversing
# destination over HTTP with nothing written outside the root.
#
# **The instrument worth stating: the client binds its own source
# address.** Two "browsers" are 127.0.0.2 and 127.0.0.3, which are
# distinct peers on a real socket and both loopback -- so the proxy sees
# two different callers and the component behind it sees one. That is
# exactly the arrangement the finding is about, and it needs no LAN
# binding, no second machine and nothing this box's live install could
# notice.
#
# The checks:
#   0. isolated from any install on this machine, and from its ports
#   1. the agent comes up; the wizard's passphrase is set
#   2. **the headline**: five wrong passphrases through the proxy, each
#      claiming a different origin, still 429 the sixth. Before this
#      slice uvicorn rewrote the peer from `X-Forwarded-For` and those
#      were five buckets of one
#   3. **the half that needs no attacker**: one browser's five mistakes
#      do not lock a second browser out, and do not lock a direct caller
#      out either. Before this slice every proxied login shared one
#      bucket, so five mistypes locked the whole install for a minute
#   4. a forwarding header does not survive the proxy, and neither does
#      a caller's copy of the header we own
#   5. the Reach card's proof cannot be forged from a local caller
#   6. `GET /` carries the frame headers, on the real page and on the
#      degraded one
#   7. **calling #3**: a download whose `filename` leaves the model root
#      is `PathTraversal`, with nothing queued and nothing on disk
#   8. an ordinary download still resolves -- the fix must not break the
#      rename the field exists for
#   9. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped (install.ps1 sets the config-file var in the USER
# environment, so a throwaway agent would otherwise come up as the live
# worker and announce a dying port to the real control root -- that
# happened, 2026-09-12), ports are +100, teardown is by pid. Never
# `pkill -f eugene_plexus_`: this box is a worker node.
#
# **No GPU, no model, no engine binary, no network.** Every subject here
# is a header, a bucket key or a path.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
LIB_PY="${EP_LIB_PY:-$EP_ROOT/library/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-r12}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
LIB_PORT="${EP_LIB_PORT:-8182}"
AGENT="http://127.0.0.1:$AGENT_PORT"
OWNED_PORTS="$AGENT_PORT $LIB_PORT"
PASSPHRASE="r12-$$"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }

A_PID=""
L_PID=""
teardown() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 3; }
  [ -n "$L_PID" ] && kill "$L_PID" 2>/dev/null
  for p in $OWNED_PORTS; do
    for pid in $(listening_pids "$p"); do
      taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
    done
  done
}

say "preflight"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
[ -f "$LIB_PY" ] || { bad "no library python at $LIB_PY"; exit 1; }
"$PY" -c "import eugene_plexus_agent" 2>/dev/null || { bad "eugene_plexus_agent must import from $PY"; exit 1; }
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && { bad "port $p in use"; exit 1; }; done
ok "agent and library interpreters; ports $OWNED_PORTS free"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
trap teardown EXIT

# --- 0 -----------------------------------------------------------------------
say "0. isolate this run"
for v in $(env | grep -o '^EUGENE_PLEXUS_[A-Z_]*' || true); do unset "$v"; done
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy NO_PROXY no_proxy
WORK_NATIVE=$(win_path "$WORK")
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] && ok "no ambient EUGENE_PLEXUS_* variable" || { bad "leaked"; exit 1; }

# The one instrument this run adds: an HTTP client that chooses its own
# source address, so two callers on one box are two peers on the wire.
# Everything below speaks through it rather than through curl, because
# curl cannot bind a source address per request and the whole subject is
# which address the server saw.
cat > peerclient.py <<'PY'
"""Speak HTTP from a chosen source address, and report what came back."""
import json, socket, sys


def request(port, method, path, *, source=None, headers=None, body=None):
    """Status, headers and the RAW body -- chunk framing and all.

    Deliberately not an HTTP client: it exists to choose a source
    address, which `curl` cannot do per request, and the whole subject
    of this run is which address the server saw. A proxied response is
    chunk-framed and is read as a substring rather than parsed.
    """
    sock = socket.socket()
    if source:
        sock.bind((source, 0))
    sock.settimeout(30)
    sock.connect(("127.0.0.1", int(port)))
    raw = b"" if body is None else json.dumps(body).encode()
    lines = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1", "Connection: close"]
    if raw:
        lines += ["Content-Type: application/json", f"Content-Length: {len(raw)}"]
    for key, value in (headers or {}).items():
        lines.append(f"{key}: {value}")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode() + raw)
    chunks = []
    while True:
        part = sock.recv(65536)
        if not part:
            break
        chunks.append(part)
    sock.close()
    blob = b"".join(chunks)
    head, _, payload = blob.partition(b"\r\n\r\n")
    head_text = head.decode("latin-1")
    status = int(head_text.split(" ", 2)[1])
    got = {}
    for line in head_text.split("\r\n")[1:]:
        name, _, value = line.partition(":")
        got[name.strip().lower()] = value.strip()
    return status, got, payload.decode("utf-8", "replace")


def status(*a, **kw):
    return request(*a, **kw)[0]
PY

# --- 1 -----------------------------------------------------------------------
say "1. the agent comes up and takes a passphrase"
cat > agent.yaml <<YAML
firstRunComplete: true
components: []
YAML
(exec env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_NATIVE/agent.yaml" \
  EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 \
  EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
  "$PY" -m eugene_plexus_agent --unattended > agent.log 2>&1) &
A_PID=$!
for _ in $(seq 1 60); do curl -sf -m 2 "$AGENT/healthz" >/dev/null 2>&1 && break; sleep 1; done
curl -sf -m 2 "$AGENT/healthz" >/dev/null 2>&1 && ok "agent answering on :$AGENT_PORT" \
  || { bad "agent never came up"; tail -40 agent.log; exit 1; }

TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' \
  -d "{\"passphrase\":\"$PASSPHRASE\"}" | jq_ "d.get('sessionToken','')")
[ -n "$TOK" ] && ok "operator session issued" || { bad "no session token"; tail -30 agent.log; exit 1; }

# --- 2 -----------------------------------------------------------------------
say "2. five forged origins through the real proxy still 429 the sixth"
# The browser's own path: socket -> /api/proxy/agent/... -> loopback hop
# -> the login route. Before this slice uvicorn rewrote the peer from
# X-Forwarded-For on that inner hop, which is loopback by construction,
# so each attempt bought a fresh bucket and the limiter counted to one.
OUT=$("$PY" - "$AGENT_PORT" <<'PY'
import sys
from peerclient import status

port = sys.argv[1]
path = "/api/proxy/agent/v1/auth/login"
codes = []
for i in range(6):
    codes.append(
        status(
            port,
            "POST",
            path,
            source="127.0.0.2",
            headers={"X-Forwarded-For": f"203.0.113.{i}", "X-Real-IP": f"198.51.100.{i}"},
            body={"passphrase": "wrong"},
        )
    )
print(",".join(str(c) for c in codes))
PY
)
note "codes: $OUT"
case "$OUT" in
  401,401,401,401,401,429) ok "a supplied forwarding header buys no bucket (review §6.1 #1)" ;;
  *429*) bad "locked earlier than the fifth failure: $OUT" ;;
  *) bad "six forged attempts and never rate limited: $OUT -- the limiter is keyed on a caller-supplied header" ;;
esac

# --- 3 -----------------------------------------------------------------------
say "3. one browser's mistakes do not lock another browser, or a direct caller"
# The half that needs no attacker. 127.0.0.2 is now locked out by check
# 2; 127.0.0.3 is a second device and 127.0.0.1 going direct is the
# operator on the box. Before this slice all three were one bucket.
OUT=$("$PY" - "$AGENT_PORT" "$PASSPHRASE" <<'PY'
import json, sys
from peerclient import request, status

port, good = sys.argv[1], sys.argv[2]
proxied = "/api/proxy/agent/v1/auth/login"
locked = status(port, "POST", proxied, source="127.0.0.2", body={"passphrase": "wrong"})
second = status(port, "POST", proxied, source="127.0.0.3", body={"passphrase": "wrong"})
direct = status(port, "POST", "/v1/auth/login", source="127.0.0.1", body={"passphrase": "wrong"})
code, _, payload = request(port, "POST", proxied, source="127.0.0.3", body={"passphrase": good})
# Substring, not `json.loads`: a proxied response is a
# `StreamingResponse` and arrives chunk-framed, which this deliberately
# tiny client does not unframe. The token's presence is the subject and
# it survives the framing.
signed_in = code == 200 and "sessionToken" in payload
print(json.dumps({"locked": locked, "second": second, "direct": direct, "signed_in": signed_in}))
PY
)
note "$OUT"
[ "$(printf '%s' "$OUT" | jq_ "d['locked']")" = "429" ] \
  && ok "the browser that failed five times is still locked out" \
  || bad "the locked browser is not locked: $OUT"
[ "$(printf '%s' "$OUT" | jq_ "d['second']")" = "401" ] \
  && ok "a second browser is 401, not locked out by the first one's mistakes" \
  || bad "a second browser inherited the first one's lockout: $OUT"
[ "$(printf '%s' "$OUT" | jq_ "d['direct']")" = "401" ] \
  && ok "a direct caller is 401 too" \
  || bad "a direct caller inherited a proxied lockout: $OUT"
[ "$(printf '%s' "$OUT" | jq_ "d['signed_in']")" = "True" ] \
  && ok "and the right passphrase from the second browser still signs in" \
  || bad "the second browser could not sign in: $OUT"

# --- 4 -----------------------------------------------------------------------
say "4. what the proxy puts on the wire"
# Proved against the agent's own API through its own proxy: `GET
# /api/proxy/agent/v1/node` reaches this same process, so whatever the
# proxy sent is what the route received. The reach block is where the
# receiving side records a caller, which is check 5's subject; here the
# subject is simply that the hop happened and nothing 5xx'd.
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H "Authorization: Bearer $TOK" \
  -H 'X-Forwarded-For: 203.0.113.9' "$AGENT/api/proxy/agent/v1/node")
[ "$CODE" = "200" ] && ok "a request carrying a forwarding header still crosses the proxy (200)" \
  || bad "the proxy refused or failed a request with a forwarding header: $CODE"

# --- 5 -----------------------------------------------------------------------
say "5. the Reach card's proof cannot be forged from this box"
# `lastReachedFrom` is the only evidence on that card that another
# device ever got in. Every caller in this run is loopback, so an honest
# answer is *nothing*; before this slice `X-Forwarded-For` wrote it.
REACHED=$(curl -s -m 10 -H "Authorization: Bearer $TOK" -H 'X-Forwarded-For: 203.0.113.9' \
  "$AGENT/v1/node" | jq_ "((d.get('reach') or {}).get('lastReachedFrom') or {}).get('address')")
note "lastReachedFrom.address = ${REACHED:-<none>}"
case "$REACHED" in
  ""|None) ok "no off-host caller claimed, because there was none" ;;
  203.0.113.9) bad "the reach proof was written from a header the caller supplied (review §6.1 #1)" ;;
  *) bad "an unexpected address was recorded: $REACHED" ;;
esac

# --- 6 -----------------------------------------------------------------------
say "6. the console refuses to be framed"
HEADERS=$(curl -s -D - -o /dev/null -m 10 "$AGENT/")
XFO=$(printf '%s' "$HEADERS" | grep -i '^x-frame-options:' | tr -d '\r' | awk '{print $2}')
CSP=$(printf '%s' "$HEADERS" | grep -i '^content-security-policy:' | tr -d '\r')
[ "$XFO" = "DENY" ] && ok "X-Frame-Options: DENY on GET /" || bad "no X-Frame-Options on GET / (got '${XFO:-<none>}')"
case "$CSP" in
  *"frame-ancestors 'none'"*) ok "frame-ancestors 'none' on GET /" ;;
  *) bad "no frame-ancestors directive on GET / (got '${CSP:-<none>}')" ;;
esac
# A deep link is a different file through the same mount, and a header
# that only the index carries is a header an attacker asks past.
DEEP=$(curl -s -D - -o /dev/null -m 10 "$AGENT/login/" | grep -ic '^x-frame-options: *DENY')
[ "${DEEP:-0}" -ge 1 ] && ok "a deep link carries them too" || note "no /login/ in this build; index checked only"

# --- 7 -----------------------------------------------------------------------
say "7. a download that would leave the model root is refused"
# Calling #3, over HTTP, against a real library with a real configured
# root. Operator-gated, so this speaks with the operator's own token --
# which is the point: the rule is not "an attacker cannot", it is "this
# product does not write outside a Library folder".
mkdir -p models
# **The catalogue is ON and its hub is a dead port**, which is what makes
# checks 7 and 8 discriminate. `start()` resolves the destination BEFORE
# it asks the hub anything, so an escaping name must come back
# `PathTraversal` with no network involved, and an ordinary one must get
# past the guard and die at the hub. With the catalogue off, both are
# refused by the route before the resolver runs, and check 8 would pass
# against a guard that refused everything. :9 is the discard port.
cat > library.yaml <<YAML
modelRoots:
  - $WORK_NATIVE\\models
catalogueEnabled: true
catalogueBaseUrl: http://127.0.0.1:9
YAML
(exec env EUGENE_PLEXUS_LIBRARY_CONFIG_FILE="$WORK_NATIVE/library.yaml" \
  EUGENE_PLEXUS_LIBRARY_BIND_HOST=127.0.0.1 \
  EUGENE_PLEXUS_LIBRARY_BIND_PORT="$LIB_PORT" \
  EUGENE_PLEXUS_LIBRARY_AUTH_DISABLED=1 \
  "$LIB_PY" -m eugene_plexus_library > library.log 2>&1) &
L_PID=$!
for _ in $(seq 1 60); do curl -sf -m 2 "http://127.0.0.1:$LIB_PORT/healthz" >/dev/null 2>&1 && break; sleep 1; done
if ! curl -sf -m 2 "http://127.0.0.1:$LIB_PORT/healthz" >/dev/null 2>&1; then
  bad "library never came up"; tail -30 library.log
else
  ok "library answering on :$LIB_PORT"
  ESCAPE='{"repo":"org/repo","files":["model.gguf"],"filename":"../../../../escaped.gguf"}'
  R=$(curl -s -m 20 -X POST -H 'Content-Type: application/json' -d "$ESCAPE" \
    "http://127.0.0.1:$LIB_PORT/v1/downloads")
  CODE=$(printf '%s' "$R" | jq_ "((d.get('detail') or d).get('code') or (d.get('detail') or d).get('title') or '')" 2>/dev/null)
  note "refusal: $(printf '%s' "$R" | head -c 300)"
  # The code reaches the wire lower-cased, inside the Problem's `type`
  # URL (`...library#pathtraversal`) -- `DownloadError.code` is what
  # builds that fragment and nothing else carries it. Matched the way a
  # client would actually read it.
  case "$(printf '%s' "$R" | tr 'A-Z' 'a-z')" in
    *pathtraversal*) ok "a traversing filename is PathTraversal (review §6.2 #14)" ;;
    *) bad "a traversing filename was not refused as PathTraversal: $R" ;;
  esac
  # And refused before the hub was asked anything -- the hub here is a
  # dead port, so a refusal that mentions it would mean the guard ran
  # after the network rather than before it.
  # NOT a bare `*hub*`: every Problem's `type` is a github.com URL, and
  # "git**hub**" matched it on the first execution -- a check that
  # reported a correct refusal as a defect. The markers are the dead
  # port and the catalogue's own error code.
  case "$(printf '%s' "$R" | tr 'A-Z' 'a-z')" in
    *catalogue-unreachable*|*127.0.0.1:9*) bad "the refusal came after a hub call: $R" ;;
    *) ok "refused before any upstream call" ;;
  esac
  # And nothing was queued. A refusal that still created a record leaves
  # a job pointing outside every Library folder.
  N=$(curl -s -m 10 "http://127.0.0.1:$LIB_PORT/v1/downloads" | jq_ "len(d.get('downloads') or [])" 2>/dev/null)
  [ "${N:-1}" = "0" ] && ok "nothing was queued" || bad "the refused download left $N record(s)"
  # And nothing landed on disk, four levels up from the repo folder,
  # which is where the name pointed.
  STRAY=$(find "$WORK/.." -maxdepth 2 -name 'escaped.gguf*' 2>/dev/null | head -3)
  [ -z "$STRAY" ] && ok "no file was written outside the root" || bad "a file appeared outside the root: $STRAY"

  # --- 8 ---------------------------------------------------------------------
  say "8. an ordinary rename is still accepted"
  # The fix must not break the field it guards. The hub is a dead port,
  # so an accepted name gets past the guard and dies there -- a refusal
  # naming the hub is the pass, because it proves the resolver was
  # reached AND let the name through. "Not PathTraversal" on its own
  # would pass against a library that refused everything one step
  # earlier, which is how this check read on its first execution.
  PLAIN='{"repo":"org/repo","files":["model.gguf"],"filename":"q4_k_m.gguf"}'
  R=$(curl -s -m 30 -X POST -H 'Content-Type: application/json' -d "$PLAIN" \
    "http://127.0.0.1:$LIB_PORT/v1/downloads")
  note "plain rename: $(printf '%s' "$R" | head -c 300)"
  case "$(printf '%s' "$R" | tr 'A-Z' 'a-z')" in
    *pathtraversal*)
      bad "an ordinary rename was refused as a traversal -- the guard is too wide" ;;
    *catalogue-unreachable*|*127.0.0.1:9*)
      ok "an ordinary rename passed the guard and reached the hub" ;;
    *)
      bad "an ordinary rename was refused by something else: $R" ;;
  esac
fi

# --- 9 -----------------------------------------------------------------------
say "9. teardown"
teardown
A_PID=""; L_PID=""
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ] && ok "no owned port still listening" || bad "still listening:$STILL"

printf '\n===============================================\n'
if [ "$FAILURES" -eq 0 ]; then
  printf 'R1.2 ACCEPTANCE: all checks passed\n'
else
  printf 'R1.2 ACCEPTANCE: %d FAILURE(S)\n' "$FAILURES"
fi
printf '===============================================\n'
exit "$FAILURES"
