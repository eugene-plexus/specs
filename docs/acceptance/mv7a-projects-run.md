# MV7a live run: chat projects

**2026-10-20, run of record: 27 passed, 0 failed.**

- **Script:** `workbench/scripts/mv7a-projects-acceptance.py`.
- **Design:** `docs/design/workbench-memory-v2.md`, sections 73-82.

**What ran.** A throwaway stack on ports 8540-8551, with every `EUGENE_PLEXUS_*` variable dropped and
everything torn down by pid:

- a deterministic model;
- a real driver and gateway;
- Workbench from the working tree, **over a schema 26 store** holding Ada's pinned general note.

What each request carried was read from a recording proxy in front of the gateway.

| Section | What it showed |
|---|---|
| 1b | The store came through: schema 27, the projects table, Ada's note general, and a backup of the schema 26 store |
| 2 | Ada made a project and kept a pinned note to it |
| 3 | A chat in no project was given her general note and not the project's |
| 4 | A chat in the project was given both. With Also use my general memory off, it was given its own only, on the very next turn |
| 5 | "Remember that ..." in the project's chat kept the note to the project, not to General |
| 6 | A chat moved into the project was given its note at once |
| 7 | Bo saw none of Ada's projects, could not make a chat in it, and could not read it |
| 8 | Deleting a project and keeping what was in it made its chats and notes general. Deleting another with everything took its chat and its note, and left no project |

## Before the run of record

- **The first run, before the review's fixes, passed 27/27.** The run of record is after them.

## Sabotage and review

- **Sabotage:** `check-memory-sabotage.py --label MV7`, 14 cases.
  - The first pass caught 8 of 8.
  - Six cases came after: past chats kept to the project, and one for each review fix a mutation
    can show.
  - The crowding case first escaped. Its HTTP test passed with the fix undone, because without a
    meaning model the Finder adds the pool's newest notes and found the project's note anyway. It
    was rewritten as a unit test of the meaning path's cut, where the crowding is, and was caught.
  - The final pass caught 14 of 14, and the baseline was restored and passing.
- **One adversarial review** (high risk: a store migration, and what models receive). No blocker.
  - **Fixed:**
    - A search filtered to the chat's place only after its cuts, so other places' notes could
      crowd a project's out.
    - "Forget ..." offered other places' notes.
    - A connection's `read_note` read a project's note by id.
    - Suggestions dropped the same words found in another place.
    - A connection's suggestion was compared with project notes.
    - The learning pass was told project-only tags.
    - Deleting a project could leave rows under its id.
    - The general switch and its chats' frozen blocks changed in two steps.
    - Counting read every chat and note.
  - **Also fixed in the build:** past chats were not kept to their project. This was planned for
    MV7b and moved into MV7a.
  - **Left, recorded** (design section 82):
    - what a memory server already holds from a chat later moved into a project;
    - the project page's simple note list;
    - Add a note on the Memory page keeping to General.
- **Checks:**
  - **Server:** 2,400 tests passed. Two other tests failed, and neither is from MV7a:
    - `tests/test_job_sites.py::test_a_person_removes_their_own_link_and_the_owner_names_anyones`
      fails on this machine also at the clean HEAD, and passes on CI.
    - `tests/test_reader.py` failed once under `-n auto` and passed alone.
  - **Static:** ruff, ruff format, and mypy on Windows and Linux.
  - **Web:** tsc, eslint, prettier, and Vitest with 3,439 tests passed.
  - **Chrome:** both checks pass. The documents check timed out once waiting for a chip, then
    passed on its own.
