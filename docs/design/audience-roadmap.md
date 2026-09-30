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
- **Pickup, in order:**
  1. A3d, Low's smaller file offered after a build
     ([`moe-aware-fit.md`](moe-aware-fit.md) §1.5).
  2. PB2's remainder, not scheduled: the model's row saying so when fit
     places a built profile differently at launch (agent log capture plus a
     `Runtime` field), and Home's "make it faster" (call 6, later).

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
| A3 | MoE-aware fit in the library, Discover, the starter set and admission's estimate, plus the **Low** preset | [`moe-aware-fit.md`](moe-aware-fit.md) (calls A-C taken 2026-09-30; A3a and A3b built) | Troy: a separate slice. M6 in the design says why: an 8 GB card is never offered the 30B-A3B that runs at 46 tok/s |
| A4 | Mac / MLX out of experimental | [`mlx-engine-unverified.md`](mlx-engine-unverified.md), B1 | **Blocked on a physical Mac** |
| A5 | Tool-call repair for local models | to write | **Measure first:** how often a local model's tool call fails to parse. The failover thread warns that a truncated call can be valid JSON with a 200 |
| A6 | A chat screen beginners stay in, or a one-click Open WebUI through the apps registry | [`apps-and-spokes.md`](apps-and-spokes.md) | "Adequate", per the 2026-09-11 call. The chat spoke was restarted from Troy's 2026-09-24 brief |
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
