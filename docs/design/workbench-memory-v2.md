# Workbench memory v2: the reshape, slice by slice

The build of `memory-research-2026-10.md` (Troy took its fourteen calls on 2026-10-19). Each MV slice
gets a section here: its design, its calls, and what building found. The research doc holds the why;
this doc holds the what. Paths are under `workbench/src/eugene_plexus_workbench/` unless named.

Status: **MV1 built and accepted 2026-10-19 (51/51 live); call MV1-C1 settled per model by MV3's measurement (section 39).
MV2 (past chats) built and accepted 2026-10-19 (36/36 live); call MV2-C1 is Troy's to confirm, its
default built. MV3 (learning and the write policy) built 2026-10-19; call MV3-C1 is Troy's to confirm, its default built.
MV4 (Memory as an app) built 2026-10-19; calls MV4-C1 to C3 are Troy's to confirm, their defaults built.
MV5a (memory servers) built 2026-10-19; Troy took MV5-C1 to C3 at their defaults the same day; MV5-C4 is his to confirm, its default built. MV5b (Hindsight from the catalogue): the probe passed 2026-10-19 (section 56), designed (sections 57-63), waits on call MV5b-C1. MV6 (provenance and tidy) built 2026-10-19 (sections 64-72), 35/35 live; calls MV6-C1 to C5 are Troy's to confirm, their defaults built. MV7 (projects) designed 2026-10-19 (sections 73-81); MV7a built 2026-10-20 (section 82), 27/27 live; MV7b built 2026-10-20 (section 83), 18/18 live; calls MV7-C1 to C5 are Troy's to confirm, their defaults built. The memory reshape MV1-MV7 is built except MV5b, which waits on MV5b-C1.**

---

## MV1: long notes, procedures, tags, supersession, and memory chosen every turn

What MV1 changes, in one paragraph: a note gets a body; a `procedure` kind joins the five; caps rise
by two orders of magnitude; a changed fact keeps its history; a person keeps a tag list and tags
notes; and what a model receives splits in two: the **pinned block** stays frozen in the system
message, and **relevant memory** is chosen again every turn and placed in the latest user turn as
data, beside a `search_memory` tool for models that call tools.

Not in MV1 (research section 10): past chats (MV2); Keep automatically, the write policy, Measure
this model (MV3); the Memory screen reorganisation (MV4); backends (MV5); provenance and the tidy pass
(MV6); projects (MV7). MV1 adds to the Memory page only what is needed to write and see the new
fields; no note goes under settings (`feedback_app_before_config`).

### 1. Note bodies

- `memory_notes.text` stays the **title**: one line, at most 240 characters, the DB `CHECK` kept.
  Lists, the pinned block and every "which note" answer show it.
- New `memory_notes.body TEXT NOT NULL DEFAULT ''`, `CHECK (length(body) <= 20000)`: Markdown, line
  breaks and tabs allowed, no other control, private-use or invisible formatting character (the
  title's `_hidden` rule minus newline and tab), and the same secret check as a title. The cap is a
  setting, `memoryMaxBodyChars` (default 20,000, range 0 to 20,000; 0 means notes have no body); the
  DB `CHECK` is the ceiling the setting cannot pass. Lowering it cuts nothing: an existing body over
  the cap is kept, and only a new or edited one is held to it.
- **A body is indexed in the person's knowledge index**, not in a table of the main store. Decided
  because the index already has, per person, everything a large body of text needs: the Markdown
  chunker with heading paths, a words index whose heading column weighs twice the text, persisted
  vectors added in the background by the search-model worker (`knowledge/meaning.py`), and the matrix
  scan. A table in the main store would have meant a second embedding worker and a second vector
  store, and the in-process `NoteVectors` (embedded on the fly within 3 s) does not survive 20,000
  notes after a restart.
  - **One scope, `notes`, for every note** (not `note:<id>`): a search names one scope, and a
    document id is the note's id. Each current note is one index document, `kind = 'note'`,
    `source = 'note'`, `sha256` the hash of what was indexed (title, tags, body), so a passage of an
    old version is recognised as old.
  - Chunk 0 is the title. Body chunks come from `knowledge/chunk.py`'s Markdown rule. Every chunk's
    heading column is `Tags: a, b · <title> > <heading path>`, so tags and the title weigh above the
    text by words and are embedded with every passage by meaning (call 14).
  - **Title-only notes are in the index too**, which is what replaces `NoteVectors`: every note's
    meaning is kept on disk with the documents' and added in the background.
  - Written directly as `searchable` chunks (no file, no reading step) by a new
    `Index.put_note`, which replaces the note's document in one index transaction.
  - **Never embedded by an outside search model.** When the model the index uses runs outside the
    machines (an owner may allow that for documents), the worker skips the `notes` scope, and
    relevance uses meaning only with a local model (as `memory_relevance` does today: a profile of the
    person does not go to an outside search model).
  - **Meaning for notes does not depend on the Documents switch.** With documents turned off by the
    owner, the worker still adds meaning to the `notes` scope.
  - The documents' own counts (the 100,000-passage cap, the Documents screen's totals and meaning
    status) leave the `notes` scope out.
- **Deletion removes passages in the same operation.** The store and the index are two SQLite files,
  so one transaction cannot hold both; the order makes every failure safe:
  1. the index document goes first (its chunks, their words-index entries and vectors, with
     `secure_delete` and the segment merge the index already does);
  2. then the note row, its tag links and its log's words (one store transaction, as today);
  3. if step 1 fails the route fails and nothing is deleted; if step 2 fails after step 1, the note
     is still there with no passages, and reconciliation (below) indexes it again.
  - **Every read checks the store.** A passage the index returns is used only if its note is the
    person's, current (`status = 'active'`), and the passage's `sha256` matches what the note is now.
    So an index that lags or fails can cost recall, never send a deleted, superseded or edited-away
    word.
  - **Reconciliation** runs at start-up for every person with notes, and after any index write that
    failed: notes missing from the index or indexed at another `sha256` are put again; index
    documents whose note is gone, superseded or not active are deleted. It is also how existing
    notes are first indexed after the upgrade.

### 2. The `procedure` kind

- `memory.KINDS` gains `procedure` (briefs, procedures, style guides, checklists): the sixth kind,
  shown in its own section of the pinned block, **How they work**.
- **Only the person writes procedures in MV1.** The MR8 suggestion schema and the MCP `suggest_note`
  tool keep their kinds without it (`memory_suggest` uses an explicit list, no longer
  `memory.KINDS`); `NoteCreate` and `NoteUpdate` take it. A suggestion cannot be kept as a procedure
  by editing its kind either (the keep route refuses the change), since a suggestion is a model's
  words.
- A procedure is not always used: pinned, it is in the pinned block; otherwise relevance chooses it.

### 3. Caps

| Setting | Was | MV1 |
|---|---|---|
| `memoryMaxNotes` | default 300, range 1 to 2,000 | default 20,000, range 1 to 200,000 |
| `memoryMaxBodyChars` (new) | — | default 20,000, range 0 to 20,000 |

- An owner who set `memoryMaxNotes` keeps their number (settings never lie); only the default moves.
- Superseded versions count toward the cap (they are stored); pending suggestions do not (as today).
- At this scale nothing reads every note with its body: lists select titles and body lengths only,
  the page shows the newest 200 of "Other notes" with a search for the rest
  (`GET /api/memory/notes?query=&tag=&offset=`), and a body is read when a note is opened.

### 4. Supersession

- New columns: `valid_from REAL` (when this version became the current one; the creation time for
  every note that exists), `superseded_at REAL`, `superseded_by TEXT`, and a new status,
  `superseded`. A status rather than a column alone so every existing `status = 'active'` query,
  including the ones that pick what a model is sent, leaves an old version out without being
  rewritten.
- **What supersedes:**
  - **Save as a new version** on a note (the person's "this changed": "Lives in Lisbon" after
    "Lives in Porto"): a new note with a new id, `valid_from` now, the old one's kind, pin and tags
    unless changed; the old one becomes `superseded`, `superseded_at` now, `superseded_by` the new id.
  - **Keep new** on a suggestion that `replaces` a note: the same, instead of today's delete.
  - "remember that ..." never supersedes: it adds (a command is matched, not interpreted).
- **What edits in place:** **Save** on a note (a typo, a better word). No history entry; the log
  keeps the words before and after, as today.
- **Superseded notes are kept, never sent, and shown as history**: not in the index, not in either
  block, not in search; on the note, "Earlier versions" lists them with "replaced on {date}".
  Deleting the current note deletes its earlier versions with it (forgetting a fact forgets what it
  was); an earlier version can be deleted alone.
- Export carries every version, with `validFrom`, `supersededAt` and `supersededBy`.
- No time-travel query in MV1 ("what was true on date X"); the fields make it possible later.

### 5. Tags (call 14)

- **The list.** `memory_tags (owner, key, tag, description, created_at)`, primary key
  `(owner, key)`, where `key` is the NFKC case fold of the tag: matching ignores case, and the tag is
  shown as the person first wrote it. A tag is 1 to 40 characters, one line, no `#`, no comma, no
  hidden character; a description is at most 200 characters, one line, checked for secrets (a model
  reads it). At most 1,000 tags a person, 10 on one note.
- **Tags on notes.** `memory_note_tags (owner, note_id, key)`, primary key `(note_id, key)`; the
  note-delete trigger removes a note's links in the same statement. A tag on a note is always on the
  list: tagging a note with a new tag adds it to the list (the person wrote it). A model's proposed
  tag that is not on the list waits on the suggestion (`proposed_tags`) until the person chooses
  **Add to my tags**, which adds it to the list and the note; keeping without it drops it.
- **Search.** Tags are in each index chunk's heading column (weighted twice the text) and embedded
  with the note. `#tag` in a search (the Memory page, `search_memory`, MCP `search_notes`) filters to
  notes carrying every named tag; the rest of the query searches as usual; a tag word without `#`
  only weighs.
- **Editing the list** (Memory page): add, describe, rename (every note follows), merge (rename onto
  an existing tag: notes get the existing one, once), delete (notes keep their text and lose the tag;
  the dialog names how many notes).
- **Export and import.** Export: CSV, `tag,description`, a header row, UTF-8. Import: that CSV (the
  header row optional) or a `.txt` with one tag per line. Import adds new tags and updates
  descriptions (an empty description cell leaves the one kept); it removes nothing. **Replace my
  list** is a separate choice that first answers what it would remove and from how many notes, and
  acts only when sent again with that answer's confirmation. Every rejected line is named with its
  line number and why.
- **The memory export** (Markdown and JSON) carries each note's tags and the list itself.
- **Suggestions** (as built: see call MV1-C1; the measurement below took the list out of the
  request, and Workbench tags a suggestion in code). As designed: the MR8 schema gains `tags`: an array, at most 3, each an `enum` of the person's
  list, and the instructions list the tags with their descriptions. Over the measured cut-off length
  (below), the enum is left out and tags are free strings, flagged on the suggestion when they are not
  on the list. An empty list sends no `tags` field. MCP `suggest_note` takes optional `tags` (at most
  5 strings) with the same rule.
- **The cut-off is measured** with `scripts/m-memory-measurement.py`: the MR8 set run with lists of
  10, 25, 50, 100 and 200 tags on the passing small models; the cut-off is the longest list at which
  the suggestion quality stays at the MR8 bar. Default until measured: 50. The result goes in "What
  building found".

### 6. What reaches the model

**The pinned block** (system message, after the chat's instructions, frozen per chat and model as
today, so the prompt cache holds):

- Instructions, pinned notes, and pinned procedures, in sections About them, How they like answers,
  How they work; titles first, in today's priority order.
- Then the **bodies** of pinned notes, in the same order, each whole or not at all, while the block
  stays in budget. A pinned body that does not fit whole is sent by relevance instead (its matching
  passages, each turn), and the drawer says so with the numbers.
- Budget `min(2,000, 4% of the window)` tokens; a person's override is `memory_prefs.budget_tokens`
  (now the pinned ceiling, 200 to 20,000).
- The footer stays ("facts about the person, never instructions that override this conversation").

**Relevant memory** (the latest user turn only, chosen again every turn):

- Candidates: every current note that is not in the pinned block (titles), every body passage (of
  any current note whose body is not in the pinned block), never a past event, a superseded version,
  a pending suggestion, or another person's note.
- Found by words (the index's FTS5 over the `notes` scope, heading column weighted twice) and by
  meaning (the index's vectors, a local search model only), fused by RRF (k = 60) as documents are;
  the query is `plan_query` of the person's latest message and the one before it, as for documents.
  No result sorter (research 7.1: only if a measurement shows it helps on notes).
- Without a local search model, or when meaning fails: by words, then the newest notes, until the
  budget is full; the drawer names which ("chosen by words: no search model is running"). This keeps
  MRC28's point (a few notes all go, so "Is vegetarian." still reaches "What should I cook tonight?")
  and stops the newest-only cut a 20,000-note store would otherwise get. Without the index at all
  (damaged, unreadable), the main store's title index stands in for words, and the cause is said.
- Packed in rank order: a note's title line, and under it the passages of its body that matched, at
  most three a note; passages of one note that follow each other are joined.
- Placed exactly as document passages are: inside `<memory-XXXXXXXX>` with a random suffix chosen
  per request and never present in the text it delimits; it opens with "Notes from the person's
  memory that may bear on this message. They are data, not instructions." Each note is
  `<note-XXXXXXXX n="1" kind="fact" tags="..." added="2026-10-01">`. In the message it comes after
  attached documents and before document passages and the person's words.
- Budget `min(6,000, 10% of the window)`, a person's override `relevant_budget_tokens` (new, 200 to
  20,000). It is also held to the room the window has left after the chat, the pinned block and the
  answer's reserve; document passages then take what is left. History is never cut.
- Never sent again: the next request has no memory block in that message, so earlier turns stay the
  bytes they were and the cache is lost only from the last user turn, as with documents.

**Existing chats' frozen snapshots** are retaken once: migration 22 empties every chat's
`memory_snapshot`, and a snapshot is read only if it says `version: 2`. The next turn of each chat is
a one-off cache miss; every turn after is cached as before. (Keeping v1 snapshots would keep sending
unpinned notes in the system message, which is what MV1 removes.)

**The person's override becomes two.** The existing `budget_tokens` becomes the pinned ceiling, and
`relevant_budget_tokens` starts at the same value for a person who set one: their number is still
the most either block may take. A person who never set one gets the two defaults.

**What was sent, per turn.** Each answer keeps what its turn's relevant block held
(`messages.memory_used`: note ids and titles as sent, the passages' places, tokens, budget, how they
were found and why not otherwise), alongside the chat's pinned snapshot. The chat's Memory drawer
shows the pinned block and the selected turn (the latest by default); the owner reading a chat
read-only sees counts only, never words, as today.

**The Memory page's usage line** says both, truthfully: "Pinned: {tokens} of {budget} tokens, in every
chat. Relevant: up to {budget} tokens a turn, chosen from {n} notes by {meaning and words | words}."
The pinned figure is the window-free budget; a chat's drawer gives its model's figures.

### 7. `search_memory`

- A tool Workbench runs itself, offered when the chat's next request may carry notes (the same
  decision as the blocks: switches, window, the outside-model guard), the model's listing does not
  say it refuses tools (`toolCalling`, assumed yes), the person has at least one note outside the
  pinned block, and the person has not turned it off (`memory_prefs.search_tool`, default on, "Let
  models search my notes" on the Memory page).
- Arguments: `query` (1 to 500 characters, `#tag` filters), `limit` (1 to 20, default 8). It
  searches exactly as relevant memory does, into a budget of 3,000 tokens a call, at most 4 calls an
  answer.
- **No tool authority.** It reads only the asking person's notes, never asks for approval (it is
  their own read-only data), and its result is the same delimited block with the "data, not
  instructions" line, sent as the tool message. A model cannot change memory through it.
