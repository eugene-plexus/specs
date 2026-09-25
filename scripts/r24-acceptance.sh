#!/usr/bin/env bash
# R2.4 -- credentials proportionate to the job. Live.
#
# Roadmap: docs/design/release-roadmap.md §3.4. Findings: review §6.2
# #12 (the control snapshot hands the sealed token key, the Argon2id
# salt and the passphrase verifier to a service token), §6.2 #15 (a
# correctly authenticated worker names the URL the root and the console
# proxy will dial, with a loopback check as the only filter), §6.3 #33
# (the admin driver probe hands the gateway's own credential to a URL
# typed into a form).
#
# **Moved onto per-node token keys on 2026-09-25**
# (docs/design/per-node-token-keys.md). There is no install signing key
# any more, so nothing here is minted from one. The fake node this run
# enrolls generates its own token key, signing key and sealing key, sends
# only the public halves, and gets back a trust bundle and the root's
# identity key -- exactly what an agent does. Its tokens are the ones a
# member node can really sign (`sub: agent`, and `sub: gateway` because
# it is joined with the gateway grant). The one root-signed service token
# comes from the root's own token key, opened from the snapshot with the
# passphrase, which is what a standby would have to do. The gateway is
# handed what an agent hands a child: the bundle file, the root's
# identity key, `node:gpu-box` as its recipient and a token addressed to
# that machine -- no key of any kind. The operator's session at the
# gateway is a sign-in the root forwarded for gpu-box, the way an
# enrolled agent's login works.
#
# **#12 is STRICTER than R2.4 left it.** R2.4 let `service:control`
# read the replication surface so that an unattended standby could
# follow; now the snapshot and the log take an operator session and
# nothing else (design D5, and §5, which names the missing standby
# credential as a residual gap). Check 5 asserts the stricter rule: even
# a service token signed by the ROOT's own key is refused there.
# Removed: the old check that `service:control` reads both, because
# that credential no longer exists and its replacement is refused on
# purpose.
#
# What only a live run can prove. The unit gates assert status codes
# against TestClient. What they cannot show is that the tokens involved
# verify against a real root's real bundle -- signed by keys a real
# enrollment registered, and the root key sealed under a real
# passphrase -- and that the credential a probe would have leaked really
# does travel on a real socket to a real listener. #33 in particular is
# a claim about a header on a wire, so the check is a wire.
#
# The checks:
#   0. isolated from the live install, and from its ports
#   1. a real trust root, initialized; its own session names only `control`
#   2. the material is really there: sealed token key, salt, verifier --
#      and the passphrase opens the root's token key from it
#   3. a node enrolls on loopback with its own token key and the gateway
#      grant; it gets a trust bundle and no install key
#   4. **#12**: that node's `sub: agent` and `sub: gateway` tokens read
#      status and nodes -- and are REFUSED on the snapshot and the log
#   5. **#12, stricter**: a `sub: control` service token signed by the
#      root's own key verifies against the live bundle and is still
#      refused on both; only a session reads them
#  5b. **#15**: a correctly signed announcement of the cloud metadata
#      address is 400, and the record does not move
#   6. **#15**: the same node cannot put itself on the open internet;
#      409, the remedy is named, the record does not move
#   7. **#15**: the announcements an install really makes still work
#   8. **#15**: the agent will not spend the caller's bearer on a
#      registry entry that cannot be a node
#   9. **#33**: a real, authenticated gateway probes a real listener,
#      sends NO Authorization header, and reports the 401 as reachable
#  10. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped, ports are +100 and overridable, state is a throwaway,
# teardown is by pid. The node this run enrolls is registered at a port
# this run owns and nothing listens on, and the "LAN" and "tailnet"
# addresses it announces are unrouted ones -- the root probes and pushes
# bundles to whatever address a node has, and none of them may be the
# live agent on this box. The gateway's agent URL is the same dead port,
# for the same reason (its default is 8079). Never `pkill -f
# eugene_plexus_`: this box is a worker node.
#
# Last run 2026-09-25, beside two other acceptance runs holding 81xx:
#   EP_CONTROL_PORT=8283 EP_GATEWAY_PORT=8280 EP_LISTENER_PORT=8291 \
#   EP_NODE_PORT=8292 bash scripts/r24-acceptance.sh
# -> 30 PASS, ALL CHECKS PASSED (first execution after the rewrite), and
#    green again as r24-sabotage.py's live baseline and restored gate.
# 2026-09-18 (old model): 21 PASS, second execution.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-r24}"
CONTROL_PORT="${EP_CONTROL_PORT:-8183}"
GATEWAY_PORT="${EP_GATEWAY_PORT:-8180}"
LISTENER_PORT="${EP_LISTENER_PORT:-8191}"
# Where gpu-box says it is. Nothing listens here, on purpose.
NODE_PORT="${EP_NODE_PORT:-8192}"
CONTROL="http://127.0.0.1:$CONTROL_PORT"
GATEWAY="http://127.0.0.1:$GATEWAY_PORT"
NODE_URL="http://127.0.0.1:$NODE_PORT"
OWNED_PORTS="$CONTROL_PORT $GATEWAY_PORT $LISTENER_PORT $NODE_PORT"
PASS="r24-acceptance-passphrase"

