# Audience roadmap

**Status: the order of work from 2026-09-30.**
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
- **A6 is designed** ([design](chat-app.md), 2026-10-01). An app runs as
  the agent's OS account, which on a one-machine install reaches the root
  token key, so apps get an account of their own first (C1). Then chat v1,
  which is chat and web search (C2), and Open WebUI in the registry (C3).
  **Pickup: §7 of the design**, six calls for Troy, then C1's measurement.
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
| A6 | A chat screen beginners stay in, as an app in the registry, plus Open WebUI beside it | [`chat-app.md`](chat-app.md), on [`apps-and-spokes.md`](apps-and-spokes.md) | **Designed 2026-10-01.** Three calls taken: v1 is chat and web search; apps get an OS account of their own first (C1); Open WebUI after it (C3). Six calls open in §7 |
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