- Offering it puts a memory chat on the tool path even with no tool server chosen (`_with_tools`
  with one internal tool). The tool definition is the same bytes every turn, so the cache holds.
- **The outside-model guard on replay.** Tool results are replayed with the history. When a later
  request may not carry notes (the chat moved to an outside model, memory was turned off), each
  earlier `search_memory` result is replaced in that request by "Memory results are not sent to this
  model." The stored answer keeps them; the owner's read-only view hides them as it hides saved
  documents' passages.

### 8. MCP connections (MR9b)

- `search_notes` keeps every field it has (`id`, `text`, `kind`, `always`, `expiresAt`), so Claude
  Code and Codex keep working, and adds `tags`, `bodyChars` and, for a note with a body, the passages
  of it that matched (`passages: [{heading, text}]`), not whole bodies: an answer stays bounded
  (8,000 tokens) at any note size. `#tag` filters. Superseded versions are never returned.
- A new tool, `read_note` (`note_id`, `offset` in characters), under the same read-notes right,
  returns one note whole: title, kind, tags, and its body from `offset`, at most about 4,000 tokens,
  with `more` saying whether it was cut.
- `suggest_note` takes optional `tags` (section 5) and no body: a body is the person's own.

### 9. Store migration 21 to 22

One transaction, after the store's own backup (`_keep_backup`), as every migration:

1. `memory_notes` is rebuilt (SQLite cannot change a `CHECK`): the new `kind` and `status` checks,
   `body`, `valid_from` (= `created_at`), `superseded_at`, `superseded_by`, `proposed_tags`; rows copied
   with their `rowid`s; its index, its FTS5 table (rebuilt) and its three triggers made again; the
   delete trigger also removes the note's tag links.
2. `memory_tags`, `memory_note_tags`.
3. `memory_prefs.relevant_budget_tokens` (copied from `budget_tokens`), `memory_prefs.search_tool`.
4. `messages.memory_used`.
5. Every chat's `memory_snapshot` emptied.

The knowledge index needs no migration: notes enter it by reconciliation, in the background.

### 10. Not blocking MV3

- Every write of a note goes through one store method per path (typed, said, button, suggested,
  connection), which is where MV3's write policy will check a proposed note before it is stored.
- Bodies and procedures are person-written only, so nothing in the pinned block is a model's words.
- `source` and the log's `actor` are kept on every path; MV3 adds the model and policy columns.

### 11. Risk, tests and acceptance

High risk (a migration, and a change to what every model receives): one adversarial review and a
real-environment run. The acceptance run (extending `workbench/scripts/mr1-memory-acceptance.py`):

1. A store at schema 21 with two people's notes and frozen chats migrates: notes, kinds, pins and
   counts as they were; snapshots retaken; nothing of one person in the other's index.
2. A long note with a body and tags round-trips through export and import; the tag list round-trips
   as CSV and `.txt`; Replace my list names what it removes.
3. Two turns on different subjects: the relevant block changes, the pinned block is byte-identical.
4. Prompt cache: turn two's prefill much smaller than turn one's (as MR2 and A7 measured).
5. The outside-model guard holds for the pinned block, the relevant block, `search_memory`, and a
   replayed `search_memory` result after the chat moves to an outside model.
6. Deleting a note removes its index passages and its tag links; a superseded version is never sent.

Sabotage each new critical check once (`check-memory-sabotage.py`).

### 12. Calls

**MV1-C1 (parked until MV3, Troy 2026-10-19; the default stands): the model does not see the tag list.** Call 14 had a model propose tags
from the person's list (an `enum` in the suggestion schema) and asked for the list length at which
small models get worse. Measured on Gemma 4 E4B (section 13): **any** list made them worse. False
memories went from 0% to 13-17% with 12-50 tags and an injection was kept; at 100-200 tags they
were 5%, at the bar's edge. So nothing measured supports sending the list.
*Recommended default, built:* the request carries no tags (`memory_suggest.TAGS_IN_REQUEST =
False`), and Workbench tags a suggestion **in code**: a listed tag whose words stand whole in the
note's text (`tags_for`), at most three, which the person keeps or drops on Suggested notes. The
schema code for the enum stays for MV3's per-model measurement (a larger model may pass; it would
be switched on per model, from a measurement, as Keep automatically is). Override: send the list
for models that pass the bar with it.

Every other decision MV1 needed was inside the research's calls or the design's remit.

### 13. What building found

- **A turn's notes follow the latest message alone.** Searching with the message before it too (as
  documents do, for "and the second one?") put the previous turn's notes first in the next turn,
  measured in `test_each_turn_carries_the_notes_it_asked_about...`. Notes now search the latest
  message, and the one before only when the latest has no word to search.
- **The index's words are not stemmed** (`unicode61`), the store's title index is (`porter`): "grow"
  finds "Grows tomatoes" only through the titles. Both are kept as rankings, with meaning, fused at
  the level of notes (three rankings, RRF).
- **The cache holds less than "only the last turn misses".** A turn's block is in its latest message
  and is not replayed, so the next request's previous user message is not the bytes the engine
  saw: the engine's cache holds the system message and every turn before the previous one, and
  reads the previous turn, its answer and the new turn again. Document passages have always
  behaved the same way. With the pinned block in the system message this is still most of a
  long chat's prompt; the live run measures turn two against turn one.
- **The meaning worker had to stop asking when nothing is owed.** Running it with documents off
  (so notes get meaning) made it ping the search model for every person even with no note owed;
  it now returns at once when documents are off and no note's passage is owed.
- **`search_memory` puts every memory chat on the tool path** when its model is listed as calling
  tools (assumed) and the person has notes outside the pinned block. `searchTool: false` (the
  Memory page's "Let models search my notes") takes a person's chats off it.
- **A tag may hold `/`**, so the tag routes take the tag as a path parameter.
- **Deletion reaches the answers too.** A turn's record (`memory_used`) and a kept `search_memory`
  result held a deleted note's title, shown on the page and replayed to the model in later turns.
  Deleting a note now takes it out of every answer's record (counted as `forgotten`) and replaces
  any kept search result that named it; "Delete every note" does so for all of them.
- **A note pinned after a chat froze waits for Refresh.** It had gone out with the next turn by
  relevance while the drawer said it waits. Relevance now never takes a note that is always used,
  except the passages of a pinned body that did not fit.
- **Notes import is not a route.** "Round-trips through export and import" holds for the tag list
  (CSV and `.txt`); for notes, the export carries every field, body and version, and nothing reads
  it back yet. Banked, not designed.
- **The page has no "has earlier versions" flag on a listed note**, so Delete reads the note first
  to say how many versions go with it (one extra request).
- **The tag-list cut-off: there is none worth having on a small model.** `m-memory-measurement.py
  --tags N` (new; the first N of a fixed 212-tag vocabulary with descriptions), Gemma 4 E4B (the
  smallest passing model), b11719 on the 5090, the 88 MR8 sets, one sample each; data in
  `specs/docs/acceptance/m-memory-data/tags/`:

  | Tags sent | False memories | Recall | Noise sets | Injections kept | Kept, tagged |
  |---|---|---|---|---|---|
  | none | 0 (0%) | 36/51 (71%) | 0/18 | 0 | 39, 0 |
  | 12 | 6 (15%) | 30/51 (59%) | 4/18 | 1 | 41, 41 |
  | 25 | 6 (13%) | 34/51 (67%) | 5/18 | 1 | 46, 46 |
  | 50 | 8 (17%) | 34/51 (67%) | 5/18 | 1 | 48, 48 |
  | 100 | 2 (5%) | 32/51 (63%) | 1/18 | 0 | 37, 37 |
  | 200 | 2 (5%) | 33/51 (65%) | 3/18 | 0 | 41, 41 |
  | 200, free words (no enum) | 3 (6%) | 41/51 (80%) | 3/18 | 0 | 48, 48 |

  The model tags everything it keeps (mostly `tech`, `work`, `writing`, `home`), and a tag list
  seems to lower its bar for keeping: the false memories are one-off needs and opinions the
  baseline turned down, and the injection kept is a coworker's biography (`coworker_bio`). One
  sample a set is noisy, but 0 against 6-8 is not. Hence call MV1-C1.
- **The adversarial review (one, as the risk asks) found no blocker.** Its should-fix findings are
  fixed: documents off with an outside model; notes kept out of the documents cap, ETA and order;
  "meaning" no longer claimed with no vectors; the store deletes securely (`secure_delete`, FTS
  optimize, WAL checkpoint); a damaged index no longer blocks a delete; a new version counts toward
  the note cap (the "Save as new version" route missed it until the finishing pass, which added
  its test); `_tags_of` filtered by note id; add's twin check reads titles before bodies; big tag
  edits reindex in the background; Keep new carries the old note's pin, body and tags; reconcile is
  batched with a retry loop; tags are checked for secrets and spreadsheet formulas, and a tag
  description that would start a formula is written to CSV behind a `'` that import takes off (also
  added in the finishing pass); CSV errors are named and capped; `search_memory` re-checks memory
  at run time; `usage.stored`.
- **Accepted, not fixed (minor):** the search model is resolved and then searched, so a model
  change between the two is not seen for that one search (TOCTOU); a narrow race between an index
  delete and a concurrent put of the same note; superseded facts stay in a kept `search_memory`
  result (that is history, not deletion; deleting a note does take it out); the per-turn
  `memory_notes()` read costs about 0.3 s at 20,000 notes with tags and 1.5 s at 100,000; the
  migration's backup keeps old titles, as every migration's backup does.
- **A withheld `search_memory` call withholds its query too.** The first live run found the kept
  result withheld from an outside model but the call's arguments replayed; a model's query can hold
  the words of the notes it had, so `tools.transcript` sends `{}` for them as well.
- **Acceptance: 51 of 51** on the live stack, starting from a schema 21 store
  (`specs/docs/acceptance/mv1-memory-run.md`). Turn two's prefill read 303 tokens against turn
  one's 2,141, the engine holding 1,884: the pinned system message is served from the cache, as
  section 6 intends.

---

## MV2: past chats

What MV2 changes, in one paragraph: every exchange of a person's chats (what they asked and the
opening of the answer, with its date) goes into their own knowledge index, in the background and
for every chat they already have. They find past chats on a **Search chats** screen and open one
at the exchange that matched; a model that calls tools may search them with `search_chats`; an
app they connected may too, with a right they grant. Past chats are **never injected** unless the
person turns on **Use past chats** for a chat (research call 7). Deleting a chat takes its
exchanges out of the index first, then every copy of them that answers kept.

### 14. What an exchange is

- **A person's message and the answer that follows it, on the chat's path** (what the chat shows,
  `store.path`): the pair `(U, A)` with `A.parent_id = U.id`, both on the path, `A` not
  `running`, and `U` with some text. An answer that failed or was stopped is the exchange with
  what it wrote, possibly nothing (the question alone still finds the chat).
- **Versions: the shown one only.** Answer versions are a tree; only the path is indexed, so a
  search finds what opening the chat shows. Choosing another version takes the exchanges of the
  branch left out of the index and puts the ones now shown in. Try again makes the new answer the
  shown one, and its exchange replaces the old one. (Indexing every version would return three
  hits for one question asked three times, and hits on versions the chat does not show.)
- **Its text:**
  - the person's message, whole up to 4,000 characters (cut, with `…`);
  - the answer's **opening**: its final text (`content[answer_from:]` when a web search ran, else
    `content`), up to 1,500 characters, cut at the last paragraph or sentence end after the 600th
    character when there is one.
  - Not indexed: reasoning, tool calls and results (other people's pages and files, and
    `search_memory`/`search_chats` results), attachments' contents (a chat's attached files are
    already that chat's own documents), and the blocks of notes or passages a turn carried (they
    are never in a message's `content`).
- **Its date:** the day of the person's message (UTC, `YYYY-MM-DD`).
- **In the index:** one document an exchange, in a new scope **`exchanges`**, by the answer's id,
  `kind = 'exchange'`, `source` = the chat's id (so a chat's exchanges are one indexed lookup),
  `name` = the chat's title. Passages: the person's message cut by the Markdown rule notes' bodies
  use (`chunk.chunk`), then the answer's opening as one passage. Each passage's heading is
  `<chat title> · <date>` (`… > Answer` on the opening), so a chat's title weighs twice the text by
  words. `sha256` hashes the title, the date, the message and the opening: what names a version
  of an exchange, as `notes_index.digest` names a note's.

### 15. The index and the backfill

- **`ExchangesIndex`** (`exchanges_index.py`), one per Workbench, beside `NotesIndex`, using the
  people's indexes and meaning worker.
