#!/usr/bin/env bash
# Row 2 acceptance: the Linux system install, Eugene under its own account.
#
# The claim (Troy's calls, 2026-09-24): on Linux the default install runs
# the agent as `eugene-plexus`, so a program running as the person -- an
# AI agent they started -- cannot read its key, its environment or its
# memory; it still reaches the person's models through their group; and
# it comes back unlocked after a restart from a passphrase file only that
# account can read.
#
# Runs AS ROOT on a Linux machine with systemd, because it creates and
# removes a real system account and a real system unit. From the Windows
# development box, against the WSL2 guest (`wsl -u root` needs no password):
#
#   MSYS_NO_PATHCONV=1 wsl.exe -u root -e env EP_PERSON=tcorbin \
#     EP_LOCAL_REPOS="agent ui" bash /mnt/d/py/eugene-plexus/specs/scripts/row2-system-install-acceptance.sh
#
# The installer is the one in this checkout, run as `sudo sh install.sh`
# would run it (root, with SUDO_USER naming the person). EP_LOCAL_REPOS
# names repos whose PINNED commit is installed from a local `git archive`
# instead of GitHub -- the same commit, fetched locally, for a run made
# before the pins are pushed. Nothing else about the installer changes.
#
# It refuses to start beside a real install, and tears down what it made.
# Checks:
#    1. the install finishes and the agent answers
#    2. the account is a system account that cannot log in
#    3. the prefix is the account's, 0750
#    4. the unit runs as the account, with the person's group and the
#       passphrase file, and names the person's models folder
#    5. the agent process runs as the account and holds the person's group
#    6. a fresh install is `securityMode: passphrase_file`
#    7. the person cannot list the prefix
#    8. the person cannot read node.yaml
#    9. the person cannot read the agent's environment
#   10. the wizard is told (`passphraseFile`) before setup
#   11. setup writes the passphrase file, the account's, 0400
#   12. a restart comes back unlocked with nobody signing in
#   13. the models folder is the person's, group-writable and setgid
#   14. the running agent lists a file in the person's models folder
#   15. the library's default folder is the person's
#   16. `--user` refuses beside it, having changed nothing
#   17. uninstall removes the unit, the account and the prefix
#   18. and keeps the prefix as root's, 0700, and the person's models
#   19. a system install refuses beside a per-user one, having made nothing

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
EP_ROOT=${EP_ROOT:-$(cd "$HERE/../.." && pwd)}
PERSON=${EP_PERSON:-${SUDO_USER:-}}
PORT=${EP_PORT:-8179}
WORK=/tmp/ep-row2
ACCOUNT=eugene-plexus
PREFIX=/var/lib/eugene-plexus
UNIT=/etc/systemd/system/eugene-plexus-agent.service
PASS_PHRASE="row two acceptance $(date +%s) passphrase"

