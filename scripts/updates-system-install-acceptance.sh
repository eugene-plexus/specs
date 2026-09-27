#!/usr/bin/env bash
# In-app updates, the Linux system install: the root helper, live.
#
# The claim (docs/design/in-app-updates.md §1.4): a system install runs as
# its own account, which owns its prefix -- so the update the app asks for is
# carried out by a root-owned helper outside the prefix, and root never runs,
# and never writes through, anything that account controls.
#
# Runs AS ROOT in the WSL2 guest (`wsl -u root` needs no password):
#   wsl.exe -u root -e env EP_PERSON=tcorbin bash /mnt/d/py/eugene-plexus/specs/scripts/updates-system-install-acceptance.sh
#
# EP_TARGET is the specs ref to update TO. Left unset, the run asks the
# installed agent for the newest on edge and updates to that when it is
# newer; when the install already IS the newest, it updates to the same ref
# anyway through the request file, which exercises every step of the root
# path except the version comparison (that one is unit-tested).
#
# Checks:
#   1. a system install from this checkout's installer, as sudo runs it
#   2. the helper, its units and its staging folder: root's, not the account's
#   3. the agent reports six stamped commits and a system install
#   4. a request naming junk is refused, and what it named is not echoed
#   5. a request that is a symlink to a root-only file reads nothing
#   6. a real update: requested through the app's own route (or the request
#      file), carried out by root, reported back by the agent that comes back,
#      and running exactly the six commits the target pins (with EP_FROM, an
#      earlier specs commit to install first, those can differ)
#   7. what the update wrote into the prefix is the account's, not root's
#   8. teardown: nothing of this run is left
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
PERSON=${EP_PERSON:-${SUDO_USER:-}}
PORT=${EP_PORT:-8179}
WORK=/tmp/ep-updates
ACCOUNT=eugene-plexus
PREFIX=/var/lib/eugene-plexus
UNIT=/etc/systemd/system/eugene-plexus-agent.service
HELPER=/usr/local/lib/eugene-plexus/update
STAGE=/var/lib/eugene-plexus-update
PATH_UNIT=/etc/systemd/system/eugene-plexus-update.path
SERVICE_UNIT=/etc/systemd/system/eugene-plexus-update.service
PASS_PHRASE="updates acceptance $(date +%s) passphrase"

FAILURES=0
ok()  { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
say() { printf '\n== %s\n' "$*"; }
as_account() { runuser -u "$ACCOUNT" -- "$@"; }
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
api() {  # api METHOD PATH [BODY]
    curl -fsS -X "$1" -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
        ${3:+-d "$3"} "http://127.0.0.1:$PORT$2"
}

[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 2; }
[ -d /run/systemd/system ] || { echo "systemd is not running here" >&2; exit 2; }
[ -n "$PERSON" ] || { echo "set EP_PERSON to the account the install is for" >&2; exit 2; }
PERSON_HOME=$(getent passwd "$PERSON" | cut -d: -f6)

if [ -f "$UNIT" ] || getent passwd "$ACCOUNT" >/dev/null || [ -e "$PREFIX" ] || [ -e "$HELPER" ]; then
    echo "this machine already has an Eugene install (or its leftovers); refusing to run" >&2
    exit 2
fi
STARTED=$(date +%s)
MODELS="$PERSON_HOME/Eugene Models"
MADE_MODELS=0
[ -e "$MODELS" ] || MADE_MODELS=1

teardown() {
    say "8. teardown"
    (cd "$WORK" 2>/dev/null && env SUDO_USER="$PERSON" sh ./install.sh --uninstall >/dev/null 2>&1) || true
    systemctl stop eugene-plexus-agent eugene-plexus-update.path >/dev/null 2>&1 || true
    rm -f "$UNIT" "$PATH_UNIT" "$SERVICE_UNIT" "$HELPER"
    rm -rf "$STAGE" "$(dirname "$HELPER")"
    systemctl daemon-reload >/dev/null 2>&1 || true
    getent passwd "$ACCOUNT" >/dev/null && userdel "$ACCOUNT" >/dev/null 2>&1
    rm -rf "$PREFIX"
    for d in "$PREFIX".removed-*; do
        [ -d "$d" ] || continue
        [ "$(stat -c %Y "$d")" -ge "$STARTED" ] && rm -rf "$d"
    done
    [ "$MADE_MODELS" = 1 ] && rm -rf "$MODELS"
    rm -rf "$WORK"
    left=""
    for f in "$UNIT" "$PATH_UNIT" "$SERVICE_UNIT" "$HELPER" "$STAGE" "$PREFIX"; do
        [ -e "$f" ] && left="$left $f"
    done
    [ -z "$left" ] && ok "8. nothing of this run is left" || bad "8. left behind:$left"
    printf '\n%s\n' "$([ "$FAILURES" = 0 ] && echo 'ALL PASS' || echo "$FAILURES FAILED")"
}
trap teardown EXIT

rm -rf "$WORK"; mkdir -p "$WORK"; chmod 0755 "$WORK"
# EP_FROM installs what an earlier specs commit pinned, so the update to
# EP_TARGET changes the version when the two pin different commits. CI
# passes the previous push.
FROM=${EP_FROM:-}
case $FROM in 0000000000000000000000000000000000000000) FROM= ;; esac
if [ -n "$FROM" ]; then
    curl -fsSL "https://raw.githubusercontent.com/eugene-plexus/specs/$FROM/scripts/install.sh" \
        -o "$WORK/install.sh" || { echo "could not fetch the installer at $FROM" >&2; exit 2; }
