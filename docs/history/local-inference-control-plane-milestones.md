# Local-inference control plane: milestones M0-M11

> **Retired 2026-10-21.** Kept as history. Moved out of [`local-inference-control-plane.md`](../design/local-inference-control-plane.md) §5. The open work is in the [roadmap](../design/roadmap.md).

## 5. Milestones

**A note on the numbering.** M5 through M7 were each renumbered once as
lifecycle policy and second-host readiness were pulled forward, and the
`*(was …)*` tags record that. One further collision is worth stating
plainly: **"networked polish" has been M7, then M8, and is now M9**,
because the retained-metrics work took the number M8 from a candidate
list and was built, contracted and live-verified under it before this
document was updated. Everything shipped as M8 — the contracts in
`openapi/gateway.yaml`, `scripts/m8-acceptance.sh`, both M8 documents —
keeps that number. Only the unbuilt milestone moved.

- **M0 — one engine, end to end**
  ([acceptance](../acceptance/m0-four-process-run.md))**.** Supervise a single
  `llama-server` from config; a driver fronts it; `GET /v1/runtimes` reports
  it healthy; the gateway routes a chat completion through the driver to it;
  the UI shows it.
  Proves the whole chain — argv + lifecycle adapter + driver + routing — with
  exactly one backend. Load balancing arrives the moment there are two, which
  is why the layering has to be right *here* and not retrofitted later.
- **M1 — engine acquisition** ([design](../design/m1-engine-acquisition.md))**.** Detect
  platform + accelerator, fetch and verify the matching prebuilt llama.cpp
  release, surface the version, offer updates. Closes the one manual step M0
  leaves behind, and it's the increment that makes first-run one-click.
- **M2 — model library, both formats** ([design](../design/m2-model-library.md),
  [acceptance](../acceptance/m2-five-process-run.md))**.** Point
  at directories, scan GGUF *and* HF-safetensors models, edit per-model
  profiles, launch from the library.
- **M3 — discovery, download, guidance**
  ([design](../design/m3-discovery-download-guidance.md),
  [acceptance](../acceptance/m3-three-process-run.md))**.** Catalogue search, model
  detail, quant recommendations against detected hardware, resumable download
  into a user-chosen directory. Sequenced ahead of lifecycle policy
  deliberately: swap policy only matters once a user *has* several models, and
  getting models is the step that decides whether they stay.

  Two results from building the contracts are worth carrying forward. A
  remote GGUF's real metadata is readable over HTTP Range for ~11 MB —
  0.07% of a 16 GB file — so quant guidance is built on
  `general.file_type` rather than on a filename, the same standard M2 holds
  local models to. And **bits per weight** (`size × 8 / parameters`, both
  free from the hub) is the one number that makes three upstream quant
  naming schemes comparable; it is also the boundary of what we will say,
  because relative quant *quality* is upstream research and a fabricated
  score is worse than none.
- **M4 — second engine: vLLM** ([design](../design/m4-second-engine-vllm.md))**.** A
  second engine adapter — and, as it turns out, **not** a second driver kind.
  vLLM speaks OpenAI-compatible HTTP, so `openai_compat_http` already covers
  it: the wire-protocol half of the split needs nothing at all, and the
  engine half needs everything. That is the `EngineKind` / `BackendKind`
  separation earning its keep on the first case that tested it.

  Where the two-layer split stops being speculative is readiness. vLLM binds
  its port *before* loading the model and answers nothing until the model is
  resident, so for minutes it is indistinguishable over the network from a
  process that died — and `loading` versus `crashed` becomes decidable only
  from the process handle, which the supervisor has and a driver does not.
  Also where the M2 routing gap closes, since a driver following a runtime by
  name is what makes a launched model routable.

  **v0.1 drives a user-provided vLLM and does not manage its installation**
  (decided 2026-09-09) — the open question §6 carried, now settled.

  **Built 2026-09-09** (agent `53d815d`, inference-driver `97f6583`,
  gateway `5ad5993`) against upstream source at v0.29.0 and fixtures;
  **no vLLM process has run for this project yet.** The readiness rule
  above is code (`interpret_readiness` in the agent), the driver follows a
  runtime by `runtimeName`, and `scripts/m4-acceptance.sh` is written for
  the first Linux run and has never been executed. M4's design §8 has the
  implementation record and what that run must measure.