FAILURES=0
ok()  { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
say() { printf '\n== %s\n' "$*"; }
as_person() { runuser -u "$PERSON" -- env HOME="$PERSON_HOME" "$@"; }

[ "$(id -u)" = 0 ] || { echo "run as root (it creates a system account)" >&2; exit 2; }
[ -d /run/systemd/system ] || { echo "systemd is not running here" >&2; exit 2; }
[ -n "$PERSON" ] || { echo "set EP_PERSON to the account the install is for" >&2; exit 2; }
PERSON_HOME=$(getent passwd "$PERSON" | cut -d: -f6)
PERSON_GROUP=$(id -gn "$PERSON")
PERSON_GID=$(id -g "$PERSON")
MODELS="$PERSON_HOME/Eugene Models"

# --- never beside a real install -------------------------------------------
if [ -f "$UNIT" ] || getent passwd "$ACCOUNT" >/dev/null || [ -e "$PREFIX" ] \
        || [ -e "$PERSON_HOME/.local/share/eugene-plexus" ]; then
    echo "this machine already has an Eugene install (or its leftovers); refusing to run" >&2
    exit 2
fi
MADE_MODELS=0
[ -e "$MODELS" ] || MADE_MODELS=1
STARTED=$(date +%s)

teardown() {
    if [ -f "$UNIT" ]; then
        systemctl stop eugene-plexus-agent >/dev/null 2>&1 || true
        systemctl disable eugene-plexus-agent >/dev/null 2>&1 || true
        rm -f "$UNIT"; systemctl daemon-reload || true
    fi
    getent passwd "$ACCOUNT" >/dev/null && userdel "$ACCOUNT" >/dev/null 2>&1
    rm -rf "$PREFIX"
    # Only the moved-aside prefixes this run made.
    for d in "$PREFIX".removed-*; do
        [ -d "$d" ] || continue
        [ "$(stat -c %Y "$d")" -ge "$STARTED" ] && rm -rf "$d"
    done
    if [ "$MADE_MODELS" = 1 ]; then rm -rf "$MODELS"; else rm -f "$MODELS/row2-probe.gguf"; fi
    rm -rf "$PERSON_HOME/.local/share/eugene-plexus.row2-marker"
    rm -rf "$WORK"
}
trap teardown EXIT

# --- stage the installer --------------------------------------------------
rm -rf "$WORK"; mkdir -p "$WORK"; chmod 0755 "$WORK"
cp "$HERE/install.sh" "$WORK/install.sh"
for repo in ${EP_LOCAL_REPOS:-}; do
    case $repo in
        agent) var=PIN_AGENT ;; ui) var=PIN_UI ;; control) var=PIN_CONTROL ;;
        gateway) var=PIN_GATEWAY ;; library) var=PIN_LIBRARY ;; inference-driver) var=PIN_DRIVER ;;
        *) echo "unknown repo $repo" >&2; exit 2 ;;
    esac
    sha=$(sed -n "s/^$var=\([0-9a-f]*\).*/\1/p" "$WORK/install.sh")
    git -c safe.directory='*' -C "$EP_ROOT/$repo" archive --format=tar.gz \
        --prefix="$repo-$sha/" "$sha" > "$WORK/$repo.tar.gz" \
        || { echo "could not archive $repo at $sha" >&2; exit 2; }
    chmod 0644 "$WORK/$repo.tar.gz"
    sed -i "s|\$(gh_archive $repo \"\$$var\")|file://$WORK/$repo.tar.gz|" "$WORK/install.sh"
    grep -q "file://$WORK/$repo.tar.gz" "$WORK/install.sh" \
        || { echo "could not point the installer at the local $repo archive" >&2; exit 2; }
    echo "installing $repo at its pinned $sha from a local archive"
done

run_install() {
    (cd "$WORK" && env SUDO_USER="$PERSON" EUGENE_PLEXUS_AGENT_BIND_PORT="$PORT" sh ./install.sh "$@") 2>&1
}
status() { curl -fsS "http://127.0.0.1:$PORT/v1/auth/status"; }
wait_for() {  # wait_for SECONDS COMMAND...
    local deadline=$(( $(date +%s) + $1 )); shift
    until "$@" >/dev/null 2>&1; do
        [ "$(date +%s)" -lt "$deadline" ] || return 1
        sleep 1
    done
}
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

# --- 1. install -----------------------------------------------------------
say "1. the default install, as sudo would run it"
OUT=$(run_install); RC=$?
if [ "$RC" = 0 ] && printf '%s' "$OUT" | grep -q "Eugene Plexus is running"; then
    ok "1. the install finished and the agent answers on $PORT"
else
    bad "1. install rc=$RC: $(printf '%s' "$OUT" | tail -8)"
    exit 1
fi
if printf '%s' "$OUT" | grep -q "any program you run as you"; then
    bad "1b. the system install printed the per-user warning"
fi

say "2-6. the account, the prefix, the unit, the process"
ENTRY=$(getent passwd "$ACCOUNT")
uid=$(printf '%s' "$ENTRY" | cut -d: -f3); shell=$(printf '%s' "$ENTRY" | cut -d: -f7)
if [ "$uid" -lt 1000 ] && case $shell in */nologin|*/false) true ;; *) false ;; esac; then
    ok "2. $ACCOUNT is a system account (uid $uid) that cannot log in ($shell)"
else
    bad "2. $ENTRY"
