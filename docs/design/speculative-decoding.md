# Speculative decoding and MTP

**Status: designed 2026-10-18, calls S1-S5 waiting for Troy.** Nothing is built.

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
2. **Profile: one setting, "Speed up writing" (S2).** Choices:
   - **Off**.
   - **Model's own prediction head**: `--spec-type draft-mtp`, offered only when
     `mtpHead` is true.
   - **Companion file**: `--spec-type draft-mtp|draft-simple --spec-draft-model F`,
     offered when `draftFiles` is not empty. The type comes from the file's own
     metadata.
   - **Reuse repeated text**: `--spec-type ngram-mod`, always offered.

   An expert field, "Tokens drafted per step", maps to `--spec-draft-n-max`.
   `extraArgs` keeps working and wins, as it does today.
3. **Agent: launch it.** Add to `_FLAG_CLI_NAMES`, and validate that the
   companion file is in the same Library model folder. A node's own model copy
   must copy the companion too: agent#10 found the same trap with split GGUF
   shards.
4. **Admission: count it.** A shared MTP head adds its context only. A separate
   draft adds its weights and KV cache. Measure both on the 5090 before trusting
   an estimate (S4).
5. **Say whether it is working.** Read the accepted-token counter from
   `llama-server`'s `/metrics` and show the acceptance rate on the run. A low
   rate means the setting costs more than it gives, and the run should say so.
6. **Profile builder.** Add on/off as a trial dimension, so the builder measures
   tok/s both ways on this machine and keeps the faster one (S1).

### Slice SD2, vLLM

The same profile setting maps to `--speculative-config`:
- Model's own head: `{"method":"mtp","num_speculative_tokens":N}`.
- Companion: `draft_model`.
- Repeated text: `ngram`.

Accepted counts come from vLLM's own metrics. The live check runs in WSL2, and
it doubles as the overdue vLLM run on current Edge.

### Not in scope

- EAGLE3, DFlash and DSpark sidecars. Add them when a model the Library
  downloads ships one.
- Pairing a draft from a *different* Library model (S5).
- MLX: `draftModel` already exists there.

## Calls for Troy

| # | Question | Recommendation |
| --- | --- | --- |
| S1 | Default on or off? | Off until the profile builder has measured it on that machine, then whichever was faster. Many people at once on one runtime gain less from it, and only a measurement shows that |
| S2 | What the setting is called | "Speed up writing", with the choices above in plain words. "Speculative decoding" and "MTP" go in its help text |
| S3 | Offer "Reuse repeated text" (n-gram)? | Yes, off by default. It needs no file and helps code edits most |
| S4 | Measure memory before shipping admission's estimate? | Yes. One run on the 5090 with a model that has an MTP head, and one with a companion file |
| S5 | Drafting with a small, separate Library model (e.g. 0.6B for a 27B)? | Later, as SD3. It needs a vocabulary match check across models |

## Acceptance

- **SD1:** a check that fails before the change. A real Qwen3.x GGUF with an MTP
  head runs on the 5090 with each choice:
  - decode tok/s with it on and off;
  - the acceptance rate the run shows;
  - admission's reservation compared with the GPU memory actually used;
  - one sabotage of the companion-file check.
- **SD2:** the same, against vLLM in WSL2.