else
    cp "$HERE/install.sh" "$WORK/install.sh"
fi

say "1. a system install, as sudo runs it${FROM:+ (the installer at $FROM)}"
OUT=$( (cd "$WORK" && env SUDO_USER="$PERSON" EUGENE_PLEXUS_AGENT_BIND_PORT="$PORT" sh ./install.sh) 2>&1 ); RC=$?
if [ "$RC" = 0 ] && printf '%s' "$OUT" | grep -q "Eugene Plexus is running"; then
    ok "1. installed, and the agent answers on $PORT"
else
    bad "1. install rc=$RC: $(printf '%s' "$OUT" | tail -8)"
    exit 1
fi

TOKEN=""
if [ ! -e "$HELPER" ]; then
    # A release from before the updater (alpha.3 and earlier) has no root
    # helper and no update route: its first update is by hand, the same
    # one-line installer run again (docs/design/in-app-updates.md §3).
    # Set up first, so the upgrade has an install with a passphrase to keep.
    say "1b. an install from before the updater: its first update is by hand"
    TOKEN=$(curl -fsS -X POST -H 'content-type: application/json' \
        -d "{\"passphrase\": \"$PASS_PHRASE\"}" "http://127.0.0.1:$PORT/v1/auth/initialize" | json 'd["sessionToken"]')
    cp "$HERE/install.sh" "$WORK/install.sh"
    OUT=$( (cd "$WORK" && env SUDO_USER="$PERSON" EUGENE_PLEXUS_AGENT_BIND_PORT="$PORT" sh ./install.sh) 2>&1 ); RC=$?
    if [ "$RC" = 0 ] && printf '%s' "$OUT" | grep -q "Eugene Plexus is running"; then
        ok "1b. this checkout's installer, run over it, upgraded it in place"
    else
        bad "1b. the by-hand upgrade: rc=$RC: $(printf '%s' "$OUT" | tail -8)"
        exit 1
    fi
    TOKEN=""
    for _ in $(seq 1 30); do
        TOKEN=$(curl -fsS -X POST -H 'content-type: application/json' \
            -d "{\"passphrase\": \"$PASS_PHRASE\"}" "http://127.0.0.1:$PORT/v1/auth/login" 2>/dev/null \
            | json 'd["sessionToken"]' 2>/dev/null) && [ -n "$TOKEN" ] && break
        sleep 2
    done
    [ -n "$TOKEN" ] && ok "1b. and kept the install: the passphrase set before the upgrade signs in" \
        || bad "1b. the passphrase set before the upgrade no longer signs in"