- **M5 — multi-host, trust, and the control root**
  ([design](../design/m5-multi-host-and-trust.md))**.** Inserted 2026-09-09 ahead of
  lifecycle policy, which pushed M5→M6 and M6→M7. The agent splits into a
  **control root** and a **node agent**; nodes get identity and enrollment;
  secrets are sealed per-node instead of under one install-wide master key;
  control state becomes a single-writer ordered log with a warm standby and
  operator-driven promotion, fenced by a monotonic epoch.

  It jumps the queue because a distributed trust model is expensive to
  retrofit and the current one caps the install at one host in a way that is
  easy to miss: multi-host is *designed* — the gateway resolves remote driver
  URLs from topology — but not *authenticable*, since a driver spawned by one
  agent rejects a token signed by another. Deliberately **not** Raft; the
  log shape is chosen so that consensus later would be a transport-and-election
  swap rather than a redesign.

  **Core built and live-verified**, with the agent-side enrollment and signed
  rekey integration completed at M7. The M5 five-process acceptance verified a
  completion after killing the control root. Actual two-machine partitions and
  offline-node rotation are still unverified; UI assets remain on the agent.
- **M6 — lifecycle policy** *(was M5)*
  ([design](../design/m6-lifecycle-policy.md),
  [acceptance](../acceptance/m6-six-process-run.md))**.** Swap on
  demand, idle unload, VRAM-aware admission, and **load balancing across
  drivers serving the same model** — testable for the first time now that
  N drivers exist. The llama-swap-without-Docker answer.

  **Built and live-verified 2026-09-10**, six processes and two
  llama.cpp replicas on one GPU. Decided to open it: a **companion
  inference-driver per runtime**, declared by the agent, so launch ends
  routable (M2's gap, closed for real); **the gateway decides lifecycle
  and the owning agent executes**, with the control root out of the
  path so swapping survives management being down; **nothing new is
  replicated** — `LogOp` stays at nine, the policy fields ride inside
  `RuntimeSpec`; **admission refuses with the arithmetic and a `force`
  override, never queues.** Every model is a slot whose tiers are model
  ids (a cloud subscription is a target like any other); within a tier,
  least outstanding requests weighted by `parallelSlots`. The live run
  found two defects the fixtures could not — a routing table a refresh
  interval behind about readiness, and 99 GPU layers read as partial
  offload — and both are fixed. Admission uses the agent's own live
  device detection, which also makes `GET /v1/node` real for the first
  time. Still on one card: two-GPU placement is unproven, same as the
  two-host question.
- **M7 — second-host readiness** *(was: networked polish, now M9)*
  ([design](../design/m7-second-host-readiness.md),
  [acceptance](../acceptance/m7-two-agent-run.md))**.** Make a second
  host possible before one exists: the agent's half of M5's enrollment
  (never built until now), an advertise address so a gateway elsewhere
  can reach a companion here, the gateway's fan-out proven over two
  agents, and a two-host acceptance script run against two agents on
  one box. **Built and live-verified 2026-09-10.** Decided to open it:
  the re-key is **signed by the control identity** rather than
  authenticated by a bearer, because a rotation invalidates every bearer
  and a re-run cannot know which key a node holds; the node **tells**
  the root where it is (derived from the route to the root, or set),
  the root never guesses from a source address; `Component.url` keeps
  its one meaning and `advertiseUrl` carries the other. Four defects the
  control repo's fake agents had agreed to are in the design's §0. What
  one box cannot prove is in its §10. **A real two-host run followed on
  2026-09-11** — a Windows host A and a WSL2 host B, NAT and a firewall
  between them, 41 checks and no component change
  ([acceptance](../acceptance/m7-two-host-run.md)) — which closes M5's
  largest gap and discharges the non-loopback-bind caveat outright.
- **M8 — retained request metrics**
  ([design](../design/m8-retained-request-metrics.md),
  [acceptance](../acceptance/m8-metrics-run.md))**.** The gateway keeps
  what it serves: per-request and per-attempt rows beside its config,
  `GET /v1/metrics{,/requests}`, a `/metrics` page, retention and
  rollup config. **Built and live-verified 2026-09-10.** It took this
  number from a candidate list rather than from this roadmap, which is
  why the milestone below moved — see the note under §5.

  Two results worth carrying. **The response envelope is the wrong
  recording point**: `x_eugene_plexus` was set in one place and the
  streaming path was not it, so a recorder hooked to the response would
  have been blind to every streaming client. `RoutingHooks` fires around
  every attempt on both paths and is the seam. And **two rows, not
  one**, because a request's total latency includes its failed attempts:
  a live cascade recorded a 2171ms failure then a 4189ms success out of
  a 6360ms request, so scoring the survivor by the total would have
  understated it by 34%.
- **M9 — networked polish: DONE, live-verified 2026-09-11** *(was M7,
  then M8)* ([design](../design/m9-networked-polish.md) §8 is the implementation
  record; [acceptance](../acceptance/m9-onboarding-run.md))**.** The auth
  arc driven **in a browser** for the first time, the wizard split one
  module per screen, [`tailnet deployment`](../deployment/tailnet.md)
  written down, `POST /v1/node/unenroll`, `PATCH /v1/nodes/{name}`, and
  the onboarding question of §4a — an interactive first-boot prompt,
  `eugene-plexus-agent join`, and a `/nodes` screen that mints a token
  and renders the command. `scripts/m9-acceptance.sh` passes 40 checks
  with **no pre-written `firstRunComplete`**, which is the bypass every
  script since M0 had been using in place of an onboarding feature that
  did not exist.

  **The defect scoping found is closed:** a node announced its address
  once, at enrollment, so a host that came back on a new one left the
  root holding a `Node.url` nobody was listening on — and the root could
  not poll its way out, because the only address it had was the stale
  one. It now announces on every start and every change, **signed with
  its own identity key**, mirroring the signed re-key in the other
  direction; a service token names a *kind*, not a host, and an
  unattended reboot has no operator to authenticate.

  **The defect the build found is larger, and was in the first-run path
  all along: the control host's own agent never enrolled.** M7 settled
  that every node enrolls the same way, the control host's included —
  every acceptance script does it, and the wizard did not. An unenrolled
  agent mints its own random signing key while the root mints the
  install's, so no browser session could reach the control root at all.
  Nothing had noticed because until M9 there was no control-root screen
  to open. `LogOp` also opened to ten (`updateNode`), for the reason its
  own description gives: applied state that mutates outside the set is
  state that would not replicate.
- **M10 — token streaming: DONE, live-verified 2026-09-11**
  ([design](../design/m10-token-streaming.md) §9 is the implementation record;
  [acceptance](../acceptance/m10-streaming-run.md))**.** Real token
  streaming through both layers, and the rule it cost: **failover is
  possible until the first token and impossible after it.** The gap was
  larger than the roadmap had carried — the gateway had been faking a
  stream as one content chunk for nine milestones, and every "is it
  streaming" check passed. This milestone took the number the next one
  had been given, which is why compute/storage separation is M11.
- **M11 — compute/storage separation: DONE, verified 2026-09-13**
  ([design](../design/m11-compute-storage-separation.md) §13 is the
  implementation record;
  [acceptance](../acceptance/m11-storage-separation-run.md))**.** The
  library names a model by its path on the library's host; a node that
  runs the engine elsewhere says where the same directory is mounted on
  its own disk (`pathMappings`, one setting on that node's agent), and
  the agent resolves the path at every spawn — never onto the
  declaration, so the runtime keeps linking to its library entry.
  Admission answers "is the model here at all" before "does it fit",
  refuses with the fix when it is not, and a worker with no library of
  its own reaches the install's through the owning node's agent. Plus
  the folder picker `path_list` had promised since M2, on both
  components that hold paths. **No transfer protocol and no node-side
  cache**, deliberately: the operator mounts the share; we map the
  path.

  Two results worth carrying. **The refusal everyone relied on did not
  exist**: the contract had promised a 400 for a missing model path
  since M0 and nothing implemented it, so a launch of a path the node
  did not have was accepted, given a companion driver, and crashed at
  spawn. And **a worker never consulted the library**: an enrolled node
  declares none, so every admission on the GPU node of the first
  two-machine install had been measured by file size, and nothing said
  so.
- **Then, as of 2026-09-17: not more milestones — a release-readiness order.**
  Everything built after M11 happened outside this list (the tree, Library
  folders, the hobbyist plan S0-S10, Issues, the node-local copy), and the
  pre-release adversarial review put eleven High findings in front of the
  release: **six slices before any public link (the review's eight fixes), five
  slices before the first hostile review, the Anthropic `/v1/messages` gap
  alongside, then the release gate — `hobbyist-ux.md` decision #13 plus #14,
  unchanged and not shortened.** The order is
  [`release-roadmap.md`](../design/release-roadmap.md); the evidence is
  `docs/private/adversarial-review-2026-09-17.md`. Still unscheduled and still
  wanted: the MLX adapter (built on a branch, blocked on upstream having no
  `--served-model-name`), cloud providers beyond the two CLI engines, and the
  Discord connector.

---