FAILURES=0
PASSES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; PASSES=$((PASSES + 1)); }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
kill_port() { for p in $(listening_pids "$1"); do taskkill //PID "$p" //F >/dev/null 2>&1 || kill -9 "$p" 2>/dev/null; done; }
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }
code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
claims_of() {  # a JWT's payload, unverified, as JSON
  printf '%s' "$1" | cut -d. -f2 | tr '_-' '/+' \
    | python -c "import sys,base64,json;s=sys.stdin.read().strip();print(json.dumps(json.loads(base64.b64decode(s+'='*(-len(s)%4)))))"
}

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
[ -z "$(env | grep '^EUGENE_PLEXUS_' || true)" ] || { bad "an EUGENE_PLEXUS_* variable survived"; exit 1; }
# No OS keyring: a throwaway root must never read or write the live one.
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
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
[ -n "$OPTOK" ] || { bad "login failed"; exit 1; }
[ "$(claims_of "$OPTOK" | jq_ "d['aud']")" = "['control']" ] \
  && ok "control root up on :$CONTROL_PORT, initialized; a sign-in made at the root is addressed to control alone" \
  || bad "the root's own session is addressed to $(claims_of "$OPTOK" | jq_ "d['aud']")"

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

# The root's token key, opened the way only the passphrase can open it --
# which is what the salt and verifier in that document are an offline
# attack on. Kept in the work dir for check 5's root-signed token.
OPENED=$("$PY" - "$PASS" <<'OPEN'
import base64, json, sys

from eugene_plexus_control import security, tokens

snap = json.load(open("snapshot.json", encoding="utf-8"))
master = security.derive_master_key(sys.argv[1], base64.b64decode(snap["salt"]))
key = tokens.load_private(security.open_b64(snap["sealedSigningKey"], master))
with open("root-token.key", "w", encoding="ascii") as fh:
    fh.write(tokens.private_to_b64(key))
print("match" if tokens.public_b64(key) == snap.get("rootTokenPublicKey") else "mismatch")
OPEN
)
[ "$OPENED" = "match" ] \
  && ok "the passphrase opens the root's token key out of that snapshot, and it is the key rootTokenPublicKey names" \
  || { bad "could not open the root's token key from the snapshot: $OPENED"; exit 1; }

# --- 3. a node enrolls -----------------------------------------------------
say "3. a node enrolls on loopback, with its own token key and the gateway grant"
"$PY" - > nodekeys.txt <<'KEYS'
import base64

import nacl.signing

from eugene_plexus_control import sealing, tokens

address = nacl.signing.SigningKey.generate()
token_key = tokens.generate_private_key()
with open("node-token.key", "w", encoding="ascii") as fh:
    fh.write(tokens.private_to_b64(token_key))
print(base64.b64encode(bytes(address)).decode())
print(base64.b64encode(bytes(address.verify_key)).decode())
print(tokens.public_b64(token_key))
print(sealing.generate_sealing_keypair().public)
KEYS
NODE_PRIV=$(sed -n 1p nodekeys.txt | tr -d '\r')
NODE_PUB=$(sed -n 2p nodekeys.txt | tr -d '\r')
TOKEN_PUB=$(sed -n 3p nodekeys.txt | tr -d '\r')
SEAL_PUB=$(sed -n 4p nodekeys.txt | tr -d '\r')
# The gateway grant, because check 4 needs the strongest service token a
# member node can hold and check 9 runs a gateway on this machine.
JOIN=$(curl -s -X POST -H "Authorization: Bearer $OPTOK" -H 'content-type: application/json' \
  -d '{"nodeName":"gpu-box","grants":["gateway"]}' "$CONTROL/v1/nodes/join-token" | jq_ "d['token']")
