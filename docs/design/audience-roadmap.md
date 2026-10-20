# Audience roadmap

**Status: the order of work from 2026-09-30, brought up to date 2026-10-19.**
- **Built 2026-10-18: SD1, [speculative decoding](speculative-decoding.md) for llama.cpp**
  ([record](../acceptance/sd1-speculative-decoding.md)). It came from two audience passes on
  2026-10-18: 17 setups from r/LocalAIServers (four run MTP), then YouTube benchmark creators.
  SD2 (vLLM) is designed, not scheduled; Discover offering MTP files is library#13. Next, in
  order:
  - **Owed, small:** nothing. Done 2026-10-18: host history, the second half of the sysadmin
    dashboards ([design](host-history.md), [acceptance](../acceptance/host-history.md), 6/6), the
    session-start issue check, and MR6b's rerun against the pinned components (111/111).
  - **MR8 built 2026-10-18:** memory suggestions after a measured harness
    ([measurement](../acceptance/m-memory-measurement.md): four starter models pass Troy's bar;
    [acceptance](../acceptance/mr8-suggestions-run.md), 30/30, two people), and
    `reasoning_effort: none` now turns a llama.cpp template's thinking off.
  - **The memory reshape is built, MV1 to MV7, except MV5b (2026-10-20).** MV7 (chat projects, with
    their notes, past chats and documents) is on Edge
    ([MV7a](../acceptance/mv7a-projects-run.md), 27/27; [MV7b](../acceptance/mv7b-project-documents-run.md),
    18/18), and so is MV6 (provenance, Still true? from changed documents, the tidy pass;
    [acceptance](../acceptance/mv6-provenance-run.md), 35/35). MV5b (Hindsight from the catalogue)
    passed its probe ([record](../acceptance/mv5b-hindsight-probe.md)) and is designed. It waits on
    Troy's call MV5b-C1: where pg0 keeps its data on Windows. Calls MV6-C1 to C5 and MV7-C1 to C5
    are Troy's to confirm, with their defaults built. What is next after the reshape is Troy's: the
    setups review and the candidates below.
  - **Before that, the reshape:** MV4 (Memory as an app) was built 2026-10-19.
    MV3 (learning and the write policy: per-model Off, Suggest or Keep automatically with
    Eugene's measured recommendation, Measure this model, the write policy Strict, Standard, Open
    or Custom, `remember` with receipts and Undo, Recently learned) is on Edge
    ([design](workbench-memory-v2.md) sections 27-39,
    [measurement](../acceptance/m-memory-measurement-mv3.md),
    [acceptance](../acceptance/mv3-learning-run.md)). No model meets Keep automatically's
    stricter bar yet, the cloud reference included. Its call MV3-C1 (Suggest judged on MR8's
    sets) is Troy's to confirm, with its default built; MV1-C1 is settled per model. MV2 (past
    chats) is on Edge ([acceptance](../acceptance/mv2-past-chats-run.md), 36/36 live), its
    call MV2-C1 Troy's to confirm. MV1 (long notes, procedures, tags, versions, notes chosen
    every turn) is on Edge ([acceptance](../acceptance/mv1-memory-run.md), 51/51 live). The
    memory research recommended reshaping Workbench's memory rather than replacing it, and
    Troy took all fourteen calls ([research and calls](memory-research-2026-10.md)).
  - **Business candidates, not scheduled:** a live vLLM run on current Edge (the last was
    2026-09-10, [record](../acceptance/m4-vllm-run.md)); vLLM installed from its official
    container image; a gateway load test at 1-256 concurrent streams, the evidence any Rust
    rewrite would need first.
  - **From the setups pass, not designed:** a hardware health readout (PCIe generation and
    width against the maximum, P2P, temperature, power cap); a Prometheus `/metrics` export;
    one model across machines through llama.cpp's `rpc-server`; TensorSharp as an
    experimental engine.
  - Job Sites slice 3, cross-site copy, stays deferred (Troy, 2026-10-13).
  - **From the creators pass (Troy, 2026-10-18: at the back of this list), not designed:**
    1. a benchmark that runs through the gateway, so llama.cpp, MLX, vLLM and Strata take
       the same test, with a concurrency sweep;
    2. a benchmark matrix (models x quants x context depths x engines x nodes), unattended,
       into one table;
    3. power during runs: GPU watts, tok/s per watt, joules per token, plus a wall-meter
       reading;
    4. a shareable benchmark card with the full provenance;
    5. a presentation view for recording;
    6. an opt-in public results dataset, which needs a privacy design.