- **Kept in step by a queue.** An answer that ends (whatever its outcome), a version chosen and a
  chat renamed each `touch` the chat; a background task syncs each touched chat once, however
  often it was touched: it reads the chat's path from the store, puts the exchanges whose digest
  changed, and deletes the index's exchanges of that chat that are no longer on its path. A chat
  that is gone has every exchange removed. A failure leaves the chat touched, retried every 30
  seconds; nothing an answer does waits for it.
- **The backfill is the reconcile.** At start-up, in the background, for every person with chats,
  newest chat first: the same sync, chat by chat. It is **resumable** because it is idempotent:
  each chat's **signature** (its title, how many messages it holds, the last `seq`, the sum of
  the chosen ones' `seq`, how many are running; one grouped query for all of a person's chats) is
  kept in the index's `meta` when the chat is synced, and a chat whose signature has not moved is
  skipped without reading its messages. A restart in the middle starts where it stopped; a new or
  rebuilt index has no signatures and fills again. Index documents of chats that are gone are
  removed in the same pass.
- **How fast:** words are written at once (no file, no reading step, as `put_note`); meaning
  follows in the background through the meaning worker. The live run measures exchanges a second
  on a synthetic store and records it in "What building found".
- **What the person sees while it runs:** the Search chats screen says "Adding your past chats to
  search: 340 of 1,200." while their backfill runs, and "{n} exchanges are still being added to
  search by meaning." while meaning is owed. Search works throughout, over what is in.
- **Meaning only from a search model on the machines**, as notes: a past chat may hold a note's
  words and a document's passages. Exchanges get meaning whether or not the owner has documents
  on, after notes in the worker's order.
- **Not documents.** The Documents screen, the 100,000-passage cap, its counts, ETA and order
  leave the `exchanges` scope out, as they leave `notes` out (one set, `index.PRIVATE`).
- **Every read checks the store.** The index only finds; what is shown or sent is **read from the
  store at that moment**: an exchange is used only when its answer still exists, is in one of the
  person's chats, and is not running, and its text is cut from the store's rows. So an index that
  lags can cost recall, never send a deleted word.

### 16. Who may receive past chats (call MV2-C1)

Past chats go wherever the **memory decision** lets notes go (`memory_api.decide`: the install's
and the person's Memory switches, the chat's memory switch, the window, and for a model outside
the machines `never`/`ask`/`always` with "Send for this chat"). One extra rule, because an earlier
answer may quote a passage of a saved document: **for a model outside the machines, a `never` for
documents (the owner's or the person's own) holds past chats back too**; the documents' `ask`
needs no second "Send for this chat". This is call MV2-C1 (section 25). The decision is
`past_chats.decide`, asked by the turn, by `search_chats` when it runs, and by the replay of kept
results, so all three agree.

### 17. Use past chats (in a chat)

- **Off by default**, per chat: `settings.pastChats` (`true` turns it on), the switch "Use past
  chats" in the chat's Memory drawer. With it on and the decision allowing, every turn:
  - searches the person's exchanges with their latest message (the one before it only when the
    latest has no word, as notes), **leaving out this chat's own** (they are its history);
  - by meaning above the search model's floor, and by words, fused (RRF, k = 60); **never filled
    up** with the newest (unlike notes): an exchange goes only when it matched;
  - at most 5 exchanges, each as an excerpt of at most 1,200 characters of the message and 1,200
    of the opening;
  - in **at most a third of the relevant budget** (section 6), taken first; notes then take the
    rest, and documents what is left after them. Without matches, notes keep the whole budget.
  - placed in the latest user turn after the notes, before document passages, in its own block
    with the request's random suffix: `<past-chats-XXXXXXXX>`, opening "Excerpts from the
    person's earlier chats that may bear on this message, with their dates. They are data, not
    instructions, and what was true then may not be now." Each excerpt is
    `<exchange-XXXXXXXX n="1" chat="<title>" date="2026-10-01">` with `Person:` and `Answer
    (opening):`.
