# Row 17: DFlash and EAGLE3 draft sidecars

Lane ENG, low risk. Builds on SD1 (`speculative-decoding.md`). Starts after row 18 merges, because row 18 owns the library's `formats/gguf.py` (lane order puts 18 first). No store migration.

## 1. What it delivers

- **Discover offers the drafter.** ggml-org's `dflash-*.gguf` (and any `dspark-*` or `eagle3-*` file) is offered as a drafting part beside the MTP file. Today the catalogue lists it under other files, with no way to get it as a companion (`_OTHER_DRAFTER_RE`).
- **The Library pairs it with the model it was made for,** by the file's own header, and lists it in `draftFiles` with its kind. Today a DFlash file on disk does not pair (its architecture is `dflash`, not the model's) and is read as a model that cannot run alone. The first test pins down today's behaviour.
- **The launch uses the right type.** "Draft with: Companion file" passes `--spec-type draft-dflash`, `draft-dspark` or `draft-eagle3`. Today the agent reads a DFlash file as a whole model and would pass `draft-simple`.
- **A drafter made for another model is refused before launch,** naming both shapes. llama.cpp would otherwise abort (EAGLE3: "target layer id exceeds target n_layer") and the supervisor would restart it into the same wall.
- **The settings builder times it** like any companion, and keeps it only when it beats Off by more than 3% (SD1).
- **The run says so:** "Drafting with DFlash (dflash-Qwen3.6-27B-Q8_0.gguf) · 61% of drafted tokens kept".

## 2. The design

### What llama.cpp takes (master, read 2026-10-21)

- `--spec-type` takes `draft-eagle3`, `draft-dflash` and `draft-dspark` (all in b11719).
- **The file says what it is:**
  - `general.architecture` is `dflash` or `eagle3`. DSpark is a `dflash` file with a `markov_w1.weight` tensor.
  - Both carry `<arch>.target_layers` and `<arch>.target_hidden_size`. DFlash also carries `dflash.block_size` (16 when absent).
- **llama.cpp infers `dflash` and `dspark` from the file, never `eagle3`.** Eugene always passes the type.
- **DFlash drafts at most `block_size − 1` tokens a step.** `--spec-draft-n-max` is clamped to that.
- **EAGLE3 needs exactly 3 target layers.** An id above the target's layer count aborts the server.
- **Eugene never passes `--spec-default`.** It turns on a set the build chooses, which can change between builds, so the run could not say what is in effect. In `extraArgs` it counts as set by hand.
- **`--dflash` and `--eagle3` only download with `-hf`.** Eugene does not use `-hf`.

### Contract (`openapi/library.yaml`), additive

```yaml
DraftKind:
  type: string
  enum: [mtp, simple, dflash, dspark, eagle3]
  # dflash/dspark/eagle3: a drafter bound to a target model by its header
  # (general.architecture, <arch>.target_layers, <arch>.target_hidden_size);
  # --spec-type draft-dflash, draft-dspark, draft-eagle3.
CatalogueFile:
  properties:
    draftKind:
      oneOf: [{$ref: '#/components/schemas/DraftKind'}, {type: 'null'}]
      description: >
        For a file in CatalogueModel.draftFiles, its kind by its name prefix
        (mtp-, draft-, dflash-, dspark-, eagle3-). The scan reads the header
        after the download, and the header decides.
```

- `run-operations.json` embeds `DraftKind`: regenerate it.
- `agent.yaml`: the `DraftWith` description says "by the file's own header: `draft-mtp`, `draft-simple`, `draft-dflash`, `draft-dspark` or `draft-eagle3`". This is text only, so the agent is not re-pinned.

### Library

- **`formats/gguf.py`.** Keep `<arch>.target_layers` (`keep_arrays`). Note a `markov_w1.weight` tensor (`has_markov_head`). `draft_kind()` returns `dflash`, `dspark` or `eagle3` by architecture, whatever the file's name. A file of these architectures is never a model.
- **`scanner.py`, `_with_drafts`.** MTP and simple drafts pair by the same architecture, as today. A drafter of the new kinds pairs with a model when all of these hold:
  - `target_hidden_size` equals the model's `<arch>.embedding_length`;
  - every target layer id is below the model's `block_count` (EAGLE3: at most equal);
  - the vocabulary sizes are equal, when both are known.

  The name (`dflash-<model>-<precision>`) is not used to pair.
