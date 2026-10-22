# Row 30: documents and folders extras

Lane WB, after row 27. This row is a bundle of seven sub-rows, ordered by value, and each one merges on its own. Sources: `workbench-memory-and-documents.md` §4.3, §4.4 step 9, §6.1 "Later" and MRC25/MRC26; `workbench-folders.md` calls 1 and 3 and "Not built".

**Store migration.** Row 27 takes 31 and 32, so this row takes **33**. Whichever row merges later renumbers. OCR changes the person's knowledge index instead (its schema goes 3 → 4). That index is derived from the person's own files and can be rebuilt.

**Fix in `roadmap-rows.json`:** the hot file is `knowledge/folder_sync.py`, not `folder_sync.py`.

## 1. What it delivers

| Sub-row | Delivers | Size | Risk | Migration |
|---|---|---|---|---|
| 30a | **Questions about a whole document,** read in parts (map-reduce) | M | cross | none |
| 30b | **Scanned pages read by a vision model,** opt-in | M | cross | index 4 |
| 30c | **The cited PDF page opens,** with the passage marked | S-M | low | none |
| 30d | **A check interval per folder** | S | high (migration) | **33**, with every store change below |
| 30e | **Collections** that a chat can search | M | cross | none (33's tables) |
| 30f | **Folders on Job Sites** (MRC26) | L | high | none |
| 30g | **Check as soon as files change** (a watcher) | M | cross | none (33's column) |

## 2. The design

### 30a Whole-document questions (map-reduce)

**When it is offered.** A question that asks for the whole ("summarize", "compare", "list every", "all the", "overview") about a document too large to send whole (MRC15: at most 6,000 tokens or 25% of the window). The answer carries a line: "Answered from 5 passages, not the whole document." Button: **Read all of it**.

**Before it starts,** it says the cost: "12 parts, about 140,000 tokens. About 3 min on qwen3-8b." The speed is the runtime's measured speed; without one, the time is left out.

**How.**
1. Each document is cut into parts of 60% of the model's window, after the question. At most 3 documents and 40 parts.
2. A map request for each part, at most 2 at a time: "From this part, write what answers: {question}. Write NONE if nothing does."
3. A reduce request over the notes, in order, each labelled with its pages. The notes are not stored.
4. The result is a new version of the answer. Its Sources say "Read whole, in 12 parts".

**UI text.**
- Progress: "Reading part 3 of 12 of Annual report.pdf". Button: Stop.
- Too long: "This is 61 parts; Workbench reads at most 40. Ask about a part of it."
- A failed part: "Part 7 (pages 61-70) was not read: {cause}. The answer leaves it out and says so."

**Rules.** Outside models follow the passages' rule (`documentsExternal`). The expert setting is `documentsWholeByParts`: `ask` (the default), `always` or `never`.

**Code:** a new `knowledge/whole.py` and a hook in `answers.py`. In the page, the line and its button go in `SourcePassages.tsx` (`SearchNotice`), which `MessageView.tsx` already shows. `MessageView.tsx` itself is row 31's.

### 30b Read scanned pages (opt-in OCR)

**The owner chooses the model.** The setting is `documentsPageReader`, in `/v1/config` and so on the console: a vision model from the gateway, or unset. Unset shows "Off: scanned pages are skipped".

- **The person chooses what is read.** A document skipped as "this PDF has no text, only pictures of pages" gets **Read the pages with {model}**. My documents and each folder gain **Read scanned pages**, off by default; with it on, PNG and JPEG files become documents too.
- **How.** The reader's child process renders each page with no text (pypdfium2, 150 DPI, at most 2,000 px long). Workbench sends them one at a time to the gateway's `/v1/chat/completions`: "Write out all the text on this page, in reading order. Keep headings and tables as Markdown." The text is chunked like any PDF, and Sources say "page 4 (read from a picture)".
- **Limits.** `documentsPageReaderMaxPages` is 200, said before starting: "48 pages to read with qwen3-vl-8b". A page image leaves the machines only under the passages' outside-model rule.
- **Index schema 4:** `documents.read_by TEXT`, the model that read the pictures.
- **Failure:** "Pages not read: qwen3-vl-8b is not served now." A page that fails is counted and named.

### 30c Open the cited PDF page

- **What the person sees.** A PDF passage in Sources gets **Show page 12**. A viewer beside the chat shows the page as a picture with the passage's words marked, and Previous, Next and Open original.
- **Why a picture.** Originals are served as downloads under `Content-Security-Policy: sandbox`, and browsers' PDF viewers do not run under it. A rendered page is an image: nothing in it runs. No pdf.js.
- **API.** `GET /api/documents/{id}/pages/{n}?passage={chunk}` returns `{image, width, height, boxes: [[x, y, w, h]], pageCount}`; `GET /api/documents/{id}/pages/{n}.png` returns the picture.
- **How.** Rendered on demand in the reader's child process. Each person's 20 most recent pages are cached, and a page goes with its document. The boxes come from pypdfium2's text search on the page, with spaces normalised.
- **Words not found:** "The passage's words were not found on this page. It is shown whole."

**Code:** `knowledge/extract.py`, `knowledge/worker.py`, `saved_api.py`, `SourcePassages.tsx`, and a new `PageView.tsx`.

### Migration 33 (lands with 30d)

- `document_folders.sync_minutes INTEGER` and `document_folders.watch INTEGER NOT NULL DEFAULT 0`.
- `document_collections (id PK, owner, name 1-80, created_at, updated_at)`.
- `document_collection_items (collection_id, owner, origin, kind document|prefix, added_at, PK (collection_id, origin))`.
- Both new tables join `PERSON_TABLES` (row 7).

### 30d A check interval per folder

- A folder's rules gain **Check every {n} minutes**. Unset, it shows the value in effect: "10 minutes (Workbench's default)". The range is 1-1,440.
- `FolderSync._cycle` reads the record's interval, then the install's.

### 30e Collections (MRC25's "a collection per chat")

- **Making one.** On the Documents screen, select documents, then **Add to collection**. A whole folder or a project's documents joins as a prefix (`folder:<grant>/`, `project:<id>`).
- **An item is kept by origin** (scope and source), so a document read again stays in. One whose document is removed shows "(removed)" until it comes back or the person removes the item.
- **Using one.** A chat's Documents control gains **Search: All my documents / {collection}** (`ChatSettings.documentsCollection`). The index search takes an origin filter.
- **Limits:** 50 collections a person, 5,000 items each.

### 30f Folders on Job Sites (MRC26: "the Job Site extracts, central Workbench indexes")

**What changes.** Today a Job Site folder is refused (call 1). Now a person adds one (`node:<folder id>`) to Documents.

**The site host.** Its file server gains two read-only tools, in a new `index_tools.py`:
- `list_for_index(folder, cursor)`: path, size and modified time, 2,000 a page, under the same caps.
- `extract_text(folder, path)`: `{sha256, mediaType, pages: [{page, text}], headings, reason}`, from the site host's own copy of the extractor in a child process (120 s, memory cap). Components share no code, so the extractor is copied; a test reads the same fixtures in both and expects the same text.

**The site decides (J8).** A workspace whose `read` rule is `ask` refuses background reads: "This folder's machine asks before each read, so Workbench cannot keep it indexed. Ask its administrator to allow reads."

**Workbench.** `folder_sync` gains a remote walk; the plan and the hash rule stay as they are. `originals/` keeps the extracted text, not the file, and Open original fetches the file through the site.

**Sign-in.** Each background call carries the person's most recent Workbench session, as `node_folders` does for a chat. With none left: "Paused: sign in to Workbench to keep this folder up to date." Signing out pauses the sync; row 7's removal deletes the folder.

**Contract.** `site-host.yaml` names the two tools, with a `SiteExtractResult` schema. Site host regenerates; Workbench generates only `common.yaml`, so it reads the result as JSON.

### 30g Check as soon as files change

- **What it is.** A per-folder switch, **Check as soon as files change**, off by default, for local folders. A watcher (`watchfiles`, MIT, wheels for Windows, Linux and macOS) on the folder's root starts a quick check 5 s after the last change. The interval check stays, and the watcher never reads a file: checks still read through held handles.
- **Windows.** One handle on the root, shared for read, write and delete, so renames inside still work. MR7's call 3 objected to a handle on every directory.
- **Linux.** inotify. When the system refuses more watches: "Watching stopped: this system allows no more watches. Checked every 10 minutes."

### Defaults

Nothing is on by default that sends more anywhere: map-reduce asks, page reading is off, collections are opt-in and the watcher is off. Job Site folders put another machine's files in the central index only when the person adds one (say so in the issue).

## 3. Repositories and files

- **workbench:** `knowledge/` (`whole.py` new, `extract.py`, `worker.py`, `index.py`, `ingest.py`, `search.py`, `folder_sync.py`); `answers.py`, `saved_api.py`, `folders_api.py`, `config.py`, `store.py` (33), `api.py` (`ChatSettings` only); web `SourcePassages.tsx`, `PageView.tsx` (new), `Documents.tsx`, `FolderRules.tsx`, `DocumentsSettings.tsx`, `ChatSettings.tsx`.
- **site-host (30f):** a new `index_tools.py`, registered in `file_server.py`, and a copy of the extractor.
- **specs:** `site-host.yaml` (30f); `scripts/row30d-migration-acceptance.py` and `scripts/row30f-job-site-folders-acceptance.py`; "What building found" in both source designs.
- **Codegen consumers:** site-host only (30f).

## 4. Tests that fail before the change

- **30a `test_whole.py::test_read_all_reads_every_part_once`.** 12 parts give 12 map requests and one reduce; a failed part is named in the answer.
- **30b `test_page_reader.py::test_scanned_pdf_read_only_when_switched_on`,** and `test_index_migration_3_to_4`.
- **30c `test_pages_api.py::test_page_png_marks_passage`.** It also checks that another person gets 404.
- **30d `test_folder_interval.py::test_folder_interval_overrides_install`,** and `test_migration_33_from_32`.
- **30e `test_collections.py::test_chat_searches_only_its_collection`.**
- **30f `test_job_site_folder.py::test_remote_folder_indexed_from_site_text`,** and site-host's `test_index_tools.py::test_ask_rule_refuses_background_read`.
- **30g `test_folder_watch.py::test_change_starts_quick_check`.**

## 5. Acceptance and review

**30d** (migration 33). `row30d-migration-acceptance.py`, in CI, on OS-assigned ports with `EUGENE_PLEXUS_*` cleared. A schema-32 store with folders and documents migrates; each folder keeps its state; an interval is set and applied; row 7's purge leaves no collection row. The reviewer attacks the migration on a store full of data and `PERSON_TABLES`.

**30f** (high: background sign-in use, another machine's files, a site-host change). `row30f-job-site-folders-acceptance.py` starts a control root, two agents, a site host and Workbench, on the same kind of ports. It checks that:
1. a question is answered from an added Job Site folder;
2. an edit on the site reaches the index;
3. an `ask` rule refuses with its sentence;
4. signing out pauses the sync;
5. a second person cannot add the folder;
6. the site's files are byte-for-byte as they were.

The reviewer should attack the background refresh token (it must not rotate the browser's session away), a path that escapes the workspace, a hostile file on the site, and the person binding.

**30a, 30b, 30c, 30e, 30g:** changed-file tests, one Chrome check of each screen, and a real run of 30b against a local vision model.

## 6. Do not change

- **workbench:** `MessageView.tsx`, `Markdown.tsx`, `artifacts.py` (31); `tools.py` (29, 32); `context.py`, `conversation.py` (26); `memory_servers.py`, `projects.py` (27, 47); `folder_windows.py`, `folder_linux.py` (23); `local_tools.py`, `mcp_sandbox.py`, `mcp_apps.py` (52, 60).
- **site-host:** `workspace_tools.py` (row 25); `join.py`, `worker.py`, `signing.py` (row 51).
- **Shared:**
  - `store.py`: add the migration and methods only.
  - `api.py`: `ChatSettings` only; row 31 changes it too.

## 7. Size, risks, calls

**Size:** about 10 days in all. 30a 2, 30b 2, 30c 1, 30d 0.5, 30e 1.5, 30f 3, 30g 1. Branches `r30a-whole`, `r30b-pages` and so on.

**Risks:**
- **30a's cost grows with the document.** That is why it asks, and why it stops at 40 parts.
- **30b's quality depends on the vision model.** Each page is marked "read from a picture".
- **30f's sign-in.** If control rotates refresh tokens on each use, a background call could sign the browser out. Check that first. If it rotates them, 30f needs a narrow grant from control: a contract change, and one more review.
- **30g on a network share.** Change events may not arrive, and the interval covers it.

**Calls only Troy can make:**
- **MRC26: the Job Site extracts, central Workbench indexes.** Recommended, and built. The sync uses the person's most recent session, and pauses when there is none.
- **The page reader.** The owner chooses the model, and reading is off until the person switches it on. Recommended.
- **Map-reduce.** Ask each time (recommended), or automatic.
- **The watcher.** Build it as a hint, off by default (recommended), or keep MR7's call 3 and drop it.
- **Click-through.** A rendered picture of the page (recommended), or bundling pdf.js (about 1 MB, and it runs PDF code in the page).
- **One migration (33)** for 30d, 30e and 30g. Recommended.

## Calls answered by Troy (2026-10-21)

- **DOC-SCAN: models are given roles.** The owner tags models with roles (row 71, MODEL-JOBS). Page reading uses the model with the "reads pages" role; when one exists, reading pages is on for everyone. Each permission group can later route each role its own way (row 37). This row needs row 71.
- **DOC-WHOLE: Choice 2.** A question about a whole document reads it in parts without asking.
- **DOC-WATCH: Choice 1.** A file watcher as an option, off by default; the timer stays.
