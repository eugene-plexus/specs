# Row 27: memory extras

Lane WB, after row 7: each new column or table joins row 7's `PERSON_TABLES`, and row 7's purge test then guards it. This row is a bundle. It splits into six sub-rows, ordered by value, and each one merges on its own. Sources: `workbench-memory-v2.md` §48, §51, §54 (MV5-C4), §69, §79 and §82.

**Store migrations.** The store is at 27. Row 7 takes 28, MV5b takes 29 and row 28 takes 30. So this row takes **31** and **32**. Whichever row merges later renumbers.

## 1. What it delivers

| Sub-row | Delivers | Size | Risk | Migration |
|---|---|---|---|---|
| 27a | **Send my past chats** to the person's memory server, after a count and a time estimate | S-M | high (migration; chats leave) | **31**: adds every column 27a-27e need |
| 27b | **A project's own model**, and projects in the owner's read-only view | S | low | none (31's column) |
| 27c | **Provenance from web pages and tool results** | S-M | low | none |
| 27d | **Model-proposed merges** in the tidy pass | M | cross | none (31's columns) |
| 27e | **A folder kept to a project** | M | cross | none (31's column) |
| 27f | **Several servers a person, and install-wide servers** | M-L | high | **32**: re-keys `memory_servers` |

## 2. The design

### Migration 31 (lands with 27a)

All additive and nullable, guarded by `PRAGMA table_info` as `_projects` is:
- `memory_servers.backfill TEXT` (JSON);
- `projects.model TEXT`;
- `memory_tidy.model TEXT` and `memory_tidy.merged TEXT` (JSON `{title, body}`);
- `document_folders.project_id TEXT`, with an index on `(owner, project_id)`.

Nothing existing is rewritten. One migration costs one acceptance and one review instead of four (call 27-C1).

### 27a Send my past chats (MV5-C4)

**Where it is.** Memory settings, under Your memory server, shown only when the server has `retain`:
- **Before sending:** "1,240 exchanges from 312 chats, about 380,000 tokens. Chats in projects, chats with memory off and turns that look like a password are not sent."
- **The choice:** All, or Since {date}.
- **The estimate:** "Your server took 4.1 s for each of the last 20: about 1 h 25 min." Before any measurement: "Time: shown after the first 10 are sent."
- **Buttons:** Send, and Cancel.

**What is sent.** Exactly what the live Courier would send for each exchange today:
- the exchanges on each chat's shown path (§14);
- each through `content_for`, with the write policy's Source row as it is now;
- the secret skip, and the exclusion of project chats and chats with memory off.

`document_id` is `{chat_id}:{message_id}`, as for a live exchange. So sending one again replaces it, and forgetting works as it does today.

**How.**
- A `Backfill` feeder in `memory_servers.py` keeps at most 20 backfill rows queued in `memory_server_sent`, oldest first. It tops up only when no live exchange is due, so a new answer is never kept waiting.
- Its state is in `memory_servers.backfill`: `{state: running|stopped|done, since, startedAt, total, sent, skipped, cursor, msPerExchange}`.
- Each row's day starts when it is queued, so a backfill that runs for days never meets the Courier's one-day give-up.
- A restart resumes from the cursor. A disconnect, or a new address, ends the backfill.

**UI text.**
- Running: "Sending past chats: 420 of 1,240 · about 56 min left". Button: Stop.
- Stopped: "Stopped: 420 of 1,240 sent. What was sent stays on your server." Button: Resume.
- Failed (three backfill rows in a row): "Stopped at 420 of 1,240: not reached since 14:02: connection refused." Button: Resume.
- Done: "Past chats sent: 1,231 of 1,240. 9 were not sent: they looked like a password or key."

**API:** `GET /api/memory/server/backfill` (count, tokens, estimate); `POST {since?}` starts; `DELETE` stops.

**Default.** Nothing is sent until the person presses Send. This keeps chats somewhere new only on the person's own press, and the issue comment says so.

### 27b A project's own model, and the owner's view

**The project's model.**
- The project page gains **Model for new chats**. Unset, it shows the model in effect: "Workbench's default (qwen3-8b)". New chats in the project start on it; a chat's own picker still changes that chat only.
- When it is not served: "qwen3-27b is not served now. New chats use qwen3-8b." The project keeps its choice.
- API: `PATCH /api/projects/{id}` takes `{model}`; `GET` returns `model` and `modelInEffect`.

**The owner's view.** While `ownerReadsChats` is on, `/api/people/{sub}/chats` returns `projects: [{id, name}]` and each chat's `projectId`. The page groups the chats under the project names. Never notes, documents or switches (W4).

### 27c Provenance from web pages and tool results

- **Remember on an answer** shows "Based on". Each web page the answer cited (`sources` kind `web`) is ticked. Each tool call with a result that is not an error is not ticked: a tool result has no citation to say it was used.
- **A ticked item is a `memory_note_documents` row:** scope `web` or `tool`, `doc_id` from a hash of the URL or the server and tool, `source` the URL or `server/tool`, `name` the title, `sha256` the hash of the text the answer was given. The words are never kept (MV6's rule).
- **The note's details** say "From a web page: Example Domain (example.com), read 21 Oct", with Open. The check on read skips these scopes: there is no index to compare with.
- **Check again** is the person's own action, never automatic. It fetches the page through their web tool and compares the hash. A change asks Still true?: "'Example Domain' changed on the web since 21 Oct".
- No migration. The 20-link cap and the export cover these links.

### 27d Model-proposed merges (research 7.5)

- **Who proposes.** A model the person set to Suggest or Keep automatically (MV3), once they turn on "Let {model} propose merges" on Memory settings.
- **When.** Inside the daily tidy pass, after the deterministic pass, on pairs it missed only: stem overlap from 0.4 to 0.6, or the same words in another order. At most 40 pairs a day, 10 to a request. The model answers `{pairs: [{a, b, same, title, body}]}`.
- **What the person sees:** "qwen3-27b thinks these say the same thing", with its wording. **Keep this wording** makes a new version that supersedes both, with the history "merged as qwen3-27b proposed; you kept it". **Keep both** and **Edit** are also offered. The limit of 20 waiting proposals covers these.
- **Where the notes go.** To the model only when it is local, or when the person's outside-model memory rule lets them; never the unseen ones (call 12).
- **Failure:** "Proposals from qwen3-27b paused: it is not served now." The next day's pass tries again.

### 27e A folder kept to a project

- The project page, Documents, gains **Add a folder**. It lists the person's folders (MR7 grants). A folder added there indexes into scope `project:<id>`.
- A folder already in My documents can be moved with **Move to project**. Its documents' scope and sidecars are rewritten, as MV7b's move does, and nothing is read again.
- **Delete project.** Delete takes the folder out of Documents; the files on disk are untouched. Keep makes the folder general.
- `folder_sync` takes the scope from the record (`document_folders.project_id`).

### 27f Several servers, and install-wide servers

- **Up to 3 servers a person.** `recall` asks each in parallel within the 2 s limit, and they share the third of the memory budget. `retain`, `forget` and `purge` go to each.
- **Install-wide servers.** The owner adds them under Workbench settings, Memory servers: name, address, token, and a bank path with `{person}` (MV5b's `wb-` rule). A person sees "Acme memory (from your install)", with **Use it**, off until they turn it on. The token is never shown. The address rule applies to the owner's addresses too.
- **Migration 32,** one transaction after the usual backup:
  - `memory_server_list (id PK, owner, install_id, url, token, name, verbs, linked, connected_at, last_ok_at, last_error, last_error_at, skipped, backfill)`, copied from `memory_servers`;
  - `memory_server_sent.server_id`;
  - `install_memory_servers (id PK, name, url, token, bank_template, verbs, added_at)`.

## 3. Repositories and files

**workbench only.** Its `/api` is private, so there is no contract change and no codegen consumer.

- **27a:** `store.py` (migration 31), `memory_servers.py`, `MemoryServer.tsx`.
- **27b:** `projects_api.py`, `api.py` (the chat-create default and `person_chats` only), `Project.tsx`, the owner's view.
- **27c:** `memory_provenance.py`, `memory_api.py`, `RememberThis.tsx`, `MemoryDetails.tsx`.
- **27d:** `memory_tidy.py`, `memory_models.py`, `MemoryTidy.tsx`, `MemorySettings.tsx`.
- **27e:** `knowledge/folder_sync.py`, `folders_api.py`, `projects_api.py`, `Project.tsx`.
- **27f:** `store.py` (migration 32), `memory_servers.py`, `config.py`, `MemoryServer.tsx`, `SettingsPage.tsx`.
- **specs:** this design's "What building found"; `scripts/row27a-backfill-acceptance.py`, `scripts/row27f-memory-servers-acceptance.py` and their `ci.yml` steps.

## 4. Tests that fail before the change

- **27a `test_memory_backfill.py::test_backfill_sends_what_live_would_and_resumes`.** A person has three chats: one in a project, one with memory off, and one with a secret turn. The backfill queues only the plain chat's other exchanges, and survives a restart without sending one twice.
- **27a, also:** `test_migration_31_from_30`.
- **27b `test_project_model.py::test_new_chat_in_project_starts_on_its_model`.**
- **27c `test_memory_provenance_web.py::test_remember_links_cited_page_not_its_words`.**
- **27d `test_memory_tidy_model.py::test_model_merge_is_only_a_proposal`.** It also checks that no unseen note goes to an outside model.
- **27e `test_project_folder.py::test_project_folder_found_only_in_its_chats`.**
- **27f `test_memory_servers_many.py::test_install_server_off_until_person_turns_it_on`,** and `test_migration_32_keeps_server_and_sent_rows`.

## 5. Acceptance and review

**27a** is high risk: a migration, and chats leave Workbench. `row27a-backfill-acceptance.py` runs in CI on Windows and Linux. It starts an agent, the gateway and Workbench on OS-assigned ports (never 8079-8083), with `EUGENE_PLEXUS_*` cleared, and `scripts/m-memory-server.py` in its own process. It checks:

1. A schema-30 store with data migrates to 31.
2. The count matches the eligible exchanges.
3. Send, then kill Workbench midway. After the restart, every exchange arrives exactly once.
4. A live answer arrives during the backfill.
5. Deleting a chat sends `forget` for each of its exchanges.

The reviewer should attack project and memory-off chats being sent, the secret skip, sending twice after a restart, the give-up clock, and `PERSON_TABLES`.

**27f** is high risk. `row27f-memory-servers-acceptance.py` runs under the same ports rule and checks:

1. Two people and an install server: each bank holds only its own person's exchanges.
2. The server is off for each person until they turn it on.
3. Purging one bank leaves the other.
4. Migration 32 keeps an existing server, and the exchanges still to be forgotten.

The reviewer should attack the bank derivation, the token's exposure, an owner reading people's memory through the server, and the address rule.

**27b-27e:** changed-file tests and one Chrome check of each screen.

## 6. Do not change

- **workbench:** `artifacts.py`, `Markdown.tsx`, `MessageView.tsx` (31); `tools.py` (29, 32); `context.py`, `conversation.py` (26); `answers.py` (28); `past_chats.py` (7); `knowledge/ingest.py`, `SourcePassages.tsx` (30); `folder_windows.py`, `folder_linux.py` (23); `local_tools.py`, `mcp_sandbox.py`, `mcp_apps.py` (52, 60).
- **Shared:**
  - `store.py`: add migrations and methods only; never reorder `_MIGRATIONS`.
  - `knowledge/folder_sync.py` (27e) is row 30's next. 27e merges first, or rebases.

## 7. Size, risks, calls

**Size:** about 7 days in all. 27a 1.5, 27b 0.5, 27c 1, 27d 1.5, 27e 1.5, 27f 2. Each is on its own branch, `r27a-backfill`, `r27b-project-model` and so on.

**Risks:**
- **27a's time estimate is measured, not promised.** Hindsight read an exchange in 3.9-5.1 s on the 5090 (MV5b probe), so 1,000 exchanges take over an hour.
- **27d sends notes to a model.** That is why it is off until turned on, and follows the outside-model rule.
- **27f rebuilds a table.** That is why it comes last and has its own acceptance.

**Calls only Troy can make:**
- **MV5-C4: build "Send my past chats"?** Recommend yes: per person, opt-in, with a count and an estimate first.
- **27-C1: one additive migration (31) for 27a-27e, or one per sub-row?** Recommend one. It is one acceptance and one review, not four, and the columns are nullable.
- **27-C2: model-proposed merges.** Recommend off until the person turns them on for a model. The alternative is on for every model set to Keep automatically.
- **27-C3: install-wide servers.** Recommend opt-in per person. The owner turning one on for everyone would keep people's chats somewhere new by default.
- **27-C4: tool results as provenance.** Recommend linked only when the person ticks them.
- **27-C5: when to build 27f.** Recommend after MV5b lands, since 27f re-keys MV5b's `linked` column.

## Calls answered by Troy (2026-10-21)

- **MEM-MERGE: Choice 2.** Merge proposals are on for every model set to "Keep automatically".
- **MEM-INSTALL: per group.** The owner adds a memory server to a permission group. It is on for every member, and a member cannot turn it off. Until Workbench can read a person's groups, the owner's choice is install-wide.
- **MEM-TOOLS: Choice 1.** A tool result is linked only when the person ticks it.