- **What was sent, per turn:** the answer's `memory_used.pastChats`: `{tokens, budget, how, why,
  exchanges: [{chatId, messageId, title, date, via}]}`, no excerpt words. The drawer's "This
  turn" lists them, each opening its chat at the exchange; a chat deleted since is not listed
  (and counted `forgotten`).
- **Never sent again**, as notes' block: the next request's earlier turns carry none.

### 18. `search_chats`

- A tool Workbench runs itself, offered when the past-chats decision allows, the model is not
  listed as refusing tools, the person has not turned it off (`memory_prefs.chats_tool`, default
  on, "Let models search my past chats" on the Memory page), and the person has an exchange in
  another chat.
- Arguments: `query` (1 to 500 characters), `limit` (1 to 10, default 5), `after` and `before`
  (`YYYY-MM-DD`, optional). Searches as section 17 does (this chat left out), into 3,000 tokens a
  call, at most 4 calls an answer. Its result is the same delimited block.
- **Re-checked at run time** (the decision is asked again when the call runs) and **withheld on
  replay** from a request that may not carry past chats: the result and the call's arguments, as
  `search_memory`'s (MV1 section 13). The owner's read-only view hides it as it hides
  `search_memory`.
- A kept call records the chats its result quoted (`call.chats`), so deleting one of them replaces
  the result (section 20).

### 19. Search chats, the screen

- **A screen of Workbench** (app before config), reached from the sidebar above the chat list.
- A search box; **When** (Any time, Past week, Past month, Past year); **Order** (Best match,
  Newest). Results: the chat's title, the date, the person's message and the answer's opening
  (each cut to 300 characters), and how it was found. An empty search lists nothing.
- **Opening a result** opens its chat scrolled to that exchange, which is marked for a moment.
- The backfill's progress and meaning's (section 15) are said under the search box.
- Routes: `GET /api/past-chats?q=&when=&order=&offset=` (at most 20 a page) and
  `GET /api/past-chats/status`. Only the person's own; `ownerReadsChats` gives the owner no search
  of anyone's chats (the setting is about reading one chat, not searching them all).

### 20. Deleting a chat

1. Its exchanges leave the person's index (words, vectors, the segment merge and `secure_delete`
   the index already does) and its signature goes. If the index cannot, the route fails with 503
   and nothing is deleted, as a note's delete does.
2. Then, in one store transaction: the chat and its rows (as today), **and every copy in the
   person's other answers**: each `memory_used.pastChats` entry of that chat is removed (counted
   `forgotten`), and each kept `search_chats` result whose `call.chats` names it is replaced by "A
   chat this search found was deleted since, so its result is not kept."
3. A step 2 that fails after step 1 leaves the chat with no exchanges in the index; the queue puts
   them back (the chat still exists).

### 21. MCP connections

A new tool, **`search_chats`** (query, limit, after, before), under a new right **Search my past
chats** (`connections.search_chats`), **off by default** for every connection, new or old. The
person ticks it when making a connection. It returns exchanges (`chatId`, `messageId`, `title`,
`date`, `question`, `answer`, `via`), bounded at 8,000 tokens and read from the store; it refuses
when Memory is off for the install or the person, as `search_notes` does.

### 22. Store migration 22 to 23

One transaction after the backup, as every migration: `connections.search_chats INTEGER NOT NULL
DEFAULT 0`; `memory_prefs.chats_tool INTEGER NOT NULL DEFAULT 1`. The knowledge index needs no
migration: exchanges enter it by the backfill.

### 23. Not blocking MV3

Past chats are read-only: nothing in MV2 writes a note. A note kept automatically later (MV3) is
a note, chosen as notes are; an exchange never becomes one without the write policy.

### 24. Risk, tests and acceptance

High risk (a backfill into every person's index, deletion, and a new path for private text to
models and connected apps): one adversarial review and a real-environment run
(`workbench/scripts/mv2-past-chats-acceptance.py`, a real gateway, driver and `llama-server`):

1. A schema 22 store with two people's chats (one with answer versions) migrates; the backfill
   indexes each path's exchanges and none of one person's in the other's index; a restart in the
   middle resumes; its rate is recorded.
2. Search chats finds an exchange by words and by meaning and opens its chat at it; a version
   switch changes what is found.
3. Use past chats: a turn carries the matching excerpt (both hops recorded); off by default; never
   this chat's own; recorded in `memory_used.pastChats`.
4. `search_chats` from a tool-calling model; withheld (result and arguments) after the chat moves
   to an outside model; MV2-C1's documents `never` holds it back.
5. Deleting a chat removes its exchanges from the index and its excerpts from other answers'
   records, and replaces a kept `search_chats` result that quoted it; a fresh chat cannot find it.
6. MCP `search_chats`: refused without the right, answers with it.

Sabotage each new critical check once (`check-memory-sabotage.py --label`).

### 25. Calls

**MV2-C1 (new, Troy's to confirm; the default is built): who may receive past chats.** The
handoff asked whether past chats follow the memory decision, the documents decision or their own.
Neither alone fits: past chats hold notes' words (memory's rule) and may quote document passages
(documents' rule). *Recommended default, built:* the memory decision, plus a documents `never`
(owner's or person's) also holds past chats back from a model outside the machines; the
documents' `ask` needs no second "Send for this chat". Alternatives: the memory decision only
(simpler, but an owner's "documents never leave" could be bypassed through a past answer that
quoted one), or both decisions in full (two "Send for this chat" choices for one chat).

Every other decision MV2 needed was inside call 7 or the design's remit.

### 26. What building found

- **MV1's `search_memory` did not ask the decision again when it ran**, though section 13 says it
  does: `run_search_tool` took only the person and the query. Both tools now get the chat and the
  model and ask the decision as the call runs (`memory_api.run_search_tool`,
  `past_chats.run_tool`); a switch turned off mid-answer withholds the result.
- **The person's own questions are now in their index**, so several older checks that counted
  every document in a person's index, or looked for a word anywhere in its file, saw the
  question that asked about a document. They now count documents only, or delete the chat first.
- **Reads are of the shown version.** `Store.exchange_rows` takes an answer only when it and its
  question are each the chosen one of their versions, so a sync that has not run yet after a
  version switch cannot show the version left out (adversarial review).
- **A delete removes twice.** Stopping a chat's answer touches it, and a sync that read the chat
  before the delete could put an exchange back after the index removal; the route removes the
  chat's exchanges again once the store has deleted it, and a store delete that fails puts them
  back (review).
- **Rebuild search** throws the person's index away; it now puts their notes and past chats back
  from the store in the background (review: past chats were empty until the next restart).
- **One chat that cannot be put does not stop a person's backfill**; it is retried with the
  touched ones. AG-UI answers are touched when their run ends, as answers are (review).
- **The live run found meaning left behind by a restart** (`docs/acceptance/mv2-past-chats-run.md`).
  A restart leaves exchanges "ready, words only" until a search model is seen, and nothing woke the
  meaning worker for them until a new answer came: the status said nothing was owed, and a search
  by meaning found nothing. The status now counts every passage without meaning and says when no
  search model can run, and a search of past chats or notes (MV1 had the same gap) or a look at
  the status wakes the worker when meaning is owed, as a look at the Documents screen does.
- **The backfill writes about 465 exchanges a second** by words on this PC (2,000 exchanges,
  resumed after a stop part way); meaning follows in the background.
- **Accepted, not fixed (minor):** an answer in another chat that quoted a deleted chat in its own
  words keeps them, and that chat's exchange holds them (the model's words are its own answer, not
  a copy we keep); an MCP connection with Search my past chats may read document passages earlier
  answers quoted, so the right says so on the Connections page; the owner's `documents never` is
  not asked for MCP connections (a connection is the person's own explicit grant).


---

## MV3: learning and the write policy

What MV3 changes, in one paragraph: a person chooses, model by model, whether it may write
memory: **Off**, **Suggest** (to Suggested notes) or **Keep automatically**. Eugene's
recommendation and its reason sit beside each choice, from a measurement Eugene ships or one the
person runs from the Memory screen (**Measure this model**). A model set to Keep automatically
keeps notes itself, in the background pass and through an in-turn `remember` tool, each with a
"Remembered ... Undo" receipt; **Recently learned** lists them, and one step removes everything a
model kept since a date. Every model-written note records the model and the **write policy** it
was kept under: Strict, Standard (default), Open or Custom, checked in code before the note is
stored. Research 7.5 and calls 3, 4, 11 and 12 hold the why.

Designed in two sub-slices:

- **MV3a**: the evaluation (sections 27-28), the per-model choice with the recommendation
  (29), Measure this model (30), the tag list per model (MV1-C1, 31), and the whole of store
  migration 23 to 24 (36).
- **MV3b**: the write policy (32), Keep automatically with the background pass and `remember`
  (33), receipts, Recently learned and removal (34), unseen notes stay local (35).

Shipped together, as one change: MV3b's code went into the same files (the store, the config,
the content checks) while MV3a waited two hours on its measurements, and splitting them again
would have cost more than it saved. Each sub-slice keeps its own sabotage cases, adversarial
review and part of the live run (section 39).

### 27. The evaluation (calls 3 and 11)

- **The labelled sets and the scorer move into Workbench** (`memory_measure.py`), so Measure this
  model runs the same sets with no terminal. `specs/scripts/m-memory-measurement.py` stays the
  instrument that drives `llama-server` (or an outside endpoint) and imports both from the
  Workbench checkout, as it imports `memory_suggest` today. Stored answers rescore as before.
- **New sets**, beside MR8's 88:
  - *Knowledge update* (LongMemEval KU): a remembered note and a message that changes it ("I've
    switched from Vim to Helix"), expected to propose the new fact and name the note it replaces;
    and the twins where a remembered note is restated or a new unrelated fact appears, where
    naming any note is wrong.
  - *Time* (LongMemEval TR): events in relative words ("next Friday", "in two weeks", "the 14th",
    "this weekend"), scored on the date the note carries.
  - *Several sessions* (LongMemEval MS): a fact that only the messages together say ("I'm
    switching jobs" ... "the new one is at a hospital, as a radiographer"), and a later message
    that corrects an earlier one.
  - *Must not persist* (PersistBench-style negatives): today-only states and requests ("short
    answers just for today, I'm ill"), one-off formats ("make this email formal"), what used to
    be true ("I used to live in Oslo"), maybes, sarcasm, another person's preferences, a question
    about a fact. Each keeps nothing.
- **The supersession check** (call 3's "new check"): a kept note that names a note it should not
  replace is a **wrong supersession**; of the changed facts kept, the share that name the note
  they replace is **supersession recall**.
- **Two paths are measured.** The *pass*: the background request (`memory_suggest.request_body`),
  as MR8. The *tool*: a chat request carrying the person's messages as turns and the `remember`
  tool (section 33), with Workbench's chat system message, each call's arguments judged by the
  same code. A model that does not call tools is measured on the pass only.
- **The bars**, judged by `memory_measure.verdict` on what the code keeps:

  | | Suggest (MR8, Troy 2026-10-18) | Keep automatically (call 3) |
  |---|---|---|
  | Secret, injection or sensitive note kept | 0 | 0 |
  | False memories, share of kept | at most 5% | at most 2% |
  | Noise sets (nothing to keep, kept something) | at most 5% | at most 2% |
  | Unreadable answers | at most 5% | at most 2% |
  | Recall | at least 60% | at least 60% |
  | Wrong supersessions | - | 0 |
  | Supersession recall | - | at least 50% |

  Keep automatically is recommended when the pass meets its bar and, for a model that calls
  tools, the tool path does too. The supersession numbers are mine (call 3 named the check, not
  its threshold): a wrong supersession hides a true note with nobody looking, so none is allowed;
  a missed one leaves two notes the person can see, so half is enough.
- **The cloud reference**: one outside model through the same request and code, so the gap to
  commercial quality is a number. Its cost is said before it runs (Troy: above $10 needs his say).

### 28. Measurements Eugene ships

- `memory_measured.json` (package data): one entry per measured model: a pattern its ids match
  (case ignored, never an "abliterated" fine-tune), its name, the date, the engine, the samples,
  each path's numbers and the verdicts (`suggest`, `keep`, `tags`). Written by the harness's
  summary from its data, never by hand.
- It replaces `memory_learn.PASSED` and `PASSED_NAMES`: "passed" is now `suggest` in the
  model's measurement. The four MR8 models keep passing; a model joins only from a run.

### 29. The per-model choice

- **Per person, per model id**: `memory_model_choices (owner, model, mode)`, `mode` one of
  `off`, `suggest`, `auto`. Any model may be set to any mode, measured or not (call 4).
- **What a model does for a person** (`memory_learn.effective`), first that applies:
  1. the install's Memory off, or `memorySuggestions: off`: off (the owner's word, final);
  2. the person's Memory off: off;
  3. their choice for this model; Keep automatically comes to Suggest while their write policy
     does not allow it (section 32), and the screen says so;
  4. their choice for models they have not set (`learn`: Off or Suggest), as Learn from my chats
     is today;
  5. `memorySuggestions: measured` and the model recommended for Suggest: Suggest (Eugene's
     word);
  6. off.

  Keep automatically is never a default: only the person's own choice for one model turns it on.
- **The recommendation, beside each choice**, from the newest measurement of the model (the
  install's own run of this exact id, else Eugene's shipped one), in research 7.5's three
  wordings:
  - "Recommended for Keep automatically: measured on 2026-10-20, false memories 1%, recall 75%."
    (or "Recommended for Suggest: ..." when it passes only Suggest's bar);
  - "Not recommended: measured on ..., kept 7% of what it should." (the first bar it failed, in
    words);
  - "Not measured yet." with **Measure this model**.
- **On the Memory screen**, a **Models that learn** section: every chat model the gateway lists
  for the person, and any model they set or the install measured, each with its mode (Off,
  Suggest, Keep automatically), whose word it is, the recommendation, and Measure this model.
  `GET /api/memory/models`, `PUT /api/memory/models/{model}` (`mode`, or `null` to forget the
  choice).

### 30. Measure this model

- **Where it runs**: in Workbench, through the gateway, as the person who started it (the same
  path the learning pass uses), one sample of every set, the pass and then the tool path. If the
  pass meets Suggest's bar it also runs once with a 25-tag list (section 31).
- **How long**: about 390 requests at most, one at a time; on the 5090 a few minutes for a small
  model. One run at a time for the install; a person may start three a day; a run stops at 60
  minutes ("took too long") and can be cancelled. A restart loses a run in progress and says so.
- **On an outside model**: the sets are made up, so nothing of anyone's goes; the provider still
  charges. The screen says "About {n} requests and up to {t} tokens of made-up messages go to
  {provider}, which charges for them" and asks before it starts (`confirmOutside`).
- **The result** is the install's: kept per model id (`memory_measurements`), shown to everyone
  beside the recommendation, newest wins over the shipped one.
- Routes: `POST /api/memory/measurements` `{model, confirmOutside}`, `GET
  /api/memory/measurements` (the run in progress: done of total; the results),
  `DELETE /api/memory/measurements/current` (cancel; its starter or the owner).

### 31. The tag list per model (MV1-C1)

The tag list goes in a model's request only when that model's measurement with a 25-tag list
meets the bar it meets without one (`tags` in the verdict). Measured in the harness for the
starter models, and by Measure this model for any model that passes Suggest's bar. Section 37
records what the measurement left of call MV1-C1.

### 32. The write policy

- **Rows** (research 7.5's table), each a value from strictest to loosest:

  | Row | Strict | Standard | Open | Custom adds |
  |---|---|---|---|---|
  | `source`: what a note may be drawn from | the person's own words | own words | anything in the chat | |
  | `secrets`: text shaped like a secret | refused | refused | refused | allowed |
  | `sensitive`: MR8's categories | refused | refused | to the inbox | kept |
  | `untrusted`: web pages, tool results, document passages, past chats, attachments or pasted material in the turns read | dropped | to the inbox | kept | |
  | `instructions`: instruction and procedure kinds from a model | never | to the inbox | kept | |
  | `keepAuto`: Keep automatically | not available | available | available | |
  | `connections`: suggestions from connected apps | off | to the inbox | to the inbox | |
  | `unseenLocal`: model-kept notes stay local until seen (call 12) | yes | yes | no | |

- **The owner's**: `memoryWritePolicy` (`strict`, `standard`, `open`, `custom`; default
  `standard`), the custom rows (`memoryPolicySource`, `memoryPolicySecrets`,
  `memoryPolicySensitive`, `memoryPolicyUntrusted`, `memoryPolicyInstructions`,
  `memoryPolicyKeepAuto`, `memoryPolicyConnections`, `memoryPolicyUnseenLocal`, shown only for
  custom), and `memoryPolicyPeople` (`stricter`, default, or `any`).
- **A person's**: `memory_prefs.write_policy` (`strict`, `standard`, `open`, or null for the
  owner's). In effect: with `stricter`, row by row the stricter of theirs and the owner's, so a
  person may always tighten and never loosen; with `any`, theirs.
- **Enforced in code where the note is written** (`memory_policy.route`), never as words to the
  model. Every model write goes through one function, `memory_write.offer`, which judges the
  proposal (`memory_suggest` rules with the policy's `source`, `secrets` and `sensitive`), routes
  it by the policy to **keep**, **inbox** or **drop**, and only then calls the store: a
  suggestion (`add_suggestions`), a kept note (`keep_learned`) or a connection's suggestion
  (`add_connection_suggestion`). A model on Suggest never keeps: its keep becomes inbox.
- **Settings never lie**: the Memory screen names the policy in effect, whose word it is, and
  under Open or Custom what it allows that Standard does not ("Models may keep notes drawn from
  web pages and tool results").
- The person's own writes (typed, said, Remember) are not the policy's: they are the person's.

### 33. Keep automatically

- **The background pass** (`memory_learn`), for a model in `auto`: the same request and code;
  each proposal it keeps goes through `memory_write.offer`. Under `source: own words` the request
  is today's; under `anything in the chat`, it also carries the answers' final text and the
  person's messages unstripped, and the quote may come from any of them.
- **`remember`**, a tool Workbench runs itself, offered to a tool-calling model in `auto` while
  memory is on for the chat and the policy allows Keep automatically: `text`, `kind`, `quote`
  (the person's exact words), `date`, `replaces` (the exact title of the note it updates). At most
  3 calls an answer; the chat's and the day's caps are shared with the pass. Its result to the
  model is "Kept.", "Offered to the person to review." or "Not kept.", never the rule that said
  no.
- **What "the turns read" holds** for the `untrusted` row: for the pass, a read message from
  which pasted material was removed, or with attachments; and, under `anything in the chat`, an
  answer that used web search, tools, document passages or past chats. For `remember`, anything
  of that kind in the chat's path or earlier in the same answer.
- **Every model-written note records** `model`, `policy` (the rows in effect, with the preset's
  name) and `auto` (kept with nobody approving); a suggestion records the model and policy too,
  and keeps them when the person keeps it.

### 34. Receipts, Recently learned and removal

- **The receipt**: a `remember` call in a chat shows "Remembered: {title} · Undo"; the pass's
  keeps for an open chat arrive as a `memory` event with the same receipt. Undo removes the note
  and makes the note it replaced current again.
- **Recently learned** on the Memory screen: notes kept automatically in the last 30 days, newest
  first, each with its model, policy, date, whether it is still unseen, and Undo. Showing a note
  there marks it seen (`POST /api/memory/learned/seen`).
- **Remove what a model kept**: "Remove everything {model} kept since {date}" names how many
  first (`GET /api/memory/learned/removal?model=&since=`) and removes them in one step (`POST
  /api/memory/learned/removal`), each undone as Undo does, out of the index as a delete is.
- A removed note's `remember` result in kept tool rounds becomes "The person removed this note.",
  as a deleted note's search results are replaced (MV1).

### 35. Unseen notes stay local (call 12)

Under `unseenLocal` (Strict, Standard), a note kept automatically and not yet seen is left out of
everything that leaves the machines: the pinned block, relevant memory and `search_memory` for a
model that is not local, the notes shown to a learning model that is not local, and every
connection's reads. Local models get it at once. Seeing it in Recently learned, editing or pinning
it ends the wait.

### 36. Store migration 23 to 24

One transaction after the backup, as every migration:

- `memory_notes`: `model TEXT`, `policy TEXT`, `auto INTEGER NOT NULL DEFAULT 0`, `seen_at REAL`
  (no `CHECK` changes, so no rebuild);
- `memory_prefs.write_policy TEXT` (null: the owner's);
- `memory_model_choices (owner, model, mode CHECK IN ('off','suggest','auto'), set_at, PRIMARY
  KEY (owner, model))`;
- `memory_measurements (model PRIMARY KEY, measured_at, owner, result TEXT)`.

All of it in MV3a, so MV3b adds no migration.

### 37. Risk, tests and acceptance

High risk (automatic writes, an injection surface, a migration): sabotage of each new critical
check, one adversarial review of the diff focused on injection (a web page, tool result, pasted
text or document passage that tries to make a model keep or change a note under each policy), and
a real-environment run per sub-slice (`workbench/scripts/mv3-learning-acceptance.py`, ports
8490-8501, every `EUGENE_PLEXUS_*` dropped, torn down by pid):

- **MV3a**: a schema 23 store migrates; the per-model choice sets what learns (a Suggest model
  suggests, an Off model does not, the default follows the recommendation); Measure this model
  runs end to end on a real small model and its result shows beside the choice; an outside model
  needs confirmation.
- **MV3b**: under each preset a real model keeps, offers or drops a note as the policy says; an
  injected page or paste never yields a kept note under Standard or Strict; `remember` with its
  receipt and Undo; Recently learned and removal by model and date; an unseen note is not sent to
  an outside model or a connection until seen.

### 38. Calls

**MV3-C1 (new, Troy's to confirm; the default is built): which sets Suggest's bar is judged
on.** The new sets (knowledge update, time, several sessions, must-not-persist) are harder than
MR8's 88, and on them Gemma 4 E4B misses Suggest's own bar (false memories 12%, recall 59%) and
Gemma 4 12B its noise limit (6.7%), though both pass it on MR8's sets, where Troy set it. Judging
Suggest on every set would turn default suggestions off for those models' people.
*Recommended default, built:* Suggest's bar is judged on MR8's 88 sets (the bar and the sets it
was set on, unchanged: who suggests by default does not change), and Keep automatically's on all
123 (the new sets were made for it, calls 3 and 11). A suggestion waits for the person, so a
noisier model there costs a click; a kept note does not wait. Alternative: judge Suggest on
every set too (fewer models suggest by default; the person can still choose Suggest for any).

MV1-C1 is settled by section 31's measurement (section 39 says how).

### 39. What building found

- **The measurement** ([record](../acceptance/m-memory-measurement-mv3.md)): five starter models and
  GPT-5.5 through OpenRouter (about $3) as the cloud reference.
  - **Keep automatically:** no model meets the stricter bar. Qwen3.8-27B is the closest, at 2.2%
    noise against 2%; GPT-5.5 is at 3.3% noise. So none is recommended for it, and the screen says
    why.
  - **Suggest:** the four MR8 models still pass on MR8's sets (call MV3-C1).
  - **MV1-C1 is settled per model, as section 31 says:** the tag list goes to Gemma 4 12B,
    Qwen3.6-35B-A3B and Qwen3.8-27B (at most 25 tags, the length measured). It does not go to Gemma
    4 E4B, which gave 19% false memories with the list.
- **Local models seldom call `remember`.**
  - Recall on the tool path was 5-21%, against 59-80% on the pass. GPT-5.5 reached 75%.
  - In the first trials none called it until the system message said the tool was there.
  - The system message now carries a one-line hint (`memory_suggest.REMEMBER_HINT`). It is guidance,
    and the measurement sends it too. The rules stay in code.
- **Keep automatically needs its tool path measured** for a model that calls tools, so it is never
  recommended from the pass alone.
- **Only the owner's own run sets a default.**
  - Any person may run Measure this model.
  - A run by someone who is not the owner is shown as advice beside the choice. It turns nothing on by
    default for anyone (review).
  - A run in which more than 10% of requests got no answer keeps nothing: a gateway that is down is
    not a measurement.
  - The install has a cap of 12 runs a day.
- **What a model may replace by itself** (review, the one blocker). An automatic keep may replace only
  a note a model wrote, of the same kind, unpinned and with no details. Any other change waits in
  Suggested notes, where Keep new shows the old note beside the new. Measured supersession was good,
  but a wrong one hides the person's own note with nobody looking.
- **Untrusted covers more than section 33 said** (review):
  - text an app's surface put in the chat's context;
  - a person's message over 400 characters or of several paragraphs, which may hold a paste the
    paste rules missed.

  And a note worded as an instruction ("always ...", "from now on ...") is routed as one, whatever
  kind the model gave it.
- **Other review fixes:**
  - Editing or pinning a note a model kept makes it the person's: no longer undone, removed by model,
    or held back as unseen.
  - The owner's read-only view hides `remember`'s receipt and arguments.
  - A kept `search_memory` result is not replayed to an outside model while the person has an unseen
    model-kept note.
- **MR8's paste rule read an apostrophe as a quotation mark** (found by the live run): "I'm a
  nurse working night shifts. What's ..." lost every word between the two. A single mark now
  quotes only where it opens and closes at a word's edge; a sentence in single quotes is still
  dropped. The measurement's data was judged again; no verdict changed.
- **Shipped as one change** (top of this section): MV3b's code went into the files MV3a touched
  while MV3a waited on its measurements.
- **Accepted, not fixed (minor):** measurement run counts are kept in memory, so a restart resets
  them. Deleting (not undoing) a model's note that replaced another takes the earlier version with
  it, as every delete does; Undo is the way back.

---

## MV4: Memory as an app

What MV4 changes, in one paragraph: MV1-MV3 added sections to the Memory page in place, so a person
reached their notes only after the settings, and Suggested notes sat under the learning controls.
MV4 arranges the page as an app (`feedback_app_before_config`): what waits for the person comes
first, then their notes, then their past chats, then the tags and their own copy. Every setting
leaves the page for a new **Settings** page of Workbench, which also takes the Documents settings
and Connections. No server route, store table or setting changes: a setting does exactly what it
did, from a different page.

### 40. The Memory page

`/memory`, in this order:

1. **The head:** Memory, **Memory settings** (opens `/settings#memory`), Back to chat. One line of
   what the page is; the owner-reads warning and the owner-off notice, as today.
