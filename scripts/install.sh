#!/bin/sh
# Eugene Plexus — one-command install for Linux and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/eugene-plexus/specs/main/scripts/install.sh | sh
#
# With options (sh cannot take arguments from a pipe without -s):
#
#   curl -fsSL .../install.sh | sh -s -- --user
#   curl -fsSL .../install.sh | sh -s -- --uninstall
#
# **On Linux, Eugene runs under its own account by default** (2026-09-24).
# The install's signing key sits in a file on disk, and anything running
# as the account the agent runs as -- an AI agent you started, say -- can
# read that file, the agent's environment and its memory. No file
# permission stops a program running as the same account; a different
# account does. So the default is a system service running as
# `eugene-plexus`, in /var/lib/eugene-plexus, and this script asks for
# sudo once to set that up. `--user` keeps the old layout: everything
# under your home, running as you, no sudo -- and anything you run can
# control Eugene. macOS always gets the per-user layout for now.
#
# What it does, in the order it does it, so that reading this comment is
# a substitute for reading the script (install-paths §11: `curl | sh`
# has to stay auditable):
#
#   0. (Linux, default) creates the `eugene-plexus` account and its
#      prefix, with sudo; the steps below then run AS that account, so
#      no package's build step ever runs as root,
#   1. fetches `uv` into the install prefix and nowhere else -- and fetches
#      it again over one older than UV_MINIMUM,
#   2. makes a virtualenv there with a Python `uv` downloads itself,
#   3. installs the seven Eugene Plexus packages into it,
#   4. checks that what landed can actually serve — see VERIFY below,
#   5. writes a systemd unit (Linux: a system unit, or a user unit with
#      --user) or launchd agent (macOS),
#   6. starts it and waits for the agent to answer.
#
# It touches nothing outside `$PREFIX` except the service file, the
# account, and (by default) a `Eugene Models` folder in your home, and
# `--uninstall` removes the first three. Only the default Linux layout
# needs root.
#
# WHERE THE PACKAGES COME FROM. GitHub source archives at pinned
# commits — the same mechanism `SPECS_REF` has used in every consumer
# since M0, which needs no package registry and no release. Nothing is
# published to PyPI yet, deliberately: the release comes after tool
# calling. At release time the PINS block below becomes one line,
# `eugene-plexus`, and the rest of this script is unchanged.
#
# THE UI IS PINNED TO A `dist` BRANCH, AND THAT IS NOT AN OVERSIGHT.
# `eugene-plexus-ui` is a wheel wrapping a Next.js static export, and
# that export is `next build` output, gitignored on `main`. Installing
# from a `main` archive therefore *succeeds* and produces a package with
# no UI inside it — verified 2026-09-11, `static_dir()` was not even a
# directory. The `dist` branch carries the built export so that all seven
# packages install by one mechanism. See install-paths §12, step 3.

set -eu

# --- pins -------------------------------------------------------------
# Generated from release/manifest.json by scripts/release-inputs.py.
PIN_AGENT=af6c3714067055308e3a56a3d20a85ecba9452fc
PIN_CONTROL=de4c6190ac2259330d3c7bab0698efa31cfbb401
PIN_GATEWAY=d9e2226c959d455dcd2a8d80ee6fe2dd19d0f53f
PIN_DRIVER=2b1850b88434f708f14566d1bdbf611cd109bb7e
PIN_LIBRARY=1be1803c5f7cbecfaef1dbc6068fa2d6856c0730
PIN_TOOL_DRIVER=b30adf8e9de4333c41c6c7816e61fe85969a7421
PIN_UI=ac6f816f410921d6bc4a9e39bc638830f598d7f9   # branch `dist`, not `main`

# The job-site host (Linux system installs only; root installs and runs it,
# see "a job site on a Linux system install" below). Not in the generated
# block above: it is not one of the seven packages in the agent's prefix. It
# must equal SITE_HOST_COMMIT in agent/src/eugene_plexus_agent/site_host.py,
# and it moves at landing, with the agent's pin.
PIN_SITE_HOST=26a4f0f292068a78251367a26066e2dec7db80e6

PY_VERSION=3.12
# **The oldest uv this installer keeps** (2026-10-03). An install keeps the
# uv it was first made with until something replaces it, and the app's own
# updates re-run this script, so this is where an old one is replaced
# (step 1). 0.12.18 fixes GHSA-2cv4-cqwr-gwf7, a path traversal while
# unpacking a wheel in uv 0.12.7 to 0.12.17. That defect is Windows-only;
# the number is kept equal to install.ps1's $UvMinimum so that both
# installers promise the same uv.
UV_MINIMUM=0.12.18
SERVICE_LABEL=eugene-plexus-agent
LAUNCHD_LABEL=com.eugeneplexus.agent

SYSTEM_ACCOUNT=eugene-plexus
SYSTEM_PREFIX=/var/lib/eugene-plexus
USER_PREFIX=$HOME/.local/share/eugene-plexus

PREFIX=${EUGENE_PLEXUS_HOME:-}
USER_MODE=0
DO_SERVICE=1
DO_UNINSTALL=0
DO_START=1
JOIN_CONTROL=
JOIN_TOKEN=
JOIN_NAME=
JOIN_ADVERTISE=
JOIN_SITE=0
JOIN_OWNER=
JOIN_ROOT_KEY=
SITE_ACTION=
SITE_PERSON=
SITE_LINK_ACCOUNT=
SITE_PASSKEY=
PASSWORD_STDIN=0
TTY_SAVED=
JOINED=0
DO_PURGE_COPIES=0
DO_PURGE_DATA=0
DO_INTERACTIVE=0
ADVERTISED=0
UPDATE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=$2; shift 2 ;;
        --prefix=*) PREFIX=${1#--prefix=}; shift ;;
        --user) USER_MODE=1; shift ;;
        --no-service) DO_SERVICE=0; shift ;;
        --no-start) DO_START=0; shift ;;
        --uninstall) DO_UNINSTALL=1; shift ;;
        --purge-data) DO_PURGE_DATA=1; shift ;;
        --interactive) DO_INTERACTIVE=1; shift ;;
        --purge-downloads|--purge-model-copies) DO_PURGE_COPIES=1; shift ;;
        --join) JOIN_CONTROL=$2; shift 2 ;;
        --token) JOIN_TOKEN=$2; shift 2 ;;
        --name) JOIN_NAME=$2; shift 2 ;;
        --advertise) JOIN_ADVERTISE=$2; shift 2 ;;
        --job-site) JOIN_SITE=1; shift ;;
        --owner) JOIN_OWNER=$2; shift 2 ;;
        --root-key) JOIN_ROOT_KEY=$2; shift 2 ;;
        --site-account|--account) SITE_LINK_ACCOUNT=$2; shift 2 ;;
        --site-link) SITE_ACTION=link; shift ;;
        --site-unlink) SITE_ACTION=unlink; shift ;;
        --site-pair) SITE_ACTION=pair; shift ;;
        --site-passkeys) SITE_ACTION=passkeys; shift ;;
        --site-unpair) SITE_ACTION=unpair; SITE_PASSKEY=$2; shift 2 ;;
        --person) SITE_PERSON=$2; shift 2 ;;
        --password-stdin) PASSWORD_STDIN=1; shift ;;
        --update) UPDATE=1; shift ;;
        -h|--help)
            sed -n '2,52p' "$0" 2>/dev/null || true
            echo "options: --user  --prefix DIR  --no-service  --no-start  --uninstall"
            echo "           --user  (Linux: install under your own account, no sudo; anything"
            echo "                   you run can then control Eugene)"
            echo "           --purge-downloads  (with --uninstall: delete this install's model"
            echo "                              copies and engine builds)"
            echo "           --purge-data  (Mac/user install: delete settings, app data and logs)"
            echo "           --interactive  (Mac: show the removal choices)"
            echo "  worker node: --join URL --token JWT [--name NAME] [--advertise URL]"
            echo "  job site (on a node): --join URL --token TOKEN --job-site --owner NAME [--root-key KEY] [--name NAME]"
            echo "                        [--site-account USER] [--password-stdin]"
            echo "  link a person to their account on a job site (Linux system install, as root):"
            echo "           --site-link --person NAME [--site-account USER] [--password-stdin]"
            echo "           --site-unlink --person NAME"
            echo "  the owner's passkey from Workbench (Linux system install, as root):"
            echo "           --site-pair  (shows a code to type into Workbench, and waits)"
            echo "           --site-passkeys   --site-unpair ID"
            echo "  standalone:  --advertise URL   (the address other devices reach this one at)"
            exit 0 ;;
        *) echo "install.sh: unknown option $1" >&2; exit 2 ;;
    esac
done

if [ "$DO_UNINSTALL" != 1 ] && { [ "$DO_PURGE_COPIES" = 1 ] || [ "$DO_PURGE_DATA" = 1 ] || [ "$DO_INTERACTIVE" = 1 ]; }; then
    echo 'Removal options require --uninstall. Nothing was installed or removed.' >&2
    exit 2
fi

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# **Every network step said nothing about why it failed** (review §6.2
# #24). `uv venv` and `uv pip install` both ran under `>/dev/null 2>&1`,
# so a TLS-intercepting corporate proxy -- the commonest reason either
# fails on a machine that is otherwise fine -- read as *could not create
# a virtualenv*, which sends a person to look at a directory. The output
# still does not scroll past on a good install: it goes to a file, and
# only a failure prints it.
STEP_LOG=
run_step() {
    _what=$1; shift
    if [ -z "$STEP_LOG" ]; then
        # On a system install the prefix belongs to Eugene's account and
        # this shell cannot write into it, so the log starts in /tmp and
        # stays there -- the path is printed on failure either way.
        if [ "$MODE" = system ]; then
            STEP_LOG=$(mktemp "${TMPDIR:-/tmp}/eugene-plexus-install.XXXXXX")
        else
            STEP_LOG=$PREFIX/logs/install.log
            mkdir -p "$PREFIX/logs"
            : > "$STEP_LOG"
        fi
    fi
    printf '\n### %s\n' "$_what" >> "$STEP_LOG"
    if "$@" >> "$STEP_LOG" 2>&1; then
        return 0
    else
        # An if with no branch taken returns zero. Capture the command's
        # failure here, before fi can turn an incomplete install into success.
        _rc=$?
    fi
    printf '\033[31merror:\033[0m %s\n' "$_what" >&2
    printf 'The command that failed:\n  %s\n' "$*" >&2
    printf 'What it said (full log: %s):\n' "$STEP_LOG" >&2
    tail -n 20 "$STEP_LOG" | sed 's/^/  /' >&2
    exit "$_rc"
}

# --- platform ---------------------------------------------------------
OS=$(uname -s)
ARCH=$(uname -m)
case "$OS" in
    Linux)  PLATFORM=linux ;;
    Darwin) PLATFORM=macos ;;
    *) die "unsupported operating system: $OS (this installer covers Linux and macOS; Windows uses install.ps1)" ;;
esac
case "$ARCH" in
    x86_64|amd64|aarch64|arm64) : ;;
    *) die "unsupported architecture: $ARCH (uv publishes x86_64 and arm64 builds)" ;;
esac

# uname describes the calling process under Rosetta. Ask the hardware too,
# then qualify uv's request so an Intel uv (or cached Python) cannot choose
# an Intel interpreter for an Apple Silicon install.
PY_REQUEST=$PY_VERSION
NATIVE_APPLE=0
if [ "$PLATFORM" = macos ]; then
    case "$ARCH" in
        arm64|aarch64) NATIVE_APPLE=1 ;;
        *) [ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" != 1 ] || NATIVE_APPLE=1 ;;
    esac
    if [ "$NATIVE_APPLE" = 1 ]; then
        PY_REQUEST=cpython-$PY_VERSION-macos-aarch64-none
        say "Apple Silicon detected; selecting native arm64 Python (also from a Rosetta terminal)"
    fi
fi

# --- which layout -----------------------------------------------------
# **system**: Linux with a service, the default. The agent runs as its
# own account, so a program running as the person cannot read its key,
# its environment or its memory. It reaches the person's model folders
# through their group (Troy's call, 2026-09-24): the unit adds the
# person's primary group, which is what a 0750 home lets in. It has no
# desktop session and so no keyring, so it unlocks from a passphrase file
# only it can read (`securityMode: passphrase_file`).
#
# **user**: `--user`, `--no-service` (nothing to run under an account --
# the container build and anyone starting the agent by hand), and macOS,
# where a LaunchDaemon under its own account needs a Mac this project
# does not have to test its GPU and file access on.
if [ "$PLATFORM" = macos ] || [ "$USER_MODE" = 1 ] || [ "$DO_SERVICE" = 0 ]; then
    MODE=user
else
    MODE=system
fi
if [ -z "$PREFIX" ]; then
    if [ "$MODE" = system ]; then PREFIX=$SYSTEM_PREFIX; else PREFIX=$USER_PREFIX; fi
fi
VENV=$PREFIX/venv
PYBIN=$VENV/bin/python
UV=$PREFIX/bin/uv
CONFIG=$PREFIX/agent.yaml

# The person this install is for: whoever ran it, or whoever ran sudo.
# Nobody, when a root shell runs it directly -- then there is no group to
# join and no home to offer a models folder in.
if [ "$(id -u)" = 0 ]; then PERSON=${SUDO_USER:-}; else PERSON=$(id -un); fi
[ "$PERSON" != root ] || PERSON=
PERSON_HOME=
PERSON_GROUP=
if [ -n "$PERSON" ]; then
    PERSON_HOME=$(getent passwd "$PERSON" 2>/dev/null | cut -d: -f6 || true)
    [ -n "$PERSON_HOME" ] || PERSON_HOME=$HOME
    PERSON_GROUP=$(id -gn "$PERSON")
fi

# Run as root: directly when this is root, through sudo when not.
as_root() {
    if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi
}

# Run as Eugene's account. sudo and runuser both start from a clean
# environment, so the variables the steps below depend on are handed over
# by name -- including a proxy, since uv and pip go to the network and a
# TLS-intercepting proxy is the commonest reason they fail (review §6.2
# #24). `${VAR:+"VAR=$VAR"}` expands to nothing at all when VAR is unset.
as_service() {
    set -- env HOME="$PREFIX" \
        UV_PYTHON_INSTALL_DIR="$PREFIX/pythons" UV_CACHE_DIR="$PREFIX/.cache/uv" \
        ${HTTPS_PROXY:+"HTTPS_PROXY=$HTTPS_PROXY"} ${https_proxy:+"https_proxy=$https_proxy"} \
        ${HTTP_PROXY:+"HTTP_PROXY=$HTTP_PROXY"} ${http_proxy:+"http_proxy=$http_proxy"} \
        ${NO_PROXY:+"NO_PROXY=$NO_PROXY"} ${no_proxy:+"no_proxy=$no_proxy"} \
        ${SSL_CERT_FILE:+"SSL_CERT_FILE=$SSL_CERT_FILE"} "$@"
    # **From `/`, not from wherever this was started** (found 2026-09-26).
    # Eugene's account cannot read the directory a person runs this from
    # when it is root's home or a 0700 one (Fedora's default), and uv reads
    # `uv.toml` from the working directory upwards: "failed to open file
    # `/root/uv.toml`: Permission denied", and the install stopped there.
    if [ "$(id -u)" = 0 ] && command -v runuser >/dev/null 2>&1; then
        (cd / && runuser -u "$SYSTEM_ACCOUNT" -- "$@")
    else
        (cd / && sudo -u "$SYSTEM_ACCOUNT" -- "$@")
    fi
}

# Anything that reads or writes under the prefix: as Eugene's account on
# a system install, whose prefix this shell cannot even look into, and
# as this shell otherwise.
in_prefix() {
    if [ "$MODE" = system ]; then as_service "$@"; else "$@"; fi
}

# The version the prefix's uv says it is -- its words are
# `uv 0.12.22 (x86_64-unknown-linux-gnu)` -- as three numbers, or nothing
# for a uv that is not there or cannot say what it is.
uv_version() {
    in_prefix "$UV" --version 2>/dev/null |
        sed -n 's/^uv \([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n 1
}

# version_older A B: true when dotted version A comes before B. Number by
# number, because as text 0.12.9 sorts after 0.12.18, and 0.9.30 after
# 0.12.18 -- both older, both read as newer by a comparison of strings.
version_older() {
    awk -v a="$1" -v b="$2" 'BEGIN {
        n = split(a, x, "."); m = split(b, y, ".")
        if (m > n) n = m
        for (i = 1; i <= n; i++) {
            if (x[i] + 0 < y[i] + 0) exit 0
            if (x[i] + 0 > y[i] + 0) exit 1
        }
        exit 1
    }'
}

# --- --update ---------------------------------------------------------
# **How the app updates an install** (2026-09-27). The agent asks for it
# -- a system install through the root unit below, a per-user one through
# a transient user unit -- and this run replaces the packages with the
# ones this script pins and restarts Eugene. Everything else about the
# install stays exactly as it was written: its unit, its models folder,
# who it runs as. Refused for anything that is not already an install, so
# an update can never be the thing that makes a second one.
if [ "$UPDATE" = 1 ]; then
    if [ -n "$JOIN_CONTROL" ] || [ "$DO_UNINSTALL" = 1 ]; then
        die "--update upgrades the install at $PREFIX; it cannot be combined with --join or --uninstall"
    fi
    if ! in_prefix test -x "$PYBIN" || ! in_prefix test -f "$CONFIG"; then
        die "--update found no install at $PREFIX to update"
    fi
fi

# --- the root unit a system install updates through ---------------------
# **Root never runs anything from the prefix**: Eugene's account owns it,
# so it could put code there and have root run it. The agent writes one
# thing, a request naming a specs commit or a release tag. This root-owned
# helper, outside the prefix, reads that request AS the account, checks
# its shape, downloads our installer for it into a folder only root can
# write, checks it against the release's checksums when there are any,
# runs it, and hands the account a record to copy back -- so nothing it
# writes lands through a path the account could have pointed elsewhere.
UPDATE_HELPER=/usr/local/lib/eugene-plexus/update
UPDATE_STAGE=/var/lib/eugene-plexus-update
UPDATE_SERVICE=/etc/systemd/system/eugene-plexus-update.service
UPDATE_PATH=/etc/systemd/system/eugene-plexus-update.path

write_update_helper() {
    as_root install -d -m 0755 "$(dirname "$UPDATE_HELPER")"
    as_root install -d -m 0711 "$UPDATE_STAGE"
    in_prefix mkdir -p "$PREFIX/update"
    {
        printf '#!/bin/sh\n'
        printf "PREFIX='%s'\n" "$PREFIX"
        printf "ACCOUNT='%s'\n" "$SYSTEM_ACCOUNT"
        printf "STAGE='%s'\n" "$UPDATE_STAGE"
        cat <<'HELPER'
# Installed by Eugene Plexus's install.sh; see "the root unit a system
# install updates through" there. Run as root by eugene-plexus-update.service.
set -u
# systemd gives a unit with no User= no HOME, and the installer reads it.
HOME=$(getent passwd root | cut -d: -f6)
export HOME=${HOME:-/root}
DIR=$PREFIX/update
REPO=https://github.com/eugene-plexus/specs
RAW=https://raw.githubusercontent.com/eugene-plexus/specs
as_account() { (cd / && runuser -u "$ACCOUNT" -- "$@"); }

# Read and remove the request as Eugene's account: a path it controls
# could point anywhere root can read.
LINE=$(as_account head -c 200 "$DIR/request" 2>/dev/null | head -n 1)
as_account rm -f "$DIR/request"
[ -n "$LINE" ] || exit 0
REF=${LINE%% *}

STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
WORK=$(mktemp -d "$STAGE/run.XXXXXX") || exit 1
chmod 0711 "$WORK"
trap 'rm -rf "$WORK"' EXIT
LOG=$WORK/update.log
: >"$LOG"

esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr -d '\000-\037'; }
finish() {
    {
        printf '{"target":"%s","startedAt":"%s",' "$(esc "$REF")" "$STARTED"
        printf '"finishedAt":"%s","outcome":"%s",' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"
        printf '"detail":"%s","log":"%s"}' "$(esc "$2")" "$DIR/update.log"
    } >"$WORK/last.json"
    chmod 0644 "$WORK/last.json" "$LOG"
    # Copied in by the account, never written by root through its paths.
    as_account cp -f "$LOG" "$DIR/update.log"
    as_account cp -f "$WORK/last.json" "$DIR/last.json.tmp" \
        && as_account mv -f "$DIR/last.json.tmp" "$DIR/last.json"
    as_account rm -f "$DIR/running.json"
}

if printf '%s' "$REF" | grep -Eq '^[0-9a-f]{40}$'; then
    URL=$RAW/$REF/scripts/install.sh
    SUMS=
elif printf '%s' "$REF" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$'; then
    URL=$REPO/releases/download/$REF/install.sh
    SUMS=$REPO/releases/download/$REF/SHA256SUMS
else
    # Never echoed back: it came from a file root does not own.
    REF=unrecognised
    finish failed "The update request did not name a specs commit or a release tag, so nothing was installed."
    exit 1
fi
if ! curl -fsSL "$URL" -o "$WORK/install.sh" 2>>"$LOG"; then
    finish failed "Could not download $URL."
    exit 1
fi
if [ -n "$SUMS" ]; then
    if ! curl -fsSL "$SUMS" -o "$WORK/SHA256SUMS" 2>>"$LOG" \
        || ! (cd "$WORK" && grep ' install.sh$' SHA256SUMS | sha256sum -c - >>"$LOG" 2>&1); then
        finish failed "The installer for $REF did not match the checksum its release published, so it was not run."
        exit 1
    fi
fi
sh "$WORK/install.sh" --update >>"$LOG" 2>&1
CODE=$?
if [ "$CODE" = 0 ]; then
    finish succeeded "Installed $REF."
else
    # Whatever the installer left behind, bring the agent back.
    systemctl start eugene-plexus-agent >/dev/null 2>&1 || true
    finish failed "The installer exited with $CODE. Its last lines: $(tail -n 12 "$LOG" | tr '\n' '|')"
fi
HELPER
    } | as_root tee "$UPDATE_HELPER.new" >/dev/null
    as_root chown root:root "$UPDATE_HELPER.new"
    as_root chmod 0755 "$UPDATE_HELPER.new"
    # Renamed into place, never rewritten: an update runs this function
    # from inside the helper it replaces, and sh reads a script as it goes,
    # so truncating the running file would hand it the new text mid-line.
    as_root mv -f "$UPDATE_HELPER.new" "$UPDATE_HELPER"
    as_root tee "$UPDATE_SERVICE" >/dev/null <<EOF
[Unit]
Description=Eugene Plexus update, asked for by the agent

[Service]
Type=oneshot
ExecStart=$UPDATE_HELPER
TimeoutStartSec=1800
EOF
    as_root tee "$UPDATE_PATH" >/dev/null <<EOF
[Unit]
Description=Eugene Plexus update requests

[Path]
PathExists=$PREFIX/update/request
Unit=eugene-plexus-update.service

[Install]
WantedBy=multi-user.target
EOF
    as_root systemctl daemon-reload
    as_root systemctl enable --now eugene-plexus-update.path >/dev/null 2>&1 \
        || warn "could not enable eugene-plexus-update.path, so this install cannot update itself from the app"
}

# --- apps in accounts of their own (C1) -------------------------------
# An app the agent installs runs as a systemd dynamic user, never as
# eugene-plexus: in that account it could read node.yaml, agent.yaml, the
# passphrase file and every other app's key (measured on a runner,
# docs/design/workbench.md §1). The template unit below runs one app per
# instance in a namespace where this prefix is an empty, read-only tmpfs
# with only the app interpreters, the launcher and the app's own folder
# bound back in; its key and admin token arrive as credentials, which
# systemd reads as root, so they stay 0600 to eugene-plexus on disk.
#
# The agent cannot start a system unit itself: it is unprivileged and its
# unit sets NoNewPrivileges, which rules out sudo. It writes a request into
# $PREFIX/apps/ctl and this root helper, triggered by a path unit, carries
# it out -- the shape the in-app updater uses. The helper reads and writes
# that folder only as eugene-plexus, and takes nothing but start, stop,
# restart or clean, of an eugene-plexus-app@ unit, for an id the registry
# could have issued.
APPS_HELPER=/usr/local/lib/eugene-plexus/apps-ctl
APPS_TEMPLATE=/etc/systemd/system/eugene-plexus-app@.service
APPS_CTL_SERVICE=/etc/systemd/system/eugene-plexus-apps-ctl.service
APPS_CTL_PATH=/etc/systemd/system/eugene-plexus-apps-ctl.path

write_app_units() {
    as_root install -d -m 0755 "$(dirname "$APPS_HELPER")"
    in_prefix mkdir -p "$PREFIX/apps/ctl"
    {
        printf '#!/bin/sh\n'
        printf "DIR='%s'\n" "$PREFIX/apps/ctl"
        printf "ACCOUNT='%s'\n" "$SYSTEM_ACCOUNT"
        cat <<'HELPER'
# Installed by Eugene Plexus's install.sh; see "apps in accounts of their
# own" there. Run as root by eugene-plexus-apps-ctl.service.
set -u
as_account() { (cd / && runuser -u "$ACCOUNT" -- "$@"); }
esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr -d '\000-\037'; }
# Listed, read and removed as Eugene's account: a path it controls could
# point anywhere root can read. Listed again until none is left, so a
# request written while this runs is answered by this run.
while :; do
NAMES=$(as_account find "$DIR" -maxdepth 1 -type f -name '*.req' -printf '%f\n' 2>/dev/null)
[ -n "$NAMES" ] || break
for NAME in $NAMES; do
    ID=${NAME%.req}
    case "$ID" in ''|*[!0-9a-f]*) as_account rm -f "$DIR/$NAME"; continue ;; esac
    LINE=$(as_account head -c 100 "$DIR/$NAME" 2>/dev/null | head -n 1)
    as_account rm -f "$DIR/$NAME"
    VERB=${LINE%% *}
    APP=${LINE#* }
    case "$VERB" in start|stop|restart|clean) ;; *) VERB= ;; esac
    printf '%s' "$APP" | grep -Eq '^[a-z][a-z0-9-]{1,39}$' || VERB=
    if [ -z "$VERB" ]; then
        CODE=2
        OUT="refused: this helper starts, stops, restarts or cleans one eugene-plexus-app@ unit"
    elif [ "$VERB" = clean ]; then
        OUT=$(systemctl clean --what=state "eugene-plexus-app@$APP.service" 2>&1)
        CODE=$?
    else
        # A dynamic user per app, never one shared by every instance of the
        # template (which systemd names after the template: C1's first run
        # put two apps in one uid, able to see each other's processes).
        # systemd takes names of 31 characters at most and an id may be 40,
        # so the name is a hash of the id.
        DROPIN=/etc/systemd/system/eugene-plexus-app@$APP.service.d
        WANT="[Service]
User=eapp-$(printf '%s' "$APP" | sha256sum | cut -c1-12)"
        if [ "$(cat "$DROPIN/10-user.conf" 2>/dev/null)" != "$WANT" ]; then
            mkdir -p "$DROPIN" && printf '%s\n' "$WANT" >"$DROPIN/10-user.conf" \
                && systemctl daemon-reload
        fi
        OUT=$(systemctl "$VERB" "eugene-plexus-app@$APP.service" 2>&1)
        CODE=$?
    fi
    printf '{"code":%s,"output":"%s"}' "$CODE" "$(esc "$OUT")" \
        | as_account tee "$DIR/.$ID.res" >/dev/null
    as_account mv -f "$DIR/.$ID.res" "$DIR/$ID.res"
done
done
HELPER
    } | as_root tee "$APPS_HELPER.new" >/dev/null
    as_root chown root:root "$APPS_HELPER.new"
    as_root chmod 0755 "$APPS_HELPER.new"
    as_root mv -f "$APPS_HELPER.new" "$APPS_HELPER"
    as_root tee "$APPS_TEMPLATE" >/dev/null <<EOF
[Unit]
Description=Eugene Plexus app %i, in an account of its own
Documentation=https://github.com/eugene-plexus/specs/blob/main/docs/design/workbench.md
After=network-online.target $SERVICE_LABEL.service
Wants=network-online.target

[Service]
Type=exec
# A user made for this unit, never eugene-plexus. DynamicUser also makes
# the system read-only to it and gives it a private /tmp.
DynamicUser=yes
StateDirectory=eugene-plexus-apps/%i
ProtectHome=yes
# This prefix as the app sees it: empty and read-only, with the app
# interpreters, the launcher and the app's own folder put back.
TemporaryFileSystem=$PREFIX:ro
BindReadOnlyPaths=-$PREFIX/apps/pythons $PREFIX/apps/launcher $PREFIX/apps/%i
LoadCredential=client_key:$PREFIX/apps/%i/data/client_key
LoadCredential=admin_token:$PREFIX/apps/%i/admin_token
# Its sign-in secret (C2); empty for an app that signs nobody in.
LoadCredential=oidc_secret:$PREFIX/apps/%i/data/oidc_secret
ExecStart=$PREFIX/apps/%i/python -I -u $PREFIX/apps/launcher/app_launcher.py $PREFIX/apps/%i/launch.json
Restart=on-failure
RestartSec=5
# The launcher stops the app itself; anything left is killed with the cgroup.
KillMode=mixed
TimeoutStopSec=45
EOF
    as_root tee "$APPS_CTL_SERVICE" >/dev/null <<EOF
[Unit]
Description=Eugene Plexus apps: start and stop, asked for by the agent
# Every start, stop and restart of every app is one run of this: systemd's
# default of five runs in ten seconds would refuse a boot with several apps,
# and a refused run leaves the path unit that triggers it failed.
StartLimitIntervalSec=0

[Service]
Type=oneshot
ExecStart=$APPS_HELPER
EOF
    as_root tee "$APPS_CTL_PATH" >/dev/null <<EOF
[Unit]
Description=Eugene Plexus app requests

