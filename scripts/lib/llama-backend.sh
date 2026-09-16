# shellcheck shell=bash
#
# A real engine behind the acceptance scripts, without Ollama.
#
# ## Why this file exists
#
# Eight scripts in this directory demanded a live Ollama with a named
# model pulled into it. Ollama was removed from the development box on
# 2026-09-16 in favour of Eugene's own llama.cpp install -- the engine
# this project actually acquires, supervises and ships -- so all eight
# stopped being runnable at once, including the only live proof several
# milestones have. Depending on a third-party product we no longer use,
# to prove our own front door, was always the odd part.
#
# This is the shared bring-up: find the engine, make sure a model is on
# disk, start `llama-server` on a port the caller owns, tear it down.
#
# ## Three decisions worth not rediscovering
#
# **The script runs the engine itself; it does not declare a runtime.**
# A runtime with `autoDriver` gets a companion driver whose port comes
# from `state.allocate_component_port()`, which scans 8090-8189 against
# THAT agent's own state and knows nothing about the machine. The
# development box is a live worker node holding 8090 and 8091, so a
# throwaway run would have taken a port out from under the real install.
# The engine here is scaffolding for slices about the control plane; what
# matters is that it is a real engine generating real tokens behind a
# real driver, which it is.
#
# **The provider key is `openai_compat_custom`, not `openai_compat_http`.**
# The latter is the engine CLASS behind it and is not a value the
# `provider` field takes; `PROVIDERS` in the driver's `providers.py` is
# the list. `openai_compat_custom` is also exactly what the agent's own
# companion drivers use (`COMPANION_PROVIDER`). Sending the wrong one is
# not an error: `apply_patch` returns 200 with per-field `applied` and
# `rejected` lists, so a driver silently keeps its DEFAULT provider
# (`claude_subscription`) and fails later by shelling out to a `claude`
# binary that is not there. `llama_configure_driver` reads the result.
#
# **`baseUrl` must NOT end in `/v1`.** The driver appends
# `/v1/chat/completions` itself, so a base of `http://host:port/v1` asks
# for `/v1/v1/chat/completions`, the engine answers 404, and the gateway
# correctly refuses to cascade it because the next backend would refuse
# it too. `llama_base_url` spells it right.
#
# ## `--jinja`, and what was actually measured
#
# Passed on every start, but NOT because tool calling needs it here:
# measured on b10948 with Qwen3-0.6B, identical requests with and without
# it produced byte-identical tool calls (`finish_reason: tool_calls`,
# `{"city": "Oslo"}`). A first comparison appeared to show it was
# required and was wrong -- the two runs had different `max_tokens`, and
# the shorter one truncated mid-`arguments`. It is kept because upstream
# documents it as the path for tool support and a model with a less
# forgiving chat template may need it, not because this repo has evidence
# that anything breaks without it.
#
# ## Usage
#
#     . "$(dirname "$0")/lib/llama-backend.sh"
#     llama_preflight                      # sets LLAMA_SERVER, ensures $EP_GGUF
#     llama_start 8192 my-model            # background; appends to LLAMA_PIDS
#     llama_start 8193 cpu-model --ngl 0   # a deliberately slower one
#     ...
#     llama_stop_all                       # from the caller's teardown
#
# The caller owns its ports and must include every port it passes to
# `llama_start` in its own `OWNED_PORTS`, because `llama_stop_all` kills
# by pid and a pid is not enough on Windows.

# Where the engine and the model come from. Both overridable so a run can
# be made self-contained; the defaults reuse what a developer box already
# has, read-only.
#
# Reusing the real engine store is safe: the run never installs into it,
# and llama.cpp builds are versioned directories that are never written
# in place. `engine_root()` in the agent uses this same path.
EP_ENGINE_ROOT="${EP_ENGINE_ROOT:-$HOME/.eugene-plexus/engines}"
EP_GGUF="${EP_GGUF:-$HOME/.eugene-plexus/acceptance-models/Qwen3-0.6B-Q4_K_M.gguf}"
EP_GGUF_URL="${EP_GGUF_URL:-https://huggingface.co/unsloth/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_K_M.gguf}"

LLAMA_SERVER=""
LLAMA_PIDS=""

# The newest build that has a server binary. `sort -V` so b10948 beats
# b10930 -- a lexical sort would not, and the acquisition code sorts by
# build number for the same reason.
llama_find_server() {
  local found
  found=$(ls -d "$EP_ENGINE_ROOT"/llama_cpp/*/llama-server.exe 2>/dev/null | sort -V | tail -1)
  [ -z "$found" ] && found=$(ls -d "$EP_ENGINE_ROOT"/llama_cpp/*/llama-server 2>/dev/null | sort -V | tail -1)
  printf '%s' "$found"
}