- **Built since the v0.2.0 release:** A10, the website overhaul (2026-10-13); v0.2.1 to v0.2.3
  (2026-10-14 to 10-16); interactive content in Workbench, G1-G5
  ([contract](workbench-ui-browser-v1.md)); the
  [gateway operations dashboard](gateway-operations-dashboard.md); the
  [engine overview](engine-overview-layout.md); the People directory, external sign-in and
  shared accounts ([design](shared-accounts-and-sso.md)); Strata image preparation, experimental.
- **A9, JOB SITES: SLICES 1, 2 AND 2b.1-2b.4 WITH J14a AND J14b ARE BUILT
  (2026-10-08, [the last record](../acceptance/j14b-signed-calls-run.md)).**
  Each person's calls run as their own account, are signed with their own key,
  and commands run where an administrator allowed them. **The pickup is slice
  3, cross-site copy: designed, with calls J92-J99 waiting for Troy**
  ([design](job-sites-cross-site-copy.md)). Then the physical checks, a doc
  refresh and the release (Troy, 2026-10-08: the Job Sites roadmap finishes
  before the next release).
- **A9's first slice (2026-10-05;**
  [record](../acceptance/job-sites-run.md)**).** Slice 1 made
  central Workbench's four file tools work on a person's own machines outside
  the LAN:
  - a node-only public route, with the root's certificate pinned at join and
    no cloud in the path;
  - file-only sites with no address;
  - membership is not access: only a site's owner grants its tools;
  - a dev/production mode;
  - capability checks.

  The slice's session pushes the design commits.
- **Experimental engine support is the current design direction** (Troy,
  2026-10-04; [policy](experimental-engines.md),
  [Strata investigation](strata-engine.md)). Strata is the first candidate
  and stays explicitly experimental. The baseline is recognition,
  install/uninstall, start/stop, model switching and inference. Full fit
  estimates, automatic model conversion/tuning and feature parity with
  llama.cpp are not prerequisites. NInfer and imp illustrate the same
  category; their integrations are not built. **First Strata implementation is
  included in Edge; [verification](../acceptance/strata-engine-run.md). Real-model
  GPU validation remains.**
- **A1 (PB1) is built and accepted the same day**:
  [record](../acceptance/profile-builder-run.md), agent `2fcebf9`, control
  `7920bf9`.
- **A3a and A3b are built and pinned** (admission, and the library's
  MoE-aware fit): agent `9ac7b7e`, library `025847e`.
- **A3c's library half is built and shipped** (the starter set's MoE class):
  library `d6f4e6f`, pinned in both installers. Troy accepted the review's
  entry, Qwen3.6-35B-A3B, on 2026-09-30
  ([record](../acceptance/a3c-starter-moe-run.md)).
- **A3c's UI half is built and pinned** (ui `f185a85` / dist `f943f3b`,
  library `dc08842`; [record](../acceptance/a3c-ui-words-run.md)). A split
  says what sits where, and a MoE model's new profile starts at its
  experts-in-RAM context instead of llama.cpp's 4,096 floor.
- **A2 (PB2) is built and pinned** (ui `f487c74` / dist `694b134`, library
  `0d9f1f2`, contract `dc2f35d`; [record](../acceptance/pb2-profile-builder-page-run.md)).
  Troy took call 6: the button is on the model's profile page first. A
  browser built, saved and launched a profile, and the launched runtime's
  flags were the saved profile's.
- **A3d is built and pinned** (ui `f3bd294` / dist `e062f0c`;
  [record](../acceptance/a3d-smaller-file-run.md)): after a build at Low, a
  smaller file of the same model when the one on disk does not fit
  entirely. **A1, A2 and A3 are complete.**
- **A4 is built on GitHub's macOS runners and pinned** (agent `d197a7a`,
  library `6e22230`, gateway `e050c15`;
  [record](../acceptance/a4-macos-runner-run.md)). The runners expose
  Metal, so the real `mlx_lm.server` ran there on macos-14, -15 and -26.
  Seven defects were found and fixed: the Mac budget (75% where Metal
  allows two thirds, and blind to a changed wired limit), the device's
  name, an MLX recipe that could not run, a sealed root making engines
  routable on faith, and an MLX model's parameter count and chat template.
  **Untested, and no Mac will be rented for now (Troy, 2026-09-30):** a
  bare-metal GPU at a real size, a model near the working set, a reboot
  and a login, a second device through the firewall. MLX's `experimental`
  label is off on Troy's call; the UI now lists an engine where it can
  run instead of by that flag.
