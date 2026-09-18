#!/usr/bin/env bash
# R2.4 -- credentials proportionate to the job. Live.
#
# Roadmap: docs/design/release-roadmap.md §3.4. Findings: review §6.2
# #12 (the control snapshot hands the sealed signing key, the Argon2id
# salt and the passphrase verifier to any `service:*` token), §6.2 #15
# (a correctly authenticated worker names the URL the root and the
# console proxy will dial, with a loopback check as the only filter),
# §6.3 #33 (the admin driver probe hands `service:gateway` to a URL
# typed into a form).
#
# **What only a live run can prove.** The unit gates assert status codes
# against TestClient. What they cannot show is that the tokens involved
# are the install's real ones -- minted from the key a real control root
# sealed under a real passphrase, and verified by the real process --
# and that the credential a probe would have leaked really does travel
# on a real socket to a real listener. #33 in particular is a claim
# about a header on a wire, so the check is a wire.
#
# The checks:
#   0. isolated from the live install, and from its ports
#   1. a real trust root, initialized and unlocked
#   2. the material is really there: sealed signing key, salt, verifier
#   3. **#12**: a real `service:gateway` token reads status and nodes --
#      and is REFUSED on the snapshot and on the log
#   4. **#12**: `service:control` reads both, so replication still works
#   5. **#15**: a node enrolls on loopback
#  5b. **#15**: a correctly signed announcement of the cloud metadata
#      address is 400, and the record does not move
#   6. **#15**: the same node cannot put itself on the open internet;
#      409, the remedy is named, the record does not move
#   7. **#15**: the announcements an install really makes still work
#   8. **#15**: the agent will not spend the caller's bearer on a
#      registry entry that cannot be a node
#   9. **#33**: a real gateway probes a real listener, sends NO
#      Authorization header, and reports the 401 as reachable
#  10. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped, ports are +100, state is a throwaway, teardown is by pid.
# Never `pkill -f eugene_plexus_`: this box is a worker node.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-r24}"
CONTROL_PORT="${EP_CONTROL_PORT:-8183}"
GATEWAY_PORT="${EP_GATEWAY_PORT:-8180}"
LISTENER_PORT="${EP_LISTENER_PORT:-8191}"
CONTROL="http://127.0.0.1:$CONTROL_PORT"
GATEWAY="http://127.0.0.1:$GATEWAY_PORT"
OWNED_PORTS="$CONTROL_PORT $GATEWAY_PORT $LISTENER_PORT"
PASS="r24-acceptance-passphrase"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
kill_port() { for p in $(listening_pids "$1"); do taskkill //PID "$p" //F >/dev/null 2>&1 || kill -9 "$p" 2>/dev/null; done; }
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

C_PID=""; G_PID=""; L_PID=""
teardown() {
  for p in $C_PID $G_PID $L_PID; do kill "$p" 2>/dev/null; done
  sleep 2
  for p in $OWNED_PORTS; do kill_port "$p"; done
}
trap teardown EXIT

say "0. isolation"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
for p in $OWNED_PORTS; do
  [ -z "$(listening_pids "$p")" ] || { bad "port $p is already in use; refusing to run"; exit 1; }
done
# A loop, not a list: a throwaway process that inherits the live
# worker's config file adopts its identity.
while IFS='=' read -r name _; do
  case "$name" in EUGENE_PLEXUS_*) unset "$name" ;; esac
done < <(env)
"$PY" -c "import eugene_plexus_agent, eugene_plexus_control, eugene_plexus_gateway" 2>/dev/null \
  || { bad "agent, control and gateway must all import from $PY"; exit 1; }
rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK" || exit 1
ok "ambient EUGENE_PLEXUS_* cleared; ports $OWNED_PORTS free; work dir $WORK"

# --- 1. a real trust root --------------------------------------------------
say "1. a real trust root, initialized and unlocked"
echo "logLevel: INFO" > control.yaml
EUGENE_PLEXUS_CONTROL_CONFIG_FILE="$(win_path "$WORK/control.yaml")" \
EUGENE_PLEXUS_CONTROL_STATE_DIR="$(win_path "$WORK/control-state")" \
EUGENE_PLEXUS_CONTROL_BIND_PORT="$CONTROL_PORT" \
  "$PY" -m eugene_plexus_control > control.log 2>&1 &
C_PID=$!
for _ in $(seq 1 60); do curl -sf -m 2 "$CONTROL/healthz" >/dev/null 2>&1 && break; sleep 1; done
curl -sf -m 2 "$CONTROL/healthz" >/dev/null 2>&1 \
  || { bad "control root never answered"; tail -20 control.log; exit 1; }
