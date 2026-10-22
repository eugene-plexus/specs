# Row 65: Ollama: keep a model in the Library, and read a worker's own Ollama store

Lane LIB, fourth in its lane. It needs row 22's relocate, which is earlier
in the same lane. Cross-component. Size S-M, split into 65a and 65b. Repos:
library, agent, ui, specs. This row includes library#16.

Sources: `console-ux-pass.md` CX9 (calls C1 and C3, "what building
found"); library `ollama_detect.py`, `formats/ollama.py`, `folders.py`,
`config.py`, `store.py`, `downloads.py`, `paths.py`; agent
`run_worker.py`; memory `feedback_library_is_home_of_model_files`.

## 1. What it delivers

**65a: the Library's own machine.**

- **Keep in the Library.** An Ollama model gets this action. On the same drive it makes a hard link into a writable Library folder, which uses no extra disk. Otherwise it copies the file and checks the copy against Ollama's digest. The kept file belongs to the Library: Ollama's `rm`, a re-pull or a prune does not remove it.
- **The kept model keeps its served name** (`llama3.1:8b`), and its profiles move to it.
- **library#16, both parts.** A new tag never renames a model. A write through a symlink or a junction into an Ollama store is refused.
- **Found while designing (to confirm first):** on a Windows service install, the Library runs as LocalSystem. So `Path.home()` is `C:\Windows\System32\config\systemprofile`, and the person's `C:\Users\<name>\.ollama\models` is never found. The fix: detection looks in each user profile.

**65b: a worker's own store.**

- **Each agent reports its store.** The agent reads its own machine's Ollama store and sends the manifests to the Library.
- **The Library lists those models** as "In Ollama on Amish_Station". They have one action, Keep in the Library, which sends the file from that machine through the existing upload path.
- **After Keep, it is an ordinary Library model.** The worker's copy of it is a hard link to Ollama's blob, so the worker uses no second disk.

## 2. The design

### Served names (library#16, part 1)

- **The store keeps the name** (library `store.py`, `replace_models`). For a model with `ollama`, the stored `name` is kept while it is still one of `ollama.tags`.
- **When that tag is gone,** the model takes the first remaining tag, and the log says: "llama3:latest is gone from Ollama. This model is now served as llama3:8b."
- **The contract text changes.** In `library.yaml`, `OllamaDetail` says "Its `name` is the first of `tags`". The new text: "the tag it was first listed under, while that tag exists."
- **The UI lists the other names correctly.** `OllamaNote` shows the tags other than `model.name`, not `tags.slice(1)`.
- **A runtime's served name is already fixed** when it is declared: `run_worker` sets `modelAlias`.

### Real paths (library#16, part 2)

- **A new helper, `paths.real_within(child, parent)`.** It runs `os.path.realpath` on both paths, which resolves symlinks and junctions, then compares their parts. For a path that does not exist yet, `realpath` resolves the longest part that does. `normalize` stays lexical, because it is for identity (its docstring's rule).
- **Every write guard checks both the lexical path and the real path:** a download's destination, a provenance file, a prepared file, Delete, and Keep's target.
- **`writable_roots` drops a folder** whose real path is inside a store.
- **The refusal** is 409 `ReadOnlyFolder`: "D:\models\shared is a link into the Ollama model store C:\Users\troyc\.ollama\models. Ollama manages the files there, and the Library never writes there. Choose another folder."
- **The folder list** shows such a folder as read-only, with the same sentence.

### Finding a store from a service account (`ollama_detect.py`, `config.py`)

This applies on Windows when `Path.home()` is under `config\systemprofile`. Detection looks in:

- **the machine's `OLLAMA_MODELS`**, from `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment`;
- **each profile in `ProfileList`** (`HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList`) that has a real folder:
  - that user's `OLLAMA_MODELS` from `HKU\<SID>\Environment`, when the hive is loaded;
  - otherwise `<profile>\.ollama\models`.

**Results:**

- Every store found is listed, so two people give two stores. `found_ollama` becomes `found_ollama_stores()`, which returns a list.
- A store that cannot be read is listed with its cause, not dropped.

### Keep in the Library (65a; new `keep.py`, routes in `routes/models.py`)

**Contract:**

- **`POST /v1/models/{model_id}/keep`** takes `{folder?}` and returns 202 with a `KeepJob`. `folder` defaults to the first writable folder.
- **`KeepJob`** is `{id, model, state: running|done|failed|cancelled, method: link|copy, bytesDone, bytesTotal, target, error}`.
- **`GET /v1/keep-jobs/{id}` and `DELETE /v1/keep-jobs/{id}`.** DELETE cancels a copy.
- **`LibraryModel.keptFrom`** is `OllamaKept {servedName, tags, digest, store, keptAt, method}`. The store keeps it, keyed by the kept file's path, and `replace_models` applies it. The scanner does not change.

**How a Keep runs:**

1. **Check the source and the target.** The model must have `ollama` and be present. A target whose real path is inside a store is refused.
2. **Choose the target.** It is `<folder>/ollama/<name>/<name>.gguf`, where `<name>` is the served name with `:` and `/` written as `-`. A projector goes beside it as `mmproj-<name>.gguf`, because the scanner pairs a projector by its folder.
3. **Link on the same drive.** Use `os.link`. On any link error, copy instead, and the job says why: "Copied, not linked: D: and C: are different drives."
4. **A copy checks its space first:** "Not kept: llama3.1:8b needs 4.9 GB, and D: has 2.1 GB free."
5. **A copy is checked against the digest.** It is written to `.partial`, hashed as it goes, and compared with the blob's digest (Ollama names each blob by its SHA-256). If they differ, the partial file is deleted and the job fails: "The copy of llama3.1:8b did not match Ollama's file (SHA-256 differs). Nothing was kept."
6. **Rescan, then move the profiles** from the Ollama entry to the kept one with row 22's relocate. The match is `same`, by contents. The click on Keep is the consent.
7. **The served name stays the same** (agent `run_worker.py`). The agent sets `modelAlias = model["name"]` when the model has `ollama` or `keptFrom`.

**UI:**

- **On an Ollama model:** a **Keep in the Library** button.
- **While a Keep runs:** "Keeping... 2.1 of 4.9 GB".
- **When it is done:** "Kept in D:\models\ollama\llama3.1-8b (linked: no extra disk)".
- **On the kept model:** "Kept from Ollama - served as llama3.1:8b".

**Rule:** the Library never opens a kept file for writing. A hard link shares Ollama's bytes.

### A worker's store (65b)

**Agent:**

- **New `ollama_store.py`.** It is a copy of the Library's manifest reader (the polyrepo rule), with the detection above.
- **The report.** At start, and every 60 seconds when the listing has changed, the agent sends `PUT /v1/nodes/{node}/ollama` to the Library. The body is `{stores: [{path, models: [{tags, digest, sizeBytes, runner, projectorDigest?, projectorSizeBytes?, architecture?, needsMigration?}], skipped: [{name, detail}]}], readAt}`. The architecture comes from the GGUF header (`gguf_context`).
- **The setting `reportOllama`** (agent config, default on) stops the report. On the Library's own machine there is no report, because the Library reads that store itself.

**Library:**

- **The report route.** `PUT /v1/nodes/{node}/ollama` needs a `sub: agent` service token whose issuer is `node:{node}`. Any other machine gets 403: "A machine reports only its own Ollama store." The body is limited to 1 MiB and 2,000 models.
- **The read route.** `GET /v1/nodes/ollama` returns `{nodes: [{node, readAt, stores}]}`.
- **These rows are not Library models.** They have no id, profiles, fit or Run. A model whose digest the Library already holds says "Already in the Library".
- **Keep from a worker.** `POST /v1/nodes/{node}/ollama/keep` takes `{digest, folder?}`.
  1. The Library asks that machine's agent to send the blob (new agent route `POST /v1/ollama/send`, in `agent.yaml`) through the LS10 upload path, in 16 MiB chunks.
  2. It checks that the SHA-256 equals the digest.
  3. It lands the file as in 65a, with `keptFrom`.
- **The worker's copy is a link** (agent `model_copies.py`). When the worker needs a copy of a kept model, and a blob with the same digest is in its own Ollama store on the same drive, the agent hard-links the blob instead of downloading it.

**UI:**

- **A Library section "In Ollama on other machines".** Each row reads like "Amish_Station - llama3.1:8b - 4.9 GB", with a **Keep in the Library** button, and the section shows "Read 2 min ago".
- **A machine that is not reporting:** "Amish_Station has not reported since 20:14."

### Defaults

- **Nothing is deleted.** Keep never deletes Ollama's file. Cancel deletes only the Library's `.partial` file.
- **Reporting is on.** A worker sends model names, sizes and digests to the Library, which is inside the install. No file content moves until someone presses Keep.

## 3. Repositories and files

- **specs:**
  - `library.yaml`: the `OllamaDetail` text, `OllamaKept`, `KeepJob`, the keep routes and the report routes;
  - `run-operations.json`, regenerated, because it embeds `LibraryModel`;
  - `agent.yaml`: `/v1/ollama/send`;
  - `scripts/cx9-ollama-models-acceptance.py`, extended;
  - `console-ux-pass.md` CX9: what building found.
- **library:**
  - `paths.py`, `ollama_detect.py`, `formats/ollama.py`, `config.py`, `store.py`, `downloads.py`, `deletion.py`;
  - new `keep.py` and `node_ollama.py`;
  - `routes/models.py` and a new nodes route module;
  - tests.
- **agent:**
  - `run_worker.py`;
  - for 65b: new `ollama_store.py`, `model_copies.py`, the send route and the report loop;
  - tests.
- **ui:** the library page (Keep, the kept note, "In Ollama on other machines") and the folder list.
- **Codegen:**
  - Library and ui regenerate.
  - The gateway names `library.yaml` but uses none of this. Diff to confirm, and do not re-pin it.
  - The agent does not generate from `library.yaml`. Its report body is hand-written, like its other calls to the Library. The agent regenerates `agent.yaml` for the send route.

## 4. Tests that fail before the change

- **library `tests/test_ollama_store.py::test_new_tag_keeps_served_name`.**
  1. A store holds `llama3:latest`. Scan.
  2. Add a manifest `llama3:8b` for the same blob. Scan again.

  Expected: the name is still `llama3:latest`. Today it is `llama3:8b`.
- **`test_write_through_link_into_store_refused`.** A writable folder is a symlink (Linux) or a junction (Windows) into a store. A download into it must get 409. Today the download lands in the store.
- **Also for 65a:**
  - `test_service_account_finds_profile_store`, with an injected profile list;
  - `test_keep_links_same_volume`;
  - `test_keep_copies_and_checks_digest`, with `os.link` patched to raise `EXDEV`;
  - `test_keep_moves_profiles_and_keeps_name`.
- **For 65b:**
  - library `test_node_reports_only_its_own_store` (403) and `test_report_lists_models_for_node`;
  - agent `test_report_body_from_store` and `test_node_copy_links_ollama_blob`.

## 5. Acceptance

The change crosses components. Extend `cx9-ollama-models-acceptance.py`, on Windows and Linux runners, with a stand-in store, its own ports (never 8079-8083), and `EUGENE_PLEXUS_*` cleared.

1. Both library#16 checks.
2. Keep by link. Then Keep into a folder on another file system, which must copy.
3. Delete Ollama's blob. The kept model still runs, under the same served name.
4. For 65b, start a second agent as a worker with its own stand-in store.
   1. The Library lists the worker's model.
   2. Keep sends it to the Library.
   3. The worker's copy is a link: same inode, no second download.

## 6. Do not change (other lanes' hot files)

- **library:**
  - `scanner.py` (17, 61);
  - `formats/gguf.py`, `preflight.py` (18, 68);
  - `engine_fit.py` (63);
  - `hardware.py` (43).

  Earlier LIB rows land first: 16 (`fit.py`, `hardware.py`), 22 (`store.py`, `routes/models.py`) and 21 (`profile_storage.py`, `routes/profiles.py`).
- **agent:**
  - `runtimes.py` (13);
  - `admission.py` (9);
  - `benchmarks.py` (10);
  - `host_probes.py` (43);
  - `engines/*` (ENG).
- **gateway:** `profiles.py` (48).

## 7. Size, split, calls

- **65a: S+, about a day.**
- **65b: M, about a day and a half.**
- **Order:** 65a goes first. It can ship alone.

**Risks:**

- A hard link shares bytes with Ollama: a write in place would corrupt Ollama's blob. The rule is that the Library never opens a kept file for writing.
- On Windows, Ollama's delete still fails while Eugene serves the kept link. The file is the same file, and Windows locks the file, not the name.
- If the Library's state is reset, a kept model's served name falls back to its file's name.

**Calls for Troy:**

1. **A worker's Ollama model: Keep it first, or Run it in place on the worker?** Recommend Keep first. Models then have one home (Troy, 2026-10-09), and the worker's copy uses no disk because it is a link to Ollama's blob. The cost is one copy over the network.
2. **Should workers report their Ollama stores by default?** Recommend on. Only names, sizes and digests move, inside the install.
3. **Should Keep move the profiles by itself?** Recommend yes. The click is the intent, and the contents are proven the same.
4. **Where should kept files go?** Recommend `<first writable folder>/ollama/<name>/`, with a folder picker for the person.

## Calls answered by Troy (2026-10-21)

- **OLLAMA-1 to OLLAMA-3: Choice 1 each.**
