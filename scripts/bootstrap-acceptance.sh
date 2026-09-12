#!/usr/bin/env bash
#
# Install-paths §9 step 4 acceptance: `bootstrap.sh` and `bootstrap.ps1`.
#
# **The developer script has never been tested, and that is the point of
# this file.** `bootstrap.ps1` existed from M0 and was only ever run
# against the one polyrepo root it defaults to — the developer's own,
# already set up, so every idempotent skip fired and nothing was
# exercised. Both scripts take `--root` / `-Root` now for exactly this
# reason: a script that can only run against the machine that already
# works cannot be checked.
#
# THE CLAIM IS NOT "IT PRINTED DONE". A bootstrap can clone every repo,
# build every virtualenv, report success and still leave a developer
# with an agent that supervises nothing — which is the failure
# `bootstrap.ps1`'s one assertion existed to catch, and it only ever
# checked imports. Since install-paths step 1 the UI is a Python package
# too, so a green bootstrap can also mean "an agent with no browser
# half". Both are checked here, and then the real one: the environment
# is used to start a control plane.
#
# Checks, POSIX (WSL2 or any Linux/macOS host):
#    1. the root does not exist before the run
#    2. no python3.12 on the machine (uv brings one)
#    3. it needs no `gh` -- asserted against the script, not hoped for
#    4. bootstrap.sh completes from nothing
#    5. all eight repos are cloned
#    6. every Python repo has a 3.12 virtualenv with its package importable
#    7. pre-commit hooks are installed where there is a config, and only there
#    8. the AGENT's virtualenv imports all five components
#    9. the UI resolves INTO the checkout, editable, with build output
#   10. the bootstrapped agent serves a control plane: UI at /, three children
#   11. a re-run is idempotent
#
# Checks, Windows (from Git Bash on the host):
#   12. bootstrap.ps1 parses as PowerShell reads it FROM DISK, pure ASCII
#   13. it needs no `gh`
#   14. bootstrap.ps1 completes from nothing
#   15. all eight repos are cloned
#   16. the agent's virtualenv imports all five components
#   17. the UI resolves into the checkout with build output
#   18. pre-commit hooks are installed where there is a config
#   19. a re-run is idempotent
#
# NOT CHECKED: macOS, which has no hardware here.
#
# Design: docs/design/install-paths-and-distribution.md §9 step 4
set -uo pipefail

FAILURES=0
CHECKS=0
say()  { printf '\n== %s\n' "$*"; }
ok()   { CHECKS=$((CHECKS + 1)); printf '  PASS  %s\n' "$*"; }
bad()  { CHECKS=$((CHECKS + 1)); FAILURES=$((FAILURES + 1)); printf '  FAIL  %s\n' "$*"; }
skip() { printf '  SKIP  %s\n' "$*"; }

HERE="$(cd "$(dirname "$0")" && pwd)"
PORT="${EP_PORT:-8079}"
REPOS="specs agent control gateway inference-driver library ui website"
PY_REPOS="agent control gateway inference-driver library"
HOOKED="agent control gateway inference-driver library ui"

# The one repo in the clone list with no .pre-commit-config.yaml. Named
# rather than inferred, so "no hooks anywhere" cannot read as a pass.
UNHOOKED="website"