curl -s -o enroll.json -w '%{http_code}' -X POST "$CONTROL/v1/nodes/enroll" -H 'content-type: application/json' \
  -d "{\"token\":\"$JOIN\",\"name\":\"gpu-box\",\"publicKey\":\"$SEAL_PUB\",\"signingPublicKey\":\"$NODE_PUB\",\"tokenPublicKey\":\"$TOKEN_PUB\",\"url\":\"$NODE_URL\"}" > enroll.code
E=$(cat enroll.code)
[ "$E" = "201" ] \
  && ok "gpu-box enrolled at $NODE_URL -- a fresh standalone install, before the Reach switch" \
  || { bad "enroll returned $E: $(head -c 300 enroll.json)"; exit 1; }
CONTROL_PUB=$(jq_ "d['controlPublicKey']" < enroll.json)
SHAPE=$(jq_ "(bool(d.get('trustBundle',{}).get('jws')), 'signingKey' in d, 'signingKeyId' in d)" < enroll.json)
[ "$SHAPE" = "(True, False, False)" ] && [ -n "$CONTROL_PUB" ] \
  && ok "the enrollment carries a signed trust bundle and the root's identity key, and no install signing key" \
  || bad "enrollment response shape: $SHAPE, controlPublicKey '$CONTROL_PUB'"

mint() {  # signer(node|root) typ(service|session) sub aud(comma list) ttl -> one token
  "$PY" - "$@" <<'MINT'
import sys

from eugene_plexus_control import tokens

signer, typ, sub, aud, ttl = sys.argv[1:6]
key_file = {"node": "node-token.key", "root": "root-token.key"}[signer]
issuer = {"node": "node:gpu-box", "root": tokens.ISSUER_CONTROL}[signer]
key = tokens.load_private(open(key_file, encoding="ascii").read().strip())
token, _ = tokens.Signer(key=key, issuer=issuer).mint(
    typ={"service": tokens.TYP_SERVICE, "session": tokens.TYP_SESSION}[typ],
    sub=sub,
    aud=aud.split(","),
    ttl_seconds=int(ttl),
)
print(token)
MINT
}
AGTOK=$(mint node service agent control 900 | tr -d '\r')
GWTOK=$(mint node service gateway control 900 | tr -d '\r')
CTLTOK=$(mint root service control control 300 | tr -d '\r')
{ [ -n "$AGTOK" ] && [ -n "$GWTOK" ] && [ -n "$CTLTOK" ]; } \
  && ok "minted gpu-box's sub:agent and sub:gateway tokens for the root, and a sub:control token with the root's own key" \
  || { bad "could not mint the tokens"; exit 1; }

