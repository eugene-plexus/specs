#!/bin/sh
# Eugene Plexus — developer environment for Linux and macOS.
#
#   git clone https://github.com/eugene-plexus/specs
#   sh specs/scripts/bootstrap.sh
#
# Path A of install-paths §4: clones every active repo as a sibling of
# this `specs` checkout, gives each Python repo its own 3.12 virtualenv
# with `[dev]` installed and pre-commit hooks active, sets up the Node
# repos, and — the step that is easy to forget and breaks everything —
# installs every component into the AGENT's virtualenv, because that is
# the interpreter the supervisor spawns children with.
#
# This is NOT the end-user installer. That is `install.sh` beside it:
# one prefix, pinned releases, a service unit. This script builds
# editable checkouts you intend to change.
#
# PREREQUISITES: `git`, and `curl` if `uv` is not already installed.
# **Not** Python — `uv` brings its own if the machine has no 3.12, the
# same way `install.sh` does. **Not** an authenticated `gh` either:
# every repo is public and cloned over HTTPS, which is the difference
# between "a contributor can run this" and "a contributor needs a
# GitHub CLI login first".
#
# Node is optional and only the `ui` and `website` repos need it. Without
# it they are skipped, and the script says what that costs — a dev agent
# with no browser half, because since install-paths §9 step 1 the UI is
# a Python package whose payload is a `next build` export.
#
# Idempotent: re-running skips what is already there.

set -eu

PY_VERSION=3.12
ORG=https://github.com/eugene-plexus

# This script lives in specs/scripts/. The polyrepo root — where sibling
# repos live — is the parent of the specs checkout, unless told
# otherwise. `--root` exists so this script can be run against a
# throwaway directory, which is the only way it has ever been tested.
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SPECS_ROOT=$(CDPATH= cd -- "$HERE/.." && pwd)
ROOT=$(CDPATH= cd -- "$SPECS_ROOT/.." && pwd)
DO_NODE=1

while [ $# -gt 0 ]; do
    case "$1" in
        --root) ROOT=$2; shift 2 ;;
        --root=*) ROOT=${1#--root=}; shift ;;
        --python) PY_VERSION=$2; shift 2 ;;
        --no-node) DO_NODE=0; shift ;;
        -h|--help)
            echo "usage: bootstrap.sh [--root DIR] [--python 3.12] [--no-node]"
            exit 0 ;;
        *) echo "bootstrap.sh: unknown option $1" >&2; exit 2 ;;
    esac
done

mkdir -p "$ROOT"
ROOT=$(CDPATH= cd -- "$ROOT" && pwd)

# The live control plane. `connector` is deferred, `memory`/`identity`
# and the five training repos are retired — see
# docs/maintenance/repository-audit-2026-09-10.md for the inventory.
AGENT_REPO=agent
COMPONENT_REPOS="control gateway inference-driver library"
PYTHON_REPOS="$AGENT_REPO $COMPONENT_REPOS"
# `website` is the project site (Astro, GitHub Pages, eugeneplexus.com).
# Not part of the control plane, cloned anyway: a repo nobody clones is
# a repo nobody discovers.
NODE_REPOS="ui website"
ALL_REPOS="specs $PYTHON_REPOS $NODE_REPOS"

BOOT=$ROOT/.bootstrap
UV=$BOOT/bin/uv

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "git is required"

say "polyrepo root: $ROOT"
say "target Python: $PY_VERSION"
mkdir -p "$BOOT/bin"

# --- uv ---------------------------------------------------------------
# One copy for the whole polyrepo, inside `.bootstrap/` so removing that
# directory undoes everything this script installed outside the repos.
# An existing `uv` on PATH is used as-is: a developer who already has
# one should not get a second.
if command -v uv >/dev/null 2>&1; then
    UV=$(command -v uv)
    say "using uv already on PATH ($("$UV" --version))"
elif [ -x "$UV" ]; then
    say "uv already present ($("$UV" --version))"
