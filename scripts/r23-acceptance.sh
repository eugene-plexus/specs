#!/usr/bin/env bash
# R2.3 -- a card we cannot see is not a machine without one. Live.
#
# Roadmap: docs/design/release-roadmap.md §3.3. Findings: review §6.1
# #11 (any non-NVIDIA GPU on Windows gets a CPU build, silently, and is
# then scored as a machine with no accelerator), §6.2 #29 (a vendor tool
# that exists and exits non-zero is diagnosed as one that is not on
# PATH), §6.2 #28 (a card whose size no tool will state is scored as no
# card at all, so a 30 GB model "fits" on a 16 GB Arc).
#
# **What only a live run can prove.** The unit gates drive the detectors
# with a patched `subprocess` and see the failure exactly where they put
# it. What they cannot show is the consequence a person meets: a real
# agent choosing a real asset variant off a real upstream release, and a
# real library answering `GET /v1/catalogue/starter` with a
# recommendation that is either the largest model that fits or the
# smallest one on the list -- which is the difference between a working
# first hour and an inexplicable one.
#
# **The stubs are real programs, and two of them had to be.**
#   * `nvidia-smi.exe` is a COPY OF `find.exe`. A `.cmd` cannot shadow a
#     real `.exe` for the agent, because `_run` passes `argv` to
#     CreateProcess rather than the path `shutil.which` resolved -- a
#     `.cmd` stub was measured running the machine's REAL nvidia-smi.
#     `find` with no arguments is a genuine executable that exits 2 and
#     writes to stderr, which is exactly the shape of a wedged driver.
#   * `xpu-smi.cmd` is enough for the library, which resolves the path
#     first and so runs what `which` found.
#
# **This box is the fixture.** It has an AMD integrated adapter beside
# the 5090 (measured: `Win32_VideoController` returns
# `AMD Radeon(TM) Graphics` and `NVIDIA GeForce RTX 5090`), so removing
# NVIDIA's tool from PATH turns it into precisely the machine #11 is
# about: a Windows box whose only visible GPU is not NVIDIA's. A box
# with no second adapter reports SKIP with the reason rather than a
# pass.
#
# The checks:
#   0. isolated from the live install, and from its ports
#   1. the baseline: with a working nvidia-smi the plan is a CUDA build
#   2. **#29**: nvidia-smi exists and exits 2 -> the plan is NOT a CUDA
#      build, and the log says the tool failed
#   3. **#11**: the same run picks `win-vulkan-x64` off the real
#      upstream release, for the AMD adapter that was always there
#   4. **#11**: nvidia-smi merely absent -> the same answer
#   5. **#29**: the library's warning names the wedged tool rather than
#      this process's PATH
#   6. **#28**: a card whose size xpu-smi will not state is counted, and
#      every verdict on this host is `unknown` rather than a guess
#   7. **#28**: the starter set is not inverted to the smallest model
#   8. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped, ports are +100, the engine root is a throwaway, teardown
# is by pid. Never `pkill -f eugene_plexus_`: this box is a worker node.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-r23}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
LIB_PORT="${EP_LIB_PORT:-8182}"
AGENT="http://127.0.0.1:$AGENT_PORT"
LIB="http://127.0.0.1:$LIB_PORT"
OWNED_PORTS="$AGENT_PORT $LIB_PORT"
PASS="r23-acceptance-passphrase"

FAILURES=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
SKIPPED=0
skip() { printf '  SKIP  %s\n' "$*"; SKIPPED=$((SKIPPED + 1)); }
jq_() { PYTHONUTF8=1 python -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }
listening_pids() { netstat -ano 2>/dev/null | grep ":$1 " | grep LISTENING | awk '{print $5}' | sort -u; }
kill_port() { for p in $(listening_pids "$1"); do taskkill //PID "$p" //F >/dev/null 2>&1 || kill -9 "$p" 2>/dev/null; done; }
win_path() { cygpath -w "$1" 2>/dev/null || printf '%s' "$1"; }

A_PID=""
teardown() {
  [ -n "$A_PID" ] && { kill "$A_PID" 2>/dev/null; sleep 2; }
  for p in $OWNED_PORTS; do kill_port "$p"; done
}
trap teardown EXIT

say "0. isolation"
[ -f "$PY" ] || { bad "no agent python at $PY"; exit 1; }
for p in $OWNED_PORTS; do
  [ -z "$(listening_pids "$p")" ] || { bad "port $p is already in use; refusing to run"; exit 1; }
done
# A loop, not a list: a throwaway agent that inherits the live worker's
# config file adopts its identity and re-announces its address.
while IFS='=' read -r name _; do
  case "$name" in EUGENE_PLEXUS_*) unset "$name" ;; esac
