# MR6 the rerank door, and Open WebUI's document search through Eugene: the run of record

Design: `docs/design/workbench-memory-and-documents.md` (MR6, MRC22); its header lists the calls made while
building. Contract: specs `e43483f`, amended `ede2e4a` (named enum, passage limits, `truncate: false`),
`8ba2e16` (search models chosen by `locality`), `4d4eb4c` (a corrected app environment resets a
database-first app once; a running search model first), `7ddc4d9` (an app's key has an app's limits; no
start without the gateway's address).

A result sorter (reranker) scores the passages a search found against the question. `POST /v1/rerank`
takes Jina's and Cohere's body (`documents`) and TEI's (`texts`) and answers in the request's shape, scores
0 to 1, best first, one model per request. Open WebUI is seeded to search documents through Eugene: the
install's local search model, its sorter as the external reranker, hybrid search.

## Acceptance of record (real processes)

`specs/scripts/mr6-rerank-acceptance.py`, Amish_Station, 2026-10-12 07:50 CDT, about 4 minutes:

- a real agent supervising a real library, gateway and the drivers it keeps for each runtime;
- llama.cpp b10948 on the processor running Qwen3-Reranker-0.6B, bge-reranker-v2-m3 (declared
  `mode: reranking`), Qwen3-Embedding-0.6B and Qwen3-0.6B;
- Open WebUI 0.11.4 started from the environment the agent's launcher renders from the catalogue;
- ports chosen by the OS (58246-63381), every ambient `EUGENE_PLEXUS_*` dropped.

**71 passed, 0 failed, 0 skipped.** Heads: gateway `226b607`, inference-driver `b1d6820`, agent `85e9e76`.

```
D1   both sorters listed as exactly rerank; the embedder embeddings; the chat model not rerank
D2   Jina body, Qwen3-Reranker: the answering passages 0.9941, 0.9998; the others 0.00086, 0.000021 (0.45 s)
D3   Cohere objects, return_documents, top_n 2: the two that answer, document.text exactly as sent
D4   TEI texts to bge: a bare array 0..1; return_text; raw_scores gives 9.34, 7.83, -5.368, -10.986
D5   bge mapped 9.34 -> 0.99991, 7.83 -> 0.99960, -5.37 -> 0.00464, -10.99 -> 0.00002, the logistic of each
D6   model left out: 400 naming both sorters; a key allowed one: answered by it; allowed none: 404
D7   a chat model named: 400, "serves chat, completion and not rerank. Send this request to ..."
D8   an empty list: 200 with no results, and no backend reached (the driver's and engine's own logs)
D9   1,001 passages: 400; documents[3] without text: 400 naming documents[3]; a passage over the
     2,048-token batch: 400 in the engine's words, not cut, not a server fault
D10  ignored settings named in the contract's order; truncate: false alone names nothing
D11  a slot [Qwen3-Reranker, bge] with Qwen3 stopped: 503 naming the stopped runtime; bge received nothing
D12  two replicas of one sorter, one stopped while still listed: all six answered, two after a failover
D13  30 reranks answered, 30 metrics rows under door rerank; the too-long passage an error row
D14  a 16.2 MiB body: 413, nothing served
O1   the launcher seeds the search model, the sorter, its engine and address, hybrid search; a stopped
     embedder is still named, with a note; none listed leaves the variable unset, with a note
O3   Open WebUI's settings show what was seeded; all five of its OpenAI connections (documents'
     embeddings, speech-to-text, text-to-speech, images, image edits) are the gateway's
O4   a 30-paragraph upload: 1 embeddings request, processed in 4.0 s
O5   retrieval puts the code-word chunk first at 0.9913 (one rerank of 5 passages); the chat answers
     "JACKDAW-7342."
O6   the sorter stopped: Open WebUI still answers, its log names the failed rerank, the gateway's
     answer names the stopped runtime
O7   an install made with the old entry held https://api.openai.com/v1 for all five; the corrected entry
     reset it once (with the note), then not again
O8   the registry mints an app's key with 8 at once and 600 a minute beside writeLogs
O9   201 chunks in 7 requests (32 each, one at a time), none refused, 44.2 s; the code word found first
O10  no gateway address: the start is refused in words, nothing written
```

Sabotage of the acceptance itself, 8 of 8 caught:

| Break | Caught by |
|---|---|
| driver `score = raw` | D4a-c, D5 |
| a clamp in place of the logistic | D5 |
| `pick_rerank` with a second tier | D11b-c |
| the catalogue without `RAG_RERANKING_MODEL` | O1a, O3, O5 |
| the pre-MR6 entry | O3b, O7 |
| no batching | O4 |
| a batch of 64 | O9a |
| agent `0f24cba` | O8, O10 |

## Defects the acceptance found

1. **Privacy, since C4.** Open WebUI 0.11.4 resets `OPENAI_API_BASE_URL` to `https://api.openai.com/v1`
   after reading its connections (`config.py` about line 367). So every per-feature address the
   catalogue did not set pointed at OpenAI, and an uploaded document's chunks were POSTed to
   `https://api.openai.com/v1/embeddings` (refused 401 for want of a key, but sent). Fixed in agent
   `0f24cba`: all five addresses and keys name the gateway. An install that already started is reset once
   by the corrected entry (O7).
2. A stopped search model left the variable as if none existed; it is now named, with a note
   (`0f24cba`).
3. **Open WebUI's upload failed on the app key's limits.** It sends one embeddings request per chunk, all
   at once, with no retry on 429, and the key allowed 2 at once and 60 a minute: 2 of 10 served. Fixed in
   agent `85e9e76` with 32 chunks a request, one at a time, and an app's key minted with 8 at once and
   600 a minute.
4. An app naming `{gatewayUrl}` could start without it, back on OpenAI's defaults. It is now refused
   (`85e9e76`).
5. **Open**: a replica whose engine is loading is not failed over from (llama-server's 503 "Loading
   model" becomes a 502 that is not safe to retry): inference-driver#10.

Building found, before the acceptance:
- the inline enum rename (named `RerankObject`);
- the passage length limit (written into the contract);
- TEI's defaults named on every answer (`truncate: false` is honoured now);
- `owned_by` never `local` for a local model (gateway#12);
- an alias whose first target does not serve the door answering 503 "not ready" (gateway#11);
- a reranker file without metadata read as an embedder (library#10).

## Unit tests and sabotage

- **inference-driver:** 1,186 passed (95 new); 47 sabotages caught.
- **gateway:** 1,414 passed (115 in `test_rerank.py`); 77 sabotages caught.
- **agent:** 2,510 passed; 73 sabotages caught on the final code.
- The real llama-server check in the driver build: Qwen3-Reranker answered probabilities, passed
  through; bge answered logits, mapped; a 6,000-word passage was a terminal 400 naming 2,048.

## Known limits

- Open WebUI keeps what its first start saw: with no search model running then, its admin picks one in
  its Admin Settings, Documents. A key minted before this change keeps 2 at once and 60 a minute: raise
  it on the keys page.
- Every future edit to Open WebUI's catalogue environment resets its admin's settings once.
- A refused start for a missing gateway address is retried against the address resolved when the app
  was started; it starts once the app is restarted.
- Open WebUI's query prefix for Qwen3-Embedding is not set (MR5 measured +12.8 points of recall@10
  with it); the hub-side prefix slice will give every client the right one.

## Pinned

- gateway `226b607`, inference-driver `b1d6820`, agent `85e9e76`.

## The live run

Owed: Troy, on an install with Open WebUI, Updates, then uploads a document in Open WebUI and asks about
it. If Open WebUI already ran, its first start after the update resets its settings once, by design.
