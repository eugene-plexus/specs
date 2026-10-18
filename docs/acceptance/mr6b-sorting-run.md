# MR6b acceptance: Workbench sorts what a search finds

Design: `docs/design/workbench-sorting.md`. The script is `workbench/scripts/mr6b-sorting-acceptance.py`.

## The run of record (2026-10-13)

- Workbench `3a1408c` (dist `7658527`, agent catalogue `aaf54ce`), gateway `437745f`, inference-driver
  `5237d8f`.
- llama.cpp b10948 on the CPU (12 threads): Qwen3-Embedding-0.6B to search, Qwen3-Reranker-0.6B-Q8_0 to
  sort, and bge-reranker-v2-m3 as a second sorter.
- The 76 design documents at specs `c5f725d` (2,810 passages), and MR5's 60 questions.
- **111 passed, 0 failed, all 13 stages, 1,160 s** (with `--reuse-data`, so the 13.7-minute import
  is skipped):

| Stage | Checks | Seconds |
|---|---|---|
| isolate | 5 | 1.2 |
| stack | 6 | 5.4 |
| documents | 3 | 0.3 |
| off | 7 | 7.9 |
| budget | 10 | 1.8 |
| gate | 20 | 426.5 |
| composition | 7 | 70.2 |
| chat | 8 | 56.2 |
| chrome | 11 | 65.4 |
| named | 10 | 157.4 |
| stopped | 11 | 62.8 |
| hung | 5 | 145.1 |
| outside | 7 | 151.7 |

The record's header discloses that for about three minutes of the gate stage, the machine was busier
with an unrelated check. Its CPU timings are a little pessimistic for that stretch; pass and fail are
unaffected.

## Quality (60 questions, paired bootstrap of 4,000 rounds, 95%)