[ "$(code_of -X POST "$CONTROL/v1/auth/initialize" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}")" = "204" ] \
  || { bad "initialize failed"; exit 1; }
OPTOK=$(curl -s -X POST "$CONTROL/v1/auth/login" -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d['sessionToken']")
[ -n "$OPTOK" ] && ok "control root up on :$CONTROL_PORT, initialized, operator session held" \
  || { bad "login failed"; exit 1; }

# --- 2. the material is really there ---------------------------------------
say "2. what the replication surface actually carries"
curl -s -H "Authorization: Bearer $OPTOK" "$CONTROL/v1/control/snapshot" > snapshot.json
HAS=$(PYTHONUTF8=1 python -c "
import json
d = json.load(open('snapshot.json', encoding='utf-8'))
print(int(d.get('passphraseVerifier','').startswith('\$argon2') and bool(d.get('salt')) and bool(d.get('sealedSigningKey'))))
")
[ "$HAS" = "1" ] \
  && ok "the snapshot carries sealedSigningKey + salt + an Argon2id passphraseVerifier -- the refusals below are about something" \
  || bad "the snapshot does not carry the key material this slice is about: $(head -c 300 snapshot.json)"

# The install's real signing key, opened the way a standby would, and
# used to mint two service tokens. Not invented keys: these are tokens
# this root verifies.
eval "$("$PY" - "$PASS" <<'MINT'
import base64, json, sys, time
import jwt
from eugene_plexus_control import security

snap = json.load(open("snapshot.json", encoding="utf-8"))
master = security.derive_master_key(sys.argv[1], base64.b64decode(snap["salt"]))
key = security.open_b64(snap["sealedSigningKey"], master)


def issue(sub, aud):
    now = int(time.time())
    claims = {"sub": sub, "aud": aud, "iat": now, "exp": now + 3600}
    return jwt.encode(claims, key, algorithm="HS256")


print("GWTOK=" + issue("gateway", "service:gateway"))
print("CTLTOK=" + issue("control", "service:control"))
print("OPTOK_GW=" + issue("operator", "operator"))
print("INSTALL_KEY=" + base64.b64encode(key).decode())
MINT
)"
[ -n "${GWTOK:-}" ] \
  && ok "minted service:gateway, service:control and an operator token from the install's own key" \
  || { bad "could not mint service tokens"; exit 1; }

# --- 3. #12 ----------------------------------------------------------------
say "3. #12 -- a service token that is not the standby cannot pull key material"
S_STATUS=$(code_of -H "Authorization: Bearer $GWTOK" "$CONTROL/v1/control/status")
S_NODES=$(code_of -H "Authorization: Bearer $GWTOK" "$CONTROL/v1/nodes")
S_SNAP=$(code_of -H "Authorization: Bearer $GWTOK" "$CONTROL/v1/control/snapshot")
S_LOG=$(code_of -H "Authorization: Bearer $GWTOK" "$CONTROL/v1/control/log?after=0")
{ [ "$S_STATUS" = "200" ] && [ "$S_NODES" = "200" ]; } \
  && ok "service:gateway still reads status ($S_STATUS) and nodes ($S_NODES) -- an agent needs the epoch" \
  || bad "service:gateway lost a read it needs: status=$S_STATUS nodes=$S_NODES"
[ "$S_SNAP" = "401" ] \
  && ok "*** service:gateway is REFUSED on /v1/control/snapshot (401) -- no offline attack on the verifier ***" \
  || bad "the snapshot answered $S_SNAP to service:gateway"
[ "$S_LOG" = "401" ] \
  && ok "*** and on /v1/control/log (401) -- the entries that wrote the key material are the same door ***" \
  || bad "the log answered $S_LOG to service:gateway"

# --- 4. #12, the other side ------------------------------------------------
say "4. #12 -- replication is untouched"
R_SNAP=$(code_of -H "Authorization: Bearer $CTLTOK" "$CONTROL/v1/control/snapshot")
R_LOG=$(code_of -H "Authorization: Bearer $CTLTOK" "$CONTROL/v1/control/log?after=0")
{ [ "$R_SNAP" = "200" ] && [ "$R_LOG" = "200" ]; } \
  && ok "service:control reads the snapshot ($R_SNAP) and the log ($R_LOG) -- a standby bootstraps with nobody logged in" \
  || bad "the fix cost failover: snapshot=$R_SNAP log=$R_LOG"

# --- 5. #15 ----------------------------------------------------------------
say "5. #15 -- a node enrolls, on loopback"
"$PY" - > nodekeys.txt <<'KEYS'
import base64
import nacl.signing

s = nacl.signing.SigningKey.generate()
print(base64.b64encode(bytes(s)).decode())
print(base64.b64encode(bytes(s.verify_key)).decode())
KEYS
NODE_PRIV=$(sed -n 1p nodekeys.txt | tr -d '\r')
NODE_PUB=$(sed -n 2p nodekeys.txt | tr -d '\r')
SEAL_PUB=$("$PY" -c "import base64; print(base64.b64encode(b'x'*32).decode())" | tr -d '\r')
JOIN=$(curl -s -X POST -H "Authorization: Bearer $OPTOK" "$CONTROL/v1/nodes/join-token" | jq_ "d['token']")
E=$(code_of -X POST "$CONTROL/v1/nodes/enroll" -H 'content-type: application/json' \
  -d "{\"token\":\"$JOIN\",\"name\":\"gpu-box\",\"publicKey\":\"$SEAL_PUB\",\"signingPublicKey\":\"$NODE_PUB\",\"url\":\"http://127.0.0.1:8079\"}")
[ "$E" = "201" ] \
  && ok "gpu-box enrolled at http://127.0.0.1:8079 -- a fresh standalone install, before the Reach switch" \
  || { bad "enroll returned $E"; exit 1; }

announce() {  # $1 url, $2 sequence -> body then http code on the last line
  local body
  body=$("$PY" - "$NODE_PRIV" "$1" "$2" <<'SIGN'
import json, sys
from eugene_plexus_control import sealing

private, url, seq = sys.argv[1], sys.argv[2], int(sys.argv[3])
message = sealing.address_message(name="gpu-box", sequence=seq, url=url)
print(json.dumps({"url": url, "sequence": seq, "signature": sealing.sign_address(private, message)}))
SIGN
)
  curl -s -w '\n%{http_code}' -X PATCH "$CONTROL/v1/nodes/gpu-box" \
    -H 'content-type: application/json' -d "$body"
}
node_url() { curl -s -H "Authorization: Bearer $OPTOK" "$CONTROL/v1/nodes/gpu-box" | jq_ "d.get('url')"; }

say "5b. #15 -- the cloud metadata address, correctly signed"
R=$(announce "http://169.254.169.254/" 1); CODE=$(echo "$R" | tail -1); BODY=$(echo "$R" | sed '$d')
[ "$CODE" = "400" ] \
  && ok "*** a correctly signed announcement of http://169.254.169.254/ is 400: $(echo "$BODY" | jq_ "d['detail']['detail'][:110]") ***" \
  || bad "the metadata address returned $CODE: $BODY"
[ "$(node_url)" = "http://127.0.0.1:8079/" ] && ok "and the record did not move" || bad "the record moved to $(node_url)"

say "6. #15 -- a node cannot put itself on the open internet"
R=$(announce "http://8.8.8.8:8079" 1); CODE=$(echo "$R" | tail -1); BODY=$(echo "$R" | sed '$d')
[ "$CODE" = "409" ] \
  && ok "*** loopback -> a public address is 409: $(echo "$BODY" | jq_ "d['detail']['detail'][:110]") ***" \
  || bad "the public address returned $CODE: $BODY"
echo "$BODY" | jq_ "d['detail']['detail']" | grep -qi "re-enroll" \
  && ok "and the remedy is named -- re-enrollment, which needs an operator-minted join token" \
  || bad "the 409 does not name a remedy"
[ "$(node_url)" = "http://127.0.0.1:8079/" ] && ok "the record did not move" || bad "the record moved to $(node_url)"

say "7. #15 -- and the moves every install really makes still work"
CODE=$(announce "http://192.168.16.75:8079" 1 | tail -1)
[ "$CODE" = "200" ] \
  && ok "loopback -> the LAN is 200 -- that is the S5 Reach switch, one click on Home" \
  || bad "the Reach switch was refused: $CODE"
CODE=$(announce "http://100.64.0.9:8079" 2 | tail -1)
[ "$CODE" = "200" ] \
  && ok "and the LAN -> a tailnet address (100.64.0.0/10) is 200, which is_private alone would have called public" \
  || bad "a tailnet address was refused: $CODE"

# --- 8. #15, at the point of use -------------------------------------------
say "8. #15 -- the agent will not spend the caller's bearer on a non-node address"
"$PY" - > proxy.json <<'PROXY'
import json

from eugene_plexus_agent import install_proxy

snapshot = install_proxy._Snapshot(
    expires_at=0.0,
    owners={"gateway": "root"},
    node_urls={"root": "http://169.254.169.254/"},
)
try:
    install_proxy._reachable_url(snapshot, "root", "the gateway")
    print(json.dumps({"raised": False, "why": ""}))
except install_proxy.InstallLookupError as exc:
    print(json.dumps({"raised": True, "why": str(exc)}))
PROXY
[ "$(jq_ "d['raised']" < proxy.json)" = "True" ] \
  && ok "*** a registry entry of http://169.254.169.254/ is refused before the hop: $(jq_ "d['why'][:110]" < proxy.json) ***" \
  || bad "the proxy would have dialled it: $(cat proxy.json)"

# --- 9. #33 ----------------------------------------------------------------
say "9. #33 -- what the driver probe puts on the wire"
cat > listener.py <<'LISTENER'
import http.server
import json
import sys

seen = []


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # **Only the probe's own path is recorded.** The readiness loop
        # above dials `/` until this listener answers, and the first
        # execution of this script counted those too -- `[null, null]`
        # against an expected `[null]`, a harness defect reported as a
        # product one. The subject is what the gateway sends to
        # `/v1/info`.
        if self.path == "/v1/info":
            seen.append(self.headers.get("authorization"))
            with open("probe-headers.json", "w", encoding="utf-8") as fh:
                json.dump(seen, fh)
        self.send_response(401)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"detail":"a key is required"}')

    def log_message(self, *args):
        return


