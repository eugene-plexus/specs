# Speculative decoding and MTP

**Status: designed 2026-10-18; Troy took S1-S5 the same day. SD1 built 2026-10-18** (see "What building SD1 found"). SD2 is not built.

## Why

Four of the seventeen r/LocalAIServers setups reviewed on 2026-10-18 run
speculative decoding, mostly multi-token prediction (MTP). Their owners report
it nearly doubles decode speed: one 6xV100 rig went from 22.6 to 42.7 tok/s on
the same model. Eugene can't turn it on today except by typing raw engine
arguments into `extraArgs`. Strata is the exception: it already passes `--mtp`.

The Library already sees most of what this needs:
- `catalogue.py` classifies `mtp`/`draft` GGUF files in a model's folder as
  "launchable only as a `--model-draft`" and hides them from the picker.
- `preflight.py` reads `<arch>.nextn_predict_layers`, the GGUF key that says a
  model carries its own MTP head.

## What the engines take

Read off upstream source. llama.cpp at **b11719** (2026-10-18), vLLM at
**v0.32.0**.

**llama.cpp** (`common/arg.cpp`, `common/speculative.cpp`, `common/common.cpp`):

| Flag | Meaning |
| --- | --- |
| `--spec-type T[,T]` | `none` (default), `draft-simple`, `draft-eagle3`, `draft-mtp`, `draft-dflash`, `draft-dspark`, `ngram-simple`, `ngram-map-k`, `ngram-map-k4v`, `ngram-mod`, `ngram-cache` |
| `--spec-draft-model F` (`-md`) | A separate draft or MTP GGUF |
| `--spec-draft-n-max N` | Tokens drafted per step (default 3) |
| `--spec-draft-ngl N\|auto\|all` | Draft layers in VRAM (default auto) |
| `--spec-draft-device D,...` | Draft devices (default: follows `--device`) |

- `draft-mtp` without `-md` runs the MTP head **inside the main GGUF on the main
  model's weights** (`shares_model = !has_draft`). The extra memory is a small
  context, not a second model.
- With `-md` it loads a separate file.
- llama.cpp's own `--fit` sizes the draft together with the target
  (`common_fit_extra_model`).
- The `ngram-*` types need no model at all. They reuse text already in the
  context, which suits code edits.
- `llama-server`'s Prometheus `/metrics` reports
  `spec_decode_num_accepted_tokens_total` and acceptance per draft position.

**vLLM** (`vllm/config/speculative.py`):
- `--speculative-config '{"method": ..., "num_speculative_tokens": N}'`.
- `method: "mtp"` is the generic MTP method; model-specific names such as
  `qwen3_5_mtp` are normalised to it.
- `"ngram"` and `"suffix"` need no model. `"draft_model"` takes `"model": <path>`.
- The agent's vLLM adapter passes none of this today.

## The design

### Slice SD1, llama.cpp

1. **Library: say what a model can do.** Each GGUF model gains
   `speculation: {mtpHead: bool, draftFiles: [path]}`.
   - `mtpHead` comes from `nextn_predict_layers > 0`.
   - `draftFiles` are the MTP or draft GGUFs already classified in the same
     folder.
   - Like the projector, a draft file belongs to the model beside it.
