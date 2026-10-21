#!/usr/bin/env bash
# Row 8, the POSIX half -- `install.sh`'s `--label`, and its Mac system
# layout driven on stand-ins for the Mac's tools, with no network and no
# root.
#
# Design: docs/design/rows/row-08.md. Run on Linux (CI's POSIX installer job,
# or WSL from a Windows box). It never touches a real install: `$HOME` is a
# throwaway folder, every prefix is under the work folder, and the Mac runs
# use a COPY of install.sh whose two root paths -- the LaunchDaemons folder
# and the receipts folder -- are rewritten into the work folder. That is the
# only edit, and the copy is checked for it before anything runs.
#
# Stand-ins: `uv`, `curl`, `systemctl`, `loginctl` (as r22 has them), and for
# the Mac `uname`, `sudo`, `dscl`, `dseditgroup`, `id` (for Eugene's account
# only), `launchctl`, `plutil` (Python's plistlib, so the plist is really
# parsed), `ditto`, `install` and `chown`. Every branch of install.sh is real.
# What a stand-in cannot show -- launchd running the job as the account,
# Metal, the firewall, removal -- is the macOS acceptance's
# (row8-macos-daemon-acceptance.py, on GitHub's macOS runners).
#
#   L1. --label without --join is refused, before anything is made
#   L2. --label 'Studio PC' reaches the agent's join as one argument; so do
#       an apostrophe and a dollar sign
#   L3. a job site's join takes --label before --name
#   M1. on a Mac the default layout is the system one: a LaunchDaemon in
#       _eugeneplexus, no LaunchAgent, the account hidden with no shell and
#       no password, in the person's group, a free number below 400, the
#       receipt, the passphrase file, passphrase_file mode
#   M2. a plist naming root, or nobody, or an account numbered 0, is refused
#       and never moved into place
#   M3. --user beside the daemon is refused
#   M4. a LaunchAgent install moves: words first, its state copied, paths and
#       securityMode rewritten, its port kept, the old folder moved aside
#   M5. launchctl refusing the daemon puts the LaunchAgent back, with
#       launchctl's words, the old folder untouched and the copy and the
#       account removed
#   M6. a move refuses --no-start
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
INSTALL_SH=$HERE/install.sh
WORK=${EP_WORKDIR:-/tmp/ep-row8}

FAILURES=0
ok()  { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
say() { printf '\n== %s\n' "$*"; }
show() { printf '%s\n' "$1" | tail -n "${2:-8}" | sed 's/^/      /'; }

[ -f "$INSTALL_SH" ] || { echo "no install.sh at $INSTALL_SH" >&2; exit 2; }
command -v python3 >/dev/null || { echo "python3 is needed for the plist stand-in" >&2; exit 2; }
rm -rf "$WORK"
mkdir -p "$WORK"

# --- stand-ins shared by every run ---------------------------------------
write_common_stubs() {
  local bin=$1
  mkdir -p "$bin"
  cat > "$bin/uv" <<'STUB'
#!/bin/sh
case "$1" in
  --version) echo "uv 0.12.22 (stub)" ;;
  venv)
    for last in "$@"; do :; done
    mkdir -p "$last/bin"
    cp "$EP_STUB_BIN/python-stub" "$last/bin/python"
    cp "$EP_STUB_BIN/agent-stub" "$last/bin/eugene-plexus-agent"
    chmod +x "$last/bin/python" "$last/bin/eugene-plexus-agent"
    ;;
esac
exit 0
STUB
  # The install's Python: answers the two questions install.sh asks of it
  # by -c, runs a script given on stdin with -I (the move's rewrite), and
  # swallows everything else (the package check).
  cat > "$bin/python-stub" <<'STUB'
#!/bin/sh
case "$*" in
  *platform.machine*) echo arm64; exit 0 ;;
  *os.path.realpath*) echo "$(dirname "$(dirname "$0")")/../pythons/cpython-3.12/bin/python3.12"; exit 0 ;;