http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
LISTENER
"$PY" listener.py "$LISTENER_PORT" > listener.log 2>&1 &
L_PID=$!
for _ in $(seq 1 30); do
  curl -s -m 1 -o /dev/null "http://127.0.0.1:$LISTENER_PORT/" && break
  sleep 1
done
rm -f probe-headers.json

echo "logLevel: INFO" > gateway.yaml
EUGENE_PLEXUS_GATEWAY_CONFIG_FILE="$(win_path "$WORK/gateway.yaml")" \
EUGENE_PLEXUS_GATEWAY_BIND_PORT="$GATEWAY_PORT" \
EUGENE_PLEXUS_GATEWAY_AUTH_SIGNING_KEY="$INSTALL_KEY" \
EUGENE_PLEXUS_GATEWAY_SERVICE_TOKEN="$GWTOK" \
  "$PY" -m eugene_plexus_gateway > gateway.log 2>&1 &
G_PID=$!
for _ in $(seq 1 60); do curl -sf -m 2 "$GATEWAY/healthz" >/dev/null 2>&1 && break; sleep 1; done
curl -sf -m 2 "$GATEWAY/healthz" >/dev/null 2>&1 || { bad "gateway never answered"; tail -20 gateway.log; }

PROBE=$(curl -s -X POST "$GATEWAY/v1/admin/drivers/probe" \
  -H "Authorization: Bearer $OPTOK_GW" -H 'content-type: application/json' \
  -d "{\"url\":\"http://127.0.0.1:$LISTENER_PORT/\",\"name\":\"candidate\"}")