2. **Profile: "Speculative decoding" (S2), two settings.**
   - **Reuse repeated text**, on or off, **on by default for every llama.cpp
     runtime** (S3). It adds `ngram-mod` to `--spec-type`, needs no file and
     proposes nothing when nothing in the context repeats.
   - **Draft with**: Off (default, S1), **Model's own prediction head**
     (`draft-mtp`, offered only when `mtpHead` is true) or **Companion file**
     (`draft-mtp` or `draft-simple` plus `--spec-draft-model F`, offered when
     `draftFiles` is not empty; the type comes from the file's own metadata).

   Both together launch as `--spec-type ngram-mod,draft-mtp`. llama.cpp tries
   the types in that order for each sequence (`common_speculative_draft`,
   b11719): a free n-gram match first, then the model. An expert field,
   "Tokens drafted per step", maps to `--spec-draft-n-max`. `extraArgs` keeps
   working and wins, as it does today.
3. **Agent: launch it.** Add to `_FLAG_CLI_NAMES`, and validate that the
   companion file is in the same Library model folder. A node's own model copy
   must copy the companion too: agent#10 found the same trap with split GGUF
   shards.
4. **Admission: count it.** A shared MTP head adds its context only. A separate
   draft adds its weights and KV cache. Measure both on the 5090 before trusting
   an estimate (S4).
5. **Show the acceptance rate.** Read the accepted-token counter from
   `llama-server`'s `/metrics` and show the rate on the run, as a fact. Eugene
   makes no recommendation from it (S3); the profile builder uses it.
6. **Profile builder.** Add "Draft with" as a trial dimension, so the builder
   measures tok/s both ways on this machine and keeps the faster one (S1).
   "Reuse repeated text" is not a trial dimension: its benefit depends on the
   person's own work, which a benchmark prompt can't stand in for.

### What building SD1 found

- **`nextn_predict_layers` does not tell a model with a head from a separate
  head.** ggml-org's `mtp-Qwen3.6-27B-Q4_0.gguf` declares
  `qwen35.nextn_predict_layers 1` and `block_count 65`, like a model, but
  holds 18 tensors: block 64 and the embeddings. The Library and the agent
  both use llama.cpp's own test instead
  (`common_speculative_types_from_gguf`): the last block has
  `nextn.eh_proj.weight`. With `blk.0.` as well, it is a model with its own
  head (`mtpHead`); without, it is a companion (`DraftKind.mtp`). The Strata
  `mtp-q2_0.gguf` has neither and stays as it was. A whole model counts as a
  companion only when it is named `draft-*`.
- **A companion pairs with every quant in its folder** of the same
  architecture and vocabulary size, since ggml-org ships one MTP file per
  repository. It is re-paired on every scan, because downloading it leaves
  the model's own file, and so its cache entry, unchanged. Its bytes are in
  `sizeBytes` but not in a fit's weights, like a projector's.
- **`--spec-type` appends.** A second one in `extraArgs` would be combined
  with ours, not replace it, so "extraArgs wins" means generating nothing
  when `extraArgs` or `env` sets any speculation flag.
- **The order is llama.cpp's.** `common_speculative_init` tries n-gram types
  before model drafts whatever order `--spec-type` lists them in.
- **The default must not break an older build.** llama-server exits on an
  argument it does not know. The adapter reads the build's `--help` (cached
  per binary, like `--load-mode`) and passes only the types it lists. A build
  whose help cannot be read gets no default; a way of drafting someone chose
  is still passed. What is left out is said on the run
  (`RuntimeSpeculation.note`).
- **The counters need `--metrics`.** llama-server's `/metrics` is off by
  default, so the adapter adds `--metrics` to any command line that
  speculates, `extraArgs` included. The agent reads the two counters every
  10 seconds while the runtime is ready, keyed to the process so a restart
  starts from zero.
- **Reusing repeated text is not free on these models:** 163-183 MiB of GPU
  memory on both Qwen3.5/3.6 runs (S4). Admission counts 256 MiB for it on
  every llama.cpp launch that does not turn it off.
- **llama-bench cannot speculate,** so the builder's "Draft with" trials run
  in llama-server, after `confirming`, on the confirmed candidate only, with
  "Reuse repeated text" off (a new phase, `drafting`). Each trial is one fixed
  384-token generation at the model's own sampling defaults. A way of
  drafting must beat Off by more than 3% to be saved.
- **The built profile's recorded speeds are still llama-bench's,** without
  drafting. `ProfileBuiltBy` gained nothing; the trials are on the build.
