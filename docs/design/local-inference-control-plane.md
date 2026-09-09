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
engines. We never ship one and never compete with them.

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

| Complaint (recurring, from the thread) | What's missing |
|---|---|
| "Q3_K_S vs 2Q_K_M? No one fucking knows." | Hardware-aware quant guidance |
| "Tired of tweaking llama.cpp settings for every different model." | Per-model settings profiles, in a GUI |
| "Couldn't use the models I already had on disk → uninstalled it." | Respect for the user's own files |
| "Let me just go to the dumpster fire UI that is HuggingFace… no search page with summaries, just an autocomplete list. Off to a real search engine." | In-app model discovery |
| "`ollama pull` takes away a lot of hugging face headaches… finding GGUF and working with HF, I wouldn't call it beginner friendly." | In-app download |
| "Can I run this on a server?" (asked three separate times) | Headless + networked + authenticated |
| llama-swap is good but "just run Docker" / "not a drop-in replacement" | Model swapping without a container runtime |

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
   round-robin; a priority-list cascade when a backend dies. Cloud
   subscriptions are just another backend — the surviving `claude_code_cli` and
   `codex_cli` engines mean **one endpoint over local models and the
   subscriptions the user already pays for.** Nothing in the field does this:
   llama-swap swaps *one* model at a time and no one load-balances replicas.
   This is what makes the platform useful past a single desktop.

---

## 3. Shape

Six live repos, becoming seven at M5. All three renames are **executed**:
`orchestrator` → `gateway` and `hemisphere-driver` → `inference-driver` on
2026-09-08, and `watchdog` → `agent` on 2026-09-09. Ports are inherited
where a retired component had one.

| Component | Repo | Port | Job |
|---|---|---|---|
| node agent | `agent` (was `watchdog`) | 8079 | **One per host.** Spawn/monitor engines by arbitrary argv; owns engine adapters (argv construction, readiness probe, config schema); local topology; log capture; safe mode. Still holds the trust root and serves the UI **until M5 extracts them** |
| control root | `control` (**new at M5**) | tbd | Trust root, install-wide topology, node registry, the replicated log, the UI. Exactly one active, plus warm standbys |
| gateway | `gateway` (was `orchestrator`) | 8080 | One OpenAI-compatible front door. Model → driver resolution, load balancing, priority-list failover, idle-unload triggers. **No backend knowledge.** |
| inference-driver | `inference-driver` (was `hemisphere-driver`) | 8081 | **One instance per backend.** Uniform surface over one heterogeneous engine; owns provider choice, model id, secrets, params, health |
| library | `library` | 8082 | The operator's own model directories: recursive scan (GGUF + safetensors), metadata, per-model launch profiles; catalogue search, resumable downloads, quant table, hardware fit scoring |
| ui | `ui` | — | Config editor, runtime dashboard, library browser, chat playground, logs |
| specs | `specs` | — | Contracts; consumers codegen from a pinned SHA as today |

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

| Knowledge | Owner | What it is |
|---|---|---|
| How to **start** an engine | supervisor | argv construction, working directory, readiness probe, curated flag schema |
| How to **talk to** an engine | inference-driver | wire protocol — `openai_compat_http`, `claude_code_cli`, `codex_cli`, all three of which already exist |

The supervisor publishes what's running (`GET /v1/runtimes`) for the UI
dashboard; the gateway builds its routing table from the agent topology plus
each driver's own config and health endpoints. "Components share schemas, not
code" stays intact — nobody imports anybody.

### Kill list

`memory`, `identity`, `coordinator`, `trainer`, `data`, `eval`, `inference`,
`cluster`. Archive, don't delete — the training arc is a coherent body of work
that may be revived as an optional add-on, and `data`'s HF-download and
manifest code is partially reusable by `library`.

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
- **M6 — lifecycle policy** *(was M5)*. Swap on demand, idle unload, VRAM-aware
  admission, and **load balancing across drivers serving the same model** —
  testable for the first time now that two engines and N drivers exist. The
  llama-swap-without-Docker answer. Admission depends on M5's
  `Node.accelerators` to know *whose* VRAM it is reasoning about.
- **M7 — networked polish** *(was M6)*. Re-verify the auth arc against the new
  topology, rewrite the wizard, document tailnet deployment. Now partly settled
  by M5, which moves auth to the control root.
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

| Decision | Date |
|---|---|
| Keep the Eugene Plexus name, org, and namespaces | 2026-09-08 |
| Strip in place — five surviving repos, history preserved | 2026-09-08 |
| Never ship an inference engine; wrap upstream instead | 2026-09-08 |
| Two layers: a routing gateway above N per-backend drivers. Never collapse them | 2026-09-08 |
| `orchestrator` → `gateway`; `hemisphere-driver` → `inference-driver` | 2026-09-08 |
| Lifecycle adapters (how to start an engine) live in the supervisor; wire protocol (how to talk to one) lives in the driver | 2026-09-08 |
| No reasoning-model refusal. Warn and adapt; never reject a model the user owns | 2026-09-08 |
| Manage engine binaries; don't make the user install llama.cpp first | 2026-09-08 |
| Library is multi-format at v0.1 — GGUF *and* HF safetensors, format is a data-model dimension | 2026-09-08 |
| Never commit the source thread's HTML (session tokens + relicensing); cite the permalink and an archive snapshot | 2026-09-08 |
| The user's model files stay in user-chosen directories; no content-addressed cache | 2026-09-08 |
| In-app discovery + download is required scope, not a convenience; downloads write plainly-named files into user-chosen directories | 2026-09-08 |
| Consciousness program retired, not paused | 2026-09-08 |
| v0.1 drives a user-provided vLLM; engine installation is managed for llama.cpp only. Driving is a first-class path — the refusal names the command, and discovery finds the operator's venv | 2026-09-09 |
| The agent splits into a **control root** and a **node agent** — two components, not one binary with a role flag. Supervision is per-host and there are N; the trust root, topology and UI are inherently one | 2026-09-09 |
| **Per-node sealing.** Secrets are sealed to the node that reads them, plus a passphrase-protected recovery recipient. No install-wide master key on every host | 2026-09-09 |
| **Warm standby, log-shaped — not Raft.** One writer, one ordered mutation path, monotonic index. Consensus later is a transport-and-election swap, not a redesign | 2026-09-09 |
| A control root is **never** marked `out` automatically. Promotion is an operator act, fenced by a monotonic epoch — automatic promotion without quorum is split-brain by definition | 2026-09-09 |
| A driver follows a supervised runtime by **name**, resolved through the agent topology — never a literal URL, because the agent owns the port | 2026-09-09 |
| Runtime states are defined by what they mean, not by how one engine reports them. For an engine that does not answer while loading, a live process that answers nothing *is* `loading` | 2026-09-09 |