done < <(env)
rm -rf "$WORK"; mkdir -p "$WORK/stub" "$WORK/engines" "$WORK/models"
WORK_WIN=$(win_path "$WORK")
ok "ambient EUGENE_PLEXUS_* cleared; ports $OWNED_PORTS free; work dir $WORK"

# --- the stubs --------------------------------------------------------
SYS32="${SYSTEMROOT:-C:\\Windows}\\System32"
cp "$(cygpath -u "$SYS32")/find.exe" "$WORK/stub/nvidia-smi.exe" 2>/dev/null \
  || { bad "could not copy find.exe as a failing nvidia-smi"; exit 1; }
printf '@echo off\r\necho Device ID,Device Name\r\necho 0,Intel(R) Arc(TM) A770 Graphics\r\n' \
  > "$WORK/stub/xpu-smi.cmd"
STUB_WIN=$(win_path "$WORK/stub")

# PATH with every directory holding a real nvidia-smi.exe removed, so
# "absent" really means absent.
# **A Windows path list, not a bash one.** The agent and every child it
# spawns are Windows processes reading PATH with `;` separators, so a
# POSIX entry is unusable to them -- measured on the first execution of
# this script: the stub directory was first and worked for the agent,
# while the library child found none of the three stubs because
# everything after it was bash-shaped.
PATH_NO_NVIDIA=$(
  printf '%s' "$PATH" | tr ':' '\n' | while read -r d; do
    [ -n "$d" ] || continue
    [ -e "$d/nvidia-smi.exe" ] || [ -e "$d/nvidia-smi" ] || printf '%s:' "$d"
  done
)
PATH_NO_NVIDIA=${PATH_NO_NVIDIA%:}
# **Left in bash form on purpose.** MSYS converts a POSIX path LIST when
# it hands it to a Windows program, but only if every entry is POSIX --
# a list with one Windows entry spliced in front is passed through
# verbatim, and everything after the first `;` is then unusable to the
# child. Measured on the first execution: the agent found the stub and
# the library it spawned found nothing.
STUB_DIR="$WORK/stub"

write_topology() {
  cat > "$WORK/agent.yaml" <<YAML
firstRunComplete: true
components:
  - name: library
    kind: library
    url: http://127.0.0.1:$LIB_PORT
    spawn:
      # **Absolute, because the agent spawns with ITS cwd**, which is
      # the shell's -- a relative name wrote a library.yaml into the
      # specs checkout on the first execution of this script.
      configFile: $WORK_WIN\library.yaml
runtimes: []
YAML
  printf 'logLevel: INFO\nmodelRoots:\n  - %s\n' "$WORK_WIN\\models" > "$WORK/library.yaml"
}

