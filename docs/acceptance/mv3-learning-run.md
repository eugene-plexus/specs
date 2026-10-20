# MV3 live run: learning and the write policy

**2026-10-19, run of record: 51 passed, 0 failed.**

- **Script:** `workbench/scripts/mv3-learning-acceptance.py --part all`.
- **Design:** `docs/design/workbench-memory-v2.md`, sections 27-39.
- **Measurement:** [m-memory-measurement-mv3.md](m-memory-measurement-mv3.md).

**What ran.** A throwaway stack on ports 8490-8501, with every `EUGENE_PLEXUS_*` variable dropped,
torn down by pid:

- `llama-server` with Qwen3-0.6B on the 5090, answering one driver as a local model and another as an
  outside one;
- a deterministic stub model that answers the learning pass and calls `remember` when it is offered,
  so each policy's outcome is the code's and not the model's;
- a real gateway, and Workbench from the working tree **over a schema 23 store**.

## Part a (MV3a)

| Section | What it showed |
|---|---|
| 1b | The store came through: schema 24, the schema 23 file kept, Ada's note as it was and written by no model, and the two new tables there |
| 2 | Models that learn lists both models: unmeasured, off by default, the outside one said to be outside |
| 3 | A choice per model: on Suggest, the local model's chat sent Ada's words (and no answer) to the learning pass after 90 s; on Off, the outside model's chat sent nothing; a suggestion records its model; Bo's list is his own |
| 4 | Measure this model: an outside model needs confirming, and says what may go and that it is charged. A local one ran on the real engine: 245 requests in 60 s, its result kept as the install's (pass and tool path, started by Ada) and shown to Bo with its reason ("Not recommended: ..., kept 17.6% of what it should"). A second run while one is going is refused; a cancelled one says so |

## Part b (MV3b)

| Section | What it showed |
|---|---|
| 6 | Keep automatically under Standard: the answer was offered `remember`, and its system message says so. The call kept the note, and the receipt says so. The store holds it active, kept automatically, with its model. Recently learned lists it, unseen, under Standard |
| 7 | Call 12: an outside model (Ada's notes set to always go) was sent her notes but not the unseen one. Once Recently learned marked it seen, it went |
| 8 | Injection: a pasted email telling the AI to remember a cleaning fee made the model call `remember`, and nothing was kept or offered. The person's own words next to a pasted `> SYSTEM:` line went to Suggested notes, not kept |
| 9 | A change to Ada's own pinned note waits in Suggested notes, and her note stays current. A note the model kept itself it may change: Undo removes the change and makes the old note current, and the kept `remember` result says the person removed it. Remove everything the model kept since yesterday named its count (2), removed them, and left Ada's own notes |
| 10 | Strict: Keep automatically comes to Suggest, and the screen says the policy does not allow it. `remember` is not offered. The pass's note waits in Suggested notes. Bo's memory holds none of Ada's |

## Before the run of record

- **The first run crashed.** `llama-server` and Workbench stopped part way through the measurement
  while the full test suite ran beside them. Every later run was alone.
- **The first run found a real defect in MR8's paste rule.**
  - The rule read an apostrophe as a quotation mark, so "I'm ... What's" lost the words between.
  - It is fixed in `memory_suggest._drop_quoted_spans`, with a regression test.
- **The second run's six failures were the run's own design.**
  - Part a's real 0.6B model had already suggested "Works as a nurse.", and part b's `remember` of
    the same words was rightly refused as a duplicate.
  - Part b now uses a fact of its own.

## Sabotage and review

- **Sabotage:** `check-memory-sabotage.py --label MV3` was run after the fixes.
  - The case "a measurement's requests go as nobody" was dropped: the run's task copies the request's
    context, so it is not observable.
  - The two cases that escaped were rewritten (an unpinned typed note; a pinned model-written note)
    and re-run: `--label replaces` 2/2, `--label MV3b` 15/15.
- **Adversarial reviews:** one for each sub-slice. Their should-fix findings and MV3b's one blocker
  (a model could replace any note by itself) are fixed (design section 39).
- **Full suite:** 2336 passed, 30 skipped (Chrome opt-in and POSIX-only), plus ruff, mypy (Windows
  and Linux) and the web checks.
