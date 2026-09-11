# M7 acceptance on two hosts — the multi-host claim, finally tested

**Status:** passed 2026-09-11, **first two-host run ever**, 41 checks,
zero failures, on the first attempt. Script:
[`scripts/m7-acceptance.sh`](../../scripts/m7-acceptance.sh) in
`EP_MODE=two-host`. The same script in `same-box` mode was re-run green
immediately before (also 41 checks) to prove the parameterisation was
neutral. Design:
[`m7-second-host-readiness.md`](../design/m7-second-host-readiness.md)
and [`m5-multi-host-and-trust.md`](../design/m5-multi-host-and-trust.md);
the same-box record is [`m7-two-agent-run.md`](m7-two-agent-run.md).

```
host A  Windows 11              agent A :8079 ─spawns─> control :8083, gateway :8080, library :8082
        all four bound 0.0.0.0                          reached at 172.19.208.1
host B  WSL2 Ubuntu 26.04       agent B :8084 ─spawns─> qwen-b (vllm serve :8090, loopback on B)
        kernel 6.18.33.2                                + qwen-b-driver :8091, bound 0.0.0.0
        reached at 172.19.221.94                          advertised as 172.19.221.94:8091

NAT between them. Windows Firewall in the middle. Nothing on loopback that crosses.
```

This is the run M5 has been waiting for since 2026-09-09 and the largest
remaining gap in it. **Every hop above crossed a real network between two
kernels** — separate network namespaces, separate filesystems, separate
process tables, address translation and a host firewall in between.

---

## What only two hosts could prove

The same-box record's "cannot" list had four items. **One is now
discharged outright, and the other three are sharpened rather than
solved.**

- **A non-loopback bind, on every one of A's services.** `netstat`
  during the run: `0.0.0.0` on 8079, 8080, 8082 and 8083. This is the
  mechanism M7 built and nothing had ever exercised — a component binds
  wide *only* when its node advertises a non-loopback address, and the
  agent passes the same widening down to every component it spawns.
  **Engines are deliberately excluded and stayed excluded:** `vllm
  serve` on B was spawned with `--host 127.0.0.1`, because an engine is
  reached by its own companion on its own host and has no business on a
  wire.
- **`advertiseUrl` derived from the route to the root, against a route
  that is not loopback.** B was given no `advertiseUrl` in its config on
  purpose. It came back `http://172.19.221.94:8084` — B looked at the
  socket it used to reach a control root on *another machine* and
  reported the address that socket had. That is the whole point of the
  field and it had only ever been tested against 127.0.0.1, where it
  cannot be wrong.
- **A companion advertised across hosts, and routed to by IP.** B's
  companion came up on B's port 8091 and advertised
  `http://172.19.221.94:8091`. The gateway on A read it out of the
  control root's topology and put it in its routing table as
  `('qwen-b-driver', 'node-b', 'http://172.19.221.94:8091/', 'ready')`.
- **The whole lifecycle, over the wire.** A completion served on B and
  attributed to node-b; an **idle unload decided by the gateway on A and
  executed by agent B**; a **wake on demand** with `swapped_in=true`;
  and a **signing-key rotation** that re-keyed both agents through the
  signed `POST /v1/node/rekey` and left both reporting generation 2 —
  followed by a completion under the new key, after A had restarted its
  gateway and B had restarted its companion, independently.
- **Fencing over the wire.** A genuinely signed epoch-0 re-key, forged
  with the real control identity unsealed from a real snapshot, was
  refused 409 by an agent on another machine; the same body with the
  epoch edited was 401; B stayed at epoch 1.

## The one number worth carrying forward

**A cross-host wake took 21,416 ms, of which `waited_ms` was 20,693.**

M6's same-box wake of a llama.cpp replica was **2.5 s**. This is the
same code path and an order of magnitude slower, and none of it is the
network: it is vLLM's startup, measured at 15-16 s warm in
[the M4 run](m4-vllm-run.md) plus this engine's own cold-cache penalty
in a fresh install directory. So **wake latency is a property of the
engine, not of the control plane**, and `swapWaitSeconds: 120` is doing
real work here rather than sitting unused — a 20 s wait would have been
20 s of a client hanging, and the default is what kept it a wake instead
of a 502. Worth knowing before anyone tunes that default down on the
evidence of llama.cpp alone.

## Heterogeneous by force, not by contrivance

B runs **vLLM** while A hosts the trust root and the gateway, and that
was not a choice made to be impressive. **Our own M1 acquisition policy
refuses to install llama.cpp on a Linux host with an NVIDIA GPU** —
upstream publishes no such build, and the refusal says so and names the
alternatives. So on this pair, a homogeneous run was never available:
either B gets a hand-built llama.cpp, routing around our own policy, or
B runs the engine that works there. It runs vLLM.

