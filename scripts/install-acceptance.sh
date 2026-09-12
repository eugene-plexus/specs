#!/usr/bin/env bash
#
# Install-paths §9 step 3 acceptance: `install.sh` and `install.ps1`.
#
# **The subject is a machine with nothing on it, so the run has to start
# from nothing.** Every acceptance script before this one built a
# throwaway install out of a developer checkout — a venv that already
# existed, packages already importable, a Python already on PATH. None
# of that is true of the machine this step is for, so this script takes
# the installer's own word for none of it: it removes the prefix, runs
# the one command a user would run, and then asks the *result*
# questions.
#
# THE CHECK THIS SCRIPT EXISTS FOR IS #6. `uv pip install` exiting 0 is
# not the claim. `eugene-plexus-ui` installs perfectly from a `main`
# archive and delivers no UI at all, because its payload is `next build`
# output that `main` gitignores — verified 2026-09-11, `static_dir()`
# was not even a directory. An installer that only checked pip's exit
# code would have reported success on a machine with no browser half,
# which is the gap install-paths §2.1 named and step 1 closed. So the
# UI is checked where it is actually served: over HTTP, from the agent
# the installer started.
#
# Checks, POSIX (run under WSL2 or any Linux/macOS host):
#    1. the prefix does not exist before the run
#    2. no python3.12 and no uv are needed on the machine
#    3. install.sh completes from nothing
#    4. it installed uv into the prefix and nowhere else
#    5. the venv exists and is not the system interpreter
#    6. the agent answers /healthz
#    7. the UI is SERVED, not merely installed
#    8. a deep link resolves (the trailing-slash convention)
#    9. the agent declared a control plane, not an empty topology
#   10. the agent and all three components are running under the prefix
#   11. the service unit exists and is enabled
#   12. a service stop runs every child's ASGI lifespan shutdown
#   13. ...including the agent's own, read unprefixed
#   14. no orphans survive the stop
#   15. re-running the installer is idempotent and restarts it
#   16. --uninstall stops it, removes the unit, and keeps the config
#
# Checks, Windows (run from Git Bash on the host itself):
#   17. install.ps1 parses as Windows PowerShell reads it FROM DISK
#   18. ...which is an encoding claim: pure ASCII, no BOM
#   19. nothing else is answering on the port (WSL2 forwards localhost)
#   20. install.ps1 completes from nothing, unelevated
#   21. the agent answers /healthz
#   22. the UI is served
#   23. the logon task exists and points at the venv's console script
#   24. the agent declared a control plane
#   25. winservice.py imports and carries the names install.ps1 uses
#   26. an unelevated service install fails non-zero with a sentence
#   27. -Uninstall removes the task and keeps the config
#
# NOT CHECKED, AND SAID RATHER THAN IMPLIED: registering and starting
# the real Windows service. It needs Administrator, which the session
# that wrote this did not have. `install.ps1 -Verify` prints the two
# commands that close it. macOS is likewise unverified — there is no
# Mac here — so the launchd half of install.sh is written and unrun,
# and llama.cpp acquisition on arm64 stays unverifiable (§8).
#
# Design: docs/design/install-paths-and-distribution.md §9 step 3, §6.1
set -uo pipefail

FAILURES=0
CHECKS=0
say() { printf '\n== %s\n' "$*"; }
ok()  { CHECKS=$((CHECKS + 1)); printf '  PASS  %s\n' "$*"; }
bad() { CHECKS=$((CHECKS + 1)); FAILURES=$((FAILURES + 1)); printf '  FAIL  %s\n' "$*"; }
skip() { printf '  SKIP  %s\n' "$*"; }

HERE="$(cd "$(dirname "$0")" && pwd)"
PORT="${EP_PORT:-8079}"

wait_gone() { for _ in $(seq 1 "${2:-30}"); do curl -sf -m 1 "$1/healthz" >/dev/null 2>&1 || return 0; sleep 1; done; return 1; }

