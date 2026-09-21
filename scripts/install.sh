#!/bin/sh
# Eugene Plexus — one-command install for Linux and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/eugene-plexus/specs/main/scripts/install.sh | sh
#
# With options (sh cannot take arguments from a pipe without -s):
#
#   curl -fsSL .../install.sh | sh -s -- --no-service
#   curl -fsSL .../install.sh | sh -s -- --uninstall
#
# What it does, in the order it does it, so that reading this comment is
# a substitute for reading the script (install-paths §11: `curl | sh`
# has to stay auditable):
#
#   1. fetches `uv` into the install prefix and nowhere else,
#   2. makes a virtualenv there with a Python `uv` downloads itself,
#   3. installs the six Eugene Plexus packages into it,
#   4. checks that what landed can actually serve — see VERIFY below,
#   5. writes a systemd user unit (Linux) or launchd agent (macOS),
#   6. starts it and waits for the agent to answer.
#
# It touches nothing outside `$PREFIX` except the one service file, and
# `--uninstall` removes both. It never needs root.
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
PIN_AGENT=d1cfe73140f464c8772f45f57441c6c0fbcf7fc1
PIN_CONTROL=7fe2d17c213b27860cd6bbf9db406b4f0973ae39
PIN_GATEWAY=899ae992f6752439924a9ffbd050f2d4fa9cd63b
PIN_DRIVER=ed26e6c5435b30ac8e9e4cbaeb55952e4448bdd2
PIN_LIBRARY=8502ac33cb6ac5bf66e07ac1a0afe39967ef98e1
PIN_UI=e7117770e3bcde8ee633a9ac975744adee77b980   # branch `dist`, not `main`

PY_VERSION=3.12
SERVICE_LABEL=eugene-plexus-agent
LAUNCHD_LABEL=com.eugeneplexus.agent

PREFIX=${EUGENE_PLEXUS_HOME:-$HOME/.local/share/eugene-plexus}
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
        --no-service) DO_SERVICE=0; shift ;;
        --no-start) DO_START=0; shift ;;
        --uninstall) DO_UNINSTALL=1; shift ;;
        --purge-downloads|--purge-model-copies) DO_PURGE_COPIES=1; shift ;;
        --join) JOIN_CONTROL=$2; shift 2 ;;
        --token) JOIN_TOKEN=$2; shift 2 ;;
        --name) JOIN_NAME=$2; shift 2 ;;
        --advertise) JOIN_ADVERTISE=$2; shift 2 ;;
        -h|--help)
            sed -n '2,40p' "$0" 2>/dev/null || true
            echo "options: --prefix DIR  --no-service  --no-start  --uninstall"
            echo "           --purge-downloads  (with --uninstall: delete this install's model"
            echo "                              copies and engine builds, which live outside the prefix)"
            echo "  worker node: --join URL --token JWT [--name NAME] [--advertise URL]"
            echo "  standalone:  --advertise URL   (the address other devices reach this one at)"
            exit 0 ;;
        *) echo "install.sh: unknown option $1" >&2; exit 2 ;;
    esac
done

VENV=$PREFIX/venv
PYBIN=$VENV/bin/python
UV=$PREFIX/bin/uv

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
        STEP_LOG=$PREFIX/logs/install.log
        mkdir -p "$PREFIX/logs"
        : > "$STEP_LOG"
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

# --- service plumbing -------------------------------------------------
# Both are *user* services. The agent reads the user's own model
# directories and writes to the user's own keyring; running it as a
# system daemon under another account would put it on the wrong side of
# both. The cost is stated where it bites, at enable-linger below.
SYSTEMD_UNIT=$HOME/.config/systemd/user/$SERVICE_LABEL.service
LAUNCHD_PLIST=$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist

service_stop() {
    if [ "$PLATFORM" = linux ]; then
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

# --- 1. uv ------------------------------------------------------------
say "installing into $PREFIX"
mkdir -p "$PREFIX/bin" "$PREFIX/logs"

if [ -x "$UV" ]; then
    say "uv already present ($("$UV" --version))"
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
if [ -x "$PYBIN" ]; then
    say "virtualenv already present"
else
    say "creating a Python $PY_VERSION virtualenv (uv downloads the interpreter; none is required on this machine)"
    # `only-managed` rather than uv's default, which prefers a matching
    # interpreter already on the machine. Preferring one would make the
    # sentence above false wherever it is true -- and it would tie the
    # install to a Python the user can upgrade or remove out from under
    # it, which contradicts "removing the prefix is complete".
    run_step "creating a Python $PY_VERSION virtualenv at $VENV" \
        "$UV" venv --python "$PY_REQUEST" --python-preference only-managed "$VENV"
    [ -x "$PYBIN" ] || die "uv reported success but there is no interpreter at $PYBIN"
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
if [ -f "$PREFIX/agent.yaml" ]; then
    warn "Before updating an initialized install, keep a stopped-install checkpoint: https://github.com/eugene-plexus/specs/blob/main/docs/recovery.md"
    warn "Rollback restores matching software AND state; installing an older release does not undo data migrations."
fi
gh_archive() { printf 'https://github.com/eugene-plexus/%s/archive/%s.tar.gz' "$1" "$2"; }

say "installing Eugene Plexus"
run_step "installing the six Eugene Plexus packages" \
    "$UV" pip install --python "$PYBIN" \
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
"$PYBIN" - <<'PYEOF' || die "the install is incomplete — see above"
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

[ -x "$VENV/bin/eugene-plexus-agent" ] || die "the eugene-plexus-agent command did not install"
say "all six packages present, with a web UI"

# --- 4b. join, if this machine is a worker ----------------------------
# **The installer owns the one onboarding question, because this is the
# only moment a human is reliably present.** The agent's own first-boot
# prompt needs a TTY *and* someone watching it, and the unit files below
# pass `--unattended` precisely because a Windows scheduled task has the
# first without the second. So: named on the command line, we enroll
# now; not named, this machine is the start of a new install, which is
# what every unit then boots into.
CONFIG=$PREFIX/agent.yaml

if [ -n "$JOIN_CONTROL" ]; then
    [ -n "$JOIN_TOKEN" ] || die "--join needs --token (mint one at the control root: Nodes -> Add a node)"
    say "joining $JOIN_CONTROL as a worker node"
    # `if` rather than `[ ... ] && set --`: under `set -e` a false test
    # at the end of a && chain is the script's exit status, so the
    # short-circuit would end the install rather than skip an option.
    set -- join --control "$JOIN_CONTROL" --token "$JOIN_TOKEN"
    if [ -n "$JOIN_NAME" ]; then set -- "$@" --name "$JOIN_NAME"; fi
    if [ -n "$JOIN_ADVERTISE" ]; then set -- "$@" --advertise "$JOIN_ADVERTISE"; fi
    EUGENE_PLEXUS_AGENT_CONFIG_FILE=$CONFIG "$VENV/bin/eugene-plexus-agent" "$@"         || die "enrollment failed; nothing was started"
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
    mkdir -p "$PREFIX"
    if [ -f "$CONFIG" ]; then
        grep -v '^advertiseUrl:' "$CONFIG" > "$CONFIG.tmp"
        printf 'advertiseUrl: %s\n' "$JOIN_ADVERTISE" >> "$CONFIG.tmp"
        mv "$CONFIG.tmp" "$CONFIG"
    else
        printf 'advertiseUrl: %s\n' "$JOIN_ADVERTISE" > "$CONFIG"
    fi
    ADVERTISED=1
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

if [ "$DO_SERVICE" = 1 ] && [ "$PLATFORM" = linux ]; then
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
if [ "$DO_START" = 1 ] && [ "$DO_SERVICE" = 1 ]; then
    say "starting the agent"
    if [ "$PLATFORM" = linux ]; then
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
            say "logs:  $PREFIX/logs/    config: $CONFIG"
            exit 0
        fi
        i=$((i + 1))
        sleep 1
    done
    warn "the agent did not answer on port $PORT within 60s. Check:"
    if [ "$PLATFORM" = linux ]; then
        echo "    systemctl --user status $SERVICE_LABEL"
        echo "    journalctl --user -u $SERVICE_LABEL -n 50"
    else
        echo "    tail -50 $PREFIX/logs/launchd.err.log"
    fi
    exit 1
fi

say "installed. Start it with:"
if [ "$DO_SERVICE" = 1 ] && [ "$PLATFORM" = linux ]; then
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
echo "    logs:  $PREFIX/logs/    config: $CONFIG"
