# Audience roadmap

**Status: the order of work from 2026-09-30.**
- **▶ A9, JOB SITES SLICE 1, IS BUILT (2026-10-05;**
  [record](../acceptance/job-sites-run.md)**). The pickup is slice 2: MCP
  between site and root (J6) and site-final policy (J8).** Slice 1 made
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
| **A9** | **Job Sites, slice 1: Workbench's four file tools on a person's machines outside the LAN, with the new access model** | [`remote-nodes.md`](remote-nodes.md) §5 (every call, J1-J18, taken 2026-10-05) | **Built 2026-10-05** ([record](../acceptance/job-sites-run.md): 17 of 17 with the root behind WSL2's NAT, sabotage 45 of 45). Then slice 2 (MCP between site and root, site-final policy) and slice 3 (cross-site copy) |
| later | AWS-style dashboards for system administrators, fleet and host telemetry over time | to write | Troy: lower priority than A1–A6; sysadmins are the longer-term audience |

## Not scheduled without Troy

- **The check pipeline and the secret filter.** The gateway runs each turn
  through an ordered list of checks, which the sysadmin arranges like
  Gateway → Routing. The hooks are free; the secret check is a separate
  commercial module, and Jessie's MSP is the free testbed. The shape is
  recorded in the private memory `project_secret_filter_msp`.
- **P7, Realtime.** Ask first, per the 2026-09-28 order.
- **The platform half of the OpenAI API:** files, batches, vector stores,
  fine-tuning. It is on the future roadmap and not relitigated.

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
