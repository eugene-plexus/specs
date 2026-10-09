#!/usr/bin/env bash
# Every GPU the operating system can see -- live (2026-09-27).
#
# An Intel Arc mini PC read "no GPU" on alpha.3. R2.3 had taught the
# engine picker to give a non-NVIDIA Windows GPU the Vulkan build, and
# the device list went on asking only vendor tools, so every fit on that
# machine was scored against RAM. The fix asks the operating system
# (DXCore and the GPU memory counters on Windows) through `gpu_probe`,
# and one decision, `gpu_probe.family`, now picks both the build and the
# cards a fit is scored against.
#
# **What only a live run can prove.** The unit gates drive `gpu_probe`
# with adapters they wrote. They cannot show that DXCore answers inside
# a real agent's worker thread, that the library child the agent spawns
# reads the same card, that the variant menu comes off a real upstream
# release, or that the build the agent installs uses the card the device
# list named.
#
# **This box is the fixture, and it is the hard case.** An RTX 5090
# beside an AMD integrated GPU whose shared allowance (~77 GiB) is larger
# than the card. With `nvidia-smi` removed from PATH it becomes a
# Windows machine no vendor tool answers on, the shape of an Arc or a
# Radeon box. The integrated GPU must not become the budget, because
# llama.cpp's Vulkan build does not use it while a card is present
# (measured the same day: `using device Vulkan0 (NVIDIA GeForce RTX
# 5090)` with nothing pinned).
#
# The checks:
#   0. isolated from the live install, and from its ports
#   1. with nvidia-smi: the 5090 as `cuda`, the integrated GPU not listed
#   2. without it: the 5090 as `vulkan`, its own memory, not the Radeon
#   3. the build is win-vulkan-x64, and the other builds are this OS's
#   4. a build for another OS is refused with the list
#   5. the agent installs win-vulkan-x64, and that build sees the card
#   6. the library child scores the same card, as a card
#   7. the library takes unifiedMemory from a running process
#   8. teardown by pid; no owned port still listening
#
# **Safe beside a live install**: every ambient EUGENE_PLEXUS_* variable
# is dropped, ports are +100, the engine root is a throwaway, teardown is
# by pid. Never `pkill -f eugene_plexus_`: this box is a worker node.
set -uo pipefail

EP_ROOT="${EP_ROOT:-/d/py/eugene-plexus}"
PY="${EP_AGENT_PY:-$EP_ROOT/agent/.venv/Scripts/python.exe}"
WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-every-gpu}"
AGENT_PORT="${EP_AGENT_PORT:-8179}"
LIB_PORT="${EP_LIB_PORT:-8182}"
AGENT="http://127.0.0.1:$AGENT_PORT"
LIB="http://127.0.0.1:$LIB_PORT"
OWNED_PORTS="$AGENT_PORT $LIB_PORT"
PASS="every-gpu-acceptance-passphrase"

FAILURES=0
SKIPPED=0
say() { printf '\n== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
note() { printf '  NOTE  %s\n' "$*"; }
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
while IFS='=' read -r name _; do
  case "$name" in EUGENE_PLEXUS_*) unset "$name" ;; esac
done < <(env)
rm -rf "$WORK"; mkdir -p "$WORK/engines" "$WORK/models"
WORK_WIN=$(win_path "$WORK")
ok "ambient EUGENE_PLEXUS_* cleared; ports $OWNED_PORTS free; work dir $WORK"

# PATH with every directory holding a real nvidia-smi removed. Left in
# bash form: MSYS converts a POSIX path list for a Windows child only if
# every entry is POSIX (measured in R2.3's run).
PATH_NO_NVIDIA=$(
  printf '%s' "$PATH" | tr ':' '\n' | while read -r d; do
    [ -n "$d" ] || continue
    [ -e "$d/nvidia-smi.exe" ] || [ -e "$d/nvidia-smi" ] || printf '%s:' "$d"
  done
)
PATH_NO_NVIDIA=${PATH_NO_NVIDIA%:}