Which means this run is also the first evidence for **differentiator
#7** as actually claimed — one endpoint over heterogeneous backends —
rather than for balancing across replicas of one engine, which is all
M6 showed.

## What the script needed, and one check that was lying

Nothing in any component changed. The script did:

1. **Host B's engine, model path, binary, flags and env are now
   parameters** (`EP_ENGINE_B`, `EP_MODEL_B`, `EP_BINARY_B`,
   `EP_FLAGS_B`, `EP_ENV_B`, `EP_ALIAS`). They defaulted to the
   same-box llama.cpp values, which is what let the regression run
   prove the change was neutral. B's paths are **never** passed through
   `win_path` — on a real two-host run this box cannot even see them.
2. **`EP_ADVERTISE_A`, and it matters more than it looks.** A component
   binds wide only when its node advertises non-loopback, and
   **enrollment deliberately does not restart the control root**. So if
   A's advertise address were discovered only at enrollment time, the
   root would still be bound to loopback afterwards and B could never
   reach it. Setting it in A's config up front is what makes the root
   reachable at all — the ordering is load-bearing and was not obvious.
3. **Two literal loopback assertions became derived.** The companion's
   `advertiseUrl` was asserted to start with `http://127.0.0.1:`, and
   its `/v1/info` was probed at a hardcoded `127.0.0.1:8091`. Both now
   come from B's own advertised address.
4. **A check that could not fail.** Teardown counted `llama-server`
   processes on *this* host. In two-host mode that passes vacuously —
   the engine is on B, B's agent is not the script's to stop, and B need
   not be running llama.cpp at all. It now reports what B was left
   holding and says plainly that nothing here owns B's lifecycle,
   instead of banking a green check for looking in the wrong place.
   Same family as the socket instrument in the M4 run: **a check whose
   subject is not where it is looking will report on the wrong thing
   confidently.**

## Still not proven, and now precisely

The three surviving caveats are no longer "we only have one box" — they
are specific, and two of them this pair *cannot* answer:

- **A node genuinely offline during a rotation.** Both hosts are on one
  machine's power and one machine's uptime. Rotating with B truly
  unreachable, and having it catch up afterwards, needs a second machine.
- **Clock skew.** Both clocks come from the same hardware clock. WSL2
  tracks the host's time, so there is nothing to skew.
- **A partitioned rather than dead old root.** The forge tests the
  *refusal*; it does not produce a live old root that still believes it
  is the root while the network has moved on. This one is testable here
  in principle — dropping the firewall rule mid-run would sever A from B
  for real — and is the obvious next experiment, because it is the one
  failure the design's epoch fencing exists for.
- **The ~2 s post-unload routing window is still undiagnosed.** This run
  took the default `EP_WAKE_DELAY=4`, so it is no evidence either way,
  exactly as the previous re-run was not. It remains open.

## Reproducing it

```sh
# host B, inside WSL2: a bare agent, own config dir, bound wide
mkdir -p ~/ep-host-b && cd ~/ep-host-b
printf 'firstRunComplete: true\ncomponents: []\nruntimes: []\n' > agent.yaml
EUGENE_PLEXUS_AGENT_CONFIG_FILE=agent.yaml \
EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0 \
EUGENE_PLEXUS_AGENT_BIND_PORT=8084 \
  ~/eugene-plexus/agent/.venv/bin/python -m eugene_plexus_agent
# then POST /v1/auth/initialize on it once, with EP_AGENT_B_PASSPHRASE

# host A, from the specs checkout
EP_MODE=two-host \
EP_AGENT_A_URL=http://172.19.208.1:8079 EP_ADVERTISE_A=http://172.19.208.1:8079 \
EP_CONTROL_URL=http://172.19.208.1:8083 EP_GATEWAY_URL=http://172.19.208.1:8080 \
EP_AGENT_B_URL=http://172.19.221.94:8084 EP_AGENT_B_PASSPHRASE=... \
EP_ENGINE_B=vllm EP_ALIAS=qwen3-0.6b \
EP_MODEL_B=/home/tcorbin/models/Qwen3-0.6B \
EP_BINARY_B=/home/tcorbin/vllm/.venv/bin/vllm \
EP_FLAGS_B='{"maxModelLen":4096,"gpuMemoryUtilization":0.5,"maxNumSeqs":4,"enforceEager":true}' \
EP_ENV_B='{"VLLM_WSL2_ENABLE_PIN_MEMORY":"1","VLLM_USE_FLASHINFER_SAMPLER":"0"}' \
  bash scripts/m7-acceptance.sh
```

The two IPs are this machine's WSL NAT addresses and will differ
elsewhere; `ip route` inside WSL names the host, and `ip addr show eth0`
names the guest. **WSL→Windows needs the Windows firewall to allow
inbound to the listening binary** — the agent spawns every component
with its own `sys.executable`, so allowing that one `python.exe` covers
all of them. Windows→WSL needs nothing.