- **A5 is measured, and its one repair built**
  ([record](../acceptance/a5-tool-calls-measurement.md),
  [design](tool-call-repair.md)). Ten models, 314 answers, through
  llama.cpp, streamed and not. There was no broken JSON, no call left in
  text, and no cut-off call that looked whole. The starter set made no
  mistake of its own. The failure every client meets is the engine
  ignoring a named `tool_choice`. **The repair is built and pinned**
  (driver `53412d5`): structured output, where `"required"` does not
  work. A forced call through the driver went from 0 of 6 to 28 of 28
  across ten models, and tool-call ids are long now. MLX's `experimental`
  label is off (agent `05d88f8`, UI dist `e404b6b`). Troy writes the
  llama.cpp report himself: their policy forbids AI-written posts, and
  the evidence notes are in `docs/private/llama-cpp-report-notes.md`.
  **No rented Mac** (Troy, 2026-09-30).
- **A6 is designed** ([design](workbench.md), 2026-10-01). An app runs as
  the agent's OS account, which on a one-machine install reaches the root
  token key, so apps get an account of their own first (C1, with one log
  ingress any tool can send to). Then sign-in with Eugene (C2), the app's
  version 1, chat and web search (C3), and Open WebUI in the registry
  (C4). The app is **Workbench**.
- **C1 is built and pinned** ([record](../acceptance/c1-app-accounts-run.md)):
  on GitHub's Windows and Ubuntu runners, an app ran as LocalSystem or
  `eugene-plexus` and read `node.yaml`, the passphrase or keyring and the
  control root's files (14 failures on each). Now each app has an OS account
  of its own and reads nothing of the install but its own folder: 42 of 42
  on each. Its output reaches the Logs page through `POST /v1/logs`. Two
  installer defects were found on the way.
- **C2 is built and pinned** ([record](../acceptance/c2-sign-in-run.md),
  [design](sign-in-with-eugene.md)): the control root is an OpenID Connect
  provider that every agent forwards `/oidc` to. With nobody added an app
  asks for Eugene's passphrase; with people, each signs in with their own
  name and password, which the owner can turn off, reset or limit to some
  apps, and which they can change themselves at sign-in. An app that signs
  people in is registered at install and handed its secret; the console has
  a People page. 42 of 42 with a real OIDC client, 6 of 6 in Chrome,
  sabotage 46 of 46. The sign-in key is not rotated yet (design §10).
- **C3 is built and pinned** ([record](../acceptance/c3-workbench-run.md),
  [design](workbench-v1.md)). Workbench is the first app in the catalogue,
  a new repo, `eugene-plexus/workbench`. It reaches the hub only through
  the gateway's public doors with one key, and signs people in with Eugene.
  Version 1 is chat and web search, in plain words (Troy's call 1: *Tools*,
  not *Toolbox*):
  - an answer keeps going with no tab open (call 2);
  - whether the owner may read people's chats is a setting each business
    decides (call 3);
  - a session is a cookie plus a per-origin secret, because cookies cross
    ports;
  - an image an answer names is never fetched.
  `GET /v1/models` now says whether a search can run for the key, and
  why not. Results: 36 of 36 with Chrome, 34 of 34 live (a real 0.6B and
  the WSL SearXNG), sabotage 46 of 46.
  - **The live install found one defect after the pin**, fixed and pinned
    the same day (agent `5c456fe`, control `28ea3e3`). Installing an app
    from another machine's console signed the operator out: the worker
    sent the console's token past its audience to the root. Now the
    worker acts for the operator, and the root takes that only for the
    worker's own apps. The harness installs through a console hop now:
    37 of 37, sabotage 60 of 60.

  **C4 is built and pinned 2026-10-02**, Open WebUI in the registry
  ([record](../acceptance/c4-open-webui-run.md)). The previous C4 pickup
  below C3 was stale.

  **C5a is built 2026-10-03**, network MCP servers, a Toolbox screen,
  per-chat selection, approval for each call, saved results and honest
  interruption states ([record](../acceptance/c5-mcp-run.md)).
  **C5b is built and pinned 2026-10-03**, local MCP processes in the app's
  OS account ([record](../acceptance/c5-local-tools-run.md)). The operator
  provisions trusted executables; only the owner can select or start them.
  **C6 is built and pinned 2026-10-03**, built-in folder tools with
  person-specific grants, read-only by default and optional text writes;
  every call needs approval ([design](workbench-files.md),
  [record](../acceptance/c6-folder-tools-run.md)). Existing host folders
  need administrator-provisioned OS access. Local MCP programs remain
  owner-only. **The working animation is built and pinned 2026-10-07**
  (`workbench.md` §6.1). **Answer versions are built and pinned 2026-10-08**
  as a branching tree ([`workbench-answer-versions.md`](workbench-answer-versions.md)).
  **Media screens are designed, with Troy's calls taken 2026-10-08**
  ([`workbench-media-screens.md`](workbench-media-screens.md)): images
  first with the shared frame, then speech and transcription, then video.
  **Slice 1 (Images) is built and pinned 2026-10-08**
  ([record](../acceptance/workbench-media-images-run.md)). **Slice 2
  (Speech and Transcription) is built and pinned 2026-10-08**
  ([record](../acceptance/workbench-media-speech-run.md)). **Slice 3
  (Video, as a work order, M11) is built and pinned 2026-10-08**
  ([record](../acceptance/workbench-media-video-run.md)): priced from the
  provider's list before sending, the gateway's first money, and polled
  from the server through restarts. **All four media screens are built.**
  Local media engines still need their own admission design.