# ---------------------------------------------------------------------
run_posix() {
  local runner=("$@")
  FAR_ENV=""
  r() { "${runner[@]}" "$FAR_ENV$1"; }

  local root="${EP_BOOT_ROOT:-\$HOME/ep-bootaccept}"
  local real
  real=$(r "echo $root")

  say "posix: a machine with nothing on it"
  r "rm -rf $root" >/dev/null 2>&1
  [ "$(r "test -e $root && echo yes || echo no")" = no ] \
    && ok "1. the root does not exist before the run" \
    || bad "1. $real still exists"

  local sys312
  sys312=$(r 'command -v python3.12 || echo none')
  [ "$sys312" = none ] && ok "2. no python3.12 on the machine -- uv has to supply one" \
                       || skip "2. this machine has python3.12 at $sys312"

  # A static check, deliberately. §4 has said since the design was
  # written that Path A clones over HTTPS so it needs no authenticated
  # GitHub CLI -- and the Windows script used `gh repo clone` anyway,
  # for four milestones, because nothing asserted it.
  # **Comments stripped first.** Grepping the whole file failed on the
  # sentence in bootstrap.ps1's own docstring explaining what it USED to
  # do -- a check that cannot tell code from prose, whose natural "fix"
  # is deleting the explanation.
  if sed 's/[[:space:]]*#.*$//' "$HERE/bootstrap.sh" | grep -qE '(^|[^[:alnum:]_-])gh (repo|auth)'; then
    bad "3. bootstrap.sh still reaches for the GitHub CLI"
  else
    grep -q 'git clone' "$HERE/bootstrap.sh" \
      && ok "3. bootstrap.sh clones over plain git, no gh" \
      || bad "3. bootstrap.sh does not clone at all?"
  fi

  # **Provision Node into the throwaway root if the host has none that
  # works.** Without it the `ui` and `website` halves are skipped and
  # checks 9 and 10 measure nothing -- and WSL makes that easy to miss,
  # because `npm` resolves there to the WINDOWS npm over interop and
  # answers `--version` happily while `node` is absent. Fetching one
  # here keeps the run self-contained and deletes with the root, rather
  # than leaving a toolchain on somebody's machine.
  say "posix: a Node toolchain for the browser half"
  local nodecheck
  nodecheck=$(r 'if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then case "$(command -v node)" in */mnt/*) echo interop;; *) echo ok;; esac; else echo none; fi')
  if [ "$nodecheck" = ok ]; then
    skip "   using the host's own node ($(r 'node --version'))"
  else
    printf '  ...no usable node here (%s); fetching one into the throwaway root\n' "$nodecheck"
    local nodever
    nodever=$(curl -fsSL https://nodejs.org/dist/index.json \
      | python -c 'import json,sys; print(next(r["version"] for r in json.load(sys.stdin) if r["version"].startswith("v24.")))')
    r "mkdir -p $root/.node && curl -fsSL https://nodejs.org/dist/$nodever/node-$nodever-linux-x64.tar.xz | tar -xJ -C $root/.node --strip-components=1" >/dev/null 2>&1
    if [ "$(r "test -x $root/.node/bin/node && echo y || echo n")" = y ]; then
      FAR_ENV="export PATH=$real/.node/bin:\$PATH; "
      printf '  ...node %s provisioned\n' "$(r 'node --version')"
    else
      bad "   could not provision Node -- checks 9 and 10 would report the browser half as missing"
    fi
  fi

  say "posix: from nothing"
  r "mkdir -p $root" >/dev/null 2>&1
  r "git clone -q https://github.com/eugene-plexus/specs $root/specs" >/dev/null 2>&1
  local out
  out=$(r "sh '$POSIX_SCRIPT' --root $root 2>&1")
  if printf '%s' "$out" | grep -q "every repo is set up under"; then
    ok "4. bootstrap.sh completed from nothing"
  else
    bad "4. bootstrap.sh did not finish"
    printf '%s\n' "$out" | tail -12 | sed 's/^/      /'
    return
  fi

  local missing=""
  for repo in $REPOS; do
    [ "$(r "test -d $root/$repo/.git && echo y || echo n")" = y ] || missing="$missing $repo"
  done
  [ -z "$missing" ] && ok "5. all eight repos cloned" \
                    || bad "5. not cloned:$missing"

  local badpy=""
  for repo in $PY_REPOS; do
    local mod ver
    mod="eugene_plexus_$(printf '%s' "$repo" | tr - _)"
    ver=$(r "$root/$repo/.venv/bin/python -c 'import sys,importlib.util as u; print(\"%d.%d\" % sys.version_info[:2], u.find_spec(\"$mod\") is not None)' 2>&1")
    case "$ver" in
      "3.12 True") : ;;
      *) badpy="$badpy $repo($ver)" ;;
    esac
  done
  [ -z "$badpy" ] && ok "6. every Python repo has a 3.12 venv with its own package importable" \
                  || bad "6. wrong:$badpy"

  local nohook="" wronghook=""
  for repo in $HOOKED; do
    [ "$(r "test -f $root/$repo/.git/hooks/pre-commit && echo y || echo n")" = y ] || nohook="$nohook $repo"
  done
  for repo in $UNHOOKED; do
    [ "$(r "test -f $root/$repo/.git/hooks/pre-commit && echo y || echo n")" = n ] || wronghook="$wronghook $repo"
  done
  if [ -z "$nohook" ] && [ -z "$wronghook" ]; then
    ok "7. hooks installed in the six repos with a config, and in no others"
  else
    bad "7. missing:$nohook unexpected:$wronghook"
  fi

  say "posix: the agent's virtualenv is the runtime"
  local agentpy="$root/agent/.venv/bin/python"
  local imports
  imports=$(r "$agentpy -c 'import importlib.util as u; print(all(u.find_spec(m) for m in [\"eugene_plexus_agent\",\"eugene_plexus_control\",\"eugene_plexus_gateway\",\"eugene_plexus_inference_driver\",\"eugene_plexus_library\"]))' 2>&1")
  [ "$imports" = True ] && ok "8. the agent's venv imports all five components" \
                        || bad "8. the agent's venv: $imports"

  # Editable AND populated. Either alone is a half-answer: a wheel
  # install would work today and stop reflecting `npm run build:python`,
  # and an editable install with no export is the "no web UI installed"
  # page wearing a successful bootstrap.
  local ui
  ui=$(r "$agentpy -c 'import eugene_plexus_ui as m; from pathlib import Path; d=Path(m.static_dir()); print(str(d).startswith(\"$real/ui/\"), (d/\"index.html\").is_file())' 2>&1")
  [ "$ui" = "True True" ] && ok "9. the UI resolves into the checkout and carries its build output" \
                          || bad "9. ui static_dir: $ui"

  say "posix: it actually runs"
  # The install directory goes INSIDE the throwaway root, so the final
  # `rm -rf $root` takes it with everything else. A sibling directory
  # was left behind by the first run of this script.
  r "rm -rf $root/run && mkdir -p $root/run" >/dev/null 2>&1
  r "cd $root/run && nohup $agentpy -m eugene_plexus_agent --unattended > run.log 2>&1 & sleep 1" >/dev/null 2>&1
  local up=no i=0
  while [ "$i" -lt 45 ]; do
    r "curl -sf -m 2 http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && { up=yes; break; }
    i=$((i + 1)); sleep 1
  done
  if [ "$up" = yes ]; then
    local page kids
    page=$(r "curl -fsS -m 5 http://127.0.0.1:$PORT/ | head -c 200")
    # **The agent answers /healthz before its children exist.** The
    # first version of this check read the process list the moment
    # /healthz came up and found zero, which is true and not what was
    # being asked: supervision starts after the socket. Poll for the
    # subject instead of for a proxy that happens to be ready sooner.
    kids=0; i=0
    while [ "$i" -lt 30 ]; do
      kids=$(r "pgrep -c -f 'eugene_plexus_(control|gateway|library)' 2>/dev/null || true")
      [ "${kids:-0}" = 3 ] && break
      i=$((i + 1)); sleep 1
    done
    if printf '%s' "$page" | grep -q '<!DOCTYPE html>' \
       && ! printf '%s' "$page" | grep -qi 'no web UI installed' \
       && [ "${kids:-0}" = 3 ]; then
      ok "10. the bootstrapped agent serves the UI and supervises three components"
    else
      bad "10. children=$kids page=$(printf '%s' "$page" | head -c 60)"
    fi
  else
    bad "10. the bootstrapped agent never answered on $PORT"
  fi
  r "pkill -f eugene_plexus_ || true" >/dev/null 2>&1

  say "posix: idempotence"
  out=$(r "sh '$POSIX_SCRIPT' --root $root 2>&1")
  if printf '%s' "$out" | grep -q "already present" \
     && printf '%s' "$out" | grep -q "every repo is set up under"; then
    ok "11. a re-run skips what is there and still finishes"
  else
    bad "11. the re-run did not behave: $(printf '%s' "$out" | tail -2)"
  fi
  r "rm -rf $root" >/dev/null 2>&1
}