write_topology() {
  cat > "$WORK/agent.yaml" <<YAML
firstRunComplete: true
updateChecks: false
components:
  - name: library
    kind: library
    url: http://127.0.0.1:$LIB_PORT
    spawn:
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
start_agent() {
  local use_path=$1; shift
  teardown; A_PID=""
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

get() { curl -s -m "${2:-30}" -H "Authorization: Bearer $TOK" "$1"; }
gh_budget() {
  curl -s -m 10 https://api.github.com/rate_limit | jq_ "d['resources']['core']['remaining']" \
    || printf 'unknown'
}

# What DXCore says about this box, read in THIS script's own process so the
# checks below compare the agent against an independent reading.
DXCORE=$("$PY" -c "
from eugene_plexus_agent.engines import gpu_probe
for a in gpu_probe.windows_adapters():
    print(f'{a.name}|{a.vendor}|{int(a.integrated)}|{a.dedicated_bytes}')
" 2>/dev/null)
CARD=$(printf '%s\n' "$DXCORE" | awk -F'|' '$3==0 && $2=="nvidia" {print $1; exit}')
CARD_BYTES=$(printf '%s\n' "$DXCORE" | awk -F'|' '$3==0 && $2=="nvidia" {print $4; exit}')
IGPU=$(printf '%s\n' "$DXCORE" | awk -F'|' '$3==1 {print $1; exit}')
note "DXCore here: $(printf '%s' "$DXCORE" | tr '\n' ';')"
if [ -z "$CARD" ] || [ -z "$IGPU" ]; then
  skip "this box is not an NVIDIA card beside an integrated GPU, which is the case under test"
fi

# --------------------------------------------------------------------- #
say "1. with nvidia-smi: the card is cuda, the integrated GPU is not listed"
start_agent "$PATH" || exit 1
NODE=$(get "$AGENT/v1/node")
KINDS=$(printf '%s' "$NODE" | jq_ "';'.join(f\"{x['kind']}:{x.get('name')}\" for x in d.get('devices') or [] if x['kind']!='cpu')")
if [ "$KINDS" = "cuda:$CARD" ]; then
  ok "devices: $KINDS"
else
  bad "expected cuda:$CARD alone, got '$KINDS'"
fi

# --------------------------------------------------------------------- #
say "2. without nvidia-smi: the card is vulkan, with its own memory"
start_agent "$PATH_NO_NVIDIA" || exit 1
NODE=$(get "$AGENT/v1/node")
KINDS=$(printf '%s' "$NODE" | jq_ "';'.join(f\"{x['kind']}:{x.get('name')}\" for x in d.get('devices') or [] if x['kind']!='cpu')")
TOTAL=$(printf '%s' "$NODE" | jq_ "next((x.get('memoryTotalBytes') for x in d.get('devices') or [] if x['kind']=='vulkan'), None)")
FREE=$(printf '%s' "$NODE" | jq_ "next((x.get('memoryFreeBytes') for x in d.get('devices') or [] if x['kind']=='vulkan'), None)")
SHARED=$(printf '%s' "$NODE" | jq_ "next((x.get('sharedMemory') for x in d.get('devices') or [] if x['kind']=='vulkan'), 'absent')")
if [ "$KINDS" = "vulkan:$CARD" ]; then
  ok "devices: $KINDS -- before this slice: none, and 'no GPU'"
else
  bad "expected vulkan:$CARD alone, got '$KINDS' (the integrated GPU must not be the budget)"
fi
[ "$TOTAL" = "$CARD_BYTES" ] && ok "its total is DXCore's ($TOTAL bytes)" \
  || bad "its total $TOTAL is not DXCore's $CARD_BYTES"
case "$FREE" in
  ''|None) bad "no free figure: the GPU memory counters did not answer inside the agent" ;;
  *) [ "$FREE" -lt "$TOTAL" ] && ok "free $FREE < total: usage was read, system-wide" \
       || bad "free $FREE is not below total $TOTAL" ;;
esac
[ "$SHARED" = "None" ] && ok "a card with memory of its own is not marked shared" \
  || bad "sharedMemory was '$SHARED' on a discrete card"

# --------------------------------------------------------------------- #
say "3. the build, and the other builds"
ENGINES=$(get "$AGENT/v1/engines" 60)
VARIANT=$(printf '%s' "$ENGINES" | jq_ "next((e.get('acquisition') or {}).get('variant') for e in d['engines'] if e['engine']=='llama_cpp')")
ALTS=$(printf '%s' "$ENGINES" | jq_ "','.join(next((e.get('acquisition') or {}).get('alternatives') or [] for e in d['engines'] if e['engine']=='llama_cpp'))")
if [ "$VARIANT" = "None" ] || [ -z "$VARIANT" ]; then
  skip "upstream did not answer (GitHub budget left: $(gh_budget))"
else
  [ "$VARIANT" = "win-vulkan-x64" ] && ok "variant $VARIANT" || bad "variant '$VARIANT'"
  case ",$ALTS," in
    *,win-sycl-x64,*win-vulkan-x64,*) ok "other builds: $ALTS" ;;
    *) bad "other builds lack SYCL or Vulkan: $ALTS" ;;
  esac
  case "$ALTS" in *ubuntu*|*macos*) bad "another OS's build is on the menu: $ALTS" ;;
    *) ok "every one is a Windows x64 build" ;; esac
fi

# --------------------------------------------------------------------- #
say "4. a build for another OS is refused, with the list"
CODE=$(curl -s -o "$WORK/refused.json" -w '%{http_code}' -m 60 -X POST \
  -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d '{"variant":"ubuntu-vulkan-x64"}' "$AGENT/v1/engines/llama_cpp/install")