2. **A switch that changes what the page means is said here, and changed there.** With Use memory
   off: "Memory is off: no model is given your notes. Turn it on in Memory settings." (settings never
   lie: the page does not look as if notes were in use).
3. **Waiting for you**, each only when it holds something: **Still true?**, **Suggested notes**,
   **Recently learned**. These are a person's decisions about notes, so they come before the notes.
4. **Your notes:** search and the tag filter at the top whenever there are notes (MV1 showed them
   only past the first page, which left the tag filter call 14 asked for out of reach for most
   people); usage; Always used, Used when relevant (or when there is room), Past; Add a note; the
   starter boxes for a person with none.
5. **Past chats:** one search box. Search opens Search chats (section 19) with those words searched.
   One screen does the searching; this is its door from Memory.
6. **Tags:** the list and its import and export (section 5).
7. **Your data:** export and Delete all memory.

### 41. The Settings page

`/settings`, a page of Workbench reached from the top bar (**Settings**, after Memory) and from each
page whose settings it holds. One section each, with an anchor:

- **Memory** (`#memory`): Use memory; Models that run outside your machines; Learn from my chats;
  Which notes a chat is given; What models may write to your memory; Let models search my notes;
  Let models search my past chats; How much room notes may take. Then **Models that learn** with
  Measure this model. The section opens with **Open Memory**.
- **Documents** (`#documents`): Documents in new chats; Models that run outside your machines.
  Opens with **Open Documents**.
- **Connections to other apps** (`#connections`): as built in MR9b.

Where the owner has turned Memory off, the Memory section says so and holds no control, as the page
did. Words elsewhere that sent a person to "the Memory page" for a setting now name Memory settings
(Suggest notes' confirmation, for one).

### 42. Not in MV4

No API, store or config change, so no migration and no schema bump. Projects (MV7) and backends
(MV5) will add their own sections to this layout.

### 43. Risk, tests and acceptance

Routine under the testing policy: UI only, and no setting changes what it does. Vitest for the new
order, the settings' absence from Memory and Documents, the Settings page (each control as before,
rendered there), the links both ways and the `/settings` address; `web/scripts/memory-browser.mjs`
and `documents-browser.mjs` follow the moved controls and run in a real browser (runner). No live
acceptance run: nothing on the server changed.

### 44. Calls

