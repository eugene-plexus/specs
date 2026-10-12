# MR7 folders: the run of record

Design: `docs/design/workbench-folders.md` (copied from Workbench's `docs-mr7-folders.md`, which holds the
calls with their reasons and what building found). A person points their Documents at a folder they are
granted on the machine Workbench runs on; Workbench reads its files read-only into the person's own index and
keeps them in step (new, edited, deleted, moved), every 10 minutes and on Sync now. No file watcher.

## Acceptance of record (real processes)

`workbench/scripts/mr7-folders-acceptance.py`, Amish_Station, 2026-10-11: a real Workbench, gateway, driver
and llama.cpp b10948 with Qwen3-0.6B, ports 8620-8627. **45 passed, 0 failed.**

```
== 2. the owner grants a folder to Ada; she adds it        states: waiting -> syncing -> synced
== 3. a question answered from the folder                   answer: 'HERON-1180'; Sources name the file
== 4. what is left out is named, with its reason            hidden, temporary, node_modules; a picture
                                                            and a program skipped; a junction pointing
                                                            outside named, not followed
== 5. edit the file                                         the new text answers; the old word is in no
                                                            request at either hop and in no file of the
                                                            person's folder
== 6. delete a file
== 7. 40 files, Workbench killed in the middle               45 documents; documents read twice: 0
== 8. two people on every route, and the owner
== 9. the folder was never written to                       every byte and modified time as left
== 10. the owner withdraws the grant                        documents out before the request returned
45 passed, 0 failed
```

The page in Chrome (`tests/test_folders_library_browser.py`): the owner grants a folder, the person adds it,
sees it sync and its files ready, asks a question answered from a folder file (Sources name the folder and
path), edits a file and uses Sync now, the rules and a refused pattern, a withdrawn folder, and removal.

## Unit tests and sabotage

- Python: 1,657 passed for the server (356 new); with every Chrome check, 1,677 passed.
- web: 2,610 passed.
- Sabotage: server 213 cases (208 Windows, 5 Linux-only) all caught after the fixes below; page 143 (125
  unit, 8 Python, 10 Chrome) all caught.
- Real defects the sabotage pass found and building fixed: a pattern's trailing space lost on save; a
  withdrawn grant answered before its documents were out (now under a lock, with a test forcing the order); a
  rule changed mid-check ignored.
- A gitleaks scan of the committed tree finds nothing.

## Known limits

- No file watcher: a quick check misses an edit that keeps a file's size and modified time (a deep check
  finds it).
- Job Sites' remote folders are not supported (MRC26).
- A first read runs at about 7 to 8 small files a second on this PC; the counts show progress.

## Pinned

- Workbench main `1b3dbcf` (server `50f101c`, page `1b3dbcf`), dist `ca97c83`; agent `69ba80e` (catalogue).

## The live run

Owed: Troy grants a folder in Toolbox · Tools, adds it in Documents, and asks about a file in it.
