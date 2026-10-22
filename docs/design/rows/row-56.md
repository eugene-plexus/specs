# Row 56: files, vector stores and `file_search`

Lane GW, after row 53 (the platform store and Files). Cross risk. Sources:
MRC24 (`workbench-memory-and-documents.md` §3.3: option B1's vector-store
operations; OpenAI chunks in 800-token windows with 400 overlap and
returns file-level results), `server-run-tools.md` (`file_search` as a
server-run tool), Workbench's retrieval code (`knowledge/chunk.py`,
`index.py` FTS5 with BM25, `vectors.py` numpy scan, `search.py` reciprocal
rank fusion), gateway `responses.py` (today: "`file_search` … is a tool
this gateway cannot run").

## 1. What it delivers

- **OpenAI's vector stores:** create a store, add files (from row 53's
  Files), search it (`POST /v1/vector_stores/{id}/search`), list and
  delete, with OpenAI's shapes and statuses.
- **`file_search` runs on the server.** A Responses request with the
  `file_search` tool and `vector_store_ids` gets answers grounded in those
  files, with `file_citation` annotations, as on OpenAI. Apps built on the
  Assistants-style retrieval work against local models.
- **Search quality is Workbench's:** words (BM25) and meaning (the
  install's Embeddings role, row 71), fused, with an optional reranker.

## 2. Design

### Indexing (platform-store)

- **Code copied from Workbench, not imported** (components share schemas,
  never code): the chunker, the FTS5 index, the vector scan, the fusion.
  Chunking follows OpenAI's `chunking_strategy`: `auto` (800 tokens, 400
  overlap) or `static` with the caller's sizes.
- **Text extraction** in a child process with a timeout (Workbench's
  MRC19), for PDF, DOCX, text, Markdown, HTML, code: the same parsers.
- **Embeddings** through the gateway's `/v1/embeddings` with
  `model: role:embeddings` (row 71), as the store app's own key; a store
  remembers the embedding model it was built with and refuses to mix
  (Workbench's identity check). No embedding model: word search only, and
  the store's `status` says so ("searching by words; give a model the
  Embeddings role for meaning").
- **One index file per vector store** (`stores/<id>.sqlite3`), owned as
  row 53 says; `expires_after` as OpenAI's.
- **File batches** (`/v1/vector_stores/{id}/file_batches`) add many files
  with statuses per file.

### `file_search` (gateway)

- The Responses door runs `file_search` as a server-run tool: when the
  model calls it, the gateway searches the named stores (owner checked by
  the store app), returns the top passages (`max_num_results`, default 10)
  to the model, and the final message carries `file_citation`
  annotations (file id, filename, index in the text).
- `include: ["file_search_call.results"]` returns the search results, as
  on OpenAI.
- Chat Completions has no `file_search` (OpenAI neither); the door's
  refusal stays.

### Console

The store app's page lists each owner's stores (counts and sizes only for
the owner of the install; contents only to their owner).

## 3. Repositories

platform-store (stores, indexing, search), gateway (`file_search` in
`responses.py` and `server_tools.py`, routing), specs (contracts:
`gateway.yaml` vector-store paths and the tool; `platform-store.yaml`).

## 4. Tests that fail before

- platform-store `test_vector_stores.py::test_a_file_is_chunked_800_400_and_searchable`.
- platform-store `test_vector_stores.py::test_mixed_embedding_models_are_refused`.
- platform-store `test_vector_stores.py::test_words_only_without_an_embeddings_model`.
- gateway `test_file_search.py::test_the_tool_runs_and_cites_the_file`
  (today: "a tool this gateway cannot run").
- gateway `test_file_search.py::test_another_owners_store_is_not_found`.

## 5. Acceptance (CI, Linux, about 5 minutes)

`specs/scripts/row56-file-search-acceptance.py` on row 2's harness with
the store app, the fixture backend (it calls `file_search` when asked, and
serves embeddings): upload three files, make a store, wait for
`completed`, search it, then a Responses request whose answer cites the
right file; another person's request naming the store gets the not-found
answer; a store with `expires_after` 1 day is listed with its expiry.

## 6. Do not change

Workbench's knowledge code (copy it); row 53's ownership; row 57's other
Responses tools.

## 7. Size and risks

L, about 3 days. Risks:
- **Copied retrieval code drifts from Workbench's.** The copy names its
  source commit; a later row may share it as a component if a third
  consumer appears.
- **Big stores on a small machine:** the numpy scan holds to about 300,000
  passages (Workbench's measurement); a store beyond that says so.

**Calls:** none.
