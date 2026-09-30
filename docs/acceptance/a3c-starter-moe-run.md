# A3c (library half) acceptance: the starter set can offer a MoE model

**2026-09-30.** Contract `29a5f22`; library `55b30db`; tests
`tests/test_starter_moe.py`; sabotage `scripts/a3c-sabotage.py`. Design:
[`../design/moe-aware-fit.md`](../design/moe-aware-fit.md) call B and §5.

**The defect.** The starter set recommended only an entry that fits entirely
on the card. An 8 GB card was never offered the 30B-A3B class, which runs at
46 tok/s there with its experts in system memory (design §0 M2), against 4.9
for a dense 27B spilled by whole layers.

**What the library does now.**
- A starter entry may carry `recommended.expertBytes`, measured by the review
  from the file's tensor table. `StarterModel.maxContextExpertsInRam` is
  filled from it.
- A MoE entry is a candidate when it fits entirely, or when its fit says
  `offload: experts`. A `no` verdict, or a split by whole layers, is never a
  candidate.
- It is recommended only over a dense entry of a smaller size class. Between
  two entries of one class that both fit, the dense one wins.
- The words say what sits on the card and what sits in system memory, with
  the sizes, and predict no speed.
- The review has a `30B MoE` class. A name ending `-A3B` or a `moe`
  architecture id makes a candidate, and the file's expert tensors are the
  proof: a MoE entry is not built without them.
- Library `55b30db` shipped the code with the list unchanged, so the review
  said REPLACE for the empty class until a person accepted an entry. Troy
  accepted one the same day (below).

**The review against the live hub, 2026-09-30.** 5 KEEP (every current
entry), 1 REPLACE:

| Class | Leader | 30-day downloads | Runners-up |
|---|---|---|---|
| `30B MoE` | **Qwen/Qwen3.6-35B-A3B** | 4,338,121 across 8 repos | gemma-4-26B-A4B-it (2.0M), its QAT build (1.2M), Qwen3.5-35B-A3B (0.56M) |

The proposed entry, as the review wrote it. The expert bytes were read over
HTTP Range from the file's header and tensor table, and the architecture
`qwen35moe` is in the llama.cpp b10999 source list. **Nothing here has loaded
the file.**

```yaml
- class: 30B MoE
  baseModel: Qwen/Qwen3.6-35B-A3B
  repo: unsloth/Qwen3.6-35B-A3B-GGUF
  why: most-downloaded well-known instruct GGUF in its size class over the last 30 days (4,338,121 downloads
    across 8 repos)
  license: apache-2.0
  parameters: 34660610688
  architecture: qwen35moe
  contextLength: 262144
  evidence:
    downloads30d: 4338121
    repos: [unsloth/Qwen3.6-35B-A3B-GGUF, unsloth/Qwen3.6-35B-A3B-MTP-GGUF, HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive,
      michaelw9999/Qwen3.6-35B-A3B-NVFP4-MTP-GGUF, bartowski/Qwen_Qwen3.6-35B-A3B-GGUF, mudler/Qwen3.6-35B-A3B-APEX-GGUF]
    consecutiveReviewsAtTop: 1
  recommended: {file: Qwen3.6-35B-A3B-UD-Q4_K_M.gguf, label: UD-Q4_K_M, sizeBytes: 22134528992, bitsPerWeight: 5.11,
    expertBytes: 19568525312}
  shape: {blockCount: 40, attentionLayers: 10, headCountKv: 2, keyLength: 256, valueLength: 256, embeddingLength: 2048,
    headCount: 16}
```

**What that list would recommend.** Budgets are the card less 0.5 GB and
three quarters of RAM:

| Card | RAM | Context | Pick | The MoE entry | Context with experts in RAM |
|---|---|---|---|---|---|
| 8 GB | 16 GB | 8k, 16k | `8B` | `no` | null |
| 8 GB | 32 GB | 8k, 16k | **`30B MoE`** | `split`, `experts` | 188,416 |
| 12 GB | 32 GB | 8k, 16k | **`30B MoE`** | `split`, `experts` | 262,144 (the trained maximum) |
| 16 GB | 32 GB | 8k, 16k | **`30B MoE`** | `split`, `experts` | 262,144 |
| 24 GB | 64 GB | 8k, 16k | `30B` (dense 27B) | `fits`, then `tight` | 262,144 |
| 32 GB | 64 GB | 8k, 16k | `30B` (dense 27B) | `fits` | 262,144 |

The words on an 8 GB card with 32 GB of RAM:

> Qwen/Qwen3.6-35B-A3B runs here with its experts in system memory:
> UD-Q4_K_M, 20.61 GiB of weights, of which 18.22 GiB are experts that
> llama.cpp keeps in system memory. The rest, with 320.00 MiB of KV cache for
> 16,384 tokens, takes 3.70 GiB of the 6.98 GiB free on the card. The largest
> of these that fits entirely on the card is google/gemma-4-E4B-it, a smaller
> model. This way it fits up to 188,416 tokens.

T2's laptop (8 GB and 16 GB of RAM) gets the 8B at three quarters of its RAM
free. With all 16 GB counted free, as `scripts/s10-starter-check.py` counts
it, the same list picks the 35B-A3B as `split` with experts in RAM: 22.1 GB of
file against 24 GB of card and RAM together. The library scores against the
RAM it detects as available, so on a real laptop the answer depends on what
else is open. The 35B-A3B is 3.6 GB larger than the 30B-A3B the design
measured, and a smaller file of it is A3d's lever, not this slice's.

**Tests and sabotage.** 19 tests. Library suite 568 passed; ruff and mypy
clean. **Sabotage: 18 of 18 caught.** The first pass caught 15 of 19:
- Two escapes named missing tests, and both are tests now: a MoE entry whose
  rest does not fit the card, and a MoE found by its architecture id alone.
- One named an untested path: that the review gives the class a verdict.
- One named a redundant guard: `no` never carries `offload`. It was deleted,
  not kept as a second mechanism.

**Accepted and shipped, 2026-09-30.** Troy accepted the whole review,
explicitly **without** a test load first. Library `d6f4e6f` carries it:
- every existing class is kept, with its streak moved to 2;
- the `30B MoE` class holds the entry above;
- `reviewed:` is 2026-09-30.

Both installers pin it. `scripts/s10-starter-check.py` now accepts a pick
that is `split` with `offload: experts`, as long as the part left on the
card fits it (3.81 GB of 8). On that fixture the pick is the 35B-A3B.

**Not done.**
- No engine has loaded the file. Troy's call was to ship without that.
- **The UI says "partial offload at 8k"** for this pick. That is true, but it
  reads like the warning a dense spill deserves. Words for a pick with its
  experts in RAM are A3c's UI half, which is first in line now that the
  theme work has landed.
