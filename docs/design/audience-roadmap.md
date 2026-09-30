# Audience roadmap

**Status: the order of work from 2026-09-30. Pickup: A1, PB1.**

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
| A2 | Profile builder, PB2: the page (ui, library `builtBy`, admission) | same | **After the UI theme work lands** (another assistant, 2026-09-30). Calls 5 and 6 are open |
| A3 | MoE-aware fit in the library, Discover, the starter set and admission's estimate, plus the **Low** preset | to write | Troy: a separate slice. M6 in the design says why: an 8 GB card is never offered the 30B-A3B that runs at 46 tok/s |
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
