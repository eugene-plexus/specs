# Row 50: one model across machines with llama.cpp's RPC server

Lane ENG. **High risk** (a new path between machines for an upstream
server with no authentication). Sources: the setups pass (RPC across
machines), llama.cpp's `tools/rpc/README.md` ("This example and the RPC
backend are currently in a proof-of-concept development stage … fragile and
insecure. Never run the RPC server on an open network or in a sensitive
environment!"), LT1 (`tls-between-machines.md`, the machine port), memory
`feedback_no_new_ports`.

## 1. What it delivers

- **A model too big for one machine runs on the GPUs of several.** On a
  llama.cpp profile: "Also use the GPUs of: nas (RTX 3090, 24 GB),
  garage-pc (RTX 3060, 12 GB)". Eugene starts llama.cpp's RPC server on
  those machines, connects them to the main runtime, and splits the model
  across every card by free memory, as llama.cpp does.
- **Safely, with no new port.** The RPC server listens on loopback only on
  each machine. Its traffic travels over Eugene's machine port (LT1:
  encrypted, both ends pinned, the caller's machine token checked), never
  in the clear on the LAN.
- **Honest about speed.** The profile shows the network link and, after a
  measurement (row 10), what it costs; fit counts every card.

## 2. Design

### On each helper machine (agent)

- A runtime kind `rpc`: the build's RPC server (`rpc-server`, named
  `ggml-rpc-server` in newer builds) from the machine's managed llama.cpp
  build, bound to `127.0.0.1:<allocated port>`, with the chosen cards
  (`--device` / `CUDA_VISIBLE_DEVICES`, by UUID from row 43) and its tensor
  cache (`-c`, with `LLAMA_CACHE` in the agent's data folder, so a second
  load does not send the weights again).
- **Who may connect:** the runtime records `peers` (the main machine's
  node name). The tunnel route accepts only that node's machine token.
- A build without the RPC server: the profile says "garage-pc's llama.cpp
  build has no RPC server; update it", and offers the update.

### The tunnel (agent, over the machine port)

- **Route on the helper:** `GET /agent/v1/rpc/{runtime}` upgraded to a
  WebSocket on the machine port (LT1's TLS, the helper's pinned key),
  authenticated by the caller's node token, refused unless the caller is
  in the runtime's `peers`. The agent pumps binary frames to and from its
  loopback RPC server.
- **On the main machine:** for each helper, the agent opens a loopback
  listener (`127.0.0.1:<port>`) and pumps each accepted connection into a
  WebSocket to the helper. llama-server gets `--rpc
  127.0.0.1:<p1>,127.0.0.1:<p2>`.
- **Throughput:** a Python pump carries a few hundred MB/s, enough for 1
  and 2.5 Gb/s links; the tensor cache means weights cross once. An
  expert override, "Direct connection (trusted network only)", binds the
  helper's RPC server to its LAN address for the main machine's address
  only, with a warning that the traffic is neither encrypted nor
  authenticated (call R50-DIRECT). It is off by default.

### The main runtime

- The profile field `rpcHelpers`: [{node, devices}]. Saving it declares an
  `rpc` runtime on each helper (through the console, the owner's session),
  started before the main runtime and stopped after it; auto-start follows
  the main runtime's.
- **Fit:** the library's fit gets the sum of the local cards' and helpers'
  free memory (read from each helper's `/v1/node`), and the split order is
  local cards first, then helpers in list order (`--tensor-split`
  follows it when the profile sets one).
- **Builds must match:** the RPC protocol changes between llama.cpp builds.
  The agent compares each helper's build with its own and refuses to start
  with a mismatch: "nas runs llama.cpp b6100, this machine b6142. Update
  nas." (Update all brings them level.)
- **A helper that is down:** the start refits without it if the model
  still fits (row 43's rule), else fails naming it. A helper lost while
  running ends the runtime (llama.cpp cannot drop a device); the
  supervisor restarts it under the same rule.

### Contract (`agent.yaml`)

Runtime kind `rpc` with `peers` and `devices`; the llama.cpp profile field
`rpcHelpers`; the machine-port route; `Runtime.rpc` {helpers: [{node,
state, link}]} for the console.

## 3. Repositories and files

specs (`agent.yaml`), agent (`engines/llama_cpp.py`, a new `rpc_tunnel.py`,
`machine_port.py` route, `runtimes.py`, `admission.py` for fit), library
(none: fit takes the budget it is given), ui (the profile's helpers
picker, the runtime's helpers line). Regenerate agent and ui and diff.

## 4. Tests that fail before

- agent `test_rpc_tunnel.py::test_bytes_cross_the_machine_port_both_ways`
  (two in-process agents, a fake RPC server echoing).
- agent `test_rpc_tunnel.py::test_a_node_not_in_peers_is_refused` and
  `test_the_rpc_server_binds_loopback_only`.
- agent `test_llama_cpp.py::test_rpc_helpers_become_loopback_rpc_endpoints`.
- agent `test_admission.py::test_fit_counts_helpers_free_memory`.
- agent `test_runtimes.py::test_mismatched_builds_refuse_with_both_numbers`.

## 5. Acceptance (CI, Linux, about 5 minutes)

`specs/scripts/row50-rpc-acceptance.py` on row 2's harness with two
enrolled agents (root and helper) and the real llama.cpp CPU build from
the managed acquisition (its RPC server exposes a CPU device): a tiny GGUF
(the harness's test model) loads across both with `--rpc`, a chat answers
through the gateway, and a packet capture on the LAN interface shows only
TLS between the machines. A third agent not in `peers` is refused.
**Sabotage:** skip the peers check; the third agent's connection must then
succeed and the run fail.

**Real GPUs across machines:** this machine and the NAS could run it; the
orchestrator runs it once if both have cards free. Not a roadmap item
otherwise.

## 6. Do not change

- LT1's pins and the machine port's TLS (`machine_trust.py`); add the
  route only.
- Row 43's device code (call it for UUIDs and refit).

## 7. Size and risks

L, about 4 days, after row 43. One adversarial review.
Risks:
- **An unauthenticated upstream server:** loopback only, reachable through
  the authenticated tunnel only; the direct mode is an expert's choice
  with the warning.
- **Network speed decides the speed.** Row 10's sweep measures it; the
  profile shows the link speed and the measurement beside the setting.
- **Upstream calls it fragile.** A failure names the helper and
  llama.cpp's words; the feature is labelled experimental until a
  measurement on real cards exists.

**Calls:** R50-DIRECT (an expert's direct, unencrypted connection on a
trusted network; off by default).
