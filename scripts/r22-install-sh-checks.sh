#!/usr/bin/env bash
# R2.2, the POSIX half -- `install.sh` driven end to end with no network.
#
# Roadmap: docs/design/release-roadmap.md §3.2. Findings: review §6.2
# #24 (the stderr of every network step is discarded, and
# EUGENE_PLEXUS_AGENT_BIND_PORT never reaches the unit), §6.2 #30
# (`--advertise` is honoured only in the join branch), §6.3 #31
# (uninstall leaves keyring entries and the model-copy directory).
#
# **Run this on Linux.** `r22-acceptance.sh` invokes it through WSL from
# a Windows box; on a Linux machine it runs directly. It never touches a
# real install: `$HOME` is a throwaway directory, so the systemd unit it
# writes is not the one on this machine, and `--prefix` is under the
# work directory.
#
# **Why stubs and not a real install.** What has to be seen here is what
# `install.sh` *writes* and what it *says when a step fails*, and both
# sit past step 3, which is a real `uv pip install` over the network.
# Four programs are stubbed -- `uv`, `curl`, `systemctl`, `loginctl` --
# and every branch of the script itself is real. `install-acceptance.sh`
# is the run that installs for real; this one is about the paths that
# run cannot reach, because it cannot make the network fail on purpose.
#
# The checks:
#   1. the happy path still installs (the baseline every other check
#      needs, and the thing a broken stub set would silently break)
#   2. **#24a**: a failing `curl` for the uv bootstrap is diagnosed by
#      naming the URL. Before: the command substitution came back empty,
#      `sh -c ""` exited 0, and `|| die` never fired -- the run failed
#      one line later with "uv did not land", which sends a person to
#      look at a directory rather than at their proxy
#   3. **#24b**: a failing `uv venv` shows uv's own stderr
#   4. **#24c**: a failing `uv pip install` shows pip's own stderr
#   5. **#24d**: EUGENE_PLEXUS_AGENT_BIND_PORT reaches the systemd unit
#   6. **#30**: `--advertise` with no `--join` is honoured -- the
#      standalone case -- and the unit binds wide because of it
#   7. `--advertise` does not overwrite an advertiseUrl already set
#   8. **#31**: uninstall drops both keyring entries and names the
#      model-copy directory
#   9. uninstall with --purge-model-copies removes it
#  10. the uninstall still moves the prefix aside rather than deleting it
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
INSTALL_SH=$HERE/install.sh
WORK=${EP_WORKDIR:-/tmp/ep-r22}

FAILURES=0
ok()  { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
say() { printf '\n== %s\n' "$*"; }

[ -f "$INSTALL_SH" ] || { echo "no install.sh at $INSTALL_SH" >&2; exit 2; }

# --- stubs ------------------------------------------------------------
write_stubs() {
  local bin=$1
  mkdir -p "$bin"

  cat > "$bin/uv" <<'STUB'
#!/bin/sh
case "$1" in
  --version) echo "uv 0.0.0-stub" ;;
  venv)
    if [ "${EP_STUB_UV_VENV_FAILS:-0}" = 1 ]; then
      echo "error: TLS certificate verification failed downloading cpython-3.12" >&2
      exit 1
    fi
    for last in "$@"; do :; done
    mkdir -p "$last/bin"
    printf '#!/bin/sh\ncat >/dev/null 2>&1 || true\nexit 0\n' > "$last/bin/python"
    printf '#!/bin/sh\necho "stub agent: $*"\n' > "$last/bin/eugene-plexus-agent"
    chmod +x "$last/bin/python" "$last/bin/eugene-plexus-agent"
    ;;
  pip)
    if [ "${EP_STUB_UV_PIP_FAILS:-0}" = 1 ]; then
      echo "error: Failed to fetch https://github.com/eugene-plexus/agent/archive/x.tar.gz" >&2
      echo "  Caused by: invalid peer certificate: UnknownIssuer" >&2
      exit 1
    fi
    ;;
esac
exit 0
STUB

  # The uv bootstrap is `sh -c "$(curl ... install.sh)"`, so a
  # successful stub curl has to emit a shell program that puts a uv
  # where UV_UNMANAGED_INSTALL says.
  cat > "$bin/curl" <<'STUB'
#!/bin/sh
if [ "${EP_STUB_CURL_FAILS:-0}" = 1 ]; then
  echo "curl: (60) SSL certificate problem: self-signed certificate in chain" >&2
  exit 60
