#!/usr/bin/env bash
# R2.2 -- the installer's own advice, and what it leaves behind.
#
# Roadmap: docs/design/release-roadmap.md §3.2. Findings: review §6.1
# #10, §6.2 #24, §6.2 #30, §6.3 #31, §6.3 #34.
#
# One run, two halves, because the two installers are two programs:
#
#   * `r22-install-ps1-checks.ps1` drives `install.ps1` on Windows --
#     a copy whose task and service names are rewritten, so the decoy it
#     stops is a decoy and not the live worker's agent. It also holds
#     the LIVE half of #34: a real scheduled task under a real accented
#     directory, read by the agent's own detector.
#   * `r22-install-sh-checks.sh` drives `install.sh` on Linux, through
#     WSL when this is a Windows box, with `uv`, `curl`, `systemctl` and
#     `loginctl` stubbed so the paths that only exist when the network
#     fails are reachable at all.
#
#   * and the agent's own unit gate for #34, which is where the OEM
#     code page is reproduced as arithmetic rather than as a fixture.
#
# **Safe beside the live install.** Nothing here binds a port, so there
# is nothing to tear down by pid; what it does touch instead is
# account-wide Windows environment variables, which the Windows half
# snapshots and restores. Every ambient EUGENE_PLEXUS_* variable is
# dropped before the POSIX half so a stubbed install cannot read the
# live worker's config file. Never `pkill -f eugene_plexus_`: this box
# is a worker node.
#
# What this run does NOT cover, and says so rather than implying it:
#   * the elevated service branch of `install.ps1` -- registering a
#     service needs Administrator, which no session here has. The
#     SYSTEM-profile fix is asserted by reading the script plus a live
#     exercise of the mechanism it relies on (the library really does
#     take its default roots from the variable).
#   * a real network failure. The POSIX half stubs the failure; only a
#     machine behind a TLS-intercepting proxy can produce the real one.
#   * macOS. `install.sh`'s launchd branch is written and unrun.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
FAILURES=0
say() { printf '\n######## %s\n' "$*"; }

# Drop every ambient EUGENE_PLEXUS_* variable -- a loop, not a list.
while IFS='=' read -r name _; do
  case "$name" in EUGENE_PLEXUS_*) unset "$name" ;; esac
done < <(env)

# --- the agent's unit gate for #34 ------------------------------------
say "the agent's own gate: reach.py decodes schtasks in the OEM code page"
AGENT_PY=${EP_AGENT_PY:-/d/py/eugene-plexus/agent/.venv/Scripts/python.exe}
if [ -x "$AGENT_PY" ]; then
  if "$AGENT_PY" -m pytest "$(dirname "$AGENT_PY")/../../tests/test_reach.py" -q 2>/dev/null \
     || (cd "$(dirname "$AGENT_PY")/../.." && "$AGENT_PY" -m pytest tests/test_reach.py -q); then
    printf '  PASS  tests/test_reach.py\n'
  else
    printf '  FAIL  tests/test_reach.py\n'; FAILURES=$((FAILURES + 1))
  fi
else
  printf '  SKIP  no agent virtualenv at %s\n' "$AGENT_PY"
fi

# --- install.sh -------------------------------------------------------
say "install.sh (POSIX)"
if [ "$(uname -s)" = Linux ]; then
  bash "$HERE/r22-install-sh-checks.sh" || FAILURES=$((FAILURES + 1))
elif command -v wsl.exe >/dev/null 2>&1; then
  guest=$(printf '%s' "$HERE" | sed 's|^/\([a-z]\)/|/mnt/\1/|')
  # To a file, not through `tr`: a pipeline's exit status is the LAST
  # command's, so piping the guest's output through `tr` would report
  # `tr`'s success as the checks' success.
  out=${TMPDIR:-/tmp}/r22-posix.out
  MSYS_NO_PATHCONV=1 wsl.exe -- bash "$guest/r22-install-sh-checks.sh" > "$out" 2>&1
  rc=$?
  tr -d '\r' < "$out"
  [ "$rc" = 0 ] || FAILURES=$((FAILURES + 1))
else
  printf '  SKIP  no Linux and no WSL; install.sh is unexercised here\n'
fi

# --- install.ps1 ------------------------------------------------------
say "install.ps1 (Windows)"
if command -v powershell.exe >/dev/null 2>&1; then
  win_here=$(cygpath -w "$HERE" 2>/dev/null || printf '%s' "$HERE")
  powershell.exe -NoProfile -ExecutionPolicy Bypass \
    -File "$win_here\\r22-install-ps1-checks.ps1" || FAILURES=$((FAILURES + 1))
else
  printf '  SKIP  not a Windows box; install.ps1 is unexercised here\n'
fi

printf '\n'
if [ "$FAILURES" = 0 ]; then
  printf 'R2.2: every half passed\n'
  exit 0
fi
printf 'R2.2: %s half/halves FAILED\n' "$FAILURES"
exit 1