else
    say "fetching uv"
    command -v curl >/dev/null 2>&1 || die "curl is required to install uv"
    UV_UNMANAGED_INSTALL="$BOOT/bin" \
        sh -c "$(curl -fsSL https://astral.sh/uv/install.sh)" >/dev/null 2>&1 \
        || die "could not install uv from https://astral.sh/uv/install.sh"
    [ -x "$UV" ] || die "uv did not land at $UV"
    say "uv $("$UV" --version | cut -d' ' -f2)"
fi

# Unlike `install.sh`, this does NOT force `only-managed`. An end-user
# install wants to be self-contained; a developer who already runs
# $PY_VERSION should get their own interpreter, and uv's default
# preference does exactly that — using a matching one if it exists and
# downloading if it does not.

# --- clone ------------------------------------------------------------
say "cloning"
for r in $ALL_REPOS; do
    if [ -d "$ROOT/$r/.git" ]; then
        printf '  %-18s already present\n' "$r"
    else
        printf '  %-18s cloning\n' "$r"
        git clone -q "$ORG/$r.git" "$ROOT/$r" || die "could not clone $r"
    fi
done

# --- pre-commit -------------------------------------------------------
# In its own environment rather than the system Python: most Linux
# distributions now mark that one externally-managed (PEP 668) and
# refuse the install outright, which is where the Windows script's
# `pip install --upgrade pre-commit` would have died first.
PRECOMMIT=$BOOT/venv/bin/pre-commit
if [ ! -x "$PRECOMMIT" ]; then
    say "installing pre-commit"
    "$UV" venv --python "$PY_VERSION" "$BOOT/venv" >/dev/null 2>&1 \
        || die "could not create the tooling virtualenv"
    "$UV" pip install -q --python "$BOOT/venv/bin/python" pre-commit \
        || die "could not install pre-commit"
fi

hooks() {
    [ -f "$ROOT/$1/.pre-commit-config.yaml" ] || return 0
    ( cd "$ROOT/$1" && "$PRECOMMIT" install >/dev/null ) \
        || warn "[$1] pre-commit hooks were not installed"
}

# --- Python repos -----------------------------------------------------
for r in $PYTHON_REPOS; do
    say "[$r]"
    venv=$ROOT/$r/.venv
    if [ ! -x "$venv/bin/python" ]; then
        "$UV" venv --python "$PY_VERSION" "$venv" >/dev/null 2>&1 \
            || die "[$r] could not create $venv"
    fi
    "$UV" pip install -q --python "$venv/bin/python" -e "$ROOT/$r[dev]" \
        || die "[$r] editable install failed"
    hooks "$r"
    printf '  ready (%s)\n' "$("$venv/bin/python" --version)"
done

