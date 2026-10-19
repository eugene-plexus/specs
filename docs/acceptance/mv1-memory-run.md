# MV1: memory v2's first slice (run of record, 2026-10-19)

Design: `docs/design/workbench-memory-v2.md` sections 1-13 (MV1). Script:
`workbench/scripts/mr1-memory-acceptance.py`, rewritten for MV1; this was its first execution.

**Stack.** A real Workbench process (the MV1 working tree) **starting on a schema 21 store** that holds
two people's notes and a chat's frozen v1 copy; the real gateway; two real inference-drivers, one
declaring a real `llama-server` (b10948, processor, Qwen3 0.6B Q4_K_M, window 8,192) local and one
declaring a stub hosted API external; recording proxies before the gateway and before the engine; a
stand-in for Eugene's sign-in; two people (Ada, Bo) and the install's owner. Every ambient
`EUGENE_PLEXUS_*` variable dropped; ports 8440-8449; teardown by pid.

**Result: 51 PASS, 0 FAIL.**

| Part | What was observed |
|---|---|
| Migration | Schema 22, the schema 21 file kept beside it first; every note each person's own, the pinned one still always used; the frozen v1 copy dropped, to be retaken; the old notes in each person's own index only |
| A note at once | "Remember that ..." keeps the words without the prefix; the very first request carries the note in the person's message as data, at both hops |
| Where notes go | One system message: the chat's instructions, then the pinned notes and nothing else; the turn's notes in the latest message before the question; the model answered `ZEBRAFISH-4417`, a word only the note held; Bo's chat carries none of Ada's notes at either hop |
| The drawer | Its pinned text is Workbench's system message after the instructions, to the byte; it names the two pinned notes and this turn's notes with both budgets |
| The next turn | The system message is the same bytes; each turn's block leads with what it asked about; an earlier turn is replayed as written, without its block |
| Prompt cache | Engine, turn one: read 2,141 tokens, held 3; turn two: read 303, held 1,884: the pinned system message came from the engine's cache |
| Pinned changes | A note added meanwhile is chosen at once; a new pinned one waits for Refresh (the drawer says so), and Refresh sends it |
| The chat's switch | Off: no note, block or memory tool at either hop, and the drawer says why; on again: both blocks return |
| Outside model | Nothing (no system message, note, block or tool) until "Send for this chat"; then the pinned block, the turn's notes and `search_memory`, which Workbench ran; taken back, the kept result **and the call's query** are withheld |
| Long note and tags | Export carries body and tags whole and the tag list; the tag list round-trips as CSV into Bo's list; Replace my list names what it removes first; the long note is in the index as title plus passages; a turn about it gets the answering passage, not the whole body; Save as a new version keeps the old as history, never sent, out of the index |
| Delete | No row, store index entry, log text, chat copy or tag link left; no passage in the knowledge index, words included; no later request carries it at either hop |
| Others | Bo's page, search, export and every call on Ada's note or chat answer nothing of hers; the owner who may read her chat gets counts and no note words (drawer, answers' records, `search_memory` call); with that setting off the owner cannot open her chat's memory |

**What the first run found (49 of 51).**

- **Product: a withheld `search_memory` call still carried its query.** Taken back from an outside model,
  the kept result was withheld but the assistant's call arguments (`{"query": "quince"}`) were replayed.
  A model's query can hold the words of the notes it had, so `tools.transcript` now withholds the
  arguments of a memory call with its result (`{}`). The unit test now checks the query's words too
  (it had checked "Lisbon" against a lowercase query), and a sabotage case covers it.
- **Harness: the delete check read the model's own answer.** The chat the code word was asked in holds
  the model's answer that said it; that is the person's chat, not the note. The check now asks in a new
  chat (nothing anywhere) and, in the old chat, checks the system message and the new turn.

**Before the run** (the finishing pass): the full suite (2,282 passed), ruff, mypy on Windows and Linux,
and the web checks (tsc, eslint, prettier, 3,326 vitest tests) passed after stale expectations were
updated: the schema number (21 to 22) in the conversion tests, and three tests that sent a `preference`
note and expected it in the system message (MV1 sends only notes always used there; they now send an
instruction). Two review fixes the record listed were not in the tree and were made, each with a test
that fails without it: "Save as a new version" counted toward the note cap (it returns 409 at the cap
now), and a tag description that would start a spreadsheet formula is written to CSV behind a `'` that
import takes off. Five outside-model tests failed once in one full-suite run and passed alone and in the
next full run (load, not reproduced).

**Review.** One adversarial review of MV1 (no blocker; should-fixes fixed; minor findings accepted in
the design's section 13).

**Sabotage.** Each mutation restored from a copy.

- `workbench/scripts/check-memory-sabotage.py`: the full pass ran 63 cases and caught 61; the two
  escapes were fixed and rerun by label with the new cases, all caught (64 cases now). The escapes: "a delete finds a note without the owner"
  escaped because the HTTP route checks the owner first; the store's own check now has its test
  (another person's delete finds and takes nothing). "The command is handled after the request is
  built" became "the command is not handled": the request is built in the answer's own task, so the
  order against `_ask` is not observable under the fakes (part 2 above checks it live). New cases:
  the cap on a new version, the CSV formula escape, the withheld query. Two anchors were stale and
  fixed; the script takes `--label`.
- `workbench/scripts/check-memory-page-sabotage.py` (unit cases): 100 of 101 caught after its stale
  anchors were fixed (the Memory page's five and the export's from MV1; the chat's chip, the back
  button and the tablet title from before it); the one escape, "the keyboard is taken into a toast
  it was not in", was then made observable and caught: its test spied on a Dismiss button that the
  toast draws anew after Undo; it spies on every element's `focus` now. The Chrome cases were not run.
