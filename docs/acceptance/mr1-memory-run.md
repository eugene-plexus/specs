# MR1 memory v1: the run of record

Design: `docs/design/workbench-memory-and-documents.md` (its header lists the calls made). A person keeps
short notes about themselves and how they like answers; Workbench gives them to the chat's model in its
one system message, frozen per chat so the prompt cache holds, and shows exactly what was sent.

## Acceptance of record (real processes)

`workbench/scripts/mr1-memory-acceptance.py`, on Amish_Station, 2026-10-11: a real Workbench, a real
gateway and driver, llama.cpp b10948 on the processor with Qwen3-0.6B (window 8,192), two recording
proxies, two people (Ada and Bo) and the install's owner, ports 8440-8449, every ambient
`EUGENE_PLEXUS_*` variable cleared. **36 passed, 0 failed.**

```
0. PASS no ambient EUGENE_PLEXUS_* reaches a child; ports 8440-8449 free
1. PASS gateway routes mr1-local, mr1-outside; Ada, Bo, owner sign in
   PASS /api/models says where each model runs (local / external); NOTE window 8192
2. PASS "Remember that ..." keeps their words, prefix off; message still answered (NOTE answer: 'It is saved.')
   PASS the very first request already carried the note in one system message
   PASS preference + pinned instruction by API: three notes, one used first
3. PASS ONE system message: chat instructions, then the notes; all three notes + the app's sentence in it
   PASS the same text reached the engine through gateway and driver
   PASS model answers 'ZEBRAFISH-4417' (a word only the note holds)
   PASS Bo's chat sent no notes at either hop; Bo's answer 'code word' (cannot know it)
4. PASS drawer text == Workbench's system message after the instructions, to the byte
   PASS names the three notes sent, none left out, budget 655 for the 8192 window (191 tokens)
5. PASS next turn: same bytes; added note waits (drawer: changed, added_since); Refresh takes it
6. PASS switch off: instructions alone at both hops; drawer says chat_off; on again: same bytes
7. PASS hosted API sent no system message; drawer says outside_model; after "Send for this chat" it is sent the notes
8. PASS deleted note in no later request (that chat or a new one), at both hops
   PASS no row, index entry, log text or chat copy of it is left
9. PASS Bo: empty page/export, 404 on every call for Ada's note or chat; his "forget" finds nothing
   PASS owner (ownerReadsChats on) gets counts only; refresh and edit are 404; off: 404
10. PASS no owned port still listening
36 passed, 0 failed
```

The page in Chrome (`tests/test_memory_browser.py` over `web/scripts/memory-browser.mjs`): "Remember that
my code word is HELIOTROPE" shows the toast; the Memory page lists the note with its source; a new chat's
chip says a note was sent and its drawer shows the exact text; the chat's switch turns it off; delete
removes it. Pictures dark and light at 1440 and 390; the reading check covers the Memory page and the
drawer too.

## Unit tests and sabotage

- Python: 441 passed (190 new: memory 128, store 16, API 46); with every Chrome check, 452 passed.
- web: 1,257 passed (331 new); typecheck, lint, format clean. A gate test holds an accessible name and a
  test id on every control in every state.
- Sabotage: server 49 of 49 caught (owner filter in six queries, the outside guard, hard delete, the
  budget and the under-4,096 skip, snapshot freezing, secret refusal, the command parser, the migration);
  page 114 of 114 (101 unit, 13 in Chrome).
- Found on the push: GitHub's push protection refused a fake Slack token in the validator's tests
  (`xoxb-...`); every key-shaped test string is now split so no whole key sits in the source.

## Pinned

- Workbench main `d315fcc` (server `25bd0f6`), dist `ac5e852`; agent `bd6e528` (catalogue).

## The live run

Owed: Troy updates (NAS, Amish_Station, then Apps -> Workbench -> Update), types "Remember that ..." in
a chat, and opens a new chat to see it used.
