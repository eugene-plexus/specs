# Row 28: answer branches: delete, name, compare (AV-later)

Lane WB, after rows 7 and 27. The source is `workbench-answer-versions.md` §9.

Delete removes rows and attachment files, so **treat step 28a as high risk:** one adversarial review, and a real-app acceptance test in Workbench's CI.

**Store migration.** Naming needs one column. The migration takes the next number after the lane's earlier rows: row 7 takes 28 and MV5b holds 29, so this row takes **30**. If row 27 adds a migration first, take the number after row 27's. Whichever row merges later renumbers, and edits this line.

## 1. What it delivers

- **Delete this version.** It removes a version and everything after it, on every branch below it. On a message with only one version, the menu says **Delete from here**, which cuts the chat at that message.
- **The confirm counts what goes:** "Delete answer 2 of 3 and the 6 messages after it? 2 files and 1 artifact go with them. Notes kept from them stay. This cannot be undone."
- **Name this version.** The arrows show the name: `‹ 2 of 3 · Shorter tone ›`.
- **Compare with…** shows the branches of two versions of one message in two columns, from the message where they part. On a phone, the columns stack, with a switch between them.

## 2. Design

### Delete

**Refused:**
- while an answer runs anywhere in the chat: 409 "Wait for the answer, or stop it." This is the `choose` rule, so a running answer and its approval are never deleted;
- on the chat's only first message: 409 "This is the whole chat. Delete the chat instead."

**What goes, in order.** This follows `delete_chat` and `remove_chat`, per message instead of per chat. A branch is a version and its descendants. Find them from one read of the chat's rows, as `path()` does.

1. **The past-chat index first.** Remove the exchange documents whose answer id is in the branch. If that fails, delete nothing: 503 "Workbench could not remove these messages from your search index, so nothing was deleted. Try again in a moment."
2. **One transaction,** `Store.delete_branch`:
   - **Other answers that kept these words.** Remove the `memory_used.pastChats` excerpts whose `messageId` is in the branch, counted as `forgotten`. Replace any kept `search_chats` result that quoted this chat with `FORGOTTEN_CHAT`. It records only chat ids, so this may remove more than the branch; that is the safe direction.
   - **Artifacts** of those messages, and their revisions.
   - **Files** of those messages, unless a message that stays lists the file. An edit shares its original's attachments.
   - **Memory notes.** Pending suggestions from the branch go. Kept notes stay, as they do for a deleted chat.
   - **The memory server (MV5).** Exchanges not yet sent are dropped. Sent ones become `forget`.
   - **Interaction surfaces** go by cascade. An AG-UI run goes only when every message it wrote is in the branch.
   - **The messages.** If the deleted version was the chosen one, the version made before it becomes chosen, else the one after it.
3. **After the commit:**
   - run `wal_checkpoint(TRUNCATE)`. `secure_delete` is already on;
   - touch the chat, so the index syncs the new path;
   - poke the memory courier;
   - cancel the reader jobs of removed files;
   - drop the documents made from those files;
   - remove the files from disk;
   - send a `path` event.