# ---------------------------------------------------------------------
# POSIX: run under WSL2 (a real Linux host with its own systemd), or
# natively on Linux/macOS.
# ---------------------------------------------------------------------
run_posix() {
  local sh_runner=("$@")
  local prefix="${EP_PREFIX:-\$HOME/ep-accept}"

  # `$prefix` is expanded on the far side, because under WSL the far
  # side has a different HOME than the shell running this script.
  r() { "${sh_runner[@]}" "$1"; }

  # ...but some checks match the installer's own output against the
  # path, and for that the expanded value is needed on this side.
  local real
  real=$(r "echo $prefix")

  say "posix: a machine with nothing on it"
  if [ "$(r "test -e $prefix && echo yes || echo no")" = no ]; then
    ok "1. the prefix does not exist before the run"
  else
    r "rm -rf $prefix"
    ok "1. the prefix did exist and was removed"
  fi

  local sysuv sys312
  sysuv=$(r 'command -v uv || echo none')
  sys312=$(r 'command -v python3.12 || echo none')
  if [ "$sysuv" = none ] && [ "$sys312" = none ]; then
    ok "2. no uv and no python3.12 on the machine (uv brings both)"
  else
    skip "2. this machine already has uv=$sysuv python3.12=$sys312 — the 'from nothing' claim is weaker here"
  fi

  say "posix: the one command a user runs"
  local out
  out=$(r "sh '$POSIX_SCRIPT' --prefix $prefix 2>&1")
  if printf '%s' "$out" | grep -q "Eugene Plexus is running"; then
    ok "3. install.sh completed from nothing"
  else
    bad "3. install.sh did not finish: $(printf '%s' "$out" | tail -3)"
    printf '%s\n' "$out" | sed 's/^/      /'
    return
  fi

  [ "$(r "test -x $prefix/bin/uv && echo yes || echo no")" = yes ] \
    && ok "4. uv landed inside the prefix" || bad "4. uv is not in the prefix"

  local pyreal
  pyreal=$(r "$prefix/venv/bin/python -c 'import sys; print(sys.prefix)'")
  if [ -n "$pyreal" ] && [ "$pyreal" != "/usr" ]; then
    ok "5. the venv is the install's own interpreter ($pyreal)"
  else
    bad "5. the venv resolved to the system interpreter: $pyreal"
  fi

  say "posix: what the install actually serves"
  r "curl -fsS -m 5 http://127.0.0.1:$PORT/healthz" | grep -q '"component":"agent"' \
    && ok "6. the agent answers /healthz" || bad "6. no /healthz"

  # #7 is the point of the whole script. Not "is the package
  # installed" — is the UI coming back over the wire.
  local root
  root=$(r "curl -fsS -m 5 http://127.0.0.1:$PORT/ | head -c 400")
  if printf '%s' "$root" | grep -q '<!DOCTYPE html>' \
     && ! printf '%s' "$root" | grep -qi 'no web UI installed'; then
    ok "7. the UI is served at / (not the 'no UI installed' page)"
  else
    bad "7. / did not return the UI: $(printf '%s' "$root" | head -c 120)"
  fi

  local deep
  deep=$(r "curl -s -o /dev/null -m 5 -w '%{http_code}' -L http://127.0.0.1:$PORT/nodes")
  [ "$deep" = 200 ] && ok "8. the /nodes deep link resolves (HTTP $deep)" \
                    || bad "8. /nodes returned $deep"

  # Two bugs in one line, both mine, both found by running it. The key
  # is "- kind:" -- a list item -- so "  kind:" matched nothing and the
  # check reported an empty topology that was in fact fully declared.
  # And `grep -c` prints 0 AND exits 1 when nothing matches, so the
  # `|| echo 0` fired as well and the comparison was against "0\n0".
  local decl
  decl=$(r "grep -c '^- kind: ' $prefix/agent.yaml 2>/dev/null || true")
  [ "${decl:-0}" = 3 ] && ok "9. the agent declared control, gateway and library" \
                       || bad "9. agent.yaml declares ${decl:-0} components, expected 3"

  # **Counted by argv[0], and it took four tries to get the subject
  # right.** A bare `pgrep -f eugene_plexus_` counted a leftover from an
  # unrelated install in the same guest. Scoping it to `$prefix` matched
  # nothing, because that variable holds the literal string "$HOME/..."
  # and single quotes on the far side never expand it -- check 10 failed
  # honestly and **check 14 passed**, since "nothing matches a pattern
  # that matches nothing" is exactly what it asked. Expanding it then
  # counted five, because `pgrep -f` matches the checking shell, whose
  # own command line contains the pattern it is searching for.
  #
  # `/proc/PID/exe` fixed that and introduced a quieter coupling: it
  # resolves symlinks, so it only lands inside the prefix because
  # install.sh sets UV_PYTHON_INSTALL_DIR there. Under `bootstrap.sh`,
  # where uv's interpreter is shared and outside the tree, the same
  # check reads 0 -- and check 14 would pass again. **argv[0] is the
  # instrument that needs neither coincidence**: it is the path the
  # process was started with, and the checking bash's own argv[0] is
  # /bin/bash, not the pattern.
  procs() { r "for d in /proc/[0-9]*; do tr '\\0' '\\n' < \$d/cmdline 2>/dev/null | head -1; done | grep -c '^$real/' || true"; }
  local kids
  kids=$(procs)
  [ "${kids:-0}" = 4 ] && ok "10. the agent and all three components are running" \
                       || bad "10. ${kids:-0} processes on the install's interpreter, expected 4 (agent + 3)"

  say "posix: the service unit"
  local enabled
  enabled=$(r 'systemctl --user is-enabled eugene-plexus-agent 2>&1')
  [ "$enabled" = enabled ] && ok "11. the unit exists and is enabled" \
                           || bad "11. unit is '$enabled'"

  # 12 and 13 are one measurement read two ways, and the distinction is
  # the one step 2 was bitten by: the agent pipes every child's stdout
  # into its own log with a [name] prefix, so a whole-file grep for
  # "Application shutdown complete" answers about the children when it
  # was asked about the parent.
  local mark
  mark=$(r "wc -l < $prefix/logs/agent.log")
  r 'systemctl --user stop eugene-plexus-agent' >/dev/null 2>&1
  wait_gone "http://127.0.0.1:$PORT" 20 >/dev/null 2>&1
  local tailcmd="tail -n +$((mark + 1)) $prefix/logs/agent.log"
  local children=0 c
  for k in control gateway library; do
    c=$(r "$tailcmd | grep -c '^\[$k\] INFO:     Application shutdown complete'")
    [ "${c:-0}" -ge 1 ] && children=$((children + 1))
  done
  [ "$children" = 3 ] && ok "12. all three children ran their ASGI lifespan shutdown" \
                      || bad "12. only $children/3 children shut down gracefully"

  local own
  own=$(r "$tailcmd | grep -c '^INFO:     Application shutdown complete'")
  [ "${own:-0}" -ge 1 ] && ok "13. the agent ran its own, read unprefixed" \
                        || bad "13. the agent's own shutdown line is absent"

  local left
  left=$(procs)
  [ "${left:-0}" = 0 ] && ok "14. no orphans survived the stop" \
                       || bad "14. ${left:-0} processes on the install's interpreter survived"

  say "posix: re-run and uninstall"
  out=$(r "sh '$POSIX_SCRIPT' --prefix $prefix 2>&1")
  if printf '%s' "$out" | grep -q "virtualenv already present" \
     && printf '%s' "$out" | grep -q "Eugene Plexus is running"; then
    ok "15. a re-run is idempotent and brings it back"
  else
    bad "15. the re-run did not behave: $(printf '%s' "$out" | tail -2)"
  fi

  out=$(r "sh '$POSIX_SCRIPT' --prefix $prefix --uninstall 2>&1")
  local kept unit_gone
  kept=$(printf '%s' "$out" | grep -o "$real.removed-[0-9]*" | head -1)
  unit_gone=$(r 'test -f $HOME/.config/systemd/user/eugene-plexus-agent.service && echo no || echo yes')
  if [ -n "$kept" ] && [ "$unit_gone" = yes ] \
     && [ "$(r "test -f $kept/agent.yaml && echo yes || echo no")" = yes ]; then
    ok "16. uninstall removed the unit and kept the config at $kept"
    r "rm -rf $kept"
  else
    bad "16. uninstall left unit_gone=$unit_gone kept='$kept'"
  fi
}