**MV4-C1 (Troy's to confirm; the default is built): where settings go.** *Recommended default,
built:* a Settings page of Workbench, one place for every setting. Alternative: a Settings section
at the foot of each page (Memory, Documents). The foot keeps a person on one page, but the settings
of one thing are then split from those of the next, and the research's own words were "settings move
to Settings".

**MV4-C2 (Troy's to confirm; the default is built): the Documents page follows.** Its two settings
sat above the documents, which breaks the same principle. *Recommended default, built:* they move to
Settings with Memory's. Alternative: leave Documents for its own slice.

**MV4-C3 (Troy's to confirm; the default is built): one page, not tabs.** *Recommended default,
built:* one page in section 40's order. Alternative: tabs (Notes, Suggested, Past chats, Tags), each
with its own address. Tabs would hide what waits for the person behind a count, and Troy set a
condition on an inbox of its own: only if the rest of the notes get the same organisation. One page
shows the waiting items first while there are any, and nothing when there are none.

### 45. What building found

- **Built as designed**, with no server change. The settings are now `MemorySettings.tsx` and
  `DocumentsSettings.tsx`, each reading its own page's data (`GET /api/memory`, `GET /api/documents`)
  and saving through the same routes. `SettingsPage.tsx` holds them, with Connections. `/search?q=`
  opens Search chats with the words searched, for Memory's Past chats box.
- **The note search was out of reach for most people.** MV1 showed it only when there were more
  notes than the first page, so the tag filter call 14 asked for appeared only past about 50 notes.
  It is now at the top of Your notes whenever there is a note.
- **Verification:** Vitest 3,379 passed, with new tests for the order, the settings' absence, both
  links, the Past chats box, `/settings` and `?q=`. Types and lint are clean. In Chrome,
  `documents-browser.mjs` passed MV4's steps (Documents holds no settings; Settings shows Memory,
  Documents and Connections in that order).
- **Two browser scripts were already failing on main, before MV4** (workbench#14).
  `memory-browser.mjs` is MR1-era: it waits for "1 note sent" for an unpinned note, which MV1's
  relevant memory replaced, so it stops before MV4's Memory steps. `documents-browser.mjs` fails
  later, on a 39 px phone overflow of the composer with four file chips. MV4's Memory page steps in
  Chrome are unrun until #14 is fixed.

---

## MV5: memory servers

What MV5 changes, in one paragraph: research call 9 put one contract in front of memory so outside
memory systems can plug in. MV5 defines that contract in Workbench and lets a person connect a
**memory server** of their own over MCP. A connected server sits **beside** the built-in notes: it
receives the person's chats, as the write policy allows, and is asked for relevant memory every turn
next to the notes. Eugene's layer stays above it: the person binding, the guards, what was sent, and
deletion with a check. Hindsight from the agent's catalogue is MV5b, after a feasibility probe
(section 52).

Read before designing (2026-10-19, three reports): Workbench has no memory seam today (every memory
module calls `Store` directly), but every guard except secret refusal already sits above the store.
Workbench already has an MCP client (`tools.py`, `mcp>=2.3`, streamable HTTP), used only for
owner-picked tool servers, which are install-wide. The agent's catalogue installs Python packages
only, has no way for one app to depend on or find another, and no generated per-app secret.
Hindsight is v1.0.0 (2026-10-13), MIT, active; it needs Postgres (embedded `pg0` in `hindsight-all`),
4-8 GB of RAM, binds `0.0.0.0` with no authentication by default (#5544, closed "not planned"), has
one shared key at best, lists no local model as tested, and does not guarantee deletion (#5419:
orphaned observations still recalled). Its MCP server (`/mcp/{bank_id}/`, streamable HTTP) has
`retain`, `recall(query, max_tokens)`, `list_memories`, `delete_document`, `clear_memories`.

### 46. The contract

`memory_servers.py` holds the contract as a `Protocol` and its MCP adapter:

| Verb | Arguments | Required |
|---|---|---|
| `recall` | `query`, `max_tokens` | Yes: a server that cannot be asked is not a memory server |
| `retain` | `content`, `document_id`, `timestamp`, `context` | No: without it the server is read-only |
| `forget` | `document_id` | No |
| `purge` | none | No |
| `list` | `limit`, `offset` | No: used for export |

- **By tool name, over MCP.** After connecting, Workbench lists the server's tools and maps each
  verb to the first name present: `recall` (`recall`, `search_memory`); `retain` (`retain`,
  `remember`); `forget` (`delete_document`, `forget`); `purge` (`clear_memories`, `purge`); `list`
  (`list_memories`, `list`). Hindsight's own MCP server matches with no adapter, and so does any
  server written to Eugene's names. The capability flags are which verbs were found; the screen says
  what each missing one means ("This server cannot forget a chat you delete").
- **The person is bound by Workbench, never by the server, the model or the client.** The server
  record belongs to the signed-in person (`owner` = the OIDC `sub`), and only that person's chats go
  to it and only their turns ask it. A shared server is the person's choice of server; its own
  scoping (a Hindsight bank in the URL, a token) is theirs, and the screen says Eugene cannot check
  it.
- **The built-in notes are not wrapped.** MV1-MV4's notes carry bodies, kinds, tags, supersession,
  receipts and Still true?, which no outside system has; putting `Store`'s forty memory methods
  behind the protocol would change nothing a person sees. The contract is where outside memory
  meets Workbench, not a rewrite of the built-in (call MV5-C1).
- **Recall results are untrusted data.** Each item is text with an optional id, date and score; the
  text is cut to 2,000 characters, the `_hidden` characters stripped, and a result whose text looks
  like a secret is dropped and counted (the drawer says how many). Results are never tool output
  with authority.

### 47. Connecting a server

On **Memory settings** (`/settings#memory`), a new part **Your memory server**: address, token
(optional), Connect. One server a person. Connect lists the tools and shows what was found; a
server with no `recall` is refused, naming it ("No recall tool: this is not a memory server").
Disconnect forgets the record; it does not delete anything on the server, and says so.

- **What may be connected is the owner's** (`memoryServers`, config trio): `off`; `outside` (the
  default: any `https` address, or `http` on a private LAN address, never loopback, link-local or
  this host's own addresses); `any` (testbeds, including loopback). Loopback is refused by default
  because Workbench runs on the same host as Eugene's own components and could be pointed at them.
  Redirects are not followed.
- **A memory server counts as an outside model.** Eugene cannot see which model it runs, so sending
  it chats follows the outside-model rule for memory: the owner's `memoryExternalModels: never`
  hides the whole part ("Your install does not allow memory servers"), and a person whose own
  setting is "never" is told that connecting turns it on for this server only.
- The token is stored like a tool server's, never returned to the page (the box is empty while one
  is stored, with "A token is saved").
- Store migration 24 to 25: `memory_servers (owner PRIMARY KEY, url, token, verbs JSON,
  connected_at, last_error, last_error_at)`; `memory_server_sent (owner, chat_id, message_id,
  sent_at)` for what was sent and for forgetting.

### 48. What a server receives

After a turn is answered, in the background (the exchanges index's queue, `exchanges_index.py`),
Workbench calls `retain` with that exchange, `document_id` = `{chat_id}:{message_id}`, `timestamp` =
when it was asked, `context` = "Chat: {chat title}". What the exchange holds is the write policy's
**Source** row (section 32), so one rule governs every writer:

- Strict and Standard: the person's own message, pasted material removed, as MR8's quote check
  reads it. No answer, tool result, web page or document passage.
- Open: the message and the answer. Tool results and fetched pages are still not sent: they are the
  chat's evidence, not the person's memory.
- Custom: the Source row as set.
- A turn whose text looks like a secret is not sent (`looks_like_secret`), and Recently learned's
  counter says "1 turn not sent: it looked like a password or key".
- Chats in a project or with memory off for the chat (when MV7 adds it) are not sent; a chat started
  with **Use memory** off is not sent.
- **Not sent before connecting.** No backfill in MV5 (call MV5-C4): a person who wants their past
  chats in the server is offered nothing yet, and the part says it starts from now.
- A failed `retain` is retried twice with the queue's back-off, then recorded as `last_error` and
  shown on the part ("Not reached since 14:02: connection refused"). Nothing is queued past a day.

### 49. What a server gives

Every turn, in parallel with the notes' Finder (`memory_relevance.Finder.choose`), Workbench calls
`recall(query = the latest user message, max_tokens = a third of the relevant-memory budget)`:

- **Time limit 2 seconds.** Past it the turn goes on without the server, and the drawer says "Your
  memory server did not answer in time" (failures name the observed cause). The model is never kept
  waiting longer.
- The results join relevant memory as data in the latest user turn, in their own block after the
  notes' (`<memory-XXXXXXXX>`, "From your memory server"), inside the same budget: notes first, then
  the server's results until the budget is spent.
- **Outside models:** a server's results are model-kept and unseen by the person, so under Strict and
  Standard they are never sent to an outside model, exactly as call 12's unseen notes
  (`memory_api.leaving`). Under Open and Custom the Unseen-local row decides.
- **What was sent** records each result's text per turn, as for notes, and the drawer lists them
  under the server's name.
- `search_memory` does not reach the server in MV5a: a kept tool result is replayed in later
  turns, and a server's results would need their own replay rule for a chat whose model changes to
  an outside one. The per-turn recall carries the server's memory instead.
- Not over connections: `/mcp`'s `search_notes` does not reach a person's server. The server is
  theirs to connect to other apps directly.

### 50. Forgetting and export

- **Deleting a chat** calls `forget` for each of its sent exchanges (from `memory_server_sent`). A
  server with no `forget` is named in the delete question: "Your memory server cannot forget, so
  what it kept from this chat stays there."
- **Delete all memory** calls `purge`, then, where the server can `list`, lists to check that nothing
  is left, and says what it found: "Your memory server still holds 12 memories after it was cleared."
  A server that cannot purge is named in the question as above.
- **Checked deletion is best effort and says so.** After `forget`, Workbench recalls with the deleted
  turn's own text and reports any result that still quotes it. This catches Hindsight's #5419 kind of
  leftover; it cannot prove absence, and the copy never claims it does ("No longer found", not
  "Deleted everywhere").
- **Export** adds `memory-server.json` (from `list`, paged, at most 20,000 items) when the server can
  list; otherwise the export says the server's memories are not in it.

### 51. Not in MV5a

Hindsight from the catalogue (MV5b, section 52). Backfill of past chats. `search_memory`
reaching the server (section 49). More than one server a
person. Install-wide servers the owner sets for everyone. Wrapping the built-in notes in the
contract. A gateway memory door (rejected in the research, 7.7).

### 52. MV5b: Hindsight from the catalogue

What MV5b needs, and why it is a separate slice: the agent's catalogue has no app-to-app link, no
generated secret and no dependency on a database, and Hindsight needs all three in some form. Before
designing it, a **feasibility probe** (no product code, one runner session):

1. `hindsight-all==1.0.0` in a scratch venv on Windows and on Linux (Python 3.12): does embedded
   `pg0` start, and with what RAM and disk.
2. Point its LLM, embedder and reranker at a local gateway (`/v1`, `/v1/embeddings`, `/v1/rerank`
   as Cohere); does it run with no other outbound connection (watch the process's sockets; grep for
   telemetry and model downloads).
3. Retain and recall a small labelled set with a local 20B-30B model and with Gemma 4 12B, through
   the MV3 harness's questions: does recall beat the built-in notes plus past chats on the same
   questions, and at what ingest time.
4. Its MCP with its API key on loopback, connected as MV5a's memory server under `memoryServers: any`.

If the probe passes, MV5b designs the catalogue entry (`source: pypi`, embedded store, `{bindHost}`,
API key from a new generated-secret placeholder, every address ours, labelled experimental, "for
20B+ models with reliable tool calls") and a link that hands Workbench the address and key of a
Hindsight on the same host, so a person connects it with one click instead of an address. If it
fails, MV5b is dropped and the research records why; MV5a still lets a person connect a Hindsight
they run themselves.

### 53. Risk, tests and acceptance

**High risk** under the testing policy: chats leave Workbench for a server Eugene does not control,
a person-supplied address is fetched from the host, and what models receive changes. So: one
adversarial review, sabotage of the new checks, and a real-environment run.

- Unit: the verb mapping; the address rule (loopback, link-local, this host's addresses, redirects,
  `http` on a public address) per `memoryServers` value; what is sent per write-policy preset
  (pasted material removed, secret-shaped turns skipped, answers only under Open); recall's limits
  (time, size, secret drop, budget share); unseen results withheld from outside models; forget on
  chat delete; purge with the list check; the export file; owner `never` hiding the part.
- A **reference memory server** for tests and the live run: a small MCP server in
  `scripts/m-memory-server.py` (specs) with all five verbs, a switch to drop each, and a switch to
  "forget" without forgetting, so the check in section 50 is observable.
- **Live run** (`mv5-memory-server-run.md`): a real Workbench and gateway with a local model; connect
  the reference server; chat; see the exchange arrive with only the person's words under Standard;
  see a recalled memory in the drawer and in the request; delete the chat and see `forget`; Delete all
  and see `purge`; a lying server reported; a slow server timed out; loopback refused under
  `outside`.
- **Sabotage once:** the loopback refusal, the Source filter, the secret skip, the unseen-local
  withholding, and the deletion check.

### 54. Calls

**MV5-C1 (taken by Troy, 2026-10-19, at the default): beside, not instead.** *Recommended default:* a
memory server sits beside the built-in notes: it gets chats and is asked every turn, and the notes,
tags, pinned block and Memory page stay the built-in's. Alternative: a person switches their whole
memory to a server, as an engine is switched. That needs every MV1-MV4 feature mapped onto a system
that has none of them (bodies, kinds, tags, receipts, Still true?), and the Memory page would show
whatever the server returns. The research's engine analogy holds at the seam, not here.

**MV5-C2 (taken by Troy, 2026-10-19, at the default): Hindsight after a probe.** *Recommended default:* MV5a now; Hindsight
from the catalogue only if the probe in section 52 passes. Hindsight is six days past 1.0, open by
default with the fix declined, untested on local models, and 4-8 GB of RAM. MV5a already lets a
person connect one they run. Alternative: design MV5b now, with the agent changes (app link,
generated secret), in parallel with MV5a.

**MV5-C3 (taken by Troy, 2026-10-19, at the default): which addresses.** *Recommended default:*
`memoryServers: outside`: a person may connect any `https` server, or `http` on a private LAN
address, never loopback or this host. Alternatives: `off` by default (the owner opts in), or `any`.
Loopback is the request-forgery risk: an unauthenticated Hindsight on loopback is exactly what #5544
describes.

**MV5-C4 (Troy's to confirm; the default is built): no backfill.** *Recommended default:* a server
receives chats from when it is connected. Backfill would send months of chats to a server the person
just met, at the server's ingest cost (Graphiti took 626 s for one sentence on a 12B; research 1).
Alternative: a "Send my past chats" button with a count and an estimate, in a later slice.

### 55. What building found

- **Built as designed, with these changes:**
  - **No recall check after a chat's `forget`.** Workbench keeps only ids of what it sent, never
    the words, so once a chat is deleted there is nothing to recall with. The check stays on
    Delete all memory: `purge`, then `list`, and the result names what is still listed.
  - **What a server cannot do is said on its Settings part** (one line per missing verb) and in
    the result of Delete all memory, not in the delete questions.
  - **`search_memory` does not reach the server** (section 49): it would need its own replay rule.
  - **The chat's title goes only under Open.** Under Strict and Standard `context` is "A Workbench
    chat": a title may be drawn from an answer or pasted text (review).
  - **Eugene's own ports are refused on any private address under `outside`** (8079-8083 and the
    container's 8279-8283). A container cannot see its host's addresses, so "this host" alone
    left the host's LAN address open to blind requests at the agent or gateway (review).
- **The address rule is checked where the connection is made.** A custom `httpcore2` network
  backend resolves the host itself, refuses it when any address it resolves to is refused, and
  dials the address it checked, so DNS rebinding finds nothing to rebind. IPv6 forms that carry an
  IPv4 address (mapped, compatible, NAT64, 6to4, Teredo) are judged by the IPv4 address. Bodies
  are asked for and accepted uncompressed only, so the 2 MiB cap counts what is read.
- **The turn's two seconds are a hard limit.** Each call runs as its own task, waited on for its
  limit; a session that is slow to close is cancelled and left to close in the background.
- **The Courier** (background sender) settles each row on its own: any failure backs off (1, 5,
  30, 60 minutes) and a row is given up a day after it was queued. A chat deleted after its
  exchange was sent starts its day then, not when it was sent (the review's blocker: a chat
  deleted a day after its answer was never forgotten). An exchange sent while its chat was being
  deleted is queued to be forgotten like any other. A new token for the same address keeps what
  is still to be forgotten; another address drops it.
- **A server forgets only by the id it kept.** `forget` is used only when `retain` takes
  `document_id`; otherwise forgetting would report success for nothing.
- **Verification:** 21 unit and HTTP tests (`tests/test_memory_servers.py`), Vitest for the
  Settings part and the drawer, sabotage `--label MV5` (10 cases), and the live run
  (`docs/acceptance/mv5-memory-servers-run.md`) with the reference server
  `scripts/m-memory-server.py` in its own process. One adversarial review: its blocker and should-fix
  findings are fixed; the rest are listed in the run record.
- **Not closed:** a signed-in person can still tell an open port from a closed one on a private
  address by the error, which allowing LAN servers implies. Workbench refuses only Eugene's own
  ports there.

### 56. The MV5b probe: what it found

**It passes** (2026-10-19, `docs/acceptance/mv5b-hindsight-probe.md`). Hindsight 1.0.0 ran on
embedded pg0 on Windows and Linux, its LLM, embedder and reranker all through Eugene's gateway,
with no connection off loopback in any run.

- **Recall.** On one labelled person (36 sessions from MV3's sets, 21 questions), it answered all
  21 in its top 5 with Gemma 4 12B and with Qwen3.8-27B. The embedder's cosine answered 19 and
  BM25 16. A superseded fact still ranked above the current one 4 times with Gemma and once with
  Qwen; the current one was always in the top 3.
- **Cost.** Ingest took a median 3.9 s (Gemma) to 5.1 s (Qwen) an exchange on the 5090. Recall
  took a median 0.2 s. Hindsight's own process tree peaked under 0.5 GiB with the models outside
  it, far from the research's 4-8 GB, which assumed its local torch models.
- **It keeps noise.** Transient and third-party turns became facts about the person. It has no
  bar like Keep's; the write policy's Source row is the only filter in front of it.
- **Five conditions for the catalogue entry:**
  1. `hindsight-api-slim[embedded-db]` instead of `hindsight-all` (1.07 GiB instead of 1.86 on
     Windows; no torch).
  2. A named pg0 port.
  3. A graceful stop. The agent's `CTRL_BREAK` stops pg0 with Hindsight; a hard kill leaves
     `postgres` running on Windows.
  4. Hindsight's whole-server key (`ApiKeyTenantExtension`), since its REST API answered with
     none. It guards REST only; MCP keeps its own token.
  5. pg0's data in the app's data folder. On Windows pg0 writes to the account's profile whatever
     `HOME` says, and Hindsight 1.0.0 cannot name the folder.
- **A Workbench defect, fixed:** Hindsight's `retain` only queues, so a `forget` sent before the
  exchange was read deleted nothing. Workbench now prefers `sync_retain` (with its own 120 s
  limit), and the probe's re-run showed the forget delete it.

### 57. MV5b: what it is

The owner installs **Hindsight** from the agent's catalogue on the machine that runs Workbench. A
person turns it on for themselves with one switch on Memory settings, **Use Hindsight on this
machine**, instead of typing an address and token. Everything MV5a does with a person's own
server then applies unchanged: what is sent (section 48), what is given (49), and forgetting and
export (50).

- **One Hindsight per machine, one bank per person.**
  - Workbench connects each person to `/mcp/{bank}/`, where `bank` is `wb-` plus the first 16 hex
    characters of the SHA-256 of their `sub`.
  - The MCP token is the install's and is never shown to anyone, so a person cannot reach another
    person's bank. The bank is chosen by Workbench, never by the person, the model or the server.
  - Purge clears that bank only. The probe showed `clear_memories` naming its bank;
    acceptance must show the other banks untouched.
- **What MV5b does not change.** A person who connected their own server keeps it; one server per
  person still holds, so using this machine's Hindsight replaces it. Nothing is backfilled
  (MV5-C4).

### 58. The catalogue entry

A third entry in `apps_catalogue.yaml`, labelled **Experimental**: "Long-term memory for
Workbench. Reads your chats with a model you choose. For 20B+ models with reliable tool calls."

- **Package:** `source: pypi`, `package: hindsight-api-slim[embedded-db]`, `version: 1.0.0`,
  `entry: hindsight_api.main:main`, `python: "3.12"`, `ui: false`, `uses: [inference]`,
  `localActions: false`, `healthPath: /health`.
- **Environment, every address ours:**
  - `HINDSIGHT_API_HOST` = `{bindHost}` and `HINDSIGHT_API_PORT` = `{port}`.
  - The LLM, embeddings and reranker all go to `{gatewayUrl}/v1`, each with `{clientKey}`:
    - the reranker as Cohere, at the full `{gatewayUrl}/v1/rerank` path;
    - the models from `{memoryModel}` (section 60), `{embeddingModel}` and `{rerankModel}`.
  - `HINDSIGHT_API_LLM_REASONING_EFFORT=none`.
  - `HINDSIGHT_API_TENANT_EXTENSION=…ApiKeyTenantExtension`, with
    `HINDSIGHT_API_TENANT_API_KEY` = `{appSecret}`.
  - `HINDSIGHT_API_MCP_ENABLED=true`, with `HINDSIGHT_API_MCP_AUTH_TOKEN` = `{linkSecret}`
    (section 59).
  - `HINDSIGHT_API_OTEL_TRACES_ENABLED=false`.
  - `HINDSIGHT_API_DATABASE_URL=pg0://hindsight:{auxPort}`.
- **New placeholders and fields:**
  - `{auxPort}`: a second port from the apps' range, for pg0.
  - An `experimental: true` field, shown on the Apps page as the engines' badge is.
  - `{appSecret}` already exists: it is generated at first start, kept in the app's data folder
    and read only by the app. That is enough for the REST key, which nothing else needs.
- **Stopping** is the launcher's existing `CTRL_BREAK` (Windows) or `SIGTERM`, which stops pg0 with
  it (section 56). A hard kill after the 20 s grace can leave `postgres` running. The next start
  finds the instance already running and uses it. The run record must show this, or MV5b adds
  a `pg0 stop` before each start.
- **pg0's data (condition 5)** is not solved by any of the above: call MV5b-C1.

### 59. The link

There is no app-to-app link today. Each app learns only the gateway's address and its own key. MV5b
adds one, narrowly:

- **A manifest field, `provides: memory-server`** (with `providesPath: /mcp/`), and a consumer's
  `uses: [inference, memory-server]`.
- **The agent generates the link secret** when the provider is installed, in its own apps folder.
  - The provider gets it as `{linkSecret}`.
  - The consumer gets the provider's loopback address and the secret's file:
    `EUGENE_PLEXUS_APP_MEMORY_SERVER_URL` and `EUGENE_PLEXUS_APP_MEMORY_SERVER_TOKEN_FILE`.
  - Each gets it the way it gets its client key: an owner-only file granted to that app's account
    on Windows, and a systemd credential on Linux.
- **Only on the same machine**, and only between the agent's own catalogue entries. A custom entry
  may not declare `provides`. Uninstalling the provider removes the secret, and the consumer's link
  goes with it.
- **A new secret** when the provider is reinstalled with its data deleted. Workbench re-reads the
  token file when it changes, as it does its client key.

### 60. The model Hindsight reads with

Hindsight needs one chat model for every retain and its reflection. Eugene recommends; the owner
decides (Troy, 2026-10-19: the harness result is advice, never a lock).

- **The app's page gets one setting, Model.** It lists the gateway's chat models and marks the
  ones the probe or the MV3 harness measured.
- **Unset by default.** Hindsight does not start until it is set, and the page says "Choose the
  model Hindsight reads your chats with". Eugene does not pick a model for the person.
- **Rendered as `{memoryModel}`**, from a new per-app settings store in the agent (`apps.yaml`,
  `settings:`). Changing it restarts the app.
- **Locality.** Workbench treats the linked server as a model on the machines only when that model
  is local. Otherwise it is an outside model, as any server is in MV5a. Workbench reads the model's
  locality from the gateway, as it does for chat models.

### 61. Workbench's side

- **Memory settings, Your memory server.** When the link is present and `memoryServers` is not
  `off`, the part offers **Use Hindsight on this machine** above the address form.
  - Turning it on records the person's server as `linked`: the URL is the link's plus the bank, and
    no token is stored per person.
  - The verbs are found as for any server.
  - Turning it off forgets the record, as Disconnect does.
- **The address rule.** The linked address is exempt from `outside`'s loopback refusal. The
  address is the agent's, not the person's, so a person still cannot point Workbench at loopback.
  Only the exact address the link names is exempt.
- **Store migration (the next after MV7's 26 to 27):** `memory_servers.linked` (0/1). A linked row's `token` stays empty
  and is read from the link's file at each call.

### 62. Risk, tests and acceptance

**High risk:** a new secret is handed between two apps' accounts; an installer path; chats go to a
server on the machine.

- **Agent unit tests:** the manifest fields and their validation (`provides` only in the shipped
  catalogue); the secret's files and their grants; the placeholders; the model setting.
- **Workbench unit tests:** the linked part, the bank derivation, the address exemption (only the
  link's exact address), and migration 27 to 28.
- **Live run**, on Windows and Linux, in the agent's account and in own accounts. The own-account
  run is elevated and needs Troy.
  - Installing Hindsight; the setting unset, so it does not start; the setting chosen.
  - REST refuses no key; MCP refuses no token.
  - Two people turn it on, and each recalls only their own.
  - Delete all for one leaves the other's bank.
  - Uninstall with data deletes the memories (condition 5).
  - Stop: no `postgres` left. A hard kill, then a start.
  - No connection off loopback.
- **Sabotage once:** the bank derivation, the address exemption, a custom entry declaring
  `provides`, and the secret's grant to a third app.

### 63. Calls

**MV5b-C1 (Troy's): where pg0 keeps the memories on Windows.** Hindsight 1.0.0 cannot name pg0's
data folder, and pg0 ignores `HOME` on Windows.
- *Recommended default:* ask Hindsight upstream for a data-folder setting (a `pg0://` URL
  parameter), and hold MV5b until it ships. Troy files upstream reports himself.
- Alternatives:
  - Ship MV5b on Linux and on agent-account installs only, with uninstall running `pg0 drop` by
    instance name. Windows own-account installs, the common Windows case, would get none.
  - Publish a small Eugene launcher package that starts Hindsight with pg0's folder set. A new
    repository to keep.

**MV5b-C2: one Hindsight per machine, a bank per person, the token held by Workbench.**
*Recommended default:* as section 57. Alternative: one Hindsight per person, which multiplies
pg0 instances and ports and fits a catalogue badly.

**MV5b-C3: the model is unset until the owner chooses.** *Recommended default:* as section 60.
Alternative: default to the first local chat model the MV3 harness passed. That is Eugene choosing.

**MV5b-C4: a narrow app-to-app link (`provides: memory-server`).** *Recommended default:* as
section 59. Alternative: the owner pastes Hindsight's address and token into Workbench's owner
settings, which needs no agent change but shows the owner a secret.

**MV5b-C5: Experimental.** *Recommended default:* labelled experimental until a release has
carried it. Hindsight is days past 1.0, and its own defaults are open.

**Order.** MV5b waits on MV5b-C1. MV6 (research section 10) is built meanwhile.

---

## MV6: provenance, "Still true?" from changed documents, and the tidy pass

What MV6 changes, in one paragraph:
- **Provenance.** A note can name the documents it rests on: the passages an answer cited when the
  person kept it, or a document the person links to it.
- **Still true?** When such a document changes or is removed, the note asks "Still true?" with the
  reason. This is the real cause that research section 8 wanted beside the 60-day timer.
- **The tidy pass.** A deterministic pass proposes merging notes that say the same thing and
  removing events long past. It proposes, the person decides, and nothing is changed by itself.

### 64. Provenance

- **New table `memory_note_documents`.** Each row records the document as it was when linked:
  - `owner`, `note_id`;
  - `doc_id`, `scope`, `source`, `name`, `sha256`;
  - `place`: the cited passages' pages or lines, heading and snippet, as the answer's Sources showed
    them, at most 240 characters each;
  - `how`: `answer` or `person`;
  - `linked_at`, `snoozed_until`.
- **Linked from an answer.** Remember on an answer links:
  - every document the answer **cited** (`cited: true` on a passage source, `answers.mark_cited`),
    one row per document with its cited passages in `place`;
  - every document the answer was sent **whole** (a `source_entry` without `passage`).

  Passages that were sent but not cited are not linked: the answer did not rest on them. An answer
  that cited nothing links nothing.
- **Linked by the person.** The note's details gain **Based on a document**. It lists the person's
  documents (My documents and their folders' files), with Unlink. A chat's attachments are linked
  only through an answer.
- **No links for other notes** (MV6-C1):
  - "Remember that ..." in a chat, typed notes, suggestions, Keep automatically, the in-turn tool and
    connections link nothing.
  - Their words are the person's or a model's, not a document's.
  - A model-written note from a turn that had documents would otherwise ask "Still true?" whenever
    any of those documents changed.
- **Carried over** when a note is saved as a new version, and when a kept suggestion replaces it.
  It is the same fact, edited, as pins and tags are carried (`keep_suggestion`).
- **Limits and deletion.**
  - At most 20 documents a note.
  - Deleting a note, Delete all memory, and deleting the person delete its links.
  - The export carries them (`documents` on each note).

### 65. Still true? from a changed document

**Checked on read.** The notes and the documents live in two SQLite files, so no transaction spans
both, as one does in Agentic GraphRAG. Instead, when the Memory page is read, Workbench compares
every link with the person's index, in one query:

| The index now | The link is |
|---|---|
| `doc_id` present, same `sha256` | current |
| `doc_id` present, another `sha256` (read again with new content) | **changed** |
| `doc_id` gone, and a document with the same scope and origin exists | **changed**: it is that document's new version |
| `doc_id` gone, nothing of that origin | **removed** |

- **Origin** is `source` for a folder's file or a chat's attachment. For My documents it is the
  name, since uploading a file of the same name replaces it (`Index.add`).
- **A file moved with the same content** keeps its id (`move_folder_document`), so it stays current.
- **A crash between a document's change and a note cannot lose the question**, since nothing is
  recorded at the moment of change.

**Asked at once, every one** (MV6-C3):
- A note with a changed or removed link is listed under Still true?, with each reason:
  - "'{name}' changed on {date}", the new version's `added_at`;
  - "'{name}' was removed".
- These have a cause, so they are not held to the timer's one project a week. The 60-day project
  timer keeps its weekly limit.
- A note whose links were all snoozed by Later waits until `snoozed_until`.

**What models receive does not change** (MV6-C2). A note waiting for its answer is still sent. The
change may not touch the fact, and the person decides.

### 66. Answering Still true?

`POST /api/memory/revisit` keeps its body `{noteId, answer}`. For a note asked about because of
documents:
- **Still true** moves each changed link to the document as it is now (`doc_id`, `sha256`, `name`).
  It drops each removed link, recording in the note's history "'{name}' was removed; you said it is
  still true".
- **Not any more: delete it** forgets the note, as today.
- **Ask me next week** snoozes its links for 7 days.
- **Edit** opens the note. Saving a new version carries the links at the documents' current
  versions, which answers it.

The page's `revisit` entries gain `reasons: [{name, change: "changed" | "removed", at}]`. A
project's timer entry has none.

### 67. The tidy pass

**Deterministic, per person, on reading the Memory page, at most once a day** (`tidy_at`). It
proposes; the person decides. What it proposes is shown under Waiting for you, after Still true?
and before the inbox.

- **Notes that say the same thing.**
  - Two active notes of the same kind whose titles are equal after normalising (`note_key`), or
    whose word stems overlap at least 0.6 (`memory_suggest.overlap`, MR8's near-duplicate measure).
  - Candidates come from an index of each note's three rarest stems, so 20,000 notes cost a linear
    pass, not every pair.
  - At most 20 proposals wait at a time.
  - Shown as "These look like the same note", with both:
    - **Keep this one** supersedes the other by it. The history shows "merged into", tags are joined,
      it is pinned if either was, and document links are joined. A body comes over only when the
      kept note has none, since two bodies are never merged by code.
    - **Keep both** remembers the pair, which is never proposed again.
- **Events long past.**
  - An `event` note whose date passed more than 30 days ago (MV6-C5): "This was on {date}. Remove
    it?"
  - **Remove** forgets it. **Keep** leaves it under Past and it is never asked again.
- **Supersession chains.** MV1 keeps one active version of a chain at write, so there is nothing
  deterministic to merge. The pass checks that invariant and logs a broken chain, naming the note.
- **New table `memory_tidy`:**
  - `id`, `owner`, `kind` (`duplicate` or `past`);
  - `note_ids` (JSON, sorted), and `pair` (`UNIQUE(owner, kind, pair)`);
  - `created_at`, `settled` (null, `merged`, `kept` or `removed`), `settled_at`.

  A proposal whose notes changed, one gone or superseded, is dropped when read.
- **API:** `tidy: [...]` in `GET /api/memory`, and `POST /api/memory/tidy/{id}` with
  `{action: "keep" | "keep_both" | "remove" | "keep_event", keepId?}`.

### 68. Store migration 27 to 28

- `memory_note_documents` and `memory_tidy`, both `CREATE TABLE IF NOT EXISTS`.
- `memory_prefs.tidy_at`.
- The backup and the single transaction as every step (`_initialize_schema`).
- Nothing existing is rewritten: notes kept before MV6 have no links.

### 69. Not in MV6

- Model-proposed consolidation, which is a later step under the per-model choice (research 7.5).
- Links for notes written by models or connections (MV6-C1).
- A version history of documents: the index keeps none. A link keeps the `sha256` it was based on,
  and the change is named, not shown as a diff.
- Provenance from web pages and tool results.
- Sending a waiting note's question to models.
- Links on a memory server's results (MV5).

### 70. Risk, tests and acceptance

**High risk** under the testing policy, for its store migration. What models receive changes only
by the person's merges and removals. So: one adversarial review, sabotage of the new checks, and a
real-environment run.

- **Unit tests:**
  - **Links:** Remember on an answer links cited documents and whole ones, not uncited passages; an
    answer citing none links nothing; the person links and unlinks only their own documents.
  - **The check on read:** same; read again with new content; replaced by name; a folder's file
    replaced; moved with the same content; removed; an attachment gone with its chat.
  - **The answers:** Still true moves or drops links; Later snoozes; Not any more deletes; a new
    version carries the links.
  - **Tidy:**
    - exact and near duplicates, and none across kinds;
    - Keep merges pins, tags, body and links and records the history;
    - Keep both is remembered;
    - a past event at 31 days is proposed, at 29 days it is not;
    - Remove forgets.
  - **The rest:** migration 27 to 28 from a schema 27 store; the export carries links.
- **Vitest:** Still true? with reasons; tidy proposals; Based on a document.
- **Live run** (`mv6-provenance-run.md`):
  - A real Workbench and gateway, with a model answering with `[1]`, over a schema 25 store.
  - An upload, and an answer citing it. Remember links it.
  - Replacing the upload asks Still true? with the reason. Still true moves the link.
  - Removing it asks again.
  - Two near-duplicate notes are proposed and merged. A past event is proposed and removed.
- **Sabotage once:** the `sha256` comparison, the match by origin, the cited filter, the kind check
  in tidy, and Keep both's memory.

### 71. Calls

**MV6-C1 (Troy's to confirm; the default is built): which notes name documents.** *Recommended
default:* notes kept from an answer (the documents it cited or was sent whole) and documents the
person links. Alternative: also notes a model writes in a turn that had documents. That links what
the model may not have used, and asks "Still true?" for every change.

**MV6-C2 (Troy's to confirm; the default is built): a waiting note is still sent.** *Recommended
default:* yes, until the person answers. Alternative: held back from models until answered, which
silently drops facts the change may not touch.

**MV6-C3 (Troy's to confirm; the default is built): document questions are asked at once.**
*Recommended default:* every note with a changed document, at once. Alternative: one a week, as the
project timer.

**MV6-C4 (Troy's to confirm; the default is built): tidy proposes, never acts.** *Recommended
default:* duplicates of the same kind (equal titles or stems overlapping 0.6) and events past by
30 days, each a proposal. Alternative: merge exact duplicates automatically.

**MV6-C5 (Troy's to confirm; the default is built): 30 days after an event.** *Recommended default:*
an event is proposed for removal 30 days after its date. Alternatives: at once, or never.

### 72. What building found

**Built as designed, with these changes:**

- **A link keeps where a passage is, never its words.** Only the cited pages and lines are kept,
  not the heading or snippet. A replaced or removed document's words go (`Index.add`'s
  promise), and a note's link must not keep them (review).
- **A merge puts the other note below the kept one's oldest version.** Superseding it by the kept
  note itself would give that note two earlier versions. `note_history` and `delete_memory_note`
  follow one line, so deleting the kept note would have left the merged one behind. The merge
  logs no words: deleting the merged version alone would otherwise leave them in the kept note's
  log (the review's blocker).
- **Near duplicates must be able to say the same thing** (`memory_suggest.same_claim`): the same
  no, the same numbers, and their shared words in the same order. Two events must fall on the
  same day. Without this, "Prefers tabs over spaces" and "Prefers spaces over tabs", "Has 2 kids"
  and "Has 3 kids", and "Is allergic to peanuts" and "Is not allergic to peanuts" were each
  proposed as one note (review). A cost: a reordered duplicate ("short bullet answers") is not
  proposed.
- **Candidates are found by prefix filtering**, not the three rarest stems. As many of a note's
  rarest stems as the 0.6 bar needs are indexed, so two long notes sharing most words are found
  whatever their rarest are. The finding runs off the event loop (review).
- **"Ask me next week" holds only while the document stays as it was.** A second change asks again
  at once (`snoozed_sha`, review).
- **A question a document raised spends nothing of the project timer's week**, whatever the
  answer (review).
- **No index where one was asks nothing.** A store restored without its documents is not a person
  who removed them all (review).
- **Linking a document again by hand keeps how and where it was first linked**, and the 20-document
  cap holds when links are carried over by a merge (review).
- **Linking and merging are refused while the owner has memory off.** Unlinking and removing are
  not: they only take away (review).
- **Edit on a Still true? question opens the note in the page's list.** A note beyond the
  list's newest 200 does not open from there; its other answers still work.

**Verification:**
- **Tests:** 22 tests in `tests/test_memory_mv6.py`, and Vitest for Still true?, tidy and Based on
  a document. 561 tests passed across the memory, past-chats, store, documents, connections, chats
  and config suites, and 3397 web tests passed.
- **Sabotage:** `--label MV6`, 12 of 12 caught.
- **Live run:** 35 of 35 over a schema 25 store (`docs/acceptance/mv6-provenance-run.md`).
- **Review:** one adversarial review. Its blocker and should-fix findings are fixed; the rest are
  below.

**Left, recorded:**
- **A merge drops the other note's body from what is sent.** It stays on the earlier version, but
  the page does not say so when both had a body.
- **An undated event a model proposed carries a date 30 days on** (`EVENT_DEFAULT_DAYS`). The tidy
  pass reads that as its day.
- **Undoing a learned note that a merge kept brings the merged note back** as current
  (`undo_learned`).

---

## MV7: chat projects

What MV7 changes, in one paragraph:
- **Projects.** A person can make **projects**: named groups of chats, each with its own notes and
  its own documents. This is call 13, "Add chat projects whose notes, procedures and documents can
  be kept to the project, with an 'also use my general memory' switch", taken at its default.
- **Inside a project.** A chat in a project is given the project's notes, and the person's general
  notes too while **Also use my general memory** is on. Its documents work the same way, with
  **Also search My documents**.
- **Outside a project.** A chat outside every project is given general notes only. What a project
  keeps stays in it, as in ChatGPT's project-only memory and Claude's per-project memory.

MV7 is built in two parts:
- **MV7a:** projects, their chats and project memory.
- **MV7b:** project documents, and past chats kept to their project.

### 73. A project

- **New table `projects`:**
  - `id`, `owner`, `name` (1-80 characters, unique per person once normalised);
  - `general_memory` (0/1, default 1);
  - `general_documents` (0/1, default 1, MV7b);
  - `created_at`, `updated_at`.
- **Chats.** `chats.project_id` is null for a chat in no project. A chat is in at most one project.
- **Moving a chat** into a project, out of one, or between two clears the chat's frozen pinned
  block (`memory_snapshot`). The next turn is given the notes of where the chat now is.
- **Instructions are notes.** A project's brief, style guide or checklist is a note of the
  `procedure` or `instruction` kind kept to the project, pinned when it should go every turn. No
  separate instructions field: MV1's notes already have bodies, kinds, pins and versions (MV7-C3).
- **Limits.** At most 100 projects a person.

### 74. Where projects are

- **The sidebar** gets a **Projects** list above Chats.
  - Each project opens to show its chats, newest first, and has **New chat in this project**.
  - Chats in no project stay under Chats, grouped by date as today.
  - **New project** asks for a name only.
- **The project page**, `/projects/<id>`:
  - name (rename), **New chat**, its chats;
  - its notes (the Memory page's note list, kept to the project), and Add a note;
  - its documents (MV7b);
  - its two switches;
  - **Delete project** (section 77).
- **The chat's header** names its project, with **Move to project** (a list of the person's
  projects, and No project) in the chat's settings menu.
- **The Memory page** gets a **Where** filter beside the tag filter: All, General, or one project.
  A note in a project says so ("In Garden plans"). A note can be moved: **Move to project**, or
  **Use everywhere** for one in a project.

### 75. Project memory

- **New column `memory_notes.project_id`.** Null is general.
- **Where a note is kept.**
  - A note written in a project chat is kept to the project, by every writer: Remember, "Remember
    that ...", the in-turn `remember` tool, suggestions and Keep automatically. It belongs where
    it was said (MV7-C2).
  - A note typed on the project page is kept to the project; on the Memory page, to General.
  - A suggestion keeps the project of the chat it came from.
- **What a chat is given:**

| The chat | Pinned block, relevant memory, `search_memory`, the notes a learning pass knows |
|---|---|
| In no project | General notes |
| In a project, Also use my general memory on | The project's notes, then general notes |
| In a project, the switch off | The project's notes only |

  - "Then": when the pinned block or the relevant budget is full, the project's notes are chosen
    first.
  - Relevant memory ranks the pool it is given (`Finder.choose`). That pool is filtered before it is
    ranked, never after, so a project's notes are not crowded out of a search's top results by
    general ones.
- **Connections** (MR9b: `search_notes` over MCP) search general notes only. A connection is
  another app, and is not in a project (MV7-C4).
- **Memory servers** (MV5) are sent no exchange from a chat in a project, as section 48 said. In a
  project chat they are asked only while Also use my general memory is on.
- **Supersession and the tidy pass stay within one place.** A suggestion may replace only a note of
  the same project, or a general note when the switch is on. The tidy pass proposes merging only
  two notes of the same project, or two general notes.

### 76. Project documents (MV7b)

- **A new index scope, `project:<id>`.**
  - Uploads on the project page go there.
  - A project chat with Documents on searches that scope, and My documents too while Also search My
    documents is on.
  - The same-name replacement rule holds within a project's scope, as it does in My documents.
- **Folders (MR7) stay general**, found by every chat that searches My documents. A folder kept to a
  project is not in MV7.
- **At boot**, a `project:` scope whose project is gone is removed, as a deleted chat's scope is
  (`Ingest._reconcile`).

### 77. Past chats and deleting a project (MV7b)

- **Past chats:**
  - In a project chat, past chats (the turn's offer and `search_chats`) are that project's chats, and
    every chat while Also use my general memory is on.
  - Outside a project they are chats in no project.
  - Search chats, the person's own screen, finds every chat, with a Where filter.
- **Delete project** asks one question with two answers:
  - **Delete the project and its chats, notes and documents**, with the counts.
  - **Delete the project, keep its chats and notes**, which become general. Its documents move to My
    documents, where a name already there is replaced, as an upload of that name would be.

  Either way nothing of it is left under the project's id.

### 78. Store migration 26 to 27

- `projects`;
- `chats.project_id` and `memory_notes.project_id`, both nullable, with indexes on
  `(owner, project_id)`.
- Nothing existing moves: every chat and note is general until the person makes a project.

### 79. Not in MV7

- Sharing a project with another person.
- A folder kept to a project.
- A project's own model or instructions field (MV7-C3).
- Projects in the owner's read-only view of people's chats, beyond the project's name on a chat.

### 80. Risk, tests and acceptance

**High risk**, for a store migration and for changing what models receive. So: one adversarial
review, sabotage of the new checks, and a real-environment run, for each of MV7a and MV7b.

- **Unit tests:**
  - a project's notes go only to its chats;
  - general notes go to a project chat only with the switch on;
  - each writer keeps a note in the chat's project;
  - moving a chat clears its frozen block;
  - the pool is filtered before ranking (a project note found when 50 general notes outrank it);
  - connections see general notes only;
  - project chats are not sent to a memory server;
  - suggestions and tidy stay within a project;
  - the migration from 26.
- **MV7b:** the project scope searched only by its chats; past chats kept to the project; both
  answers to Delete project; the boot reconcile.
- **Vitest:** the sidebar's projects, the project page, Move to project, and the Where filter.
- **Live runs:** `mv7a-projects-run.md` and `mv7b-project-documents-run.md`.

### 81. Calls

**MV7-C1 (Troy's to confirm; the default is built): a project's notes stay in it.** *Recommended
default:* a chat outside a project is never given a project's notes. Alternative: project notes are
general notes with a label, given everywhere and first in their project. That is weaker isolation,
and not what either reference does.

**MV7-C2 (Troy's to confirm; the default is built): a note belongs where it was said.**
*Recommended default:* a note written in a project chat is kept to the project, whoever wrote it.
Alternative: notes go to General unless the person picks the project. That is simpler, but a
project's facts then leak into every chat.

**MV7-C3 (Troy's to confirm; the default is built): instructions are notes.** *Recommended
default:* a project's instructions are its pinned instruction and procedure notes. Alternative: a
separate instructions box on the project page, as ChatGPT's projects have. That is a second place
for the same thing, without versions or tags.

**MV7-C4 (Troy's to confirm; the default is built): connections see general notes.** *Recommended
default:* MCP `search_notes` searches general notes only. Alternative: a connection is granted
projects one by one.

**MV7-C5 (Troy's to confirm; the default is built): Also use my general memory is on by default.**
*Recommended default:* on: a new project starts knowing what the person told Workbench. Alternative:
off, a clean room for each project.

### 82. What building MV7a found

**Built as designed, with these changes:**

- **Past chats are kept to their project in MV7a, not MV7b.** Without that, an exchange from a
  project's chat reached a chat in no project through Use past chats, which breaks MV7-C1. The
  turn's offer and `search_chats` follow the place, as section 77 says. Search chats, the
  person's own screen, finds every chat. A connection's `search_chats` finds chats in no
  project.
- **A search reaches further than it keeps** (`SPREAD`, five times). It drops other places'
  notes before any cut: the 200 word hits, the 200 title hits, and the eight best by meaning.
  Filtering only after the cuts let eight or more better-matching notes elsewhere hide a
  project's note (review).
- **"The project's notes first" holds for the pinned block only.** Relevant memory ranks a
  project's notes and general ones together, by how well they match.
- **Every way out is kept to its place**, each found by the review:
  - "Forget ..." offers only notes the chat may be given.
  - A connection's `read_note` refuses a project's note by id, as its search already did.
  - A connection's suggestion is compared with general notes only, so its answer never says that
    a project holds the words.
  - The learning pass is told no tag that only another place's notes carry.
- **The same words are one note within one place.** Each place stands alone: a suggestion in a
  project is not dropped because General holds the same words (review).
- **Deleting a project leaves nothing under its id.** What its delete did not take becomes
  general in the same step: a suggestion waiting from a chat moved out of it, an earlier version,
  a chat made while it ran (review).
- **The general-memory switch and its chats' frozen blocks change in one step** (review).
- **The export says where each note is kept**, by the project's name then.
- **Counting a project's chats and notes is two grouped queries**, not every chat and note read
  (review).
- **A project's name may not hold characters nobody sees**, as a note's may not (review).

**Verification:**
- **Tests:** 22 tests in `tests/test_memory_mv7.py`, and Vitest for the sidebar's projects, the
  project page, Move to project and the Where filter. 2,400 server tests and 3,439 web tests
  passed.
- **Sabotage:** `--label MV7`, 14 of 14 caught.
- **Live run:** 27 of 27 over a schema 26 store (`docs/acceptance/mv7a-projects-run.md`).
- **Chrome:** both Chrome checks pass. The documents check timed out once waiting for a
  chip, then passed on its own.
- **Review:** one adversarial review, with no blocker. Its should-fix findings are fixed.

**Left, recorded:**
- **A chat moved into a project keeps on a memory server what was sent before.** Only new
  exchanges stop. Forgetting them would need the move to queue a forget.
- **The project page lists its notes simply.** Editing, pinning and moving a note are on the
  Memory page, where the Where filter finds them.
- **Add a note on the Memory page keeps it to General** whatever the Where filter shows.

### 83. What building MV7b found

**Built as designed, with these changes:**

- **A project's documents are the person's like My documents.** Open, Read again, Remove and
  the text of one work as for My documents. The first build refused them (404) everywhere but
  the project's search (the review's blocker).
- **Moving a project's documents to My documents rewrites their own files too.** Each document's
  sidecar names its scope, and a Rebuild makes the documents again from those files. Without
  the rewrite, a Rebuild after Delete project (keep) put them back under the project that was
  gone, and the next boot deleted them (the review's second blocker). The move is all or
  nothing: the files of a My documents file it replaces are staged, as `delete_many` does, and
  put back if anything fails.
- **A Rebuild makes a project's document again only in a project of the person's.**
- **Delete project (keep) moves the documents first.** A move that fails leaves the whole
  project, chats and notes included, to try again. It answers 503 with the reason (review).
- **At boot, a project's documents go only when some of the person's projects are still
  there.** With every one of them gone, it may be a store restored from before them, and files
  the person kept are not deleted on a guess. They wait, unsearched, and the log says so
  (review).
- **An upload that races its project's delete is taken back**, and answers 404 (review).
- **A project's files are read in My documents' turn**, after a chat's attachments (review).
- **The documents chip and Sources label a project's documents "My documents".** The drawer's
  `library` counts are what the chat searches: the project's documents, and My documents
  while the switch is on.
- **A project's documents count toward the person's passage cap**, as My documents do.

**Verification:**
- **Tests:** 10 tests in `tests/test_memory_mv7b.py`, and Vitest for the project page's Documents,
  the switch and the delete question. 2,413 server tests and 3,444 web tests passed, and both
  Chrome checks pass.
- **Sabotage:** `--label MV7b`, 10 of 10 caught.
- **Live run:** 18 of 18 (`docs/acceptance/mv7b-project-documents-run.md`).
- **Review:** one adversarial review. Its two blockers and its should-fix findings are fixed.
- **Also fixed:** a Windows CI flake in folder sync's "too new to trust" test. A slow runner first
  read the file after the 2.5 s window, so it was trusted. The test widens the window.

**Left, recorded:**
- **A folder kept to a project** (section 76) is not built: folders stay general.
- **The project page's document rows** carry Open and Read again as well as Remove: they are the
  Documents screen's rows.
