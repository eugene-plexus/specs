# MR6b: Workbench sorts the passages it finds

Workbench's saved documents are searched by words and by meaning (MR4, MR5), fused by reciprocal rank,
and the best 5 go to the model. MR6 built a result sorter door (`POST /v1/rerank`). This slice has
Workbench use a served sorter to choose those 5, when it helps and when it is quick enough.

## The measurement that decided it (2026-10-12)

MR5's harness and 60 questions (written from the heading outline only), 76 design documents, 2,810
passages. Qwen3-Embedding-0.6B and two sorters, llama.cpp b10948 on the processor. Workbench `2f40f0a`;
the script and full tables are in the session's `scratchpad/mr6b/`. The baseline reproduced MR5's record
to the digit: recall@5 words 0.500, meaning 0.583, hybrid 0.600.

| What is sorted | Sorter | recall@5 | MRR@5 | change in recall [95%] | gained / lost |
|---|---|---|---|---|---|
| hybrid's first 5 (baseline) | none | 0.600 | 0.432 | | |
| hybrid's 10, text | Qwen3-Reranker | 0.600 | 0.443 | +0.000 [-0.083, +0.083] | 3 / 3 |
| best 10 of each way, text | Qwen3-Reranker | 0.650 | 0.452 | +0.050 [-0.067, +0.167] | 8 / 5 |
| hybrid's 10, **heading path + text** | Qwen3-Reranker | 0.667 | 0.582 | +0.067 [+0.017, +0.133] | 4 / 0 |
| **best 10 of each way, heading path + text** | Qwen3-Reranker | **0.750** | **0.631** | **+0.150 [+0.033, +0.267]** | 11 / 2 |
| best 10 of each way, heading path + text | bge-reranker-v2-m3 | 0.717 | 0.553 | +0.117 [+0.000, +0.233] | 10 / 3 |

- **Text alone does not help.** The hybrid order already weighs headings (words count a heading double;
  meaning embeds heading plus text). A passage whose sense is in its heading ("Trade-off: ..." under
  "J25. Windows, while the person is signed out") is lost by a sorter that never sees the heading.
- **The heading path before the text does help.** With Qwen3-Reranker it reaches the ceiling of what
  the candidates hold almost exactly: 45 of the 47 questions whose right passage is among them.
