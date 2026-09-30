# A3b acceptance: the library's fit knows what moves

**2026-09-30.** Contract `e318b03`; library tests `tests/test_moe_fit.py`;
sabotage `scripts/a3b-sabotage.py`. Design:
[`../design/moe-aware-fit.md`](../design/moe-aware-fit.md) §1-§3.

**The defect.** The library scored every model as dense. A model bigger than
the card was `split`, and nothing said whether the part left in system memory
would be whole layers or only the experts. The difference is the one design §0
M3 measured on an 8 GB card: 4.9 tok/s for a dense 27B, 46.5 for the 30B-A3B
with its experts in RAM. And the only context the library offered was the one
that fits entirely on the card, which for a MoE model on a small card is none.

**What the library does now.**
- The scan reads each GGUF's tensor table and sums the expert tensors
  (`_exps` and `_chexps`; a shared expert, `_shexp`, stays on the card). A
  type the reader has no size for makes the share unknown, never a guess.
- `GgufDetail.expertBytes` is summed over every part of a sharded model. An
  entry cached before this field existed is read again.
- A `split` or `tight` fit carries `offload`: `experts` when everything but
  the experts, plus the cache, fits on the card, else `layers`. It is null
  when nothing has to move or the share is unknown.
- `ModelFit.maxContextExpertsInRam` is the largest context with the experts
  in system memory, bounded by the card and by the card and RAM together.
- A remote preflight reads no further than before: the table is read only
  when asked for.

**Real files.** The tensor sums equal each file's data region on six real
GGUFs. Budgets are the card less 0.5 GB and three quarters of RAM, at a 16k
context:

| Model | Card | RAM | Verdict | `offload` | Context with experts in RAM |
|---|---|---|---|---|---|
| Qwen3-30B-A3B Q4_K_M (18.6 GB, experts 94.6%) | 8 GB | 16 GB | `no` | null | 13,056 |
| | 8 GB | 32 GB | `split` | `experts` | 60,672 |
| | 16 GB | 32 GB | `split` | `experts` | 147,968 |
| Qwen3-30B-A3B UD-Q3_K_XL | 8 GB | 16 GB | `split` | `experts` | 60,416 |
| | 8 GB | 32 GB | `split` | `experts` | 60,416 |
| | 16 GB | 32 GB | `fits` | null | 147,712 |
| Qwen3.6-27B Q4_K_M (dense) | 8 GB | 16 GB | `split` | `layers` | null |
| | 8 GB | 32 GB | `split` | `layers` | null |
| | 16 GB | 32 GB | `split` | `layers` | null |

Before A3b every row above except the one `fits` offered no context. The
Q3_K_XL rows are bounded by the card rather than RAM, which is why 16 GB and
32 GB of RAM give the same number. The Q4_K_M at 8 GB / 16 GB is `no` at 16k
and still offers 13,056, because a smaller context is what fits in the card
and RAM together.

**Tests and sabotage.** Ten tests cover the tensor table, an unknown type, a
dense model, experts against layers, the null cases, a card too small for the
non-expert part, the offered context, shards, the route and a stale cache.
Library suite 549 passed; ruff and mypy clean. **Sabotage: 12 of 12 caught**,
restored from a copy after a passing baseline. The entries: chunked experts
not counted, a shared expert counted, an unknown type sized anyway, the table
read by default, experts always said to move, a dense model said to move
experts, an unknown share described, the offered context ignoring RAM, a
stale cache served, shards not summed, and the route passing neither the
expert bytes nor the offered context.

**Not covered.**
- No real engine loaded a model at the offered context. The PB1 runs are
  where llama.cpp's `--fit` was measured placing experts.
- A safetensors model has no tensor table read, so its `offload` is null.
- Discover's words and the starter set's MoE class are A3c, after the theme
  work in `ui`.