fi
# Honour -o FILE the way curl does; install.sh fetches the uv
# bootstrap to a file now precisely so its failure is visible.
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
if [ -n "$OUTFILE" ]; then emit "$@" > "$OUTFILE"; else emit "$@"; fi
exit 0
STUB

  for name in systemctl loginctl launchctl; do
    cat > "$bin/$name" <<'STUB'
#!/bin/sh
case "$*" in
  *Linger*) echo yes ;;
esac
exit 0
STUB
  done
  chmod +x "$bin"/uv "$bin"/curl "$bin"/systemctl "$bin"/loginctl "$bin"/launchctl
}

# run <name> [args...] -> OUT, RC
PREFIX=
FAKE_HOME=
UNIT=
run() {
  local tag=$1; shift
  local root=$WORK/$tag
  rm -rf "$root"
  PREFIX=$root/prefix
  FAKE_HOME=$root/home
  UNIT=$FAKE_HOME/.config/systemd/user/eugene-plexus-agent.service
  mkdir -p "$root/bin" "$FAKE_HOME" "$root/run"
  write_stubs "$root/bin"
  OUT=$(
    env -i \
      HOME="$FAKE_HOME" \
      XDG_RUNTIME_DIR="$root/run" \
      PATH="$root/bin:/usr/bin:/bin" \
      EP_STUB_BIN="$root/bin" \
      EP_STUB_CURL_FAILS="${EP_STUB_CURL_FAILS:-0}" \
      EP_STUB_UV_VENV_FAILS="${EP_STUB_UV_VENV_FAILS:-0}" \
      EP_STUB_UV_PIP_FAILS="${EP_STUB_UV_PIP_FAILS:-0}" \
      ${EP_EXTRA_ENV:-} \
      sh "$INSTALL_SH" --prefix "$PREFIX" --no-start "$@" 2>&1
  )
  RC=$?
}

# Re-run against an existing prefix without wiping it.
rerun() {
  local root=$WORK/$1; shift
  OUT=$(
    env -i \
      HOME="$root/home" \
      XDG_RUNTIME_DIR="$root/run" \
      PATH="$root/bin:/usr/bin:/bin" \
      EP_STUB_BIN="$root/bin" \
      ${EP_EXTRA_ENV:-} \
      sh "$INSTALL_SH" --prefix "$root/prefix" --no-start "$@" 2>&1
  )
  RC=$?
}

# --- 1. baseline ------------------------------------------------------
say "1. the happy path still installs"
run base
if [ "$RC" = 0 ] && [ -x "$PREFIX/venv/bin/eugene-plexus-agent" ] && [ -f "$UNIT" ]; then
  ok "install.sh ran to the end, wrote a unit, and a stubbed uv is enough to drive it"
else
  bad "the baseline run failed (rc=$RC); every check below would be vacuous"
  printf '%s\n' "$OUT" | sed 's/^/      /'
fi

say "1b. a good install stays quiet"
if printf '%s' "$OUT" | grep -q 'Resolved\|Installed\|Downloading'; then
  bad "the package step now scrolls its output past the operator"
elif [ -s "$PREFIX/logs/install.log" ]; then
  ok "what the network steps said is in logs/install.log and not on the console"
else
  bad "no install.log was written, so a failure has nothing to print"
fi

# --- 2. #24a: the uv bootstrap ---------------------------------------
say "2. #24a -- a failing curl names the URL"
EP_STUB_CURL_FAILS=1 run curlfail
EP_STUB_CURL_FAILS=0
if printf '%s' "$OUT" | grep -q 'astral.sh/uv/install.sh'; then
  ok "the refusal names https://astral.sh/uv/install.sh"
else
  bad "the refusal does not name the URL it could not reach"
  printf '%s\n' "$OUT" | tail -5 | sed 's/^/      /'
fi
# **Indented, because that is the fix speaking rather than curl.**
# curl writes to stderr, which this run captures anyway, so a bare
# substring match passes against the broken script too -- an assertion
# that cannot fail. The installer prints the captured diagnosis under
# its own refusal, two spaces in; that is the thing being tested.
if printf '%s' "$OUT" | grep -q '^  curl: (60)'; then
  ok "curl's own diagnosis is relayed inside the refusal"
else
  bad "the refusal does not carry curl's diagnosis -- a TLS-intercepting proxy is unnamed"
  printf '%s
