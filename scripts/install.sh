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
#   1. fetches `uv` into the install prefix and nowhere else,
#   2. makes a virtualenv there with a Python `uv` downloads itself,
#   3. installs the six Eugene Plexus packages into it,
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
# directory. The `dist` branch carries the built export so that all six
# packages install by one mechanism. See install-paths §12, step 3.

set -eu

# --- pins -------------------------------------------------------------
# One commit per repo. Bump these to ship a new version.
PIN_AGENT=ce90e340a63897b9209dfe6b330bfef407d75bc8
PIN_CONTROL=b14bd5764d233944ad9209104ca97e1ba40a418e
PIN_GATEWAY=2f4d8ddbabd8400dae6fcd9689fc195653e88d4d
PIN_DRIVER=f754620003950991b546503f79775450f1113737
PIN_LIBRARY=47dfdf032ab9cc63cef3753e37af0d08c2b71e23
PIN_UI=53d465fac8cbd646b5fc24e7efa141518807ea69   # branch `dist`, not `main`

PY_VERSION=3.12
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
JOINED=0
DO_PURGE_COPIES=0
ADVERTISED=0

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=$2; shift 2 ;;
        --prefix=*) PREFIX=${1#--prefix=}; shift ;;
        --user) USER_MODE=1; shift ;;
        --no-service) DO_SERVICE=0; shift ;;
        --no-start) DO_START=0; shift ;;
        --uninstall) DO_UNINSTALL=1; shift ;;
        --purge-downloads|--purge-model-copies) DO_PURGE_COPIES=1; shift ;;
        --join) JOIN_CONTROL=$2; shift 2 ;;
        --token) JOIN_TOKEN=$2; shift 2 ;;
        --name) JOIN_NAME=$2; shift 2 ;;
        --advertise) JOIN_ADVERTISE=$2; shift 2 ;;
        -h|--help)
            sed -n '2,52p' "$0" 2>/dev/null || true
            echo "options: --user  --prefix DIR  --no-service  --no-start  --uninstall"
            echo "           --user  (Linux: install under your own account, no sudo; anything"
            echo "                   you run can then control Eugene)"
            echo "           --purge-downloads  (with --uninstall: delete this install's model"
            echo "                              copies and engine builds, which live outside the prefix)"
            echo "  worker node: --join URL --token JWT [--name NAME] [--advertise URL]"
            echo "  standalone:  --advertise URL   (the address other devices reach this one at)"
            exit 0 ;;
        *) echo "install.sh: unknown option $1" >&2; exit 2 ;;
    esac
done

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
    if [ "$(id -u)" = 0 ] && command -v runuser >/dev/null 2>&1; then
        runuser -u "$SYSTEM_ACCOUNT" -- "$@"
    else
        sudo -u "$SYSTEM_ACCOUNT" -- "$@"
    fi
}