wait_healthy() {
  local url=$1 n=${2:-40}
  for _ in $(seq 1 "$n"); do
    curl -sf -m 2 "$url/healthz" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

TOK=""
# start_agent <path> [extra env assignments...]
start_agent() {
  local use_path=$1; shift
  teardown; A_PID=""
  # **Both logs.** The agent mirrors its console to `logs/agent.log`
  # beside the config file, which survives a restart -- so a run that
  # cleared only the redirected file read the PREVIOUS run's warning and
  # reported a tool as failing on a run where none had been executed.
  rm -f "$WORK/agent.log" "$WORK/logs/agent.log"
  write_topology
  (
    exec env -u EUGENE_PLEXUS_AGENT_CONFIG_FILE \
      PATH="$use_path" \
      EUGENE_PLEXUS_AGENT_CONFIG_FILE="$WORK_WIN\\agent.yaml" \
      EUGENE_PLEXUS_AGENT_BIND_HOST=127.0.0.1 \
      EUGENE_PLEXUS_AGENT_BIND_PORT="$AGENT_PORT" \
      EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY=0 \
      EUGENE_PLEXUS_AGENT_ENGINE_ROOT="$WORK_WIN\\engines" \
      EUGENE_PLEXUS_LIBRARY_STATE_FILE="$WORK_WIN\\library-state.json" \
      "$@" \
      "$PY" -m eugene_plexus_agent --unattended > "$WORK/agent.log" 2>&1
  ) &
  A_PID=$!
  wait_healthy "$AGENT" 60 || { bad "the agent never came up"; tail -20 "$WORK/agent.log"; return 1; }
  TOK=$(curl -s -X POST "$AGENT/v1/auth/initialize" -H 'content-type: application/json' \
        -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
  [ -n "$TOK" ] || TOK=$(curl -s -X POST "$AGENT/v1/auth/login" -H 'content-type: application/json' \
        -d "{\"passphrase\":\"$PASS\"}" | jq_ "d.get('sessionToken','')")
  [ -n "$TOK" ] || { bad "no session token"; return 1; }
  return 0
}

# The agent mirrors its console to `logs/agent.log` beside the config
# file as well as to the file this script redirects, and neither is
# flushed the instant a request returns.
wedged_logged() {
  sleep 1
  grep -qi "is installed and exited" "$WORK/agent.log" 2>/dev/null && return 0
  grep -qi "is installed and exited" "$WORK/logs/agent.log" 2>/dev/null
}

llama_field() {
  curl -s -m 30 -H "Authorization: Bearer $TOK" "$AGENT/v1/engines" \
    | jq_ "next((e.get('acquisition',{}).get('$1') for e in d['engines'] if e['engine']=='llama_cpp'), 'ABSENT')"
}

# **The variant, with one retry, and a named excuse for the one thing
# that is not about us.** This read asks GitHub for the upstream release
# list, four times in one run -- and GitHub's UNAUTHENTICATED limit is
# 60 requests an hour per address. Measured: running this script ten
# times in an afternoon exhausts it, after which every variant check
# fails for a reason that is about the network. A run that cannot see
# upstream SKIPs the variant assertions and says so, rather than
# reporting the finding as reproducing.
gh_budget() {
  curl -s -m 10 https://api.github.com/rate_limit \
    | jq_ "d['resources']['core']['remaining']" 2>/dev/null || printf 'unknown'
}

variant_of() {
  local got
  got=$(llama_field variant)
  if [ "$got" = "None" ] || [ "$got" = "ABSENT" ] || [ -z "$got" ]; then
    # Silent: this function's stdout IS its return value, so a note here
    # lands inside the variant string and every comparison below reads a
    # two-line value. Caught on the first execution with the budget
    # exhausted.
    sleep 5
    got=$(llama_field variant)
  fi
  printf '%s' "$got"
}

# Assert a variant, unless upstream is out of reach.
want_variant() {
  local got=$1 want=$2 why=$3
  if [ "$got" = "$want" ]; then
    ok "$why"
  elif [ "$got" = "None" ] || [ "$got" = "ABSENT" ] || [ -z "$got" ]; then
    skip "upstream did not answer (GitHub budget left: $(gh_budget)); the reason was:"
    note "$(llama_field reason)"
  else
    bad "$why -- got '$got'"
  fi
}

# --------------------------------------------------------------------- #
say "1. the baseline: a working nvidia-smi still plans a CUDA build"
start_agent "$PATH" || exit 1
BASE=$(variant_of)
case "$BASE" in
  win-cuda-*) ok "variant $BASE" ;;
  None|ABSENT|"")
    skip "upstream did not answer (GitHub budget left: $(gh_budget)); the reason was:"
    note "$(llama_field reason)" ;;
  *) bad "expected a win-cuda-* variant on this box, got '$BASE'"; note "$(llama_field reason)" ;;
esac

# --------------------------------------------------------------------- #
say "2. #29 -- nvidia-smi exists and exits non-zero"
start_agent "$STUB_DIR:$PATH_NO_NVIDIA" || exit 1
WEDGED=$(variant_of)
case "$WEDGED" in
  win-cuda-*)
    bad "a wedged nvidia-smi still produced a CUDA plan ($WEDGED) -- the install would fail at load"
    ;;
  None|ABSENT|"")
    skip "upstream did not answer (GitHub budget left: $(gh_budget))" ;;
  *) ok "the plan is not a CUDA build ($WEDGED)" ;;
esac
if wedged_logged; then
  ok "the log says the tool ran and failed, rather than nothing at all"
else
  bad "nothing in the log distinguishes a wedged driver from an absent one"
fi