- **Cost, on this processor (12 threads, others' work around 14%):**
  - Qwen3-Reranker: 3.8 s for 10 passages, 6.2 s for 18 (the union median), about 820 tokens a second.
  - bge: about half that time, for about half the gain.
  - The GPU is not measured.
- Sorting alone beat fusing the sorter's order with the hybrid's (recall@5 0.700 against 0.650 on the
  fused 20).
- Caveats:
  - The questions were written from headings, which favours heading-aware scoring (the baseline too).
  - 60 questions make wide intervals.
  - The headings rows were planned before the run, but they are the best of several.
  - A live run on real questions is owed.

## The calls (for Troy's tweaks)

1. **What a sorter sees: each passage as its heading path, a new line, its words**, the text the search
   model embeds.
2. **Which passages: the best 10 by words and the best 10 by meaning, each passage once** (up to 20),
   sorted. Then Workbench's choice as before: 5 by default, at most 3 from one file unless the question
   names it, merged and packed into the budget. With only one way running, its best 10.
3. **Which sorter, set in `documentsSortModel` (config trio):**
   - `auto`, the default: the first local, running sorter the gateway lists to Workbench's key
     (surfaces `rerank`, locality `local`);
   - `off`;
   - or a model id.
   An outside sorter is never chosen by itself: passages would leave the install. This is the
   embeddings rule (MR5 call 1).
4. **Only when quick enough** (`documentsSortSeconds`, default 3). A sort runs only when the expected
   time is within the budget. The expected time is the tokens to sort divided by the sorter's measured
   rate:
   - the rate comes from Workbench's own recent sorts;
   - before its first sort, the rate comes from a two-passage probe when the sorter appears.
   Over the budget, the passages go in the hybrid order, and the Documents screen says why, with the
   numbers. For example: "Not sorted: Qwen3-Reranker sorts about 820 tokens a second here, so this
   would add about 7 s to each answer. Raise Sort time in Workbench's settings to sort anyway."
   Settings never lie: the screen shows the measured rate and the budget.
5. **A sorter that fails never fails a search.** A failure is the sorter down, a refusal, or a sort
   taking over twice the budget. The hybrid order is used, and the search's report says so in the
   sorter's words, as a way of searching that could not run does (`SignalUnavailable`).
6. **What a person sees:**
   - The Documents screen states the mode ("Searching by meaning and words, sorted by
     Qwen3-Reranker").
   - Test a question shows each passage's place by words, by meaning and by the sorter.
   - Under an answer, Sources are unchanged.
7. **The scores stay unshown.** A sorter's score is 0 to 1 (MR6). Workbench shows places, never
   numbers, as it does for words and meaning.

## Acceptance (MR6b)

- The 60 questions through the real stack, with the shipped settings and a budget large enough to sort
  on this processor:
  - recall@5 and MRR@5, sorted against hybrid;
  - the gate: sorted is not worse than hybrid on recall@5, and better on MRR@5, with the paired
    intervals printed.
- The budget, both ways. The default 3 s on this processor does not sort, and the screen and Test a
  question say why with the rate. A raised budget sorts.
- The sorter stopped mid-run: questions are answered from the hybrid order, and its reason is named.
- `off` and a named model; an outside sorter never chosen by `auto`.
- The page in Chrome: the mode line, Test a question's places, and the not-sorted reason.
- Sabotage per the changed code: heading path dropped, the union replaced by hybrid's 10, the budget
  ignored, a failure failing the search, `auto` choosing an outside sorter.

## What building found (MR6b, built 2026-10-12 to 13)

Record: `docs/acceptance/mr6b-sorting-run.md`. Workbench `534a8bd` to `3a1408c`, dist `7658527`, agent
`aaf54ce`. Built in three rounds, each reviewed adversarially; the third round was fixes only.

- **The gain held through the real stack.** On the CPU, recall@5 went from 0.600 to 0.783 and MRR@5
  from 0.432 to 0.664. On the RTX 5090 they were 0.767 and 0.678. **In-sample:** the questions were
  written from headings and chose the heading format. A live run on real questions is owed.
- **Speed decides where it sorts.** Through Workbench, a sort takes 7.1 s on a 12-thread CPU and 0.6 s
  on an RTX 5090. The default Sort time of 3 s sorts on the card and not on the CPU, and says so with
  the numbers.
- **Calls changed while building:**
  - **A search never waits for a measurement.** With no speed known, the question is answered unsorted
    ("measuring") and the quick test runs behind it. A quick test that times out is learned from.
    Failed measurements back off from 10 s, doubling, up to the 10-minute re-measure.
  - **A given-up sort is its own state, not a speed.** "X did not answer within N s the last time it
    was asked; Workbench asks it again after (time)", with no "raise Sort time" advice. While it
    stands, Sort time decides, not size: a question is asked again only when twice Sort time is longer
    than the wait that was given up on. Questions that were waiting together count as one strike.
  - **Re-measuring.** The quick test runs again only when the speed is the quick test's alone, or when
    the sorter is over budget and its speed is stale. It is blended in, and "from quick tests" is
    said once they make up most of the speed.
  - **A named way is not sorted.** "Try one way at a time" shows what that way finds alone.
  - **Meaning and sorting share one look at the gateway's model list**, so a hung list holds the
    Documents screen once, not twice.
  - **Sort time reads "a sort is given up on after twice this"**, not "the most a sort may add".
  - **The Result sorter says "In use" only while it sorts.** Otherwise it says "Chosen: X (automatic),
    not sorting now:" and the reason.
- **Failures name what was observed.** A gateway hold (a 503 with Retry-After) is the gateway asking
  for a wait, not "not running"; MR5's meaning search had the same misreading, now fixed. A 404 gives
  the gateway's words. The door's own 400 is not "the sorter refused".
