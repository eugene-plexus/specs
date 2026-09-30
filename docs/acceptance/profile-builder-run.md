# PB1 acceptance: the profile builder's job

**2026-09-30.** `scripts/pb1-profile-builder-acceptance.py` drives a
disposable agent over HTTP, with its own port and folder and every ambient
`EUGENE_PLEXUS_*` variable dropped. It uses the real llama.cpp tools and
real models. Design: [`../design/profile-builder.md`](../design/profile-builder.md).
Roadmap: A1.

Across both runs the harness exercised the builder's promises:
- It asks before stopping.
- It stops only what was agreed, with reason `measurement`, and holds
  other launches during the build.
- It measures quality on the model and applies the accuracy level's rule.
- Placement comes from fit and is measured with the placement passed
  explicitly.
- It confirms the result in llama-server.
- It restarts what it stopped.
- It refuses a short custom text with its count.
- Its history survives an agent restart.

## Run 1: CPU, Qwen3-1.7B Q8_0, Medium (b11254 `win-cpu-x64`)

The live install kept serving throughout; every GPU was hidden from the
tools. A second runtime of the same model was really serving first, so the
ask-stop-restart path ran against a real process.

**The first execution passed, and its numbers showed a design flaw.**
- Each candidate had been measured at half its own context. The 4k and 8k
  rungs read 23.5 and 20.8 tok/s and every rung from 16k up read 16.7, so
  the build suggested 8k.
- All five rungs placed identically (`-ngl -1`), so a longer context
  costs nothing until it is filled. The numbers measured depth, not
  settings.
- **Fixed:** every candidate is now measured at one common depth of 2,048
  tokens, and speeds within 3% count as equal.

The second execution passed with the fix:

| Context | Decode (tok/s) | At 2,048 deep (tok/s) | Frontier |
|---|---|---|---|
| 4,096 | 27.4 | 23.5 | no |
| 8,192 | 27.2 | 23.6 | no |
| 16,384 | 27.0 | 23.0 | no |
| 32,768 | 27.2 | 23.2 | no |
| **40,960** (trained max) | 27.1 | 23.6 | **yes, suggested, confirmed** |

**Quality on this model:**
- 8-bit cache: 97.23% ± 0.18 same top token, KLD 0.0031. It passes
  Medium.
- **4-bit cache: 71.29% ± 0.50, KLD 0.392.** It fails Medium.

That is the lowest 4-bit figure measured on any of the three models
(93.1% for the 30B-A3B and 96.0% for the 27B, both on wikitext). It is
the strongest single argument for measuring on the user's own model. This
run cannot separate the model from the CPU backend's quantised-cache path.

Build time: 483 s, including the 8- and 4-bit quality runs.

## Run 2: RTX 5090 at an 8 GB margin, Qwen3-30B-A3B Q4_K_M, High (b11215 CUDA+Vulkan)

Setup:
- The live Amish_Station service was stopped for the run, with Troy's
  agreement, and restarted after.
- The profile pinned `devices: CUDA0`, as §0 did.
- A 1.7B GPU runtime served first, and was stopped and restarted.

The run passed on its first execution, in 369 s.