- **Discover offers the companion (library#13, built 2026-10-18).** A repo's
  `mtp-*`/`draft-*` GGUFs are `CatalogueModel.draftFiles`, a box beside the
  vision part, off by default with the smallest precision chosen. A version
  already on the disk names its `root` and `folder`, and the companion
  downloads alone into it. ggml-org also ships `dflash-*.gguf`, which
  llama.cpp b11719 takes as `draft-dflash`; Discover listed them as versions
  of the model, and now lists them under other files. Launching DFlash is not
  built.

### Measured on the 5090 (S4, 2026-10-18)

llama-server b11719, CUDA 13.4, `-c 32768`, slots automatic, f16 cache,
thinking off, seed 7, 512 tokens. "Prose" asks for an explanation and a short
class; "edit" asks for a 50-line file back with type hints added.
`docs/acceptance/sd1-speculative-decoding.md` has the run through the agent.

| Model | Drafting | GPU over none | Prose tok/s | Edit tok/s | Kept (prose, edit) |
| --- | --- | --- | --- | --- | --- |
| Qwen3.5-9B Q4_K_M (own head) | none | (6,730 MiB) | 211.5 | 213.1 | |
| | repeated text | +169 MiB | 210.3 | 249.3 | -, 36% |
| | own head | +961 MiB | 277.4 | 372.8 | 62%, 95% |
| | both | +1,170 MiB | 281.4 | 367.6 | 62%, 55% |
| Qwen3.6-27B Q4_K_M + ggml-org MTP Q4_0 | none | (20,838 MiB) | 70.0 | 69.7 | |
| | repeated text | +163 MiB | 69.1 | 87.4 | -, 36% |
| | companion | +2,979 MiB | 149.2 | 190.7 | 68%, 95% |
| | both | +3,129 MiB | 149.7 | 180.9 | 68%, 56% |

With both on, an edit ran slower than with the model's head alone (367.6
against 372.8 on the 9B, 180.9 against 190.7 on the 27B): it drafted about
400 tokens and kept about 230, where the head alone drafted about 220 and kept
almost all. On its own, reusing repeated text made the same edit 17-25%
faster. S3 keeps it on everywhere with no recommendation; the run shows the
rate, and this is one prompt each.

### Slice SD2, vLLM

The same settings map to `--speculative-config`, which takes **one** method:
- Model's own head: `{"method":"mtp","num_speculative_tokens":N}`.
- Companion: `draft_model`.
- Repeated text: `ngram`, used only when "Draft with" is Off. vLLM can't combine
  it with a model, so a chosen model wins, and the run says that n-gram is not
  in effect.

Accepted counts come from vLLM's own metrics. The live check runs in WSL2, and
it doubles as the overdue vLLM run on current Edge.

### Not in scope

- EAGLE3, DFlash and DSpark sidecars. Add them when a model the Library
  downloads ships one.
- Pairing a draft from a *different* Library model (S5).
- MLX: `draftModel` already exists there.

## Calls for Troy

| # | Question | Decision |
| --- | --- | --- |
| S1 | Default on or off? | **Taken 2026-10-18:** off until the profile builder has measured it on that machine, then whichever was faster |
| S2 | What the setting is called | **Taken:** "Speculative decoding", with "MTP" in its help text |
| S3 | Offer "Reuse repeated text" (n-gram)? | **Taken:** yes, **on everywhere** by default, with no recommendation when it isn't helping. Slot count was rejected as a signal: llama-server's default is auto (several slots), and one person's several agents fill slots just as several people do |
| S4 | Measure memory before shipping admission's estimate? | **Taken: yes.** One run on the 5090 with a model that has an MTP head, and one with a companion file |
| S5 | Drafting with a small, separate Library model (e.g. 0.6B for a 27B)? | **Taken:** later, as SD3. It needs a vocabulary match check across models |

## Acceptance

- **SD1:** a check that fails before the change. A real Qwen3.x GGUF with an MTP
  head runs on the 5090 with each choice:
  - decode tok/s with it on and off;
  - the acceptance rate the run shows;
  - admission's reservation compared with the GPU memory actually used;
  - one sabotage of the companion-file check.
- **SD2:** the same, against vLLM in WSL2.
