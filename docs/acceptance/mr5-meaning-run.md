# MR5 search by meaning, fused with the words: the run of record

Design: `docs/design/workbench-memory-and-documents.md` (sections 4.1, 4.2, 4.4, 4.7, 4.9, 5.3, 5.7; its
header lists the calls made). Saved documents are searched by words first (MR4); a local search model,
reached through Eugene's gateway, adds meaning as it catches up, and the two are fused by reciprocal rank
(k=60, equal weights). Words-only search keeps working whenever meaning cannot.

## Acceptance of record (real processes)

`workbench/scripts/mr5-meaning-acceptance.py`, Amish_Station, 2026-10-11: a real Workbench, gateway, three
drivers, llama.cpp b10948 on the processor with Qwen3-0.6B for chat and two search models
(Qwen3-Embedding-0.6B Q8_0 and nomic-embed-text-v1.5), 76 of Eugene's own design documents (specs
`c5f725d`, 2,810 passages), ports 8500-8513, every ambient `EUGENE_PLEXUS_*` cleared. **52 passed, 0
failed.**

- Import: all 76 files searchable by words in 12 s; then "Adding meaning: n of N passages, about X
  left", ready after 13.1 minutes (3.6 passages a second on the processor).
- The search model killed mid-import at 352: the screen named it ("Searching by words only. No search
  model is running."), questions and a chat were still answered from the words, and the import resumed
  when it came back; every passage was given meaning exactly once.
- Swapping to nomic: meaning paused for both people, named both models and offered Rebuild; nothing of
  nomic's was stored until Rebuild; after it every vector was nomic's, with its own prefixes. The time
  left during the 5.6-minute rebuild was within a few seconds (263 vs 259, 175 vs 177, 85 vs 80).
- The quality gate: 60 questions over 53 files, written by an agent shown only the heading outline
  (committed as `scripts/mr5-meaning-questions.json`):

```
recall@5      words (BM25)   meaning      hybrid
              0.500 (30/60)  0.583 (35)   0.600 (36)
MRR@5         0.331          0.459        0.432
hybrid minus words    +0.100  (95% interval -0.017 to +0.217)
hybrid minus meaning  +0.017  (95% interval -0.117 to +0.150)
```

Hybrid beats both on recall@5, so the gate passes, but its margin over meaning alone is one question and
inside the noise; meaning's MRR is higher. Words found 10 questions meaning missed, meaning found 15 that
words missed. RRF stays at k=60 with equal weights, as designed: words are what find an exact identifier.

Defects the live run found, fixed before landing: a refused passage's note quoted the wrong limit (now
the engine's own words); estimates from tiny batches and from the request limit's burst (now measured over
real work, capped at the allowance).

The page in Chrome (`tests/test_library_browser.py`, extended with a deterministic embeddings route in
the fake gateway): "Searching by meaning and words.", a passage found by meaning, its Sources tag, and
Test a question's places and closeness.

## Unit tests and sabotage

- Python: 1,305 passed (224 new for the server); with every Chrome check, 1,318 passed.
- web: 2,328 passed.
- Sabotage: server 82 of 82 caught; page 99 of 99 (75 unit, 17 Python, 7 Chrome).
- A gitleaks scan of the committed tree finds nothing.

## Known limits

- The search model on the live 5090 box is Troy's call (it holds the GPU); a CPU search model gives
  meaning to about 3.6 passages a second, so 10,000 passages take about 45 minutes.
- At the default 30 requests a minute, a fast search model is held to 8 passages a second until the
  owner raises `documentsEmbedRequestsPerMinute`.
- The no-words floor (0.5) is measured for Qwen3-Embedding only; other models send their top passages
  whatever their closeness.

## Pinned

- Workbench main `fa3c014` (server `b85f0dd`, page `fa3c014`), dist `2979d97`; agent `fbe5a9d`
  (catalogue).

## The live run

Owed: Troy starts a search model (Qwen3-Embedding-0.6B from the console's Search models shelf; on the
processor or the GPU, his call), and asks his documents a question in his own words.
