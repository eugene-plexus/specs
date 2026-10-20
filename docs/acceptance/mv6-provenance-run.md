# MV6 live run: provenance, Still true? from changed documents, and tidy

**2026-10-19, run of record: 35 passed, 0 failed.**

- **Script:** `workbench/scripts/mv6-provenance-acceptance.py`.
- **Design:** `docs/design/workbench-memory-v2.md`, sections 64-72.

**What ran.** A throwaway stack on ports 8540-8551, with every `EUGENE_PLEXUS_*` variable dropped and
everything torn down by pid:

- a deterministic model that cites passage 1 in every answer;
- a real driver and gateway;
- Workbench from the working tree, **over a schema 25 store** holding one of Ada's notes;
- real documents, read by Workbench's own worker.

| Section | What it showed |
|---|---|
| 1b | The store came through: schema 26, both new tables, and a backup of the schema 25 store |
| 2 | An answer cited one passage of `survey.md` and not the other document's. Remember on it linked `survey.md`, from the answer, with the cited place |
| 3 | Nothing was asked while the survey was as it was |
| 4 | Replacing the survey (an upload of the same name) asked Still true? naming it and saying it changed. The note was still sent to the model while it waited (MV6-C2) |
| 5 | Still true moved the link to the new version, and nothing more was asked |
| 6 | Removing the survey asked about both notes that rest on it, at once. Ask me next week put one off, and Still true dropped the other's link |
| 7 | Bo could not link Ada's document, and was asked nothing of hers |
| 8 | The tidy pass proposed the two notes that say the same thing, and Keep this one merged them into one note with both pins and tags and the other as its earlier version. It proposed the event long past, and Remove forgot it |
| 9 | The export carries a note's documents |

## Before the run of record

- **The first run, before the review's fixes, passed 35/35.** The run of record is after them.

## Sabotage and review

- **Sabotage:** `check-memory-sabotage.py --label MV6`.
  - The first pass caught 7 of 7, before the review.
  - After the review's fixes, five cases were added, one for each fix that a mutation can show:
    contradictions, the candidate filter, the merge's log, a snooze's document, and the timer's
    week. That pass caught 12 of 12, and the baseline was restored and passing.
- **One adversarial review** (high risk: a store migration).
  - **Blocker, fixed:** a merge wrote the other note's words into the kept note's log, and deleting
    the merged version alone left them there. The merge now logs no words, with a regression check.
  - **Fixed:**
    - Contradicting notes were proposed as duplicates ("tabs over spaces" and "spaces over tabs",
      "2 kids" and "3 kids", "allergic" and "not allergic").
    - Links kept cited snippets after their document was removed. They now keep pages and lines
      only.
    - "No" to a document's question spent the project timer's week.
    - The page read checked every version's links, one lookup at a time. It now checks current
      notes only, each document once.
    - The pass ran on the event loop, and its candidate filter could miss long duplicates.
    - Linking again by hand reset how a link was made.
    - The 20-document cap did not hold through a merge.
    - A snooze hid a second change.
    - A missing index was read as every document removed.
    - Linking and merging were allowed with memory off.
  - **Left, recorded** (design section 72):
    - a merge's dropped body is not said;
    - undated model events carry a 30-day date;
    - undoing a learned note a merge kept restores the other.
- **Checks:**
  - 561 server tests passed across the memory, past-chats, store, documents, connections, chats and
    config suites, with 2 skipped (Chrome opt-in).
  - ruff, ruff format, and mypy on Windows and Linux.
  - Web: tsc, eslint, prettier, and Vitest with 3397 tests passed.