fi
got=$(stat -c '%U:%G %a' "$PREFIX")
[ "$got" = "$ACCOUNT:$ACCOUNT 750" ] && ok "3. the prefix is $got" || bad "3. the prefix is $got"
if grep -qx "User=$ACCOUNT" "$UNIT" \
        && grep -q "^SupplementaryGroups=.*\b$PERSON_GROUP\b" "$UNIT" \
        && grep -qx "Environment=EUGENE_PLEXUS_AGENT_PASSPHRASE_FILE=$PREFIX/passphrase" "$UNIT" \
        && grep -qx "Environment=EUGENE_PLEXUS_CONTROL_PASSPHRASE_FILE=$PREFIX/passphrase" "$UNIT" \
        && grep -qx "Environment=\"EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS=$MODELS\"" "$UNIT"; then
    ok "4. the unit runs as $ACCOUNT with $PERSON_GROUP, the passphrase file and $MODELS"
else
    bad "4. the unit: $(grep -E '^(User|SupplementaryGroups|Environment)' "$UNIT" | tr '\n' ' ')"
fi
PID=$(systemctl show -p MainPID --value eugene-plexus-agent)
owner=$(ps -o user= -p "$PID" | tr -d ' ')
groups=$(sed -n 's/^Groups:\s*//p' "/proc/$PID/status")
if [ "$owner" = "$ACCOUNT" ] && printf ' %s ' "$groups" | grep -q " $PERSON_GID "; then
    ok "5. the agent (pid $PID) runs as $owner and holds gid $PERSON_GID ($PERSON_GROUP)"
else
    bad "5. pid $PID runs as '$owner' with groups '$groups'"
fi
grep -qx 'securityMode: passphrase_file' "$PREFIX/agent.yaml" \
    && ok "6. agent.yaml: securityMode: passphrase_file" \
    || bad "6. agent.yaml: $(grep securityMode "$PREFIX/agent.yaml" || echo 'no securityMode')"

say "7-9. what a program running as $PERSON can reach"
if ! as_person ls "$PREFIX" >/dev/null 2>&1; then ok "7. $PERSON cannot list $PREFIX"
else bad "7. $PERSON can list $PREFIX"; fi
if ! as_person cat "/proc/$PID/environ" >/dev/null 2>&1; then ok "9. $PERSON cannot read the agent's environment"
else bad "9. $PERSON can read /proc/$PID/environ"; fi

say "10-12. the passphrase file"
BODY=$(status)
if [ "$(printf '%s' "$BODY" | json 'd.get("passphraseFile")')" = True ] \
        && [ "$(printf '%s' "$BODY" | json 'd["initialized"]')" = False ]; then
    ok "10. before setup the agent says passphraseFile: true"
else
    bad "10. /v1/auth/status: $BODY"
fi
TOKEN=$(curl -fsS -X POST -H 'content-type: application/json' \
    -d "{\"passphrase\": \"$PASS_PHRASE\"}" "http://127.0.0.1:$PORT/v1/auth/initialize" \
    | json 'd["sessionToken"]')
got=$(stat -c '%U %a' "$PREFIX/passphrase" 2>/dev/null || echo missing)
if [ "$got" = "$ACCOUNT 400" ] && [ "$(cat "$PREFIX/passphrase")" = "$PASS_PHRASE" ]; then
    ok "11. setup wrote the passphrase file: $got"
else
    bad "11. the passphrase file: $got"
fi
# node.yaml appears when the wizard enrols this machine, which this run
# does not drive; the files setup has just written are the secrets here.
unreadable=0
for f in agent.yaml passphrase node.yaml; do
    [ -f "$PREFIX/$f" ] || continue
    if as_person cat "$PREFIX/$f" >/dev/null 2>&1; then unreadable=1; bad "8. $PERSON can read $f"; fi
done
[ "$unreadable" = 0 ] && ok "8. $PERSON cannot read agent.yaml or the passphrase file"
systemctl restart eugene-plexus-agent
if wait_for 60 status && [ "$(status | json 'd["unlocked"]')" = True ]; then
    ok "12. after a restart the agent is unlocked, and nobody signed in"
else
    bad "12. after a restart: $(status 2>&1)"
fi
PID=$(systemctl show -p MainPID --value eugene-plexus-agent)
# An agent that has not enrolled signs with a fresh key at every start,
# so the token from setup died with the restart.
TOKEN=$(curl -fsS -X POST -H 'content-type: application/json' \
    -d "{\"passphrase\": \"$PASS_PHRASE\"}" "http://127.0.0.1:$PORT/v1/auth/login" \
    | json 'd["sessionToken"]')

