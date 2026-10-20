# MV5b probe: Hindsight 1.0.0 as a local memory server

**2026-10-19. The probe passes, with four conditions for the catalogue entry (below).**

- **Script:** `scripts/mv5b-hindsight-probe.py`. It writes one JSON per run to `docs/acceptance/mv5b-data/`.
- **Design:** `docs/design/workbench-memory-v2.md`, section 52 (the probe's plan) and section 56 (what
  it found).
- **No product code ran from Hindsight's side.** A throwaway stack on ports 8520-8529, with every
  `EUGENE_PLEXUS_*` variable dropped:
  - three `llama-server`s on the RTX 5090: the chat model, Qwen3-Embedding-0.6B and
    bge-reranker-v2-m3;
  - a driver for each, and a real gateway;
  - `hindsight-api` with its LLM, embedder and reranker pointed at the gateway's `/v1`,
    `/v1/embeddings` and `/v1/rerank` (as Cohere's), on embedded `pg0`.

## Results

| | Gemma 4 12B | Qwen3.8-27B | Linux (WSL, stub models) |
|---|---|---|---|
| Install | `hindsight-all`: 1.86 GiB venv | same venv | `hindsight-all`: 6.27 GiB, 24 s with `uv` |
| Ready on embedded pg0 | 11.7 s | 10.1 s | 7.1 s |
| Peak RSS, Hindsight's process tree | 0.48 GiB | 0.42 GiB | 0.41 GiB |
| pg0 data | 0.22 GiB | 0.29 GiB | 0.15 GiB |
| Outside connections (sampled every 0.2 s) | none in 741 samples | none in 904 | none in 35 |
| Listening off loopback | none | none | none |
| Retain, 36 sessions | 140 s (median 3.9 s, max 6.2 s), 0 failed, 109 memories | 173 s (median 5.1 s, max 8.9 s), 0 failed, 84 memories | 200 |
| Recall, 21 questions, answered in the top 5 | **21** (4 stale first) | **21** (1 stale first) | 200 |
| Stand-in for past chats, embedder cosine | 19 (3 stale first) | 19 (3) | |
| Stand-in for past chats, BM25 | 16 (4) | 16 (4) | |
| Recall time | median 0.25 s, max 1.39 s | median 0.21 s, max 2.27 s (an early call) | |
| Workbench's adapter | every verb found; in-turn recall 0.28 s | same, 0.21 s | |

- **The labelled person.** One person, 36 sessions, built from MV3's sets. It has 20 facts, preferences,
  projects and events, five superseded facts, and 11 distractors from MV3's `nothing` and `transient`
  sets. Each session is retained as Workbench sends it under Standard: the person's own words, with
  `context` "A Workbench chat". "Stale first" means the superseded value ranked above the current one.
- **The past-chats stand-ins are not Workbench's past-chats search.** They are the same embedder's
  cosine and a plain BM25, each over the same 36 sessions. The built-in notes were not run: MV3
  measured that no model passes Keep's bar, so on these sessions the notes would hold what a person
  accepted from suggestions, not what was said.
- **Hindsight keeps the noise too.** "User is ill and requested short answers for the day", "User
  is considering taking up pottery", "Sam (user's friend) is vegan" and "Sales rose 4% and costs
  fell" were all kept as facts about the person. Hindsight has no bar like Keep's.
- **Superseded facts.** Hindsight keeps the old fact and the new one. With Gemma, the old one ranked
  first for the editor, the city, the phone and the diet. With Qwen, it ranked first for the city
  only. The new fact was always in the top 3.
- **pg0 brings PostgreSQL inside its own binary.** It extracted it to `~/.pg0/installation` with no
  download seen.
  - It takes 5432 by default, then the next free port. The Gemma and Qwen instances were on 5432 and
    5433.
  - It listened on loopback only.
- **Static read of the installed packages.** The outside addresses in Hindsight's code belong to
  providers this setup does not use (OpenAI, Groq, Gemini and others). The rest are an OTLP exporter
  that is off unless configured, and the `iris` file parser (Vectorize's API), which is used only
  when named.

## The four conditions for a catalogue entry

1. **Install `hindsight-api-slim[embedded-db]==1.0.0`, not `hindsight-all`.**
   - The slim package is 1.07 GiB on Windows, against 1.86 GiB. The Linux venv's 6.27 GiB is
     mostly CUDA torch, which nothing here loads.
   - The slim install started on Windows with stub models and answered retain and recall.
   - It made no outside connections (`mv5b-data/windows-slim.json`).
2. **Name pg0's port** (`pg0://name:port`). Its default, 5432, is any other PostgreSQL's.
3. **Stop pg0 explicitly.** On Windows, killing `hindsight-api`'s process tree left `postgres.exe`
   running, because `pg_ctl` starts it outside that tree.
   - The probe's teardown now runs `pg0 stop --name <instance>`, which stops it cleanly.
   - The peak RSS above may miss part of postgres for the same reason.
4. **Its REST API answered with no key.** The MCP endpoint took its token (`HINDSIGHT_API_MCP_AUTH_TOKEN`).
   - The REST API under `/v1/default/banks/...` answered this run's retain, recall and list calls
     with no key, on loopback.
   - Any local process could read every memory. The entry must set Hindsight's API key for the
     whole server, not only for MCP.
   - Hindsight has a key for this: `HINDSIGHT_API_TENANT_EXTENSION=hindsight_api.extensions.builtin.tenant:ApiKeyTenantExtension`
     with `HINDSIGHT_API_TENANT_API_KEY`, which its docstring says covers MCP too.
   - That key was not run in this probe. MV5b's acceptance must show that REST and MCP both refuse
     a missing key.

## A Workbench defect it found, fixed

**`forget` deleted nothing.** Workbench mapped `retain` to Hindsight's `retain`, which only queues
the content and answers "Memory storage initiated". A `forget` sent 20 ms later answered
`document_deleted: 0`.

So a chat deleted before Hindsight had read its exchange kept its words on the server, and Workbench
recorded it as forgotten.

**The fix.** Workbench now prefers `sync_retain` when a server lists it. A retain answers once the
words are kept, with its own 120 s limit (`RETAIN_SECONDS`).

- **The regression test** (`test_verbs_are_found_by_name_and_need_their_argument`) fails without
  the fix.
- **Re-run with the fix** (`mv5b-data/gemma-4-12b-sync.json`): retain answered "Memory stored
  successfully" in 1.46 s. The memory was recalled, then `forget` answered `document_deleted: 1`.
- **Existing connections** keep the verbs found when they connected. They pick up `sync_retain`
  when they connect again.

## Before the runs of record

- **The first Windows run stopped at its preflight.** The drivers asked the llama-servers what they
  serve before the models had loaded, so the gateway listed the reranker as a chat model. The probe
  now waits for each server's `/health`.
- **The Gemma and Qwen runs left their `postgres.exe` running.** They were stopped by pid, before
  the `pg0 stop` teardown was added.