' "$OUT" | tail -6 | sed 's/^/      /'
fi
[ "$RC" != 0 ] && ok "and the run stops" || bad "the run continued after the uv fetch failed"

# --- 3. #24b: uv venv -------------------------------------------------
say "3. #24b -- a failing uv venv shows uv's stderr"
EP_STUB_UV_VENV_FAILS=1 run venvfail
EP_STUB_UV_VENV_FAILS=0
if printf '%s' "$OUT" | grep -qi 'TLS certificate verification failed'; then
  ok "uv's own message is printed"
else
  bad "uv's stderr was discarded; the operator sees only 'could not create a virtualenv'"
  printf '%s\n' "$OUT" | tail -4 | sed 's/^/      /'
fi

# --- 4. #24c: uv pip install -----------------------------------------
say "4. #24c -- a failing uv pip install shows pip's stderr"
EP_STUB_UV_PIP_FAILS=1 run pipfail
EP_STUB_UV_PIP_FAILS=0
if printf '%s' "$OUT" | grep -qi 'invalid peer certificate'; then
  ok "the resolver's own message is printed"
else
  bad "the package step's stderr was discarded"
  printf '%s\n' "$OUT" | tail -4 | sed 's/^/      /'
fi

# --- 5. #24d: the bind port ------------------------------------------
say "5. #24d -- EUGENE_PLEXUS_AGENT_BIND_PORT reaches the unit"
EP_EXTRA_ENV="EUGENE_PLEXUS_AGENT_BIND_PORT=8179" run port
EP_EXTRA_ENV=
if grep -q 'EUGENE_PLEXUS_AGENT_BIND_PORT=8179' "$UNIT" 2>/dev/null; then
  ok "the unit carries the port the installer was told to use"
else
  bad "the unit does not carry the port; the service comes back on 8079 at the next boot"
  grep -c Environment "$UNIT" 2>/dev/null | sed 's/^/      Environment lines: /'
fi
if printf '%s' "$OUT" | grep -q '8179'; then
  ok "and the closing lines point at the port the agent will answer on"
else
  bad "the closing lines name a port the agent will not be on"
fi

# --- 6. #30: --advertise with no --join ------------------------------
say "6. #30 -- --advertise is honoured on a standalone install"
run advertise --advertise http://10.4.4.4:8079
CFG=$PREFIX/agent.yaml
if grep -q 'advertiseUrl:[[:space:]]*http://10.4.4.4:8079' "$CFG" 2>/dev/null; then
  ok "agent.yaml carries the address the operator asked for"
else
  bad "--advertise was accepted and dropped on the floor outside the join branch"
  [ -f "$CFG" ] && sed 's/^/      /' "$CFG" || echo "      (no agent.yaml was written)"
fi
if grep -q 'EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0' "$UNIT" 2>/dev/null; then
  ok "and the unit binds wide, because a node that advertises an address binds one"
else
  bad "the unit still binds loopback, so nothing can reach the advertised address"
fi

say "7. an advertiseUrl already set is not overwritten"
printf 'advertiseUrl: http://10.9.9.9:8079\nfirstRunComplete: true\n' > "$WORK/advertise/prefix/agent.yaml"
rerun advertise --advertise http://10.4.4.4:8079
if grep -q '10.4.4.4' "$WORK/advertise/prefix/agent.yaml"; then
  ok "an explicit --advertise on a re-run does update it"
else
  bad "--advertise was ignored on a re-run"
fi
if grep -q 'firstRunComplete: true' "$WORK/advertise/prefix/agent.yaml"; then
  ok "and the rest of the file survives the edit"
else
  bad "the rest of agent.yaml was lost -- the installer clobbered an existing install's state"
fi

# --- 8. #31: uninstall ------------------------------------------------
say "8. #31 -- uninstall drops the keyring entries and names the copy directory"
run uninst
# The agent's engine store, where the installer will look for it.
mkdir -p "$FAKE_HOME/.eugene-plexus/engines/llama.cpp/b11026"
head -c 8192 /dev/urandom > "$FAKE_HOME/.eugene-plexus/engines/llama.cpp/b11026/llama-server"
COPYDIR=$WORK/uninst/copies
mkdir -p "$COPYDIR/sub"
head -c 4096 /dev/urandom > "$COPYDIR/sub/model.gguf"
cat > "$PREFIX/agent.yaml" <<YAML
firstRunComplete: true
modelCopyEnabled: true
modelCopyDir: $COPYDIR
auth:
  masterSalt: c2FsdHktc2FsdC0xNg==
  passphraseHash: \$argon2id\$v=19\$m=1,t=1,p=1\$c2FsdA\$aGFzaA