[Path]
PathExistsGlob=$PREFIX/apps/ctl/*.req
Unit=eugene-plexus-apps-ctl.service

[Install]
WantedBy=multi-user.target
EOF
    as_root systemctl daemon-reload
    as_root systemctl enable --now eugene-plexus-apps-ctl.path >/dev/null 2>&1 \
        || warn "could not enable eugene-plexus-apps-ctl.path, so apps will run as eugene-plexus"
}

# --- a job site on a Linux system install (2b.2) -----------------------------
# **Root installs, owns and runs the job-site host and every person's
# worker** (job-sites-own-enrollment.md §2.4, §3.2; in-app-updates.md, "the
# root helper follows one rule"). The agent runs as eugene-plexus, and a
# worker runs as a *person*: whoever can write the program a person's worker
# runs can become that person. So nothing under $PREFIX is ever executed as
# root here, and nothing the agent's account can write is ever written
# through. The program lives in /usr/local/lib/eugene-plexus/site-host
# (root:root, nothing group- or world-writable), with its own uv and its
# own Python, fetched and installed by root. The site's state is in the
# home of an account of its own, eugene-plexus-site, which opens no one's
# files. The links (who is which account) and the local-server list are
# root's, in /etc/eugene-plexus/site; a link is made only by root, at the
# machine, after the person has proved who they are (J36).
SITE_SVC_ACCOUNT=eugene-plexus-site
SITE_SVC_HOME=/var/lib/eugene-plexus-site
SITE_ROOT=/usr/local/lib/eugene-plexus/site-host
SITE_PY=$SITE_ROOT/venv/bin/python
SITE_CONF=/etc/eugene-plexus/site
SITE_CACHE=/var/cache/eugene-plexus-site
SITE_WORKERS=/usr/local/lib/eugene-plexus/site-workers
SITE_HOST_UNIT=/etc/systemd/system/eugene-plexus-site-host.service
SITE_WORKER_UNIT=/etc/systemd/system/eugene-plexus-site-worker@.service
SITE_WORKERS_UNIT=/etc/systemd/system/eugene-plexus-site-workers.service
SITE_WORKERS_PATH=/etc/systemd/system/eugene-plexus-site-workers.path
SITE_DEFAULT_PORT=8300
SITE_PW=
SITE_UID=
SITE_UNAME=
SITE_PORT=

# What the link program does, as one program so that every way of changing
# the links follows the same rules: one link per person and one person per
# account, an account that is a real person's (uid 1000 or more), and the
# file replaced whole (a temporary file in the same folder, then a rename)
# so a reader never sees half of one. No apostrophes in it: it sits in
# single quotes.
SITE_LINK_PY='
import json, os, sys, tempfile, time

mode, path = sys.argv[1], sys.argv[2]


def fail(message):
    sys.stderr.write("error: " + message + "\n")
    sys.exit(1)


def load():
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        fail("the links file " + path + " could not be read, so nothing was changed")
    links = data.get("links") if isinstance(data, dict) else None
    if not isinstance(links, list) or not all(isinstance(x, dict) for x in links):
        fail("the links file " + path + " is not a links file, so nothing was changed")
    return links


def save(links):
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".links-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "links": links}, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def text(value):
    return value if isinstance(value, str) and value.strip() else None


def add(subject, name, uid, uname):
    subject, name = text(subject), text(name)
    if subject is None or name is None:
        fail("the site did not say who this person is, so nobody was linked")
    if not (uid.isascii() and uid.isdigit() and int(uid) >= 1000):
        fail("an account below uid 1000 is not a person, so nobody was linked")
    links = load()
    for link in links:
        same_account = str(link.get("account")) == uid
        if link.get("subject") == subject:
            if same_account:
                link["accountName"] = uname
                save(links)
                print(name + " was already linked to " + uname + " (uid " + uid + ").")
                return
            fail(name + " is already linked to the account " + str(link.get("accountName")) + " (uid " + str(link.get("account")) + "). A person has one account on a machine. To move them, run --site-unlink --person " + name + " first.")
        if same_account:
            fail("the account " + uname + " is already linked to " + str(link.get("name")) + ". One account serves one person. To give it to someone else, run --site-unlink --person " + str(link.get("name")) + " first.")
    links.append({
        "subject": subject,
        "name": name,
        "account": uid,
        "accountName": uname,
        "linkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    save(links)
    print("Linked " + name + " to the account " + uname + " (uid " + uid + ").")


if mode == "owner":
    try:
        with open(sys.argv[3], encoding="utf-8") as handle:
            site = json.load(handle)
    except (OSError, ValueError):
        fail("the record of this site could not be read, so its owner was not linked")
    add(site.get("owner"), site.get("ownerName"), sys.argv[4], sys.argv[5])
elif mode == "link":
    try:
        who = json.loads(sys.argv[3])
    except ValueError:
        fail("the site answered with something that is not a person, so nobody was linked")
    if not isinstance(who, dict):
        fail("the site answered with something that is not a person, so nobody was linked")
    add(who.get("subject"), who.get("name"), sys.argv[4], sys.argv[5])
elif mode == "unlink":
    wanted = sys.argv[3].casefold()
    links = load()
    kept = [x for x in links if str(x.get("subject")) != sys.argv[3] and str(x.get("name")).casefold() != wanted]
    if len(kept) == len(links):
        fail("no one named " + sys.argv[3] + " is linked on this machine")
    save(kept)
    print("Removed the link for " + sys.argv[3] + ". Their worker stops now.")
else:
    fail("unknown mode " + mode)
'

# Root, with a clean environment, from `/`, with a umask that leaves what it
# installs readable by the account that runs it. uv gets a root-only home
# and cache; the proxy variables are carried by name, as `as_service` does,
# because uv and curl go to the network and a TLS-intercepting proxy is the
# commonest reason either fails.
as_site_root() {
    set -- env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        HOME="$SITE_CACHE/home" UV_CACHE_DIR="$SITE_CACHE/uv" \
        UV_PYTHON_INSTALL_DIR="$SITE_ROOT/pythons" \
        ${HTTPS_PROXY:+"HTTPS_PROXY=$HTTPS_PROXY"} ${https_proxy:+"https_proxy=$https_proxy"} \
        ${HTTP_PROXY:+"HTTP_PROXY=$HTTP_PROXY"} ${http_proxy:+"http_proxy=$http_proxy"} \
        ${NO_PROXY:+"NO_PROXY=$NO_PROXY"} ${no_proxy:+"no_proxy=$no_proxy"} \
        ${SSL_CERT_FILE:+"SSL_CERT_FILE=$SSL_CERT_FILE"} "$@"
    (umask 022; cd / && as_root "$@")
}

# The site host's own account, for what only it may do (the join, the
# check of a person's sign-in). Same clean environment, its own home.
as_site_account() {
    set -- env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$SITE_SVC_HOME" \
        ${HTTPS_PROXY:+"HTTPS_PROXY=$HTTPS_PROXY"} ${https_proxy:+"https_proxy=$https_proxy"} \
        ${HTTP_PROXY:+"HTTP_PROXY=$HTTP_PROXY"} ${http_proxy:+"http_proxy=$http_proxy"} \
        ${NO_PROXY:+"NO_PROXY=$NO_PROXY"} ${no_proxy:+"no_proxy=$no_proxy"} \
        ${SSL_CERT_FILE:+"SSL_CERT_FILE=$SSL_CERT_FILE"} "$@"
    if [ "$(id -u)" = 0 ] && command -v runuser >/dev/null 2>&1; then
        (cd / && runuser -u "$SITE_SVC_ACCOUNT" -- "$@")
    else
        (cd / && sudo -u "$SITE_SVC_ACCOUNT" -- "$@")
    fi
}

# put_changed MODE OWNER:GROUP PATH < content. Written root-only beside the
# target, given its owner and mode, and renamed over it -- never rewritten in
# place. A file whose content is already right is left alone (its owner and
# mode are still set), so an update does not touch a unit it did not change.
put_changed() {
    _m=$1; _o=$2; _p=$3
    (umask 077; as_root tee "$_p.new" >/dev/null)
    as_root chown "$_o" "$_p.new"
    as_root chmod "$_m" "$_p.new"
    if as_root test -f "$_p" && as_root cmp -s "$_p.new" "$_p"; then
        as_root rm -f "$_p.new"
        as_root chown "$_o" "$_p"
        as_root chmod "$_m" "$_p"
        return 0
    fi
    as_root mv -f "$_p.new" "$_p"
}

# The account the site host runs as: a system user with a home of its own
# and no shell. Its home is 0700: the site's key and enrollment are in it.
ensure_site_account() {
    if ! id "$SITE_SVC_ACCOUNT" >/dev/null 2>&1; then
        say "creating the $SITE_SVC_ACCOUNT account (the job-site host runs as it)"
        _nologin=/usr/sbin/nologin
        [ -x "$_nologin" ] || _nologin=/sbin/nologin
        [ -x "$_nologin" ] || _nologin=/bin/false
        as_root useradd --system --user-group --home-dir "$SITE_SVC_HOME" --no-create-home \
            --shell "$_nologin" "$SITE_SVC_ACCOUNT" \
            || die "could not create the $SITE_SVC_ACCOUNT account"
    fi
    as_root install -d -m 0700 -o "$SITE_SVC_ACCOUNT" -g "$SITE_SVC_ACCOUNT" "$SITE_SVC_HOME"
}

# The program: its own uv, its own Python, a venv, and the site host at the
# pin, all fetched and installed by root. Skipped when the recorded pin is
# the wanted one. EUGENE_PLEXUS_SITE_HOST_SOURCE (a local checkout) is for
# acceptance runs and always reinstalls.
install_site_host() {
    _spec="eugene-plexus-site-host @ https://github.com/eugene-plexus/site-host/archive/$PIN_SITE_HOST.tar.gz"
    _want=$PIN_SITE_HOST
    _local=0
    if [ -n "${EUGENE_PLEXUS_SITE_HOST_SOURCE:-}" ]; then
        _spec=$EUGENE_PLEXUS_SITE_HOST_SOURCE
        _want="local:$EUGENE_PLEXUS_SITE_HOST_SOURCE"
        _local=1
    fi
    if [ "$_local" = 0 ] && as_root test -x "$SITE_PY" \
            && [ "$(as_root cat "$SITE_ROOT/PIN" 2>/dev/null || true)" = "$_want" ]; then
        say "the job-site host is already installed at its pinned version"
        return 0
    fi
    command -v curl >/dev/null 2>&1 || die "curl is required"
    as_root install -d -m 0755 -o root -g root /usr/local/lib/eugene-plexus "$SITE_ROOT" "$SITE_ROOT/bin"
    as_root install -d -m 0700 -o root -g root "$SITE_CACHE" "$SITE_CACHE/home" "$SITE_CACHE/uv"
    _uv=$SITE_ROOT/bin/uv
    _have=$(as_site_root "$_uv" --version 2>/dev/null \
        | sed -n 's/^uv \([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n 1 || true)
    if [ -z "$_have" ] || version_older "$_have" "$UV_MINIMUM"; then
        say "fetching uv for the job-site host (into $SITE_ROOT/bin, as root)"
        # Fetched to a file only root can read or replace, the fetch checked,
        # then run -- the same shape as step 1, and never `sh -c "$(curl)"`.
        _boot=$(as_root mktemp "$SITE_CACHE/uv-install.XXXXXX")
        _err=$(as_root mktemp "$SITE_CACHE/uv-fetch.XXXXXX")
        if ! as_site_root sh -c 'curl -fsSL -o "$1" https://astral.sh/uv/install.sh 2>"$2"' sh "$_boot" "$_err"; then
            printf '\033[31merror:\033[0m could not fetch https://astral.sh/uv/install.sh\n' >&2
            as_root cat "$_err" | sed 's/^/  /' >&2
            printf '  A proxy that intercepts TLS is the usual cause. Set HTTPS_PROXY.\n' >&2
            as_root rm -f "$_boot" "$_err"
            exit 1
        fi
        run_step "installing uv for the job-site host" \
            as_site_root UV_UNMANAGED_INSTALL="$SITE_ROOT/bin" sh "$_boot"
        as_root rm -f "$_boot" "$_err"
        as_root test -x "$_uv" || die "uv did not land at $_uv"
    fi
    if ! as_root test -x "$SITE_PY"; then
        run_step "creating a Python $PY_VERSION virtualenv for the job-site host" \
            as_site_root "$_uv" venv --python "$PY_REQUEST" --python-preference only-managed "$SITE_ROOT/venv"
        as_root test -x "$SITE_PY" || die "uv reported success but there is no interpreter at $SITE_PY"
    fi
    run_step "installing the job-site host" \
        as_site_root "$_uv" pip install --python "$SITE_PY" \
        --reinstall-package eugene-plexus-site-host "$_spec"
    # Root's, and writable by nobody else, whatever uv's umask made.
    as_root chown -R root:root "$SITE_ROOT"
    as_root chmod -R go-w,a+rX "$SITE_ROOT"
    as_site_account "$SITE_PY" -I -c 'import eugene_plexus_site_host, eugene_plexus_site_host.worker' \
        || die "the job-site host was installed, but the $SITE_SVC_ACCOUNT account cannot run it"
    printf '%s\n' "$_want" | put_changed 0644 root:root "$SITE_ROOT/PIN"
}

# Root's configuration: the links and the local servers (root's to write; the
# site host reads them and cannot change them), and the site host's
# environment. `links.json` and `servers.yaml` are made once and then left:
# they are what the people at the machine have put in them.
write_site_config() {
    as_root install -d -m 0755 -o root -g root /etc/eugene-plexus "$SITE_CONF"
    if ! as_root test -e "$SITE_CONF/links.json"; then
        printf '{"version": 1, "links": []}\n' | put_changed 0644 root:root "$SITE_CONF/links.json"
    fi
    if ! as_root test -e "$SITE_CONF/servers.yaml"; then
        printf 'servers: []\n' | put_changed 0640 "root:$SITE_SVC_ACCOUNT" "$SITE_CONF/servers.yaml"
    fi
    as_root chown root:root "$SITE_CONF/links.json"
    as_root chmod 0644 "$SITE_CONF/links.json"
    as_root chown "root:$SITE_SVC_ACCOUNT" "$SITE_CONF/servers.yaml"
    as_root chmod 0640 "$SITE_CONF/servers.yaml"
    SITE_PORT=$(as_root cat "$SITE_CONF/host.json" 2>/dev/null \
        | sed -n 's/.*"port"[^0-9]*\([0-9][0-9]*\).*/\1/p' | head -n 1 || true)
    SITE_PORT=${SITE_PORT:-$SITE_DEFAULT_PORT}
    printf '{"port": %s}\n' "$SITE_PORT" | put_changed 0644 root:root "$SITE_CONF/host.json"
    # systemd reads an EnvironmentFile's quotes, so the JSON list is in
    # single quotes: everything inside them is literal.
    put_changed 0644 root:root "$SITE_CONF/host.env" <<EOF
EUGENE_PLEXUS_APP_DATA_DIR=$SITE_SVC_HOME
EUGENE_PLEXUS_APP_BIND_PORT=$SITE_PORT
EUGENE_PLEXUS_APP_ACCOUNT_KIND=systemd
SITE_HOST_PROTECTED_ROOTS='["/var/lib/eugene-plexus","/etc/eugene-plexus","/usr/local/lib/eugene-plexus","/var/lib/eugene-plexus-site"]'
SITE_HOST_LINKS_FILE=$SITE_CONF/links.json
SITE_HOST_LOCAL_SERVERS_FILE=$SITE_CONF/servers.yaml
SITE_HOST_CHANNEL=/run/eugene-plexus-site/channel
EOF
}

# The units and the root script that keeps one worker per linked person.
write_site_units() {
    _hostuid=$(id -u "$SITE_SVC_ACCOUNT")
    put_changed 0644 root:root "$SITE_HOST_UNIT" <<EOF
[Unit]
Description=Eugene Plexus job-site host
Documentation=https://github.com/eugene-plexus/specs/blob/main/docs/design/job-sites-own-enrollment.md
After=network-online.target
Wants=network-online.target

[Service]
User=$SITE_SVC_ACCOUNT
Group=$SITE_SVC_ACCOUNT
EnvironmentFile=$SITE_CONF/host.env
ExecStart=$SITE_PY -I -m eugene_plexus_site_host serve
# The folder its channel to the workers is in. 0755: a worker running as a
# person has to be able to reach the socket in it.
RuntimeDirectory=eugene-plexus-site
RuntimeDirectoryMode=0755
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=$SITE_SVC_HOME
ProtectHome=yes
PrivateTmp=yes
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    # One instance per linked person, the instance being their uid. No
    # ProtectHome: it works in that person's own files, as that person. The
    # server list arrives as a credential (systemd reads it as root), so the
    # worker's account needs no read of /etc/eugene-plexus/site/servers.yaml.
    put_changed 0644 root:root "$SITE_WORKER_UNIT" <<EOF
[Unit]
Description=Eugene Plexus job-site worker for uid %i
After=eugene-plexus-site-host.service

[Service]
User=%i
ExecStart=$SITE_PY -I -m eugene_plexus_site_host.worker --account %i --channel /run/eugene-plexus-site/channel --host $_hostuid --servers %d/servers --protect /var/lib/eugene-plexus --protect /etc/eugene-plexus --protect /usr/local/lib/eugene-plexus --protect /var/lib/eugene-plexus-site
LoadCredential=servers:$SITE_CONF/servers.yaml
NoNewPrivileges=yes
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    put_changed 0644 root:root "$SITE_WORKERS_UNIT" <<EOF
[Unit]
Description=Eugene Plexus job site: one worker for each linked person

[Service]
Type=oneshot
ExecStart=$SITE_WORKERS
EOF
    put_changed 0644 root:root "$SITE_WORKERS_PATH" <<EOF
[Unit]
Description=Eugene Plexus job-site links

[Path]
PathChanged=$SITE_CONF/links.json
Unit=eugene-plexus-site-workers.service

[Install]
WantedBy=paths.target
EOF
    as_root install -d -m 0755 -o root -g root "$(dirname "$SITE_WORKERS")"
    put_changed 0755 root:root "$SITE_WORKERS" <<'SITEWORKERS'
#!/bin/sh
# Installed by Eugene Plexus's install.sh; see "a job site on a Linux system
# install" there. Run as root by eugene-plexus-site-workers.service when
# /etc/eugene-plexus/site/links.json changes, and by the installer.
#
# One worker for each linked account, and none for any other. Reads only the
# root-owned links file, with the root-owned program; an id is used only if
# it is all digits, is 1000 or more, and names an account on this machine.
# Safe to run any number of times.
set -u
LINKS=/etc/eugene-plexus/site/links.json
PY=/usr/local/lib/eugene-plexus/site-host/venv/bin/python
UNIT=eugene-plexus-site-worker

WANT=$("$PY" -I -c '
import json, sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
    for link in data["links"]:
        account = link["account"]
        if isinstance(account, str) and account.isascii() and account.isdigit():
            print(account)
except FileNotFoundError:
    pass
' "$LINKS") || { echo "eugene-plexus-site-workers: $LINKS could not be read; no worker was changed" >&2; exit 1; }

LINKED=" "
for U in $WANT; do
    case "$U" in ''|*[!0-9]*) continue ;; esac
    [ "${#U}" -le 9 ] || continue
    [ "$(expr "$U" + 0)" = "$U" ] || continue
    [ "$U" -ge 1000 ] || continue
    if ! getent passwd "$U" >/dev/null 2>&1; then
        echo "eugene-plexus-site-workers: no account has uid $U on this machine; skipped" >&2
        continue
    fi
    LINKED="$LINKED$U "
    systemctl enable --now "$UNIT@$U.service" >/dev/null 2>&1 \
        || echo "eugene-plexus-site-workers: could not start the worker for uid $U" >&2
done

# Every worker that is loaded, or only enabled, for an account that is not
# linked: stopped and disabled.
HAVE=$( {
    systemctl list-units --all --plain --no-legend --type=service "$UNIT@*.service" 2>/dev/null |
        awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^eugene-plexus-site-worker@/) { print $i; break } }'
    find /etc/systemd/system -name "$UNIT@*.service" 2>/dev/null | sed 's|.*/||'
} | sed -n "s/^$UNIT@\([0-9][0-9]*\)\.service\$/\1/p" | sort -u )
for U in $HAVE; do
    case "$LINKED" in *" $U "*) continue ;; esac
    systemctl disable --now "$UNIT@$U.service" >/dev/null 2>&1 \
        || systemctl stop "$UNIT@$U.service" >/dev/null 2>&1 || true
done
exit 0
SITEWORKERS
}

site_reconcile() {
    as_root "$SITE_WORKERS" || warn "could not start the workers for the linked people: sudo $SITE_WORKERS"
}

# Everything a site needs on disk, in one call: used by --job-site and by
# an update.
site_prepare() {
    ensure_site_account
    install_site_host
    write_site_config
    write_site_units
}

# An update (run as root by the update unit): the program at this
# installer's pin, the units as this installer writes them, and the host and
# its workers restarted. Does nothing on a machine that is not a job site.
update_site_host() {
    as_root test -f "$SITE_CONF/host.env" || return 0
    say "updating the job-site host"
    site_prepare
    as_root systemctl daemon-reload
    as_root systemctl restart eugene-plexus-site-host.service
    as_root systemctl try-restart 'eugene-plexus-site-worker@*.service' >/dev/null 2>&1 || true
    site_reconcile
}

# Removal. The state folder holds the site's key and its enrollment, so it
# is handled like the prefix is: moved aside, handed to root (the account is
# deleted next, and files left under its number would belong to whichever
# system account is given that number later), and said. It is never deleted
# here. The apps' state folders (systemd's) are left where they are, so
# this is the one place a state folder is moved.
remove_site_host() {
    as_root systemctl disable --now eugene-plexus-site-workers.path eugene-plexus-site-workers.service \
        eugene-plexus-site-host.service >/dev/null 2>&1 || true
    for _u in $(as_root find /etc/systemd/system -name 'eugene-plexus-site-worker@[0-9]*.service' 2>/dev/null \
            | sed 's|.*/||' | sort -u); do
        as_root systemctl disable --now "$_u" >/dev/null 2>&1 || as_root systemctl stop "$_u" >/dev/null 2>&1 || true
    done
    as_root rm -f "$SITE_HOST_UNIT" "$SITE_WORKER_UNIT" "$SITE_WORKERS_UNIT" "$SITE_WORKERS_PATH" "$SITE_WORKERS"
    as_root rm -rf "$SITE_ROOT" "$SITE_CONF" "$SITE_CACHE"
    as_root rmdir /etc/eugene-plexus >/dev/null 2>&1 || true
    as_root systemctl daemon-reload >/dev/null 2>&1 || true
    if as_root test -d "$SITE_SVC_HOME"; then
        _keep=$SITE_SVC_HOME.removed-$(date +%Y%m%d%H%M%S)
        as_root mv "$SITE_SVC_HOME" "$_keep"
        as_root chown -R root:root "$_keep"
        as_root chmod 0700 "$_keep"
        say "the job site's own records are at $_keep (readable by root only);"
        say "  delete it when you are sure: sudo rm -rf '$_keep'. The install it joined still lists"
        say "  this machine as a job site: remove it there (Workbench, Job sites)."
    fi
    if id "$SITE_SVC_ACCOUNT" >/dev/null 2>&1; then
        as_root userdel "$SITE_SVC_ACCOUNT" >/dev/null 2>&1 \
            || warn "could not remove the $SITE_SVC_ACCOUNT account: sudo userdel $SITE_SVC_ACCOUNT"
    fi
}

# --- the person at the machine: a password and an account -----------------
# A password is read where only the person can see it -- the terminal, with
# echo off -- or, for automation, from the first line of this script's own
# standard input (--password-stdin). It is never an argument or part of the
# environment of any process: it is written to the site host's stdin by a
# shell builtin.
site_read_password() {
    SITE_PW=
    if [ "$PASSWORD_STDIN" = 1 ]; then
        IFS= read -r SITE_PW || true
    else
        ( : </dev/tty ) 2>/dev/null || die "this needs $1's Eugene password, typed at a terminal, and this
       has none. Run it from a terminal, or give the password as the first line of
       standard input with --password-stdin (save this script to a file first, so its
       own standard input is free)."
        printf "%s's Eugene password: " "$1" >/dev/tty
        TTY_SAVED=$(stty -g </dev/tty 2>/dev/null || true)
        stty -echo </dev/tty 2>/dev/null || true
        IFS= read -r SITE_PW </dev/tty || true
        if [ -n "$TTY_SAVED" ]; then stty "$TTY_SAVED" </dev/tty 2>/dev/null || true; fi
        TTY_SAVED=
        printf '\n' >/dev/tty
    fi
    [ -n "$SITE_PW" ] || die "no password was given, so nothing was changed"
}

# Which account a person works as: --site-account, else the account that ran
# sudo. Never root, never a system account, never one of Eugene's own.
site_resolve_account() {
    if [ -n "$SITE_LINK_ACCOUNT" ]; then
        SITE_UID=$(id -u -- "$SITE_LINK_ACCOUNT" 2>/dev/null) \
            || die "there is no account named $SITE_LINK_ACCOUNT on this machine"
    elif [ -n "${SUDO_UID:-}" ]; then
        SITE_UID=$SUDO_UID
    else
        die "say which account this person works as on this machine:  --site-account USER
       (it is taken from sudo when you run this with sudo)"
    fi
    case "$SITE_UID" in ''|*[!0-9]*) die "that account's number ($SITE_UID) is not one this installer can use" ;; esac
    [ "$SITE_UID" != 0 ] || die "root cannot be linked to a person: their calls would run as root"
    [ "$SITE_UID" -ge 1000 ] || die "uid $SITE_UID is a system account, not a person (people are uid 1000 and up)"
    for _a in "$SITE_SVC_ACCOUNT" "$SYSTEM_ACCOUNT"; do
        if [ "$(id -u -- "$_a" 2>/dev/null || true)" = "$SITE_UID" ]; then
            die "$_a is one of Eugene's own accounts, not a person. Name the person's own account."
        fi
    done
    SITE_UNAME=$(getent passwd "$SITE_UID" | cut -d: -f1)
    [ -n "$SITE_UNAME" ] || die "no account on this machine has uid $SITE_UID"
}

site_link_py() { as_site_root "$SITE_PY" -I -c "$SITE_LINK_PY" "$@"; }

# What every --job-site / --site-link / --site-unlink on a system install
# needs first.
site_system_preflight() {
    [ "$MODE" = system ] || die "$1 needs Eugene installed as a system service (the default on Linux). A per-user
       install (--user) serves only the person who installed it, so it has nothing to link."
    [ -d /run/systemd/system ] || die "this machine is not running systemd, so a job site cannot run its workers here"
    if [ "$(id -u)" != 0 ]; then
        command -v sudo >/dev/null 2>&1 || die "this needs root, and sudo is not installed. Run it as root."
        sudo -v || die "sudo was refused, so nothing was changed"
    fi
}

site_require_installed() {
    as_root test -f "$SITE_CONF/host.env" && as_root test -f "$SITE_SVC_HOME/site.json" \
        || die "this machine is not a job site yet. Add it first, with the join command Workbench gives
       you (Job sites -> Add a job site)."
}

# --site-link: who the person is, from their Eugene sign-in typed here, and
# then a link written by root. The site host's own account asks the root;
# root never takes the person's word for who they are.
site_link_person() {
    [ -n "$SITE_PERSON" ] || die "--site-link needs --person NAME, how that person signs in to Eugene"
    site_system_preflight "--site-link"
    site_require_installed
    site_resolve_account
    site_read_password "$SITE_PERSON"
    _who=$(printf '%s\n' "$SITE_PW" | as_site_account "$SITE_PY" -I -m eugene_plexus_site_host \
        check-person --name "$SITE_PERSON" --data-dir "$SITE_SVC_HOME") \
        || die "$SITE_PERSON could not be checked (see above), so nobody was linked"
    SITE_PW=
    site_link_py link "$SITE_CONF/links.json" "$_who" "$SITE_UID" "$SITE_UNAME" \
        || die "nobody was linked"
    # The path unit starts the worker too; this makes it immediate.
    site_reconcile
    say "done: $SITE_PERSON's job-site calls on this machine now run as $SITE_UNAME, in their own files"
    say "  and with their own permissions."
}

# --site-pair (J14a.3): a Linux system install has no page at the machine,
# so the code for pairing the owner's passkey is shown here, at the terminal
# the owner is already at. The site host makes it and checks the passkey's
# MAC with it; this script only asks the running host for it, as the host's
# own account, which can read the host's loopback token.
site_host_port() {
    as_root cat "$SITE_CONF/host.json" 2>/dev/null \
        | sed -n 's/.*"port"[^0-9]*\([0-9][0-9]*\).*/\1/p' | head -n 1 || true
}

site_passkey_command() {
    site_system_preflight "$1"
    site_require_installed
    _port=$(site_host_port)
    [ -n "$_port" ] || die "the job site's port is not recorded in $SITE_CONF/host.json"
    shift
    as_site_account "$SITE_PY" -I -m eugene_plexus_site_host "$@" \
        --data-dir "$SITE_SVC_HOME" --port "$_port"
}

site_unlink_person() {
    [ -n "$SITE_PERSON" ] || die "--site-unlink needs --person NAME"
    site_system_preflight "--site-unlink"
    site_require_installed
    site_link_py unlink "$SITE_CONF/links.json" "$SITE_PERSON" || die "nobody was unlinked"
    site_reconcile
}

# --job-site on a system install: the program, the account, the root's
# configuration and units; the site host's own `join`, run as its own
# account with the owner's password on its standard input; the owner's link;
# then the site host and the workers started.
site_join_system() {
    site_system_preflight "a job site"
    as_root test -x "$VENV/bin/eugene-plexus-agent" || die "this machine is not a node yet.
       Install Eugene here and join it to your install first, then run this
       again. A machine that is only a job site waits for the standalone install."
    SITE_LABEL=${JOIN_NAME:-$(hostname)}
    # Before anything is changed: a link that cannot be made stops the run
    # now, not after the machine has joined.
    site_resolve_account
    site_prepare
    as_root systemctl daemon-reload
    site_read_password "$JOIN_OWNER"
    set -- join --data-dir "$SITE_SVC_HOME" --url "$JOIN_CONTROL" --token "$JOIN_TOKEN" \
        --owner "$JOIN_OWNER" --label "$SITE_LABEL"
    if [ -n "$JOIN_ROOT_KEY" ]; then set -- "$@" --root-key "$JOIN_ROOT_KEY"; fi
    say "adding $SITE_LABEL as a job site of $JOIN_OWNER"
    printf '%s\n' "$SITE_PW" | as_site_account "$SITE_PY" -I -m eugene_plexus_site_host "$@" \
        || die "the job site was not added (see above). Its program and accounts are installed;
       run the same command again once that is fixed."
    SITE_PW=
    site_link_py owner "$SITE_CONF/links.json" "$SITE_SVC_HOME/site.json" "$SITE_UID" "$SITE_UNAME" \
        || die "the site joined, but its owner was not linked to an account. Run:  --site-link --person $JOIN_OWNER"
    as_root systemctl enable --now eugene-plexus-site-host.service eugene-plexus-site-workers.path \
        >/dev/null 2>&1 || warn "could not enable the job-site units: sudo systemctl enable --now eugene-plexus-site-host.service eugene-plexus-site-workers.path"
    # The host reads its enrollment at start, and may have run before it.
    as_root systemctl restart eugene-plexus-site-host.service \
        || warn "the job-site host did not start: sudo journalctl -u eugene-plexus-site-host"
    site_reconcile
    say "done: $SITE_LABEL is a job site of $JOIN_OWNER. Its owner manages it from Workbench (Job sites)."
    say "  $JOIN_OWNER's calls on this machine run as the account $SITE_UNAME, in their own files."
    say "  Anyone else's run in that same worker, confined to the folders $JOIN_OWNER shares."
    say "  To let another person work as their own account here, they or you run, on this machine:"
    say "    curl -fsSL $INSTALLER_URL | sudo sh -s -- --site-link --person NAME --account USER"
    say "  No tool runs here until $JOIN_OWNER pairs a passkey from Workbench (at its https"
    say "  address) and approves this machine's rules with it. To show the code for that, run:"
    say "    curl -fsSL $INSTALLER_URL | sudo sh -s -- --site-pair"
}

# --- service plumbing -------------------------------------------------
# A *user* service in the per-user layout: it reads the user's own model
# directories and writes to the user's own keyring, and the cost is
# stated where it bites, at enable-linger below. A *system* service in the
# default Linux layout, for the reasons above.
SYSTEMD_UNIT=$HOME/.config/systemd/user/$SERVICE_LABEL.service
SYSTEM_UNIT=/etc/systemd/system/$SERVICE_LABEL.service
LAUNCHD_PLIST=$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist

service_stop() {
    if [ "$MODE" = system ]; then
        [ -f "$SYSTEM_UNIT" ] || return 0
        as_root systemctl stop "$SERVICE_LABEL" >/dev/null 2>&1 || true
        as_root systemctl disable "$SERVICE_LABEL" >/dev/null 2>&1 || true
    elif [ "$PLATFORM" = linux ]; then
        [ -f "$SYSTEMD_UNIT" ] || return 0
        systemctl --user stop "$SERVICE_LABEL" >/dev/null 2>&1 || true
        systemctl --user disable "$SERVICE_LABEL" >/dev/null 2>&1 || true
    else
        [ -f "$LAUNCHD_PLIST" ] || return 0
        launchctl bootout "gui/$(id -u)/$LAUNCHD_LABEL" >/dev/null 2>&1 || true
    fi
}