# ---------------------------------------------------------------------
run_windows() {
  local ps1="$HERE/bootstrap.ps1"
  local root="${EP_WIN_BOOT_ROOT:-D:\\tmp\\ep-bootaccept}"
  local root_unix
  root_unix=$(cygpath -u "$root" 2>/dev/null || echo "$root")

  say "windows: the script as PowerShell reads it from disk"
  local winps1 parse
  winps1=$(cygpath -w "$ps1")
  parse=$(EP_PS1="$winps1" powershell.exe -NoProfile -NonInteractive -Command \
    '$e=$null; $null=[System.Management.Automation.Language.Parser]::ParseFile($env:EP_PS1,[ref]$null,[ref]$e); if($e){$e[0].Message}else{"OK"}' \
    2>&1 | tr -d '\r')
  local ascii=no
  python - "$ps1" <<'PY' && ascii=yes
import sys
b = open(sys.argv[1], 'rb').read()
sys.exit(0 if (b[:3] != b'\xef\xbb\xbf' and all(c < 128 for c in b)) else 1)
PY
  [ "$parse" = OK ] && [ "$ascii" = yes ] \
    && ok "12. bootstrap.ps1 parses from disk and is pure ASCII" \
    || bad "12. parse=$parse ascii=$ascii"

  # Tokenised rather than grepped, for the reason check 3 records: the
  # docstring legitimately contains the words `gh repo clone` while
  # explaining that the script no longer does it. A check that cannot
  # tell code from prose invites deleting the prose.
  local ghuse
  ghuse=$(EP_PS1="$winps1" powershell.exe -NoProfile -NonInteractive -Command \
    '$t=[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw $env:EP_PS1),[ref]$null); if ($t | Where-Object { $_.Type -eq "Command" -and $_.Content -eq "gh" }) { "yes" } else { "no" }' \
    2>&1 | tr -d '\r')
  [ "$ghuse" = no ] && ok "13. bootstrap.ps1 invokes no gh command (tokenised, not grepped)" \
                    || bad "13. bootstrap.ps1 invokes gh: $ghuse"

  say "windows: from nothing"
  powershell.exe -NoProfile -NonInteractive -Command \
    "if (Test-Path '$root') { Remove-Item -Recurse -Force '$root' }" >/dev/null 2>&1
  local out
  out=$(powershell.exe -NoProfile -NonInteractive -File "$winps1" -Root "$root" 2>&1 | tr -d '\r')
  if printf '%s' "$out" | grep -q "every repo is set up under"; then
    ok "14. bootstrap.ps1 completed from nothing"
  else
    bad "14. bootstrap.ps1 did not finish"
    printf '%s\n' "$out" | tail -12 | sed 's/^/      /'
    return
  fi

  local missing=""
  for repo in $REPOS; do
    [ -d "$root_unix/$repo/.git" ] || missing="$missing $repo"
  done
  [ -z "$missing" ] && ok "15. all eight repos cloned" || bad "15. not cloned:$missing"

  local agentpy="$root_unix/agent/.venv/Scripts/python.exe"
  local imports
  imports=$("$agentpy" -c 'import importlib.util as u; print(all(u.find_spec(m) for m in ["eugene_plexus_agent","eugene_plexus_control","eugene_plexus_gateway","eugene_plexus_inference_driver","eugene_plexus_library"]))' 2>&1 | tr -d '\r')
  [ "$imports" = True ] && ok "16. the agent's venv imports all five components" \
                        || bad "16. the agent's venv: $imports"

  local ui
  ui=$("$agentpy" -c 'import eugene_plexus_ui as m; from pathlib import Path; d=Path(m.static_dir()); print("ui" in d.parts and "python" in d.parts, (d/"index.html").is_file())' 2>&1 | tr -d '\r')
  [ "$ui" = "True True" ] && ok "17. the UI resolves into the checkout and carries its build output" \
                          || bad "17. ui static_dir: $ui"

  local nohook=""
  for repo in $HOOKED; do
    [ -f "$root_unix/$repo/.git/hooks/pre-commit" ] || nohook="$nohook $repo"
  done
  [ -z "$nohook" ] && ok "18. hooks installed in the six repos with a config" \
                   || bad "18. missing:$nohook"

  say "windows: idempotence"
  out=$(powershell.exe -NoProfile -NonInteractive -File "$winps1" -Root "$root" 2>&1 | tr -d '\r')
  if printf '%s' "$out" | grep -q "already present" \
     && printf '%s' "$out" | grep -q "every repo is set up under"; then
    ok "19. a re-run skips what is there and still finishes"
  else
    bad "19. the re-run did not behave: $(printf '%s' "$out" | tail -2)"
  fi
  powershell.exe -NoProfile -NonInteractive -Command \
    "Remove-Item -Recurse -Force '$root' -ErrorAction SilentlyContinue" >/dev/null 2>&1
}

# ---------------------------------------------------------------------
# Staged under /var/tmp, not /tmp, and that is not fussiness. In WSL
# `/tmp` is tmpfs AND the distro is terminated when it goes idle, so the
# copied script evaporates partway through a run -- check 15 failed with
# "cannot open" while check 3 had used the same file minutes earlier.
# It had worked all day only because a leftover agent process happened
# to keep the distro alive; removing that stray process broke the
# instrument, not the thing under test.
POSIX_SCRIPT="${EP_POSIX_SCRIPT:-/var/tmp/ep-bootstrap.sh}"

case "${EP_MODE:-auto}" in
  posix|auto)
    if [ "$(uname -s)" = Linux ] || [ "$(uname -s)" = Darwin ]; then
      cp "$HERE/bootstrap.sh" "$POSIX_SCRIPT"
      run_posix sh -c
    elif command -v wsl.exe >/dev/null 2>&1; then
      say "no native POSIX host; using WSL2"
      # Piped in, not copied by path: Git Bash rewrites anything that
      # looks like a POSIX path into a Windows one.
      wsl.exe -e bash -c "cat > '$POSIX_SCRIPT'" < "$HERE/bootstrap.sh"
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