YAML
# The install's own python is what holds the keyring library, so the
# uninstall has to ask it. A stub that records being asked is the only
# way to see that from here -- a real keyring needs a desktop session.
cat > "$PREFIX/venv/bin/python" <<'PY'
#!/bin/sh
cat > "$PREFIX_KEYRING_LOG.script" 2>/dev/null
echo "python-called" >> "$PREFIX_KEYRING_LOG"
exit 0
PY
chmod +x "$PREFIX/venv/bin/python"
export PREFIX_KEYRING_LOG=$WORK/uninst/keyring.log
rm -f "$PREFIX_KEYRING_LOG" "$PREFIX_KEYRING_LOG.script"
OUT=$(
  env -i HOME="$FAKE_HOME" XDG_RUNTIME_DIR="$WORK/uninst/run" \
    PATH="$WORK/uninst/bin:/usr/bin:/bin" PREFIX_KEYRING_LOG="$PREFIX_KEYRING_LOG" \
    sh "$INSTALL_SH" --prefix "$PREFIX" --uninstall 2>&1
)
RC=$?
SCRIPT=$(cat "$PREFIX_KEYRING_LOG.script" 2>/dev/null || true)
if printf '%s' "$SCRIPT" | grep -q 'eugene-plexus-agent' \
   && printf '%s' "$SCRIPT" | grep -q 'eugene-plexus-control'; then
  ok "both keyring services are named in what the install's python was asked to run"
else
  bad "the uninstall does not drop the keyring entries (agent and control each keep one)"
fi
if printf '%s' "$OUT" | grep -q "$COPYDIR"; then
  ok "the node-local model copy directory is named"
else
  bad "the model-copy directory is left behind unmentioned"
  printf '%s\n' "$OUT" | sed 's/^/      /'
fi
if [ -f "$COPYDIR/sub/model.gguf" ]; then
  ok "and it is not deleted without being asked"
else
  bad "the uninstall deleted the copy directory with no switch asking it to"
fi
if ls -d "$PREFIX".removed-* >/dev/null 2>&1; then
  ok "the prefix is moved aside, not deleted"
else
  bad "the prefix was not preserved"
fi
# The engine store lives in $HOME, not under the prefix -- so an
# uninstall that only moves the prefix aside leaves gigabytes of
# llama.cpp builds that nobody will ever attribute to us.
if printf '%s' "$OUT" | grep -q "$FAKE_HOME/.eugene-plexus/engines"; then
  ok "the engine store outside the prefix is named"
else
  bad "the engine builds this install downloaded are left behind unmentioned"
fi

say "9. --purge-downloads removes what we made, including the engine store"
run purge
ENGINES2=$FAKE_HOME/.eugene-plexus/engines
mkdir -p "$ENGINES2/llama.cpp/b11026"
head -c 2048 /dev/urandom > "$ENGINES2/llama.cpp/b11026/llama-server"
COPYDIR2=$WORK/purge/copies
mkdir -p "$COPYDIR2/sub"
head -c 2048 /dev/urandom > "$COPYDIR2/sub/model.gguf"
printf 'modelCopyDir: %s\n' "$COPYDIR2" > "$PREFIX/agent.yaml"
OUT=$(
  env -i HOME="$WORK/purge/home" XDG_RUNTIME_DIR="$WORK/purge/run" \
    PATH="$WORK/purge/bin:/usr/bin:/bin" \
    sh "$INSTALL_SH" --prefix "$PREFIX" --uninstall --purge-downloads 2>&1
)
if [ ! -e "$COPYDIR2" ]; then
  ok "the copy directory is gone when the operator asks for it"
else
  bad "--purge-downloads left the directory in place"
fi
if [ ! -e "$ENGINES2" ]; then
  ok "and so is the engine store"
else
  bad "--purge-downloads left the engine store in place"
fi

printf '\n'
if [ "$FAILURES" = 0 ]; then
  printf 'R2.2 (POSIX half): all checks passed\n'
else
  printf 'R2.2 (POSIX half): %s FAILED\n' "$FAILURES"
fi
exit $([ "$FAILURES" = 0 ] && echo 0 || echo 1)
