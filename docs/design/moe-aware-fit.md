# MoE-aware fit: the library, admission, the starter set, and Low

**Status: designed 2026-09-30, not built. §0 is measured; §4 holds the
calls for Troy.** Roadmap: [`audience-roadmap.md`](audience-roadmap.md) A3,
a separate slice from the profile builder by Troy's call.

## §0 Measurements

All figures are from 2026-09-30, on the same files as
[`profile-builder.md`](profile-builder.md) §0.

**M1. How a MoE file splits.** Read from the tensor table only (header,
no weights), each tensor sized by the gap to the next offset:

| File | Data | Expert tensors | Everything else |
|---|---|---|---|
| Qwen3-30B-A3B Q4_K_M | 17.28 GiB | **16.35 GiB (94.6%)**, 324-374 MiB a layer over 48 | **0.93 GiB** |
| Qwen3-30B-A3B UD-Q3_K_XL | 12.88 GiB | 11.93 GiB (92.6%) | 0.95 GiB |
| Qwen3.6-27B Q4_K_M (dense hybrid) | 15.40 GiB | none | 15.40 GiB |

So a MoE model's attention, embeddings and routers are under a gigabyte.
A card that holds those plus the cache runs the model with the experts
in system memory, which llama.cpp's fit arranges by itself
(profile-builder §0 M2).

**M2. What that does to speed** (profile-builder §0 M4 and the PB1
acceptance runs, 5090 at an 8 GB margin):
- The MoE model decodes at **46.5-50.6 tok/s** with most experts in RAM.
- The dense 27B, spilled by whole layers, decodes at **4.9**.
- Expert offload beats layer offload by 39% at equal memory.

**M3. What the library says today, by execution** (`fit.compute` and
`max_context_that_fits` over each file's own shape, at 16k):

| File | 8 GB card, 16 GB RAM | 8 GB, 32 GB | 16 GB, 32 GB | 24 GB, 64 GB |
|---|---|---|---|---|
| 30B-A3B Q4_K_M | **`no`** (needs 19.8 GiB) | `split`, no context offered | `split`, none | `fits`, 56,832 |
| 30B-A3B UD-Q3_K_XL | `split`, none | `split`, none | `fits`, 17,408 | `fits`, 104,960 |
| 27B dense Q4_K_M | `split`, none | `split`, none | `split`, none | `fits`, 115,968 |

- **The same word, `split`, covers 46 tok/s and 4.9 tok/s.** The arithmetic
  treats every byte as needing the card, and it cannot say which model
  degrades gracefully.
- On T2's own laptop (8 GB and 16 GB of RAM), the MoE Q4_K_M is `no`.
- No context is offered on any card smaller than the whole file.

**M4. What admission does with `split` today, by execution:**
- **A profile with `gpuLayers` unset scored `split` is refused.**
- The same model with an explicit `gpuLayers: 20` is admitted.
- `wants_full_offload` reads unset as "the whole model on the card". That
  was true before llama.cpp's `--fit`. Every build the installers ship has
  `--fit on` by default (b10948 and later were checked), so today unset
  means "llama.cpp places it", and llama.cpp does run the model partly in
  RAM.
- **This blocks PB2.** A profile the builder saves leaves `gpuLayers`
  unset on purpose, so it would be refused at launch on exactly the cards
  where the builder found it runs.

## §1 What changes

1. **Admission: unset `gpuLayers` means llama.cpp places it** (call A).
   - Where the selected build's help lists `--fit`, and the profile does
     not pass `--fit off`, a llama.cpp profile with unset `gpuLayers` is
     treated as a partial offload the engine arranges.
   - `split` and `tight` are admitted with the arithmetic shown; `no`
     (more than VRAM plus RAM) is still refused.
   - This is an agent-only change with no contract change. It replaces
     profile-builder call 5, "admission trusts a built profile's measured
     memory": a built profile launches by the general rule, not by an
     exception.

2. **The library reads the tensor table.**
   - It is a few kilobytes after the key-value block, and the rule
     "never a tensor, never the weights" stands, because it reads names,
     shapes and offsets only.
   - The scan records `expertBytes` beside the file size.
   - The remote preflight (HTTP Range) already refetches when a buffer
     ends early (`GgufTruncated`), so a longer header costs one more
     round trip at most.

3. **Fit knows where a MoE model's bytes can go.**
   - For a model with experts: the card needs the non-expert part, the
     cache and the overhead, and system memory takes whatever experts do
     not fit on the card.
   - The verdict keeps its five words. Beside it, a new named field says
     how a `split` would run: `offload: experts | layers`.
   - A second context number answers "how long can it be with the experts
     in RAM": `maxContextExpertsInRam` (the non-expert part plus cache on
     the card).
   - **No speed is predicted.** Prediction is a filter; the profile builder
     measures. The words tell a person which kind of split this is, and
     the builder puts numbers on it.

4. **The starter set can suggest a MoE model to a small card** (call B).
   - Where RAM allows, a MoE model whose non-expert part and cache fit on
     the card is a candidate beside models that fit entirely.
   - The file gains a MoE class; `starter-review` learns `expertBytes`.

5. **Low, the fourth accuracy level** (call C, and profile-builder call 1).
   - Its lever is a smaller file of the same model.
   - After a build, if a smaller quant of the same repository would move
     the frontier (more of the model on the card at the chosen context),
     the page offers it with Download and rebuild.
   - The build cannot download mid-run, and does not.

## §2 Contract

**`library.yaml`:**
- `GgufInfo.expertBytes` (null for a dense model or one scanned before
  this).
- `Fit.offload`, with a named enum `FitOffload` whose values are
  `experts` and `layers`.
- `Fit.maxContextExpertsInRam`.

Consumers: library and ui codegen `library.yaml`. The agent reads fit over
HTTP and gains nothing it must parse. **Nothing in `agent.yaml` changes**,
because call A is logic.

## §3 Slices

| Slice | Repos | Needs `ui`? |
|---|---|---|
| **A3a** Admission reads unset as "llama.cpp places it" | agent | no, so it can go before PB2 |
| **A3b** Tensor table, `expertBytes`, `offload`, `maxContextExpertsInRam` | specs, library | no |
| **A3c** The starter set's MoE class and Discover's words for the two kinds of split | library, ui | yes, after the theme |
| **A3d** Low: a smaller file, offered after a build | ui, library catalogue | yes, with PB2 |

## §4 Calls for Troy

| # | Call | Recommendation | Against it |
|---|---|---|---|
| A | Treat unset `gpuLayers` as "llama.cpp places it" in admission | **Yes.** It is what the engine does, and PB2 cannot ship without it. `no` still refuses | A dense model too big for the card now launches and runs slowly (4.9 tok/s on 8 GB) instead of being refused. The verdict's words and the builder are what say so |
| B | The starter set may suggest a MoE model with experts in RAM to a small card | **Yes, when RAM allows.** On 8 GB it is the difference between a 4-8B model and a 30B one at a similar speed | It changes starter decision #4 ("runs entirely in GPU memory") and makes the recommendation depend on RAM too |
| C | What Low allows | **A smaller file of the same model, offered after a build, plus the 4-bit cache at ≥ 88% same top token** | Two levers in one level; Low could be the file only |