| Context | Placement (fit's, first terms) | Decode | At 2,048 deep | Frontier |
|---|---|---|---|---|
| 4,096 | `-ngl 49`, experts of 17-48 on the CPU | 50.3 | 49.0 | no (8k is as fast, and longer) |
| 8,192 | `-ngl 49`, experts of 16-48 | 48.4 | 48.3 | yes |
| 16,384 | `-ngl 49`, experts of 13-48 | 46.0 | 45.4 | yes |
| **32,768** | `-ngl 49`, experts of 9-48 | 41.2 | 40.7 | **yes, suggested, confirmed** |
| 65,536 | `-ngl 47`, experts of 3-48 | 33.9 | 32.6 | yes |
| 131,072 | `-ngl 24`, experts of 26-48 | 27.9 | 23.6 | yes |
| 262,144 | `-ngl 12`, experts of 38-48 | 25.5 | 20.8 | yes |

- **§0 M4 is reproduced through the agent.** Fit offloads experts, and
  each doubling of context moves more of the model off the card: 49.0
  tok/s at 4k against 32.6 at 64k.
- **The suggestion follows the rule.** 32k is the longest context keeping
  80% of the fastest frontier speed (40.7 of 48.3).
- **The confirmed load used 7.78 GiB** of the 5090, against a fit target
  of about 6.8 GiB (30.4 GiB free minus the 23,499 MiB margin). **Fit
  undercounts by about 1 GiB here**, more than the 240-610 MiB §0 saw with
  bare binaries. A real 8 GB card would be tighter than this run.

**A finding that bears on call 2: at High, the 8-bit cache was refused.**
- On the bundled text it scored **96.32% ± 0.21** same top token, KLD
  0.0054. On wikitext in §0 it scored 97.29% ± 0.13.
- With the boundary rule (96.11 < 96.5) High refused it, so every
  candidate was f16.
- The same cache clears High on one text and fails it on the other. **The
  bundled text is harder than wikitext for this model**, and High's
  threshold sits between the two.
- Nothing is changed. It is recorded for Troy (call 2 was taken at
  96.5%).

**An instrument defect, and it is fixed.** The "8-bit is faster at 64k"
check passed with no 8-bit candidate to compare: a guard skipped the
comparison and the line still printed PASS. It now asserts when 8-bit was
allowed, and prints `NOT CHECKED` when the level refused it. Run 3
exercises it.

## Run 3: the same, at Medium

Same model, card, margin and device pin; no busy runtime. It passed on
its first execution, in 667 s, and measured 14 candidates.

**Quality:**
- 8-bit cache: 96.32% ± 0.21. It passes Medium's 92%.
- 4-bit cache: **88.40% ± 0.35**, KLD 0.074. It fails Medium. On wikitext
  in §0 it scored 93.1%, so again the bundled text is the harder one.

| Context | f16: at 2,048 deep | q8_0: at 2,048 deep | On the frontier |
|---|---|---|---|
| 4,096 | 49.7 | 49.7 | neither (8k is as fast, and longer) |
| 8,192 | 48.4 | 48.8 | both, in this run (see below) |
| 16,384 | 45.3 | 46.9 | q8_0 |
| 32,768 | 40.8 | 44.6 | q8_0 |
| **65,536** | 32.9 | **39.8** | **q8_0, suggested, confirmed** |
| 131,072 | 23.8 | 30.7 | q8_0 |
| 262,144 | 20.7 | 22.7 | q8_0 |

- **The 8-bit check ran and passed.** At 64k the 8-bit cache keeps two
  more layers' experts on the card (`-ngl 49 … blk.8` against f16's
  `-ngl 47 … blk.3`) and decodes 21% faster. This is §0 M4 reproduced
  through the agent.
- **The suggestion is 64k with the 8-bit cache,** at 39.8 tok/s, 82% of
  the fastest frontier speed (48.8). At High (Run 2) the same model was
  given 32k with f16, because High refused the 8-bit cache.
- **At the 8,192 row, f16 and q8_0 ran at the same speed within 3%** and
  both stayed on the frontier, where the smaller cache buys nothing but a
  quality cost.
  - The more precise cache now dominates at an equal context and speed.
  - This was added after the run: a unit test uses this run's exact
    numbers, and a sabotage entry proves the test catches its removal.
  - The suggestion is unchanged, because at 64k the two caches differ by
    21%.

## Sabotage

`scripts/pb1-sabotage.py` breaks twenty-one of the builder's promises, one
at a time, and runs the builder, benchmark, adapter and benchmark-argument
tests after each. **21 of 21 were caught.** Files are restored from a copy
taken first, and the run opens with a baseline that passes. The broken
promises:
- **Measurement:** placement sent to llama-bench through `-fitc` (M3's
  trap), the warm-up turned off, and candidates measured at half their own
  context.
- **Choosing:** the quality boundary rule dropped, the speed tolerance
  removed, the precision tie-break removed, an identically-placed smaller
  cache kept, a cache allowed after failing the level, and Max running the
  quality step.
- **Stopping and restarting:** a shutdown restarting models, a build that
  never restarts, a model nobody agreed to being stopped, an agreed stop
  recorded as an operator stop, a refused benchmark leaving its stops
  stopped, and a running build not holding launches.
- **Tools and parsing:** a tool lacking an option accepted, a quantised
  cache served without flash attention, and the GGUF reader not skipping
  an array.
- **Other:** the missing work folder (a defect the unit tests found), a
  short text's count not recorded, and a candidate llama-server could not
  load still being recommended.

## Not covered

- **A real 8 GB card, a laptop CPU, or 16 GB of RAM.** The 8 GB rows come
  from a margin on a 5090 with a 16-core desktop CPU, so every offloaded
  number is an upper bound.
- **Two GPUs, Vulkan, AMD or a Mac.**
- **The UI** (PB2), so no person has used this yet.
- **The live install.** Its agent is not pinned to this build until the
  pins land.
