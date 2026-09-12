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
PIN_AGENT=46ac6ef34e2c5f00bf695910636ac47b048ae247
PIN_CONTROL=82df602b06999ded4983b41bc44ee219fb3a85d4
PIN_GATEWAY=bf2c930609eadf58c5225a5bb7b90bc60cce8e90
PIN_DRIVER=b2aab879cdfbaa328e2403e0e3ce2601810b2aaf
PIN_LIBRARY=1a59e7e7ca3f5895a092cfeeca4a562c65d76010
PIN_UI=1ffbdd25c6c5bde89ce3a04bd1a35158ae8448cc   # branch `dist`, not `main`

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

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=$2; shift 2 ;;
        --prefix=*) PREFIX=${1#--prefix=}; shift ;;
        --no-service) DO_SERVICE=0; shift ;;
        --no-start) DO_START=0; shift ;;
        --uninstall) DO_UNINSTALL=1; shift ;;
        --join) JOIN_CONTROL=$2; shift 2 ;;
        --token) JOIN_TOKEN=$2; shift 2 ;;
        --name) JOIN_NAME=$2; shift 2 ;;
        --advertise) JOIN_ADVERTISE=$2; shift 2 ;;
        -h|--help)
            sed -n '2,40p' "$0" 2>/dev/null || true
            echo "options: --prefix DIR  --no-service  --no-start  --uninstall"
            echo "  worker node: --join URL --token JWT [--name NAME] [--advertise URL]"
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
if [ "$DO_UNINSTALL" = 1 ]; then
    say "stopping the service"
    service_stop
    rm -f "$SYSTEMD_UNIT" "$LAUNCHD_PLIST"
    [ "$PLATFORM" = linux ] && systemctl --user daemon-reload >/dev/null 2>&1 || true
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
    UV_UNMANAGED_INSTALL="$PREFIX/bin" \
        sh -c "$(curl -fsSL https://astral.sh/uv/install.sh)" >/dev/null 2>&1 \
        || die "could not install uv from https://astral.sh/uv/install.sh"
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
    "$UV" venv --python "$PY_VERSION" --python-preference only-managed "$VENV" >/dev/null 2>&1 \
        || die "could not create a virtualenv at $VENV"
fi

# --- 3. packages ------------------------------------------------------
gh_archive() { printf 'https://github.com/eugene-plexus/%s/archive/%s.tar.gz' "$1" "$2"; }

say "installing Eugene Plexus"
"$UV" pip install --python "$PYBIN" \
    "eugene-plexus-agent @ $(gh_archive agent "$PIN_AGENT")" \
    "eugene-plexus-control @ $(gh_archive control "$PIN_CONTROL")" \
    "eugene-plexus-gateway @ $(gh_archive gateway "$PIN_GATEWAY")" \
    "eugene-plexus-inference-driver @ $(gh_archive inference-driver "$PIN_DRIVER")" \
    "eugene-plexus-library @ $(gh_archive library "$PIN_LIBRARY")" \
    "eugene-plexus-ui @ $(gh_archive ui "$PIN_UI")" \
    >/dev/null 2>&1 || die "package install failed — re-run with the pip output visible:
  $UV pip install --python $PYBIN 'eugene-plexus-agent @ $(gh_archive agent "$PIN_AGENT")'"

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
fi

# --- 5. service -------------------------------------------------------

# Set once, used by both unit writers below.
if [ "$JOINED" = 1 ]; then
    WIDE_BIND_UNIT="Environment=EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0"
    WIDE_BIND_PLIST="
        <key>EUGENE_PLEXUS_AGENT_BIND_HOST</key><string>0.0.0.0</string>"
else
    WIDE_BIND_UNIT="# this install is single-machine; the agent stays on loopback"
    WIDE_BIND_PLIST=""
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
        <key>EUGENE_PLEXUS_AGENT_CONFIG_FILE</key><string>$CONFIG</string>$WIDE_BIND_PLIST
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
PORT=${EUGENE_PLEXUS_AGENT_BIND_PORT:-8079}
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