- Not scheduled without Troy: PB2's remainder (the model's row saying so
  when fit places a built profile differently at launch; Home's "make it
  faster", call 6, later).

This replaces [`adoption-roadmap.md`](adoption-roadmap.md) as the pickup
point. Its open physical and moderated checks still stand and are carried
below; nothing in it is reopened. P1–P8 and every slice CLAUDE.md records
up to 2026-09-30 are done.

## Where this came from

On 2026-09-30 Troy asked for a comparison with Unsloth (Desktop/Studio,
v0.1.811-beta). He then asked for that comparison to be filtered through
the saved Reddit threads that started the project, and said the result would
shape the next roadmap.
- The raw threads are in `docs/private/raw_reddit/`, gitignored because a
  saved page carries session tokens.
- The counts and the method are in the private memory
  `project_unsloth_audience_gaps`.

**What the audience asks for that Unsloth has and we don't, strongest
first:**
1. **Automatic load tuning.** T2's largest group of comments is settings,
   quants and fit (6 of 24 top-level). Unsloth is praised there for exactly
   this ("auto optimization saves hours", 22 and 15 points). T1 adds "tired
   of tweaking llamacpp settings for different models" (25).
2. **Mac / MLX.** Seven commenters, including a Mac Studio serving MLX to
   Hermes over the OpenAI endpoint (17), which is Eugene's shape.
3. **Tool calls that work with local models.** The looping-harness
   complaint (5 points) is blamed on Ollama and is mostly answered already.
   What remains is repair, and it is thinner than first stated.
4. **A chat screen beginners stay in.** The bar is low: several commenters
   call llama-server's own web UI enough.

**No recorded demand:**
- Fine-tuning. It is what people know Unsloth *for*: nine describe it, none
  ask for it, and three tell the beginner it isn't what they need yet.
- Local image, video and speech models.
- MCP and code execution.
- Multi-user accounts.

## The order