# BEGIN GENERATED OFFLINE REMOVAL
# Source: scripts/uninstall*; regenerate with python scripts/embed-uninstall.py.
write_removal_bundle() {
    mkdir -p "$PREFIX/uninstall"
    cat > "$PREFIX/uninstall/inventory.py" <<'EUGENE_REMOVAL_INVENTORY_PY'
"""Read an install's removal inventory before its Python is removed.

Installed verbatim by both installers. This program never deletes files.
The native uninstallers retain its plain-text inventory for offline cleanup.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shlex
import sys


def absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def overlaps(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or a in b.parents or b in a.parents


def read_config(path: Path, warnings: list[str]) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml

        value = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
        if not isinstance(value, dict):
            raise ValueError("expected a mapping")
        return value
    except Exception as exc:
        warnings.append(
            f"Could not read {path} ({type(exc).__name__}). Custom downloads are kept."
        )
        return {}


def inventory(prefix: Path) -> dict:
    warnings: list[str] = []
    agent = read_config(prefix / "agent.yaml", warnings)
    protected = [prefix / "models", Path.home() / "Eugene Models"]

    # Library state contains modelRoots and, on newer installations, folders.
    def roots(value: object, key: str = "") -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ("modelRoots", "defaultModelRoots") and isinstance(v, list):
                    protected.extend(absolute(p) for p in v if isinstance(p, str))
                    roots(v, k)
                elif (
                    k in ("path", "localPath")
                    and key in ("folders", "modelRoots")
                    and isinstance(v, str)
                ):
                    protected.append(absolute(v))
                else:
                    roots(v, k)
        elif isinstance(value, list):
            for v in value:
                roots(v, key)

    for config in prefix.glob("library*.yaml"):
        roots(read_config(config, warnings))
    roots(agent)
    software = [
        prefix / name for name in ("venv", "pythons", "bin", ".cache/uv", "update")
    ]
    software += [
        prefix / name for name in ("install-check.py", "release-requirements.lock")
    ]
    apps = prefix / "apps"
    software += [apps / name for name in ("pythons", "launcher", "ctl")]
    data = [prefix / name for name in ("logs", "passphrase", "control-state")]
    for app in apps.iterdir() if apps.is_dir() and not apps.is_symlink() else []:
        if (
            app.is_dir()
            and not app.is_symlink()
            and app.name not in ("pythons", "launcher", "ctl")
        ):
            software += [app / "versions", app / "python"]
            data += [p for p in app.iterdir() if p.name not in ("versions", "python")]
    for item in prefix.iterdir():
        if item.is_file() and (
            item.suffix
            in (
                ".yaml",
                ".json",
                ".sqlite3",
                ".db",
                ".sqlite3-wal",
                ".sqlite3-shm",
                ".db-wal",
                ".db-shm",
            )
            or item.name.startswith(
                (
                    ".update-channel",
                    "agent.yaml.",
                    "node.yaml.",
                    "control.yaml.",
                    "gateway.yaml.",
                    "library.yaml.",
                )
            )
        ):
            data.append(item)
    if apps.is_dir():
        data += [p for p in apps.iterdir() if p.is_file()]
    downloads = [prefix / "engines"]
    engine = os.environ.get("EUGENE_PLEXUS_AGENT_ENGINE_ROOT")
    # Service installs own prefix/engines. Do not also sweep the invoking
    # administrator's per-user store (which may belong to another install).
    info_path = prefix / "uninstall/install-info.json"
    if info_path.exists():
        try:
            recorded_engine = json.loads(info_path.read_text(encoding="utf-8"))[
                "engineRoot"
            ]
            downloads.append(absolute(recorded_engine))
        except (OSError, ValueError, KeyError, TypeError):
            warnings.append(
                "Could not read the installed download location. External engines were kept."
            )
    elif not (prefix / "engines").exists():
        if engine and absolute(engine) != prefix / "engines":
            warnings.append(
                f"External engine store kept: {engine}. Its ownership cannot be confirmed from this installation."
            )
        elif not engine:
            downloads.append(Path.home() / ".eugene-plexus/engines")
    copies = agent.get("modelCopyDir")
    if isinstance(copies, str) and copies:
        if Path(copies).expanduser().is_absolute():
            downloads.append(absolute(copies))
        else:
            warnings.append(
                f"Relative model-copy location kept: {copies}. Its working directory cannot be confirmed."
            )
    if any(w.startswith("Could not read") for w in warnings):
        downloads = []
        warnings.append(
            "Downloads were kept because the configuration could not be read safely."
        )
    result: dict = {"version": 1, "prefix": str(prefix), "warnings": warnings}
    for kind, candidates in (
        ("software", software),
        ("data", data),
        ("downloads", downloads),
    ):
        kept = []
        for path in dict.fromkeys(absolute(p) for p in candidates):
            if not path.exists() and not path.is_symlink():
                continue
            if "\n" in str(path) or "\r" in str(path):
                warnings.append(
                    f"Kept a {kind} path containing a newline; remove it manually."
                )
                continue
            if (
                path == prefix
                or path in prefix.parents
                or path == absolute(Path.home())
                or len(path.parts) < 3
            ):
                warnings.append(f"Kept unsafe {kind} path: {path}")
                continue
            if any(overlaps(path, p) for p in protected):
                warnings.append(f"Kept {path}: it overlaps an original model folder.")
                continue
            # Never traverse a symlink/junction to make a deletion inventory.
            if any(
                p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                for p in (path, *path.parents)
            ):
                warnings.append(f"Kept {path}: it uses a link or junction.")
                continue
            kept.append(str(path))
        result[kind] = kept
    result["protected"] = list(dict.fromkeys(str(absolute(p)) for p in protected))
    return result


def keyring_cleanup(prefix: Path) -> dict:
    warnings: list[str] = []
    config = read_config(prefix / "agent.yaml", warnings)
    auth = config.get("auth") or {}
    if not isinstance(auth, dict):
        return {
            "removed": 0,
            "warnings": ["Credentials kept: the auth configuration is not readable."],
        }
    salt = auth.get("masterSalt")
    names = []
    if salt:
        try:
            fingerprint = hashlib.sha256(
                base64.b64decode(salt, validate=True)
            ).hexdigest()[:12]
            # The application uses a colon. The old uninstall/test code
            # incorrectly used a dash; also remove that historical spelling.
            names = ["master-key:" + fingerprint, "master-key-" + fingerprint]
        except Exception as exc:
            warnings.append(f"Could not identify this install's credentials: {exc}")
    elif config.get("auth"):
        # A legacy entry is shared; do not delete a different install's key.
        warnings.append(
            "Legacy unscoped credentials were kept. Review Eugene entries in the OS credential store."
        )
    removed = 0
    if names:
        try:
            import keyring

            for service in ("eugene-plexus-agent", "eugene-plexus-control"):
                for name in names:
                    try:
                        if keyring.get_password(service, name) is not None:
                            keyring.delete_password(service, name)
                            if keyring.get_password(service, name) is not None:
                                raise RuntimeError(
                                    "entry is still present after deletion"
                                )
                            removed += 1
                    except Exception as exc:
                        warnings.append(f"Credential left: {service}/{name}: {exc}")
        except Exception as exc:
            warnings.append(f"Could not open the OS credential store: {exc}")
    return {"removed": removed, "warnings": warnings}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--keyring-only", action="store_true")
    parser.add_argument("--install-macos", action="store_true")
    args = parser.parse_args()
    prefix = absolute(args.prefix)
    if args.install_macos:
        install_macos(prefix)
        return
    if args.output is None:
        parser.error("--output is required")
    result = keyring_cleanup(prefix) if args.keyring_only else inventory(prefix)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    if not args.keyring_only:
        for kind in ("software", "data", "downloads", "protected"):
            (args.output.parent / f"{kind}.txt").write_text(
                "".join(p + "\n" for p in result[kind]), encoding="utf-8"
            )
        (args.output.parent / "original-prefix.txt").write_text(
            str(prefix) + "\n", encoding="utf-8"
        )
        (args.output.parent / "warnings.txt").write_text(
            "\n".join(result["warnings"]), encoding="utf-8"
        )
        programs = [prefix / "venv/bin/python", Path(sys.executable).resolve()]
        owned_programs = [
            str(p) for p in programs if p.resolve().is_relative_to(prefix.resolve())
        ]
        (args.output.parent / "firewall.txt").write_text(
            "".join(p + "\n" for p in dict.fromkeys(owned_programs)), encoding="utf-8"
        )
        app_record = prefix / "uninstall/mac-app.txt"
        if app_record.exists():
            (args.output.parent / "mac-app.txt").write_text(
                app_record.read_text(encoding="utf-8"), encoding="utf-8"
            )
    for warning in result["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)


def install_macos(prefix: Path) -> None:
    """A Finder-visible local utility; no interpreter or network at launch."""
    suffix = (
        ""
        if prefix == Path.home() / ".local/share/eugene-plexus"
        else " " + hashlib.sha256(str(prefix).encode()).hexdigest()[:8]
    )
    app = Path.home() / "Applications" / f"Remove Eugene Plexus{suffix}.app"
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Resources").mkdir(exist_ok=True)
    (contents / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": "com.eugeneplexus.remove" + suffix.strip(),
                "CFBundleName": "Remove Eugene Plexus",
                "CFBundleDisplayName": "Remove Eugene Plexus",
                "CFBundleExecutable": "remove",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
                "LSUIElement": True,
            }
        )
    )
    executable = contents / "MacOS/remove"
    executable.write_text(
        "#!/bin/sh\nexec /bin/sh "
        + shlex.quote(str(prefix / "uninstall/remove.sh"))
        + " --interactive\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    (contents / "Resources/prefix.txt").write_text(str(prefix) + "\n", encoding="utf-8")
    (prefix / "uninstall/mac-app.txt").write_text(str(app) + "\n", encoding="utf-8")
    engine = os.environ.get("EUGENE_PLEXUS_AGENT_ENGINE_ROOT") or str(
        Path.home() / ".eugene-plexus/engines"
    )
    (prefix / "uninstall/install-info.json").write_text(
        json.dumps({"engineRoot": engine}), encoding="utf-8"
    )
    print(f"Removal utility: {app}")


if __name__ == "__main__":
    main()
EUGENE_REMOVAL_INVENTORY_PY
    cat > "$PREFIX/uninstall/remove.sh" <<'EUGENE_REMOVAL_REMOVE_SH'
#!/bin/sh
# Offline removal. The installer embeds this script and inventory.py.
set -eu
PREFIX=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
INTERACTIVE=0 PURGE_DOWNLOADS=0 PURGE_DATA=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=$2; shift 2 ;;
        --interactive) INTERACTIVE=1; shift ;;
        --purge-downloads|--purge-model-copies) PURGE_DOWNLOADS=1; shift ;;
        --purge-data) PURGE_DATA=1; shift ;;
        *) echo "Unknown removal option: $1" >&2; exit 2 ;;
    esac
done
PLATFORM=$(uname -s)
case "$PREFIX" in ''|/|"$HOME"|/Applications|/usr|/var|/opt|*/../*|*/./*) echo "Not an installation folder: $PREFIX" >&2; exit 1 ;; esac
if [ ! -d "$PREFIX" ]; then echo "Nothing installed at $PREFIX"; exit 0; fi
if [ -L "$PREFIX" ]; then echo "Refusing a linked installation folder: $PREFIX" >&2; exit 1; fi
if [ ! -f "$PREFIX/agent.yaml" ] && [ ! -f "$PREFIX/node.yaml" ] && [ ! -f "$PREFIX/bin/uv" ] && [ ! -f "$PREFIX/uninstall/receipt/inventory.json" ]; then
    echo "No Eugene installation or removal receipt at $PREFIX. Nothing was removed." >&2; exit 1
fi
PREFIX=$(CDPATH= cd -- "$PREFIX" && pwd -P)
RECEIPT=$PREFIX/uninstall/receipt
mkdir -p "$RECEIPT"
chmod 700 "$RECEIPT"
WARNINGS=$RECEIPT/current-warnings.txt
: > "$WARNINGS"
warn() { printf 'warning: %s\n' "$*" >&2; printf '%s\n' "$*" >> "$WARNINGS"; }
fail() {
    warn "$*"
    if [ "$INTERACTIVE" = 1 ] && [ "$PLATFORM" = Darwin ]; then
        /usr/bin/osascript - "$*" <<'APPLE' || true
on run argv
    display dialog (item 1 of argv) with title "Eugene removal did not finish" buttons {"OK"} default button "OK" with icon caution
end run
APPLE
    fi
    exit 1
}
PYBIN=$PREFIX/venv/bin/python
if [ ! -f "$RECEIPT/inventory.json" ] || { [ ! -f "$RECEIPT/removed.txt" ] && [ -x "$PYBIN" ]; }; then
    if [ -x "$PYBIN" ]; then
        "$PYBIN" -I "$PREFIX/uninstall/inventory.py" --prefix "$PREFIX" --output "$RECEIPT/inventory.json" || fail "Could not inventory this installation. Nothing was removed."
    else
        printf '%s\n' "$PREFIX" > "$RECEIPT/original-prefix.txt"
        for name in venv pythons bin .cache/uv update; do printf '%s/%s\n' "$PREFIX" "$name"; done > "$RECEIPT/software.txt"
        : > "$RECEIPT/data.txt"; : > "$RECEIPT/downloads.txt"
        printf '%s/models\n' "$PREFIX" > "$RECEIPT/protected.txt"
        printf '%s\n' 'Python is missing. Settings, downloads and credentials were kept; review the remaining folder.' > "$RECEIPT/warnings.txt"
        printf '{}\n' > "$RECEIPT/inventory.json"
    fi
fi
ORIGINAL=$(cat "$RECEIPT/original-prefix.txt")
map_path() {
    case "$1" in "$ORIGINAL"/*) printf '%s%s\n' "$PREFIX" "${1#"$ORIGINAL"}" ;; *) printf '%s\n' "$1" ;; esac
}
group_size() {
    total=0 unknown=0
    while IFS= read -r original; do
        path=$(map_path "$original")
        if [ -e "$path" ] && [ ! -L "$path" ]; then
            if usage=$(du -sk "$path" 2>/dev/null); then
                kb=$(printf '%s\n' "$usage" | awk '{print $1}')
                total=$((total + ${kb:-0}))
            else unknown=1; fi
        fi
    done < "$RECEIPT/$1.txt"
    if [ "$unknown" = 1 ]; then printf 'size unavailable'; else awk -v kb="$total" 'BEGIN {printf "%.2f GB", kb/1048576}'; fi
}
if [ "$INTERACTIVE" = 1 ] && [ "$PLATFORM" = Darwin ]; then
    if ! CHOICE=$(/usr/bin/osascript - "$(group_size software)" "$(group_size data)" "$(group_size downloads)" "$PREFIX" <<'APPLE'
on run argv
    set dataChoice to "Delete settings, app data and logs (" & item 2 of argv & ")"
    set downloadChoice to "Delete downloaded engines and model copies (" & item 3 of argv & ")"
    set picked to choose from list {dataChoice, downloadChoice} with title "Remove Eugene Plexus" with prompt ("Software to remove: " & item 1 of argv & return & "Original model folders will be kept." & return & "Optionally select data to delete:") default items {} OK button name "Continue" cancel button name "Cancel" with multiple selections allowed and empty selection allowed
    if picked is false then error number -128
    display dialog ("Remove Eugene from this computer?" & return & item 4 of argv & return & "Items you did not select will be kept.") with title "Remove Eugene Plexus" buttons {"Cancel", "Remove Eugene"} default button "Cancel" cancel button "Cancel" with icon caution
    set answer to ""
    if picked contains dataChoice then set answer to answer & "data "
    if picked contains downloadChoice then set answer to answer & "downloads"
    return answer
end run
APPLE
    ); then echo 'Removal cancelled.'; exit 0; fi
    case "$CHOICE" in *data*) PURGE_DATA=1 ;; esac
    case "$CHOICE" in *downloads*) PURGE_DOWNLOADS=1 ;; esac
fi
if [ -s "$RECEIPT/warnings.txt" ]; then cat "$RECEIPT/warnings.txt" >> "$WARNINGS"; fi

if [ ! -f "$RECEIPT/removed.txt" ]; then
    if [ "$PLATFORM" = Darwin ]; then
        LABEL=com.eugeneplexus.agent
        PLIST=$HOME/Library/LaunchAgents/$LABEL.plist
        if [ -f "$PLIST" ]; then
            OWNER=$(/usr/libexec/PlistBuddy -c 'Print :ProgramArguments:0' "$PLIST") || fail "Cannot read $PLIST. Nothing was removed."
            case "$OWNER" in "$PREFIX"/*) ;; *) fail "The startup job belongs to $OWNER. Use that install's removal utility." ;; esac
            if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
                launchctl bootout "gui/$(id -u)/$LABEL" || fail "macOS could not stop Eugene. Try removal again after signing out and back in."
            fi
            rm -f "$PLIST"
        fi
    else
        UNIT=$HOME/.config/systemd/user/eugene-plexus-agent.service
        if [ -f "$UNIT" ]; then
            grep -F -- "$PREFIX/" "$UNIT" >/dev/null || fail "The startup job belongs to another installation."
            systemctl --user disable --now eugene-plexus-agent || fail 'Could not stop the user service.'
            rm -f "$UNIT"
            systemctl --user daemon-reload || fail 'Could not reload the user service manager.'
        fi
    fi
    # launchd normally terminates the job's process group; also cover a
    # manually started process. Match an executable path, never a regex.
    PIDS=$(ps -axo pid=,comm= | awk -v root="$PREFIX/" '{pid=$1; sub(/^[[:space:]]*[0-9]+[[:space:]]+/, ""); if(index($0,root)==1) print pid}')
    for pid in $PIDS; do kill -TERM "$pid" 2>/dev/null || true; done
    tries=0
    while [ "$tries" -lt 15 ]; do
        alive=0
        for pid in $PIDS; do if kill -0 "$pid" 2>/dev/null; then alive=1; fi; done
        [ "$alive" = 0 ] && break
        sleep 1; tries=$((tries + 1))
    done
    for pid in $PIDS; do
        if kill -0 "$pid" 2>/dev/null; then fail "Eugene process $pid is still running. Close it and run removal again."; fi
    done
    if [ -x "$PYBIN" ]; then
        if "$PYBIN" -I "$PREFIX/uninstall/inventory.py" --keyring-only --prefix "$PREFIX" --output "$RECEIPT/credentials-user.json" 2> "$RECEIPT/credential-warnings.txt"; then
            cat "$RECEIPT/credential-warnings.txt" >> "$WARNINGS"
        else warn 'Credential cleanup failed. Review Eugene entries in Keychain Access or your OS credential store.'; fi
    else warn 'Credential cleanup could not run: the installed Python is missing.'; fi
    if [ "$PLATFORM" = Darwin ]; then
        # Only entries for this install's Python; no shared firewall rules.
        FW=/usr/libexec/ApplicationFirewall/socketfilterfw
        if [ -f "$RECEIPT/firewall.txt" ]; then
            while IFS= read -r program; do
                if "$FW" --listapps 2>/dev/null | grep -F -- "$program" >/dev/null; then
                    if ! /usr/bin/osascript - "$program" <<'APPLE'
on run argv
    do shell script "/usr/libexec/ApplicationFirewall/socketfilterfw --remove " & quoted form of (item 1 of argv) with administrator privileges
end run
APPLE
                    then warn "Firewall entry kept: $program. Remove it in System Settings > Network > Firewall > Options."; fi
                fi
            done < "$RECEIPT/firewall.txt"
        fi
    fi
    cp "$WARNINGS" "$RECEIPT/integration-warnings.txt"
elif [ -s "$RECEIPT/integration-warnings.txt" ]; then
    cat "$RECEIPT/integration-warnings.txt" >> "$WARNINGS"
fi

safe_remove() {
    target=$1 kind=$2
    case "$target" in /*) ;; *) warn "Kept non-absolute path: $target"; return ;; esac
    case "$target" in /|/usr|/var|/opt|/Applications|/Users|/home|"$HOME"|"$PREFIX"|*/../*|*/./*) warn "Kept unsafe path: $target"; return ;; esac
    case "$PREFIX/" in "$target"/*) warn "Kept parent of the installation: $target"; return ;; esac
    if [ "$kind" != downloads ]; then
        case "$target" in "$PREFIX"/*) ;; *) warn "Kept path outside the installation: $target"; return ;; esac
    fi
    cursor=$target
    while [ "$cursor" != / ] && [ -n "$cursor" ]; do
        if [ -L "$cursor" ]; then warn "Kept linked path: $target"; return; fi
        cursor=$(dirname -- "$cursor")
    done
    while IFS= read -r original; do
        protected=$(map_path "$original")
        case "$target/" in "$protected/"*) warn "Kept original model folder: $target"; return ;; esac
        case "$protected/" in "$target/"*) warn "Kept parent of an original model folder: $target"; return ;; esac
    done < "$RECEIPT/protected.txt"
    if ! rm -rf -- "$target"; then warn "Could not remove $target. Check its permissions and run cleanup again."; fi
}
for kind in software downloads data; do
    [ "$kind" = downloads ] && [ "$PURGE_DOWNLOADS" != 1 ] && continue
    [ "$kind" = data ] && [ "$PURGE_DATA" != 1 ] && continue
    while IFS= read -r original; do
        [ -n "$original" ] || continue
        safe_remove "$(map_path "$original")" "$kind"
    done < "$RECEIPT/$kind.txt"
done

KEEP=$PREFIX
if [ ! -f "$RECEIPT/removed.txt" ]; then
    case "$PREFIX" in *.removed-*) ;; *)
        KEEP=$PREFIX.removed-$(date +%Y%m%d%H%M%S)
        [ ! -e "$KEEP" ] || fail "The retained folder already exists: $KEEP"
        mv -- "$PREFIX" "$KEEP" || fail "Could not move the retained files to $KEEP. Check permissions and try again."
        ;;
    esac
fi
PREFIX=$KEEP
RECEIPT=$KEEP/uninstall/receipt
WARNINGS=$RECEIPT/current-warnings.txt
printf '%s\n' 'Startup disabled; see report.txt for remaining work.' > "$RECEIPT/removed.txt"
if [ "$PLATFORM" = Darwin ] && [ -f "$RECEIPT/mac-app.txt" ]; then
    APP=$(cat "$RECEIPT/mac-app.txt")
    case "$APP" in "$HOME/Applications/Remove Eugene Plexus"*.app)
        # Only our own bundle (identified by its exact stored prefix).
        if [ -f "$APP/Contents/Resources/prefix.txt" ] && [ "$(cat "$APP/Contents/Resources/prefix.txt")" = "$ORIGINAL" ]; then rm -rf -- "$APP"; fi ;;
    esac
fi
{
    echo "Eugene's removal finished."
    echo "Retained files and cleanup utility: $KEEP"
    echo 'Original model folders were kept.'
    while IFS= read -r original; do
        path=$(map_path "$original")
        if [ -e "$path" ]; then echo "Retained download: $path"; fi
    done < "$RECEIPT/downloads.txt"
    echo 'To change your cleanup choices, open uninstall/Remove Eugene.command in the retained folder.'
    if [ -s "$WARNINGS" ]; then echo 'Items to review:'; cat "$WARNINGS"; fi
} > "$RECEIPT/report.txt"
cat "$RECEIPT/report.txt"
if [ "$INTERACTIVE" = 1 ] && [ "$PLATFORM" = Darwin ]; then
    /usr/bin/osascript - "$(cat "$RECEIPT/report.txt")" <<'APPLE'
on run argv
    display dialog (item 1 of argv) with title "Eugene removal" buttons {"OK"} default button "OK"
end run
APPLE
fi
[ ! -s "$WARNINGS" ] || exit 1
EUGENE_REMOVAL_REMOVE_SH
    cat > "$PREFIX/uninstall/Remove Eugene.command" <<'EUGENE_REMOVAL_COMMAND'
#!/bin/sh
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec /bin/sh "$HERE/remove.sh" --interactive
EUGENE_REMOVAL_COMMAND
    chmod 700 "$PREFIX/uninstall/Remove Eugene.command" "$PREFIX/uninstall/remove.sh"
}
# END GENERATED OFFLINE REMOVAL

# --- uninstall --------------------------------------------------------

# **Two keyring entries, not one** (review §6.3 #31). The agent stores
# its master key under the service `eugene-plexus-agent` and the control
# root stores the install's signing key under `eugene-plexus-control`,
# each scoped by a fingerprint of that install's master salt (S0). An
# uninstall that leaves them behind leaves two secrets in the OS keyring
# belonging to an install that no longer exists -- and the salt they are
# named after goes into the `.removed-` directory with everything else,
# so after this runs nothing can work out what to delete.
#
# The install's own interpreter is what holds `keyring`, so it is what
# has to be asked; a missing library or a locked backend is a warning,
# never a failure, because an uninstall that refuses to finish is worse
# than one that leaves a credential.
drop_keyring_entries() {
    [ -x "$PYBIN" ] || return 0
    [ -f "$PREFIX/agent.yaml" ] || return 0
    "$PYBIN" - "$PREFIX/agent.yaml" <<'PYEOF' 2>&1 | sed 's/^/  /'
import base64, hashlib, sys

try:
    import keyring
    import yaml
except Exception as exc:  # noqa: BLE001
    print(f"could not open the OS keyring ({exc}); entries left in place")
    raise SystemExit(0)

try:
    doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8").read()) or {}
    salt = ((doc.get("auth") or {}).get("masterSalt")) or ""
except Exception as exc:  # noqa: BLE001
    print(f"could not read agent.yaml ({exc}); keyring entries left in place")
    raise SystemExit(0)

# The scoped username is a fingerprint of the install's master salt --
# `keyring_store.install_id_for`, duplicated here rather than imported
# because the packages may already be gone by the time anyone runs this.
names = ["master-key"]
if salt:
    try:
        names.append("master-key-" + hashlib.sha256(base64.b64decode(salt)).hexdigest()[:12])
    except Exception:  # noqa: BLE001
        pass

removed = 0
for service in ("eugene-plexus-agent", "eugene-plexus-control"):
    for username in names:
        try:
            if keyring.get_password(service, username) is not None:
                keyring.delete_password(service, username)
                print(f"removed the {service} keyring entry")
                removed += 1
        except Exception:  # noqa: BLE001
            pass
if removed == 0:
    print("no keyring entries belonged to this install")
PYEOF
}

# **The node-local model copy directory is ours and is not under the
# prefix** (review §6.3 #31). The agent creates it, fills it with whole
# model files and deletes from it; a Library folder is the operator's
# and is never written to. So this is the one thing an uninstall can
# offer to remove -- and it is offered, not taken, because tens of
# gigabytes is not a thing to delete on somebody's behalf.
# **The engine store is ours too, and it is not under the prefix.** The
# agent downloads llama.cpp builds into `~/.eugene-plexus/engines` (or
# wherever `EUGENE_PLEXUS_AGENT_ENGINE_ROOT` says), keeps two of them,
# and nothing else on the machine writes there. An uninstall that leaves
# it leaves gigabytes nobody will ever attribute to us.
engine_root() {
    printf '%s' "${EUGENE_PLEXUS_AGENT_ENGINE_ROOT:-$HOME/.eugene-plexus/engines}"
}

model_copy_dir() {
    [ -f "$PREFIX/agent.yaml" ] || return 0
    # `yaml.safe_dump` writes a POSIX path as a plain scalar; a quoted
    # form is possible and is the only one that escapes anything.
    sed -n 's/^modelCopyDir:[[:space:]]*//p' "$PREFIX/agent.yaml" | head -1 \
        | sed "s/^['\"]//; s/['\"]$//"
}

if [ "$DO_UNINSTALL" = 1 ]; then
    # What is installed decides, not what the default is now: a per-user
    # install made before 2026-09-24 is uninstalled as one, without sudo.
    if [ "$MODE" = system ] && [ ! -f "$SYSTEM_UNIT" ] \
            && ! id "$SYSTEM_ACCOUNT" >/dev/null 2>&1; then
        MODE=user
        if [ "$PREFIX" = "$SYSTEM_PREFIX" ] && [ -z "${EUGENE_PLEXUS_HOME:-}" ]; then
            PREFIX=$USER_PREFIX
            VENV=$PREFIX/venv
            PYBIN=$VENV/bin/python
        fi
    fi
fi

if [ "$DO_UNINSTALL" = 1 ] && [ "$MODE" = system ]; then
    if [ "$DO_PURGE_DATA" = 1 ] || [ "$DO_INTERACTIVE" = 1 ]; then
        die '--purge-data and --interactive apply to Mac and per-user installs; Linux system removal still preserves its data.'
    fi
    if [ "$(id -u)" != 0 ]; then
        sudo -v || die "removing Eugene's own account needs sudo, and sudo was refused"
    fi
    say "stopping the service"
    service_stop
    as_root systemctl disable --now eugene-plexus-update.path >/dev/null 2>&1 || true
    # Apps are the service manager's, not the agent's: stopped here, or
    # they would outlive the install that started them.
    as_root systemctl disable --now eugene-plexus-apps-ctl.path >/dev/null 2>&1 || true
    as_root systemctl stop 'eugene-plexus-app@*.service' >/dev/null 2>&1 || true
    as_root rm -f "$APPS_TEMPLATE" "$APPS_CTL_SERVICE" "$APPS_CTL_PATH" "$APPS_HELPER"
    as_root sh -c 'rm -rf /etc/systemd/system/eugene-plexus-app@*.service.d'
    # The job-site host, its workers, its program and its account (if any).
    remove_site_host
    as_root rm -f "$SYSTEM_UNIT" "$UPDATE_SERVICE" "$UPDATE_PATH" "$UPDATE_HELPER"
    as_root rm -rf "$UPDATE_STAGE"
    as_root systemctl daemon-reload >/dev/null 2>&1 || true
    if as_root test -d "$PREFIX"; then
        KEEP=$PREFIX.removed-$(date +%Y%m%d%H%M%S)
        as_root mv "$PREFIX" "$KEEP"
        if [ "$DO_PURGE_COPIES" = 1 ]; then
            say "removing the engine builds and model copies this install downloaded"
            as_root rm -rf "$KEEP/engines" "$KEEP/.eugene-plexus"
        fi
        # **Root keeps them, not the account's number.** The account goes
        # next, and files left owned by its uid belong to whichever system
        # account is given that number later -- with this install's
        # signing key and passphrase inside.
        as_root chown -R root:root "$KEEP"
        as_root chmod 0700 "$KEEP"
        say "removed. Its config and logs are at $KEEP (readable by root only) —"
        say "  delete it when you are sure: sudo rm -rf '$KEEP'"
        # With nobody to make a home folder for, the models went under the
        # prefix, so they moved too. Say where, before anyone deletes it.
        if [ -n "$(as_root find "$KEEP/models" -type f 2>/dev/null | head -1)" ]; then
            say "the models that were in $PREFIX/models moved with it, to $KEEP/models"
            say "  (readable by root only). Move them into a new install's models folder."
        fi
    else
        say "nothing installed at $PREFIX"
    fi
    if id "$SYSTEM_ACCOUNT" >/dev/null 2>&1; then
        as_root userdel "$SYSTEM_ACCOUNT" >/dev/null 2>&1 \
            || warn "could not remove the $SYSTEM_ACCOUNT account: sudo userdel $SYSTEM_ACCOUNT"
    fi
    if [ -n "$PERSON_HOME" ] && [ -d "$PERSON_HOME/Eugene Models" ]; then
        say "your models in $PERSON_HOME/Eugene Models are yours, and were not touched"
    fi
    exit 0
fi

if [ "$DO_UNINSTALL" = 1 ]; then
    # Keep the old Linux system-account lifecycle above. Mac and user
    # installations use the same offline utility that Finder launches.
    if [ ! -d "$PREFIX" ] && { [ "$DO_PURGE_COPIES" = 1 ] || [ "$DO_PURGE_DATA" = 1 ]; }; then
        for kept in "$PREFIX".removed-*; do
            [ -f "$kept/uninstall/receipt/inventory.json" ] || continue
            set -- --prefix "$kept"
            [ "$DO_PURGE_COPIES" = 1 ] && set -- "$@" --purge-downloads
            [ "$DO_PURGE_DATA" = 1 ] && set -- "$@" --purge-data
            [ "$DO_INTERACTIVE" = 1 ] && set -- "$@" --interactive
            /bin/sh "$kept/uninstall/remove.sh" "$@" || exit $?
        done
        exit 0
    fi
    if [ ! -d "$PREFIX" ]; then say "nothing installed at $PREFIX"; exit 0; fi
    write_removal_bundle
    set -- --prefix "$PREFIX"
    [ "$DO_PURGE_COPIES" = 1 ] && set -- "$@" --purge-downloads
    [ "$DO_PURGE_DATA" = 1 ] && set -- "$@" --purge-data
    [ "$DO_INTERACTIVE" = 1 ] && set -- "$@" --interactive
    /bin/sh "$PREFIX/uninstall/remove.sh" "$@"
    exit $?
fi

# --- a join takes over whatever Eugene is already here ------------------
# **Someone running a join command with a valid token knows what they are
# doing** (Troy, 2026-09-26). The Windows join took an afternoon of
# refusals, each right on its own terms, so a join no longer asks: it
# stops every Eugene install on this machine, moves each folder aside --
# nothing is deleted -- installs fresh and joins. If anything fails before
# the join succeeds, every install it moved is put back and whatever was
# running is started again, so a bad token leaves the machine as it was.
INSTALLER_URL=https://raw.githubusercontent.com/eugene-plexus/specs/main/scripts/install.sh
SET_ASIDE_STAMP=
SET_ASIDE_LIST=
JOIN_COMMITTED=0
RESTORED=0
FRESH_PREFIX=
ACCOUNT_CREATED=0
SYS_UNIT_BACKUP= SYS_WAS_ACTIVE=0 SYS_WAS_ENABLED=0
USR_UNIT_BACKUP= USR_WAS_ACTIVE=0 USR_WAS_ENABLED=0
PLIST_BACKUP= PLIST_WAS_LOADED=0

# Move one folder aside, as root for the system layout.
set_aside_one() {
    _aside="$2.replaced-$SET_ASIDE_STAMP"
    if [ "$1" = root ]; then as_root mv "$2" "$_aside"; else mv "$2" "$_aside"; fi \
        || die "could not move $2 aside.
       Close anything using that folder, then run this again."
    SET_ASIDE_LIST="$SET_ASIDE_LIST$1|$2|$_aside
"
    say "set aside the install at $2; nothing deleted"
    echo "    it is now at $_aside"
}

take_over_existing() {
    # A per-user install belonging to someone else, when this runs as root:
    # its service is theirs to stop, so say so before touching anything.
    _person_prefix=${PERSON_HOME:-/nonexistent}/.local/share/eugene-plexus
    _person_unit=${PERSON_HOME:-/nonexistent}/.config/systemd/user/$SERVICE_LABEL.service
    if [ "$(id -u)" = 0 ] && [ -n "$PERSON" ] \
            && { [ -f "$_person_unit" ] || [ -d "$_person_prefix" ]; }; then
        die "Eugene is also installed under $PERSON's own account. Run this join as
       $PERSON (without sudo), so that install can be stopped and moved aside too."
    fi
    SET_ASIDE_STAMP=$(date +%Y%m%d%H%M%S)
    if [ "$PLATFORM" = linux ] && { [ -f "$SYSTEM_UNIT" ] || [ -d "$SYSTEM_PREFIX" ]; }; then
        if [ "$(id -u)" != 0 ]; then
            say "Eugene is already installed here under its own account; moving it aside needs sudo"
            sudo -v || die "sudo was refused, so the install that is here was left as it is."
        fi
        if [ -f "$SYSTEM_UNIT" ]; then
            SYS_UNIT_BACKUP=$(mktemp "${TMPDIR:-/tmp}/eugene-plexus-unit.XXXXXX")
            cp "$SYSTEM_UNIT" "$SYS_UNIT_BACKUP"
            if as_root systemctl is-active --quiet "$SERVICE_LABEL"; then SYS_WAS_ACTIVE=1; fi
            if as_root systemctl is-enabled --quiet "$SERVICE_LABEL" 2>/dev/null; then SYS_WAS_ENABLED=1; fi
            say "stopping the $SERVICE_LABEL service"
            as_root systemctl stop "$SERVICE_LABEL" >/dev/null 2>&1 || true
            as_root systemctl disable "$SERVICE_LABEL" >/dev/null 2>&1 || true
            as_root rm -f "$SYSTEM_UNIT"
            as_root systemctl daemon-reload >/dev/null 2>&1 || true
        fi
        if [ -d "$SYSTEM_PREFIX" ]; then set_aside_one root "$SYSTEM_PREFIX"; fi
    fi
    if [ "$PLATFORM" = linux ] && [ -f "$SYSTEMD_UNIT" ]; then
        USR_UNIT_BACKUP=$(mktemp "${TMPDIR:-/tmp}/eugene-plexus-unit.XXXXXX")
        cp "$SYSTEMD_UNIT" "$USR_UNIT_BACKUP"
        if systemctl --user is-active --quiet "$SERVICE_LABEL" 2>/dev/null; then USR_WAS_ACTIVE=1; fi
        if systemctl --user is-enabled --quiet "$SERVICE_LABEL" 2>/dev/null; then USR_WAS_ENABLED=1; fi
        say "stopping your $SERVICE_LABEL service"
        systemctl --user stop "$SERVICE_LABEL" >/dev/null 2>&1 || true
        systemctl --user disable "$SERVICE_LABEL" >/dev/null 2>&1 || true
        rm -f "$SYSTEMD_UNIT"
        systemctl --user daemon-reload >/dev/null 2>&1 || true
    fi
    if [ "$PLATFORM" = macos ] && [ -f "$LAUNCHD_PLIST" ]; then
        PLIST_BACKUP=$(mktemp "${TMPDIR:-/tmp}/eugene-plexus-plist.XXXXXX")
        cp "$LAUNCHD_PLIST" "$PLIST_BACKUP"
        if launchctl print "gui/$(id -u)/$LAUNCHD_LABEL" >/dev/null 2>&1; then PLIST_WAS_LOADED=1; fi
        launchctl bootout "gui/$(id -u)/$LAUNCHD_LABEL" >/dev/null 2>&1 || true
        rm -f "$LAUNCHD_PLIST"
    fi
    if [ -d "$USER_PREFIX" ]; then set_aside_one self "$USER_PREFIX"; fi
    # The target itself, when it is somewhere else and holds anything.
    if [ -d "$PREFIX" ]; then
        if [ -n "$(ls -A "$PREFIX" 2>/dev/null || as_root ls -A "$PREFIX" 2>/dev/null)" ]; then
            if [ "$MODE" = system ]; then set_aside_one root "$PREFIX"; else set_aside_one self "$PREFIX"; fi
        else
            if [ "$MODE" = system ]; then as_root rmdir "$PREFIX"; else rmdir "$PREFIX"; fi
        fi
    fi
    # Only a folder this run makes is ever removed again.
    [ -e "$PREFIX" ] || FRESH_PREFIX=$PREFIX
}

# Put the machine back as take_over_existing found it. Never fails; what
# it could not do, it says, with where the files are.
restore_existing() {
    [ -n "$SET_ASIDE_STAMP" ] || return 0
    [ "$RESTORED" = 0 ] || return 0
    RESTORED=1
    case "$FRESH_PREFIX" in
        ""|/) : ;;
        *)
            if [ "$MODE" = system ]; then as_root rm -rf "$FRESH_PREFIX" || true
            else rm -rf "$FRESH_PREFIX" || true; fi ;;
    esac
    if [ "$ACCOUNT_CREATED" = 1 ]; then as_root userdel "$SYSTEM_ACCOUNT" >/dev/null 2>&1 || true; fi
    printf '%s' "$SET_ASIDE_LIST" | awk '{ lines[NR] = $0 } END { for (i = NR; i > 0; i--) print lines[i] }' |
    while IFS='|' read -r _kind _path _aside; do
        [ -n "$_path" ] || continue
        if [ -e "$_path" ]; then
            warn "$_path exists again, so the old install was left at $_aside"
        elif { if [ "$_kind" = root ]; then as_root mv "$_aside" "$_path"; else mv "$_aside" "$_path"; fi; }; then
            say "put back the Eugene install at $_path"
        else
            warn "could not move $_aside back to $_path"
        fi
    done
    if [ -n "$SYS_UNIT_BACKUP" ]; then
        as_root cp "$SYS_UNIT_BACKUP" "$SYSTEM_UNIT" && rm -f "$SYS_UNIT_BACKUP" || warn "could not restore $SYSTEM_UNIT"
        as_root systemctl daemon-reload >/dev/null 2>&1 || true
        if [ "$SYS_WAS_ENABLED" = 1 ]; then as_root systemctl enable "$SERVICE_LABEL" >/dev/null 2>&1 || true; fi
        if [ "$SYS_WAS_ACTIVE" = 1 ]; then
            if as_root systemctl start "$SERVICE_LABEL"; then say "the $SERVICE_LABEL service is running again"
            else warn "could not start the $SERVICE_LABEL service again: sudo systemctl start $SERVICE_LABEL"; fi
        fi
    fi
    if [ -n "$USR_UNIT_BACKUP" ]; then
        mkdir -p "$(dirname "$SYSTEMD_UNIT")"
        cp "$USR_UNIT_BACKUP" "$SYSTEMD_UNIT" && rm -f "$USR_UNIT_BACKUP" || warn "could not restore $SYSTEMD_UNIT"
        systemctl --user daemon-reload >/dev/null 2>&1 || true
        if [ "$USR_WAS_ENABLED" = 1 ]; then systemctl --user enable "$SERVICE_LABEL" >/dev/null 2>&1 || true; fi
        if [ "$USR_WAS_ACTIVE" = 1 ]; then systemctl --user start "$SERVICE_LABEL" || warn "could not start your $SERVICE_LABEL service again"; fi
    fi
    if [ -n "$PLIST_BACKUP" ]; then
        cp "$PLIST_BACKUP" "$LAUNCHD_PLIST" && rm -f "$PLIST_BACKUP" || warn "could not restore $LAUNCHD_PLIST"
        if [ "$PLIST_WAS_LOADED" = 1 ]; then launchctl bootstrap "gui/$(id -u)" "$LAUNCHD_PLIST" >/dev/null 2>&1 || true; fi
    fi
}

# Whatever stops this run after installs were set aside and before the
# join succeeded -- a refusal, a failed download, an interrupt -- puts them
# back. `die` exits, and so does `run_step`, so this is the one place.
on_exit() {
    _code=$?
    # A password was being typed: give the terminal its echo back.
    if [ -n "$TTY_SAVED" ]; then stty "$TTY_SAVED" </dev/tty 2>/dev/null || true; fi
    if [ "$_code" != 0 ] && [ -n "$SET_ASIDE_STAMP" ] && [ "$JOIN_COMMITTED" = 0 ] && [ "$RESTORED" = 0 ]; then
        restore_existing
        printf '       This machine is back as it was.\n' >&2
    fi
}
trap on_exit EXIT
trap 'exit 130' INT TERM

# --- a job site on this node ---------------------------------------------
# A job site is its own enrollment (job-sites-own-enrollment.md, J19), added
# to a machine that is already a node without reinstalling or re-joining it
# (J35). A machine that is only a job site waits for the standalone install
# (J21). The site host makes the site's key itself; this script never sees
# the owner's password, which the agent's `site join` asks for at the
# terminal.
#
# **On a Linux system install (2b.2) root does all of it** -- see "a job site
# on a Linux system install" above: root installs the site host's program,
# runs the site host's own `join` as its own account, and makes the links. The
# agent there is unprivileged and `site join` through it would run agent code
# the `eugene-plexus` account owns, as root. A per-user install has no
# privilege to separate: the agent's own `site join` runs as this user and
# links the owner to this account itself, and the site serves only them (J38).
if [ -n "$SITE_ACTION" ] && { [ "$JOIN_SITE" = 1 ] || [ "$UPDATE" = 1 ] || [ -n "$JOIN_CONTROL" ]; }; then
    die "--site-link, --site-unlink and --site-pair are run on their own, not with --job-site, --join or --update"
fi
if [ "$SITE_ACTION" = link ]; then
    site_link_person
    exit 0
elif [ "$SITE_ACTION" = unlink ]; then
    site_unlink_person
    exit 0
elif [ "$SITE_ACTION" = pair ]; then
    site_passkey_command "--site-pair" pair || die "no passkey was paired (see above)"
    exit 0
elif [ "$SITE_ACTION" = passkeys ]; then
    site_passkey_command "--site-passkeys" passkeys || die "the passkeys could not be listed (see above)"
    exit 0
elif [ "$SITE_ACTION" = unpair ]; then
    case "$SITE_PASSKEY" in
        ''|*[!0-9a-f]*) die "--site-unpair needs a passkey's id (--site-passkeys lists them)" ;;
    esac
    site_passkey_command "--site-unpair" passkeys --remove "$SITE_PASSKEY" \
        || die "the passkey was not removed (see above)"
    exit 0
fi

if [ "$JOIN_SITE" = 1 ]; then
    if [ -z "$JOIN_CONTROL" ] || [ -z "$JOIN_TOKEN" ] || [ -z "$JOIN_OWNER" ]; then
        die "a job site's join command gives --join, --token and --owner (copy the whole command from Workbench)"
    fi
    if [ "$MODE" = system ]; then
        site_join_system
        exit 0
    fi
    [ "$PLATFORM" = linux ] || [ "$PLATFORM" = macos ] || die "this installer adds job sites on Linux and macOS"
    [ -x "$VENV/bin/eugene-plexus-agent" ] || die "this machine is not a node yet.
       Install Eugene here and join it to your install first, then run this
       again. A machine that is only a job site waits for the standalone install."
    SITE_LABEL=${JOIN_NAME:-$(hostname)}
    set -- site join --url "$JOIN_CONTROL" --token "$JOIN_TOKEN" --owner "$JOIN_OWNER" --label "$SITE_LABEL"
    if [ -n "$JOIN_ROOT_KEY" ]; then set -- "$@" --root-key "$JOIN_ROOT_KEY"; fi
    if [ -n "$SITE_LINK_ACCOUNT" ]; then set -- "$@" --site-account "$SITE_LINK_ACCOUNT"; fi
    say "adding $SITE_LABEL as a job site of $JOIN_OWNER (it serves only you; tools run as you)"
    env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$CONFIG" "$VENV/bin/eugene-plexus-agent" "$@" \
        || die "the job site was not added (see above). Nothing else on this machine changed."
    say "done: $SITE_LABEL is a job site of $JOIN_OWNER. Its owner manages it from Workbench (Job sites)."
    exit 0
fi

if [ -n "$JOIN_CONTROL" ]; then
    [ -n "$JOIN_TOKEN" ] || die "--join needs --token (mint one at the control root: Nodes -> Add a node)"
    take_over_existing
fi

# --- one install per machine --------------------------------------------
# **Two installs on one machine are two trust roots**, and the second one
# strands everything the first enrolled (R2.6 found this on Windows, where
# following our own advice produced one). Both layouts want port 8079 and
# the same service name, so each refuses to start beside the other and
# says how to update the one that is there.
PERSON_USER_PREFIX=${PERSON_HOME:-$HOME}/.local/share/eugene-plexus
PERSON_USER_UNIT=${PERSON_HOME:-$HOME}/.config/systemd/user/$SERVICE_LABEL.service
if [ "$MODE" = system ] \
        && { [ -f "$PERSON_USER_UNIT" ] || [ -f "$PERSON_USER_PREFIX/agent.yaml" ]; }; then
    die "this machine already has Eugene installed under your own account, at
    $PERSON_USER_PREFIX
  Installing it again under its own account would put a second install beside it.
  To update the one that is there:  re-run with --user
  To move to the safer layout: uninstall it first (--user --uninstall keeps its files),
  then re-run without --user. Moving an install across is not built yet, so the
  machine then starts as a new install and any machines joined to it join again."
fi
if [ "$MODE" = user ] && [ "$DO_SERVICE" = 1 ] && [ -f "$SYSTEM_UNIT" ]; then
    die "this machine already has Eugene installed under its own account (the
  $SERVICE_LABEL system service, in $SYSTEM_PREFIX). Re-run without --user to update it."
fi

# --- 0. Eugene's own account (the default on Linux) ----------------------
if [ "$MODE" = system ]; then
    [ -d /run/systemd/system ] || die "this machine is not running systemd, so Eugene cannot run as a
  service under its own account here. Re-run with --user to install it under your own
  account instead (anything you run can then control Eugene), or with --no-service
  to start it yourself."
    if [ "$(id -u)" != 0 ]; then
        command -v sudo >/dev/null 2>&1 || die "Eugene runs under its own account, and setting that up
  needs root, but sudo is not installed. Run this as root, or re-run with --user."
        say "Eugene will run under its own account, $SYSTEM_ACCOUNT, so the programs you run"
        say "  cannot read its keys. Setting that up needs sudo, once."
        sudo -v || die "sudo was refused. Re-run with --user to install Eugene under your own
  account instead, without sudo."
    fi
    if ! id "$SYSTEM_ACCOUNT" >/dev/null 2>&1; then
        say "creating the $SYSTEM_ACCOUNT account"
        NOLOGIN=/usr/sbin/nologin
        [ -x "$NOLOGIN" ] || NOLOGIN=/sbin/nologin
        [ -x "$NOLOGIN" ] || NOLOGIN=/bin/false
        as_root useradd --system --user-group --home-dir "$PREFIX" --no-create-home \
            --shell "$NOLOGIN" "$SYSTEM_ACCOUNT" \
            || die "could not create the $SYSTEM_ACCOUNT account"
        ACCOUNT_CREATED=1
    fi
    # 0750: Eugene's account, and nobody but root, can look inside -- which
    # is the whole point. Applied on every run, so a prefix somebody opened
    # up by hand is closed again.
    as_root install -d -m 0750 -o "$SYSTEM_ACCOUNT" -g "$SYSTEM_ACCOUNT" \
        "$PREFIX" "$PREFIX/bin" "$PREFIX/logs"
fi

# **An install from alpha.2 or earlier cannot be upgraded, and says so**
# (Troy, 2026-09-26: alpha.3 requires a fresh install). Per-node token
# keys deleted the install-wide signing key rather than converting it, so
# an old install upgraded in place does not come back, and sign-in blames
# the network. The marker is the old key: node.yaml held `signingKey:`,
# and nothing written since does. A join never gets here with one: it set
# the old install aside above.
if [ -z "$JOIN_CONTROL" ] && in_prefix grep -q '^signingKey:' "$PREFIX/node.yaml" 2>/dev/null; then
    die "the Eugene install at $PREFIX
       is from alpha.2 or earlier, and this version cannot upgrade it: how
       machines prove who they are changed, and the old keys do not carry
       over. Start fresh: remove it (its files are kept, moved aside), then
       run this command again.
         curl -fsSL $INSTALLER_URL | sh -s -- --uninstall
       No model file is deleted. Any in its own models folder move aside
       with it; the uninstall says where, so you can move them into the new
       install's. You will choose a new passphrase, and machines that were
       joined to it will need to join again."
fi

# --- 1. uv ------------------------------------------------------------
say "installing into $PREFIX"
[ "$MODE" = system ] || mkdir -p "$PREFIX/bin" "$PREFIX/logs"

# **An install kept the uv it was first made with, forever** (found
# 2026-10-03, the upstream drift audit). This step skipped the download
# whenever a uv was there, and the app's updates re-run this script, so
# nothing ever replaced one. A uv older than UV_MINIMUM, or one that cannot
# say its version, is fetched again by the same official installer, over
# the old one; one new enough is left alone, exactly as before. Not
# `uv self update`: UV_UNMANAGED_INSTALL, which keeps uv inside the prefix,
# also turns uv's self-updater off (its installer writes no receipt, and
# self update refuses a uv without one).
UV_FETCH="fetching uv"
if in_prefix test -x "$UV"; then
    UV_HAVE=$(uv_version)
    if [ -z "$UV_HAVE" ]; then
        UV_FETCH="the uv at $UV does not say its version; fetching uv again"
    elif version_older "$UV_HAVE" "$UV_MINIMUM"; then
        UV_FETCH="uv $UV_HAVE is older than $UV_MINIMUM, the oldest this installer keeps (GHSA-2cv4-cqwr-gwf7); fetching a newer one"
    else
        UV_FETCH=
    fi
fi

if [ -z "$UV_FETCH" ]; then
    say "uv already present ($(in_prefix "$UV" --version))"
elif [ "$MODE" = system ]; then
    say "$UV_FETCH"
    command -v curl >/dev/null 2>&1 || die "curl is required"
    # Fetched as this shell and run as Eugene's account, which cannot read
    # a file this shell's umask made private -- hence the chmod.
    UV_BOOTSTRAP=$(mktemp "${TMPDIR:-/tmp}/uv-install.XXXXXX")
    UV_FETCH_ERR=$(mktemp "${TMPDIR:-/tmp}/uv-fetch.XXXXXX")
    if ! curl -fsSL -o "$UV_BOOTSTRAP" https://astral.sh/uv/install.sh 2>"$UV_FETCH_ERR"; then
        printf '\033[31merror:\033[0m could not fetch https://astral.sh/uv/install.sh\n' >&2
        sed 's/^/  /' "$UV_FETCH_ERR" >&2
        printf '  A proxy that intercepts TLS is the usual cause. Set HTTPS_PROXY.\n' >&2
        rm -f "$UV_BOOTSTRAP" "$UV_FETCH_ERR"
        exit 1
    fi
    chmod 0644 "$UV_BOOTSTRAP"
    run_step "installing uv from https://astral.sh/uv/install.sh" \
        as_service env UV_UNMANAGED_INSTALL="$PREFIX/bin" sh "$UV_BOOTSTRAP"
    rm -f "$UV_BOOTSTRAP" "$UV_FETCH_ERR"
    as_service test -x "$UV" || die "uv did not land at $UV"
    say "uv $(as_service "$UV" --version | cut -d' ' -f2)"
else
    say "$UV_FETCH"
    command -v curl >/dev/null 2>&1 || die "curl is required"
    # UV_UNMANAGED_INSTALL puts uv exactly here and edits no shell
    # profile and no PATH. The installer owns its own copy, so nothing
    # the user already has is touched and `rm -rf $PREFIX` is complete.
    # **`sh -c "$(curl ...)"` cannot fail** (review §6.2 #24). When curl
    # exits non-zero the command substitution is empty, `sh -c ""` exits
    # 0, and the `|| die` naming the URL never fires -- the run died one
    # line later on "uv did not land at ...", a true sentence about the
    # wrong subject. Fetch to a file, check curl, then run the file.
    UV_BOOTSTRAP=$PREFIX/bin/uv-install.sh
    mkdir -p "$PREFIX/logs"
    if ! curl -fsSL -o "$UV_BOOTSTRAP" https://astral.sh/uv/install.sh \
            2>"$PREFIX/logs/uv-fetch.err"; then
        printf '\033[31merror:\033[0m could not fetch https://astral.sh/uv/install.sh\n' >&2
        sed 's/^/  /' "$PREFIX/logs/uv-fetch.err" >&2
        printf '  A proxy that intercepts TLS is the usual cause. Set HTTPS_PROXY, or\n' >&2
        printf '  install uv yourself and put it at %s.\n' "$UV" >&2
        exit 1
    fi
    UV_UNMANAGED_INSTALL="$PREFIX/bin" \
        run_step "installing uv from https://astral.sh/uv/install.sh" sh "$UV_BOOTSTRAP"
    rm -f "$UV_BOOTSTRAP"
    [ -x "$UV" ] || die "uv did not land at $UV"
    say "uv $("$UV" --version | cut -d' ' -f2)"
fi
# Said rather than assumed: a replacement that did not happen (a uv
# another program was running, say) leaves the old one in place.
if [ -n "$UV_FETCH" ]; then
    UV_HAVE=$(uv_version)
    if [ -z "$UV_HAVE" ] || version_older "$UV_HAVE" "$UV_MINIMUM"; then
        die "the uv at $UV is ${UV_HAVE:-one that does not say its version} after fetching it
       again, and this installer needs $UV_MINIMUM or newer. Stop anything using it, or
       put a uv $UV_MINIMUM or newer there yourself, then run this again."
    fi
fi

# Keep uv's downloaded interpreters inside the prefix too, for the same
# reason: one directory to remove.
UV_PYTHON_INSTALL_DIR=$PREFIX/pythons
export UV_PYTHON_INSTALL_DIR

# --- 2. venv ----------------------------------------------------------
if in_prefix test -x "$PYBIN"; then
    say "virtualenv already present"
else
    say "creating a Python $PY_VERSION virtualenv (uv downloads the interpreter; none is required on this machine)"
    # `only-managed` rather than uv's default, which prefers a matching
    # interpreter already on the machine. Preferring one would make the
    # sentence above false wherever it is true -- and it would tie the
    # install to a Python the user can upgrade or remove out from under
    # it, which contradicts "removing the prefix is complete".
    run_step "creating a Python $PY_VERSION virtualenv at $VENV" \
        in_prefix "$UV" venv --python "$PY_REQUEST" --python-preference only-managed "$VENV"
    in_prefix test -x "$PYBIN" || die "uv reported success but there is no interpreter at $PYBIN"
fi

if [ "$NATIVE_APPLE" = 1 ]; then
    PY_ARCH=$("$PYBIN" -c 'import platform; print(platform.machine())') \
        || die "could not inspect the Python interpreter at $PYBIN; nothing was installed into it"
    case "$PY_ARCH" in
        arm64|aarch64) : ;;
        *) die "Python at $VENV reports '$PY_ARCH' on Apple Silicon. Native arm64 Python is required for Metal. Stop this install, rename only '$VENV' to a backup, then re-run this installer. Your config and model files are unchanged." ;;
    esac
fi

# --- 3. packages ------------------------------------------------------
if in_prefix test -f "$PREFIX/agent.yaml"; then
    warn "Before updating an initialized install, keep a stopped-install checkpoint: https://github.com/eugene-plexus/specs/blob/main/docs/recovery.md"
    warn "Rollback restores matching software AND state; installing an older release does not undo data migrations."
fi
gh_archive() { printf 'https://github.com/eugene-plexus/%s/archive/%s.tar.gz' "$1" "$2"; }

# BEGIN GENERATED DEPENDENCIES
in_prefix "$PYBIN" -c 'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.stdin.read(), encoding="utf-8", newline="\n")' "$PREFIX/release-requirements.lock" <<'EUGENE_REQUIREMENTS'
annotated-doc==0.0.5 \
    --hash=sha256:117bac03a25ede5df5440e855b32d556049ca169ead221505badf432fed4b101 \
    --hash=sha256:c7e58ce09192557605d8bbd92836d7e1d520ac9580096042c0bfd197efacf1bb
annotated-types==0.8.0 \
    --hash=sha256:13b2beaad985e05e2d6407ee4c4f35590b11f8d693a258a561055cac8f64cab7 \
    --hash=sha256:f072f4d804ea359e4eaf198b1af7a8b0943881a87f31bb764f8bf219bb9419e0
anyio==4.15.1 \
    --hash=sha256:6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101 \
    --hash=sha256:9f28306018cbd6d329e64a36d58256edff76dd996fe423bc957326e578b82a94
argon2-cffi==23.1.0 \
    --hash=sha256:879c3e79a2729ce768ebb7d36d4609e3a78a4ca2ec3a9f12286ca057e3d0db08 \
    --hash=sha256:c670642b78ba29641818ab2e68bd4e6a78ba53b7eff7b4c3815ae16abf91c7ea
argon2-cffi-bindings==26.1.0 \
    --hash=sha256:061a6919145bbf282ebf1f9c59d3135d4833c25313c8595c0d68cf7712ddfce2 \
    --hash=sha256:0cc40f7b4050bb93eb67de95d2d759322fc7ce4930b9d645581ecf4913ec651e \
    --hash=sha256:151dfaad9de753f4af2a7854e707e4784f2acc434340ade64239c5b104b2d605 \
    --hash=sha256:19423e5d7ac1cc354baab59eaabf18db2ec04ef6593b5abe5a34f323c4a8f87a \
    --hash=sha256:19b562b1de4b9052ef1214a2821c44b6e6f22945daa102c32ae4eff929d8b6d8 \
    --hash=sha256:1a0a29ed86960e44eaace7e081bdfab4f08b012fd96ec8edba71e2ad020939e4 \
    --hash=sha256:1af817e84578ef8b7295ad17de0f9896e4c8520dbf2233c7aa5aa3d487256fc4 \
    --hash=sha256:1b0bcac4d490a237e18cf91f57352920c29f77f2fa39efd0813fb81298bf17ba \
    --hash=sha256:1d98e33bd8bd67d7206c124e200bf2229c4cfa8c9c19f7b44a897f0fc71837eb \
    --hash=sha256:21ca0396fe5ec995dd54431c32698189666f9224810acfa752e50d2bd94d9df2 \
    --hash=sha256:224865cbbcb7a2bd1356741dff12b0134df726b6d44bb7b500df8e303cbd9e81 \
    --hash=sha256:242bb0cda2ae3650764fc194593d9ea45fc9e72729acd89778c7cfe184cec2a5 \
    --hash=sha256:27f1821903e2ceadcb88ec2b45ef190897b7682449c772f4d9b53e42c520cf29 \
    --hash=sha256:28524438cd3e723f25412f63d4fd516ff5bae9ae5aa56acbe2a1404398a0cf31 \
    --hash=sha256:2b741888c93147444fdfc851abd81cc207f37f7f7da42062a00deb3888e57da8 \
    --hash=sha256:2c36ff87b5dfaa477d0bd51e9d7f6abdae7c8955d2983c97419085d842154b3e \
    --hash=sha256:34b7d9c24a4165a2c61cc8ae11d44d48c9ce2830fb536cb7914e11fdd9962728 \
    --hash=sha256:49d525938467d52c923a890153c99087c9d5a937d1f6b585dbdba34ec82e397a \
    --hash=sha256:4f84cdd868978d7b7350a566c254042d44216d9e37f241f3a6d3b1dfebeede35 \
    --hash=sha256:62ff20cd130c956c7c9144d5fe35228f98b51c579b2439e988b27ef93e16c02a \
    --hash=sha256:63505c71542a44b68b1e38060450fb006404170da375feb31af153e7f9c6205d \
    --hash=sha256:6376d4b3aca039375ca8bf92f770da0ec424a1ce3a37077a8d3c557411aa56ca \
    --hash=sha256:6a4e68eed961a8de6928d1c17ff3dc2a547e0e923c17f8f1cd79fb7bc9502f98 \
    --hash=sha256:6ab674f668d5962a3a4136ae0812519b0f1586874263723a32181d60d64137e1 \
    --hash=sha256:7014ab7e6f5d8511af92544667a0346ea6dfc314ea9a7cad1dba9fdb5c9a6e33 \
    --hash=sha256:76ae29acace5d33355344612844d588e19deaaba4639d8bb01601e4b1418ef36 \
    --hash=sha256:78de2d65e0b9ea7ce9d1b1c3e87297b2d7305a02c266ee2a2d6910daddd7ee69 \
    --hash=sha256:9bacedc04b0402837586a17f0919e3dfdd95291f441f1f56bd80ec274c2840a1 \
    --hash=sha256:a86c069c91a747a2c4e5c51473590aeb48172fff9b2130d23729a42d98665ecb \
    --hash=sha256:ac82fc756a446b6ccd7139ce70efa9d8bbe541e7ad579a12dcb52764b7175c5f \
    --hash=sha256:af11ac37a7c53dc16cb7950a6190851b0870fe218b6c60c0bb7ac355234e3083 \
    --hash=sha256:b70225b5fd1e0d2ef4f7fd30d24658454535f0924dff0caca5dc08efbbbadfbb \
    --hash=sha256:c49e853a3bef9dd10329f31f702e7fa9b5c58229ff9c2ff6d069efaf09177c08 \
    --hash=sha256:ccaf0a46cbb380f1fd102a874e32aa629fd3cb0c0e94f4943fa1f6d5edc5dac6 \
    --hash=sha256:d157ddfab1e8b21f2f1dedda9c09645d98b5ed0b667b0626be600a345d426440 \
    --hash=sha256:d88e5f7e60f28ae0b0cc6b2f16c43e87cd642a196a86f85e0d8bb6fe016fc16d \
    --hash=sha256:db0fcd827ca61622a01b220aadfbece01939acf53888f2cb98cd93e9b1e2c97e \
    --hash=sha256:df612391feca41c44d20118f3b88d1b86419465cd1f5496859f715ca60ec2210 \
    --hash=sha256:f0c3103fcff20183e593459cfea6e012281c0e76ae3ed8b5565ad1b92eac3990 \
    --hash=sha256:f9c4420a7a864fe1b86ce35befc95b8e39fb852493b81cf798671ddc265de638 \
    --hash=sha256:ffff613aaa9ce6236766e2fc6dc560bb5abde7a2e2416e3db1f9ae395a2b4dd4
attrs==26.1.0 \
    --hash=sha256:c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309 \
    --hash=sha256:d03ceb89cb322a8fd706d4fb91940737b6642aa36998fe130a9bc96c985eff32
authlib==1.8.0 \
    --hash=sha256:88aebbd9af6757e14e912d5dc007ae1dc1f3e27e3b2152ce7c552ee2c3b3c121 \
    --hash=sha256:f3ecd5f1da737262fb53bf1a4d95c4ea1ad9dd509316587a255c99ab1838a4f0
certifi==2026.7.22 \
    --hash=sha256:62f22742b58a1a33014a2b6b706588a8d7e2a88ae7bd1a6ebe8c992928483775 \
    --hash=sha256:741e2c3b351ddf169a738da9f2c048608ff7f2c5cc02f1ebc6b118bb090d5d55
cffi==2.1.1 \
    --hash=sha256:046bfc24911b37851ee1b51aab8bffe713d89c68c6a057b09484ce9fd5f69b4e \
    --hash=sha256:06c72bb76605a4b0cd0aad6930b69d4baf7dd5d806cfc409b824191099700e66 \
    --hash=sha256:0beceaabe56af686895136a2de78db54ecd8e4046b236b8fd6d6cb61389e9bf2 \
    --hash=sha256:154852545011f779917b11c78db2358d095da62a9a172b78ad0a583ee5adc0d0 \
    --hash=sha256:194cffa889098ced9976c3fc6340305e43f6303657d298da55366907c05c22d6 \
    --hash=sha256:19ee6127ee34de7d83ce3d371ebc5ed91addbdcc39f9ab15ce4eb35a4e534971 \
    --hash=sha256:1a18a57b58cfb21fc28d72e876acf10eaed67a1ed96226f92af4df681d571c4c \
    --hash=sha256:1aa5645c30469b09530c4ebca77ebf8f17618293c58f8549cb1a543a50236e7d \
    --hash=sha256:1dea0e4d7d4f11f619fe8c1d76caf49e24405b4b5743c0e3be16a500ecd930c9 \
    --hash=sha256:208f941bb9d18e768138677f0a6d2ce01f590df56043dda1df1535ac57c88517 \
    --hash=sha256:210019b6c7cf07f081b4c54635c8cf744377001350e29cc0f81c4377b4797735 \
    --hash=sha256:246fa40ce8645a614ff682e0b70f37134e460eaf93a775e0cbe3cca585a67a80 \
    --hash=sha256:25792eac27877609e7bb06d42ff88278a6624fff2ba9bbb523c09616b117e80f \
    --hash=sha256:27350daa11d4f10c540e6e89dada4c54feb7256ad03e9a4dc075ebad7ba360d1 \
    --hash=sha256:28907ab9bfb6aa13184cfc17c6b8e1023c5ab6fd7076d8c20a35e59fe04f8f29 \
    --hash=sha256:2ae64be792b8966f2c69538199728b290e34726562896df1e5dc8ffd8d8188e8 \
    --hash=sha256:31348097ff5bbe827ccc41795d4dd099d9f0625e7def00ee653c137a490c2a6c \
    --hash=sha256:3143d81e29e1e20a9ce10901ec369012947876596f75a222235965f2b7ae832e \
    --hash=sha256:3222ba5d678f80a030e6afbcc33dc1ae5cb45facabb61cee2c7016b8432fde48 \
    --hash=sha256:3311ed60d36f83378794e1009ac6258bafbf81f7888b4caa7b35a521e3f95813 \
    --hash=sha256:334644fbac4eff73d985a17a91226df55d0f394160c4cfb880e084c8f7161cac \
    --hash=sha256:34e261f78cb6ceaaa36f42f2613f4380d94d9c759a9c73c769ee6e0247364632 \
    --hash=sha256:363e05fa78e15116c3c32c210ee36884fd6b9afa6d440e47112c3bd511d64cb6 \
    --hash=sha256:398aff33cee2767e3e781d2554c54bd0dff386bb437581e0d8011fde1a942ec1 \
    --hash=sha256:3d22a20b1fb1632cc72c22f95f7b0d2961c3e1c235f245ba4c606c4771035659 \
    --hash=sha256:42a494cee34437f05546455144f2b5d9ac09b1face62bcfce597d2e521066688 \
    --hash=sha256:42e2f76b9455f5a9a844f770bf3e200ed3da0e15f5df3db9c31fe80b04b3d004 \
    --hash=sha256:42f6930c31dc7f50732c9ae793c2786c7b6b044195967bbdde40bb9be81c4cc0 \
    --hash=sha256:456a61fa52d579ebf9df2e9552ead5129855dbaff6c1e5a9b1bc408809bdc062 \
    --hash=sha256:471cee653ae88de62096552e6d24ccb4a5adb8c8c9f10b5054d0122c15bf2779 \
    --hash=sha256:49cbc70e6542d4ccccb936558d1064a8012541e78f821f955cff24e357776c94 \
    --hash=sha256:4a7c934f7360e8cd64fe9efadcbd10c7c6364f531e432b9a4bf5ccbc9e0e8b50 \
    --hash=sha256:4be96343e422f2dfcd12ab5c9f5aebe03f82f737c6bffeca6830b3875cb44aab \
    --hash=sha256:4f42141fc14250de6dde5ee7ea4432be017252d91f19c5ad043c084cea629cac \
    --hash=sha256:507a24c282e0f42f8ed737cf048572cbf580468da5555764a8331735e9c736b6 \
    --hash=sha256:51b31d1c98274844cfd7838ce00bfc27c7423a4dc00fc0772fc3331c2cc90676 \
    --hash=sha256:58acb8ab8e295e6c5ea12f888cbb13cf21511ef2a3303a23f4325c29d17fe5c1 \
    --hash=sha256:5a59cc1c4442bc3d5c703bf720b51138d0bfc173618807c9ee2490a7541dd3d9 \
    --hash=sha256:5bb4e7ea95dcd6a014a6fef62e62467d67d8e582326443f3d68e71d6320a9fcf \
    --hash=sha256:5c58fe613dc5e5336357eff555824a314d8e43282600435c8d1cb6a7a2fedd13 \
    --hash=sha256:5e7cecbaadb83884793e05828cee59b210b24583b9c7425d0ba6a754fe22eb4e \
    --hash=sha256:616f097f2fe415bc92a247f02e11f634e1f9e9a83d327e3c915c15089c87869e \
    --hash=sha256:63bbfd5ded17c4840ac07cd8f1c21ba9d9708141f840b324f422f41b207e3973 \
    --hash=sha256:64faea20f4e2613363a1a9b9c7dd73058f3ecd00133a511e72ad7c511658f527 \
    --hash=sha256:661c298b4821edebead0c91edd2b00374d67ad7c5a1f7a91d4442633b79d6a72 \
    --hash=sha256:68e62fe11f30d5ca8289242866f0a5291402d8529ca2178ab8afc5c9694ae890 \
    --hash=sha256:6a8dddef476fab96d066d578fc88526767b836ab5ab21754e1d5bf3879c31c7c \
    --hash=sha256:6e192623c49c94421616a5778fba35cf0d5a8d000650c1967ef4448ee5cdd990 \
    --hash=sha256:7225e4514edb64eb6740324353e0da0711954fd8d7da4576755b1c6e09b697cd \
    --hash=sha256:75f80557d1389eddbd0de2681f6a390a0c5338c31ddaa821381c203fc3fd50d9 \
    --hash=sha256:770de9db11e84213beec501cfcaa013b019820ca881e03344dea5844f7876d94 \
    --hash=sha256:7750c6449dff7864bb9bb27ddfb0267756189201a3afc911d82b3caacd70dfc3 \
    --hash=sha256:7bde5e4cc5c10140859842b9d383af292b22639a4dffb725314baf45968cef80 \
    --hash=sha256:7ce713ace7c0e4520535b42b77eaa742c16dab813978064913e5a3cf82973b41 \
    --hash=sha256:7da0c5eff80f0197f3b3d1232ec5a682a9325f4ae9016a78f5f5ca35f9ced1f5 \
    --hash=sha256:7dbb61fe3a7699468030f71bbe5f8a0e326a151daa91beb11a6fc1f980c55e1c \
    --hash=sha256:811bd1e21d32de12efca32393a0ab3f5133b54fce9bd44b8bd77ab07da14bf6a \
    --hash=sha256:8ef53b2de9bcb9197d31854256575d59dbac0cba72ac627bb291ef5eceb74be4 \
    --hash=sha256:937c0052c05a31ca1daf18de3158eed4dbfcb9cc107adbea227728d647be701e \
    --hash=sha256:9d2055050ea716bd38b7f7f1579c275386646b4894c155a3e2f3cd62ed41b7c6 \
    --hash=sha256:9f8d177621de5cb38ee3e731eda45d421db093ec0739f46a5594babda7987a98 \
    --hash=sha256:a2d7755bef5a12ed488f4ef1f1b69ee9191d7396083b755a5d2295f6edb4768b \
    --hash=sha256:a48d62ab9d6f4f98c983223a547af44be6ca3691074c31cecced6facd3ba2dc1 \
    --hash=sha256:a4f00aa42f75d6e4595e8866e748cc1705adc0cddfeb2ca86d0d03993d63ba03 \
    --hash=sha256:a6e721d4b0e45d5b65e87534470e67b18dcd092c83f68fba09f152b9cbc061af \
    --hash=sha256:a730a083190634c65cca36ba5f489531576ebd79bcd5c8e172130f6453127231 \
    --hash=sha256:a931079504ecc49efed7744c476a5c343a92fabf66dec2db95edb1b2fdc770e2 \
    --hash=sha256:aa9511c62d14da7aacc9b4bf51f3f697a621e83b2d6919008243c3aad168eea3 \
    --hash=sha256:ab36d55f9ed2d067327667c2fea18dda018eb628dd6347aa01dda6cf1f5d3836 \
    --hash=sha256:ad2c86c495b899d862ea0f4b42891b8713a3bd45dd4105c7fd51c2a72f39f3a5 \
    --hash=sha256:aeae0e330c9f6acd681f647d46cefd30c29f93e3392882e792e82080c9691399 \
    --hash=sha256:b0431303acaea1089ad4b3e9ce4e6518193def1118d4073ca848635ee4ea2e96 \
    --hash=sha256:b5bdfd1c873d4e093aabc0ca84c4ca6dbc4f752afb5c86f146d9742580c9da2e \
    --hash=sha256:baed1e86cc735622097354b9d1281406caf42ff42a886d29faa8e8d1630333be \
    --hash=sha256:c1453022f490d2459a11819d83ad1d586e9ff65a12ac3e705ffebd46d3685dcf \
    --hash=sha256:c26608d2222fb1e94487e4a387d85f13eb55d5ed725cb25a0c589ac4ee60e7bc \
    --hash=sha256:c7659f22557c5a0bc4855cd635f55edec690cc008a40768527762cb9fb263455 \
    --hash=sha256:c8c69575568085ba0b1b10c0249d779a214aea6f6522e949a0fc9fb0fcb449d0 \
    --hash=sha256:c8d2c9fd1f2d16f780d15127abb050d13d1a76c03a4bd87d7e4980e45e511e12 \
    --hash=sha256:ca82be1a1d406ecfe1d25dc16cb33488e5a16bf4438c9fb590484ea29d92478b \
    --hash=sha256:cc572dace3f60ef98d7b12ff411d20f5362feb31a0439eab0085bbfd349982d7 \
    --hash=sha256:d18e5ac0f2f03f4f518d3e23db0f0cad7faa1da8620e9c09461d443bbf6e6692 \
    --hash=sha256:d28630f5854ab07ab1fd4aba756de52326c82e6be15d414b12793f1975048b54 \
    --hash=sha256:d9c275eaacd24aa73f94ffd6de08fc3f932424d8b6c376f4bed7cde376fe7bc3 \
    --hash=sha256:da0e573f9f97159390c89d9f1a9e41908b66d408cc5b58d08cf3847d844c531b \
    --hash=sha256:dd31f52ea1086513bb9df30f8fcee9b8918323ae067a3d5b78bc826a000712be \
    --hash=sha256:dddad92b554513a31f272570678ba307fb9f618f05e3d4a5eacafff9eae03e1d \
    --hash=sha256:df423d40ee8654634421812bc3b196da3f9bd7d32929da813f8394c4348a5358 \
    --hash=sha256:df913725b79db7bcf03448f36b7bf8815363417d5b58deecf9305e3e30f0f21a \
    --hash=sha256:e0bcb7e0f677f543555d2adff3bf19c05f66cdb4796e5ff602442ab2fe3c4ef7 \
    --hash=sha256:e2d65b31f36619cda3999b78b2aa9632e76b78448e7a56fc4240824200e7c4fc \
    --hash=sha256:e6e8cff14d6fb0be70a09c0bdc58096f501952d04624ebf867e0e56da2df8960 \
    --hash=sha256:f16c709686a78c727bbbf059f92b0bf41c6fc60deec706d2dc19f529175a6125 \
    --hash=sha256:f24fb43132a4c6b4cb4eb029492919b2db645be6808d738f244fd146c03c32cb \
    --hash=sha256:f53e442b08449d42821fa4a4fba000095af9f62742a500f978a9f557ec44339a \
    --hash=sha256:f5cfbc5fe74540d335175b656c725d74d90e3730c626d92575eea35029d9afaa \
    --hash=sha256:f81b3b8f3d4e343550fa4baa0e479bba9f2d29ce9c2e9b51d1ce1718d7442fcf \
    --hash=sha256:f8ec5e643a9a937f64e1999eb9f75d072263751912dc5cd06d3c85f8f44be7c3 \
    --hash=sha256:fb92203a88b3d3053034db775110081c49d28be6551923805e039924093761e4 \
    --hash=sha256:fcd22650c908d7b7da162bbfaab594a1227a15d1643a98c68b122ac642fa2264
click==8.5.0 \
    --hash=sha256:255bc9599cf7748b4b1a446ccc735421bd08a2ae529a8b88597d3de5664ee360 \
    --hash=sha256:ba0d2089de75ea0310e2dde03160e6ca10009947fb95a182f9b54021bb272e34
cryptography==50.0.2 \
    --hash=sha256:0ddc924c04591c2811ca024d62ecad4f7f6f08af8939c211438f48a16bd23602 \
    --hash=sha256:0ec5f09541743261e66e291b4a0cbf0fb2997aeaab6d9e9c740b9dba1b58d1c2 \
    --hash=sha256:0ecbc5652bdb6fc9eaf89a7d196e20941adfe812f43bc4ca05d9150496821047 \
    --hash=sha256:1981f1db4630889b9ef7803fadef12b056f428cb6b85c27ba57b774793b6093c \
    --hash=sha256:1ba34f04897fcdaa73f74145c25f3ec146fbd56593853e88adc2e811303c5f42 \
    --hash=sha256:241449bf940a5d27309bd317e6f9a2af6932113818bb2b8f5c59ddc7ef16da18 \
    --hash=sha256:25784ce8b9621c90c643efb9e1e2162ab3b0224cae446ad5e70e7fcb1ce18b51 \
    --hash=sha256:3dc4fd8058cea1644971207d530e1a03a184a805ffc8ebdddf0599d78a331b81 \
    --hash=sha256:4061c0079120205fb760c58acab6443e217307dcf05e3702cf970e0689972856 \
    --hash=sha256:4a20ce1e5cb4284a86692fdcba7cb8754185c6b2e5c56fcef3751cf451d3cdc2 \
    --hash=sha256:4e81d95e5bafc2d6e34e4bed780e53e4d5b9a2f928573428aa4d35fbec1eb0de \
    --hash=sha256:58a0c478eeca76fe5e07993c5a0703def34a6dc6a0cda4f5564639b33112ffe7 \
    --hash=sha256:58ddb5a8e3179d12f19e4ea34d2d32e9d63a4baa142c875c1eb59f41b7243acd \
    --hash=sha256:630ebfea3bf689d075f82316324ff7433dc447fe6bc1bfc76524b74b4a9567d2 \
    --hash=sha256:6f8700550aa1474a91e5dc07049c46f98b423b5b1ddd0483e0b51362eeeaf5be \
    --hash=sha256:78198641e5be9521beea5aa782bb551a58068d10e6eb04c9c680c1b69f2e7d45 \
    --hash=sha256:79def8d059362e7831389ed3be0ecdf58a89386e1271e35dd9f5af84e81bffd0 \
    --hash=sha256:7a8701d6b584d76e909e3d305b7d126b41439876a5aaf76cddc67fc230eafa2e \
    --hash=sha256:7afa5a6602a9f29af1f3a2965f831bae7c9d5d597b7cbb716d41ab3b7d89879c \
    --hash=sha256:7b46165bb56eb4704e2eaaf86f3c940d19154535d9b0ca7d6d590b04060e00d5 \
    --hash=sha256:7b75de3c8b3be1cdb1052747c929440c3eea46c1bc2cb8a6e3a48388e9b7b452 \
    --hash=sha256:7c6d0330c472d96f6a6afe24d80dfdf15176c33096f0a4397ae4c60f3dd3be48 \
    --hash=sha256:828d49b0ff5a0e3975865571c5d91dbbdd0d38d8289b249a163e9425413a5e05 \
    --hash=sha256:84f964e537f916e2cc85199e5a88742e964939b575ac8598b3f9d6cc416cdaf1 \
    --hash=sha256:85d0d9a31b9098e98534226d5686b47264b95e62ce459dc2e62fdfc809f9fe93 \
    --hash=sha256:87e9ce85beb6b328ba370cc6e6aea483c92617b4c95b1d33a49297eb662bfb04 \
    --hash=sha256:8c71ba2cd31fc93748c38e1b613200ff1c2665cbfd5341fe3a61cfde35a1430e \
    --hash=sha256:92e665960f25fcdc73725b9cec7a3824f279ba97a98653afe9ffac2e43668f67 \
    --hash=sha256:94e5e9f108ee10471288214d3d233fbfbb492840a8457eb85178d643ddeb32c7 \
    --hash=sha256:9c8402a82ea0dc4ceeab793db05f0fafa8ca139ca34fcde5df0f596103c74107 \
    --hash=sha256:9dab55f57c74c3cad24c323bacbbd04be4705ba6eb0d92e920b1fc4837ed5079 \
    --hash=sha256:a582ab2ae1d34f67112cadc86702774c9ea4374df6bca6afe672817203c99134 \
    --hash=sha256:a6557e5f38e065ca9fbdaf7cfc7435ecb1d113aa81a022d1b51921ee7432e227 \
    --hash=sha256:a9f7355e6fab51f6c369b86fb7571cffa05edee2c2121e0380a37fb9ac1cd5c1 \
    --hash=sha256:ab50ee449bf968271e820086f10a33d101dd060370abc10bcd22279be2656539 \
    --hash=sha256:ac9ed99d81760c62fe89d5f0815cdfa1ba9a35141cf30f1c2d044f04b4803d2e \
    --hash=sha256:b13478603dcd0a2479ff8e87e2c19a7d525734686fe3c49542472293a204212d \
    --hash=sha256:c423ab384a46c4dff7217b2ea5ba2e11cffdeab6441acd04cf65a369caf0366c \
    --hash=sha256:c5e67125c7dca78d199ec4e116aa93dbb83494808ecbb8211a2cb09b1bf41dbd \
    --hash=sha256:c71be1cbfa5cd9a41ee452acf1eccd82b2c05950358b106ec8ceb83411d1a020 \
    --hash=sha256:cbc8738fd8526d80f35cb3a40d41f41a2e7030bb3b18b09a6778ef63d291c2fd \
    --hash=sha256:ce47f66801c20ec6c6632453bb5960fe38939e9306970b48b3a5a26de7745d94 \
    --hash=sha256:d370b8d1dfcdf7130178137f6fbee6140774a1acc6cacefc4b42643ec11d0a3a \
    --hash=sha256:d38cdff612d06fa6a32840d5e1b1f7a27cee4a349aa9085d94a67789d6bfd408 \
    --hash=sha256:d8947001be83df1394050758ce0e745dd74fb134eef0a4b5124208dfc3a68c37 \
    --hash=sha256:deb9fde5c60e437ee4821bc9bc39ff31b42135c27e1dc61ef0a629389c1de62e \
    --hash=sha256:dfe9763530994147d9af1def057a5b9658b00e8f8fe8743d144d1e0911c2e454 \
    --hash=sha256:e105ab60406787da31fccc883fc0f733af1efd78f0136a4599692c4083a73d0c \
    --hash=sha256:e275096ea1e60cc595cda2836fd4a6c725d1125108b868be17f53684d164e2cc \
    --hash=sha256:edc3342adf8f697fc5f59c887a304356f147b397809440ed64e2fa6af2f50f37 \
    --hash=sha256:ee247f5c245c9a2fe7c8e2214e295918838e44e00a45a6718451e4004219e767 \
    --hash=sha256:eef4c2f3423810b3070ab391f85436d2f8bbfcb286ac15cbc73190b3563b1f1a \
    --hash=sha256:f21e8a22c8605750c7af886bab299a363721264061b4ac0a30efb73cfd58efc5 \
    --hash=sha256:f265528741e048bce55c3463ed721fb0aa45a5888d8add8cfeccb3035451bbdc \
    --hash=sha256:f2f9bd7f90c64fe89253f0a2c05e3c4856072660429ce8831b4235bf29403a67 \
    --hash=sha256:f785f6161f202ab04d8ca194158968798e480ca058943907972da5f12e2881e8 \
    --hash=sha256:f9f6143a8c75945eb960d9eb98905a441394abfa24afaae239d514ffb2586480 \
    --hash=sha256:fa8f5efb344d6908a1ce62f4a24e2e5780f825d6f53f5f50ec5ffacac72936cb \
    --hash=sha256:fdd28f912fccfec1846a94e2e1e8f9b0012f557f0c46fe4f3eb0d7a87afcf90b
fastapi==0.142.2 \
    --hash=sha256:06366626f2e70576367714d9ab2fe8472e6c8456dba69b399f9f797ab5e92570 \
    --hash=sha256:bd5f4d81f1e93a88bcd77caf4dfe3c2dbffc3805407a0007e9a114c18b3a670b
h11==0.16.0 \
    --hash=sha256:4e35b956cf45792e4caa5885e69fba00bdbc6ffafbfa020300e549b208ee5ff1 \
    --hash=sha256:63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86
hatchling==1.32.4 \
    --hash=sha256:08ecf7548fb48205e7f213d70c71e67b8271b7242093dc3f1da578b42c734a2c \
    --hash=sha256:c4468f73144c054d2aab4ef0f0378c43b9878bf07f8ffd6b79690e970d375f07
httpcore==1.0.9 \
    --hash=sha256:2d400746a40668fc9dec9810239072b40b4484b640a8c38fd654a024c7a1bf55 \
    --hash=sha256:6e34463af53fd2ab5d807f399a9b45ea31c3dfa2276f15a2c3f00afff6e176e8
httpcore2==2.13.1 ; sys_platform != 'emscripten' \
    --hash=sha256:e0aa977abe17e69a3b820a24542a6fa88702676d83880b8d194dcd18408e5103 \
    --hash=sha256:e1e05d4f25f7d7d496bfb96748f6f4b67657b03da069b3a68c36069f3db73d0a
httptools==0.8.0 \
    --hash=sha256:0770728beb05094c809b98e814edff5fef69d26ad7d21185f2f6d5884a0ba683 \
    --hash=sha256:0ea897f0c729581ebf72131a438a7932d9b14efef72d75ada966700cac3caaeb \
    --hash=sha256:159e9ab5f701ccd42e555a12f1ad8ff69702910fc1c996cf2bb66e5fcb7a231b \
    --hash=sha256:19d1ee275bb59ba2643ba9a3a1e51cc0c788caf2b8df506368e03f56fdd08527 \
    --hash=sha256:20b4aac66ff65f7db06a375808b78f42a94970aa22e826b3cb2b43eb09174124 \
    --hash=sha256:2a021c3a8e65cc125390d72f59b968afca3bdcaff25bd67965e0a055a14946ca \
    --hash=sha256:2c032fa028f46871ec7e1fc59fc15e8023eab3e6bbe6ece786a1611719a5d081 \
    --hash=sha256:2d689918c15a013c65ef52d9fd495d766893ab831a2c8d89f2ac5940a5df847c \
    --hash=sha256:384c17174464c8e873398b7af24f0b1f44d992c820328413951a625323155d77 \
    --hash=sha256:425f83884fd6343828d8c565f046cb72b6d19063f6924093e11bcd8e1548cd09 \
    --hash=sha256:48774d39cbb70e2b1f71f88852a3087ae1d3a1eb80482bb48c13067ab080c14f \
    --hash=sha256:52dd695b865fe96d9d2b16b64a895f3f57bf3cb064e8383cd3b5713a069e8085 \
    --hash=sha256:57278e6fa0424c42a8a3e454828ab4f0aff27b40cddf9679579b98c6dce6a376 \
    --hash=sha256:5931891fb7b441b8a3853cf1b85c82c903defce084dd5f6771ca46e31bf862c5 \
    --hash=sha256:5d7fa4ba7292c1139c0526f0b5aad507c6263c948206ea1b1cbca015c8af1b62 \
    --hash=sha256:5eb911c515b96ee44bbd861e42cbefc488681d450545b1d02127f6136e3a86f5 \
    --hash=sha256:614ceea8ea606848bece2338ac03b3ce5324bcb4be8dc7d377ed708012fa4db8 \
    --hash=sha256:6a43c9dd399758ccc0531acb0a3c4a6c299ee893ee9400e9c893b7bdcfae0681 \
    --hash=sha256:6b2a32f18d97e16e90827d7a819ffa8dbd8cc245fc4e1fa9d1095b54ef4bd999 \
    --hash=sha256:7685df791fad561384bfb139e77fde27a1ffd93134e016f95a0db424ffbf77b1 \
    --hash=sha256:7b71e7d7031928c650e1006e6c03e911bf967f7c69c011d37d541c3e7bf55005 \
    --hash=sha256:880490234c10f70a9830743097e8958d6e4b9f5a0ffc24515023afeef984054d \
    --hash=sha256:88bdd940f2b5d487b4d032c6afa5489a7dc4694410d43de3c38c4fb3af0dc45d \
    --hash=sha256:88eead8ec8680a9f146c655bc88445a325bd7921cfd8194c7337e9467282427d \
    --hash=sha256:9518c406d7b310f05adb1a37f80acabac40504a575d7c0da6d3e365c695ac20d \
    --hash=sha256:9878eb2785ba5eb70631ad269b37976f73d647955e26c91d490eb8a4edfda4ba \
    --hash=sha256:9fc1644f415372cec4f8a5be3a64183737398f10dbb1263602a036427fe75247 \
    --hash=sha256:a1afd7c9fbff0d9f5d489c4ce2768bd09c84a46ddefc7161e6aa82ae35c85745 \
    --hash=sha256:a1b4c8e7a489a0d750d91894e9a8cdc295838f1924c0ca903ae993456fddec07 \
    --hash=sha256:a3b7387147361c3fd47a0bde763c5c91b5b4cd4dc9989b8ece84ff436c99843b \
    --hash=sha256:a6f21e2a3b0067bbe7f67e34cfd16276af556e5e52f4c7503be0cb5f90e905e4 \
    --hash=sha256:b15fc622b0f869d19207c4089a501d9bcc63ca5e071ffdd2f03f922df882dcb2 \
    --hash=sha256:b205e5f5523fa039679da0dfe5a10132b2a4abeae6a86fdd1ddc035f7f836557 \
    --hash=sha256:bbb8caadb2b742d293169d2b458b5c001ef70e3158704aa3d3ef9597624c5d1d \
    --hash=sha256:bf3b6f807c8541503cecfbb8a8dffb385640d0d96102f3d112aa8740f9b7c826 \
    --hash=sha256:c08ffe3e79756e0963cbc8fe410139f38a5884874b6f2e17761bef6563fdcd9b \
    --hash=sha256:c0d726cc107fceb7d45f978483b4b70dd8caa836f5914d3434bb18628eb73813 \
    --hash=sha256:c4a9f1707e4823d54dfec6c33fa3697d302aed536ed352a7ebb5a061ddb869d0 \
    --hash=sha256:cd96f29b4bab1d42fa6e3d008711c75e0f79e94e06827330160e3a304227f150 \
    --hash=sha256:d76ad7b951387e3632c8716a9bb03ac5b45c5f16119aa409db0459520887944e \
    --hash=sha256:da684f2e1aa2ee9bdcb083f3f3a68c5956750b375bc5df864d3a5f0c42a40b77 \
    --hash=sha256:de1ed58a974e75d56560acc7e7fed01a454994429456f65209789992e41f2568 \
    --hash=sha256:de242a49b5d18e0a8776e654e9f6bf6d89f3875a5c35b425a0e7ce940feb3fd6 \
    --hash=sha256:df31ef5494f406ab6cf827b7e64a22841c6e2d654100e6a116ea15b46d02d5e8 \
    --hash=sha256:e93c227b595c6926c1acee96891dd9da4be338cfbe82e5cd3bb9d8dd7dc4ac0b \
    --hash=sha256:eb3028cca2fc0a6d720e52ef61d8ebb62fcbfeb1de56874546d858d3f25a26b7 \
    --hash=sha256:ed377e64805bdba4943c82717333f8f8603a13b09aff9cead2717c6c817fb168 \
    --hash=sha256:ef7c3c97f4311c7be57e2986629df89d49cb434dbff78eafcd48c2bff986b15a \
    --hash=sha256:f256d6ce930c52ca1cb2a960b7da03548c454e7d28b06059ad41bfe789036ce0 \
    --hash=sha256:fe2a4c95aeba2209434e7b31172da572846cae8ca0bf1e7013e61b99fbbf5e72
httpx==0.28.1 \
    --hash=sha256:75e98c5f16b0f35b567856f597f06ff2270a374470a5c2392242528e3e3e42fc \
    --hash=sha256:d909fcccc110f8c7faf814ca82a9a4d816bc5a6dbfea25d6591d6985b8ba59ad
httpx2==2.13.1 \
    --hash=sha256:6dff50fabc270ee5fd25d845d0b078ed20564579744d6d962850975996d2f9a4 \
    --hash=sha256:e48744a19e3af5ee48313d0ce5fe941d5422fae5705ea922a4aabf94d7800dfa
httpx2-jsfetch==1.0 ; sys_platform == 'emscripten' \
    --hash=sha256:70a0e3eabfef7cce5ad9c629f7d01ca05e418f586646f4ddf14782e4c1454c60 \
    --hash=sha256:cb916b707601e69a07721aabc8f3f6659be3a6893bc1ff5c6f9e02241df2da32
idna==3.20 \
    --hash=sha256:a7db850025b95ded1eae8a46181a1a6c56c92c96f0e2b005d9ff8dc0210cab44 \
    --hash=sha256:ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c
jaraco-classes==3.4.0 \
    --hash=sha256:47a024b51d0239c0dd8c8540c6c7f484be3b8fcf0b2d85c13825780d3b3f3acd \
    --hash=sha256:f662826b6bed8cace05e7ff873ce0f9283b5c924470fe664fff1c2f00f581790
jaraco-context==6.1.2 \
    --hash=sha256:bf8150b79a2d5d91ae48629d8b427a8f7ba0e1097dd6202a9059f29a36379535 \
    --hash=sha256:f1a6c9d391e661cc5b8d39861ff077a7dc24dc23833ccee564b234b81c82dfe3
jaraco-functools==4.6.0 \
    --hash=sha256:880c577ec9720b3a052d5bc611fb9f2269b3d87902ef42440df443b88e443280 \
    --hash=sha256:99e3dc0060c5cbe8fcd1cdb36258e2a65ca40f1566b2033b12abb1bb44dd3c30
jeepney==0.9.0 ; sys_platform == 'linux' \
    --hash=sha256:97e5714520c16fc0a45695e5365a2e11b81ea79bba796e26f9f1d178cb182683 \
    --hash=sha256:cf0e9e845622b81e4a28df94c40345400256ec608d0e55bb8a3feaa9163f5732
joserfc==1.7.5 \
    --hash=sha256:add2c2c84e8373b084d526a8b53daba5d7a513a118cd2dcd9fc9f979d0922159 \
    --hash=sha256:d5ff536e658e17664f8c1b1ab60dc4aa62aa973fcef1edd33cc44bda45d6f5ea
jsonschema==4.26.0 \
    --hash=sha256:0c26707e2efad8aa1bfc5b7ce170f3fccc2e4918ff85989ba9ffa9facb2be326 \
    --hash=sha256:d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce
jsonschema-specifications==2025.9.1 \
    --hash=sha256:98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe \
    --hash=sha256:b540987f239e745613c7a9176f3edb72b832a4ac465cf02712288397832b5e8d
keyring==25.7.0 \
    --hash=sha256:be4a0b195f149690c166e850609a477c532ddbfbaed96a404d4e43f8d5e2689f \
    --hash=sha256:fe01bd85eb3f8fb3dd0405defdeac9a5b4f6f0439edbb3149577f244a2e8245b
mcp==2.3.0 \
    --hash=sha256:8b147a50441cf059dc88c684e0aeed3687f0aa0f39c6cde7b90330effd2b34d8 \
    --hash=sha256:dd0c44c089d16453e8ae31a3877a0054d7a2314caaa81f5e0541b9b1734b2377
mcp-types==2.3.0 \
    --hash=sha256:968efdbdaedfab06adae40d378a34395f1090c5921d4be3c9cde283aaf76d91d \
    --hash=sha256:d1e46549edb35ee19a94940fcee6d1addd7e589ab7ea92dda83f5d84781fc362
more-itertools==11.1.0 \
    --hash=sha256:48e8f4d9e7e5878571ecf6f2b4e57634f93cd474cc8cfbd2376f2d11b396e30d \
    --hash=sha256:4b65538ae22f6fed0ce4874efd317463a7489796a0939fa66824dd542125a192
opentelemetry-api==1.45.0 \
    --hash=sha256:711ede81773c8025c2c03dac0450bc89f3d30aea6eabcc815c570d4e35a963f7 \
    --hash=sha256:80e068aba7cd56c8b58512d6a36f8d25cb1dfaa0c0a4cc1c938ccf9f362d9cb3
packaging==26.3 \
    --hash=sha256:94edc256424af38762eb31306eed28beb9f0efc50a8837492c9d6fd6004aed79 \
    --hash=sha256:d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c
pathspec==1.1.1 \
    --hash=sha256:17db5ecd524104a120e173814c90367a96a98d07c45b2e10c2f3919fff91bf5a \
    --hash=sha256:a00ce642f577bf7f473932318056212bc4f8bfdf53128c78bbd5af0b9b20b189
pillow==12.3.0 \
    --hash=sha256:00808c5e14ef63ac5161091d242999076604ff74b883423a11e5d7bbb38bf756 \
    --hash=sha256:04f01d28a6aaff387bf842a13be313df23ba0597a44f1a976c9feb3c6ff4711a \
    --hash=sha256:06ff022112bc9cbf83b60f8e028d94ad87b60621706487e65f673de61610ab59 \
    --hash=sha256:0740a512dc522224c77d9aa5a8d70d8b7d73fb91f2c21125d8d025d3b8990e45 \
    --hash=sha256:0847a763afefb695bc912d7c131e7e0632d4edc1d8698f58ddabec8e46b8b6d3 \
    --hash=sha256:0dd2064cbc55aaec028ef5fbb60fa47bb6c3e7918e07ff17935284b227a9d2df \
    --hash=sha256:0feb2e9d6ad6c9e3c06effe9d00f3f1e618a6643273576b016f591e9315a7139 \
    --hash=sha256:10e41f0fbf1eec8cfd234b8fe17a4caac7c9d0db4c204d3c173a8f9f6ef3232b \
    --hash=sha256:1182d52bc2d5e5d7d0949503aa7e36d12f42205dc287e4883f407b1988820d39 \
    --hash=sha256:164b31cd1a0490ab6efae01aa5df49da7061be0af1b30e035b6e9a1bfe34ee6e \
    --hash=sha256:1657923d2d45afb66526e5b933e5b3052e6bdea196c90d3abb2424e18c77dae8 \
    --hash=sha256:186941b6aef820ad110fb01fb06eb925374dc3a21b17e37ec9a53b250c6fe2d1 \
    --hash=sha256:1cca606cd25738df4ed873d5ad46bbdb3d83b5cbca291f6b4ff13a4df6b0bbe8 \
    --hash=sha256:21900ce7ba264168cd50defae43cd75d25c833ad4ad6e73ffc5596d12e25ac89 \
    --hash=sha256:236ff70b9312fb68943c703aa842ca6a758abfa45ac187a5e7c1452e96ef72b5 \
    --hash=sha256:23aceaa007d6172b02c277f0cd359c79492bbb14f7072b4ede9fbcaf20648130 \
    --hash=sha256:23d27a3e0307ec2244cc51e7287b919aa68d097504ebe19df4e76a98a3eea5bd \
    --hash=sha256:24870b09b224f7ae3c39ed07d10e819d06f8720bc551847b1d623832b5b0e28d \
    --hash=sha256:251bf95b67017e27b13d82f5b326234ca62d70f9cf4c2b9032de2358a3b12c7b \
    --hash=sha256:25b9b82bb22e6e2b3cd07b39c68b7b862001226cb3dff7130d1cb914121b39ed \
    --hash=sha256:28ce87c5ab450a9dd970b52e5aca5fe63ed432d18a2eaddd1979a00a1ba24ace \
    --hash=sha256:300557495eb45ebb8aec96c2da9c4be642fbf7cd937278b4013ba894ea8eb0eb \
    --hash=sha256:30f2aa603c41533cc25c05acd0da21636e84a315768feb631c937177db558931 \
    --hash=sha256:331b624368d4f1d069149002f25f44bc61c8919ce8ddb3c45bdad8f6e2d89510 \
    --hash=sha256:37d6d0a00072fd2948eb22bce7e1475f34569d90c87c59f7a2ec59541b77f7a6 \
    --hash=sha256:37dc8f7bbb66efe481bb60defacef820c950c24713fb44962ed6aa2a50966de1 \
    --hash=sha256:3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce \
    --hash=sha256:3edce1d53195db527e0191f84b71d02022de0540bf43a16ed734ed7537b07385 \
    --hash=sha256:446c34dcc4324b084a53b705127dc15717b22c5e140ae0a3c38349d4efec071e \
    --hash=sha256:4998562bf62a445225f22e07c896bb04b35b1b1f2eb6d760584c9c51d7a5f78c \
    --hash=sha256:4b0a7fe987b14c31ebda6083f74f22b561fd3739bc0ac51e019622e3d72668c7 \
    --hash=sha256:4e8c2a84d977f50b9daed6eeaf3baef67d00d5d74d932288f02cb94518ee3ace \
    --hash=sha256:4f883547d4b7f0495ebe7056b0cc2aea76094e7a4abc8e933540f3271df27d9c \
    --hash=sha256:514435a37670e3e5e08f3945b68718b6ed329bb84367777e16f9f4dfe1e61a0f \
    --hash=sha256:53aa02d20d10c3d814d536aa4e5ac9b84ca0ff5a88377963b085ad6822f93e64 \
    --hash=sha256:5594fc43d548a7ed94949d139aa1341b270f1863f11cfd37f5a6c8b778a6b67f \
    --hash=sha256:571b9fcb07b97ef3a492028fb3d2dc0993ca23a06138b0315286566d29ef718a \
    --hash=sha256:57b3d78c95ba9059768b10e28b813002261d3f3dfc55cc48b0c988f625175827 \
    --hash=sha256:5afb51d599ea772b8365ae807ae557f18bccfe46ab261fd1c2a9ed700fc6eb17 \
    --hash=sha256:6b02afb9b97f65fbca5f31db6a2a3ba21aa93030225f150fa3f249717e938fb4 \
    --hash=sha256:6c0016e7b354317c4e9e525b937ac8596c38d2d232b419529b9cd7a1cd46e39a \
    --hash=sha256:71d6097b330eea8fd15097780c8e89cb1a8ce7838669f48c5bacd6f663dd4701 \
    --hash=sha256:756c768d0c9c2955feb7a56c37ea24aea2e369f8d36a88da270b6a9f19e62b5e \
    --hash=sha256:78cb2c6865a35ab8ff8b75fd122f6033b92a62c82801110e48ddd6c936a45d91 \
    --hash=sha256:7a743ff716f746fc19a9557f60dab1600d4613255f8a7aeb3cdde4db7eb15a66 \
    --hash=sha256:85f998ea1848bc6757289e739cfbdda3a04adfd58b02fc018ce54d754a5ce468 \
    --hash=sha256:8728f216dcdb6e6d555cf971cb34076139ad74b31fc2c14da4fafc741c5f6217 \
    --hash=sha256:877c3f311ff35410f690861c4409e7ccbf0cd2f878e50628a28e5a0bb689e658 \
    --hash=sha256:8cd2f7bdda092d99c9fc2fb7391354f306d01443d22785d0cbfafa2e2c8bb418 \
    --hash=sha256:8e95e1385e4998ae9694eeaa4730ba5457ff61185b3a55e2e7bea0880aef452a \
    --hash=sha256:962864dc93511324d51ddbb5b9f8731bf71675b93ca612a07441896f4688fb8c \
    --hash=sha256:9cf95fe4d0f84c82d282745d9bb08ad9f926efa00be4697e767b814ce40d4330 \
    --hash=sha256:9e881fca225083806662a5c43d627d215f258ff43c890f831966c7d7ba9c7402 \
    --hash=sha256:a2b55dd6b2a4c4b7d87ffa56bdb33fdc5fdb9a462173861a7bc097f17d91cb09 \
    --hash=sha256:a45650e8ce7fafffd731db8550230db6b0d306d181a90b67d3e6bca2f1990930 \
    --hash=sha256:a876864214e136f0eb367788dbd7df045f4806801518e2cfe9e13229cfe06d8f \
    --hash=sha256:ae26d61dfa7a47befdc7572b521024e8745f3d809bd95ca9505a7bba9ef849ec \
    --hash=sha256:af8d94b0db561cf68b88a267c5c44b49e134f525d0dc2cb7ed413a66bc23559a \
    --hash=sha256:b343699e8308bdc51978310e1c959c584e7869cc8c40780058c87da7781a1e94 \
    --hash=sha256:b3c777e849237620b022f7f297dd67705f9f5cf1685f09f02e46f93e92725468 \
    --hash=sha256:b629de27fda84b42cde7edef0d85f13b958b47f6e9bbcbba9b673c562a89bd8b \
    --hash=sha256:ba09209fbe443b4acccebe845d8a138b89a8f4fbaeedd44953490b5315d5e965 \
    --hash=sha256:ba54cfebe86920a559a7c4d6b9050791c20513650a1952ebe3368c7dc70306f8 \
    --hash=sha256:bcb46e2f9feff8d06323983bd83ed00c201fdcab3d74973e7072a889b3979fcd \
    --hash=sha256:bcc33feacfaefce60c12fd500a277533bdc02b10a19f7f6d348763d8140bbba7 \
    --hash=sha256:bf16ba1b4d0b6b7c8e534936632270cf70eb00dbe09005bc345b2677b726855c \
    --hash=sha256:cf1845d02ad822a369a49f2bb9345b1614744267682e7a03527dc3bf6eea1777 \
    --hash=sha256:d69141514cc30b774ceea5e3ed3a6635c8d8a96edf664689b890f4089111fb35 \
    --hash=sha256:d9c7f76c0673154f044e9d78c8655fb4213f6ca31a836df48b40fe5d187717b9 \
    --hash=sha256:dbce0b29841537a2fa4a214c2bbf14de3587c9680caa9b4e217568472490b28f \
    --hash=sha256:dc624f6bc473dacdf7ef7eb8678d0d08edf15cd94fad6ae5c7d6cc67a4e4902f \
    --hash=sha256:e158cb00350dc278f3b91551101aa7d12415a66ebf2c91d8d5ac14e56ddd3ad0 \
    --hash=sha256:e491916b378fba47242221bb9ead245211b70d504f495d105d17b14a24b4907c \
    --hash=sha256:e795b7eb908249c4e43c7c99fac7c2c75dab0c43566e37db472a355f63693d71 \
    --hash=sha256:e7e480451b9fa137494bccd3a7d69adbe8ac65a87d97be61e11f1b1050a5bac3 \
    --hash=sha256:e91206ee562682b51b98ef4b26a6ef48fd84e15fd4c4bc5ec768eb641d206838 \
    --hash=sha256:e9871b1ffbfa9656b60aeee92ed5136a5742696006fa322b29ea3d8da0ecc9cf \
    --hash=sha256:e9aeb04d6aef139de265b29683e119b638208f88cf73cdd1658aa07221165321 \
    --hash=sha256:ebaea975e03d3141d9d3a507df75c9b3ec90fa9d2ffd07567b3a978d9d790b26 \
    --hash=sha256:f0606c8bf2cdefea14a43530f7657cbbb7ecf1c4222512492ef4a4434a9501ec \
    --hash=sha256:f13c32a3abd6079a66d9526e18dad9b6d280384d49d7c54040cd57b6424041d9 \
    --hash=sha256:f7401aebd7f581d7f83a439d87d474999317ee099218e5ad25d125290990ba65 \
    --hash=sha256:fa4ecea169a355be7a3ade2c783e2ed12f0e40d2c5621cda8b3297faf7fbb9f5 \
    --hash=sha256:fbd139c8447d25dd750ab79ee274cc5e1fe80fc56340ab10b18a195e1b6eca3e \
    --hash=sha256:fdafc9cce40277e0f7a0feabce0ee50dd2fa1800f3b38015e51296b5e814048d \
    --hash=sha256:fe3cca2e4e8a592be0f269a1ca4835c25199d9f3ce815c8491048f785b0a0198 \
    --hash=sha256:ffd0c5368496f41b0944be820fcb7a838aa6e623d250b01acf2643939c3f99d7
pluggy==1.6.0 \
    --hash=sha256:7dcc130b76258d33b90f61b658791dede3486c3e6bfb003ee5c9bfb396dd22f3 \
    --hash=sha256:e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746
pycparser==3.0 ; implementation_name != 'PyPy' \
    --hash=sha256:600f49d217304a5902ac3c37e1281c9fe94e4d0489de643a9504c5cdfdfc6b29 \
    --hash=sha256:b727414169a36b7d524c1c3e31839a521725078d7b2ff038656844266160a992
pydantic==2.13.5 \
    --hash=sha256:346a034f080da3755d8e9cb5e00e8b07de1d39e4f6e2c87d8ab7cafa0b269a73 \
    --hash=sha256:51a9c5f7b2f8e636f04c6cada605d9b6a3bf1348fdf945a3d8869b19bba0ee08
pydantic-core==2.46.5 \
    --hash=sha256:013d6f3483d81e02e7c328831808f336c8596ee33b4bd4026b9ffb1e960b8942 \
    --hash=sha256:03b9666e41e35d8909852ba191a0607520f81b74eaf12ccf8737005dbb313821 \
    --hash=sha256:045ab3b6d308439e32b81cc173bba5b9018bc6ed896afd0c65b3b009b1699af5 \
    --hash=sha256:0bddb4020d8f04175865ccd17eff3040874fc11fb593f424edb452653b4b947c \
    --hash=sha256:0cdbada856a1c69a7624a64d3d9aefe79300bd6ef827b43a4f265010b9b55184 \
    --hash=sha256:0fc5be0abd4a407e200d844b404e33639a554e7bd0d448e7b9ae181be4789ac2 \
    --hash=sha256:10416c15b8839ecc4ef4d0885da76da6fd0f67333a0eb8aff6d93c4b8f2910fc \
    --hash=sha256:15f4a94963c95accac15b7b657bb177d3ad82bb90b0d0526d9a9b85079925db5 \
    --hash=sha256:18a09e1e1011b462f2e32774f25859ef1223d5c2b0546a633cf56654710721e0 \
    --hash=sha256:193375f3548919d3f0b60936ca113ada3e38f264f91b9b8e0508efaad57be931 \
    --hash=sha256:1a353f84de772f423b5ffb11d7ae352fbbef0f446f3c0b0af0f8236d7233606e \
    --hash=sha256:1e449def1945a462c464331254e5a44fca7c3b4f9aedf59ec2f50f8066dd8e25 \
    --hash=sha256:1e5aad1220a1192c42341c8fd4a8686657e73ab2a920c970bdc4de334fe3193d \
    --hash=sha256:200aa3dc9f8d54f0754f43247c0bad0999fdcfbfd2488384dd44f37279271fe6 \
    --hash=sha256:2471fd51c61c610e1dcf7de44d7299283661654d11264ab4802b303368d69c47 \
    --hash=sha256:24922243639cbdac66c75fcb6fd6495a9cb52b213d62f9a0d16f0310b1ff8038 \
    --hash=sha256:28a6a556cd3b6066bea827857f9d9cce027c96f776e512f544a581f9e42161f8 \
    --hash=sha256:2bc9419666990c06d7397831f2126a1ecc3594aaa3ff7de5bf2d066802f4e07b \
    --hash=sha256:2cbd9a5eff05e51c447c34dfa4632145b26b09120cf04bd0c871e44c1a5e1c9a \
    --hash=sha256:2d330aaba8621b1edcec8ae2c4050f63b84ccf6d98723a8f212e9684713abf0e \
    --hash=sha256:2d5d76654becf5efd62c9e51c3756c67b49498b0c9a40884934c40807adbd074 \
    --hash=sha256:337639ba62a11acde6ef3aeb08c8ea755f8ef1fe5e513356c0f36a2b0d7568b0 \
    --hash=sha256:347ec774390c87326a2e4929d58d3f7e8763a104d5d35f4cd595a4c952366433 \
    --hash=sha256:356c8368cbc321050b169595683a2e1d63413b1e0e2868b330af9fc14c616d3f \
    --hash=sha256:37ae34309d7bd8c0d61ab839668058f2a7962ea1fc51d105d2db228fe0618034 \
    --hash=sha256:37ea7b83c935e5b0d68c9449b82651accf78a10828b2c02b2f2d9e9496446c21 \
    --hash=sha256:3a3e26b6a8274211bddee2d0e4d0d42778f17a34510f49d2ec44b58abfc41736 \
    --hash=sha256:3aa166e99c4f2985407fb8714aebede877ecb5455cf321b606adca926d30d5a0 \
    --hash=sha256:3d2652072b2d774947ba5cf78a9e59644ac62ee572daf6dd2e1dfe905e15b2b7 \
    --hash=sha256:40375c2d05acec10323e45dfe2077ac44bc74659008614af5069034e2cfc781c \
    --hash=sha256:413a717a410d0c817ef5b786a059415550b3794e1d0c2abffd9efb93a3d9f7b4 \
    --hash=sha256:46c25dda9d092a06c08db76ffe0a197107904d0dfac653f7d5306bbcd6d6119c \
    --hash=sha256:49776eab08766a08dfff7012f8b422dcd7e25e43b316eedf0477c24fcfa84b7c \
    --hash=sha256:4d44cf99ddebf875f9b68cc267aa684c99b7b44fe63ee1cac4ec163807290069 \
    --hash=sha256:4dedce55295becb61921e386b99d4f2706045306e7fa52249a33004c837379fb \
    --hash=sha256:4f8507560a9284e1370bb048ed4282012fbef4e8d109875b95e884d228552061 \
    --hash=sha256:4fdc8b93a41521988916eeaa271173fcca7fa0803d62f87675aac8dcec1c8e29 \
    --hash=sha256:5086029a57366b8cf81b130a43908738095c270c21a8d7f0e8bdfdb89718e2f3 \
    --hash=sha256:52e24eacdb536cade636aa90fb851835222becff8484b7001fdc78cb0290f2aa \
    --hash=sha256:53feb344243bb9510a9dec7bf3cf1b64d88a98af5dc7872a5160465f8b198c8e \
    --hash=sha256:545f26c504b27c3758439a5e6d9349931f0a04f855668d5fe323c89e82300a38 \
    --hash=sha256:54d510bac3ee52247af28ed4bb18a1e799f040ac60fd2bf5ccd4c92f1fbe786f \
    --hash=sha256:5cb482e9e84c851f4e623fe4acc1ced89168cf1fe18f7089db4548c8f5bbb65b \
    --hash=sha256:5e81740c09e310f5aa5cbd3e434a01c154d4bef93241c7877b39f211d2b78ba8 \
    --hash=sha256:5ee239d575f80b08eca11f6e20f90c4c695de7825c67eefe6091fbf20dda648e \
    --hash=sha256:5f194189415698233dd1114a093a9b56e61e2c57e11b469be3b0506f46f0771c \
    --hash=sha256:5f93c5fe914d75fbec9a49209b00da5f08e9e467d69da2b1510c81940cfd10be \
    --hash=sha256:657b40d6240c0a7b6a64b30f22d1e3aa631c7e846c621b0c0f6d1d75e2e15ea6 \
    --hash=sha256:6d30e1a4f138b8951063e9a394752a9179b51da288ffa507b1e659222f4c1793 \
    --hash=sha256:6f7b393a8b3da82f5c1fc0751e6d01ac6c55b93c18226a60bdfba4a724efafd1 \
    --hash=sha256:701b2e04b560eeb4bddf7a25ab8ca476176e34fdbd9a0e18196f0d12d4685f0b \
    --hash=sha256:771cf63ae0b1b50dd22e5f3e3549fab5f3f4ff1635d352a9e1a97fe01c7b2e64 \
    --hash=sha256:79bdfa52f843137045b2d081cc05c120ba6665d29b7559c2c47690906f39279f \
    --hash=sha256:7ac031912d54f3d83ef3b3eb98dfabc1608802e2202263d25957eeed40b94761 \
    --hash=sha256:7b0fc826b16c55e561e5d2a0c5c77b051ba1d92808118c4e4b5390f5e0cf191d \
    --hash=sha256:7c6be839a5a8312626b32029a415644a0846b420bc8b52b95b28cd92da162168 \
    --hash=sha256:816ff0a6550ffc06c098ccd2e0698600f9aa7da192a79eaa6f9af504a35db869 \
    --hash=sha256:82a36973cf8a2ef5406f4fe2edbf8ed0c99629535d959e0b100c76a32535a111 \
    --hash=sha256:837b396ca3d7b74091ca623f6cbd8351bd42d670a79c2683e79fb089f06a2de5 \
    --hash=sha256:850a08d167dde16db8702c274f320c7be9d7da6f6dff2b58b18f9e815bd94f5b \
    --hash=sha256:8816f3d218beb4b787de5c9759c259b8fa61f9dec42dc7811f320a33771778b7 \
    --hash=sha256:892a881d5f68c2b9ea304b7a6c2c60d9343df578a311b0f86b94bc8f1ffe8129 \
    --hash=sha256:895395f8918627b04efb1ad2a4cf605387143300ba03304cd1dfa6d03f5e095e \
    --hash=sha256:8b10e3e8fd7ddc2bd915848a2768e44c15b22936f1cc54c462ad1164deb02655 \
    --hash=sha256:8e24d8f05fa2d28513d94e877e9c75ad66175376209b3977f916e240e623193c \
    --hash=sha256:8feeac04b5794e513e710af2f9c87d49f31a6dc47967bb264a1fed61a8989bec \
    --hash=sha256:9432f3598db432cb51c5b37fdbf29a60fcccc79e30d37a05022776a6bc4ab689 \
    --hash=sha256:976e1128455aa595ea04c79ccfedff1aaeab96ee013fcc916bed120c4f0ad94f \
    --hash=sha256:978e7b97d4824b5be09c69fb70507cbde3b0323fc147332ca40a94d9a6a0ebbf \
    --hash=sha256:97bf8de4d541598c94a59344eeb988a94c08ff76b5723c41f6567ec18c7892ea \
    --hash=sha256:97cf3eb53a8cccacf9d46686a0926186c9bfb5574f2ed66d3639d5fe117cd3a9 \
    --hash=sha256:9b68938dd5b0c783d88ff8e2dcc69451b5eb936fe212d516b21b9d5567f6d464 \
    --hash=sha256:9c4b71f10dd532fb7a5cbc8f58707779e64f03a258c2bf8bfbaecfcd9970b519 \
    --hash=sha256:9f47b8a949e60f027f0aa0a6f6c7b7e9c55cbf4380d10b344e282fa4e7ab1e1b \
    --hash=sha256:a1dee1b804ff4d11c663636cf15d2ea47e9f79cd56c033fb1cbf08924842a48f \
    --hash=sha256:a2468d93d181667a7abd66e1b64bb9f76f361b0fef8faddf687456453576f5ee \
    --hash=sha256:a2a5e1d0ff29adddc9f6d6821a66302e4493f8ca898b715b6b1182c2c201ea0a \
    --hash=sha256:a39ac25a9a2fa4072efdb429833c4a4c8009a51ff9eea3eeae131713cd27991e \
    --hash=sha256:a445486499897b88a7d6c310c88ed64dd37b1b59bfd7ae9107490bbb362f47d6 \
    --hash=sha256:a91c17edf6eea2402cb5457b4c89e99bc5ed1004aa34c4adf1d4258c1a5c22c2 \
    --hash=sha256:ab4b66edffb32d9e951efb3814bd104b8367a7501b81b955cacb5726d897389f \
    --hash=sha256:aca6c767f552b21b10f774aeac128e828eafb796adfa1b666a18bf6321453c3a \
    --hash=sha256:acf8a67ba51f4ca9ddbd0e6b3000a65ac51ab734661778b3e7ba64d99a710f2f \
    --hash=sha256:b10ec717381bdbfafef34607824db4c91de69ff085e4fca3b2af91b4fa17e68a \
    --hash=sha256:b49924c73a235e969511bf2aabdff3beebf9820931f646c80274d5d780010c47 \
    --hash=sha256:b6acfb46a814762367fb7ba0828b0a17d441b92ce249a0e007474c9072662dda \
    --hash=sha256:b7ca9034437b6022f941f4857459562ee00a560b97e7cce8a0ec5a74fc6766e0 \
    --hash=sha256:b98134087d9de723658d17a42c7d0da8d6e2ef08015dee7dc93889047315f5e4 \
    --hash=sha256:b9fe6fb92520e3fd61f2e49000b6911b188824f089b75973ea06d6267f0b476d \
    --hash=sha256:bce57638e08ac148e5778cce7feb968307a727d66f8e2274a543d0cf0c9ad6a3 \
    --hash=sha256:c14ad3bdc85ee7f318742c457ca3968a92126d144b15721c759033bfb06296c2 \
    --hash=sha256:c1c43ad4339643d70ebb8124e1305a7dab423001eff58bb41a0f731adbc98355 \
    --hash=sha256:c3471e5c4a949c26ec00a77f01df59096aa9495877de76fd60a980f8ee6be461 \
    --hash=sha256:c583b927a8838dab890706a6fa7573fbb8b70e24000ef9f7238e2d6f6435a5ed \
    --hash=sha256:c76fe65e607be28c7fd4d56fc3c42b1583aa058ce3408b7ad0fd540171d31f9f \
    --hash=sha256:c7ea57fc63aa7da93a1bd2d644e6577befae10c52c4e36377635eea1056a74f5 \
    --hash=sha256:cd5214352ae68f3b5e9af7768bdc5253695ee069675db3480518420b3be881f2 \
    --hash=sha256:cdbb78909f52b981d3b2d56b97328d71eb0b974c36bd77c920123a7ebb192829 \
    --hash=sha256:cdc8b74ecc48c0cb1e9607a05ec4e9e88db60a19ffcc9a1d5f9088ede40c8dc0 \
    --hash=sha256:d0a24b40877af2de4950252be9d21eaf7fb07660f3c2cae1f56c6b599ada5266 \
    --hash=sha256:d22a945598fb91236b4dd793a6e42e4f3dd7740bb5aace5ebd7d4c08d13bb575 \
    --hash=sha256:d2f9fc07a8042a8f95925b35c4f04f469707c981fc33245b6ca187cf5d2dd290 \
    --hash=sha256:d625a186a65201c23a9e3b8ed9c47e90a026e03256608cc91851c6709096844f \
    --hash=sha256:d925f3d9afd05a8c0fb3a1031463a8d59ebe5e2afad297e29c78be19e13b4e62 \
    --hash=sha256:e64e88d5585bea9ce95861079de72006c7fa6d3df4e3a3b65ba31eb979c15c9f \
    --hash=sha256:e652ab17569c94bff5475520f907b7148b8c24036a8ebbe5cf7cf7493d28579a \
    --hash=sha256:e7b891faeedeafba41b2983e5001a81b6a915b69544c7e7570d1989ce1c36ac7 \
    --hash=sha256:e80675d75ae2cd14372cb65cad5400d9347a3d3f6c13000183f22dfd027283ed \
    --hash=sha256:e9c134bb666dd54b778b9fc0d2b50cbb7f979b9e3716f26a88c9ab3b6fc1dd0f \
    --hash=sha256:eb7d8d0e5886a89a55d2eef490e272fa965a9d57c6b29a5b5088a7997ec2cad1 \
    --hash=sha256:ecb42011e12ee19cafbc312887cbf3546959fe02fbad44f272d4be5baa997615 \
    --hash=sha256:ef3fbbf161dc9351a2fe0422e51b129f9e97e42385bd0320b309c15f7d287dd8 \
    --hash=sha256:efd62a42486f1bda5d24cb4f63d15a3c7768375fe83d36f9417b4ad7a2fb20b3 \
    --hash=sha256:f077d0b97ab11fa7dcc633fca53515f290bca8a8a633e966d5b6d1879d9ed01a \
    --hash=sha256:f332f0e72a5a0400141f830744e141bf9f97917878dbe968669e8a7fefea78ff \
    --hash=sha256:f7b0ec93a2893de856652154d73b7ba622f26fa97726487dcac373de5f4c6084 \
    --hash=sha256:fa10ef4112775900e7a0661068635eb67b2ab824fbde764de6e0e21982a93db0 \
    --hash=sha256:fc5d783bd4a2387e97b8a2d5ec781cfb92b3d893bf82370548e99db5915935d3 \
    --hash=sha256:fc8515076c11f3cfdf4fb142dcca0fe384b1230a3b5415458ac84f3e0903ec13 \
    --hash=sha256:ff218293c9c806138dca139765e3b067621be52bcd93cdc14c7711be7ddc90a9
pydantic-settings==2.15.0 \
    --hash=sha256:0ba092c291c94baceb5eff768aa0d56400a457585bc0175925a5a5510303da42 \
    --hash=sha256:694b793e84f766ba76a90ebdefc01d0a9a045dab0382bee70393da93712ad117
pyjwt==2.15.1 \
    --hash=sha256:42d59d631f7768a1028a64c7ff581a9bf7519804daf91fc5b6c56e30eec5e193 \
    --hash=sha256:4f259e80cdfb6b3fc18a7de51fd1ef9ec79652f25019bae68975ca2468a34df8
pynacl==1.6.2 \
    --hash=sha256:018494d6d696ae03c7e656e5e74cdfd8ea1326962cc401bcf018f1ed8436811c \
    --hash=sha256:04316d1fc625d860b6c162fff704eb8426b1a8bcd3abacea11142cbd99a6b574 \
    --hash=sha256:22de65bb9010a725b0dac248f353bb072969c94fa8d6b1f34b87d7953cf7bbe4 \
    --hash=sha256:26bfcd00dcf2cf160f122186af731ae30ab120c18e8375684ec2670dccd28130 \
    --hash=sha256:2fef529ef3ee487ad8113d287a593fa26f48ee3620d92ecc6f1d09ea38e0709b \
    --hash=sha256:320ef68a41c87547c91a8b58903c9caa641ab01e8512ce291085b5fe2fcb7590 \
    --hash=sha256:3bffb6d0f6becacb6526f8f42adfb5efb26337056ee0831fb9a7044d1a964444 \
    --hash=sha256:44081faff368d6c5553ccf55322ef2819abb40e25afaec7e740f159f74813634 \
    --hash=sha256:46065496ab748469cdd999246d17e301b2c24ae2fdf739132e580a0e94c94a87 \
    --hash=sha256:5811c72b473b2f38f7e2a3dc4f8642e3a3e9b5e7317266e4ced1fba85cae41aa \
    --hash=sha256:622d7b07cc5c02c666795792931b50c91f3ce3c2649762efb1ef0d5684c81594 \
    --hash=sha256:62985f233210dee6548c223301b6c25440852e13d59a8b81490203c3227c5ba0 \
    --hash=sha256:68be3a09455743ff9505491220b64440ced8973fe930f270c8e07ccfa25b1f9e \
    --hash=sha256:834a43af110f743a754448463e8fd61259cd4ab5bbedcf70f9dabad1d28a394c \
    --hash=sha256:8845c0631c0be43abdd865511c41eab235e0be69c81dc66a50911594198679b0 \
    --hash=sha256:8a66d6fb6ae7661c58995f9c6435bda2b1e68b54b598a6a10247bfcdadac996c \
    --hash=sha256:8b097553b380236d51ed11356c953bf8ce36a29a3e596e934ecabe76c985a577 \
    --hash=sha256:a84bf1c20339d06dc0c85d9aea9637a24f718f375d861b2668b2f9f96fa51145 \
    --hash=sha256:a9f9932d8d2811ce1a8ffa79dcbdf3970e7355b5c8eb0c1a881a57e7f7d96e88 \
    --hash=sha256:bc4a36b28dd72fb4845e5d8f9760610588a96d5a51f01d84d8c6ff9849968c14 \
    --hash=sha256:c8a231e36ec2cab018c4ad4358c386e36eede0319a0c41fed24f840b1dac59f6 \
    --hash=sha256:c949ea47e4206af7c8f604b8278093b674f7c79ed0d4719cc836902bf4517465 \
    --hash=sha256:d071c6a9a4c94d79eb665db4ce5cedc537faf74f2355e4d502591d850d3913c0 \
    --hash=sha256:d29bfe37e20e015a7d8b23cfc8bd6aa7909c92a1b8f41ee416bbb3e79ef182b2 \
    --hash=sha256:fe9847ca47d287af41e82be1dd5e23023d3c31a951da134121ab02e42ac218c9
python-dotenv==1.2.4 \
    --hash=sha256:42269a8a5b3fd54ffa6f3d84b18abed50064717576b4ecf03dc4a55d8aa04fdc \
    --hash=sha256:f0d53e69935a851c0dcc78f3ab7aaccd8cabef0b92382b576b824212902873c0
python-multipart==0.0.32 \
    --hash=sha256:be54b7f3fa167bb83e4fcd936b887b708f4e57fe75911c02aebf53efaf8d938e \
    --hash=sha256:ff6d3f776f16878c894e52e107296ffc890e913c611b1a4ec6c44e2821fe2e23
pywin32==312 ; sys_platform == 'win32' \
    --hash=sha256:02ebca0f0242b75292e218065004310d6a477407c09fa449bfe4f6022bc0c0fc \
    --hash=sha256:17948aeadbdb091f0ced6ef0841620794e68327b94ee415571c1203594b7215c \
    --hash=sha256:3020656e34f1cf7faeb7bccd2b84653a607c6ff0c55ada85e6487d61716deabd \
    --hash=sha256:59aba5d5940842075343a5ddc6b11f1cdf0d1567fe745290359dfbcc7c2eb831 \
    --hash=sha256:5c1fbe4a937a73ae9297384a3da38518cbc694c68ad8a809b2e19acd350f03ed \
    --hash=sha256:5dbc35d2b5320dc07f25fa31269cfb767471002b17de5eb067d03da68c7cb2db \
    --hash=sha256:6017c58e12f6809fbb0555b75df144c2922a9ffd18e4b9b5afa863b6c1a9d950 \
    --hash=sha256:772235332b5d1024c696f11cea1ae4be7930f0a8b894bb43db14e3f435f1ff7e \
    --hash=sha256:7a27df850933d16a8eabfbaeb73d52b273e2da667f80d70b01a89d1f6828d02c \
    --hash=sha256:9fce94568364e0155e6dfb781ac5d95903be8baf28670632beab1b523f300daa \
    --hash=sha256:a4dd3a848290ef724347b19f301045831d8e802fa4464f491b98b1e0a081432e \
    --hash=sha256:a77a90fbb6881238d2ca9c6fd797b25817f3768fe78d214a90137ff055a75f5b \
    --hash=sha256:a8597d28f267b39074aef51fa593530082b39cbe5a074226096857b1fed2dfb9 \
    --hash=sha256:b2200a054ca6d6625c4842fc56a4976a4b47f96b73dbe5538c3f813a80359f47 \
    --hash=sha256:b457f6d628a47e8a7346ce22acb7e1a46a4a78b52e1d17e1af56871bd19a93bc \
    --hash=sha256:c2f03a0f73f804a13c2735b99392b0cd426bb4f2c4d0178e5ac966a0f21618d5 \
    --hash=sha256:c53e878d15a1c44788082bfe712a905433473aa38f86375b7cf8b45e3acbaaf9 \
    --hash=sha256:d11417d84412f859b722fad0841b3614459ed0047f7542d8362e77884f6b6e8a \
    --hash=sha256:d620900033cc7531e50727c3c8333091df5dd3ffe6d68cdca38c03f5821408d5 \
    --hash=sha256:dab4f65ac9c4e48400a2a0530c46c3c579cd5905ecd11b80692373915269208b \
    --hash=sha256:dc90147579a905b8635e1b0ec6514967dcb07e6e0d9c42f1477feef14cac23bb
pywin32-ctypes==0.2.3 ; sys_platform == 'win32' \
    --hash=sha256:8a1513379d709975552d202d942d9837758905c8d01eb82b8bcc30918929e7b8 \
    --hash=sha256:d162dc04946d704503b2edc4d55f3dba5c1d539ead017afa00142c38b9885755
pyyaml==6.0.3 \
    --hash=sha256:00c4bdeba853cc34e7dd471f16b4114f4162dc03e6b7afcc2128711f0eca823c \
    --hash=sha256:0150219816b6a1fa26fb4699fb7daa9caf09eb1999f3b70fb6e786805e80375a \
    --hash=sha256:02893d100e99e03eda1c8fd5c441d8c60103fd175728e23e431db1b589cf5ab3 \
    --hash=sha256:02ea2dfa234451bbb8772601d7b8e426c2bfa197136796224e50e35a78777956 \
    --hash=sha256:0f29edc409a6392443abf94b9cf89ce99889a1dd5376d94316ae5145dfedd5d6 \
    --hash=sha256:10892704fc220243f5305762e276552a0395f7beb4dbf9b14ec8fd43b57f126c \
    --hash=sha256:16249ee61e95f858e83976573de0f5b2893b3677ba71c9dd36b9cf8be9ac6d65 \
    --hash=sha256:1d37d57ad971609cf3c53ba6a7e365e40660e3be0e5175fa9f2365a379d6095a \
    --hash=sha256:1ebe39cb5fc479422b83de611d14e2c0d3bb2a18bbcb01f229ab3cfbd8fee7a0 \
    --hash=sha256:214ed4befebe12df36bcc8bc2b64b396ca31be9304b8f59e25c11cf94a4c033b \
    --hash=sha256:2283a07e2c21a2aa78d9c4442724ec1eb15f5e42a723b99cb3d822d48f5f7ad1 \
    --hash=sha256:22ba7cfcad58ef3ecddc7ed1db3409af68d023b7f940da23c6c2a1890976eda6 \
    --hash=sha256:27c0abcb4a5dac13684a37f76e701e054692a9b2d3064b70f5e4eb54810553d7 \
    --hash=sha256:28c8d926f98f432f88adc23edf2e6d4921ac26fb084b028c733d01868d19007e \
    --hash=sha256:2e71d11abed7344e42a8849600193d15b6def118602c4c176f748e4583246007 \
    --hash=sha256:34d5fcd24b8445fadc33f9cf348c1047101756fd760b4dacb5c3e99755703310 \
    --hash=sha256:37503bfbfc9d2c40b344d06b2199cf0e96e97957ab1c1b546fd4f87e53e5d3e4 \
    --hash=sha256:3c5677e12444c15717b902a5798264fa7909e41153cdf9ef7ad571b704a63dd9 \
    --hash=sha256:3ff07ec89bae51176c0549bc4c63aa6202991da2d9a6129d7aef7f1407d3f295 \
    --hash=sha256:41715c910c881bc081f1e8872880d3c650acf13dfa8214bad49ed4cede7c34ea \
    --hash=sha256:418cf3f2111bc80e0933b2cd8cd04f286338bb88bdc7bc8e6dd775ebde60b5e0 \
    --hash=sha256:44edc647873928551a01e7a563d7452ccdebee747728c1080d881d68af7b997e \
    --hash=sha256:4a2e8cebe2ff6ab7d1050ecd59c25d4c8bd7e6f400f5f82b96557ac0abafd0ac \
    --hash=sha256:4ad1906908f2f5ae4e5a8ddfce73c320c2a1429ec52eafd27138b7f1cbe341c9 \
    --hash=sha256:501a031947e3a9025ed4405a168e6ef5ae3126c59f90ce0cd6f2bfc477be31b7 \
    --hash=sha256:5190d403f121660ce8d1d2c1bb2ef1bd05b5f68533fc5c2ea899bd15f4399b35 \
    --hash=sha256:5498cd1645aa724a7c71c8f378eb29ebe23da2fc0d7a08071d89469bf1d2defb \
    --hash=sha256:5cf4e27da7e3fbed4d6c3d8e797387aaad68102272f8f9752883bc32d61cb87b \
    --hash=sha256:5e0b74767e5f8c593e8c9b5912019159ed0533c70051e9cce3e8b6aa699fcd69 \
    --hash=sha256:5ed875a24292240029e4483f9d4a4b8a1ae08843b9c54f43fcc11e404532a8a5 \
    --hash=sha256:5fcd34e47f6e0b794d17de1b4ff496c00986e1c83f7ab2fb8fcfe9616ff7477b \
    --hash=sha256:5fdec68f91a0c6739b380c83b951e2c72ac0197ace422360e6d5a959d8d97b2c \
    --hash=sha256:6344df0d5755a2c9a276d4473ae6b90647e216ab4757f8426893b5dd2ac3f369 \
    --hash=sha256:64386e5e707d03a7e172c0701abfb7e10f0fb753ee1d773128192742712a98fd \
    --hash=sha256:652cb6edd41e718550aad172851962662ff2681490a8a711af6a4d288dd96824 \
    --hash=sha256:66291b10affd76d76f54fad28e22e51719ef9ba22b29e1d7d03d6777a9174198 \
    --hash=sha256:66e1674c3ef6f541c35191caae2d429b967b99e02040f5ba928632d9a7f0f065 \
    --hash=sha256:6adc77889b628398debc7b65c073bcb99c4a0237b248cacaf3fe8a557563ef6c \
    --hash=sha256:79005a0d97d5ddabfeeea4cf676af11e647e41d81c9a7722a193022accdb6b7c \
    --hash=sha256:7c6610def4f163542a622a73fb39f534f8c101d690126992300bf3207eab9764 \
    --hash=sha256:7f047e29dcae44602496db43be01ad42fc6f1cc0d8cd6c83d342306c32270196 \
    --hash=sha256:8098f252adfa6c80ab48096053f512f2321f0b998f98150cea9bd23d83e1467b \
    --hash=sha256:850774a7879607d3a6f50d36d04f00ee69e7fc816450e5f7e58d7f17f1ae5c00 \
    --hash=sha256:8d1fab6bb153a416f9aeb4b8763bc0f22a5586065f86f7664fc23339fc1c1fac \
    --hash=sha256:8da9669d359f02c0b91ccc01cac4a67f16afec0dac22c2ad09f46bee0697eba8 \
    --hash=sha256:8dc52c23056b9ddd46818a57b78404882310fb473d63f17b07d5c40421e47f8e \
    --hash=sha256:9149cad251584d5fb4981be1ecde53a1ca46c891a79788c0df828d2f166bda28 \
    --hash=sha256:93dda82c9c22deb0a405ea4dc5f2d0cda384168e466364dec6255b293923b2f3 \
    --hash=sha256:96b533f0e99f6579b3d4d4995707cf36df9100d67e0c8303a0c55b27b5f99bc5 \
    --hash=sha256:9c57bb8c96f6d1808c030b1687b9b5fb476abaa47f0db9c0101f5e9f394e97f4 \
    --hash=sha256:9c7708761fccb9397fe64bbc0395abcae8c4bf7b0eac081e12b809bf47700d0b \
    --hash=sha256:9f3bfb4965eb874431221a3ff3fdcddc7e74e3b07799e0e84ca4a0f867d449bf \
    --hash=sha256:a33284e20b78bd4a18c8c2282d549d10bc8408a2a7ff57653c0cf0b9be0afce5 \
    --hash=sha256:a80cb027f6b349846a3bf6d73b5e95e782175e52f22108cfa17876aaeff93702 \
    --hash=sha256:b30236e45cf30d2b8e7b3e85881719e98507abed1011bf463a8fa23e9c3e98a8 \
    --hash=sha256:b3bc83488de33889877a0f2543ade9f70c67d66d9ebb4ac959502e12de895788 \
    --hash=sha256:b865addae83924361678b652338317d1bd7e79b1f4596f96b96c77a5a34b34da \
    --hash=sha256:b8bb0864c5a28024fac8a632c443c87c5aa6f215c0b126c449ae1a150412f31d \
    --hash=sha256:ba1cc08a7ccde2d2ec775841541641e4548226580ab850948cbfda66a1befcdc \
    --hash=sha256:bdb2c67c6c1390b63c6ff89f210c8fd09d9a1217a465701eac7316313c915e4c \
    --hash=sha256:c1ff362665ae507275af2853520967820d9124984e0f7466736aea23d8611fba \
    --hash=sha256:c2514fceb77bc5e7a2f7adfaa1feb2fb311607c9cb518dbc378688ec73d8292f \
    --hash=sha256:c3355370a2c156cffb25e876646f149d5d68f5e0a3ce86a5084dd0b64a994917 \
    --hash=sha256:c458b6d084f9b935061bc36216e8a69a7e293a2f1e68bf956dcd9e6cbcd143f5 \
    --hash=sha256:d0eae10f8159e8fdad514efdc92d74fd8d682c933a6dd088030f3834bc8e6b26 \
    --hash=sha256:d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f \
    --hash=sha256:ebc55a14a21cb14062aa4162f906cd962b28e2e9ea38f9b4391244cd8de4ae0b \
    --hash=sha256:eda16858a3cab07b80edaf74336ece1f986ba330fdb8ee0d6c0d68fe82bc96be \
    --hash=sha256:ee2922902c45ae8ccada2c5b501ab86c36525b883eff4255313a253a3160861c \
    --hash=sha256:efd7b85f94a6f21e4932043973a7ba2613b059c4a000551892ac9f1d11f5baf3 \
    --hash=sha256:f7057c9a337546edc7973c0d3ba84ddcdf0daa14533c2065749c9075001090e6 \
    --hash=sha256:fa160448684b4e94d80416c0fa4aac48967a969efe22931448d853ada8baf926 \
    --hash=sha256:fc09d0aa354569bc501d4e787133afc08552722d3ab34836a80547331bb5d4a0
referencing==0.37.0 \
    --hash=sha256:381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231 \
    --hash=sha256:44aefc3142c5b842538163acb373e24cce6632bd54bdb01b21ad5863489f50d8
rpds-py==2026.6.3 \
    --hash=sha256:0be972be84cfcaf46c8c6edf690ca0f154ac17babf1f6a955a51579b34ad2dc5 \
    --hash=sha256:127565fead0a10943b282957bd5447804ff3160ad79f2ad2635e6d249e380680 \
    --hash=sha256:127e08c0642d880cf32ca47ec2a4a77b901f7e2dd1ad9762adb13955d72ffcc9 \
    --hash=sha256:166cf54d9f44fc6ceb53c7860258dde44a81406646de79f8ed3234fca3b6e538 \
    --hash=sha256:168c733a7112e071bb7a66460e667edfcff06c017a3c523f7a8a8e08d0140804 \
    --hash=sha256:1967debc37f64f2c4dc90a7f563aec558b471966e12adcac4e1c4240496b6ebf \
    --hash=sha256:1cebd1337c242e4ec2293e541f712b2da849b29f48f0c293684b71c0632625d4 \
    --hash=sha256:1cf01971c4f2c5553b772a542e4aaf191789cd331bc2cd4ff0e6e65ba49e1e97 \
    --hash=sha256:1e5822dfc2f0d4ab7e745eaa6d85945069329beeccef965af3f3bb26058fcab6 \
    --hash=sha256:22bffe6042b9bcb0822bcd1955ec00e245daf17b4344e4ed8e9551b976b63e96 \
    --hash=sha256:23a439f31ccbeff1574e24889128821d1f7917470e830cf6544dced1c662262a \
    --hash=sha256:24e9c5386e16669b674a69c156c8eeefcb578f3b3397b713b08e6d60f3c7b187 \
    --hash=sha256:270b293dae9058fc9fcedab50f13cebf46fb8ed1d1d54e0521a9da5d6b211975 \
    --hash=sha256:29dfa0533a5d4c94d4dfa1b694fcb56c9c63aad8330ffdd816fd225d0a7a162f \
    --hash=sha256:2a9c6f195058cb45335e8cc3802745c603d716eb96bc9625950c1aac71c0c703 \
    --hash=sha256:2bfd04c19ddbd6640de0b51894d764bd2758854d5b75bd102d2ef10cb9c293a9 \
    --hash=sha256:2c54a076ca4d370980ab57bc0e31df57bbe8d41340436a90ef8b1219a3cbb127 \
    --hash=sha256:2c958bf94822e9290a40aaf2a822d4bc5c88099093e3948ad6c571eca9272e5f \
    --hash=sha256:2c99f7e8ccb3dd6e3e4bfeac657a7b208c9bac8075f4b078c02d7404c34107fa \
    --hash=sha256:2f7c26fbc5acd2522b95d4177fe4710ffd8e9b20529e703ffbf8db4d93903f05 \
    --hash=sha256:30c6dc199b24a5e3e81d50da0f00858c5bbdb2617a750395687f4339c5818171 \
    --hash=sha256:38a2fea2787428f811719ceb9114cb78964a3138838320c29ac39526c79c16ba \
    --hash=sha256:3a83ae6c67b7676b9878378547ca8e93ed77a580037bcbcd1d32f739e1e6089c \
    --hash=sha256:3cfe765c1da0072636ca06628261e0ea05688e160d5c8a03e0217c3854037223 \
    --hash=sha256:421aba32367055614287a4292b6a17f1939c9452299f7a0209c117e990b646d4 \
    --hash=sha256:425560c6fa0415f27261727bb20bd097568485e5eb0c121f1949417d1c516885 \
    --hash=sha256:4470ce197d4090875cf6affbf1f853338387428df97c4fb7b7106317b8214698 \
    --hash=sha256:4cf2d36a2357e4d07bb5a4f98801265327b48256867816cfd2ceb001e9754a8f \
    --hash=sha256:4f4bca01b63096f606e095734dd56e74e175f94cfbf24ff3d63281cec61f7bb7 \
    --hash=sha256:501f9f04a588d6a09179368c57071301445191767c64e4b52a6aa9871f1ef5ed \
    --hash=sha256:536bceea4fa4acf7e1c61da2b5786304367c816c8895be71b8f537c480b0ea1f \
    --hash=sha256:538949e262e46caa31ac01bdb3c1e8f642622922cacbabbae6a8445d9dc33eaf \
    --hash=sha256:539d75de9e0d536c84ff18dfeb805398e58227001ce09231a26a08b9aed1ee0e \
    --hash=sha256:54f45a148e28767bf343d33a684693c70e451c6f4c0e9904709a723fafbdfc1f \
    --hash=sha256:55927d532399c2c646100ff7feb48eaa940ad70f42cd68e1328f3ded9f81ca24 \
    --hash=sha256:58eadac9cd119677b60e1cf8ac4052f35949d71b8a9e5556efccbe82533cf22a \
    --hash=sha256:5e8d07bddee435a2ff6f1920e18feff28d0bc4533e42f4bf6927fbd073312c41 \
    --hash=sha256:62698275682bf121181861295c9181e789030a2d516071f5b8f3c23c170cd0fc \
    --hash=sha256:639c8929aa0afe81be836b04de888460d6bed38b9c54cfc18da8f6bfabf5af5d \
    --hash=sha256:67e3a721ffc5d8d2210d3671872298c4a84e4b8035cfe42ffd7cde35d772b146 \
    --hash=sha256:6de4744d05bd1aa1be4ed7ea1189e3979196808008113bbbf899a460966b925e \
    --hash=sha256:6e84adbcf4bf841aed8116a8264b9f50b4cb3e7bd89b516122e616ac56ca269e \
    --hash=sha256:7491ee23305ac3eb59e492b6945881f5cd77a6f731061a3f25b77fd40f9e99a4 \
    --hash=sha256:79486287de1730dbaff3dbd124d0ca4d2ef7f9d29bf2544f1f93c09b5bcbbd12 \
    --hash=sha256:7b689145a1485c335569bd056464f3243a29af7ed3871c7be31ad624ba239bc7 \
    --hash=sha256:7f88d653e7b3b779d71ae7454e20dcc9b6bae903f33c269db9f2be41bda3f261 \
    --hash=sha256:8020133a74bd81b4572dd8e4be028a6b1ebcd70e6726edc3918008c08bee6ee6 \
    --hash=sha256:808345f53cb952433ca2816f1604ff3515608a81784954f38d4452acfe8e61d5 \
    --hash=sha256:83e35b57523816c8613fd0776b40cd8bb9f596b37ddd2692eb4a6bb5ab2f8c93 \
    --hash=sha256:842e7b070435622248c7a2c44ae53fa1440e073cc3023bc919fed570884097a7 \
    --hash=sha256:847927daf4cffbd4e90e42bc890069897101edd015f956cb8721b3473372edda \
    --hash=sha256:882076c00c0a608b131187055ddc5ae29f2e7eaf870d6168980420d58528a5c8 \
    --hash=sha256:8b95977e7211527ab0ba576e286d023389fbeeb32a6b7b771665d333c60e5342 \
    --hash=sha256:8bb68f03f395eb793220b45c097bd4d8c32944393da0fad8b999efac0868fc8c \
    --hash=sha256:8c2642a7603ec0b16ed77da4555db3b4b472341904873788327c0b0d7b95f1bb \
    --hash=sha256:8c3d1e9c15b9d51ca0391e13da1a25a0a4df3c58a37c9dc368e0736cf7f69df0 \
    --hash=sha256:8c6e5a2f750cc71c3e3b11d71661f21d6f9bc6cebc6564b1466417a1ec03ec77 \
    --hash=sha256:8d2294a31386bfa251d8c8a39472beee17db67d4f1a6eabea665d35c9a4461c3 \
    --hash=sha256:8e4320744c1ffdd95a603def63344bfab2d33edeab301c5007e7de9f9f5b3885 \
    --hash=sha256:8e65860d238379ed982fd9ba690579b5e95af2f4840f99c772816dbe573cb826 \
    --hash=sha256:8f2e5c5ee828d42cb11760761c0af6507927bec42d0ad5458f97c9203b054617 \
    --hash=sha256:900a67df3fd1660b035a4761c4ce73c382ea6b35f90f9863c36c6fd8bf8b09bb \
    --hash=sha256:913ca42ccad3f8cc6e292b587ae8ae49c8c823e5dce51a736252fc7c7cdfa577 \
    --hash=sha256:9250a9a0a6fd4648b3f868da8d91a4c52b5811a62df58e753d50ae4454a36f80 \
    --hash=sha256:931908d9fc855d8f74783377822be318edb6dcb19e47169dc038f9a1bf60b06e \
    --hash=sha256:9826217f048f620d9a712672818bf231442c1b35d96b227a07eabd11b4bb6945 \
    --hash=sha256:9891e594296ab9dada6551c8e7b387b2721f27a67eecd528412e8906247a7b90 \
    --hash=sha256:9c1255b302953c86a486b81d330d5ee1d5bd937691ce271b6be0ef0e299eaab7 \
    --hash=sha256:a0811d33247c3d6128a3001d763f2aa056bb3425204335400ac54f89eec3a0d0 \
    --hash=sha256:a136d453475ac0fcbda502ef1e6504bd28d6d904700915d278deeab0d00fe140 \
    --hash=sha256:a214c993455f99a89aaeadc9b21241900037adc9d97203e374d75513c5911822 \
    --hash=sha256:a3086b538543802f84c843911242db20447de00d8752dd0efc936dbcf02218ba \
    --hash=sha256:a3450b693fde92133e9f51060568a4c31fcca76d5e53bbd611e689ca446517e9 \
    --hash=sha256:a550fb4950a06dde3beb4721f5ad4b25bf4513784665b0a8522c792e2bd822a4 \
    --hash=sha256:a9f4645593036b81bbdb36b9c8e0ea0d1c3fee968c4d59db0344c14087ef143a \
    --hash=sha256:aca6c1ef08a82bfe327cc156da694660f599923e2e6665b6d81c9c2d0ac9ffc8 \
    --hash=sha256:acac386b453c2516111b50985d60ce46e7fadb5ea71ae7b25f4c946935bf27cf \
    --hash=sha256:acc992ab27b15f852c76755eb2ab7dce86585ddadba6fa5946e58556088845b4 \
    --hash=sha256:ae3d4fe8c0b9213624fdce7279d70e3b148b682ca20719ebd193a23ebfa47324 \
    --hash=sha256:ae50181a047c871561212bb97f7932a2d45fb53e947bd9b57ebad85b529cbc53 \
    --hash=sha256:ae6dd8f10bd17aad820876d24caec9efdafd80a318d16c0a48edb5e136902c6b \
    --hash=sha256:af05d726809bff6b141be124d4c7ce998f9c9c7f30edb1f46c07aa103d540b41 \
    --hash=sha256:afd70d95892096cdb26f15a00c45907b17817577aa8d1c76b2dcc2788391f9e9 \
    --hash=sha256:b5c2dc92304aa48a4a60443b548bb12f12e119d4b72f314015e67b9e1be97fca \
    --hash=sha256:bc0011654b91cc4fb2ae701bec0a0ba1e552c0714247fa7af6c59e0ccfa3a4e1 \
    --hash=sha256:bcfbcf66006befb9fd2aeaa9e01feaf881b4dc330a02ba07d2322b1c11be7b5d \
    --hash=sha256:bdbd97738551fca3917c1bd7188bec1920bb520104f28e7e1007f9ceb17b7690 \
    --hash=sha256:c60924535c75f1566b6eb75b5c31a48a43fef04fa2d0d201acbad8a9969c6107 \
    --hash=sha256:c7b9a2f8f4d8e90af72571d3d495deebdd7e3c75451f5b41719aee166e940fc2 \
    --hash=sha256:ca6546b66be9dc4738b1b043d5ebd5488c66c578c5ff0fd0e8065313fe3afb76 \
    --hash=sha256:ccffae9a092a00deb7efd545fe5e2c33c33b88e7c054337e9a74c179347d0b7d \
    --hash=sha256:cdc7e35386f3847df728fbcb5e887e2d79c19e2fa1eba9e51b6621d23e3243af \
    --hash=sha256:d15fde0e6fb0d88a60d221204873743e5d9f0b7d29165e62cd86d0413ad74ba6 \
    --hash=sha256:d34c20167764fbcf927194d532dd7e0c56772f0a5f943fa5ef9e9afbba8fb9db \
    --hash=sha256:d483fe17f01ad64b7bf7cc38fcefff1ca9fb83f8c2b2542b68f97ffe0611b369 \
    --hash=sha256:d7469697dce35be237db177d42e2a2ee26e6dcc5fc052078a6fefabd288c6edd \
    --hash=sha256:db08f45aecde626498fb3df07bcf6d2ec040af42e859a4f5040d79c200342911 \
    --hash=sha256:dc319e5a1de4b6913aac94bf6a2f9e847371e0a140a43dd4991db1a09bc2d504 \
    --hash=sha256:de3eceba0b683bcbb1ab93da016d0270df1f9ae7be716b40214c5dafac6ea45a \
    --hash=sha256:dfcc8b909769d19db55c7cc9541eb64b9b774b1057ffffb4f1048070475bb9f9 \
    --hash=sha256:e059c5dde6452b44424bd1834557556c226b57781dee1227af23518459722b13 \
    --hash=sha256:e4316bf32babbed84e691e352faf967ce2f0f024174a8643c37c94a1080374fc \
    --hash=sha256:e52655eaf81e32593abedaa4bfe33170c8cfedf3365ed9be6e11e07f148f0278 \
    --hash=sha256:e55d236be29255554da47abe5c577637db7c24a02b8b46f0ca9524c855801868 \
    --hash=sha256:ea7bb13b7c9a29791f87a0387ba7d3ad3a6d783d827e4d3f27b40a0ff44495e2 \
    --hash=sha256:ea964164cc9afa72d4d9b23cc28dafae93693c0a53e0b42acbff15b22c3f9ddd \
    --hash=sha256:ec829541c45bca16e61c7ae50c20501f213605beb75d1aba91a6ee37fbbb56a4 \
    --hash=sha256:ecabd69db66de867690f9797f2f8fa27ba501bbc24540cbdbdc649cd15888ba6 \
    --hash=sha256:ed0c1e5d10cdc7135537988c74a0188da68e2f3c30813ba3744ab1e42e0480f9 \
    --hash=sha256:f0840b5b17057f7fd918b76183a4b5a0635f43e14eb2ce60dce1d4ee4707ea00 \
    --hash=sha256:f4d78253f6996be4901669ad25319f842f740eccf4d58e3c7f3dd39e6dde1d8f \
    --hash=sha256:f56f1695bc5c0871cbc33dc0130fcf503aab0c57dcc5a6700a4f49eba4f2652e \
    --hash=sha256:f826877d462181e5eb1c26a0026b8d0cab05d99844ecb6d8bf3627a2ca0c0442 \
    --hash=sha256:f8f23ead891a3b762f35ab3b04623da7056545b48aa60d59957e6789914545da \
    --hash=sha256:f90938e92afda60266da758ee7d363447f7f0138c9559f9e1811629580582d90 \
    --hash=sha256:faa679d19a6696fd54259ad321251ad77a13e70e03dd834daa762a44fb6196ef
secretstorage==3.5.0 ; sys_platform == 'linux' \
    --hash=sha256:0ce65888c0725fcb2c5bc0fdb8e5438eece02c523557ea40ce0703c266248137 \
    --hash=sha256:f04b8e4689cbce351744d5537bf6b1329c6fc68f91fa666f60a380edddcd11be
sse-starlette==3.5.0 \
    --hash=sha256:3e6e1070df3f0f5d9cea81496de92dbb72f6721871d99748ece67441dd8b7997 \
    --hash=sha256:75de713aa8a9441513cc283220826da079d982770965b951e9437720e8bafdb2
starlette==1.7.0 \
    --hash=sha256:67f8e99895493dd2911a03f11314af6ceebeae4e704bb9f43dfc6a9db151c93e \
    --hash=sha256:c79f74ea63cff761804fbbfb182f1e0b440c2d07b164d24700c5a1bab5d6ff5d
tomlkit==0.15.1 \
    --hash=sha256:177a05aece5a8ca5266fd3c448abb47b8d352f09d477d3ca8332db4d89b24304 \
    --hash=sha256:e25bbf38843005246210a12982776f27f99cb9be67160e14434d0c0d21ee1e97
trove-classifiers==2026.9.21.13 \
    --hash=sha256:0a9ebc8d4e2f3e8a22848c5258033035bec17a3012ac3fea16dbaa764489eb71 \
    --hash=sha256:8b1ff4f9c191b1040b71c37f1e445ab99732911e3cd91de52838453a854d7a17
truststore==0.10.4 \
    --hash=sha256:9d91bd436463ad5e4ee4aba766628dd6cd7010cf3e2461756b3303710eebc301 \
    --hash=sha256:adaeaecf1cbb5f4de3b1959b42d41f6fab57b2b1666adb59e89cb0b53361d981
typing-extensions==4.16.0 \
    --hash=sha256:481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8 \
    --hash=sha256:dc983d19a509c94dba722ee6abd33940f7c05a89e243c47e907eb4db6f1a43e5
typing-inspection==0.4.4 \
    --hash=sha256:547274fa6b0a561ccf549cc9524b999a578e737d015d8709d021f9d0d13bea47 \
    --hash=sha256:65b8397ba37ccbce054456aaccddfc91e6e3083c92824df348d96ca832f3f147
uvicorn==0.54.0 \
    --hash=sha256:505bdb0f318731d45f1f712071fc781a8981f6847a31c902c9f5e652d4f67faf \
    --hash=sha256:a2e33cbfaa0306f8e6b0c13e0cb89d7d7a2da3e62b90c66e18c33d9807b28620
uvloop==0.23.0 ; platform_python_implementation != 'PyPy' and sys_platform != 'cygwin' and sys_platform != 'win32' \
    --hash=sha256:0305871ac712f54b62af73f943dbf21ae3ce80a44bc0f0151424484affa85645 \
    --hash=sha256:090865d8ce7a03986755a3ce711b7dd0d4b44eb14ab74368b717f3fad1180208 \
    --hash=sha256:098a85e1393ef5202767b7e5fb41a32cd8bd81e6ee4af364c179801c4aa3f6d4 \
    --hash=sha256:0efdd55bddbd36bb2fcb842d64c0d5f6407c6958c68088cc25df8c09edc5b5fd \
    --hash=sha256:12634f15e6625f78b3f2922f91404c4d7173487eba11746764153f556e9852dc \
    --hash=sha256:1748321e3c59a14a75404b1ae8d5a8d81c4e201803ea0e14c1b6fd84421024b5 \
    --hash=sha256:19c64108b507cd0bc140e400e3396bacebd9d504956aa7726272bf6de7d9aabb \
    --hash=sha256:1e84575f11873c109cf3962ad0bdf679094466184125f4cadcc41a73febff41f \
    --hash=sha256:24c58ae4a83e93a04c504bcc678125e36a0bfc44af928ad69444880c60f187a5 \
    --hash=sha256:28d160f51ab4da3b187063652e643dea6831072add4adc1e6d62afbe73b6be27 \
    --hash=sha256:2dcff2d69be43e6559e5dad2c5a7a2dbfb60e05a77311b6c4b7a4a8123d86c65 \
    --hash=sha256:31e0cf90bc8fd88784f6802cdba968a51fb1aec1cc3feec74d862b2d371d1330 \
    --hash=sha256:378188efbb1524f2219d05246a3e1e5907217848d2882144dff59585f1b81d55 \
    --hash=sha256:42feced24b9b44b856c633eafb5cc5dec354972da55ce77598db6844c054bc7c \
    --hash=sha256:4448e9124537620f9c25d004c227bb5104440b58955c19bbd312d910af919a63 \
    --hash=sha256:4a08875543bbd4519faf30497506c9cda8a48470467ffdf967c7313c7a5981a8 \
    --hash=sha256:4b8e207c67d207a8608fec57e116511030af3495dc0109b8c333cf9cb412b16f \
    --hash=sha256:4bb7f5d0b62b5afaaaea2b7b60d508921c24b0fe39c22c1438bec1811ffe10ec \
    --hash=sha256:4f1798f56c6f4ba5ac11fa2869e5717926e4470d97a1dd42b4f59219d43b5027 \
    --hash=sha256:514698d3683189031dcbfdc31e87115992e5ce9e1b19fe5359941323f2df800c \
    --hash=sha256:53c2c5d7e2024e46776c2d90e6c637d01102126b61aaf5faa5edaf05f8b5722a \
    --hash=sha256:55d6f4135d914305929fe9e9c44d8b5383a9b3fa1bee3bfcf60ee97e01af07ea \
    --hash=sha256:5a2bbad3a63007f7e9524d4903ba04fee252557c2acd86f9a3d4f91786695254 \
    --hash=sha256:5a3e0f56ec19bfd9ad1605572878dd6ff7f01b325f4fc154812ae70d615c3aff \
    --hash=sha256:5bb9be71d9ee39b4359b832f9569518ec9bc08704194034e79e4958e6bc4d46d \
    --hash=sha256:60ec798c40a1810d282ee046f61ecac1c5675cb898763d9f08d97d53a5e00a81 \
    --hash=sha256:6b3cbc4f96ddfa1fb88a78a69dd851369825b7816d9702eee8c4461505ba172e \
    --hash=sha256:6c7ef4701a96553514b2688e342ef1bf2beae6cfd172d89a76c768292aabf405 \
    --hash=sha256:7337b06a9f9ed9ea3049f04b76f65819db9b19bb832ee598e97b388eadf25e5f \
    --hash=sha256:76345f51367fb1f23e08605c6efb18374f669be5b223658fbab6b17627950507 \
    --hash=sha256:7e35c9bc977760981693e1a7a51493b58ee5a501f9ebb1e547565ee40b6c6208 \
    --hash=sha256:80cac5cb90ed7b9b72a217a1d6982b15b829cdbd0ee6bc19b93e3a9e47fb0ac9 \
    --hash=sha256:8af88fe5c7dd68fe1fec6dea8155caa1a47155d219a750ff34049541cf536a5e \
    --hash=sha256:8fcd721113260ffb5e38bf14a8725b17d431f34209f7d1c7005b667946e630b3 \
    --hash=sha256:93087a845cdfb35753e539354ac9551bdd2ff528c202a98df0ae46e852bcf021 \
    --hash=sha256:93935ab27b6eaef4c3e5489aebc84284f0644592f7ab516df60ee1b27eaf5eb3 \
    --hash=sha256:9bf08e4b6362dd1c08623bbfa2d061e8bac0f1da8fc2007062cfe1dc360a49fa \
    --hash=sha256:a6ac96da66c35bf789bdcde78a88dc7d56b7907d8379648c54adc1c61594575d \
    --hash=sha256:ab17b3a8aa754be0de0e397f7b95f13b14e56f077a4c6ae295e3d4afd199b325 \
    --hash=sha256:b0d106d9314546d69b3df1b5352639aa628530ec3ecef8a98a21942d2a2a64f5 \
    --hash=sha256:b90397a50ad6332ed3e459c648ac20d182cce24a557354363ad85fc9ea4a17cd \
    --hash=sha256:bbbdb8fcd5e7062e546eec1ac78c28bb21ae7df54c18f8e4b06e15a18d661a49 \
    --hash=sha256:bd6f2f81c7b9da99d301c0b16b82044e76fe887086e42e1590ecf520b94dbdac \
    --hash=sha256:be53e1d5f83de43dc175c87612ecc128d444b38e5c56cb3f807f5a73d6887476 \
    --hash=sha256:c3f23f403a273900d57de6ee5ca0614c650f7f58563065dad1a4744498960e53 \
    --hash=sha256:cbe8d03d4efcccdb7fcedecbaa1e1fa02913eaf3a74cb933634a6bc6d2ea9e2a \
    --hash=sha256:ce17bc317d089f361b33521654c13e30eacfd3d2034fd34e613ca9c51c969686 \
    --hash=sha256:d918d6f304a309222a784bbd140b85ec5594d97e4dc0e79f590549d28970663a \
    --hash=sha256:dc61e4f9e37b507069dc7e659ae28bca7adcb04c993c3508214315d12c63f848 \
    --hash=sha256:e095f9e105af76593b4c183bb0bcbdae64bd913a59ec595732dc108b48730ab5 \
    --hash=sha256:e2cba180d6451822763eda8364f342435a873bcfb3849cbd82fdeca248ca65eb \
    --hash=sha256:e49eba8f1e28e7c03648b7a476e1ba05309e087ccdea859fc6dd659564aa8d7e \
    --hash=sha256:f1341c6abcee1c31277cfe28d34e46196f2143ec3d755e6efe7452126e1f626d \
    --hash=sha256:f3fbfe82829d8e381426a289b87e59e585278728361db9ce975b88b51f64f410 \
    --hash=sha256:f50b580fad005a092ed87c5a3a4683459b21d1620497d6a5bccad203bee4c071 \
    --hash=sha256:f5576e8ae1723ece60d8f93c6710abf784714e99388bcf023ba9ca800bc587f6 \
    --hash=sha256:f673d835bdb1a60229cc3609a113fd2c9ce3f4a3c75ad4eaed111180c00199d2 \
    --hash=sha256:f7548ede3ee908cfabc0d068106e303a9a2d811af959cdf6ab85676344cedcda \
    --hash=sha256:fa8ed556fcc87a4091cf61587ef172fa104323dc89ecc085a618ba7ff8629a8f \
    --hash=sha256:fefea5cf8cdda9053b962ca8a90216fb0b1d40907dcb6819382b42e483e6e9f6 \
    --hash=sha256:ff7144d8167e513fe39fbb46bffb4f6f192dfb1f4b0b4e9102e1fd4f212e4747
watchfiles==1.3.0 \
    --hash=sha256:000b9688fc8133037a8b075c8ebf98f32844ff8964dda61e85c1db547dafc441 \
    --hash=sha256:025b108f2d5cc2799cb941f79380df3e8b22bfb589c218e801767fe78d598c95 \
    --hash=sha256:04c5500faa725d69a99b0f63750e80795e455bb951849e9c98a811b4324997c4 \
    --hash=sha256:1acabde19b67e673274e89a04d613b7fb1f122e2c4b8ec9a581e59c149264b61 \
    --hash=sha256:26b81bc515a0f03f66a69a6fea86eea54c8eca4173c46dd7222569f79dd2f977 \
    --hash=sha256:380f513d26cc2e598266b88d66456e07d67ef4be8f0f435a1154d9c44b43d509 \
    --hash=sha256:45726c6b5a8d67c8087eb2933c4398948546d04206ef40f629dc4881d65d23d1 \
    --hash=sha256:4af9c464d410e8c44b58ddf1cbec7c3a02c1cb2c6c80df9c74659ba2fbda0ab5 \
    --hash=sha256:509d9f74d2bec5c1f4cd868ddcfe0c9601f7ea53066dfcb19d8ede742c4de661 \
    --hash=sha256:591de392458bca26f6130fea4e667c06b657e873ad334ea06fad5a79f5086cef \
    --hash=sha256:5ec46a1ff4c1d81405a5fc645abdbff5e4e9388f7c9a6cdb392316a7c29b884f \
    --hash=sha256:6398d250994baff581147ccba846223076fe6492ca93c0d1b3588fcf5355eb5c \
    --hash=sha256:7398930a2b76b9dc67a4e6b8bfc7baf30946892a86f417a3920c07bdd6febc30 \
    --hash=sha256:7c1125e99f84934a92996ae343501285617373acd66f16b59fd5654b27ad8d80 \
    --hash=sha256:81c989d7267bfb7b676cd32c83bec97914e396870983cbf493e29415037bff5e \
    --hash=sha256:99aee4a07847c06820765fd7b1b49ceac4f3f711ccb7d104655a33231de1c207 \
    --hash=sha256:a5b631db08fd3032db57ec6a92d1777cd60f88803287e4e941a4858c53aab1e0 \
    --hash=sha256:a85e243c87109d9f48a2e0d10d6abdee8768cc114848b32281ec83d7f81d86ef \
    --hash=sha256:b5768b49e426fd5b550b012c866db347cdf15c398ef98dc557b6e6b72fa74cd1 \
    --hash=sha256:bbc1198edfdc90fda0600f825aa94150f428dfcbf8138746f55998e0e660d64c \
    --hash=sha256:be9ef3cd403d756a304a0a08a112163c63da7ec72c8c9d083c98818291ff8f29 \
    --hash=sha256:ca39661934749df580d89f3dde266f2af7c6968f4c21c72ce2dc387d299e6aa7 \
    --hash=sha256:d36c72fcdc08f143d87316a4c4c3b064e340da2c7383d39803950740ed418935 \
    --hash=sha256:d4593392e87669836670f87d62fc754059eaeb0e6157af44060a46558cebe5a3 \
    --hash=sha256:d754e049006e81a9be49dc78ba7802081cee426e968cbc63ee19e164fa2d0e39 \
    --hash=sha256:d978cc1dd7ba44f5590d7de74f7a9c8be7262d9e469c2c0efb8bbfc2574321dc \
    --hash=sha256:da213822ec9082b62cadf3008e07a8c690ec7a3c89f6dc5e55a8cf07b56a1b26 \
    --hash=sha256:dd538c71766c59c732e2c5cedc39323c99c11897b99f93eac773438e54af206a \
    --hash=sha256:e0204f90677b7fb8d3a824279a71a01166bea9f6e53923b8056592d87b33b0b6 \
    --hash=sha256:e5871d4a7f788a9f64fb06f5793389d29d171e5c32d37c3ebfd520b017cc7694 \
    --hash=sha256:eb94e40b9a0db19636b5e3fed0a9803452ecc7381df13b385272abb779ee83ca \
    --hash=sha256:ec3cd4bb181a7b6329134204c2277c7144ab5f62cce9c5335d6f901ee7ce8d6a \
    --hash=sha256:f0c9865240e065a2247f4b5248528ae3d01e0e8ae071462c250c884dc16e3ee3
websockets==17.2 \
    --hash=sha256:01420cb1cb47433e8e7075d32cb8017ad3ffed0654bd1e48c0251b865920dec3 \
    --hash=sha256:0198c4ec6a3406a2f7557c032967de426474c2c995c81076585e09d29a9f407b \
    --hash=sha256:0360c4dc13ac569cc245e0efa2f4d4b1e4733d24c47b8ab3f3747227b1356348 \
    --hash=sha256:063508ce9e0db745f30ab52fc652f4e59efc79c2b74934b3837d5cdb974da620 \
    --hash=sha256:06c7386128a9d85de4e1960114604f3031c084d2f4eee8db382637f1634cbab1 \
    --hash=sha256:06e46da092bca3a52e98f0458c66b247993ce501a07cd09c858be3296511ab7d \
    --hash=sha256:06fa3ce9c3154826c33d4395b225b2994aa64f1f3bcd8be8ed932019175d9268 \
    --hash=sha256:08d90cf344bdb971ba3a826b78d4da9bfd56cc6a97a604d9b88cbd40bfa6c735 \
    --hash=sha256:08d97098644728bd1895caa7ecf3090b8e563d70809870d2adb33a107bd061d0 \
    --hash=sha256:0a6220bdf8d5f11af71251a599092d89ac1d6bfac691c7f5951c5b07953947a0 \
    --hash=sha256:0c8600aec354cc259f1691b0b42816f04a9886a953f82cb227246df76057f97a \
    --hash=sha256:1110fbfd530c447380e6e6db88b7e43ffe33d54178f5b0ff0aaa5a280301e668 \
    --hash=sha256:15a7101b660a9f15fac34108c92cefc9848f6753a50acef8869e3cd94148fdb7 \
    --hash=sha256:18b0a46e5e9b315e2b54ce8c3bafdeef0e1388ca363114fa868e6aab2dc58512 \
    --hash=sha256:19e2511412ad3393191de652513bc7a0ca3c93af143b32d96d46e59fbbddf1d4 \
    --hash=sha256:1c27339934109dfaca83f18ab2c23db06714e9d5deca2c8e37e8f492ab90d20b \
    --hash=sha256:1d829946a2e7630f92f9d7b45b62f3abe9f393cc2dea6a35edb3988f865e75f2 \
    --hash=sha256:1fdb8d5a1660307dc6d36d0b7fc725213cbd7f80800904dc4896aa3208b89121 \
    --hash=sha256:214da56dba368f61b3d745c77630b2d03c61c02da7b42fe80ef6efba079d3077 \
    --hash=sha256:222fb626fa15701a850eccc778be17312142b2f6a0e16aea80770b7459adb784 \
    --hash=sha256:27c7a59b5352a8f741b422820adfe89dfe47c8f2d84fb32111e76111edaa0e83 \
    --hash=sha256:2901bdf24f20bc884124b3e88c61f7ece260c20c81e610f2196007395264a4aa \
    --hash=sha256:2ab742249f953d148a9ba696c8b9944361e8cb92e8bc61ba2dd53a178403afd3 \
    --hash=sha256:2ab9af5cb7265899e659f079eb71691375a1025b6d5fbd3caa495dd08f70833a \
    --hash=sha256:2d39c19b1ba6a6791050383fd69efdd3b63533e2254693d0263879cd5f5921ba \
    --hash=sha256:2de1ccf298f5c9e0f27113836d742edb95f015eee3148f004ac386f7ba9a05b1 \
    --hash=sha256:30201a7f69833b015556c72feb69ea501b645986fd0b90dab13f589e995ff428 \
    --hash=sha256:307fc22ea496be8542d67b82ae8c867a978dfd19ac35573d4f15943fd9277dfe \
    --hash=sha256:3117abfd32b183bdb6194df9317766d32c6517f3d1c0aa8c62d5c6ccfda0b4a8 \
    --hash=sha256:313f6703023d53baabab6d6c5c37cf637b2c4fee255acf2ed5e92ad69e28f1b7 \
    --hash=sha256:315551f4ccedbbf9fd4f7e8bf037a5948c976ade0e919ba5d8f581d465f6f725 \
    --hash=sha256:35e0f088ddfd9d9bc5019e27ff3767411779e92b59db5bb1507f2731a5b61158 \
    --hash=sha256:3621f3686397708b8eeabfd0a9d75267c1f29a7537d2fe31e65d099e71587fa4 \
    --hash=sha256:36c2fb94c990cc2545143b12690e2de6c16300f9dbe5b4f33fa300cf57dc8792 \
    --hash=sha256:376a693697ddb695ea282ead76060f4847f90e564b12b4389f2c7589e6fadb9e \
    --hash=sha256:3892d76754b5f36fb40619f3ef09c68e5c3091f1ab8840964518ae5a41f30952 \
    --hash=sha256:3bbc5543e39ee025d524077c5c15c2d67bc11c9f6676afe5b531839e24d701f6 \
    --hash=sha256:3eb44019a2b0b3b91bac95998f1e4e5589730421170e060fe654a2b7be727dc7 \
    --hash=sha256:3f0def1279644acaa9bc861d4234af3f82ea9cee7e460dffac5cb63e691501e9 \
    --hash=sha256:40960554e60eb60c3eec4ff9e42a80f84f8cd3ca9bc80a5481a61f1e64d807c9 \
    --hash=sha256:4173a4b8a025ae44313d9d9b4ecf31e886c7b7faf45386d51a8ca4ff2dcf3f2a \
    --hash=sha256:42cbca10f82a8b2fb1536e8a0830ca6ceeb6bb3d8d64b766e0795369135654a8 \
    --hash=sha256:4497e87c34a2d21cbec1227858fec3af8e514dd70c47625557a122fcebc081dc \
    --hash=sha256:4733fc2d99fe888261417b7e29995403a72d9ffa78629902882325ea141177f2 \
    --hash=sha256:48997ed4431d8006988788ef4b62e1fd3f053c7463b4fa793aa6c4f9e96a3bb7 \
    --hash=sha256:4a49ca342efc0800e6ae94ed5c9cbdcb319308f75e73c21181e4c24d6710e8dd \
    --hash=sha256:4c32eb565ad9ce8a6444248e5b7a19dbb86a81c811fe5fcc2fba7a735aed5163 \
    --hash=sha256:4e312e07557a5ad348f4e83d3419773527f6e790c7f97928b1911d767b6ea1c7 \
    --hash=sha256:50644d8715be7e0ec0682f9d7744b63008e199c5e1618a48fa153756a332235f \
    --hash=sha256:533b7c82bb1eafbeb921dfe131c9f88e55451ddc328d84bde1c9340ba72d2808 \
    --hash=sha256:5436ffea003adb50e283ca0684a3fcaa1396104f841736c3322ee6582bd09e98 \
    --hash=sha256:55c5b9eab079540bfb639b40b07b7b467e5c5a7ecf97a65cc8665781381c9856 \
    --hash=sha256:55f9a808a0e072473337c240c939849818276e288e2374b832255b5b791b0851 \
    --hash=sha256:569ed5db651e420b13279f9333443bb5b84a436cc66b599cbc535697ae4434a0 \
    --hash=sha256:5b43a1f7e4853ce08c3f6d3bf69799ee5b46548bfb71792a8158f7e45d66b547 \
    --hash=sha256:5d459bbb6c22f26dcebea56924a362aba50d453b9867912862c970434fcf0d94 \
    --hash=sha256:5dc29815520c329f5662f6eb3ebadecf0d4f8c82dfa416d4d6efbf8f39245559 \
    --hash=sha256:60deca33e584c09e91f70f8b55a0b1de7d671d6a63f051d154920f48bed717c7 \
    --hash=sha256:61040f6f7da5a279d2f77496c69d51132aba75f701c52bded400d4c639277b18 \
    --hash=sha256:6281c171557ce0e408e19d9a223f22d915117ac38a5a7f32ed83809e7492316c \
    --hash=sha256:63499fc49efe48bccc2fca40723bc7adb198866cbe159093dd979905316994b6 \
    --hash=sha256:63f543463601c1558b755f8dd7618b6ec3dd0934dda051d3b7030d8c76e54de2 \
    --hash=sha256:65a89a5bde227bfe908016f35b5bd347970cd1e5b0360f389502eba1c7fde6e0 \
    --hash=sha256:660aa158127035e741d4b1835dbe79ae18a1fbb21ecd236655f31d60110e68d5 \
    --hash=sha256:6627b913b8586b1c06db9516b31dd0dfbc621de3bb9312616d92a7e44f268a5b \
    --hash=sha256:691780fca2be3dec512cb603cb91060271968cb4af86b51d07c57445c5754a37 \
    --hash=sha256:6aa59f0ef92e796b2db6f5f26550c4713c0e4036899fadf02f55e2ed4db0b7ae \
    --hash=sha256:6c274fc1572edf7c197094a0eb1887d45fdc95254bc80597dc7599550486c06a \
    --hash=sha256:6e9a04e69456015e6ae5e0d486d995137fd435794442122b00ce5f9526ea3ba8 \
    --hash=sha256:74836317b7010b579522bb52426f1e225608b042c9e78cbe2493522bebb8a318 \
    --hash=sha256:761cde41439f0be761aa460e1451a31e2e14baf4a46db6fe4913e5a06a90df66 \
    --hash=sha256:76693a16dead737946b651375ee3109d7db7ad9569a1c55c60aaed3ef85cfcc6 \
    --hash=sha256:77a42cc507993ec5471b5283f7eef869239173b6000031543e3938a86d1af0fd \
    --hash=sha256:7f115d5d804a2163dd89245710049078b0e726a58c1f44a1f86c2c6e79055d76 \
    --hash=sha256:80cbc645af23ac5c12096545c161626960114a1bc10f864760558d3b3e82ba18 \
    --hash=sha256:83abd8beab056aa77a116364811f8fc262dffbcc7abea48de0c85ccbfc6f1428 \
    --hash=sha256:8462395df8f224d2daa3d80db3ae4450d9d4b7243c8483ac79a82862f1599dd6 \
    --hash=sha256:876da8ca5520d65b5d0f2ca6b4e7a00d35bb90ccda35cb2ce3cda4b6c711e84a \
    --hash=sha256:88c6a42c2632ff469e84155e44f6ed92cb15ccb047bf5fcb59225ae5a12fd33d \
    --hash=sha256:89c4898da776193577279173dcf9860487590611d7320d379435a145881b048d \
    --hash=sha256:8a2321bcb73758c44c8076509024d02c15ee484fe77ce04edea4bf4d257492cc \
    --hash=sha256:8a829db795e3f87053904493d184b185c8eb1f497c852f434168ec856aa6f997 \
    --hash=sha256:8be4a87b3baca380ec3c7b1643b2dd268ac9d42c5097c0e8dc9a49342faf4774 \
    --hash=sha256:8da58558bfb0ca6ccac2419773521f1111e40654038b1afabdfc69c02cb82614 \
    --hash=sha256:8e24b878cf54843a63985d90480f163ca7f692689fbcbe9cdbd8165521083a8b \
    --hash=sha256:902ce8cafca2dc14cef9558a6fc3b45dbf7f121d1404bf2ad18a1c894555e48c \
    --hash=sha256:908d81d88bb16141613a6275059b5114656d5c2f0b5400b421d54fe6f1943507 \
    --hash=sha256:916ebdfd82e7fc68041d36b2b5f60361b9abce1e087454da15f8bd004839e090 \
    --hash=sha256:946ac2164d646e733004946ae39536b5af473853183d81da5962e29d36e3ad35 \
    --hash=sha256:9496bff5541086478264678bac73c0a75b2fde94fdf6568893bca1f7c6d50d18 \
    --hash=sha256:96f6c8d0fe21930d1f982bfce2382789d2e8d005d2ab63d21280660f95ef8fe1 \
    --hash=sha256:983bcdc898662f6ba9d6a025c30d29946ff0986d9ad60d400af0da3671f7cbf3 \
    --hash=sha256:98f2d03df74977fd252831c997c388cd6c3f691a8a9d022b266d3cbd9849838f \
    --hash=sha256:9a2a60a7f0ea5f239efb6391d2b28630a640d82dad63e3bee47cf2c623c4495d \
    --hash=sha256:9c393a202df08e96ed619310f0cd78be700e532a57d9a6ceee5f80b4e35bef14 \
    --hash=sha256:9c88697fa943bd4ef67cc919a17d81de6581846f52bfa8c6f64a916098986556 \
    --hash=sha256:9df9d048def11365d170b375b6ffc8b23a7f188c3560acd4418ba088ca2e2705 \
    --hash=sha256:a046227daa7f191e843d26b911c1146233e9a33d249e0c954dcb3ac7c398710e \
    --hash=sha256:a69ce25be5f1330ee1c74eb6fabbbceaa96b384beedd2627cecded7546490c40 \
    --hash=sha256:a7c4bb26de6ef496d24822aee4f6a305d97cd33d21a2b85f290292d69ba1c25e \
    --hash=sha256:a81e19710d48da88653473b6b9c366d47e99fe4f58e37ce415be47966748f31f \
    --hash=sha256:aaead3d926e9ab4124ada727d20cd62d396649917822df4f771d1f07f1079b40 \
    --hash=sha256:ada04d0262ab06527054a2a497f384d102698ff39b3865dc566a7d24b6f4058c \
    --hash=sha256:af4c565b923bb5975401b8e4cedc2e17b2fdbf33b905737ee12384e6a6fd9507 \
    --hash=sha256:b24b83fbb34b2d8de06cf0f0d4bd7737344ef854482a614826d4356c0c3f0c12 \
    --hash=sha256:b25659ab2d655d742701487d5591e3f98e8f8b329fc999e05e3d59691ab344a1 \
    --hash=sha256:b5f79366a8d8dbb981d53ba800bb54a95454595ab8a4548c2b95501b32a08326 \
    --hash=sha256:b789356bc4e2e6c20ba52817f92c3fed74e24657654237ecd536c54843b80c6c \
    --hash=sha256:c08da1f15040bd1e1a6074bd4518a6ef20e67b1594ecfb0aa75e5b45f87e6d6d \
    --hash=sha256:c1c09d5d4646eb96bda2cfb97493bcea21a0956a981de116e6b1f4a9de07f3fd \
    --hash=sha256:c2ec7e51157a3fa0e9cfdb1a8969bab38d1c22ad1ace7c6cea006383b43a1ad4 \
    --hash=sha256:c49c9edd47d0e44d360299e2d8865e2950d2fcf1b4098782c9d7dcd070919e5a \
    --hash=sha256:c63ff5a21f26bd0e6a8464b53fadbe174825c8718ac14180df45665eaacdb6af \
    --hash=sha256:c6590e1eb624ff6b15b872421bc9a10bc6d2057635d69c6cd244ac3f928f85c6 \
    --hash=sha256:c76b4bcbf0f713194591673fc86a42820e14da6bbd1bb445d3d002cc4d1e4521 \
    --hash=sha256:c796a1bb3e4015249639849f30e8e680df8a431b45d417ba8acf843d2451d95f \
    --hash=sha256:c81d6cdbacccda7e0eef3b076a457fd14c3835cdbc5993d2881580c2fb1f5f26 \
    --hash=sha256:c8eea55fdfa9ba65c6981eea38bd20c800bce2f092a2803d82de764ecf0f071a \
    --hash=sha256:cb5e2bf969ac99a6ae3c71208a5eb05cfde973192540ffa6e1068b57fb78c4f8 \
    --hash=sha256:cca2fcb72c007103740fa4fc3df19fdb1a318c641c69f3b0cc47ed63a889336e \
    --hash=sha256:cf8811d285acc91216368df7fb55cc8c9bf6fcd90eea42429c7186c7385a12b9 \
    --hash=sha256:d1a4f9462da6496b6cb79bbb09c60d17f7e63e8a1df136797b3afabec9560e4d \
    --hash=sha256:d4df62fd8448a85c752bbea1803cb3a2785e6fc8352009ab64ad7447af079b3c \
    --hash=sha256:d6605630c2808b33f362d6d08582e79821f77ed2bd3f49f9d467ea70defea06d \
    --hash=sha256:d87091c4347daadbcc0833b65812ff38d7350c67339625d4e4a512cf38e3e8ef \
    --hash=sha256:d8cfe9522ad69b6abb26b413ed1deca43cb915cefc588433d557cb3ae1c783e2 \
    --hash=sha256:dac93bf7a9beb215be3282b8441173cd50806c41c007b8be9bb24e03c60ad563 \
    --hash=sha256:dd9252828073fd0d69e7667af4275a1b17c18d0833b1ab7f59db272f194a6b9a \
    --hash=sha256:e136197f1262620ef2e507afc3ea759c1ae7d221886da20eec5f4c9f2618c2aa \
    --hash=sha256:e1e3bc8090a7eae79fdf634b63bdbfa3c93999991023c37c6fd3b469fc8ff5dc \
    --hash=sha256:e48ac2b302986c6f55cf61e8e36b4dd97d0132c5078a713a697a940934ba422e \
    --hash=sha256:e53d950e16d4bb672a5ff41fe3131e65a4e5d688d694e1c7074c8c9990bb3ceb \
    --hash=sha256:e5855e574804398859c5fbaf4fc7882b96278b7f6572a3d889627e6eb6cfca59 \
    --hash=sha256:eb0023e6cdb4b8ece0b33875188dd16104ad8c335361d396a98394f99e30ff7a \
    --hash=sha256:eb7b737ce8d18c8a08beb68f751572b7bf6a18093ecd1406ca1256b50592552e \
    --hash=sha256:ecb748910e9ba4624ebe2057791df51dcbffb48c37108ab94a3c593472023c9e \
    --hash=sha256:ecd63d0c7ed0d3d719c91b5a3861f0f0b3cec9bf223033ddf69d17aaac74bb6d \
    --hash=sha256:f19ca1a21871f024e38faf4107b433047df27558dff1b72a1dac31481e2c1fe5 \
    --hash=sha256:f2731f9067976c8c4127212c0d2f2ada42d497d935e470419e029802365b12bb \
    --hash=sha256:f2bbf3f28d0b63157577c8b774b9136f076afa6797e1a52a2ecd477f23cad3a8 \
    --hash=sha256:f33c7908a6885dcae9f462a4a8347b637053b4ff2b96beb4c23fba1cf7818e5f \
    --hash=sha256:f60e39adfecf998488166aca8ff24ab1ac406c9ecbecbcf9b3bcfc43cb1ec9a1 \
    --hash=sha256:f7eac84d4969da82166d5e90d9c38d2f416fe24f9708a7013569b193745b9a31 \
    --hash=sha256:f8969ad228115ad8869b5fed801f899e52ab8ad376fdb165ba4760a277c8258a \
    --hash=sha256:f90bad2839c185a1edf8ee22a257cfc8a39e0e337a0490ab185dfa76ef04d1bd \
    --hash=sha256:faa763b677e96f1beccc6b4d7e8c079dfeed2f249f57a19debc321b519ee64ec \
    --hash=sha256:fb78fb4158c12f77a934a003006784108a27a6553cfc0c6f10483c9c02e94f48 \
    --hash=sha256:fcce735ffd72ac4056db05325d9f0232382b74826f0196eb6a15ca903abdaa0f
EUGENE_REQUIREMENTS
# END GENERATED DEPENDENCIES
run_step "installing locked dependencies" \
    in_prefix "$UV" pip install --python "$PYBIN" --require-hashes --only-binary :all: \
    -r "$PREFIX/release-requirements.lock"
say "installing Eugene Plexus"
run_step "installing the seven Eugene Plexus packages" \
    in_prefix "$UV" pip install --python "$PYBIN" --no-deps --no-build-isolation \
    "eugene-plexus-agent @ $(gh_archive agent "$PIN_AGENT")" \
    "eugene-plexus-control @ $(gh_archive control "$PIN_CONTROL")" \
    "eugene-plexus-gateway @ $(gh_archive gateway "$PIN_GATEWAY")" \
    "eugene-plexus-inference-driver @ $(gh_archive inference-driver "$PIN_DRIVER")" \
    "eugene-plexus-library @ $(gh_archive library "$PIN_LIBRARY")" \
    "eugene-plexus-tool-driver @ $(gh_archive tool-driver "$PIN_TOOL_DRIVER")" \
    "eugene-plexus-ui @ $(gh_archive ui "$PIN_UI")"

in_prefix "$UV" pip check --python "$PYBIN"

# --- 4. VERIFY --------------------------------------------------------
# "pip install exited 0" is not the claim. Three things can be true of a
# successful install and still leave a machine that serves nothing, and
# each of them has bitten this project:
#
#   * a component is importable but `default_topology` looks for it with
#     `find_spec` against *this* interpreter, so an install into the
#     wrong one declares an empty control plane and supervises nothing;
#   * `eugene-plexus-ui` can install with an empty payload (above), and
#     the symptom is a browser page, not an installer error;
#   * the console script is what the service unit executes, so its
#     absence is a failure that only appears at boot.
say "checking the install"
in_prefix "$PYBIN" - <<'PYEOF' || die "the install is incomplete — see above"
import importlib.util, sys
from pathlib import Path

bad = []
for mod, what in [
    ("eugene_plexus_agent", "the node agent"),
    ("eugene_plexus_control", "the control root"),
    ("eugene_plexus_gateway", "the gateway"),
    ("eugene_plexus_inference_driver", "the inference driver"),
    ("eugene_plexus_library", "the model library"),
    ("eugene_plexus_tool_driver", "the web-search tool driver"),
]:
    if importlib.util.find_spec(mod) is None:
        bad.append(f"{what} ({mod}) is not importable from {sys.executable}")

try:
    import eugene_plexus_ui
    static = Path(eugene_plexus_ui.static_dir())
    if not (static / "index.html").is_file():
        bad.append(
            f"the web UI package installed but carries no build output ({static}); "
            "the UI pin must point at the `dist` branch, not `main`"
        )
except Exception as exc:  # noqa: BLE001
    bad.append(f"the web UI package is not usable: {exc}")

for line in bad:
    print(f"  - {line}", file=sys.stderr)
raise SystemExit(1 if bad else 0)
PYEOF

in_prefix test -x "$VENV/bin/eugene-plexus-agent" || die "the eugene-plexus-agent command did not install"
say "all seven packages present, with a web UI"

# --- 4b. join, if this machine is a worker ----------------------------
# **The installer owns the one onboarding question, because this is the
# only moment a human is reliably present.** The agent's own first-boot
# prompt needs a TTY *and* someone watching it, and the unit files below
# pass `--unattended` precisely because a Windows scheduled task has the
# first without the second. So: named on the command line, we enroll
# now; not named, this machine is the start of a new install, which is
# what every unit then boots into.
# Replace one top-level `key: value` line in agent.yaml, keeping every
# other line. As YAML text rather than through the install's Python: on a
# fresh install the file does not exist yet, and it is a flat mapping of
# config keys at the top level, so replacing one line is exact. `|| true`
# because grep -v selecting nothing -- a file holding only this key -- is
# exit 1, which `set -e` used to treat as the end of the install.
set_config_line() {
    in_prefix sh -c '
        f=$1 k=$2 v=$3
        { if [ -f "$f" ]; then grep -v "^$k:" "$f" || true; fi
          printf "%s: %s\n" "$k" "$v"; } > "$f.tmp" && mv "$f.tmp" "$f"
    ' sh "$CONFIG" "$1" "$2"
}

FRESH=1
if in_prefix test -f "$CONFIG"; then FRESH=0; fi

if [ -n "$JOIN_CONTROL" ]; then
    [ -n "$JOIN_TOKEN" ] || die "--join needs --token (mint one at the control root: Nodes -> Add a node)"
    # `if` rather than `[ ... ] && set --`: under `set -e` a false test
    # at the end of a && chain is the script's exit status, so the
    # short-circuit would end the install rather than skip an option.
    set -- join --control "$JOIN_CONTROL" --token "$JOIN_TOKEN"
    say "joining $JOIN_CONTROL as a worker node"
    if [ -n "$JOIN_ADVERTISE" ]; then set -- "$@" --advertise "$JOIN_ADVERTISE"; fi
    if [ -n "$JOIN_NAME" ]; then set -- "$@" --name "$JOIN_NAME"; fi
    JOIN_RC=0
    in_prefix env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$CONFIG" "$VENV/bin/eugene-plexus-agent" "$@" \
        || JOIN_RC=$?
    if [ "$JOIN_RC" != 0 ]; then
        # The new install goes and every install set aside comes back, then
        # the reason, last, where it is read.
        restore_existing
        if [ "$JOIN_RC" = 3 ]; then
            # The agent's EXIT_TOKEN_REFUSED: unknown, expired or used. The
            # same command cannot work again, so this never says to retry.
            die "the control root refused the join token.
       Make a new one on its Nodes page (Add a node) and run the command
       it gives you. This machine is back as it was."
        fi
        die "the join failed (see above). This machine is back as it was.
       Fix what it says, then run this command again."
    fi
    # The commit point: from here a failure is reported, never undone.
    JOIN_COMMITTED=1
    if [ "$MODE" = system ]; then
        # Save a download: the set-aside install's engine builds are exactly
        # what this machine runs.
        printf '%s' "$SET_ASIDE_LIST" | while IFS='|' read -r _kind _path _aside; do
            if [ -n "$_aside" ] && as_root test -d "$_aside/engines" && ! as_root test -e "$PREFIX/engines"; then
                as_root cp -a "$_aside/engines" "$PREFIX/engines" \
                    && as_root chown -R "$SYSTEM_ACCOUNT:$SYSTEM_ACCOUNT" "$PREFIX/engines" \
                    && say "carried over the engine builds from $_aside"
            fi
        done
    fi
    # **A node that advertises an address must be reachable at it.**
    # Found on the first enrollment between two genuinely separate
    # machines: the worker advertised its LAN address, bound 127.0.0.1,
    # and the control root could not call back -- so the union topology
    # view, idle unload and start-on-demand would all have failed while
    # enrollment itself looked perfect, because enrollment is outbound.
    # Joining is exactly the moment that stops being optional, so the
    # unit written below binds wide. A single-machine install still gets
    # loopback, which is the conservative default and the reason the
    # rule exists. A job site is the exception: nothing connects to it.
    if [ "$JOIN_SITE" != 1 ]; then JOINED=1; fi
elif [ -n "$JOIN_TOKEN" ]; then
    die "--token needs --join <control-root-url>"
elif [ -n "$JOIN_ADVERTISE" ]; then
    # **`--advertise` was accepted on any invocation and honoured only
    # here** (review §6.2 #30), so the standalone case -- one machine,
    # no control root to join, an operator who already knows the address
    # their phone will use -- typed a flag that did nothing and got an
    # install on loopback. It is the same field `PATCH /v1/config` sets
    # and the Reach card writes; setting it before the first start is
    # what `tailnet.md` has always said matters, because enrollment does
    # not restart anything and a listening socket cannot follow a
    # setting.
    #
    # Written as YAML text rather than through the install's Python: at
    # this point in a fresh install `agent.yaml` does not exist yet, and
    # the file is a flat mapping of config keys, so replacing one
    # top-level line is exact. An existing file keeps everything else,
    # which a re-run has to be true of or the installer is the thing
    # that loses an install's state.
    say "advertising this machine at $JOIN_ADVERTISE"
    [ "$MODE" = system ] || mkdir -p "$PREFIX"
    set_config_line advertiseUrl "$JOIN_ADVERTISE"
    ADVERTISED=1
fi

# **An agent under its own account has no keyring**, so a fresh system
# install unlocks from a passphrase file only that account can read
# (`securityMode: passphrase_file`; the path is in the unit below). Only
# on a fresh install: a re-run keeps whatever the person has since chosen
# under Config. The wizard reads `passphraseFile` off the agent and sets
# the control root to the same mode.
if [ "$MODE" = system ] && [ "$FRESH" = 1 ]; then
    set_config_line securityMode passphrase_file
fi

# --- 5. service -------------------------------------------------------

# Set once, used by both unit writers below.
if [ "$JOINED" = 1 ] || [ "$ADVERTISED" = 1 ]; then
    WIDE_BIND_UNIT="Environment=EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0"
    WIDE_BIND_PLIST="
        <key>EUGENE_PLEXUS_AGENT_BIND_HOST</key><string>0.0.0.0</string>"
else
    WIDE_BIND_UNIT="# this install is single-machine; the agent stays on loopback"
    WIDE_BIND_PLIST=""
fi

# **The one lever when 8079 is taken, and it reached nothing** (review
# §6.2 #24). `EUGENE_PLEXUS_AGENT_BIND_PORT` was read for the health
# wait at the end of this script and never written into the unit or the
# plist, so the install that answered on the chosen port during the run
# came back on 8079 at the next boot -- and the closing line told the
# person to open the port it would not be on. The port is decided once,
# here, above everything that quotes it.
PORT=${EUGENE_PLEXUS_AGENT_BIND_PORT:-8079}
# An update keeps the unit it finds, so the port is the one that unit
# starts the agent on -- not whatever the update's own environment says.
# The update helper and a transient user unit both start with none.
if [ "$UPDATE" = 1 ]; then
    if [ "$MODE" = system ]; then _kept=$SYSTEM_UNIT
    elif [ "$PLATFORM" = linux ]; then _kept=$SYSTEMD_UNIT
    else _kept=$LAUNCHD_PLIST; fi
    PORT=$(sed -n \
        -e 's/^Environment=EUGENE_PLEXUS_AGENT_BIND_PORT=\([0-9][0-9]*\)$/\1/p' \
        -e 's/.*<key>EUGENE_PLEXUS_AGENT_BIND_PORT<\/key><string>\([0-9][0-9]*\)<\/string>.*/\1/p' \
        "$_kept" 2>/dev/null | head -n 1)
    PORT=${PORT:-8079}
fi
if [ "$PORT" != 8079 ]; then
    PORT_UNIT="Environment=EUGENE_PLEXUS_AGENT_BIND_PORT=$PORT"
    PORT_PLIST="
        <key>EUGENE_PLEXUS_AGENT_BIND_PORT</key><string>$PORT</string>"
else
    PORT_UNIT="# the agent takes its default port, 8079"
    PORT_PLIST=""
fi

write_systemd_unit() {
    mkdir -p "$(dirname "$SYSTEMD_UNIT")"
    cat > "$SYSTEMD_UNIT" <<EOF
[Unit]
Description=Eugene Plexus node agent
Documentation=https://github.com/eugene-plexus/agent
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
WorkingDirectory=$PREFIX
Environment=EUGENE_PLEXUS_AGENT_CONFIG_FILE=$CONFIG
$WIDE_BIND_UNIT
$PORT_UNIT
ExecStart=$VENV/bin/eugene-plexus-agent --unattended
Restart=on-failure
RestartSec=5
# The agent stops its own children inside its lifespan shutdown. mixed
# sends SIGTERM to the agent only, so it gets to do that; anything still
# alive after the timeout is killed with the cgroup.
KillMode=mixed
TimeoutStopSec=60

[Install]
WantedBy=default.target
EOF
}

# **Where the models go on a system install: your home, read through your
# group** (Troy's call, 2026-09-24). The unit adds your primary group, a
# 0750 home lets that group in, and this folder is made group-writable
# (and setgid, so what Eugene downloads into it stays in your group) so
# that downloads can land. It is created as you and owned by you: it is
# your folder, the library's default, and nothing this install removes.
# With nobody to make it for (a root shell), it goes under the prefix.
prepare_models_dir() {
    if [ -z "$PERSON_HOME" ]; then
        MODELS_DIR=$PREFIX/models
        as_service mkdir -p "$MODELS_DIR"
        return 0
    fi
    MODELS_DIR="$PERSON_HOME/Eugene Models"
    if [ ! -d "$MODELS_DIR" ]; then
        if [ "$(id -u)" = 0 ]; then
            as_root install -d -m 2775 -o "$PERSON" -g "$PERSON_GROUP" "$MODELS_DIR"
        else
            mkdir -p "$MODELS_DIR"
            chmod 2775 "$MODELS_DIR"
        fi
        say "made $MODELS_DIR for your models (Eugene reads and writes it through your group)"
    else
        case $(stat -c %A "$MODELS_DIR" 2>/dev/null) in
            ?????w*) : ;;
            *) warn "Eugene reads $MODELS_DIR through your group, and downloads into it
    need that group to be able to write:  chmod g+ws '$MODELS_DIR'" ;;
        esac
    fi
    # Your home has to let the group through at all. 0750 is Ubuntu's
    # default; 0700 (Fedora's) lets nobody else in, Eugene included --
    # said, not changed, because your home's permissions are yours.
    case $(stat -c %A "$PERSON_HOME" 2>/dev/null) in
        ??????[xs]*) : ;;
        *) warn "your home folder lets nobody else in (it is not group-searchable), so
    Eugene cannot reach the models in it. Either let your own group in:
        chmod g+x '$PERSON_HOME'
    or keep models outside your home and add that folder under Library -> Folders." ;;
    esac
}

write_system_unit() {
    # Your group, for the models above; video and render where they exist,
    # because some distributions restrict the GPU device nodes to them.
    UNIT_GROUPS=${PERSON_GROUP:-}
    for g in video render; do
        if getent group "$g" >/dev/null 2>&1; then UNIT_GROUPS="$UNIT_GROUPS $g"; fi
    done
    as_root tee "$SYSTEM_UNIT" >/dev/null <<EOF
[Unit]
Description=Eugene Plexus node agent
Documentation=https://github.com/eugene-plexus/agent
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
# Its own account, so the programs you run cannot read its keys, its
# environment or its memory. See the top of install.sh.
User=$SYSTEM_ACCOUNT
Group=$SYSTEM_ACCOUNT
SupplementaryGroups=$UNIT_GROUPS
WorkingDirectory=$PREFIX
Environment=EUGENE_PLEXUS_AGENT_CONFIG_FILE=$CONFIG
Environment=EUGENE_PLEXUS_AGENT_ENGINE_ROOT=$PREFIX/engines
# No keyring for an account with no desktop session: the passphrase is
# kept here, readable by this account only, and the control root on this
# machine reads the same file.
Environment=EUGENE_PLEXUS_AGENT_PASSPHRASE_FILE=$PREFIX/passphrase
Environment=EUGENE_PLEXUS_CONTROL_PASSPHRASE_FILE=$PREFIX/passphrase
Environment="EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS=$MODELS_DIR"
$WIDE_BIND_UNIT
$PORT_UNIT
ExecStart=$VENV/bin/eugene-plexus-agent --unattended
Restart=on-failure
RestartSec=5
# The agent stops its own children inside its lifespan shutdown. mixed
# sends SIGTERM to the agent only, so it gets to do that; anything still
# alive after the timeout is killed with the cgroup.
KillMode=mixed
TimeoutStopSec=60
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
EOF
}

write_launchd_plist() {
    mkdir -p "$(dirname "$LAUNCHD_PLIST")"
    cat > "$LAUNCHD_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LAUNCHD_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV/bin/eugene-plexus-agent</string>
        <string>--unattended</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>EUGENE_PLEXUS_AGENT_CONFIG_FILE</key><string>$CONFIG</string>$WIDE_BIND_PLIST$PORT_PLIST
    </dict>
    <key>WorkingDirectory</key><string>$PREFIX</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
    <key>StandardOutPath</key><string>$PREFIX/logs/launchd.out.log</string>
    <key>StandardErrorPath</key><string>$PREFIX/logs/launchd.err.log</string>
</dict>
</plist>
EOF
}

if [ "$UPDATE" = 1 ]; then
    # The unit stays as it was written; the update helper is this
    # version's, since a newer installer may carry a newer one.
    if [ "$MODE" = system ]; then
        write_update_helper; write_app_units
        # A failure here must not stop the agent's own update before it is
        # restarted: a subshell, so `die` and `run_step` end only this step.
        ( update_site_host ) || warn "the job-site host was not updated (see above); the agent was"
    fi
elif [ "$MODE" = system ]; then
    prepare_models_dir
    say "writing $SYSTEM_UNIT"
    write_system_unit
    as_root systemctl daemon-reload
    as_root systemctl enable "$SERVICE_LABEL" >/dev/null 2>&1 || true
    write_update_helper
    write_app_units
elif [ "$DO_SERVICE" = 1 ] && [ "$PLATFORM" = linux ]; then
    if ! command -v systemctl >/dev/null 2>&1 || [ ! -d "${XDG_RUNTIME_DIR:-/nonexistent}" ]; then
        warn "no systemd user session here — skipping the service. Start the agent with:
    EUGENE_PLEXUS_AGENT_CONFIG_FILE=$CONFIG $VENV/bin/eugene-plexus-agent"
        DO_SERVICE=0
    else
        say "writing $SYSTEMD_UNIT"
        write_systemd_unit
        systemctl --user daemon-reload
        systemctl --user enable "$SERVICE_LABEL" >/dev/null 2>&1 || true
        # A user unit runs when the user is logged in. Lingering is what
        # makes it start at boot instead, and enabling it needs polkit
        # authorisation this script will not have. Say so rather than
        # leave a machine that quietly only works after someone logs in.
        if [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || echo no)" != yes ]; then
            warn "this agent will start when you log in, not at boot. For boot:
    sudo loginctl enable-linger $(id -un)"
        fi
    fi
elif [ "$DO_SERVICE" = 1 ]; then
    say "writing $LAUNCHD_PLIST"
    write_launchd_plist
fi

# Store a local remover even when startup is disabled. No network is
# needed to use it, and it remains beside retained files after removal.
if [ "$MODE" = user ]; then
    write_removal_bundle
    if [ "$PLATFORM" = macos ]; then
        "$PYBIN" -I "$PREFIX/uninstall/inventory.py" --prefix "$PREFIX" --install-macos
    fi
fi

# --- 6. start ---------------------------------------------------------
# **The per-user layout says what it costs**, on every path that installs
# a service there: this is the one fact the default Linux layout exists
# to change, and a person choosing --user should hear it once, plainly.
warn_same_account() {
    if [ "$MODE" != user ] || [ "$DO_SERVICE" != 1 ]; then return 0; fi
    warn "Eugene runs as you ($(id -un)), so any program you run as you -- an AI agent
    included -- can read its keys and take control of it."
    if [ "$PLATFORM" = linux ]; then
        echo "    For Eugene to run under its own account instead, uninstall this one"
        echo "    (--user --uninstall) and re-run without --user."
    else
        echo "    On macOS, Eugene cannot run under its own account yet."
    fi
}

if [ "$MODE" = system ]; then
    LOGS_HINT="sudo journalctl -u $SERVICE_LABEL   (files: sudo ls $PREFIX/logs)"
else
    LOGS_HINT="$PREFIX/logs/    config: $CONFIG"
fi

if [ "$DO_START" = 1 ] && [ "$DO_SERVICE" = 1 ]; then
    say "starting the agent"
    if [ "$MODE" = system ]; then
        as_root systemctl restart "$SERVICE_LABEL"
    elif [ "$PLATFORM" = linux ]; then
        systemctl --user restart "$SERVICE_LABEL"
    else
        launchctl bootout "gui/$(id -u)/$LAUNCHD_LABEL" >/dev/null 2>&1 || true
        launchctl bootstrap "gui/$(id -u)" "$LAUNCHD_PLIST"
    fi

    i=0
    while [ "$i" -lt 60 ]; do
        if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/healthz" 2>/dev/null; then
            printf '\n'
            say "Eugene Plexus is running — open http://127.0.0.1:$PORT/"
            say "logs:  $LOGS_HINT"
            warn_same_account
            exit 0
        fi
        i=$((i + 1))
        sleep 1
    done
    warn "the agent did not answer on port $PORT within 60s. Check:"
    if [ "$MODE" = system ]; then
        echo "    sudo systemctl status $SERVICE_LABEL"
        echo "    sudo journalctl -u $SERVICE_LABEL -n 50"
    elif [ "$PLATFORM" = linux ]; then
        echo "    systemctl --user status $SERVICE_LABEL"
        echo "    journalctl --user -u $SERVICE_LABEL -n 50"
    else
        echo "    tail -50 $PREFIX/logs/launchd.err.log"
    fi
    exit 1
fi

say "installed. Start it with:"
if [ "$MODE" = system ]; then
    echo "    sudo systemctl start $SERVICE_LABEL"
elif [ "$DO_SERVICE" = 1 ] && [ "$PLATFORM" = linux ]; then
    echo "    systemctl --user start $SERVICE_LABEL"
elif [ "$DO_SERVICE" = 1 ]; then
    echo "    launchctl bootstrap gui/$(id -u) $LAUNCHD_PLIST"
else
    echo "    EUGENE_PLEXUS_AGENT_CONFIG_FILE=$CONFIG $VENV/bin/eugene-plexus-agent"
fi
# Every path ends with the same two facts a first-time user needs and the
# service path already printed: where the browser goes, and where the
# files are. Found by the hobbyist UX measurement (docs/design/hobbyist-ux.md
# §5): a Linux install with a service ended in a systemctl line and nothing
# else.
echo "    then open http://127.0.0.1:$PORT/"
echo "    logs:  $LOGS_HINT"
warn_same_account