# ---------------------------------------------------------------------
# Windows: run from Git Bash on the host itself.
# ---------------------------------------------------------------------
run_windows() {
  local ps1="$HERE/install.ps1"
  local prefix="${EP_WIN_PREFIX:-$LOCALAPPDATA\\EugenePlexusAccept}"
  local prefix_unix
  prefix_unix=$(cygpath -u "$prefix" 2>/dev/null || echo "$prefix")

  say "windows: the installer as PowerShell reads it from disk"
  # This is an ENCODING check wearing a syntax check's clothes. A
  # BOM-less UTF-8 .ps1 is decoded as CP-1252 by Windows PowerShell
  # 5.1, and U+2014's third UTF-8 byte (0x94) is U+201D in CP-1252 --
  # a curly quote PowerShell honours as a string delimiter. So one em
  # dash in a comment makes the file unparseable from disk while
  # `irm | iex` (which decodes by the HTTP charset) works fine. Found
  # by running it, 2026-09-11.
  #
  # NOTE THE INVOCATION. The first version passed the path as a trailing
  # argument to -Command, which PowerShell appends to the command TEXT --
  # so it executed install.ps1 for real, installed the product, and then
  # tripped check 19 on the agent it had just started. -Command takes a
  # script, not a script plus argv.
  local winps1 parse
  winps1=$(cygpath -w "$ps1")
  parse=$(EP_PS1="$winps1" powershell.exe -NoProfile -NonInteractive -Command \
    '$e=$null; $null=[System.Management.Automation.Language.Parser]::ParseFile($env:EP_PS1,[ref]$null,[ref]$e); if($e){$e[0].Message}else{"OK"}' \
    2>&1 | tr -d '\r')
  [ "$parse" = OK ] && ok "17. install.ps1 parses from disk" || bad "17. parse: $parse"

  if python - "$ps1" <<'PY'
import sys
b = open(sys.argv[1], 'rb').read()
sys.exit(0 if (b[:3] != b'\xef\xbb\xbf' and all(c < 128 for c in b)) else 1)
PY
  then ok "18. install.ps1 is pure ASCII with no BOM"
  else bad "18. install.ps1 has non-ASCII bytes or a BOM"
  fi

  say "windows: nobody else is answering on the port"
  # **WSL2 forwards localhost.** An agent left running inside the guest
  # by the POSIX half of this very script is reachable from Windows at
  # 127.0.0.1:8079, answers /healthz with byte-identical JSON, and would
  # make every check below pass against the wrong machine. Add the M10
  # observation -- a stub still holding a loopback port two days later --
  # and "something answered" is never evidence about *what*. So: nothing
  # may be listening before we start.
  if curl -sf -m 2 "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    bad "19. something is already answering on $PORT (a leftover WSL agent, or a stale process) -- the checks below would be about it"
    return
  fi
  ok "19. nothing was listening on $PORT before the install"

  say "windows: install from nothing, unelevated"
  powershell.exe -NoProfile -NonInteractive -Command \
    "if (Test-Path '$prefix') { Remove-Item -Recurse -Force '$prefix' }" >/dev/null 2>&1
  local out
  out=$(powershell.exe -NoProfile -NonInteractive -File "$(cygpath -w "$ps1")" \
        -Prefix "$prefix" 2>&1 | tr -d '\r')
  if printf '%s' "$out" | grep -q "Eugene Plexus is running"; then
    ok "20. install.ps1 completed from nothing"
  else
    bad "20. install.ps1 did not finish"
    printf '%s\n' "$out" | tail -12 | sed 's/^/      /'
    return
  fi

  curl -fsS -m 5 "http://127.0.0.1:$PORT/healthz" | grep -q '"component":"agent"' \
    && ok "21. the agent answers /healthz" || bad "21. no /healthz"

  local root
  root=$(curl -fsS -m 5 "http://127.0.0.1:$PORT/" | head -c 400)
  if printf '%s' "$root" | grep -q '<!DOCTYPE html>' \
     && ! printf '%s' "$root" | grep -qi 'no web UI installed'; then
    ok "22. the UI is served at /"
  else
    bad "22. / did not return the UI"
  fi

  local action
  action=$(powershell.exe -NoProfile -NonInteractive -Command \
    '(Get-ScheduledTask -TaskName EugenePlexusAgent -ErrorAction SilentlyContinue).Actions.Execute' 2>&1 | tr -d '\r')
  if printf '%s' "$action" | grep -qi 'eugene-plexus-agent.exe'; then
    ok "23. the logon task runs the venv's console script"
  else
    bad "23. task action is '$action'"
  fi

  local decl
  decl=$(grep -c '^- kind: ' "$prefix_unix/agent.yaml" 2>/dev/null || true)
  [ "${decl:-0}" = 3 ] && ok "24. the agent declared control, gateway and library" \
                       || bad "24. agent.yaml declares ${decl:-0} components, expected 3"

  say "windows: the service module, as far as no-Administrator reaches"
  local names
  names=$("$prefix_unix/venv/Scripts/python.exe" -c \
    "import eugene_plexus_agent.winservice as w; print(w.SERVICE_NAME); print(type(w.build_service_class()).__name__)" 2>&1 | tr -d '\r')
  if printf '%s' "$names" | grep -q '^EugenePlexusAgent'; then
    ok "25. winservice imports and names the service install.ps1 registers"
  else
    bad "25. winservice: $names"
  fi

  local denied
  denied=$("$prefix_unix/venv/Scripts/python.exe" -m eugene_plexus_agent.winservice install 2>&1 | tr -d '\r')
  if printf '%s' "$denied" | grep -qi 'needs Administrator'; then
    ok "26. an unelevated service install explains itself"
  else
    bad "26. unelevated install said: $(printf '%s' "$denied" | tail -2)"
  fi
  skip "   registering and starting the service -- needs Administrator (install.ps1 -Verify)"

  say "windows: uninstall"
  out=$(powershell.exe -NoProfile -NonInteractive -File "$(cygpath -w "$ps1")" \
        -Prefix "$prefix" -Uninstall 2>&1 | tr -d '\r')
  local task_gone kept
  task_gone=$(powershell.exe -NoProfile -NonInteractive -Command \
    'if (Get-ScheduledTask -TaskName EugenePlexusAgent -ErrorAction SilentlyContinue) { "no" } else { "yes" }' 2>&1 | tr -d '\r')
  kept=$(printf '%s' "$out" | grep -o "removed-[0-9]*" | head -1)
  if [ "$task_gone" = yes ] && [ -n "$kept" ]; then
    ok "27. uninstall removed the task and kept the config ($kept)"
    powershell.exe -NoProfile -NonInteractive -Command \
      "Remove-Item -Recurse -Force '$prefix.$kept'" >/dev/null 2>&1
  else
    bad "27. uninstall left task_gone=$task_gone kept='$kept'"
  fi
}

