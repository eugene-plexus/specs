# Local-inference control plane (design)

**Status:** direction change, decided 2026-09-08. **Supersedes the consciousness
program entirely** — the functional-region architecture, the continuous-loop
runtime (`retired-continuous-runtime.md`), and the NT/identity/memory stack are
retired, not paused. Also retires the local-LLM-*training* platform arc
(`coordinator`/`trainer`/`data`/`eval`/`inference`/`cluster`, June 2026) as the
headline direction.

**What it is:** a self-hosted control plane for local LLM inference. It
supervises engine processes it does not own, manages a model library on the
user's own disk, holds per-model settings profiles, exposes one
OpenAI-compatible endpoint that routes across local runtimes and cloud
providers with failover, and serves a web UI with real auth so it works over a
tailnet — not just localhost.

**What it is not:** an inference engine. llama.cpp, vLLM and MLX are the
engines. We supervise upstream, not fork or replace it. llama.cpp and
user-installed vLLM are integrated; MLX has no adapter yet.

**Reading this record (updated 2026-09-10):** the motivation and original work
list below describe the direction change. M0-M3 and M6 are live-verified; M5's
core and M7's enrollment/addressing integration are built. M7 used two agents on
one host, not two machines. M4's vLLM launch, browser acceptance and real
multi-host failure testing remain outstanding. See the milestone implementation
records and the [current overview](../../README.md#current-status), rather than
treating an original future-tense work item as today's implementation status.

---

## 1. Why this exists

The evidence is the r/LocalLLaMA reaction to "Friends Don't Let Friends Use
Ollama" (2026-09-07, 1.1k points, 93% upvoted, 355 comments) —
`reddit.com/r/LocalLLaMA/comments/1wa26pn/friends_dont_let_friends_use_ollama/`,
linking `sleepingrobots.com/dreams/stop-using-ollama/`. **Take a web-archive
snapshot; do not commit the thread HTML** (a saved copy carries the reader's own
Reddit session tokens, and republishing a full thread with usernames isn't ours
to relicense). Strip out the tribalism and the *unanswered* complaints are all
operational, not engine-level:

| Complaint (recurring, from the thread)                                                                                                               | What's missing                             |
| ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| "Q3_K_S vs 2Q_K_M? No one fucking knows."                                                                                                            | Hardware-aware quant guidance              |
| "Tired of tweaking llama.cpp settings for every different model."                                                                                    | Per-model settings profiles, in a GUI      |
| "Couldn't use the models I already had on disk → uninstalled it."                                                                                    | Respect for the user's own files           |
| "Let me just go to the dumpster fire UI that is HuggingFace… no search page with summaries, just an autocomplete list. Off to a real search engine." | In-app model discovery                     |
| "`ollama pull` takes away a lot of hugging face headaches… finding GGUF and working with HF, I wouldn't call it beginner friendly."                  | In-app download                            |
| "Can I run this on a server?" (asked at least six separate times — recounted 2026-09-11; it is the thread's single most repeated question)            | Headless + networked + authenticated       |
| llama-swap is good but "just run Docker" / "not a drop-in replacement"                                                                               | Model swapping without a container runtime |

Nobody owns this layer. Everyone builds an *engine* (llama.cpp, vLLM, MLX) or a
*desktop chat app* (LM Studio, Unsloth Studio, llama.app). The boring middle —
supervise, configure, route, authenticate — is unclaimed.

**Honest framing:** Ollama's persistence is a distribution problem, not a
technical one. llama.cpp already beats it on merit and still loses the
recommendation slot in Google's AI answers and in LLM output. Being
technically better is table stakes, not a strategy.

---

## 2. The differentiators

Each maps to a row in the table above. Nothing here is aspirational framing —
these are the product.

1. **It supervises engines it doesn't own.** Engines are upstream projects,
   tracked and wrapped, never forked or replaced.
2. **Discovery and download happen in the app.** Search a model catalogue,
   read what a model *is*, pick a quant, download it with resume and progress —
   without leaving for HuggingFace's search box and a manual file copy. This is
   the one thing `ollama pull` genuinely got right, and it is *why* people
   tolerate everything else about it. **Necessary, not a convenience.**
3. **The user's files stay theirs.** Point it at existing GGUF directories, and
   downloads land *in those same directories as plainly-named files*. No
   content-addressed cache, no hash mismatches, no opaque store. **Non-negotiable.**

   These two are in obvious tension, and resolving it correctly is the whole
   trick: **acquisition is a convenience layer over a plain filesystem, never a
   managed store.** `ollama pull` was right; the blob cache behind it was wrong.
   A user must be able to delete us and still have their models, correctly
   named, where they chose to put them.
4. **Schema-driven config UI with per-model profiles.** Every knob is a form
   field with help text, defaults and conditional visibility, generated from
   the config schema the component already publishes.
5. **Networked-first with auth.** The v0.2 security arc (Argon2id master key,
   libsodium envelopes, JWT bearer, OS keyring) is already built and is
   exactly what the "run it on a server" crowd lacks.
6. **Hardware-aware quant guidance,** on the discovery screen. Detect VRAM/RAM,
   read model metadata, recommend a quant tier, warn *before* a 40GB download
   that won't fit — and show *why*. Guidance and discovery are the same screen:
   the moment a user is choosing between `Q3_K_S` and `2Q_K_M` is the moment
   they need to be told which one their box can actually run.

7. **Many backends at once, load-balanced, with failover.** Several models
   resident simultaneously; two replicas of one model across two GPUs served
  by outstanding requests and capacity; a priority-list cascade when a backend dies. Cloud
   subscriptions are just another backend — the surviving `claude_code_cli` and
   `codex_cli` engines mean **one endpoint over local models and the
   subscriptions the user already pays for.** Nothing in the field does this:
   llama-swap swaps *one* model at a time and no one load-balances replicas.
   This is what makes the platform useful past a single desktop.

---

## 3. Shape

Seven active repos as of M7, including `control`. All three renames are **executed**:
`orchestrator` → `gateway` and `hemisphere-driver` → `inference-driver` on
2026-09-08, and `watchdog` → `agent` on 2026-09-09. Ports are inherited
where a retired component had one.

| Component        | Repo                                         | Port                   | Job                                                                                                                                                                                       |
| ---------------- | -------------------------------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| node agent       | `agent` (was `watchdog`)                     | 8079                   | **One per host.** Component/engine supervision, adapters, local topology, admission, enrollment, logs and safe mode. Still serves UI assets; enrolled nodes use the install's signing key |
| control root     | `control` (added at M5)                      | 8083                   | Trust root, install-wide topology, node registry and replicated log. Exactly one active, plus warm standbys. Spawns nothing; UI ownership remains undecided                               |
| gateway          | `gateway` (was `orchestrator`)               | 8080                   | One OpenAI-compatible front door. Model → driver resolution, load balancing, priority-list failover, idle-unload triggers. **No backend knowledge.**                                      |
| inference-driver | `inference-driver` (was `hemisphere-driver`) | 8081                   | **One instance per backend.** Uniform surface over one backend; owns provider choice, model id, secrets, protocol and health. Request parameters come from the gateway                    |
| library          | `library`                                    | 8082                   | The operator's own model directories: recursive scan (GGUF + safetensors), metadata, per-model launch profiles; catalogue search, resumable downloads, quant table, hardware fit scoring  |
| ui               | `ui`                                         | 3000 dev / 8079 served | Config editor, runtime dashboard, library, discovery/downloads, playground and logs; control types/proxy exist, dedicated control screens do not                                          |
| specs            | `specs`                                      | —                      | Contracts; consumers codegen from a pinned SHA as today                                                                                                                                   |

The **node agent** was called the *watchdog* through M0–M4, and the old
name is still what appears in the acceptance-run records, which are
transcripts and were deliberately left alone. `agent` is the name because
there is one per host reporting to a central authority — the sense Consul,
Nomad, Datadog and Puppet all use it in — and because the name it replaced
was a survivor of the anatomical scheme (it was the *medulla*) rather than
a description of the job.

### Two layers: a gateway above N drivers

The gateway does **not** wrap backends. One `inference-driver` runs per backend
and owns everything backend-specific. The gateway sits above them owning only
*routing*.

Collapsing both into a single process was the first sketch and it was wrong
(corrected 2026-09-08). It would have cost:

- **Load balancing and concurrency.** Two replicas of one model across two
  GPUs, or a small fast model and a large one serving at the same time, both
  need N independently-configured backends with something above them.
- **Multi-host placement.** A driver belongs *next to its engine*. As separate
  processes, a driver runs on the remote GPU host and the gateway reaches it
  over the tailnet. That is the entire multi-host story — and it is what makes
  "GPUs in different buildings" a supported topology rather than a wish.
- **Non-HTTP backends.** `claude_code_cli` and `codex_cli` are *subprocess*
  engines with no endpoint to proxy to. Something has to front them with HTTP,
  and that something is the driver — so the driver must be able to sit in the
  request path regardless.

The extra local hop is sub-millisecond against a multi-second generation. It is
not a cost worth optimising away.

### Where engine knowledge lives

Two different kinds of engine knowledge, in two places, no duplication and no
shared library:

| Knowledge                    | Owner            | What it is                                                                                             |
| ---------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------ |
| How to **start** an engine   | supervisor       | argv construction, working directory, readiness probe, curated flag schema                             |
| How to **talk to** an engine | inference-driver | wire protocol — `openai_compat_http`, `claude_code_cli`, `codex_cli`, all three of which already exist |

The supervisor publishes what's running (`GET /v1/runtimes`) for the UI
dashboard; the gateway builds its routing table from the agent topology plus
each driver's own config and health endpoints. "Components share schemas, not
code" stays intact — nobody imports anybody.

### Kill list

`memory`, `identity`, `coordinator`, `trainer`, `data`, `eval`, `inference`.
The original list also named `cluster`, but no such repository exists.
Retain, don't delete — the training arc is a coherent body of work
that may be revived as an optional add-on, and `data`'s HF-download and
manifest code is partially reusable by `library`.

These seven repos are retired in project scope, not GitHub-archived. On
2026-09-10 the operator chose to keep archive flags unchanged while labeling
their descriptions and README introductions. `connector` remains deferred.

**`orchestrator` survives** (moved off the kill list 2026-09-08). It is already
the thing that sat above N drivers and routed to them, so it is the gateway's
natural home: rename it, delete `bicameral/` and `runtime/`, and keep the auth
wiring, config trio, agent-topology peer resolution, SSE streaming and the
driver priority-list plumbing. Real reuse, not just history.

`connector` is **deferred, not killed**: "expose your local model in Discord" is
a real differentiator that already works, and reviving it is cheap once the
gateway is stable.

Chat history for the playground stays browser-side for the first pass. If
durable multi-device history is wanted later, `memory`'s `local_sqlite` backend
comes back stripped of person-keying and NT snapshots.

---

## 4. New work

Everything not listed here already exists and mostly survives untouched.

1. **Arbitrary-argv supervision.** The supervisor currently spawns
   `sys.executable -m <module>` from a fixed kind→module map
   (`supervisor.py:105`). Engines need argv, working directory, and per-engine
   readiness semantics.
2. **Engine adapters.** llama.cpp first: argv from a *curated* flag surface
   (llama-server has far too many flags to expose wholesale), `/health` probe,
   config schema, capability flags.
3. **`GET /v1/runtimes`** on the supervisor — what's running, where, with which
   model, and what it can do.
4. **Gateway routing** (in the renamed `orchestrator`). Model → driver
   resolution, **load balancing across drivers serving the same model**, idle
   unload, swap-on-demand, VRAM-aware admission. The OpenAI surface, peer
   resolution and the failover design already exist; load balancing is new.
5. **Library, multi-format from the start** (decided 2026-09-08). Format is a
   dimension of the data model, not an assumption: **GGUF** (single file, quant
   tiers) and **HF safetensors** (multi-file repo, no quant tier) are both
   implemented at v0.1, with MLX conversions reserved. *Local:* directory scan,
   metadata read, per-model profiles. *Remote:* catalogue search against the HF
   API, model detail, resumable download with progress and cancel, writing
   plainly-named files into user-chosen directories. Plus the quant table +
   hardware fit scoring — which stays **GGUF-specific, correctly**, since quant
   tiers are a GGUF concept; safetensors models are sized, not tiered.
6. **Engine acquisition** (decided 2026-09-08: manage binaries, don't make the
   user install them). Detect platform + accelerator, fetch the matching
   prebuilt llama.cpp release, verify it, surface the version, offer updates.
   This makes engine releases a **third managed artifact** alongside models and
   configs. Honest asymmetry: llama.cpp ships prebuilt binaries and is
   tractable; **vLLM is a Python package needing a CUDA-matched wheel and its
   own venv, is Linux-first and has no Metal path.** v0.1 therefore *manages*
   llama.cpp and *drives* vLLM from a user-provided install — see the open
   question in §6.
7. **UI.** Library browser, per-model profile editor, runtime dashboard. Delete
   the bicameral rail, consciousness stream, identity and connector panels.
8. **Specs.** New contracts for the above; delete the consciousness schemas.
9. **Drop the reasoning-model refusal rule.** The old rule had drivers *refuse*
   temperature-rejecting models at construction — correct for a consciousness
   that needed temperature control, wrong for a control plane whose job is
   routing to whatever the user owns. Mostly already true in code: the
   rejection list at `providers.py:82` is empty and `engines/_thinking.py`
   already implements the accommodate-don't-refuse path. Warn and adapt, never
   reject.

---

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
- **M1 — engine acquisition** ([design](m1-engine-acquisition.md))**.** Detect
  platform + accelerator, fetch and verify the matching prebuilt llama.cpp
  release, surface the version, offer updates. Closes the one manual step M0
  leaves behind, and it's the increment that makes first-run one-click.
- **M2 — model library, both formats** ([design](m2-model-library.md),
  [acceptance](../acceptance/m2-five-process-run.md))**.** Point
  at directories, scan GGUF *and* HF-safetensors models, edit per-model
  profiles, launch from the library.
- **M3 — discovery, download, guidance**
  ([design](m3-discovery-download-guidance.md),
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
- **M4 — second engine: vLLM** ([design](m4-second-engine-vllm.md))**.** A
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
  ([design](m5-multi-host-and-trust.md))**.** Inserted 2026-09-09 ahead of
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
  ([design](m6-lifecycle-policy.md),
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
  ([design](m7-second-host-readiness.md),
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
  ([design](m8-retained-request-metrics.md),
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
- **M9 — networked polish** *(was M7, then M8)*
  ([design](m9-networked-polish.md))**.** Re-verify the auth arc
  against the new topology **in a browser**, rewrite the wizard,
  document tailnet deployment, un-enroll and re-advertise. **This is the
  next milestone** (Troy, 2026-09-11): it is the only remaining item
  that blocks a differentiator — #5, networked-first with auth, whose
  crypto is built and proven process-to-process but whose browser path
  has never been driven against the current topology. **Scoping it found
  a defect:** a node announces its advertise address once, at
  enrollment, and nothing re-announces it — so a host that comes back on
  a new address leaves the root holding a stale `Node.url` while the
  gateway, which prefers `advertiseUrl` and falls back only when it is
  *absent*, routes to a dead URL with no error anywhere.
- **Then:** MLX adapter, cloud providers back in the routing table, Discord
  revival.

---

## 6. Risks

**Settled 2026-09-09 (was the open question here): v0.1 drives a
user-provided vLLM and does not manage its installation.** The reasoning
moved to [M4's design](m4-second-engine-vllm.md) along with the install
matrix it rests on, and the shape of the problem was not what this section
guessed. CUDA-version matching — the thing named here as the hard part — is
the easy part, because the default wheel bundles its own CUDA build and
`--torch-backend=auto` selects it, so we would never match a version at
all. What is actually hard is that the unit of installation is *a Python
environment*: an interpreter of a version we do not control (specifically
3.12 for the ROCm and Intel wheels), several GB per retained copy, three of
six targets on a non-default package index, Apple silicon served by a
separate project, and no single digest that verifies the result.

So engine acquisition stays **llama.cpp only**, and "we drive vLLM" is made
a first-class path rather than an absence of one: the refusal names the
exact command for the detected host, and discovery finds the operator's
venv. Rejected on the way: managing a venv on Linux + NVIDIA alone, which
is genuinely tractable and would have made the one accelerator on the one
OS behave differently from every other target.


- **llama.cpp is moving into this space.** `llama.app` is, in the thread
  author's own words, "a first baby step in that direction." If upstream ships
  good multi-model management, the core shrinks to routing + library + auth +
  guidance. Still a product — but plan for it rather than being surprised.
- **The recommendation slot is the whole game,** and it's won by SEO and
  mindshare, not merit. See §1.
- **The name doesn't help.** "Eugene Plexus" was chosen to signal consciousness
  research; keeping it (decided 2026-09-08) means the tagline, README and
  domain copy have to carry all of the "what it does" load that a descriptive
  name would have carried for free.
- **Curated flag surfaces need maintenance** as upstream engines churn.
- **Dev/prod platform mismatch.** Development is Windows; the audience is
  overwhelmingly Linux and macOS. The existing CI-vs-devenv lesson applies with
  more force now that we're spawning third-party binaries.

---

## 7. Locked decisions

| Decision                                                                                                                                                                                                         | Date       |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| Keep the Eugene Plexus name, org, and namespaces                                                                                                                                                                 | 2026-09-08 |
| Strip in place — five surviving repos, history preserved                                                                                                                                                         | 2026-09-08 |
| Never ship an inference engine; wrap upstream instead                                                                                                                                                            | 2026-09-08 |
| Two layers: a routing gateway above N per-backend drivers. Never collapse them                                                                                                                                   | 2026-09-08 |
| `orchestrator` → `gateway`; `hemisphere-driver` → `inference-driver`                                                                                                                                             | 2026-09-08 |
| Lifecycle adapters (how to start an engine) live in the supervisor; wire protocol (how to talk to one) lives in the driver                                                                                       | 2026-09-08 |
| No reasoning-model refusal. Warn and adapt; never reject a model the user owns                                                                                                                                   | 2026-09-08 |
| Manage engine binaries; don't make the user install llama.cpp first                                                                                                                                              | 2026-09-08 |
| Library is multi-format at v0.1 — GGUF *and* HF safetensors, format is a data-model dimension                                                                                                                    | 2026-09-08 |
| Never commit the source thread's HTML (session tokens + relicensing); cite the permalink and an archive snapshot                                                                                                 | 2026-09-08 |
| The user's model files stay in user-chosen directories; no content-addressed cache                                                                                                                               | 2026-09-08 |
| In-app discovery + download is required scope, not a convenience; downloads write plainly-named files into user-chosen directories                                                                               | 2026-09-08 |
| Consciousness program retired, not paused                                                                                                                                                                        | 2026-09-08 |
| v0.1 drives a user-provided vLLM; engine installation is managed for llama.cpp only. Driving is a first-class path — the refusal names the command, and discovery finds the operator's venv                      | 2026-09-09 |
| The agent splits into a **control root** and a **node agent** — two components, not one binary with a role flag. Supervision is per-host and there are N; the trust root, topology and UI are inherently one     | 2026-09-09 |
| **Per-node sealing.** Secrets are sealed to the node that reads them, plus a passphrase-protected recovery recipient. No install-wide master key on every host                                                   | 2026-09-09 |
| **Warm standby, log-shaped — not Raft.** One writer, one ordered mutation path, monotonic index. Consensus later is a transport-and-election swap, not a redesign                                                | 2026-09-09 |
| A control root is **never** marked `out` automatically. Promotion is an operator act, fenced by a monotonic epoch — automatic promotion without quorum is split-brain by definition                              | 2026-09-09 |
| A driver follows a supervised runtime by **name**, resolved through the agent topology — never a literal URL, because the agent owns the port                                                                    | 2026-09-09 |
| Runtime states are defined by what they mean, not by how one engine reports them. For an engine that does not answer while loading, a live process that answers nothing *is* `loading`                           | 2026-09-09 |
| **A companion inference-driver per runtime, declared by the agent** — not a declared pool. One driver per backend is the M0 rule; a runtime is a backend                                                         | 2026-09-10 |
| **The gateway decides lifecycle policy; the owning node's agent executes; the control root is not in the path.** Idle unload and start on demand are data-path behaviours and must survive management being down | 2026-09-10 |
| **Nothing about lifecycle is replicated.** Loaded/unloaded is liveness, re-read from agents after a promotion; `LogOp` stays closed at nine; the policy fields ride inside `RuntimeSpec`                         | 2026-09-10 |
| **Admission refuses with the arithmetic and a `force` override; it never queues.** `unknown` never refuses                                                                                                       | 2026-09-10 |
| **Every model is a slot; a slot's tiers are model ids, not driver names.** A model id names its replica set; a cloud subscription is a target like any other                                                     | 2026-09-10 |
| **A driver whose runtime is not `ready` is not routed to**, and a request that finds nothing eligible refreshes the table before concluding anything                                                             | 2026-09-10 |
| **The re-key is signed by the control identity, not authenticated by a bearer.** A rotation invalidates every bearer; the identity key does not rotate                                                           | 2026-09-10 |
| **The node tells the root where it is.** `advertiseUrl`, configured or derived from the route to the root; the root records it and never guesses from a source address                                           | 2026-09-10 |
| **`Component.url` keeps one meaning** (what the agent binds and probes); `Component.advertiseUrl` is where peers reach it. Engines are never widened                                                             | 2026-09-10 |
| **The install's signing key is stored in the clear on each node**, 0600. Children already hold it; a headless node has nobody to type a passphrase                                                               | 2026-09-10 |
| **Every node enrolls the same way**, the control host's included. One mechanism                                                                                                                                  | 2026-09-10 |
| **A desktop UI is no longer a differentiator; the networked story is.** The product's claim is the server — headless, tailnet, authenticated, many backends at once                                              | 2026-09-11 |

**Note on the row above (2026-09-11).** When §1 was written the
desktop-app alternatives were LM Studio and Ollama's own UI, and "a
schema-driven config UI with per-model profiles" read as scarce.
It is not scarce any more: **llama.app and Unsloth Studio are now the
answers the community recommends** to someone who wants a local model
with a good interface, and both are better funded and more focused on
that single job than we will be. §6 already flagged llama.cpp moving
into this space as a risk; the recount above is the other half of the
same observation, and together they move the weight of the pitch.

What this changes: differentiator #4 (schema-driven config, per-model
profiles) and the UI generally are now **table stakes** — necessary,
insufficient, and not what to lead with. What it does **not** change is
the scope; those screens still have to exist and still have to be good.
What to lead with instead is the part no desktop app can answer, and
that the source thread asked for more often than anything else:
**#5 networked-first with auth, #7 many backends at once with failover,
and multi-host** — one endpoint over the machines and subscriptions a
user already has, reachable from anywhere on their tailnet. That is
also the half we have just proven on real hardware (M4, M7), and the
half a desktop chat app is structurally unable to follow us into.