# --- Node repos -------------------------------------------------------
# **`command -v npm` is not a test for a usable Node toolchain**, and
# WSL is where that bites. With Windows interop on PATH, `npm` resolves
# to /mnt/c/Program Files/nodejs/npm and `npm --version` answers 11.8.0
# — measured — while `node` is absent, and an `npm install` run that way
# writes Windows-native binaries and .bin shims into a Linux directory.
# So: require both commands, and refuse a toolchain reached through
# /mnt/, which is a Windows one wearing a POSIX path.
node_usable() {
    command -v node >/dev/null 2>&1 || return 1
    command -v npm >/dev/null 2>&1 || return 1
    case "$(command -v node):$(command -v npm)" in
        */mnt/*) return 2 ;;
    esac
    return 0
}

NODE_OK=0
node_usable && NODE_STATUS=0 || NODE_STATUS=$?
if [ "$DO_NODE" = 1 ] && [ "$NODE_STATUS" = 2 ]; then
    warn "node/npm here are Windows binaries reached over WSL interop ($(command -v npm)). An npm install run through them writes Windows executables into a Linux tree. Install Node inside this distribution, or pass --no-node."
    DO_NODE=0
fi

if [ "$DO_NODE" = 1 ] && [ "$NODE_STATUS" = 0 ]; then
    NODE_OK=1
    for r in $NODE_REPOS; do
        say "[$r]"
        ( cd "$ROOT/$r" && npm install --no-fund --no-audit >/dev/null 2>&1 ) \
            || die "[$r] npm install failed"
        hooks "$r"
        printf '  ready\n'
    done
    # Codegen and the static export, in that order: the export is built
    # from generated types.
    say "[ui] codegen and static export"
    ( cd "$ROOT/ui" && npm run codegen >/dev/null 2>&1 ) || die "[ui] codegen failed"
    ( cd "$ROOT/ui" && npm run build:python >/dev/null 2>&1 ) || die "[ui] build:python failed"
elif [ "$DO_NODE" = 1 ]; then
    warn "no usable node/npm — skipping ui and website. The dev agent will serve the API and an \"no web UI installed\" page, because since install-paths step 1 the UI is a Python package whose payload is a next build export."
fi

# --- the agent's venv is the install's runtime ------------------------
#
# The agent spawns every component with its own `sys.executable`, and
# `default_topology` decides what to declare by calling `find_spec`
# against that same interpreter. Without this the agent starts, cannot
# import the gateway, and declines to declare it: a working supervisor
# with nothing to supervise.
say "[agent] installing every component into the supervisor's virtualenv"
AGENT_PY=$ROOT/$AGENT_REPO/.venv/bin/python
for r in $COMPONENT_REPOS; do
    "$UV" pip install -q --python "$AGENT_PY" -e "$ROOT/$r" || die "[agent] could not install $r"
    printf '  + %s\n' "$r"
done

# The browser half, editable on purpose: `static_dir()` then resolves
# into the checkout, so `npm run build:python` in `ui` is immediately
# visible to a running agent with no reinstall. `EUGENE_PLEXUS_AGENT_UI_DIR`
# exists for the same job and is the override; this makes the default
# path work without one.
if [ "$NODE_OK" = 1 ]; then
    "$UV" pip install -q --python "$AGENT_PY" -e "$ROOT/ui" || die "[agent] could not install ui"
    printf '  + ui (editable: rebuild with npm run build:python)\n'
fi

# --- assert -----------------------------------------------------------
# The Windows script asserted the imports and nothing else, which was
# the whole story before the UI became a Python package. It is not now:
# an agent that imports every component and serves no browser is a
# half-installed dev environment that looks complete.
say "checking"
"$AGENT_PY" - "$NODE_OK" <<'PYEOF' || die "the developer environment is incomplete"
import importlib.util, sys
from pathlib import Path

want_ui = sys.argv[1] == "1"
bad = []
for mod in (
    "eugene_plexus_agent",
    "eugene_plexus_control",
    "eugene_plexus_gateway",
    "eugene_plexus_inference_driver",
    "eugene_plexus_library",
):
    if importlib.util.find_spec(mod) is None:
        bad.append(f"{mod} is not importable from {sys.executable}")

if want_ui:
    try:
        import eugene_plexus_ui
        static = Path(eugene_plexus_ui.static_dir())
        if not (static / "index.html").is_file():
            bad.append(f"the web UI package has no build output at {static}")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"the web UI package is not usable: {exc}")

for line in bad:
    print(f"  - {line}", file=sys.stderr)
raise SystemExit(1 if bad else 0)
PYEOF

printf '\n'
say "done — every repo is set up under $ROOT"
printf '\n'
printf 'Start a dev control plane from a directory you want the install to live in:\n'
printf '    mkdir -p ~/ep-dev && cd ~/ep-dev\n'
printf '    %s -m eugene_plexus_agent\n' "$AGENT_PY"
printf '\nIt declares and spawns the control root, gateway and library on first\n'
printf 'boot, and serves the UI at http://127.0.0.1:8079/.\n'
if [ "$NODE_OK" = 1 ]; then
    printf '\nFor UI hot reload instead: `npm run dev` in %s/ui.\n' "$ROOT"
fi