fi

say "2. the helper is root's, and outside the prefix"
got=$(stat -c '%U:%G %a' "$HELPER" 2>/dev/null || echo missing)
[ "$got" = "root:root 755" ] && ok "2a. $HELPER is $got" || bad "2a. $HELPER is $got"
got=$(stat -c '%U %a' "$STAGE" 2>/dev/null || echo missing)
[ "$got" = "root 711" ] && ok "2b. the staging folder is $got" || bad "2b. the staging folder is $got"
if systemctl is-active --quiet eugene-plexus-update.path && systemctl is-enabled --quiet eugene-plexus-update.path; then
    ok "2c. eugene-plexus-update.path is enabled and watching $PREFIX/update/request"
else
    bad "2c. eugene-plexus-update.path: $(systemctl is-active eugene-plexus-update.path) / $(systemctl is-enabled eugene-plexus-update.path)"
fi
if grep -q "$PREFIX" "$HELPER" && ! grep -q "$PREFIX/venv\|\$PREFIX/venv" "$HELPER"; then
    ok "2d. the helper names the prefix and runs nothing from it"
else
    bad "2d. the helper: $(grep -n 'venv' "$HELPER" | head -3)"
fi

say "3. what the agent reports"
[ -n "$TOKEN" ] || TOKEN=$(curl -fsS -X POST -H 'content-type: application/json' \
    -d "{\"passphrase\": \"$PASS_PHRASE\"}" "http://127.0.0.1:$PORT/v1/auth/initialize" | json 'd["sessionToken"]')
NODE=$(api GET /v1/node)
states=$(printf '%s' "$NODE" | json '" ".join(c["state"] for c in d["install"]["components"])')
mechanism=$(printf '%s' "$NODE" | json 'd["install"]["mechanism"]')
agent_commit=$(printf '%s' "$NODE" | json 'next(c.get("commit","") for c in d["install"]["components"] if c["name"]=="agent")')
pinned=$(sed -n 's/^PIN_AGENT=\([0-9a-f]*\).*/\1/p' "$WORK/install.sh")
if [ "$states" = "stamped stamped stamped stamped stamped stamped" ] && [ "$mechanism" = systemd_system ] \
        && [ "$agent_commit" = "$pinned" ]; then
    ok "3. six stamped commits, the agent's is the pin ($pinned), and it is a system install"
else
    bad "3. states '$states', mechanism '$mechanism', agent $agent_commit vs pin $pinned"
fi