# --------------------------------------------------------------------- #
say "3. #11 -- and the AMD adapter that was always there decides"
ADAPTERS=$("$PY" -c "
from eugene_plexus_agent.engines import host
print('|'.join(host._windows_display_adapters()))
" 2>/dev/null)
NON_NVIDIA=$(printf '%s' "$ADAPTERS" | tr '|' '\n' | grep -iv nvidia | grep -iv "microsoft basic" | head -1)
if [ -z "$NON_NVIDIA" ]; then
  skip "this box has no non-NVIDIA display adapter, so #11's positive case cannot be produced here"
  note "adapters: $ADAPTERS"
else
  want_variant "$WEDGED" "win-vulkan-x64" \
    "win-vulkan-x64, for '$NON_NVIDIA' -- before this slice the same machine got win-cpu-x64"
fi

# --------------------------------------------------------------------- #
say "4. #11 -- nvidia-smi merely absent reaches the same answer"
start_agent "$PATH_NO_NVIDIA" || exit 1
ABSENT=$(variant_of)
if [ -z "$NON_NVIDIA" ]; then
  skip "no non-NVIDIA adapter here"
else
  want_variant "$ABSENT" "win-vulkan-x64" "win-vulkan-x64"
fi
if wedged_logged; then
  bad "a tool that is genuinely absent was logged as one that failed"
else
  ok "and nothing claims a tool failed, because none ran"
fi

# --------------------------------------------------------------------- #
say "5. #29 -- the library says which kind of nothing it found"
start_agent "$STUB_DIR:$PATH_NO_NVIDIA" || exit 1
wait_healthy "$LIB" 60 || { bad "the library never came up"; tail -20 "$WORK/agent.log"; }
HW=$(curl -s -m 20 -H "Authorization: Bearer $TOK" "$LIB/v1/hardware")
WARN=$(printf '%s' "$HW" | jq_ "' | '.join(d.get('warnings') or [])")
# **Not a bare "does it mention nvidia-smi".** The sentence this
# replaces lists all three vendor tools, so that match passes against
# the defect too -- an assertion that cannot fail. What is new is the
# statement that the tool RAN.
if printf '%s' "$WARN" | grep -qi "installed here and exited"; then
  ok "the warning says nvidia-smi ran and exited non-zero"
else
  bad "the warning does not say the tool ran and failed: $WARN"
fi
if printf '%s' "$WARN" | grep -qi "not on"; then
  bad "a tool that ran and failed was reported as one that is not on PATH: $WARN"
else
  ok "and does not blame this process's PATH"
fi

# --------------------------------------------------------------------- #
say "6. #28 -- a card whose size nothing will state"
GPUS=$(printf '%s' "$HW" | jq_ "len(d.get('gpus') or [])")
VENDOR=$(printf '%s' "$HW" | jq_ "(d.get('gpus') or [{}])[0].get('vendor','none')")
TOTAL=$(printf '%s' "$HW" | jq_ "(d.get('gpus') or [{}])[0].get('vramTotalBytes',-1)")
if [ "$GPUS" = "1" ] && [ "$VENDOR" = "intel" ] && [ "$TOTAL" = "0" ]; then
  ok "the card is counted (gpuCount 1, vendor intel) and its size is 0 -- the shape the detector emits"
else
  bad "the Intel stub did not land: gpus=$GPUS vendor=$VENDOR total=$TOTAL"
fi
STARTER=$(curl -s -m 30 -H "Authorization: Bearer $TOK" "$LIB/v1/catalogue/starter")
VERDICTS=$(printf '%s' "$STARTER" | jq_ "','.join(sorted({(m.get('fit') or {}).get('verdict','?') for m in d.get('models') or []}))")
if [ "$VERDICTS" = "unknown" ]; then
  ok "every verdict on this host is 'unknown' rather than a guess"
else
  bad "verdicts were '$VERDICTS'; a 30 GB model on a card of unknown size must not read as fits"
fi

# --------------------------------------------------------------------- #
say "7. #28 -- the starter set is not inverted to the smallest model"
REASON=$(printf '%s' "$STARTER" | jq_ "(d.get('recommended') or {}).get('reason') or ''")
CLASS=$(printf '%s' "$STARTER" | jq_ "(d.get('recommended') or {}).get('sizeClass') or ''")
if printf '%s' "$REASON" | grep -qi "no graphics card"; then
  bad "an Arc owner was told their machine has no graphics card (class $CLASS)"
else
  ok "no 'machine with no graphics card' sentence${CLASS:+ (recommended class: $CLASS)}"
fi
# **Nothing recommended is only honest if it says why.** The live run
# found this: with every verdict `unknown` nothing "fits", so the
# nothing-fits branch produced "None of these fits entirely in 0 B" --
# a number that is not a number, about a card we can see and cannot
# size.
if [ -n "$CLASS" ]; then
  bad "a class was recommended against a card nothing can measure ($CLASS)"
elif printf '%s' "$REASON" | grep -qi "0 B"; then
  bad "the reason quotes a budget of 0 B: $REASON"
elif printf '%s' "$REASON" | grep -qi "graphics card"; then
  ok "nothing is recommended, and the reason is about the machine rather than the models"
else
  bad "nothing recommended and nothing said: '$REASON'"
fi

# --------------------------------------------------------------------- #
say "8. teardown"
teardown
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ] && ok "no owned port still listening" || bad "still listening:$STILL"

printf '\n'
if [ "$SKIPPED" != 0 ]; then
  # **Said loudly, because a sabotage pass reads this script's exit
  # status.** With GitHub's unauthenticated budget exhausted the variant
  # assertions cannot run, and a green exit would tell a sabotage run
  # that the defect it put back was caught while nothing looked.
  printf 'R2.3: %s check(s) SKIPPED -- the variant path was not exercised.\n' "$SKIPPED"
  printf '      GitHub budget left: %s. Wait for the hourly reset and re-run\n' "$(gh_budget)"
  printf '      before trusting a sabotage result that depends on it.\n'
fi
if [ "$FAILURES" = 0 ]; then
  printf 'R2.3: all checks passed\n'
  exit 0
fi
printf 'R2.3: %s FAILED\n' "$FAILURES"
exit 1