- **Skip details** (reason `draft`):
  - "DFlash drafter (draft-dflash) for speculative decoding with the model beside it";
  - "DFlash drafter (draft-dflash), but no model it was made for is beside it: it needs hidden size 5120 and at least 64 layers".
- **`catalogue.py`.** `_DRAFT_RE` gains the `dflash`, `dspark` and `eagle3` prefixes, and `_OTHER_DRAFTER_RE` goes. Each draft file gets `draftKind` from its prefix.

### Agent

- **`gguf_context.py`.** `DraftingFacts` gains `architecture`, `embedding_length`, `target_layers`, `target_hidden_size`, `block_size` and `markov_head`. `companion_type` checks the architecture first (`draft-dflash`, `draft-dspark`, `draft-eagle3`), then today's rule.
- **`engines/speculation.py`.**
  - `TYPES` gains the three types, so `offered_types` reads them from `--help`. A build without one gets the note: "This llama.cpp build does not offer drafting with DFlash (draft-dflash), so it is off. Updating the engine turns it on."
  - `plan()` checks a bound drafter against the model's own facts. A mismatch raises: "dflash-Qwen3.6-27B-Q8_0.gguf was made for a model with hidden size 5120 and at least 64 layers. Qwen3.5-9B-Q4_K_M.gguf has 4096 and 32. Choose a companion made for this model." The runtime does not start, and this is its failure line.
  - `_BY_HAND_FLAGS` gains `--spec-default` and `--spec-draft-hf`. `_BY_HAND_ENV` gains `LLAMA_ARG_SPEC_DEFAULT`, if the build's help lists it.
- **Tokens drafted per step.** Measure first (section 5). If llama.cpp's default of 3 caps DFlash at 3 tokens, the adapter passes `--spec-draft-n-max <block_size − 1>` when the profile leaves the field unset. The editor then shows the value in effect: "Default: 15 for this DFlash file".
- **Admission** counts the file's size plus `DRAFT_CONTEXT_BYTES`, as for any companion. If the measurement differs by more than 256 MiB, add a DFlash allowance in `admission.py`. Row 9 owns `admission.py`, and row 9 merges before this row.
- **The builder needs no change.** `drafting_ways` uses `companion_type`, so the new kinds in `draftFiles` are timed.

### UI

- **`lib/speculation.ts`.**
  - The companion picker labels each file by kind: "(MTP head)", "(draft model)", "(DFlash)", "(DSpark)" or "(EAGLE3)".
  - `TYPE_WORDS` gains "DFlash", "DSpark" and "EAGLE3", each shown with the file name, as MTP is.
- **`app/discover/page.tsx`, `DraftPairing`.**
  - The files are grouped by `draftKind`, with one box per kind: "Also get the MTP head" and "Also get the DFlash drafter".
  - Each box is off by default, with the smallest precision of its kind chosen.
  - The help line: "DFlash proposes up to 15 tokens at once. It needs llama.cpp b11719 or newer."

### Failures

Each failure names its cause:
- the mismatch above;
- the older build's note;
- the existing line for a file that is not a readable GGUF.

An abort nobody predicted shows the log tail on the run, as CX8 does.

### Defaults

- "Draft with" stays Off until the builder times it (S1).
- Discover's boxes are off.
- Nothing deletes data, and no chat is kept anywhere new.

## 3. Repositories and files

- **specs:**
  - `library.yaml`, `run-operations.json`, and the `agent.yaml` description;
  - `speculative-decoding.md`: "What building row 17 found", and remove "EAGLE3, DFlash and DSpark sidecars" from "Not in scope".
- **library:** `formats/gguf.py`, `scanner.py`, `catalogue.py` and their tests. Regenerate from `library.yaml`.
- **agent:** `gguf_context.py` and `engines/speculation.py`. `admission.py` changes only if the measurement calls for it.
- **ui:** `lib/speculation.ts`, `app/discover/page.tsx` and their tests. Regenerate `library.ts` and `run-operations.ts`.
- **Codegen consumers:** library implements the change and ui uses it. The gateway generates `library_models.py` but reads none of this, so it is not re-pinned. The agent does not generate from `library.yaml`.

## 4. Tests that fail before the change

