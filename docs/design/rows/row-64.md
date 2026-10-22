# Row 64: starter set: proof of CPU speed

Lane LIB, low risk, size M. Repos: library, specs, ui.

Sources: `hobbyist-ux.md` §6.5, step 3 ("For classes whose smallest quant
is under 6 GB, download it and produce one token on CPU in CI"; built: the
architecture half only), and §11.7 "Not done". Memory
`project_library_findings` ("With no accelerator the starter
recommendation inverts to the smallest"; "CPU-token proof unbuilt"). Also
library `starter.py`, `starter_review.py`, `starter_models.yaml` and
`.github/workflows/starter-review.yml`; `moe-aware-fit.md` §0.

## 1. What it delivers

- **The review measures speed on a processor.** The monthly starter review runs each entry of 8 GiB or less on GitHub's runner, with the pinned llama.cpp CPU build. This is the CPU proof that §6.5 promised. The report's `proof` column says `cpu` or `architecture`.
- **The pick on a machine with no graphics card changes.** Today it is always the smallest entry. Now it is the largest entry that fits in memory here and generated at least 8 tok/s on the test machine.
- **The reason names the speed and the machine:** "Gemma 4 E4B generated 11 tok/s on a 4-core test processor. Yours may be faster or slower. After the download, Benchmark measures it here."
- **A text fix.** The CPU reason says "a few words a second" today. Troy's rule is tokens and tok/s.
- **The workflow works on a schedule.** The scheduled run on 2026-10-01 failed while filing its report ("could not add label: 'starter-review' not found"). The manual run on 2026-10-02 passed.

## 2. The design

### The measurement (library `starter_review.py`, new `cpu_proof.py`)

A new step 3b runs after the architecture check:

1. **Get the engine.** Download the pinned engine's Linux CPU build once: the `engine:` line of the YAML, for example `b10999`, and its release asset `llama-<tag>-bin-ubuntu-x64.zip`.
2. **Measure each small entry.** For each class whose recommended file is 8 GiB or less (4B, 8B and 14B today: 2.7, 5.3 and 7.1 GB):
   1. Download the file.
   2. Run `llama-bench -m <file> -p 512 -n 128 -r 3 -o json -t <physical cores>`.
   3. Delete the file.

   Only one file is on disk at a time: the public runner has 4 vCPU, 16 GB of RAM and about 14 GB of free disk.
3. **Record it.** Write `cpuProof` on the proposed entry. The processor name comes from `/proc/cpuinfo` at run time, not from an assumption.
4. **A load failure** makes that class's verdict REVIEW, with llama-bench's last lines: "Qwen3.5-4B did not load on the pinned CPU build b10999: {last lines}."
5. **A file over 8 GiB** is not measured. Its proof stays `architecture`.

**When a proof is kept.** A proof is carried from last month when the repo, the file, its size and the engine tag are all unchanged. Otherwise the file is measured again.

**On and off.** The workflow measures by default. `--no-cpu-proof` turns it off for a local run.

### Contract (`library.yaml`)

- **New schema `CpuProof`:**
  - `decodeTokensPerSecond` and `promptTokensPerSecond`, as numbers;
  - `promptTokens` (512), `decodeTokens` (128) and `threads`;
  - `machine`, for example "GitHub ubuntu-24.04 runner, 4 vCPU AMD EPYC 7763, 16 GB";
  - `engine`, for example "llama_cpp b10999";
  - `measuredOn`, a date.
- **`StarterModel.cpuProof`** is `CpuProof` or null.
- **`StarterRecommendation.reason`'s description.** It says "No speed is predicted." The new text: "On a machine with no graphics card, the largest entry that fits in memory and whose `cpuProof.decodeTokensPerSecond` is at or above the floor. The speed is the test machine's, and the reason names that machine. No speed is predicted for this machine."
- **No field of `StarterRecommendation` changes.**

### The pick (library `starter.py`)

Today, `has_no_accelerator(budget)` with any entry that fits gives the smallest entry. The new rule:

1. **Find the proven entries.** These are the entries that fit and whose `cpuProof.decodeTokensPerSecond` is at least the floor.
2. **If there are any, take the largest.** The reason: "{baseModel} is the largest of these that generated at least {floor} tok/s on a test processor ({machine}: {decode} tok/s). On a machine with no graphics card, the processor computes every token, so speed decides. Yours may be faster or slower. After the download, Benchmark measures it here. {label}, {size}."
3. **If there are none, take the smallest**, as today. The reason is in tokens: "Bigger ones fit in memory here, but on the processor they generate only a few tokens a second. No entry in this list has a measured speed."
4. **A mixture-of-experts entry without a proof** is never the pick on a processor.

**The floor is a setting:** `starterCpuFloorTokensPerSecond`, default 8, from 1 to 100. It is in `/v1/config` and its schema (`config.py`), so the console's config editor shows it (GUI equality). 8 tok/s is about reading speed.

### The starter card (ui `src/components/StarterSetPanel.tsx`)

On a machine with no graphics card, each proven entry shows "11 tok/s on a 4-core test processor". It is never presented as this machine's speed. On a machine with a graphics card the line is hidden, because a processor's speed says nothing about a card.

### The workflow (library `.github/workflows/starter-review.yml`)

- Create the label before filing: `gh label create starter-review --force`. This was the October failure.
- Set the timeout to 60 minutes. The measurement adds about 15 GB of downloads and about 10 minutes.

### The two-review rule, end to end

The rule has never fired on real data, and only `verdict_for` is unit-tested. Add an end-to-end test that runs the review command twice on recorded hub answers. A new leader is first both times. The second proposed file says REPLACE, with `consecutiveReviewsAtTop: 2`.

### Failures (each names its cause)

- **The engine build does not download.** Every class gets `proof: architecture` and REVIEW: "The pinned CPU build b10999 could not be downloaded: {cause}. No speed was measured."
- **A model file does not download.** That class gets REVIEW, with the cause.
- **llama-bench's output cannot be read.** That class gets REVIEW, and the report holds the last lines of the output.

### Defaults

Nothing is deleted, and nothing new is stored about people. The list still changes only by a person's commit.

## 3. Repositories and files

- **specs:**
  - `library.yaml`;
  - one more check in `scripts/starter-set-acceptance.sh`;
  - `hobbyist-ux.md` §6.5 step 3: the CPU half is built.
- **library:**
  - new `cpu_proof.py`;
  - `starter_review.py`, `starter.py`, `config.py`;
  - the workflow and tests;
  - `starter_models.yaml`: the first run fills it, and a person accepts it.
- **ui:** `src/components/StarterSetPanel.tsx`. Check `FirstModelCard.tsx` for the reason text.
- **Codegen:** library and ui. The gateway's codegen names `library.yaml` but uses none of this. Regenerate and diff to confirm, and do not re-pin the gateway.

## 4. Test that fails before the change

**library `tests/test_starter.py::test_cpu_pick_uses_measured_speed`**

- A budget with no GPU and 32 GB of RAM.
- 4B has a proof of 20 tok/s, 8B of 11 tok/s, and 14B of 6 tok/s. The floor is 8.

Expected: the pick is 8B, and the reason names "11 tok/s". Today the pick is 4B, the smallest.

**Also:**

- `test_cpu_reason_says_tokens_not_words`;
- `test_no_proof_keeps_smallest_and_says_so`;
- `test_moe_without_proof_never_cpu_pick`;
- `test_proof_kept_when_file_and_engine_unchanged`;
- `test_bench_json_parsed`, on a recorded llama-bench JSON;
- `test_two_reviews_fire_replace`.

## 5. Acceptance

The row is low risk. CI runs the unit tests.

**The proof of record** is one `workflow_dispatch` run of the review on the branch. Its report shows `proof: cpu` and three speeds.

**`starter-set-acceptance.sh`** gains one check: with `vramBytes=0`, the reason names a tok/s and the test machine.

## 6. Do not change (other lanes' hot files)

- **library:**
  - `fit.py`, `hardware.py` (16, 43);
  - `scanner.py` (17, 61);
  - `formats/gguf.py`, `preflight.py` (18, 68);
  - `engine_fit.py` (63).
- **agent:** `benchmarks.py` (10).

Hot files of rows earlier in the LIB lane are free once those rows land.

## 7. Size, risks, calls

**Size M, about a day.**

**Risks:**

- **The runner is not the person's machine.** The number is always labelled as the test machine's.
- **A shared runner's speed varies between runs.** The bench runs three times, and the report gives the standard deviation.
- **GitHub changes runner hardware.** Each proof records its machine.

**Calls for Troy:**

1. **The floor: 8 tok/s?** Recommend 8.
2. **The size limit: 8 GiB, where the design said 6 GB?** Recommend 8 GiB. It adds the 14B class and still fits the free runner.
3. **The 30B MoE is fast on a processor, but too big for the free runner.** Measure it on a larger, paid runner, or leave it unproven? Recommend unproven for now, because of the cost. Look again if CPU users ask for it.

## Calls answered by Troy (2026-10-21)

- **CPU-FLOOR: 4 tokens a second.**
- **CPU-SIZE: Choice 1.** Up to 8 GiB.
- **CPU-MOE: measured on Troy's workstation, 2026-10-21.** Qwen3.6-35B-A3B UD-Q4_K_M (22.1 GB), llama.cpp b10948 with CUDA hidden (`CUDA_VISIBLE_DEVICES=-1`, `-ngl 0`), `llama-bench -p 512 -n 128 -r 3 -t 16` on an AMD Ryzen 9 9950X (16 cores): **13.85 ± 0.27 tok/s decode, 175.4 ± 3.5 tok/s prompt.** Above the 4 tok/s floor. Other local test runs may have shared the processor, so the true figure can be a little higher. Record it as the class's `cpuProof` with `measuredOn` 2026-10-21 and the machine named; the monthly run on GitHub still skips it, and keeps this proof while the file and engine tag are unchanged.