esac
if [ "${1:-}" = -I ] && [ "${2:-}" = - ]; then shift 2; exec python3 -I - "$@"; fi
cat >/dev/null 2>&1 || true
exit 0
STUB
  # The agent: records every argument on a line of its own.
  cat > "$bin/agent-stub" <<'STUB'
#!/bin/sh
for a in "$@"; do printf '%s\n' "$a"; done > "${EP_STUB_ARGS:-/dev/null}"
exit 0
STUB
  cat > "$bin/curl" <<'STUB'
#!/bin/sh
case "$*" in
  *healthz*) [ "${EP_STUB_HEALTH_FAILS:-0}" = 1 ] && exit 7; exit 0 ;;
esac
OUTFILE=
prev=
for a in "$@"; do
  [ "$prev" = "-o" ] && OUTFILE=$a
  prev=$a
done
emit() {
  case "$*" in
    *astral.sh/uv/install.sh*)
      echo 'mkdir -p "$UV_UNMANAGED_INSTALL"'
      echo 'cp "$EP_STUB_BIN/uv" "$UV_UNMANAGED_INSTALL/uv"'
      ;;
    *) echo ok ;;
  esac
}
if [ -n "$OUTFILE" ] && [ "$OUTFILE" != /dev/null ]; then emit "$@" > "$OUTFILE"; else emit "$@"; fi
exit 0
STUB
  for name in systemctl loginctl; do
    printf '#!/bin/sh\ncase "$*" in *Linger*) echo yes ;; esac\nexit 0\n' > "$bin/$name"
  done
  chmod +x "$bin"/*
}

# --- stand-ins for a Mac ----------------------------------------------------
write_mac_stubs() {
  local bin=$1
  printf '#!/bin/sh\ncase "${1:-}" in -m) echo arm64 ;; *) echo Darwin ;; esac\n' > "$bin/uname"
  # Not root here: sudo runs the command as this account.
  cat > "$bin/sudo" <<'STUB'
#!/bin/sh
while [ $# -gt 0 ]; do
  case "$1" in -v|-n) shift ;; -u) shift 2 ;; --) shift; break ;; *) break ;; esac
done
[ $# -gt 0 ] || exit 0
exec "$@"
STUB
  # The directory service, kept in a file. 400 is taken, so the account
  # must get 399.
  cat > "$bin/dscl" <<'STUB'
#!/bin/sh
state=$EP_STUB_STATE/dscl
shift
verb=$1; shift
printf '%s %s\n' "$verb" "$*" >> "$EP_STUB_STATE/dscl.log"
case "$verb" in
  -list)
    case "$1" in
      /Users) printf 'root 0\ndaemon 1\n_taken 400\n'
              grep '^/Users/[^ ]* UniqueID ' "$state" 2>/dev/null | sed 's|^/Users/||; s/ UniqueID / /' ;;
      /Groups) printf 'wheel 0\nstaff 20\n'
               grep '^/Groups/[^ ]* PrimaryGroupID ' "$state" 2>/dev/null | sed 's|^/Groups/||; s/ PrimaryGroupID / /' ;;
    esac ;;
  -read)
    if [ "${2:-}" = NFSHomeDirectory ] && [ "$1" = "/Users/$EP_STUB_PERSON" ]; then
      echo "NFSHomeDirectory: $HOME"; exit 0
    fi
    v=$(grep "^$1 ${2:-} " "$state" 2>/dev/null | tail -n 1 | cut -d' ' -f3-)
    [ -n "$v" ] || exit 56
    echo "${2}: $v" ;;
  -create)
    [ $# -ge 3 ] && printf '%s %s %s\n' "$1" "$2" "$3" >> "$state"
    touch "$state" ;;
  -delete)
    sed -i "\\|^$1 |d" "$state" 2>/dev/null || true ;;
esac
exit 0
STUB
  cat > "$bin/dseditgroup" <<'STUB'
#!/bin/sh
printf '%s\n' "$*" >> "$EP_STUB_STATE/dseditgroup.log"
case "$*" in *checkmember*) exit 1 ;; esac
exit 0
STUB
  # `id` for Eugene's account comes from the directory service; anything
  # else is the real one.
  cat > "$bin/id" <<'STUB'
#!/bin/sh
for a in "$@"; do
  if [ "$a" = _eugeneplexus ]; then
    uid=$(grep '^/Users/_eugeneplexus UniqueID ' "$EP_STUB_STATE/dscl" 2>/dev/null | tail -n 1 | cut -d' ' -f3)
    gid=$(grep '^/Users/_eugeneplexus PrimaryGroupID ' "$EP_STUB_STATE/dscl" 2>/dev/null | tail -n 1 | cut -d' ' -f3)
    [ -n "$uid" ] || exit 1
    [ -z "${EP_STUB_ACCOUNT_UID:-}" ] || uid=$EP_STUB_ACCOUNT_UID
    case "$1" in -u) echo "$uid" ;; -g) echo "$gid" ;; -Gn) echo _eugeneplexus ;; *) echo "uid=$uid(_eugeneplexus)" ;; esac
    exit 0
  fi
done
exec /usr/bin/id "$@"
STUB
  cat > "$bin/launchctl" <<'STUB'
#!/bin/sh
printf '%s\n' "$*" >> "$EP_STUB_STATE/launchctl.log"
case "$*" in
  "bootstrap system "*)
    if [ "${EP_STUB_LAUNCHCTL_FAIL:-}" = bootstrap ]; then
      echo "Bootstrap failed: 5: Input/output error" >&2; exit 5
    fi ;;
  print*) exit 113 ;;
esac
exit 0
STUB
  # plutil: the plist really parsed, by Python's plistlib.
  cat > "$bin/plutil" <<'STUB'
#!/bin/sh
case "$1" in
  -lint) exec python3 -c 'import plistlib, sys; plistlib.load(open(sys.argv[1], "rb")); print(sys.argv[1] + ": OK")' "$2" ;;
  -extract)
    key=$2; file=$6   # plutil -extract KEY raw -o - FILE
    if [ "$key" = UserName ] && [ -n "${EP_STUB_PLIST_USER+set}" ]; then
      [ -n "$EP_STUB_PLIST_USER" ] || exit 1
      printf '%s' "$EP_STUB_PLIST_USER"; exit 0
    fi
    exec python3 -c '
import plistlib, sys
value = plistlib.load(open(sys.argv[2], "rb"))
for part in sys.argv[1].split("."):
    try:
        value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, ValueError):
        sys.exit(1)
sys.stdout.write("true" if value is True else "false" if value is False else str(value))
' "$key" "$file" ;;
esac
exit 1
STUB
  cat > "$bin/ditto" <<'STUB'
#!/bin/sh
if [ -d "$1" ]; then mkdir -p "$2" && cp -R "$1/." "$2/"; else cp -p "$1" "$2"; fi
STUB
  cat > "$bin/install" <<'STUB'
#!/bin/sh
if [ "$1" = -d ]; then
  shift; mode=
  while [ $# -gt 0 ]; do
    case "$1" in -m) mode=$2; shift 2 ;; -o|-g) shift 2 ;; *) break ;; esac
  done
  for d in "$@"; do mkdir -p "$d"; [ -z "$mode" ] || chmod "$mode" "$d"; done
  exit 0
fi
exec /usr/bin/install "$@"
STUB
  printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "$EP_STUB_STATE/chown.log"\nexit 0\n' > "$bin/chown"
  chmod +x "$bin"/*
}

# A copy of install.sh whose two root paths are under the work folder.
mac_copy() {
  local root=$1
  python3 - "$INSTALL_SH" "$root/install.sh" "$root/LaunchDaemons" "$root/receipts" <<'PY'
import sys
source, target, daemons, receipts = sys.argv[1:]
text = open(source, encoding="utf-8").read()
for old, new in (
    ("LAUNCHD_DAEMON=/Library/LaunchDaemons/$LAUNCHD_LABEL.plist\n",
     f"LAUNCHD_DAEMON={daemons}/$LAUNCHD_LABEL.plist\n"),
    ("MAC_RECEIPTS=/usr/local/lib/eugene-plexus\n", f"MAC_RECEIPTS={receipts}\n"),
):
    if text.count(old) != 1:
        sys.exit(f"refusing to run: {old.strip()!r} appears {text.count(old)} times")
    text = text.replace(old, new)
open(target, "w", encoding="utf-8", newline="\n").write(text)
PY
  mkdir -p "$root/LaunchDaemons"
}

# run_linux TAG [args...] -> OUT, RC; a per-user install, as r22 runs it.
run_linux() {
  local tag=$1; shift
  local root=$WORK/$tag
  rm -rf "$root"; mkdir -p "$root/bin" "$root/home" "$root/run"
  write_common_stubs "$root/bin"
  OUT=$(env -i HOME="$root/home" XDG_RUNTIME_DIR="$root/run" PATH="$root/bin:/usr/bin:/bin" \
    EP_STUB_BIN="$root/bin" EP_STUB_ARGS="$root/args.txt" \
    sh "$INSTALL_SH" --user --prefix "$root/prefix" --no-start "$@" 2>&1)
  RC=$?
}

# run_mac TAG [args...] -> OUT, RC; the Mac's default layout, on stand-ins.
# Reuses TAG's folder when it exists, so a second run sees the first.
run_mac() {
  local tag=$1; shift
  ROOT=$WORK/$tag
  if [ ! -d "$ROOT/bin" ]; then
    mkdir -p "$ROOT/bin" "$ROOT/home" "$ROOT/state"
    write_common_stubs "$ROOT/bin"
    write_mac_stubs "$ROOT/bin"
    mac_copy "$ROOT"
  fi
  PREFIX=$ROOT/eugene-plexus
  DAEMON=$ROOT/LaunchDaemons/com.eugeneplexus.agent.plist
  OUT=$(cd "$ROOT" && env -i HOME="$ROOT/home" PATH="$ROOT/bin:/usr/bin:/bin" \
    EP_STUB_BIN="$ROOT/bin" EP_STUB_STATE="$ROOT/state" EP_STUB_PERSON="$(id -un)" \
    EP_STUB_ARGS="$ROOT/args.txt" ${EP_EXTRA_ENV:-} \
    sh "$ROOT/install.sh" --prefix "$PREFIX" "$@" 2>&1)
  RC=$?
}

plist() { python3 -c '
import plistlib, sys
value = plistlib.load(open(sys.argv[1], "rb"))
for part in sys.argv[2].split("."):
    value = value[int(part)] if isinstance(value, list) else value[part]
print(value)' "$1" "$2" 2>/dev/null; }

# --- L. --label ---------------------------------------------------------------
say "L1. --label without --join is refused, before anything is made"
run_linux label-alone --label 'Studio PC'
if [ "$RC" = 2 ] && printf '%s' "$OUT" | grep -q "The first machine's name is asked on its setup page" \
    && [ ! -e "$WORK/label-alone/prefix" ]; then
  ok "refused with the setup page named, and no prefix made"
else
  bad "rc=$RC"; show "$OUT"
fi

say "L2. --label reaches the agent's join as one argument"
for shown in 'Studio PC' "Troy's \$HOME box"; do
  run_linux label-join --join http://192.0.2.10:8083 --token t0k --name studio --label "$shown"
  args=$(cat "$WORK/label-join/args.txt" 2>/dev/null)
  next=$(printf '%s\n' "$args" | awk 'p { print; exit } $0 == "--label" { p = 1 }')
  if [ "$RC" = 0 ] && [ "$next" = "$shown" ] && printf '%s\n' "$args" | grep -qx -- '--name'; then
    ok "join got --label [$shown] whole, after --name"
  else
    bad "rc=$RC; the join got: $(printf '%s' "$args" | tr '\n' '|')"; show "$OUT"
  fi
done

say "L3. a job site's join takes --label before --name"
run_linux label-site
rm -f "$WORK/label-site/args.txt"
OUT=$(env -i HOME="$WORK/label-site/home" XDG_RUNTIME_DIR="$WORK/label-site/run" \
  PATH="$WORK/label-site/bin:/usr/bin:/bin" EP_STUB_BIN="$WORK/label-site/bin" \
  EP_STUB_ARGS="$WORK/label-site/args.txt" \
  sh "$INSTALL_SH" --user --prefix "$WORK/label-site/prefix" --join https://nodes.example.com \
  --token t --job-site --owner ada --name studio --label 'Studio PC' 2>&1)
args=$(cat "$WORK/label-site/args.txt" 2>/dev/null)
if [ "$(printf '%s\n' "$args" | awk 'p { print; exit } $0 == "--label" { p = 1 }')" = 'Studio PC' ] \
    && printf '%s\n' "$args" | head -n 2 | tr '\n' ' ' | grep -q '^site join'; then
  ok "site join got --label 'Studio PC', not the --name"
else
  bad "site join got: $(printf '%s' "$args" | tr '\n' '|')"; show "$OUT"
fi

# --- M. the Mac ---------------------------------------------------------------
say "M1. on a Mac the default is a LaunchDaemon in _eugeneplexus"
run_mac fresh --no-start
STATE=$ROOT/state
if [ "$RC" = 0 ]; then ok "the install ran to the end"; else bad "rc=$RC"; show "$OUT" 15; fi
if [ -f "$DAEMON" ] && [ ! -e "$ROOT/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ]; then
  ok "a LaunchDaemon plist, and no LaunchAgent"
else
  bad "daemon=$([ -f "$DAEMON" ] && echo yes || echo no) agent=$([ -e "$ROOT/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ] && echo yes || echo no)"
fi
if [ "$(plist "$DAEMON" UserName)" = _eugeneplexus ] && [ "$(plist "$DAEMON" GroupName)" = _eugeneplexus ] \
    && [ "$(plist "$DAEMON" ProgramArguments.0)" = "$PREFIX/venv/bin/eugene-plexus-agent" ] \
    && [ "$(plist "$DAEMON" KeepAlive)" = True ] && [ "$(plist "$DAEMON" RunAtLoad)" = True ]; then
  ok "it parses, runs the prefix's agent as _eugeneplexus:_eugeneplexus, and is kept alive"
else
  bad "the plist: $(cat "$DAEMON" 2>/dev/null | tr '\n' ' ' | head -c 600)"
fi
if [ "$(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_AGENT_PASSPHRASE_FILE)" = "$PREFIX/passphrase" ] \
    && [ "$(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_CONTROL_PASSPHRASE_FILE)" = "$PREFIX/passphrase" ] \
    && [ "$(plist "$DAEMON" EnvironmentVariables.HOME)" = "$PREFIX" ] \
    && [ "$(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_AGENT_ENGINE_ROOT)" = "$PREFIX/engines" ] \
    && grep -qx 'securityMode: passphrase_file' "$PREFIX/agent.yaml" 2>/dev/null; then
  ok "it unlocks from the passphrase file in the prefix, its home and engines there too"
else
  bad "environment or securityMode: $(grep securityMode "$PREFIX/agent.yaml" 2>/dev/null)"
fi
if grep -qx '/Users/_eugeneplexus UniqueID 399' "$STATE/dscl" \
    && grep -qx '/Users/_eugeneplexus UserShell /usr/bin/false' "$STATE/dscl" \
    && grep -qx '/Users/_eugeneplexus IsHidden 1' "$STATE/dscl" \
    && grep -qx "/Users/_eugeneplexus Password \*" "$STATE/dscl" \
    && grep -qx "/Users/_eugeneplexus NFSHomeDirectory $PREFIX" "$STATE/dscl" \
    && grep -qx '/Groups/_eugeneplexus PrimaryGroupID 399' "$STATE/dscl"; then
  ok "the account: number 399 (400 was taken), no shell, hidden, no password, home the prefix"
else
  bad "the account: $(grep _eugeneplexus "$STATE/dscl" 2>/dev/null | tr '\n' '|')"
fi
if grep -qx -- "-o edit -a _eugeneplexus -t user $(id -gn)" "$STATE/dseditgroup.log" 2>/dev/null; then
  ok "it joins the person's group, $(id -gn)"
else
  bad "dseditgroup: $(cat "$STATE/dseditgroup.log" 2>/dev/null | tr '\n' '|')"
fi
if [ "$(cat "$ROOT/receipts/account.txt" 2>/dev/null)" = "account 399 399 1" ]; then
  ok "the receipt records the account and group this installer made"
else
  bad "receipt: $(cat "$ROOT/receipts/account.txt" 2>/dev/null)"
fi
if [ -f "$ROOT/receipts/remove.sh" ] && grep -q 'DAEMON_PLIST=' "$ROOT/receipts/remove.sh" \
    && [ -x "$ROOT/home/Applications/Remove Eugene Plexus.app/Contents/MacOS/remove" ]; then
  ok "root's own removal script, outside the prefix, and the removal app"
else
  bad "removal: script=$([ -f "$ROOT/receipts/remove.sh" ] && echo yes || echo no)"
fi
if printf '%s' "$OUT" | grep -q 'any program you run as you'; then
  bad "the system layout printed the per-user warning"
fi

say "M2. a startup job for root, for nobody, or for account 0 is refused"
for case_ in "EP_STUB_PLIST_USER=root" "EP_STUB_PLIST_USER=" "EP_STUB_ACCOUNT_UID=0"; do
  rm -f "$DAEMON"
  EP_EXTRA_ENV=$case_ run_mac fresh --no-start
  if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -qi 'refusing a startup job\|must be a service' \
      && [ ! -f "$DAEMON" ]; then
    ok "$case_: refused, and no plist moved into place"
  else
    bad "$case_: rc=$RC daemon=$([ -f "$DAEMON" ] && echo present || echo absent)"; show "$OUT" 4
  fi
done
EP_EXTRA_ENV=

say "M3. --user beside the daemon is refused"
run_mac fresh --no-start
OUT_KEEP=$OUT
EP_EXTRA_ENV= run_mac fresh --user --no-start
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q "This Mac already starts Eugene at boot. Re-run without --user to update it." \
    && [ ! -e "$ROOT/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ]; then
  ok "refused, in the design's words, and no LaunchAgent written"
else
  bad "rc=$RC"; show "$OUT" 4; show "$OUT_KEEP" 3
fi

# A per-user Mac install as the old layout left it: a LaunchAgent naming
# its prefix, on port 18279, onboarded with the Keychain.
old_install() {
  local home=$1 old=$1/.local/share/eugene-plexus
  mkdir -p "$old/venv/bin" "$old/logs" "$old/control-state" "$home/Library/LaunchAgents" \
    "$home/.eugene-plexus/engines/llama_cpp/b1"
  printf 'name: studio\nnodeKey: abc\n' > "$old/node.yaml"
  cat > "$old/agent.yaml" <<YAML
securityMode: os_keyring
firstRunComplete: true
components:
- kind: control
  spawn:
    configFile: $old/control.yaml
modelCopyDir: $old
YAML
  printf 'securityMode: os_keyring\nstateDir: %s/control-state\n' "$old" > "$old/control.yaml"
  printf '{"profiles": {"p1": {"modelPath": "%s/Eugene Models/m.gguf"}}}\n' "$home" > "$old/library-state.json"
  printf 'snapshot\n' > "$old/control-state/snap.bin"
  printf 'build\n' > "$home/.eugene-plexus/engines/llama_cpp/b1/llama-server"
  cat > "$home/Library/LaunchAgents/com.eugeneplexus.agent.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.eugeneplexus.agent</string>
    <key>ProgramArguments</key>
    <array><string>$old/venv/bin/eugene-plexus-agent</string><string>--unattended</string></array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>EUGENE_PLEXUS_AGENT_CONFIG_FILE</key><string>$old/agent.yaml</string>
        <key>EUGENE_PLEXUS_AGENT_BIND_PORT</key><string>18279</string>
        <key>EUGENE_PLEXUS_AGENT_BIND_HOST</key><string>0.0.0.0</string>
    </dict>
</dict>
</plist>
PLIST
}

say "M4. a LaunchAgent install moves to the daemon"
mkdir -p "$WORK/move/home"
old_install "$WORK/move/home"
OLD=$WORK/move/home/.local/share/eugene-plexus
run_mac move
STATE=$ROOT/state
if [ "$RC" = 0 ]; then ok "the move finished"; else bad "rc=$RC"; show "$OUT" 15; fi
words=$(printf '%s' "$OUT" | grep -n 'Eugene will start when this Mac starts, before anyone signs in' | cut -d: -f1 | head -n 1)
copied=$(printf '%s' "$OUT" | grep -n 'copying its identity' | cut -d: -f1 | head -n 1)
if [ -n "$words" ] && [ -n "$copied" ] && [ "$words" -lt "$copied" ] \
    && printf '%s' "$OUT" | grep -q 'sign in to Eugene once; from then on'; then
  ok "it says what happens before it does anything"
else
  bad "the words: line ${words:-none}, the copy: line ${copied:-none}"
fi
if grep -q "^bootout gui/$(id -u)/com.eugeneplexus.agent$" "$STATE/launchctl.log" \
    && grep -q "^bootstrap system $DAEMON$" "$STATE/launchctl.log"; then
  ok "the LaunchAgent was booted out and the daemon bootstrapped"
else
  bad "launchctl: $(tr '\n' '|' < "$STATE/launchctl.log")"
fi
if [ "$(cat "$PREFIX/node.yaml" 2>/dev/null)" = "$(printf 'name: studio\nnodeKey: abc')" ] \
    && [ -f "$PREFIX/control-state/snap.bin" ] && [ -f "$PREFIX/library-state.json" ] \
    && [ -f "$PREFIX/engines/llama_cpp/b1/llama-server" ] && [ ! -e "$PREFIX/uninstall" ]; then
  ok "identity, control state, Library state and engine builds came along; the old removal did not"
else
  bad "copied: $(ls -A "$PREFIX" 2>/dev/null | tr '\n' ' ')"
fi
if grep -qx 'securityMode: passphrase_file' "$PREFIX/agent.yaml" \
    && grep -qx 'securityMode: passphrase_file' "$PREFIX/control.yaml" \
    && grep -q "configFile: $PREFIX/control.yaml" "$PREFIX/agent.yaml" \
    && grep -qx "modelCopyDir: $PREFIX" "$PREFIX/agent.yaml" \
    && grep -q "stateDir: $PREFIX/control-state" "$PREFIX/control.yaml" \
    && ! grep -q "$OLD" "$PREFIX/agent.yaml" "$PREFIX/control.yaml" \
    && grep -q "$WORK/move/home/Eugene Models/m.gguf" "$PREFIX/library-state.json"; then
  ok "paths now name the new prefix, the Keychain mode became passphrase_file, models stayed put"
else
  bad "rewritten: $(tr '\n' '|' < "$PREFIX/agent.yaml") // $(tr '\n' '|' < "$PREFIX/control.yaml")"
fi
if [ "$(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_AGENT_BIND_PORT)" = 18279 ] \
    && [ "$(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_AGENT_BIND_HOST)" = 0.0.0.0 ]; then
  ok "the daemon keeps the LaunchAgent's port 18279 and its wide bind"
else
  bad "port/host: $(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_AGENT_BIND_PORT) $(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_AGENT_BIND_HOST)"
fi
moved=$(ls -d "$OLD".moved-* 2>/dev/null | head -n 1)
if [ ! -e "$WORK/move/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ] && [ ! -e "$OLD" ] \
    && [ -n "$moved" ] && [ -f "$moved/node.yaml" ] && [ ! -e "$WORK/move/home/.eugene-plexus/engines" ]; then
  ok "the LaunchAgent is gone, the old folder kept at ${moved##*/}, the engine store moved"