SEEN=$(cat probe-headers.json 2>/dev/null || echo 'NOTHING-ARRIVED')
[ "$SEEN" = '[null]' ] \
  && ok "*** the probe sent NO Authorization header to a URL typed into a form -- the install's service token stayed here ***" \
  || bad "the probe did not arrive unauthenticated: $SEEN"
[ "$(echo "$PROBE" | jq_ "d.get('reachable')")" = "True" ] \
  && ok "and a 401 is reported reachable: $(echo "$PROBE" | jq_ "d.get('error','')[:110]")" \
  || bad "a 401 was reported unreachable: $PROBE"
grep -qF "$(echo "$GWTOK" | cut -c1-40)" probe-headers.json 2>/dev/null \
  && bad "the service token's own bytes appear in what the listener saw" \
  || ok "and the service token's own bytes appear nowhere in what the listener saw"

# --- 10. teardown ----------------------------------------------------------
say "10. teardown"
for p in $C_PID $G_PID $L_PID; do kill "$p" 2>/dev/null; done
sleep 3
LEFT=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && LEFT="$LEFT $p"; done
[ -z "$LEFT" ] && ok "no owned port still listening" || bad "still listening:$LEFT"

say "what this run proved / could not"
echo "  proved: the refusals are about a snapshot that really carries sealedSigningKey + salt + the Argon2id"
echo "          verifier, refused to a token this root really verifies; a correctly signed announcement of the"
echo "          cloud metadata address refused by a real root with the record unmoved; a real gateway probing a"
echo "          real listener with no Authorization header at all."
echo "  cannot: a real standby following a real active root across two hosts (m5/m7 territory); a browser driving"
echo "          the Test button; and the 409's remedy end to end -- re-enrolling a node after a genuine address"
echo "          change is an operator action nobody performed here."

printf '\n'
[ "$FAILURES" -eq 0 ] && { echo "ALL CHECKS PASSED"; exit 0; }
echo "$FAILURES CHECK(S) FAILED"; exit 1
