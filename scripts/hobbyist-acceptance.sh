#!/usr/bin/env bash
# S10 entry point. The maintained instrument counts real browser events, tests
# the download branch, and times from installer start to visible assistant text.
# Every run needs a NEW output directory; no recursive cleanup is performed.
# Dependencies: the chosen Python has httpx + PyYAML; sibling ui has npm ci;
# Windows has Chrome and Node. WSL drives that Windows browser over forwarding.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="${EP_TARGET:-windows}"
STAMP="$(date +%Y%m%d-%H%M%S)-$$"
ARGS=()
if [ "${EP_DOWNLOAD:-0}" = "1" ]; then ARGS+=(--download); fi
case "$TARGET" in
  windows)
    PY="${EP_TEST_PY:-$HERE/../../agent/.venv/Scripts/python.exe}"
    WORK="${EP_WORKDIR:-${TMPDIR:-/tmp}/ep-s10-$STAMP}"
    ARGS+=(--output "$(cygpath -w "$WORK")")
    if [ "${EP_DOWNLOAD:-0}" != "1" ]; then
      MODEL="${EP_MODEL:-$HOME/.eugene-plexus/acceptance-models/Qwen3-0.6B-Q4_K_M.gguf}"
      ARGS+=(--model "$(cygpath -w "$MODEL")")
    fi
    exec "$PY" "$(cygpath -w "$HERE/s10-acceptance.py")" "${ARGS[@]}"
    ;;
  wsl)
    : "${EP_TEST_PY_WSL:?Set EP_TEST_PY_WSL to a WSL Python with httpx and PyYAML}"
    SCRIPT=$(wsl.exe -e wslpath -u "$(cygpath -w "$HERE/s10-acceptance.py")" | tr -d '\r')
    ARGS+=(--output "${EP_WORKDIR:-/tmp/ep-s10-$STAMP}")
    if [ "${EP_DOWNLOAD:-0}" != "1" ]; then
      : "${EP_MODEL_WSL:?Set EP_MODEL_WSL to a small GGUF visible in WSL}"
      ARGS+=(--model "$EP_MODEL_WSL")
    fi
    exec wsl.exe -e "$EP_TEST_PY_WSL" "$SCRIPT" "${ARGS[@]}"
    ;;
  *) echo "EP_TARGET must be windows or wsl" >&2; exit 2 ;;
esac