# Fetch the model once and keep it. 400 MB per run is a run nobody
# repeats, so this is cached outside the work directory on purpose.
llama_fetch_model() {
  local path="${1:-$EP_GGUF}" url="${2:-$EP_GGUF_URL}"
  [ -f "$path" ] && return 0
  mkdir -p "$(dirname "$path")" || return 1
  curl -fL --retry 3 -o "$path.part" "$url" || return 1
  mv "$path.part" "$path"
}

# Caller must define `bad`; every script here already does.
llama_preflight() {
  LLAMA_SERVER=$(llama_find_server)
  if [ -z "$LLAMA_SERVER" ] || [ ! -x "$LLAMA_SERVER" ]; then
    bad "no llama-server under $EP_ENGINE_ROOT/llama_cpp. Install llama.cpp from the UI (Inference -> Engines), or set EP_ENGINE_ROOT"
    return 1
  fi
  if ! llama_fetch_model; then
    bad "no model at $EP_GGUF and could not fetch $EP_GGUF_URL"
    return 1
  fi
  return 0
}

llama_build() { basename "$(dirname "$LLAMA_SERVER")"; }

# The base URL a driver should be given for an engine on this port.
# Deliberately no `/v1`: see the header.
llama_base_url() { printf 'http://127.0.0.1:%s' "$1"; }

# llama_start <port> <alias> [-m <gguf>] [--ngl N] [--ctx N] [extra...]
#
# `-a <alias>` fixes the id the engine advertises. Without it llama-server
# names the model by its file path and the gateway would route to a
# filename, which is both ugly and unstable across machines.
#
# **`--reasoning off`, and it is load-bearing, not tidiness.** The default
# acceptance model is Qwen3-0.6B, which is a reasoning model: asked for
# five words with `max_tokens: 40` it spends the entire budget inside
# `<think>` and returns `content: ""` with the thought extracted into
# `reasoning_content`. m10 failed two checks on exactly that -- "only 0
# content frame(s): this is the pre-M10 behaviour" -- which reads as a
# streaming regression and is nothing of the kind. Measured on b10948:
# with `--reasoning off` the same request answers `'Hello!'`, and tool
# calls are unaffected (`finish_reason: tool_calls`, `{"city": "Oslo"}`).
# A script that wants the thinking path back passes `--reasoning auto`.
llama_start() {
  local port="$1" alias="$2"; shift 2
  local gguf="$EP_GGUF" ngl=99 ctx=4096 reasoning=off extra=()
  while [ $# -gt 0 ]; do
    case "$1" in
      -m) gguf="$2"; shift 2 ;;
      --ngl) ngl="$2"; shift 2 ;;
      --ctx) ctx="$2"; shift 2 ;;
      --reasoning) reasoning="$2"; shift 2 ;;
      *) extra+=("$1"); shift ;;
    esac
  done
  local native; native=$(cygpath -w "$gguf" 2>/dev/null || printf '%s' "$gguf")
  ("$LLAMA_SERVER" -m "$native" --host 127.0.0.1 --port "$port" -a "$alias" \
    -c "$ctx" -ngl "$ngl" --jinja --reasoning "$reasoning" "${extra[@]}" > "llama-$port.log" 2>&1) &
  LLAMA_PIDS="$LLAMA_PIDS $!"
  local i
  for i in $(seq 1 180); do
    curl -sf -m 2 "http://127.0.0.1:$port/v1/models" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

# Started by us and supervised by nobody, so stopped by us. The engine
# holds VRAM; a caller that forgets this leaves a card full on a
# development box that is also a live worker node.
llama_stop_all() {
  local pid
  for pid in $LLAMA_PIDS; do kill "$pid" 2>/dev/null; done
  [ -n "$LLAMA_PIDS" ] && sleep 1
  LLAMA_PIDS=""
}

# PATCH a driver onto an engine and PROVE the patch landed.
#
# llama_configure_driver <driver-url> <token> <model-id> <engine-port>
llama_configure_driver() {
  local url="$1" token="$2" model="$3" port="$4" out
  out=$(curl -s -X PATCH "$url/v1/config" -H "Authorization: Bearer $token" \
    -H 'content-type: application/json' \
    -d "{\"provider\":\"openai_compat_custom\",\"baseUrl\":\"$(llama_base_url "$port")\",\"modelId\":\"$model\"}")
  if [ "$(printf '%s' "$out" | PYTHONUTF8=1 python -c "import sys,json;print(len(json.load(sys.stdin)['rejected']))" 2>/dev/null)" = "0" ]; then
    return 0
  fi
  bad "the driver rejected part of its config: $out"
  return 1
}