# ---------------------------------------------------------------------
# Staged under /var/tmp, not /tmp, and that is not fussiness. In WSL
# `/tmp` is tmpfs AND the distro is terminated when it goes idle, so the
# copied script evaporates partway through a run -- check 15 failed with
# "cannot open" while check 3 had used the same file minutes earlier.
# It had worked all day only because a leftover agent process happened
# to keep the distro alive; removing that stray process broke the
# instrument, not the thing under test.
POSIX_SCRIPT="${EP_POSIX_SCRIPT:-/var/tmp/ep-install.sh}"

case "${EP_MODE:-auto}" in
  posix|auto)
    if [ "$(uname -s)" = Linux ] || [ "$(uname -s)" = Darwin ]; then
      cp "$HERE/install.sh" "$POSIX_SCRIPT"
      run_posix sh -c
    elif command -v wsl.exe >/dev/null 2>&1; then
      say "no native POSIX host; using WSL2, which is a real Linux machine with its own systemd"
      # Copy the script into the guest rather than run it off /mnt/d:
      # a DrvFs path would test the installer against a filesystem no
      # target machine has, and the mount's noexec/permission model is
      # not Linux's.
      # Piped in rather than copied by path: Git Bash rewrites any
      # argument that looks like a POSIX path into a Windows one, and
      # turned /mnt/d/... into 'C:/Program Files/Git/mnt/d/...' on the
      # first run of this script. stdin has no such opinion.
      wsl.exe -e bash -c "cat > '$POSIX_SCRIPT'" < "$HERE/install.sh"
      run_posix wsl.exe -e bash -c
    else
      skip "posix checks: no Linux, no macOS, no WSL"
    fi
    ;;
esac

case "${EP_MODE:-auto}" in
  windows|auto)
    if command -v powershell.exe >/dev/null 2>&1; then
      run_windows
    else
      skip "windows checks: not on Windows"
    fi
    ;;
esac

say "result"
printf '  %d checks, %d failures\n' "$CHECKS" "$FAILURES"
[ "$FAILURES" -eq 0 ] || exit 1