**Oversight, exports and learned memory:**
- **The owner's view (V5)** loses the branch too. A person can already delete a whole chat, so this hides nothing new.
- **Exports** write the path shown. An export made earlier (row 7's ZIPs, kept 24 h) keeps the branch until it expires.
- **A kept note** whose source was deleted shows its source as "from a deleted message".
- **Undo:** none (RB-C1).

### Name

- **Where it is stored:** `messages.branch_name TEXT`, nullable, at most 60 characters, with no control characters.
- **Where it shows:** `versions()` returns `names` beside `ids`, and `message_view` carries the name. A message hidden by J13a hides its name too.
- **Running answers:** a version may be named while an answer runs; it does not move the path. Naming sends a `path` event.
- **Where it does not go:** names are not indexed, not sent to the model, and not exported.

### Compare

- **No new read API.** The page fetches `GET /api/chats/{id}?via=A` and `?via=B`. `?via=` already reads a branch without saving anything (V5).
- **Layout.** Messages both branches share show once. The columns start where the branches part.
- **Choose this one** calls `choose`.
- **The owner's view** may compare. It only looks.
- **The tree map** comes later (RB-C3).

### API (Workbench's own; no specs contract)

```text
GET    /api/chats/{id}/messages/{mid}/branch  -> {messages, answers, files, artifacts,
                                                  pendingNotes, keptNotes, toolCalls, chosen}
DELETE /api/chats/{id}/messages/{mid}         -> 200 chat detail | 404 | 409 | 503
PUT    /api/chats/{id}/messages/{mid}/name    {name: string 1..60 | null} -> 200 {versions}
GET    /api/chats/{id}                        versions gains names: [string|null]
```

All of these need the person whose chat it is (`_own_chat`). The owner's view gets 403 on DELETE and PUT.

### Page

`VersionArrows` moves from `MessageView.tsx` to new `Versions.tsx`. It gains a `⋯` menu: **Name this version**, **Compare with version 1**, **Delete this version**. Two more new components: `DeleteBranchDialog.tsx` and `CompareVersions.tsx`.

**Text:**
- After a delete: "Deleted answer 2 and the 6 messages after it."
- Name placeholder: "Name, e.g. Shorter tone".
- Compare headers: "Answer 1 · qwen3-8b" | "Answer 2 · Shorter tone · claude-sonnet".
- Delete is in the danger style and is not focused by default.

**Defaults.** Nothing is deleted without the confirm. Kept notes stay. It exposes no private data.

## 3. Repositories and files

- **workbench:**
  - `store.py`: the migration, `delete_branch`, `branch_summary`, `name_version` and `versions`;
  - `answers.py`: `message_view`;
  - `api.py`;
  - `exchanges_index.py`: `remove_exchanges`;
  - web: one import change in `MessageView.tsx`, new `Versions.tsx`, `DeleteBranchDialog.tsx` and `CompareVersions.tsx`, and `useChat.ts`.
- **specs:** `workbench-answer-versions.md` §9: mark it built, and add what building found.
- No codegen. Workbench `dist` ships through `ship.py`.

## 4. Tests that fail before the change

**workbench `test_branch_delete.py::test_delete_leaves_nothing_of_the_branch`.**
- **Setup.** Answer 2 has three tries. Try 2 has two more turns, an attachment, an artifact, a pending note, a kept note and a sent memory-server exchange. A later chat's `pastChats` excerpt quotes it.
- **Action.** Choose try 2, so it is indexed. Then delete it.
- **Expected:**
  - no row holds the branch's ids;
  - the branch's marker is in no table and not in the index;
  - its file is gone from disk;
  - the kept note stays, with its source cleared;
  - the server exchange is `forget`, and the excerpt is gone;
  - try 1 is chosen;
  - the other branches are byte-identical.
- **Today** it fails: there is no delete route.

**Also:**
- `test_shared_attachment_survives_deleting_its_edit`
- `test_delete_refused_while_running`
- `test_index_failure_deletes_nothing`
- `test_delete_from_here_on_single_version`
- `test_name_round_trips_and_hidden_name_hidden`
- `test_migration_adds_branch_name`
- `Versions.test.tsx`
- `CompareVersions.test.tsx`

## 5. Acceptance (Workbench CI) and review

**`tests/test_branch_delete_app.py`:**
- It starts the real app on an OS-assigned port (never 8079-8083), with a fake gateway, a stand-in MCP memory server, and `EUGENE_PLEXUS_*` cleared.
- It runs the scenario over HTTP.
- It closes the app and opens the store read-only.
- It greps every file under the data folder for the marker: the store, the WAL and the index. The `.bak` copies follow RB-C2.

The Chrome check `test_versions_browser.py` adds a delete, then a compare.

**The reviewer should attack:**
- words left in `agui_events`, other answers' `tool_rounds`, the index, the WAL or a `.bak` copy;
- a shared attachment deleted under a kept version;
- a delete during an approval;
- a tab one step behind;
- a delete in another person's chat;
- the owner's view deleting or naming;
- the courier forgetting the wrong branch's exchanges.

## 6. Do not change

- **workbench:**
  - `context.py`, `conversation.py` (row 26);
  - `tools.py` (rows 29, 32);
  - `projects.py`, `memory_servers.py` (rows 27, 47);
  - `past_chats.py` (row 7);
  - `knowledge/ingest.py`, `folder_sync.py` (row 30);
  - `folder_windows.py`, `folder_linux.py` (row 23);
  - `local_tools.py`, `mcp_sandbox.py`, `mcp_apps.py` (rows 52, 60);
  - `Markdown.tsx`, `artifacts.py` (row 31).
- **Shared:**
  - `store.py`: add the migration and new methods only, and do not reorder `_MIGRATIONS`.
  - `MessageView.tsx` belongs to row 31. Make only the one-line move of `VersionArrows`, and tell row 31 to rebase.

## 7. Size, risks, split, calls

**S-M, about 2 days, on one branch, `r28-branches`:**
- **28a (about 1 day, high risk):** delete, its summary, its dialog and the review.
- **28b (about 1 day, low risk):** names with the migration, and compare.

**Risks:**
- A copy of the branch's words is missed. The guard is the marker grep.
- An attachment is shared between versions.
- `MessageView.tsx` overlaps with row 31.

**Calls only Troy can make:**
- **RB-C1: undo after a delete?** Recommended: no undo, and a confirm that counts what goes. A soft delete keeps the words in the store and the index, which is the opposite of what someone deleting a pasted secret wants. Every reader would also have to filter deleted rows.
- **RB-C2: is a delete a true delete, like row 7's Delete now (MRC27)?** Recommended: yes. Checkpoint the WAL, and remove the rows from every `*.schema-N.bak` copy with row 7's routine. File an issue so that deleting a whole chat does the same.
- **RB-C3: side by side now, a tree map later?** Recommended: yes. Side by side answers "which try was better?" with no new read API.
- **RB-C4: Delete from here, on a message with one version?** Recommended: yes. Otherwise, removing a pasted secret from a chat without versions means deleting the whole chat.

## Calls answered by Troy (2026-10-21)

- **RB-C1: Choice 2.** A deleted branch is hidden for 30 days with an Undo.
- **RB-C2: Choice 1.** After the 30 days, the delete is a true delete: the store, its backup copies and the past-chat index.
- **RB-C3: Choice 1.** No tree map in this row.
- **RB-C4: Choice 1.** "Delete from here" works on a message with one version.
