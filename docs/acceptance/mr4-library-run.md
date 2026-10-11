# MR4 saved documents, searched by words: the run of record

Design: `docs/design/workbench-memory-and-documents.md` (sections 4.1, 4.3 to 4.7, 4.9, 5.2 to 5.4, 5.7;
its header lists the calls made). A person keeps their own files in Documents; Workbench reads and
indexes them in one SQLite file per person; a chat with Documents on gets the best-matching passages in
its latest message, cited by number, and the answer names each passage's file and page.

## Acceptance of record (real processes)

`workbench/scripts/mr4-library-acceptance.py`, Amish_Station, 2026-10-11: a real Workbench, gateway,
driver and llama.cpp b10948 with Qwen3-0.6B, Ada, Bo and the install's owner, ports 8480-8487.
**70 passed, 0 failed** (about 60 s).

- States seen as they happened: `survey.pdf: queued -> reading -> ready`, then the counts.
- In a chat with Documents on, the real model answered `[1] HERON-1180`; the Sources entry names
  `survey.pdf`, page 4.
- Editing (adding again) or deleting a file: the old text is gone from the next answer.
- Workbench killed at 6 ready, 1 reading, 7 waiting: it resumed, each file read once and only the one cut
  off read twice.
- A PDF with no text is skipped with its reason; chat-scoped documents die with their chat.
- Two people: the same 404 for every not-yours call; the owner never reads saved documents.
- An index with its search table dropped says "failed (SQLite said: no such table: chunks_fts)", never
  "nothing matched", and Rebuild fixes it.
- Breaking five things on purpose (placement, owner redaction, isolation, failure wording, scrub) made
  it fail each time.

The page in Chrome (`tests/test_library_browser.py` over `web/scripts/library-browser.mjs`): three files
added and a picture refused in its own words, Ready, Test a question finds the page-4 code word without
asking a model, a chat with Documents on answers with the passage cited by file and page, "Documents
only" with "Ask the model anyway", and removing a file.

## Unit tests and sabotage

- Python: 1,047 passed for the server (298 new); with every Chrome check, 1,081 passed.
- web: 1,901 passed.
- Sabotage: server 198 of 198 caught; page 390 of 390 (355 page, 21 against the server's shapes, 14 in
  Chrome). The Chrome checks also found a real defect: at 320 px the top bar's hidden "(your machines)"
  widened the page.
- A gitleaks scan of the committed tree finds nothing.

## Known limits

- Words only: "costs" does not find "cost" (no stemming); meaning search is MR5. The Documents screen
  says so.
- A single upload request's total size is not capped (each file is, at 50 MiB, and 200 files a request).

## Pinned

- Workbench main `d90dede` (server `fd6af48`, page `d90dede`), dist `d9984de`; agent `ab28d46`
  (catalogue).

## The live run

Owed: Troy updates, adds a few of his own files in Documents, and asks about them in a chat with
Documents on.