| # | Slice | Design | Notes |
|---|---|---|---|
| **A1** | **Profile builder, PB1: the job** (specs, agent) | [`profile-builder.md`](profile-builder.md) | Calls 1–4 are taken. Includes the shared ask-stop-restart step and moves R6.1's Benchmark onto it |
| A2 | Profile builder, PB2: the page (ui, library `builtBy`, admission) | same | **Built 2026-09-30.** Call 6 taken (the profile page); call 5 became moe-aware-fit call A, taken |
| A3 | MoE-aware fit in the library, Discover, the starter set and admission's estimate, plus the **Low** preset | [`moe-aware-fit.md`](moe-aware-fit.md) (calls A-C taken 2026-09-30; **A3a-A3d built**) | Troy: a separate slice. M6 in the design says why: an 8 GB card is never offered the 30B-A3B that runs at 46 tok/s |
| A4 | Mac / MLX out of experimental | [`mlx-engine.md`](mlx-engine.md) (A4 section), B1 | **Built on GitHub's macOS runners 2026-09-30**; the rented-Mac list is in the record, and dropping the `experimental` flag is Troy's call |
| A5 | Tool-call repair for local models | [`tool-call-repair.md`](tool-call-repair.md) | **Measured and built 2026-09-30.** Almost nothing to repair. The one repair, a named `tool_choice` answered by structured output on llama-server, is pinned |
| A6 | A chat screen beginners stay in, as an app in the registry, plus Open WebUI beside it | [`workbench.md`](workbench.md), on [`apps-and-spokes.md`](apps-and-spokes.md) | **C1–C6 built; C6 pinned 2026-10-03.** App accounts, Eugene sign-in, Workbench chat/search, Open WebUI, network/local MCP tools and person-specific folder tools with approval. Working animation built 2026-10-07; answer versions built 2026-10-08; media screens designed and built 2026-10-08 (Images, Speech/Transcription, Video as a work order) |
| **A7** | **The prompt cache: keep each engine's cache warm across doors, replicas and hosted backends** | [`prompt-cache.md`](prompt-cache.md) ([record](../acceptance/prompt-cache-measurement.md)) | **Troy, 2026-10-02: high priority before going public** (*"at the core of what Eugene is: managing multiple backends efficiently"*). Measured the same day; **PC1-PC5 built and pinned 2026-10-02** (Troy took the four calls: PC1-PC5 before public, affinity the default, the system-message fold an operator setting, client breakpoints only). PC6-PC7 after the release |
| **A8** | **Experimental engines, starting with Strata** | [`experimental-engines.md`](experimental-engines.md), [`strata-engine.md`](strata-engine.md) | **First Strata implementation on Edge 2026-10-04.** Recognition, install/uninstall, start/stop, model switching and text inference; [verification](../acceptance/strata-engine-run.md). Real-model GPU validation remains. The experimental label persists after hardware validation. NInfer and imp are subsequent candidates. |
| **A9** | **Job Sites, slice 1: Workbench's four file tools on a person's machines outside the LAN, with the new access model** | [`remote-nodes.md`](remote-nodes.md) §5 (every call, J1-J18, taken 2026-10-05) | **Built 2026-10-05** ([record](../acceptance/job-sites-run.md): 17 of 17 with the root behind WSL2's NAT, sabotage 45 of 45). Slice 2, 2b.1-2b.4, J14a and J14b built by 2026-10-08 ([J14b record](../acceptance/j14b-signed-calls-run.md)). Slice 3 (cross-site copy) designed 2026-10-08, calls J92-J99 for Troy ([design](job-sites-cross-site-copy.md)) |
| **A10** | **Website overhaul after v0.2.0**: every new feature described in full, new screenshots, updated install instructions and how-tos | deployed 2026-10-13 ([plan and findings](a10-website-overhaul.md)) | **Built.** The website deploys by manual `workflow_dispatch` |
| selected 2026-10-15 | AWS-style dashboards for system administrators, fleet and host telemetry over time | [Gateway dashboard built](gateway-operations-dashboard.md); host history remains separate | Troy selected Gateway Metrics after the engine overview; includes operations panels and varied dials. Host history built 2026-10-18 (Hosts page) |
| built 2026-10-18 | MR9 | [`workbench-memory-and-documents.md`](workbench-memory-and-documents.md) | MR8 built 2026-10-18 (harness, inbox, relevance, expiry and revisit). Order may change after Troy's setups review |
| then | **v0.3.0 release** (Troy, 2026-10-18) | `docs/maintenance/testing-and-release.md` | After MR9b. Release qualification on one candidate. The v0.1 data converters stay in v0.3.0 |
| done 2026-10-19 | Remove the v0.1 data converters, so v0.3.1 has none | memory `project_v020_release` | Shipped to Edge for v0.3.1. Old data is refused by name with the way out (start v0.3.0 once, then update) |
| done 2026-10-19 | **Memory research**: is Workbench's memory competitive, or should it be extended, reshaped or replaced? | [`memory-research-2026-10.md`](memory-research-2026-10.md) | **Reshape.** Keep the built-in store as the default, rebuild it on CoALA's four memory types, raise the limits, let any model the person allows keep notes under an owner-set write policy, index past chats, add tags with a master list, put one contract in front for optional backends (Hindsight first). Troy took all fourteen calls |
| built 2026-10-20 (MV5b waits on MV5b-C1) | **Memory reshape, MV1-MV7**: MV1 notes with bodies, procedures, tags and supersession, budgets scaled, relevant memory re-chosen each turn; MV2 past chats; MV3 learning and the write policy; MV4 Memory as an app; MV5 backends; MV6 provenance and tidy; MV7 projects | [`memory-research-2026-10.md`](memory-research-2026-10.md) §7, §10; slice designs in `workbench-memory-v2.md` (MV1 writes it) | Handoff `docs/private/handoff-memory-mv1.md`. MV1 includes a store migration and changes what models receive; MV3 changes who writes memory. Both are high risk: one adversarial review each and a real-environment run |
| candidate, after the setups review | **Connect an app on this machine** (Troy, 2026-10-19): a Workbench connection set up by the person's Job Site instead of a pasted command | not designed | The site's worker (the person's own OS account) finds the installed clients (Claude Code, Codex), writes their config with the client's own tool where one exists (`claude mcp add -s user`) or a merging edit with a backup (`~/.codex/config.toml`), and removes it on revoke. The token goes Workbench → worker → file, never through the browser. Approval like the folder tools. Open WebUI is configured by Eugene itself, no site needed. The copied setup stays the expert route. High risk (auth, writes in a home directory): one review and a real-machine run |

| candidate (Troy, 2026-10-20) | **Console experience pass, CX1-CX9**: folders scan on save, apps on a silent machine, plain engine status, setup that resumes, one-click run asks first, one context for fit, a Connect apps page, remove a machine, saves that restart say so, failures link to logs, models already in Ollama | [`console-ux-pass.md`](console-ux-pass.md) | Not Workbench (its own pass). **CX1 built and on Edge 2026-10-20** (ui `d3123b4`); CX2 next. CX2 and CX6 are high risk. CX-C1 (Machines or nodes) is Troy's |

## Not scheduled without Troy

- **The standby takes over by itself (Troy, 2026-10-20).** The goal is
  automatic takeover when the root is gone, not a Promote button. A
  complicated slice: it has to tell a dead root from a partitioned one,
  open the sealed material without a person typing the passphrase, and
  tell every agent the new root's address, which nothing carries today
  ([`warm-standby.md`](warm-standby.md), "Found, not fixed"). Until then
  promotion stays on the standby's command line.

- **The check pipeline and the secret filter.** The gateway runs each turn
  through an ordered list of checks, which the sysadmin arranges like
  Gateway → Routing. The hooks are free; the secret check is a separate
  commercial module, and Jessie's MSP is the free testbed. The shape is
  recorded in the private memory `project_secret_filter_msp`.
- **P7, Realtime.** Ask first, per the 2026-09-28 order.
- **The platform half of the OpenAI API:** files, batches, vector stores,
  fine-tuning. It is on the future roadmap and not relitigated.
- **Blueprints: a programming language with ML at its core (Troy,
  2026-10-18).** Harness workflows as visual programs, like UE5 Blueprints
  rather than ComfyUI. They have control flow (loops, if/else, subroutines,
  variables) and sub-agent definitions picked by `#tag`. Fast typed decisions
  (Jev, the `/v1/systemone` door) serve as branch conditions. Each sub-agent
  gets explicitly wired context. Blueprints are created, saved, shared and
  tuned per person.
  - **A tool of its own, independent of Workbench** (Troy). Workbench may run
    blueprints; it does not contain them.
  - **Prior art, partial:** Rivet, OpenAI's Agent Builder, LangGraph, Dify,
    n8n. None found that combines cheap typed decisions as branches,
    explicit context wiring, a tagged sub-agent registry, and a
    local-first, interactive harness.
  - **When it is picked up:**
    - Design the language first: the execution model, node types, scope,
      context wiring, and the file format the runtime executes. The editor
      and the debugger (live flow, breakpoints, watched variables) are
      views of it.
    - First proof: a hand-written blueprint driving a local 9B model on
      coding tasks, against the same model running free.

## Carried from the adoption roadmap

The physical and moderated checks listed in
[`adoption-roadmap.md`](adoption-roadmap.md) stay open. This roadmap
neither closes nor repeats them.

## Rules that bind every slice

- **Execute; don't re-verify** a dated finding. A slice starts with a check
  that fails before the fix.
- **Sabotage passes restore from a copy** and open with a baseline that
  passes.
- **Acceptance scripts clear the ambient `EUGENE_PLEXUS_*` environment**,
  use their own ports and folders, and never touch the live install.
  Stopping Amish_Station needs Troy's word each time.
- **Rebuild `dist` whenever the UI changes** and re-pin both installers.
- Commit straight to `main` with a DCO sign-off, and **stage by path**:
  another assistant may be working in the same checkouts.
