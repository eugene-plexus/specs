# MV7b live run: a project's documents

**2026-10-20, run of record: 18 passed, 0 failed.**

- **Script:** `workbench/scripts/mv7b-project-documents-acceptance.py`.
- **Design:** `docs/design/workbench-memory-v2.md`, sections 76-77 and 83.

**What ran.** A throwaway stack on ports 8540-8551, with every `EUGENE_PLEXUS_*` variable dropped and
everything torn down by pid:

- a deterministic model;
- a real driver and gateway;
- Workbench from the working tree over a schema 26 store, migrated as it started;
- real documents, read by its worker.

Each request's documents block was read from a recording proxy in front of the gateway.

| Section | What it showed |
|---|---|
| 2 | Ada kept a document in a project and one in My documents. Each listing holds only its own |
| 3 | A chat in the project, with Documents on, was sent both. With Also search My documents off, only the project's |
| 4 | A chat in no project was sent My documents' and never the project's |
| 5 | A file kept to the project under My documents' file's name left My documents' file as it was |
| 6 | Deleting the project and keeping what was in it moved its two documents to My documents, replacing the one of the same name. Deleting another with everything took its document, which was then nowhere |

## Before the run of record

- **The first run failed 2 checks, both the script's own.** The questions named both words, so they
  were in every request. The checks now read the documents block only, and the next run passed
  18/18.
- **The run of record is after the review's fixes.**

## Sabotage and review

- **Sabotage:** `check-memory-sabotage.py --label MV7b`, 10 cases.
  - The first pass caught 7 of 7.
  - Three were added for the review's fixes: the per-document routes, the moved sidecar, and the
    boot guard. That pass caught 10 of 10, and the baseline was restored and passing.
- **One adversarial review** (high risk: documents are deleted and moved).
  - **Blocker, fixed:** a project's documents answered 404 to Remove, Read again, Open and their
    text.
  - **Blocker, fixed:** moving a kept project's documents left their sidecars naming the project. A
    Rebuild then put them back under the deleted project, and the next boot deleted them.
  - **Fixed:**
    - Delete project (keep) now moves the documents first, and a failure leaves the whole
      project.
    - The move stages the files it replaces.
    - A replaced file stops being read before it goes.
    - The boot reconcile deletes nothing when all of a person's projects are gone.
    - An upload racing its project's delete is taken back.
    - A project's files are read in My documents' turn.
  - **Left, recorded** (design section 83):
    - a project's documents are labelled "My documents" in the chip and Sources;
    - they count toward the passage cap;
    - folders stay general.
- **Checks:**
  - **Server:** 2,413 tests passed.
  - **Static:** ruff, ruff format, and mypy on Windows and Linux.
  - **Web:** tsc, eslint, prettier, and Vitest with 3,444 tests passed.
  - **Chrome:** both checks pass.
  - **Also fixed:** a Windows CI flake in `test_folder_api.py`. The "too new to trust" window was
    shorter than a slow runner's first read.