| | recall@5 | MRR@5 |
|---|---|---|
| hybrid, the sorter off (MR5's record, reproduced to the digit) | 0.600 | 0.432 |
| sorted, on the CPU | 0.783 | 0.664 |
| change, paired | +0.183 [+0.083, +0.300] | +0.232 [+0.129, +0.335] |
| sorted, on the RTX 5090 | 0.767 | 0.678 |

- On the CPU, the sort gained 12 questions and lost 1 (q15, which the offline measurement also lost).
- The gate held: recall@5 is not worse, and MRR@5 is better, with its interval excluding zero.
- **In-sample.** The 60 questions were written from the documents' headings, and the heading-path
  format was chosen on them, so these numbers favour heading-aware sorting. Sorting the text alone
  changed recall by +0.050 [-0.067, +0.167]. **A live run on real questions is owed** (Troy's).

## Speed, measured through Workbench

| | CPU (12 threads) | RTX 5090 |
|---|---|---|
| Sort per question, median | 7.10 s | 0.60 s |
| p90 | 8.13 s | 0.66 s |
| Speed from sorts | about 735 tokens a second | about 9,030 |
| The quick test's reading | 749 | 3,842 |
| The default Sort time, 3 s | does not sort: a usual sort is priced at about 8 s, and the screen says so with the numbers | sorts all 60 of 60 (a usual sort takes 0.64 s) |

A question without a sorter takes 0.06 s.

## What the checks cover

- **Off.** Nothing is asked of the sorter, and the screen and settings say so quietly.
- **The default budget on the CPU.** Nothing is sorted. The screen, Test a question and both settings
  say why with the rate.
- **The sorter's input.** Every request carried each passage as heading path, a new line, then the
  text, exactly as the index embeds it.
- **The order.** Every place shown equals the place the engine's own scores give, and no score is
  shown.
- **Composition.** The sorter gets exactly the best 10 of each way, each passage once. A named way
  ("Try one way at a time") is not sorted.
- **Chat.** The sorted order reaches the model, and Sources still name the files.
- **Chrome.** The mode line, a sorted place and the not-sorted reason, at 1440 and 390 pixels, dark
  and light.
- **A named sorter.** One that does not sort, one that is not listed, and a second sorter.
- **A stopped sorter.**
  - The screen noticed in 10.4 s, and sorting resumed 10.2 s after a restart.
  - The gateway's 503 with Retry-After is said as the gateway asking for a wait, not as "not running".
- **A hung sorter.** It is given up on at twice Sort time, and the next questions are answered at once.
  The screen says it did not answer, with no speed and no "In use". It is asked again after a backoff.
  A sorter that was never measured is not waited on: the first question is answered unsorted in
  0.08 s, and the quick test runs behind it.
- **An outside sorter.** `auto` never chooses one, whether outside sorters are allowed or not and
  whether the local sorter is stopped or not. A named outside sorter is used only when the owner
  allows outside models.

## Defects found and fixed

- **Found live by the acceptance.** Each has a unit test that fails without its fix.
  - A gateway hold (a 503 with Retry-After) was read as "the sorter is not running". Fixed in
    sorting, and in meaning, where MR5 had the same reading.
  - A sort that was given up on was blended into the speed, so the next questions waited again.
- **Found by the reviews.**
  - The Result sorter setting said "In use" while nothing was sorted.
  - A search waited on the first speed measurement, and a probe that timed out was never learned
    from.
  - The bound from a given-up sort was shown as a measured speed.
  - A smaller question was still asked of a sorter that had hung.
  - The speed kept saying "from sorts" after the quick tests had taken it over.
  - Simultaneous askers counted as several strikes.
  - A probe failing inside Workbench left no memory of the failure, and some error branches had no
    test.
  - The CI flake (workbench#6, #7) was found and fixed: a stale no-model wait outlived the model, and
    the test helper had a race. Before the fix it failed 5 times in 150 runs; after, 0 in 150.

## Sabotage

- **Acceptance:** 8 of 8 in round one (the design's five plus three), 12 of 12 in round two, and the 2
  new cases in round three. Each was caught.
- **Unit:** `scripts/check-sorting-sabotage.py` has 155 cases. Each round's new cases were caught, and
  the restored baseline passes.
- **Page:** 63 of 63, plus round three's case.

## Also re-run

MR5's acceptance on round two's code passed 52 of 52, the same 52 as its record, with identical
numbers.

## Left

- gateway#14: the rerank door's 502 for a lost connection says "work may have occurred".
- workbench#8: five older sabotage scripts have drifted anchors (from earlier slices).
- A live run on real questions and real hardware (Troy's).

## Rerun against the pinned components (2026-10-18)

Troy's choice: MR5's 60 questions as they are, against the components pinned at
specs c8619eb (gateway 2036c31, inference-driver 8b9305d, Workbench 020df6b,
which is the pinned dist's source), on the CPU, on the script's own ports, with
every `EUGENE_PLEXUS_*` cleared, and with no `--reuse-data` (the import took
10.1 minutes, 2,810 passages). **111 passed, 0 failed, 1,574 s.**

- With the sorter off, the three searches reproduce MR5's record to the digit.
- Recall@5 went from 0.600 to 0.783, +0.183 [+0.083, +0.300], and MRR@5 from
  0.432 to 0.664, +0.232 [+0.129, +0.335]. That is 12 gained and 1 lost (q15),
  the same as the run of record.
- On the CPU, a sorted question took a median of 5.46 s (p90 6.34 s), at about
  949 tokens a second, against 7.10 s on 2026-10-13. The default Sort time of
  3 s still sorts none of the 60 and says so (`over_budget`, a usual sort
  priced at 6.07 s). The price matched what a sort actually took (1.0×).
- A stopped sorter was noticed in 10.3 s and was back in 15.2 s. A hung sorter
  was given up on at 40.1 s, twice the Sort time of 20 s.

This is still in-sample: the questions were written from the documents' headings.
Troy chose this regression run over a new set of real questions.