else
  bad "after: agent plist $([ -e "$WORK/move/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ] && echo kept || echo gone), old $([ -e "$OLD" ] && echo kept || echo gone), moved '${moved}'"
fi

say "M5. launchctl refusing the daemon puts the LaunchAgent back"
rm -rf "$WORK/back"
mkdir -p "$WORK/back/home"
old_install "$WORK/back/home"
OLD=$WORK/back/home/.local/share/eugene-plexus
BEFORE=$(cd "$OLD" && find . -type f -exec sha256sum {} + | sort)
EP_EXTRA_ENV=EP_STUB_LAUNCHCTL_FAIL=bootstrap run_mac back
STATE=$ROOT/state
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q 'Bootstrap failed: 5: Input/output error'; then
  ok "the run stops with launchctl's own words"
else
  bad "rc=$RC"; show "$OUT" 10
fi
if grep -q "^bootstrap gui/$(id -u) $WORK/back/home/Library/LaunchAgents/com.eugeneplexus.agent.plist$" "$STATE/launchctl.log" \
    && [ -f "$WORK/back/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ] \
    && printf '%s' "$OUT" | grep -q 'Eugene runs again from'; then
  ok "the LaunchAgent was bootstrapped again and answers"
else
  bad "launchctl: $(tr '\n' '|' < "$STATE/launchctl.log")"; show "$OUT" 4
fi
if [ "$(cd "$OLD" 2>/dev/null && find . -type f -exec sha256sum {} + | sort)" = "$BEFORE" ] \
    && [ -f "$WORK/back/home/.eugene-plexus/engines/llama_cpp/b1/llama-server" ]; then
  ok "the old folder and its engine store are untouched"
else
  bad "the old folder changed"
fi
if [ ! -e "$PREFIX" ] && [ ! -f "$DAEMON" ] && [ ! -f "$ROOT/receipts/account.txt" ] \
    && grep -q '^-delete /Users/_eugeneplexus' "$STATE/dscl.log"; then
  ok "the copy, the daemon plist and the account this run made are gone"
else
  bad "left: prefix=$([ -e "$PREFIX" ] && echo yes || echo no) daemon=$([ -f "$DAEMON" ] && echo yes || echo no) receipt=$([ -f "$ROOT/receipts/account.txt" ] && echo yes || echo no)"
fi

say "M6. a move refuses --no-start, having changed nothing"
rm -rf "$WORK/nostart"
mkdir -p "$WORK/nostart/home"
old_install "$WORK/nostart/home"
run_mac nostart --no-start
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q 'Re-run without --no-start' && [ ! -e "$PREFIX" ] \
    && [ ! -s "$ROOT/state/launchctl.log" ]; then
  ok "refused before stopping anything"
else
  bad "rc=$RC"; show "$OUT" 4
fi

printf '\n'
if [ "$FAILURES" = 0 ]; then
  printf 'Row 8 (install.sh): all checks passed\n'
else
  printf 'Row 8 (install.sh): %s FAILED\n' "$FAILURES"
fi
exit $([ "$FAILURES" = 0 ] && echo 0 || echo 1)