# --- 4. #12 ----------------------------------------------------------------
say "4. #12 -- a member node's service tokens cannot pull key material"
for pair in "agent:$AGTOK" "gateway:$GWTOK"; do
  SUB=${pair%%:*}; T=${pair#*:}
  S_STATUS=$(code_of -H "Authorization: Bearer $T" "$CONTROL/v1/control/status")
  S_NODES=$(code_of -H "Authorization: Bearer $T" "$CONTROL/v1/nodes")
  S_SNAP=$(code_of -H "Authorization: Bearer $T" "$CONTROL/v1/control/snapshot")
  S_LOG=$(code_of -H "Authorization: Bearer $T" "$CONTROL/v1/control/log?after=0")
  { [ "$S_STATUS" = "200" ] && [ "$S_NODES" = "200" ]; } \
    && ok "gpu-box's sub:$SUB token reads status ($S_STATUS) and nodes ($S_NODES) -- a real token this root accepts" \
    || bad "gpu-box's sub:$SUB token lost a read it needs: status=$S_STATUS nodes=$S_NODES"
  [ "$S_SNAP" = "401" ] \
    && ok "*** and is REFUSED on /v1/control/snapshot (401) -- no offline attack on the verifier ***" \
    || bad "the snapshot answered $S_SNAP to gpu-box's sub:$SUB token"
  [ "$S_LOG" = "401" ] \
    && ok "*** and on /v1/control/log (401) -- the entries that wrote the key material are the same door ***" \
    || bad "the log answered $S_LOG to gpu-box's sub:$SUB token"
done

# --- 5. #12, stricter than R2.4 --------------------------------------------
say "5. #12 -- replication takes a session and nothing else"
# The genuineness proof first: the component's own verifier, against the
# bundle the root is serving right now, accepts this token as a service
# token addressed to control. So a refusal below is about the route.
curl -s "$CONTROL/v1/trust/bundle" > bundle-now.json
GENUINE=$("$PY" - "$CTLTOK" "$CONTROL_PUB" <<'VERIFY'
import json
import sys

from eugene_plexus_control import tokens

jws = json.load(open("bundle-now.json", encoding="utf-8"))["jws"]
bundle = tokens.parse_bundle(jws, authority=sys.argv[2])
try:
    claims = tokens.verify(
        sys.argv[1], bundle=bundle, recipient=tokens.RECIPIENT_CONTROL, classes=(tokens.TYP_SERVICE,)
    )
    print(f"verified {claims.iss} {claims.sub}")
except tokens.TokenError as exc:
    print(f"refused: {exc}")
VERIFY
)
[ "$GENUINE" = "verified control control" ] \
  && ok "a sub:control service token signed by the root's own key verifies against the live bundle" \
  || bad "the root-signed control token does not even verify, so its refusal below would prove nothing: $GENUINE"
R_SNAP=$(code_of -H "Authorization: Bearer $CTLTOK" "$CONTROL/v1/control/snapshot")
R_LOG=$(code_of -H "Authorization: Bearer $CTLTOK" "$CONTROL/v1/control/log?after=0")
{ [ "$R_SNAP" = "401" ] && [ "$R_LOG" = "401" ]; } \
  && ok "*** and it is REFUSED on the snapshot ($R_SNAP) and the log ($R_LOG) -- stricter than R2.4, which let service:control in ***" \
  || bad "the root's own service token opened replication: snapshot=$R_SNAP log=$R_LOG"
O_SNAP=$(code_of -H "Authorization: Bearer $OPTOK" "$CONTROL/v1/control/snapshot")
O_LOG=$(code_of -H "Authorization: Bearer $OPTOK" "$CONTROL/v1/control/log?after=0")
{ [ "$O_SNAP" = "200" ] && [ "$O_LOG" = "200" ]; } \
  && ok "an operator session reads the snapshot ($O_SNAP) and the log ($O_LOG) -- the door is narrow, not shut" \
  || bad "the operator session was refused: snapshot=$O_SNAP log=$O_LOG"

# --- 5b-7. #15 -------------------------------------------------------------
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
[ "$(node_url)" = "$NODE_URL/" ] && ok "and the record did not move" || bad "the record moved to $(node_url)"

say "6. #15 -- a node cannot put itself on the open internet"
R=$(announce "http://8.8.8.8:$NODE_PORT" 1); CODE=$(echo "$R" | tail -1); BODY=$(echo "$R" | sed '$d')
[ "$CODE" = "409" ] \
  && ok "*** loopback -> a public address is 409: $(echo "$BODY" | jq_ "d['detail']['detail'][:110]") ***" \
  || bad "the public address returned $CODE: $BODY"
echo "$BODY" | jq_ "d['detail']['detail']" | grep -qi "re-enroll" \
  && ok "and the remedy is named -- re-enrollment, which needs an operator-minted join token" \
  || bad "the 409 does not name a remedy"
[ "$(node_url)" = "$NODE_URL/" ] && ok "the record did not move" || bad "the record moved to $(node_url)"

say "7. #15 -- and the moves every install really makes still work"
# Unrouted private addresses, not this box's LAN one: the root probes
# and pushes bundles to wherever a node says it is.
CODE=$(announce "http://10.255.0.9:$NODE_PORT" 1 | tail -1)
[ "$CODE" = "200" ] \
  && ok "loopback -> the LAN is 200 -- that is the S5 Reach switch, one click on Home" \
  || bad "the Reach switch was refused: $CODE"
CODE=$(announce "http://100.64.0.9:$NODE_PORT" 2 | tail -1)
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

# What gpu-box's agent would hand the gateway it spawns: the bundle it
# keeps, the root identity it pinned, its own recipient name, and a
# token its own key signs for this machine alone. No key.
curl -s "$CONTROL/v1/trust/bundle" > trust_bundle.json
LOCALTOK=$(mint node service gateway node:gpu-box 3600 | tr -d '\r')
echo "logLevel: INFO" > gateway.yaml
EUGENE_PLEXUS_GATEWAY_CONFIG_FILE="$(win_path "$WORK/gateway.yaml")" \
EUGENE_PLEXUS_GATEWAY_BIND_PORT="$GATEWAY_PORT" \
EUGENE_PLEXUS_GATEWAY_AGENT_URL="$NODE_URL" \
EUGENE_PLEXUS_GATEWAY_TRUST_BUNDLE_FILE="$(win_path "$WORK/trust_bundle.json")" \
EUGENE_PLEXUS_GATEWAY_TRUST_AUTHORITY="$CONTROL_PUB" \
EUGENE_PLEXUS_GATEWAY_AUTH_RECIPIENT="node:gpu-box" \
EUGENE_PLEXUS_GATEWAY_SERVICE_TOKEN="$LOCALTOK" \
  "$PY" -m eugene_plexus_gateway > gateway.log 2>&1 &
G_PID=$!
for _ in $(seq 1 60); do curl -sf -m 2 "$GATEWAY/healthz" >/dev/null 2>&1 && break; sleep 1; done
curl -sf -m 2 "$GATEWAY/healthz" >/dev/null 2>&1 || { bad "gateway never answered"; tail -20 gateway.log; }

# The operator at gpu-box: the root mints the session when gpu-box's
# agent forwards the sign-in with its own token as the actor.
GBSESSION=$(curl -s -X POST "$CONTROL/v1/auth/login" -H "Authorization: Bearer $AGTOK" \
  -H 'content-type: application/json' -d "{\"passphrase\":\"$PASS\"}" | jq_ "d['sessionToken']")
[ "$(claims_of "$GBSESSION" | jq_ "d['aud']")" = "['node:gpu-box', 'control']" ] \
  && ok "a sign-in forwarded for gpu-box comes back addressed to that machine and the root" \
  || bad "forwarded sign-in: $(claims_of "$GBSESSION" 2>/dev/null)"
# The absence of a header below means something only if this gateway
# holds a credential and checks one. So: it is authenticated, against
# the bundle, and addressed.
G_NONE=$(code_of "$GATEWAY/v1/config")
G_ROOT=$(code_of -H "Authorization: Bearer $OPTOK" "$GATEWAY/v1/config")
G_GB=$(code_of -H "Authorization: Bearer $GBSESSION" "$GATEWAY/v1/config")
{ [ "$G_NONE" = "401" ] && [ "$G_ROOT" = "401" ] && [ "$G_GB" = "200" ]; } \
  && ok "the gateway runs authenticated: no bearer $G_NONE, the root's own session $G_ROOT, gpu-box's session $G_GB" \
  || bad "the gateway is not verifying as gpu-box's: none=$G_NONE root-session=$G_ROOT gpu-box-session=$G_GB"

PROBE=$(curl -s -X POST "$GATEWAY/v1/admin/drivers/probe" \
  -H "Authorization: Bearer $GBSESSION" -H 'content-type: application/json' \
  -d "{\"url\":\"http://127.0.0.1:$LISTENER_PORT/\",\"name\":\"candidate\"}")
SEEN=$(cat probe-headers.json 2>/dev/null || echo 'NOTHING-ARRIVED')
[ "$SEEN" = '[null]' ] \
  && ok "*** the probe sent NO Authorization header to a URL typed into a form -- the gateway's token stayed here ***" \
  || bad "the probe did not arrive unauthenticated: $SEEN"
[ "$(echo "$PROBE" | jq_ "d.get('reachable')")" = "True" ] \
  && ok "and a 401 is reported reachable: $(echo "$PROBE" | jq_ "d.get('error','')[:110]")" \
  || bad "a 401 was reported unreachable: $PROBE"
# The signature segment: the header of every EdDSA token here begins
# with the same bytes, so a prefix would match any token at all.
grep -qF "$(echo "$LOCALTOK" | cut -d. -f3 | cut -c1-40)" probe-headers.json 2>/dev/null \
  && bad "the gateway's own token appears in what the listener saw" \
  || ok "and the gateway's own token appears nowhere in what the listener saw"

# --- 10. teardown ----------------------------------------------------------
say "10. teardown"
for p in $C_PID $G_PID $L_PID; do kill "$p" 2>/dev/null; done
sleep 3
LEFT=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && LEFT="$LEFT $p"; done
[ -z "$LEFT" ] && ok "no owned port still listening" || bad "still listening:$LEFT"

say "what this run proved / could not"
echo "  proved: the refusals are about a snapshot that really carries the sealed root token key + salt + the"
echo "          Argon2id verifier, refused to tokens this root really verifies -- a member's sub:agent and"
echo "          granted sub:gateway tokens, and a sub:control token signed by the root's own key; a correctly"
echo "          signed announcement of the cloud metadata address refused by a real root with the record"
echo "          unmoved; a real, authenticated gateway probing a real listener with no Authorization header."
echo "  cannot: a real standby following a real active root (it has no credential for the replication"
echo "          surface now; design §5); a browser driving the Test button; and the 409's remedy end to end --"
echo "          re-enrolling a node after a genuine address change is an operator action nobody performed here."

printf '\n%s PASS\n' "$PASSES"
[ "$FAILURES" -eq 0 ] && { echo "ALL CHECKS PASSED"; exit 0; }
echo "$FAILURES CHECK(S) FAILED"; exit 1
