# MR2 documents in the prompt: the run of record

Design: `docs/design/workbench-memory-and-documents.md` (sections 4.3, 4.5 to 4.7, 5.2, 5.7; its header
lists the calls made). A person attaches a PDF, Word, Markdown, text, CSV, HTML or code file to a chat, and
any model, including a local one that cannot read a PDF, answers from it; the answer names the file and
the pages that were sent.

## Acceptance of record (real processes)

`workbench/scripts/mr2-documents-acceptance.py`, Amish_Station, 2026-10-11: a real Workbench, gateway,
driver and llama.cpp b10948 with Qwen3-0.6B (window 8,192; it cannot read PDFs), ports 8460-8467.
**50 passed, 0 failed.**

- A Markdown file, a 3-page text PDF and a Word file were each read in the background and sent as one
  user message, the document's text in a delimited block before the person's words; the same text
  reached the engine, and the real model answered `HERON-1180`, `TAMARIND-6042` (on page 3) and
  `QUOKKA-7359`. Sources named the file, and for the PDF "pages 1 to 3 of 3".
- A 30-page PDF (about 24,183 tokens against an 8,192 window): the offer was "pages 1 to 6 of 30 (4,786
  tokens)"; sending without choosing was refused with the numbers and nothing was stored or sent; after
  choosing, the request carried pages 1 to 6 only and said it was the first part; the answer was
  `OSPREY-2255`, and the engine never saw page 7.
- A corrupt PDF failed with its cause ("PDFium: Data format error; pypdf: Stream has ended
  unexpectedly"), a scan was skipped as having no text, and a locked file as password-protected;
  Workbench kept answering in that chat and another.
- Two people: Bo gets the same 404 for Ada's file, its text, her chat's files, a choice and a removal.
- The cache: turn two's request begins with turn one's, byte for byte, at Workbench and at the engine
  (the engine reused 140 of turn two's prompt tokens).

The page in Chrome (`tests/test_documents_browser.py` over `web/scripts/documents-browser.mjs`): a file's
card goes from reading to ready, the code word on page 3 reaches the model, Sources says "pages 1 to 3 of
3", a server refusal lands on the file's card, the first part of a long PDF is chosen and sent, a model
change re-checks the files, and a reload keeps them. The reading check now includes a documents chat and
asserts Send stays on a 390 px screen with two cards.

## Unit tests and sabotage

- Python: 756 passed (309 new for the server: extract 80, context 88, reader 36, API 97, store 8, plus
  `test_documents_page.py` holding the page's types to the server's real answers); with every Chrome
  check, 768 passed. The server suite also passes on Linux (WSL Ubuntu, Python 3.14: 753), which covers
  `killpg`, `RLIMIT_AS` and the SIGKILL test.
- web: 1,479 passed.
- Sabotage: server 76 of 76 caught; page 138 of 138 (126 unit, 12 in Chrome).
- A gitleaks scan of the committed tree finds nothing.

## Pinned

- Workbench main `9515527` (server `8a81721`, page `2bb18fa`), dist `30bfff1`; agent `fae68eb`
  (catalogue).

## The live run

Owed: Troy updates, attaches a PDF in a chat with a local model, and asks about a later page.