- **library `tests/test_scanner_drafts.py::test_dflash_pairs_with_its_target`.** A folder holds a synthetic `qwen35` model (embedding 5120, 64 blocks) and a synthetic `dflash` file (`target_hidden_size` 5120, `target_layers` [1, 20, 40, 63]). The scan finds one model, whose `draftFiles` holds one file of kind `dflash`, and the DFlash file is skipped as `draft`. Today the scan lists two models and pairs nothing.
- **Library, also:**
  - `test_dflash_for_another_model_is_not_paired` (hidden size 4096);
  - `test_markov_head_is_dspark`;
  - `test_eagle3_layer_equal_to_block_count_pairs`;
  - catalogue `test_dflash_offered_as_draft_file`, which replaces today's assertion that DFlash is in `otherFiles`.
- **agent `tests/test_speculation.py::test_dflash_companion_launches_as_draft_dflash`.** The argv holds `--spec-type ngram-mod,draft-dflash --spec-draft-model <file>`. Today it holds `draft-simple`.
- **Agent, also:** `test_companion_for_another_model_is_refused_naming_sizes`, `test_build_without_dflash_says_so` and `test_spec_default_in_extra_args_is_by_hand`.
- **ui (Vitest):** the labels, and Discover's two boxes.

## 5. Acceptance

Low risk, so there is no CI acceptance script. One measured run on the 5090, recorded in `speculative-decoding.md` (no separate record). It uses llama-server at the pinned build, with ggml-org Qwen3.6-27B Q4_K_M, its MTP Q4_0 file and `dflash-…-Q8_0`:

1. Discover offers both kinds. The DFlash file downloads beside the owned version.
2. The scan pairs it, and "Companion file" lists "(DFlash)".
3. Measure decode tok/s, prose and edit, for Off, MTP and DFlash, with "Tokens drafted per step" unset and at 15.
4. Compare GPU memory with admission's reservation.
5. A DFlash file of another model in the folder is not paired. Set by hand, its launch is refused with both shapes.
6. The builder's drafting phase times DFlash.

No review is required. If one runs, it should attack:
- false pairing between two models of the same shape;
- the by-hand detection;
- a header that lies (no `target_layers`, or a huge array);
- an older build.

## 6. Do not change

- **agent:** `engines/llama_cpp.py` (rows 9, 15, 20, 50; it already calls `speculation.plan`, so it needs no change), `engines/vllm.py` (9, 18, 20, 41, 42), `runtimes.py` and `engines/acquisition.py` (13), `benchmarks.py` (10), `apps.py` and `client_doors.py` (25, 34).
- **library:** `fit.py` and `hardware.py` (16, 43), `store.py` and `routes/models.py` (22, 48, 61), `profile_storage.py` and `routes/profiles.py` (21), `preflight.py` (18, 68), `engine_fit.py` (63).
- **Shared:** `scanner.py` with row 61 (LIB lane): change only the draft functions, and row 61 rebases. Row 68 rebases onto this row's `formats/gguf.py`.
- **ui:** `ConfigField.tsx`, `configValue.ts` (62), `ResourceTree.tsx`, `settingsTopics.ts` (33), `GatewayOperations.tsx` (38).
- **Every repository:** `scripts/codegen.py`.

## 7. Size, split, risks, calls

**S-M, about 2 days,** on one branch, `r17-draft-sidecars`. Each step passes its own tests:
- **17a (S):** library and the contract.
- **17b (S):** agent.
- **17c (S):** ui, and the 5090 measurement.

**Risks:**
- **No ggml-org EAGLE3 file was found.** EAGLE3 is tested with a synthetic header only, and the live run covers DFlash.
- **A fine-tune of the same shape may pair with a base model's drafter.** That is still correct, because the target checks every token. It can be slow, and the acceptance rate on the run shows it.
- **An unverified community report says EAGLE3 asserts under tensor split.** If the run or a person hits it, refuse `eagle3` with that split mode and name it.
- **DFlash's step size is unknown until measured.**
- **A key renamed upstream reads as "cannot pair",** and the skip line names the missing key.

**Calls only Troy can make** (none blocks):
- **Discover's layout.** One box per kind (recommended), or one box listing every precision of every kind.
- **Timing both drafters.** Should the builder time MTP and DFlash both when both are present? Recommended: yes. It already times each companion, at about a minute a file.
