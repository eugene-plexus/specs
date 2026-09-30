# A3d acceptance: Low offers a smaller file after a build

**2026-09-30.** ui `f3bd294`, dist `e062f0c`, pinned in both installers. No
contract or library change. Sabotage `scripts/a3d-sabotage.py`. Design:
[`../design/moe-aware-fit.md`](../design/moe-aware-fit.md) §1.5, call C and
§6.

**What it does.** On the settings builder's result, after a build at
**Low** only:
- If the file on disk does not fit entirely on the card at the chosen
  stop's context and cache type (the library's fit, against the node the
  page looks at), the page looks for a smaller quant of the same model.
- The repository is the one the model's own finished download names. A
  file copied in by hand gets *A smaller version might fit entirely on the
  card. This file was not downloaded here, so Discover is where to look for
  one.*
- The offer is the largest quant in that repository, smaller than the file
  on disk, whose weights fit in the room the file's **own** cache and
  overhead leave: *A smaller version, IQ4_XS (16.4 GB), fits entirely on
  the card at 64k. A smaller file changes answers more than any memory
  setting, and the builder does not measure how much.*
- **Download it**, then **Build settings for it** once the file lands. The
  builder is never started for the person (it runs on demand only). A
  smaller file already on disk links to its own page instead.

## The finding that set the rule

The first version used the catalogue's own per-quant verdicts. **Checked
against the real hub before shipping, they were wrong where this matters.**
For Qwen3-30B-A3B-Instruct-2507 on an 8 GB card at 64k, the library's
catalogue called the 18.56 GB Q4_K_M "no", although PB1 had just run that
file there with its experts in system memory. Every quant from 8 GB up read
"no" or "split". A candidate nobody has read is scored from its size alone,
and the cache guessed from weight size is far off at a long context.

**Quants of one model share its shape, so they share its cache.** Only the
weights differ. So the arithmetic is the file on disk's own fit: free
graphics memory, less its cache at the chosen context and cache type, less
its overhead, is the room any quant's weights have. Measured on the real
Q4_K_M, one card, free memory 1 GiB under the card's size:

| Card | Context, cache | This file | Cache + overhead | Largest smaller that fits entirely |
|---|---|---|---|---|
| 8 GB | 16k, f16 | split, experts | 1.50 + 1.00 GiB | none |
| 8 GB | 64k, q4_0 | split, experts | 1.69 + 1.00 GiB | none |
| 12 GB | 16k, f16 | split, experts | 1.50 + 1.00 GiB | UD-IQ1_S, 9.05 GB |
| 16 GB | 16k, f16 | split, experts | 1.50 + 1.00 GiB | UD-IQ3_XXS, 12.91 GB |
| 16 GB | 64k, f16 | split, experts | 6.00 + 1.00 GiB | UD-TQ1_0, 8.09 GB |
| 24 GB | 64k, f16 | split, experts | 6.00 + 1.00 GiB | IQ4_XS, 16.38 GB |
| 24 GB | 64k, q4_0 | fits | 1.69 + 1.00 GiB | (nothing offered: it fits) |

So the MoE model on a small card, whose split is the graceful kind, is
rarely offered a smaller file, and when it is on a mid-size card the offer
is a real quality step down, said as one. A dense model spilled by whole
layers, where the whole model on the card is the difference (M2: 4.9 tok/s
spilled), is the case this serves. The cache type matters: a 4-bit cache at
64k is 1.7 GiB of this model where full precision is 6.0, so the fit is
asked at the stop's own cache type.

## Checks

- **ui:** 1,574 tests, typecheck, lint, format and the copy gate green. The
  pure rule is tested with the real repository's sizes and the catalogue's
  wrong verdicts beside them, so a rule that trusted those verdicts fails.
  The offer is driven through the profile page: the fit asked at the chosen
  context and cache type, the repository from the download record, the
  download posted, the link to build the new file, nothing offered when the
  file fits or when the build was not Low, no repository guessed for a file
  copied in by hand, and a file already on disk linked rather than
  downloaded.
- **Sabotage, 14 of 14 caught** (`scripts/a3d-sabotage.py`, from a copy,
  after a baseline that passed). A fifteenth, removing the guard that reads
  a missing cache or overhead as "cannot say", escapes the vitest gate:
  `free − undefined` is NaN and no size compares below it, and removing it
  is a type error `tsc` refuses in CI. It is recorded in the script rather
  than kept as a case the gate cannot see.
- **Every script specs CI runs** passed locally in Python 3.12 before the
  pin.

## Not done

- **No browser ran it.** The offer needs a Low build on a card the file
  does not fit, and this box's 5090 was serving the live install; a CPU
  machine has no graphics memory to offer room in. It is driven through the
  page in jsdom with the real sizes.
- The smaller file's quality is not measured, and the page says so. A
  rebuild at Low on the new file measures its cache cost, not its loss
  against the original.