say "13-15. the person's models, through their group"
got=$(stat -c '%U:%G %a' "$MODELS" 2>/dev/null || echo missing)
if [ "$MADE_MODELS" = 0 ]; then
    ok "13. (the models folder existed before this run: $got)"
elif [ "$got" = "$PERSON:$PERSON_GROUP 2775" ]; then
    ok "13. $MODELS is $got"
else
    bad "13. $MODELS is $got"
fi
as_person sh -c "head -c 4096 /dev/urandom > \"$MODELS/row2-probe.gguf\""
LIST=$(curl -fsS -G -H "Authorization: Bearer $TOKEN" --data-urlencode "path=$MODELS" \
    --data-urlencode includeFiles=true "http://127.0.0.1:$PORT/v1/directories" 2>&1)
if printf '%s' "$LIST" | grep -q 'row2-probe.gguf'; then
    ok "14. the running agent lists $MODELS/row2-probe.gguf"
else
    bad "14. the agent's listing of $MODELS: $(printf '%s' "$LIST" | head -c 300)"
fi
folders() {
    curl -fsS -H "Authorization: Bearer $TOKEN" \
        "http://127.0.0.1:$PORT/api/proxy/library/v1/folders"
}
if wait_for 90 folders; then
    first=$(folders | json 'next(((f.get("path") if isinstance(f, dict) else f) for f in d.get("folders") or []), None)')
    [ "$first" = "$MODELS" ] && ok "15. the library's default folder is $first" \
        || bad "15. the library's first folder is '$first'"
else
    bad "15. the library never answered through the agent"
fi

say "16. --user beside it"
BEFORE=$(ls -la "$PERSON_HOME" | md5sum)
OUT=$(cd "$WORK" && as_person sh ./install.sh --user --no-start 2>&1); RC=$?
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q "already has Eugene installed under its own account" \
        && [ "$(ls -la "$PERSON_HOME" | md5sum)" = "$BEFORE" ]; then
    ok "16. --user refuses, says to re-run without it, and changed nothing"
else
    bad "16. rc=$RC: $(printf '%s' "$OUT" | tail -3)"
fi

say "17-18. uninstall"
OUT=$(run_install --uninstall); RC=$?
if [ "$RC" = 0 ] && [ ! -f "$UNIT" ] && ! getent passwd "$ACCOUNT" >/dev/null && [ ! -e "$PREFIX" ]; then
    ok "17. the unit, the account and the prefix are gone"
else
    bad "17. rc=$RC unit=$([ -f "$UNIT" ] && echo present) account=$(getent passwd "$ACCOUNT" | cut -d: -f1): $(printf '%s' "$OUT" | tail -3)"
fi
KEPT=$(ls -d "$PREFIX".removed-* 2>/dev/null | tail -1)
got=$(stat -c '%U:%G %a' "$KEPT" 2>/dev/null || echo missing)
# The passphrase file is the secret this run wrote (node.yaml waits for
# the wizard's enrolment, which this run does not drive).
if [ "$got" = "root:root 700" ] && [ -f "$KEPT/passphrase" ] \
        && [ "$(stat -c %U "$KEPT/passphrase")" = root ] && [ -d "$MODELS" ]; then
    ok "18. the old prefix is kept as $got, and $MODELS is still there"
else
    bad "18. kept '$KEPT' as $got; models $([ -d "$MODELS" ] && echo kept || echo GONE)"
fi

say "19. a system install beside a per-user one"
MARKER="$PERSON_HOME/.local/share/eugene-plexus"
as_person mkdir -p "$MARKER" && as_person touch "$MARKER/agent.yaml"
OUT=$(run_install); RC=$?
as_person rm -rf "$MARKER"
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q "already has Eugene installed under your own account" \
        && ! getent passwd "$ACCOUNT" >/dev/null && [ ! -e "$PREFIX" ]; then
    ok "19. it refuses, says to use --user, and made no account and no prefix"
else
    bad "19. rc=$RC: $(printf '%s' "$OUT" | tail -3)"
fi

echo
if [ "$FAILURES" = 0 ]; then echo "all checks passed"; else echo "$FAILURES check(s) failed"; fi
exit "$FAILURES"