wait_record() {  # wait_record SECONDS: until last.json is newer than the mark
    local deadline=$(( $(date +%s) + $1 ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if [ -f "$PREFIX/update/last.json" ] && [ "$PREFIX/update/last.json" -nt "$WORK/mark" ]; then
            return 0
        fi
        sleep 2
    done
    return 1
}

say "4. a request naming junk"
touch "$WORK/mark"; sleep 1
as_account sh -c "printf '%s\n' '../../../etc/passwd; touch /tmp/ep-pwned' > '$PREFIX/update/request'"
if wait_record 60; then
    rec=$(cat "$PREFIX/update/last.json")
    outcome=$(printf '%s' "$rec" | json 'd["outcome"]')
    if [ "$outcome" = failed ] && ! printf '%s' "$rec" | grep -q "passwd" && [ ! -e /tmp/ep-pwned ]; then
        ok "4. refused, and the record does not repeat what it named"
    else
        bad "4. record: $rec"
    fi
else
    bad "4. no record appeared within 60 s"
fi

say "5. a request that is a symlink to a root-only file"
touch "$WORK/mark"; sleep 1
as_account ln -sf /etc/shadow "$PREFIX/update/request"
sleep 8
if [ -L "$PREFIX/update/request" ] || [ -e "$PREFIX/update/request" ]; then
    bad "5. the request is still there"
elif [ -f "$PREFIX/update/last.json" ] && [ "$PREFIX/update/last.json" -nt "$WORK/mark" ] \
        && grep -q 'root:' "$PREFIX/update/last.json"; then
    bad "5. the record carries /etc/shadow"
else
    ok "5. read as the account, so nothing: removed, no record, nothing of /etc/shadow"
fi

say "6. a real update, carried out by root"
CHECK=$(api POST /v1/node/update/check '{}')
newest=$(printf '%s' "$CHECK" | json '(d.get("newest") or {}).get("ref","")')
available=$(printf '%s' "$CHECK" | json 'd["available"]')
possible=$(printf '%s' "$CHECK" | json 'd["apply"]["possible"]')
[ "$possible" = True ] && ok "6a. the agent says it can update itself" || bad "6a. apply: $CHECK"
TARGET=${EP_TARGET:-$newest}
touch "$WORK/mark"; sleep 1
if [ "$available" = True ] && [ "$TARGET" = "$newest" ]; then
    R=$(api POST /v1/node/update "{\"target\": \"$TARGET\"}") \
        && ok "6b. asked through POST /v1/node/update for $TARGET" \
        || bad "6b. POST /v1/node/update: $R"
else
    # Not what this agent found newest (already on it, or a target it
    # cannot know of yet): the same request the route writes, by hand.
    as_account sh -c "printf '%s edge\n' '$TARGET' > '$PREFIX/update/request'"
    ok "6b. asked for $TARGET through the request file, as the route writes it"
fi
if wait_record 600; then
    rec=$(cat "$PREFIX/update/last.json")
    outcome=$(printf '%s' "$rec" | json 'd["outcome"]')
    [ "$outcome" = succeeded ] && ok "6c. root ran the installer: $(printf '%s' "$rec" | json 'd["detail"]')" \
        || bad "6c. $rec"
else
    bad "6c. no record within ten minutes"
fi
for _ in $(seq 1 60); do curl -fsS -o /dev/null "http://127.0.0.1:$PORT/healthz" && break; sleep 2; done
AFTER=$(api GET /v1/node)
last=$(printf '%s' "$AFTER" | json '(d["update"].get("last") or {}).get("outcome","")')
[ "$last" = succeeded ] && ok "6d. the agent that came back reports it" || bad "6d. update: $(printf '%s' "$AFTER" | json 'd["update"]')"
curl -fsSL "https://raw.githubusercontent.com/eugene-plexus/specs/$TARGET/scripts/install.sh" \
    -o "$WORK/target-install.sh" 2>/dev/null || : >"$WORK/target-install.sh"
compare=$(printf '%s' "$AFTER" | python3 -c '
import json, re, sys
pins = dict(re.findall(r"^PIN_([A-Z]+)=([0-9a-f]{40})", open(sys.argv[1]).read(), re.M))
before = dict(re.findall(r"^PIN_([A-Z]+)=([0-9a-f]{40})", open(sys.argv[2]).read(), re.M))
names = {"agent": "AGENT", "control": "CONTROL", "gateway": "GATEWAY",
         "inference-driver": "DRIVER", "library": "LIBRARY", "ui": "UI"}
now = {c["name"]: c.get("commit", "") for c in json.load(sys.stdin)["install"]["components"]}
wrong = ["%s %s not %s" % (n, (now.get(n) or "-")[:7], pins.get(k, "?")[:7])
         for n, k in names.items() if now.get(n) != pins.get(k)]
moved = sum(1 for k in names.values() if pins.get(k) != before.get(k))
print("; ".join(wrong) if wrong else f"ok {moved}")
' "$WORK/target-install.sh" "$WORK/install.sh")
case $compare in
    "ok 0") ok "6e. it runs all six commits $TARGET pins (the same six it had: no version changed)" ;;
    ok\ *)  ok "6e. it runs all six commits $TARGET pins, ${compare#ok } of them new" ;;
    *)      bad "6e. $compare" ;;
esac

say "7. what the update left in the prefix"
bad_owner=$(find "$PREFIX/update" -maxdepth 1 ! -user "$ACCOUNT" -printf '%p ' 2>/dev/null)
[ -z "$bad_owner" ] && ok "7. every file in $PREFIX/update is $ACCOUNT's" || bad "7. not the account's: $bad_owner"
exit 0