# Anything that reads or writes under the prefix: as Eugene's account on
# a system install, whose prefix this shell cannot even look into, and
# as this shell otherwise.
in_prefix() {
    if [ "$MODE" = system ]; then as_service "$@"; else "$@"; fi
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
    if [ "$(id -u)" != 0 ]; then
        sudo -v || die "removing Eugene's own account needs sudo, and sudo was refused"
    fi
    say "stopping the service"
    service_stop
    as_root rm -f "$SYSTEM_UNIT"
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
    say "stopping the service"
    service_stop
    rm -f "$SYSTEMD_UNIT" "$LAUNCHD_PLIST"
    [ "$PLATFORM" = linux ] && systemctl --user daemon-reload >/dev/null 2>&1 || true

    COPIES=$(model_copy_dir || true)
    say "clearing this install's OS keyring entries"
    drop_keyring_entries

    if [ -n "${COPIES:-}" ] && [ -d "$COPIES" ]; then
        SIZE=$(du -sh "$COPIES" 2>/dev/null | cut -f1 || echo "?")
        if [ "$DO_PURGE_COPIES" = 1 ]; then
            say "removing this node's model copies at $COPIES ($SIZE)"
            rm -rf "$COPIES"
        else
            say "this node's model copies are at $COPIES ($SIZE) — they are copies, so"
            say "  deleting them loses nothing. Re-run with --purge-model-copies, or: rm -rf $COPIES"
        fi
    elif [ -n "${COPIES:-}" ]; then
        say "no model copies on disk (modelCopyDir was $COPIES)"
    fi

    ENGINES=$(engine_root)
    if [ -d "$ENGINES" ]; then
        ESIZE=$(du -sh "$ENGINES" 2>/dev/null | cut -f1 || echo "?")
        if [ "$DO_PURGE_COPIES" = 1 ]; then
            say "removing the engine store at $ENGINES ($ESIZE)"
            rm -rf "$ENGINES"
        else
            say "the engine builds this install downloaded are at $ENGINES ($ESIZE) —"
            say "  re-run with --purge-downloads, or: rm -rf $ENGINES"
        fi
    fi

    if [ -d "$PREFIX" ]; then
        # `agent.yaml` and `node.yaml` are the install's identity, and
        # `logs/` is the only record of what it did. Moving the prefix
        # aside rather than deleting it means an uninstall cannot be the
        # thing that loses an enrollment.
        KEEP=$PREFIX.removed-$(date +%Y%m%d%H%M%S)
        mv "$PREFIX" "$KEEP"
        say "removed. Your config and logs are at $KEEP — delete it when you are sure."
    else
        say "nothing installed at $PREFIX"
    fi
    exit 0
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
    fi
    # 0750: Eugene's account, and nobody but root, can look inside -- which
    # is the whole point. Applied on every run, so a prefix somebody opened
    # up by hand is closed again.
    as_root install -d -m 0750 -o "$SYSTEM_ACCOUNT" -g "$SYSTEM_ACCOUNT" \
        "$PREFIX" "$PREFIX/bin" "$PREFIX/logs"
fi

# --- 1. uv ------------------------------------------------------------
say "installing into $PREFIX"
[ "$MODE" = system ] || mkdir -p "$PREFIX/bin" "$PREFIX/logs"

if in_prefix test -x "$UV"; then
    say "uv already present ($(in_prefix "$UV" --version))"
elif [ "$MODE" = system ]; then
    say "fetching uv"
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
    say "fetching uv"
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

say "installing Eugene Plexus"
run_step "installing the six Eugene Plexus packages" \
    in_prefix "$UV" pip install --python "$PYBIN" \
    "eugene-plexus-agent @ $(gh_archive agent "$PIN_AGENT")" \
    "eugene-plexus-control @ $(gh_archive control "$PIN_CONTROL")" \
    "eugene-plexus-gateway @ $(gh_archive gateway "$PIN_GATEWAY")" \
    "eugene-plexus-inference-driver @ $(gh_archive inference-driver "$PIN_DRIVER")" \
    "eugene-plexus-library @ $(gh_archive library "$PIN_LIBRARY")" \
    "eugene-plexus-ui @ $(gh_archive ui "$PIN_UI")"

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
say "all six packages present, with a web UI"

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
    say "joining $JOIN_CONTROL as a worker node"
    # `if` rather than `[ ... ] && set --`: under `set -e` a false test
    # at the end of a && chain is the script's exit status, so the
    # short-circuit would end the install rather than skip an option.
    set -- join --control "$JOIN_CONTROL" --token "$JOIN_TOKEN"
    if [ -n "$JOIN_NAME" ]; then set -- "$@" --name "$JOIN_NAME"; fi
    if [ -n "$JOIN_ADVERTISE" ]; then set -- "$@" --advertise "$JOIN_ADVERTISE"; fi
    in_prefix env EUGENE_PLEXUS_AGENT_CONFIG_FILE="$CONFIG" "$VENV/bin/eugene-plexus-agent" "$@" \
        || die "enrollment failed; nothing was started"
    # **A node that advertises an address must be reachable at it.**
    # Found on the first enrollment between two genuinely separate
    # machines: the worker advertised its LAN address, bound 127.0.0.1,
    # and the control root could not call back -- so the union topology
    # view, idle unload and start-on-demand would all have failed while
    # enrollment itself looked perfect, because enrollment is outbound.
    # Joining is exactly the moment that stops being optional, so the
    # unit written below binds wide. A single-machine install still gets
    # loopback, which is the conservative default and the reason the
    # rule exists.
    JOINED=1
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

if [ "$MODE" = system ]; then
    prepare_models_dir
    say "writing $SYSTEM_UNIT"
    write_system_unit
    as_root systemctl daemon-reload
    as_root systemctl enable "$SERVICE_LABEL" >/dev/null 2>&1 || true
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