DETAIL=$(jq_ "str(d)" < "$WORK/refused.json")
if [ "$CODE" = "422" ] && printf '%s' "$DETAIL" | grep -q "win-vulkan-x64"; then
  ok "422, naming what this machine can have"
elif [ "$VARIANT" = "None" ] || [ -z "$VARIANT" ]; then
  skip "upstream did not answer; the refusal was $CODE"
else
  bad "got $CODE: $DETAIL"
fi

# --------------------------------------------------------------------- #
say "5. the agent installs the Vulkan build, and that build sees the card"
if [ "$VARIANT" = "win-vulkan-x64" ]; then
  curl -s -m 60 -X POST -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
    -d '{}' "$AGENT/v1/engines/llama_cpp/install" > /dev/null
  STATE=""
  for _ in $(seq 1 180); do
    STATE=$(get "$AGENT/v1/engines/llama_cpp/install" | jq_ "d.get('state')")
    case "$STATE" in done|failed|cancelled) break ;; esac
    sleep 2
  done
  if [ "$STATE" = "done" ]; then
    MANAGED=$(get "$AGENT/v1/engines" 60 | jq_ "next((e.get('managed') or {}) for e in d['engines'] if e['engine']=='llama_cpp')")
    MV=$(printf '%s' "$MANAGED" | python -c "import sys,ast; print(ast.literal_eval(sys.stdin.read()).get('variant'))")
    BIN=$(printf '%s' "$MANAGED" | python -c "import sys,ast; print(ast.literal_eval(sys.stdin.read()).get('binaryPath'))")
    [ "$MV" = "win-vulkan-x64" ] && ok "installed $MV" || bad "installed '$MV'"
    LISTED=$("$(cygpath -u "$BIN")" --list-devices 2>&1 | grep -E "Vulkan[0-9]+:" | tr '\n' ';')
    case "$LISTED" in
      *"$CARD"*) ok "the installed build lists the card: $LISTED" ;;
      *) bad "the installed build does not list $CARD: $LISTED" ;;
    esac
  else
    bad "the install ended '$STATE': $(get "$AGENT/v1/engines/llama_cpp/install" | jq_ "d.get('error')")"
  fi
else
  skip "no Vulkan plan to install (variant '$VARIANT')"
fi

# --------------------------------------------------------------------- #
say "6. the library child scores the same card, as a card"
wait_healthy "$LIB" 60 || bad "the library never came up"
HW=$(get "$LIB/v1/hardware")
GPUS=$(printf '%s' "$HW" | jq_ "';'.join(g['name'] for g in d.get('gpus') or [])")
UNIFIED=$(printf '%s' "$HW" | jq_ "d.get('unifiedMemory')")
WARN=$(printf '%s' "$HW" | jq_ "' | '.join(d.get('warnings') or [])")
[ "$GPUS" = "$CARD" ] && ok "gpus: $GPUS -- before this slice: none" || bad "gpus '$GPUS'"
[ "$UNIFIED" = "False" ] && ok "not a shared pool" || bad "unifiedMemory '$UNIFIED'"
if printf '%s' "$WARN" | grep -qi "no accelerator"; then
  bad "the library still says no accelerator: $WARN"
else
  ok "and does not say 'no accelerator'"
fi

# --------------------------------------------------------------------- #
say "7. the library takes unifiedMemory from a running process"
STARTER=$(get "$LIB/v1/catalogue/starter?vramBytes=15000000000&ramBytes=26000000000&unifiedMemory=true" 60)
ALL=$(printf '%s' "$STARTER" | jq_ "all((m.get('fit') or {}).get('budget',{}).get('unifiedMemory') is True for m in d.get('models') or [None]) and bool(d.get('models'))")
[ "$ALL" = "True" ] && ok "every starter verdict was scored as one pool" \
  || bad "the starter set ignored unifiedMemory: $(printf '%s' "$STARTER" | head -c 300)"

# --------------------------------------------------------------------- #
say "8. teardown"
teardown
STILL=""
for p in $OWNED_PORTS; do [ -n "$(listening_pids "$p")" ] && STILL="$STILL $p"; done
[ -z "$STILL" ] && ok "no owned port still listening" || bad "still listening:$STILL"

printf '\n'
if [ "$SKIPPED" != 0 ]; then
  printf 'every-gpu: %s check(s) SKIPPED; GitHub budget left: %s.\n' "$SKIPPED" "$(gh_budget)"
fi
if [ "$FAILURES" = 0 ]; then
  printf 'every-gpu: all checks passed\n'
  exit 0
fi
printf 'every-gpu: %s FAILED\n' "$FAILURES"
exit 1
