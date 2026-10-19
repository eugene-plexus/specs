# Memory research, October 2026: keep, reshape or replace

Written 2026-10-19 for Troy's brief (`docs/private/handoff-memory-research.md`) and his message the same
day: decompose memory along CoALA's four types, choosing vector search or Graph RAG by use; let models
that can write memory do so; hold a very large body of memories; choose what is relevant each turn.
Research only: no repo code was changed. Five researchers (Sonnet, web) reported; the synthesis, the
recommendation and the calls are mine.

**Status: Troy took every call on 2026-10-19 (section 9). The build follows section 10, MV1 first; each
slice's design goes in `workbench-memory-v2.md`, which MV1's session starts.**

Tags. **[R]** a researcher verified it at a primary source on 2026-10-19 (sources in section 12).
**[Vendor]** the figure is the vendor's own and not reproduced. **[I]** my inference. **[U]** needs a
measurement. Nothing here was re-verified by me beyond reading the reports and this repo's design docs.

---

## 1. The answer on one page

**Reshape, do not replace.** Keep Workbench's memory as the built-in default and the floor that works on
any hardware, rebuild it around CoALA's four memory types, raise the limits by an order of magnitude,
let any model the person allows keep memories on its own (Eugene recommends models from measurements and
says why; the person decides), with receipts, add recall of past chats, and put one
contract in front of it so outside memory systems can plug in as optional backends.

Why not replace it with an open-source memory system:

1. **The field is unstable.** In the past twelve months Letta archived its memory server and became a
   coding-agent harness; Zep deprecated its community edition (cloud only); Mem0 removed its self-hosted
   MCP server (2026-07-29) and its v2 dropped graph memory and the update/delete step from the open
   source; LangMem has shipped nothing in 2026 [R]. Betting the product on one of them is the
   one thing we must not do. This argues for the pluggable *seam*, not for any one backend.
2. **None of them keeps people apart safely.** Mem0's server accepts any `user_id` with any key;
   Graphiti's servers have no authentication; Hindsight defaults to open on 0.0.0.0 with one shared key;
   MemOS has auth off by default [R]. Per-person scoping has to be Eugene's whatever the backend.
3. **Deletion is not real in several.** Mem0 writes the deleted text into its history table; Graphiti can
   keep a deleted fact inside an entity summary (#1837); LangMem reported success while leaving 0 of 47
   secrets deleted (#202) [R].
4. **They fail on the models our people run.** Every system that extracts facts or graphs needs reliable
   JSON or tool calls. Recorded failures with local models: Mem0 invalid JSON with Llama 3.x; Graphiti
   with gemma3:12b lost the date on 25% of edges and took 626 s to ingest one sentence for one user;
   Hindsight with qwen3.5:9b invents dates and owners; LangMem cannot run on LM Studio at all [R].
   Workbench's notes work with no model at all, and its suggestions pass Troy's bar on Gemma 4 E4B.
5. **Their benchmarks do not decide it.** LoCoMo's answer key is 6.4% wrong (ceiling 93.6%) and its judge
   accepts 63% of vague wrong answers; the Zep and Mem0 numbers dispute each other; on Qwen3-8B the
   memory frameworks score within a few points of plain RAG, while harness differences move results
   by about 15 points [R].

Why not keep it as it is: Troy's critiques hold. Against CoALA's four types, Workbench has no episodic
memory (past chats cannot be searched), procedural memory is 240-character instruction notes, the
1,000-token ceiling is low for 128k windows, and 240 characters and 300 notes are toy limits. The
October reason for refusing automatic writes was also weaker than we stated it (section 11).

What the evidence says to build (section 5): keep raw evidence and treat extracted facts as an index;
words-plus-meaning retrieval by default; time and supersession recorded at write time; inject little and
only what is relevant; memory is untrusted data; graphs are optional and need a 30B-class model.

Where I push back on the framing: **CoALA does not prescribe vector or graph storage** (section 2), and the
evidence does not support a graph store as the default for local models (section 5.3). The four types are
a good checklist; the storage choice should follow the evidence, not the taxonomy.

---

## 2. What CoALA says, and what it does not

Sumers, Yao, Narasimhan and Griffiths, "Cognitive Architectures for Language Agents" (arXiv 2309.02427,
TMLR 2024) [R]:

| Memory | CoALA's definition | Actions on it |
|---|---|---|
| Working | "Active and readily available information as symbolic variables for the current decision cycle"; the hub between the model, long-term memory and the world | Reasoning updates it |
| Episodic | "Experience from earlier decision cycles" | Retrieval reads, learning writes |
| Semantic | "An agent's knowledge about the world and itself" | Retrieval reads, learning writes |
| Procedural | Implicit (the model's weights) and explicit (the agent's code and prompts) | Writing it is flagged as riskier than writing episodic or semantic memory |

- Retrieval "could be implemented in various ways, e.g., rule-based, sparse, or dense". The full text has
  **no occurrence of "vector" or "graph"** [R]. The idea of choosing vector or Graph RAG per memory type is
  a later gloss (Mem0's blog argues entity stores suit semantic facts; that is its opinion) [R].
- Who uses the taxonomy: LangChain's 2024 memory post and LangMem (semantic, episodic, procedural);
  MIRIX's six managers (core, episodic, semantic, procedural, resource, vault) are the closest fit; Mem0
  calls procedural memory "early-stage" [R]. No 2025-26 system claims to implement CoALA as a
  specification, and a 2026 governance survey criticises it for treating modules as isolated black boxes
  [R].
- What we take from it [I]: the four types as the checklist for gaps (section 3), and its warning that
  procedural writes are the riskiest, which shapes who may write what (section 7.5).

---

## 3. Workbench today against the four types

Read from the code on 2026-10-19 (paths under `workbench/src/eugene_plexus_workbench/`) [R].

| Type | What exists | Gap |
|---|---|---|
| Working | One system message: the chat's instructions plus a frozen block of notes, at most `min(1,000, 8% of window)` tokens (`memory.py:58-66`, `:110`); relevance by words and meaning when a local search model runs (`memory_relevance.py:142`); document passages in the latest user turn, re-searched each turn (`context.py:987-1046`) | Low ceiling for large windows; all notes frozen into the system prompt, which is the riskier pattern for injection (5.6) |
| Episodic | **None.** No index over messages; the only chat search is by chat name (`Sidebar.tsx:110`). Suggestions read chats only to propose notes | Recalling past chats, the most-cited gap |
| Semantic | Notes: one line of at most 240 characters (`memory.py:52`, a DB CHECK), at most 300 per person (`memoryMaxNotes`, range 1-2,000), kinds fact, preference, instruction, project, event. Documents: per-person index, 100,000 passages, words plus meaning plus a served sorter, folders | Toy note size and count; no supersession history (only `replaces` on a suggestion); no link from a note to the document it came from |
| Procedural | `instruction` notes (240 characters) and a chat's own instructions | No long notes: briefs, procedures, style guides |

Also per person only: no shared or team memory (deferred as MRC25). The Anthropic `memory` tool (MR9a) keeps
nothing in Eugene; the calling client runs it on its own files [R].

What Workbench already does better than the field, measured against the complaints in 4.4: the frozen
block keeps the prompt cache; relevance is gated; the drawer shows exactly what was sent; outside models
get no notes without a say; the owner cannot read notes; deletion nulls the audit text; suggestions come
only from the person's own words and pass a measured harness.

The seams for a different backend exist: `memory_api.block_for` (`:757`) is the single read-side entry and
returns text; `Store` is documented as replaceable; `knowledge.search.Signal`, `Retriever` and `Sorter` take
new search methods; `knowledge/vectors.py` is "the one thing to swap"; `connections.Tools` already serves the
same functions over MCP [R].

---

## 4. The field

### 4.1 Hosted assistants

| | Who writes | Recall | Limits | Scope and control |
|---|---|---|---|---|
| ChatGPT | The model during the chat, plus a background "dreaming" job over chat history (rebuilt 2026-06-04) | Model-judged, not every answer; past chats referenced | None published; Plus/Pro "twice the capacity" (2026-06) | Per account; project-only memory (2026-08-14); editable summary, sources under replies; deleting a chat leaves its memory; temporary chats |
| Claude | The model during the chat, by topic (on by default for Free/Pro/Max; Team/Enterprise off until enabled) | Past-chat search is a separate tool with citations | None stated | Per person and per project ("use account memory" switch); owners cannot read; export; incognito; deleting a chat leaves its memory |
| Claude API | Your app runs the `memory_20250818` tool on its files; Managed Agents edit attached stores | The model views `/memories` then reads files | Stores: 100 kB a memory, 10,000 a store | "Dreams" (preview) rewrites a store from up to 100 transcripts into a new store; versions kept 30 days |
| Gemini | Past chats from Activity (on by default); saved info by the person or "remember that" | Undisclosed | None stated | Per account; remove past-chat memory only by deleting chats |

All [R]. Sources V1-V12 in the hosted report (section 12).

### 4.2 Local chat apps

| App | Who writes | Recall | Limits |
|---|---|---|---|
| Open WebUI 0.12 | The model through native tools (on by default since 0.10); optional review every 10 turns, off | "User" memories injected every turn; "context" memories by vector top 8, threshold 0 | 2,000 characters each, cut mid-entry |
| LibreChat 0.8.8 | Optional memory agent (an extra call beside each reply), off by default | All entries injected, "not semantic" | `charLimit` 10,000 |
| AnythingLLM 1.18 | Background job every 3 hours after 20 idle minutes, off by default, needs tool calling | All global plus top 5 of the workspace | 5 global, 20 a workspace |
| Jan 0.8 | The agent writes Markdown notes, each write approved (nightly only) | Files at start, BM25 excerpts | Not stated |
| Cherry Studio 2 | Removed its automatic "Global Memory"; agents keep Markdown files | Files at start | Not stated |
| Msty Studio | The person, or a model draft the person reviews | Title and summary always; full text by tool | Not stated |
| LM Studio | Nothing built in; a plugin writes `Label: value` files | Injected | Not stated |

All [R]. **Open WebUI's "27B floor" is not a requirement**: its docs list Qwen 3.6 27B and a 30B model as the
smallest "verified working at the time of writing", say only very small models struggle, and call the list
unmaintained [R]. Its observed small-model failure is "nothing written" (no native tool mode) and
over-saving ("I had eggs for breakfast", Qwen 3.6 35B) [R].

### 4.3 Open-source memory systems

| System | Licence, telemetry | Needs | Writes with | Retrieval | Per-person safety | Local 4-35B | Maturity | For Eugene |
|---|---|---|---|---|---|---|---|---|
| **Hindsight** | MIT; no product telemetry | Postgres+pgvector (embedded `pg0`), pip or Docker, all OSes | JSON-schema extraction about once per 3,000 characters, background consolidation | Meaning + words + graph + time, RRF, cross-encoder, token budget; 0 model calls to recall | Banks are isolated; default open on 0.0.0.0 with one key | Vendor names gpt-oss-20b; qwen3.5:9b invents dates (#4457); a 16K window breaks "reflect" (#4561) | 51.6k stars, v1.0.0 2026-10-13 | **Best backend candidate**, for 20B+ models |
| Graphiti | Apache-2.0; telemetry on | FalkorDB or Neo4j | Serial model calls per episode (nodes, edges, dedupe, contradiction) | Cosine + BM25 + graph walk, rerankers | `group_id`, **no auth** | gemma3:12b lost `valid_at` on 25% of edges; 626 s for one sentence (one user) | 32k stars, v0.31.1 | Conditional: 27B+, behind our auth |
| Cognee | Apache-2.0, but the production Postgres graph and GLiNER extractor are licensed; telemetry on, includes a hash of the LLM key | Embedded SQLite, LanceDB, Kuzu; heavy Python deps | One extraction call per chunk; a keyless mode (GLiNER + fastembed) | 17 search types | Per-user databases and ACLs, the best tenancy found | Qwen3.6-35B 10-30x slower until thinking is off | 32.5k stars; 96 releases in 2026 (churn) | Conditional |
| Mem0 (open source) | Apache-2.0; telemetry on | Qdrant + SQLite, or pgvector server | One JSON-mode call per add; **v2 is add-only** (no update or delete step) | Meaning + BM25 + entity boost | `user_id` not bound to the key; deletes leave text in history | Invalid JSON with Llama 3.x; truncated JSON drops all facts silently | 67.5k stars; self-hosted MCP removed | No |
| Letta | Apache-2.0 | Now a Node agent harness | The agent edits its files | Files plus keyword search | Per agent | Stalls with Ollama | Memory server archived | No |
| Zep | Proprietary cloud | — | — | — | — | — | Community edition dead since 2025-04 | No |
| LangMem | MIT | Library only | Needs `tool_choice` | Store search | None | Fails on LM Studio | No release in 2026 | No |
| Basic Memory | **AGPL-3.0** + CLA; events on | Markdown files + SQLite | The agent writes notes; no server model | Words + meaning, graph walk over links | Projects; no auth locally | No model risk | 4.3k stars | Possible (separate process only) |
| MemPalace | MIT | Chroma | Verbatim storage, no model | Meaning | One bearer token | No model risk | 59.6k stars; retracted two benchmark claims | Possible |
| MemOS | Apache-2.0; telemetry on | Neo4j + Qdrant | Extraction + scheduler | Graph + vector | Auth off by default | Bad JSON silently stored as empty | 11.9k stars | Weak |
| Supermemory | Server is a closed binary | — | — | — | — | — | — | No |
| Memori | Extraction runs on its hosted service | — | — | — | — | — | — | No |
| Memobase, MIRIX, A-MEM, MemoryOS | Apache or MIT | Various | Various | Various | Thin | No evidence | No 2026 release, or dormant | No |
| OpenViking | AGPL-3.0 | VLM + embedder | — | Virtual filesystem | Accounts, ACLs | Ollama listed | 40.3k stars | Watch |
| TencentDB Agent Memory | MIT | Node 22 | Proxy in front of the model | BM25 + vector, RRF | — | — | 29.6k stars | Watch: it sits where our gateway sits |
| Agentic GraphRAG | Apache-2.0; Neo4j Community (GPLv3) | Neo4j, stdio MCP only | GLiNER locally, model optional | Neo4j words + vector, graph navigation | `project_id` fixed in env, no auth | Local embedder only | 7 stars, created 2026-08-20 | **Take the idea, not the system** (7.3) |

All [R] except the last column [I]. The only verbs every MCP memory server shares are **write** and
**search**; delete is not universal (Zep's has none); writes are asynchronous everywhere [R].

### 4.4 What people complain about

Injected memory breaks prompt caching (Open WebUI, Jan, LibreChat issues); no relevance gate and unbounded
growth (209 memories, about 102,000 characters, all injected); junk memories and a wish to approve before
saving; memory silently not written without native tool mode; memory-agent cost (a 2.1M-token request);
Cherry Studio deleted its automatic memory for complexity and weak quality; hosted memory outlives chat
deletion [R].

---

## 5. What the evidence says

### 5.1 Raw evidence beats compression

"Preserving usable evidence matters more than making memory more compact or more structured"; no single
architecture dominates (arXiv 2606.24775) [R]. HaluMem: extraction recall under 60% for every system but
one, update omission above 50% for most (2511.03506) [R]. **Extracted facts are an index into what was
said, not a replacement for it.** [I]

### 5.2 Long context does not replace memory on small models

LongMemEval full context against the relevant sessions only: GPT-4o 0.870 to 0.606, Llama 3.1 8B 0.710 to
0.454, Phi-3.5-mini 0.660 to 0.342 (2410.10813) [R]. Hindsight's 20B open model: 39% full context, 83.6%
with memory (2512.12818) [R, Vendor]. Chroma's Context Rot: a focused prompt of about 300 tokens beat the
full 113k-token prompt for every model tested [R]. RULER at 4k against 32k: Gemma-3-4B 90.9 to 62.3,
Qwen3-8B 94.8 to 91.0 (2605.07731, not peer reviewed) [R]. The norm is 1,000 to 7,000 tokens of memory per
query (LightMem about 1k, Mem0 about 7k) [R].

### 5.3 Graphs help some questions at a high price

RAG against GraphRAG (2502.11371): temporal questions 30.7 against 49.9-53.3 for graphs; single-hop
questions RAG wins, 64.8 against 61-63; building the graph took 41 to 57 times longer (135 s against
5,560-7,702 s) [R]. GraphRAG-Bench: HippoRAG2 +10.5 on complex reasoning, graphs tie or lose on fact
retrieval [R]. Zep's +38% on temporal questions was measured against full context, never against vector
RAG; in one vendor table plain RAG top-20 scored 80.05% against Zep's 71.2% [R, Vendor]. Graph quality sets
the ceiling: about 65% of answer entities reach the extracted graph [R]. Small models: Graphiti warns that
smaller models produce wrong schemas; LightRAG calls Qwen3-30B-A3B "a reasonable minimum"; a 7-8B GraphRAG
study took 88 to 211 minutes to index 8 documents and Phi-4-mini failed on JSON (2605.20815) [R]. No
controlled study shows graph extraction working below about 30B [R].

### 5.4 Updates need time and supersession recorded at write time

MERIT (2609.05441): fact stores and summaries scored 0.70-1.00 on updated facts, embedding retrieval
0.30-0.95, hybrid worse than the fact store alone; agents ignored a correctly retrieved latest value 45%
of the time [R]. BEAM contradiction resolution about 0.03 (2510.27246); no method above 28% on multi-hop
conflict resolution in MemoryAgentBench (2507.05257) [R]. Mem0 v2's add-only store keeps "I work at A"
and "I work at B" side by side (#4956) [R].

### 5.5 Relevance gating works, and costs useful recall if overdone

PersistBench (2602.01146, ICML 2026): with 4-16 memories in the system prompt, median failure 53% on
cross-domain leakage and 97.8% on sycophancy; swapping in other people's memories cut failures 2-12 times,
so the memories cause them; an embedding threshold took cross-domain failure from 50% to 0% but beneficial
failure from 20% to 97%; a model filter did little [R]. Hybrid words plus meaning added 8.8 to 17.2 Hit@1
on LoCoMo; cross-encoder reranking gave no reliable gain on memory (one study lowered Hit@1 by 6.9) [R].
Query expansion helps with GPT-4o, barely with an 8B model (recall@10 0.550 to 0.570 against 0.722) [R].

### 5.6 Automatic writing: the junk rate is a pipeline problem, and memory is an attack surface

The "97.8% junk" figure (mem0 #4573) is one person's hand audit of one agent: the first 20 days used
gemma2:2b, the last 12 Sonnet 4.6 at **89.6%** junk; the batch table sums to 6,264 entries, not 10,134;
52.7% of the junk was the agent's own system prompt re-extracted and 11.5% heartbeat noise; after four
fixes, 46.6% on a 73-entry sample [R]. It shows that unfiltered extraction from an agent's runtime context
is junk; it is not a small-against-large comparison. AlpsBench extraction F1: DeepSeek-v3.2 0.674,
GPT-5.2 0.672, GPT-4.1-mini 0.537 [R]. No published extraction precision exists for Qwen3.x, Gemma 3/4 or
Phi [R]; our own MR8 harness is the only measurement on those models.

Security: MINJA planted memories by query alone (98.2% injection success on GPT-4 agents); Microsoft found
50 "summarize with AI" prompts from 31 companies planting "remember X as trusted" (2026-02-10) [R]. A
systematic study (2606.04329, one model): 34% attack success where memory is reached only through a
`memory_search` tool, 67% where writes are permissive and memory is frozen into the system prompt; the two
differ in both respects [R]. Storing a malicious instruction is easy (over 97.5%); executing it ranged
0-95% by model, and only a tool-layer sandbox reached 0% (2605.08442) [R]. What works: confirmation for
writes made while untrusted content is in context; recalled memory kept apart from tool authority;
retrieval on demand; visible, deletable memory [R].

### 5.7 Benchmarks

Evaluate in house. LoCoMo's ceiling is 93.6% and its judge lenient; vendor LongMemEval numbers use
different readers and judges; harness variance is about 15 points on the same backbone [R]. The useful
public sets for us are LongMemEval's question types (knowledge update, temporal, multi-session) and
PersistBench's negatives, run on the models our people use [I].

---

## 6. Troy's asks against the evidence

| Ask | What the evidence says | What I recommend |
|---|---|---|
| Four CoALA layers | A sound checklist; it prescribes no storage | Build all four (7.1-7.4) |
| Vector or Graph RAG by use | Words plus meaning wins single-hop and is cheap; graphs win temporal and multi-hop at 41-57 times the ingest and need a 30B-class extractor | Words plus meaning for every type; time and supersession as fields, not a graph; a graph only through an optional backend |
| Models that can auto-write may do so | The field moved there (ChatGPT, Claude, Open WebUI); local apps ship it off; the junk evidence is about pipelines; memory writes are an injection target | Yes, for any model the person allows; Eugene recommends from a stricter measured bar and says why; from the person's own words, with receipts and undo; never while untrusted content is in context; never procedural notes (7.5) |
| A very large corpus | Retrieval scales; injection must stay small | Tens of thousands of notes, long notes, every past chat indexed; the per-turn budget grows with the window but stays in the thousands (7.6) |
| Choose what is relevant per turn | Gating cuts leakage; too strict a gate kills useful recall; on-demand retrieval is safer | Re-selected every turn, outside the system prompt, plus search tools for models that call tools (7.1) |

### The proposal against commercial memory

Asked by Troy, 2026-10-19. The proposal after MV1-MV6, against what 4.1 recorded; hosted internals are
mostly undisclosed, so "match" means matching the published behaviour, not measured quality [I].

| | Proposed Eugene | ChatGPT | Claude | Where we stand |
|---|---|---|---|---|
| Who writes | The person; any model the person allows, in the turn and in the background, under the write policy | The model in the turn, plus background "dreaming" | The model in the turn | Match on mechanism |
| Write and read quality | The person's model's; measured and shown per model | Frontier models | Frontier models | Behind on small local models (5.2, 5.6); equal when a cloud model is used through Eugene |
| Consolidation | Supersession at write; deterministic tidy; model consolidation later | Background rewrite, rebuilt 2026-06 | Dreams (API, preview) | **Behind** |
| Past chats | Indexed; search by screen, tool and MCP; not injected by default | Referenced automatically, no stated limit | A search tool with citations | Match Claude; less automatic than ChatGPT, by choice |
| Scale | 20,000 notes with 20,000-character bodies, every chat, 100,000 document passages and folders a person | Undisclosed ("twice the capacity") | Undisclosed; API stores 10,000 × 100 kB | Match or ahead on paper; bounded by local embedding speed |
| Relevance each turn | Words and meaning, re-chosen each turn; tools on demand | Model-judged | Undisclosed | Match |
| Project scope | **None: Workbench has no projects** | Project-only memory switch | Per-project memory with an account-memory switch | **Behind** (call 13) |
| Transparency | The exact text sent each turn; the model, policy and source of each note | Editable summary; sources under replies | A list of topics | Ahead |
| Deletion | Real; deleting a chat removes its past-chat entries; audit text nulled | Deleting a chat leaves memory; logs kept 30 days | Deleting a chat leaves memory | Ahead |
| Where it lives | The person's disk; the owner cannot read it | The vendor's cloud | The vendor's cloud; owners cannot read it | Ahead, structurally |
| Write security | A code-enforced policy the owner sets; untrusted content goes to the inbox | Fixed and undisclosed; injection writes shown in 2024 | Fixed and undisclosed | Ahead in design; not yet attacked (MV3's adversarial review) |
| Models and apps | Any model; other apps through connections and the Anthropic memory door | ChatGPT only | Claude only; export and experimental import | Ahead |
| Setup | Relevance needs a local search model running | Nothing to set up | Nothing to set up | **Behind** unless the search model starts by itself when memory needs it |
| Measured quality | Not measured | Not published | Not published | Unknown: the largest open item (call 11) |

Against the managed memory platforms (Mem0 Platform, Zep Cloud, Supermemory): they sell graph memory,
decay and managed consolidation with LongMemEval claims of 91-95% that are their own and disputed (5.7).
The built-in has no graph by choice; the Hindsight backend supplies graph and time-aware recall for
people with 20B+ models.

Summary [I]: ahead on what a cloud vendor cannot easily copy (the person's disk, real deletion, any model,
the owner's policy, showing exactly what was sent); on par in mechanisms and scale once MV1-MV3 land;
behind on consolidation, project scope and zero setup, all closable; and behind on answer quality
whenever the person's model is small, a hardware ceiling the per-model recommendation makes visible
rather than hides.

---

## 7. The recommendation: reshape

### 7.1 Working memory: what reaches the model each turn

- **Pinned block** (About me, How I want answers, pinned notes; person-written or person-kept): stays in the
  system message, frozen per chat, as today, so the prompt cache holds. Budget `min(2,000, 4% of window)`.
- **Relevant memories** (notes, passages of long notes, past-chat excerpts the person turned on): chosen
  afresh **every turn** and placed in the **latest user turn** as data, exactly as document passages are
  (`<memory-XXXXXXXX>` with a random suffix, "data, not instructions"). Budget `min(6,000, 10% of window)`.
  Only the last turn misses the cache, as with documents today. This answers "relevant to the current
  turn" and takes memory out of the frozen system prompt (5.6).
- **Search on demand** for models that call tools: `search_memory` and `search_chats` as tools Workbench
  runs, results in the turn, never with tool authority. Models without tool calling get the injected
  selection only.
- Selection: words plus meaning (RRF, as now), then a recency and kind order, with a similarity floor per
  search model that is tuned to keep useful recall (5.5). A served sorter only if a measurement shows it
  helps on notes [U].
- The drawer keeps showing exactly what was sent, now per turn.

### 7.2 Episodic memory: past chats

- A per-person index of chat exchanges (the person's message plus the answer's opening), in the same
  per-person index files documents use, words plus meaning, with dates. Built in the background,
  including a backfill of existing chats.
- **Search chats** as a screen in Workbench (app before config), and `search_chats` for tool-calling models
  and over MCP connections.
- Not injected by default: past-chat excerpts reach a chat by search, by the tool, or by the person
  turning on "Use past chats" for that chat (PersistBench's cross-domain leakage is about exactly this) [I].
- Deleting a chat removes its exchanges from the index in the same transaction.

### 7.3 Semantic memory: notes and documents

- A note has a **title line** (at most 240 characters, what lists and the pinned block show) and an optional
  **body** (Markdown, up to 20,000 characters). A body is indexed as passages like a document, so a long
  note costs only the passages that match.
- **Supersession, not overwrite**: `valid_from`, `superseded_at`, `superseded_by`. A changed fact keeps its
  history; only the current version is sent; the page shows "replaced on {date}" with the old text. This is
  Graphiti's bi-temporal idea without a graph (5.4).
- **Provenance**: a note records where it came from (an exchange, a connection, or document passages with
  the document's version). When a cited document changes or is removed, its notes ask "Still true?" with
  the reason. This is Agentic GraphRAG's stale-decision check, which is implemented there
  (`agrag/cypher/documents.py`, run in the same transaction as the document commit) [R]. It matters for
  notes kept from answers that cited documents, and for long notes the person links to a document.
- **Documents stay as they are** (MR2-MR7): they are already the large semantic corpus.
- No graph store in the built-in. Multi-hop questions get iterative tool search on capable models; temporal
  questions get dates and supersession.

### 7.4 Procedural memory: how you work

- A `procedure` kind (briefs, procedures, style guides, checklists) with a long body, either pinned to a
  project or matched by relevance.
- Written by the person, or suggested to the inbox; **never kept automatically** (CoALA's warning; an
  instruction is what an injection wants to plant).
- Skills in the Anthropic sense (a folder with instructions and files) are a later question, not this
  slice.

### 7.5 Who writes memory

**The person decides which models may write memory; Eugene recommends and says why** (Troy,
2026-10-19: "a user must be allowed to make that determination themselves. They might be testing a new
type of 27B model that is supposed to be better at making summaries.").

- **Per model, three settings:** Off, Suggest (to the inbox), Keep automatically. Any model can be set to
  any of them, measured or not.
- **Eugene's recommendation sits beside the choice, with its reason:**
  - "Recommended: measured on {date}, false memories 1.2%, recall 64%";
  - "Not recommended: measured, kept 7% of what it should";
  - "Not measured yet. [Measure this model]".
  - Keep automatically is recommended only for models that pass a stricter bar (call 3). Suggest is
    recommended for those passing today's bar (Gemma 4 E4B and 12B, Qwen3.6-35B-A3B, Qwen3.8-27B).
- **Measure this model:** runs the harness's labelled set against the chosen model from the Memory
  screen (no terminal), and shows the result next to the recommendation. This is the path for the person
  testing a new 27B.
- **Undo at scale:** every note records the model that kept it. "Recently learned" shows each note with its
  model and an Undo, and one step removes everything one model kept since a date.
- **The install owner** can still turn learning off for everyone (as with "never" for outside models).

| Writer | Today | Reshaped |
|---|---|---|
| The person | Typed, "Remember that ...", Remember this | Same, plus long notes and procedures |
| A model set to Suggest | Suggestions to the inbox (passing models by default) | Same, for any model the person sets |
| A model set to Keep automatically | — | **Keeps** facts, preferences, projects and events itself, with a "Remembered ... Undo" receipt; in-turn `remember` tool for tool-calling models plus the existing background pass |
| Any model, while untrusted content is in the context the note is drawn from | Pasted material excluded | Decided by the write policy below (Standard: to the inbox) |
| Instruction and procedure kinds | Person or inbox | Decided by the write policy below (Standard: person or inbox only) |

**The memory write policy** (Troy, 2026-10-19: the guards are a security posture, Standard by default,
with stricter and looser policies, and "someone who knows what they're doing must have final control",
at least the root owner, because Eugene may be a testbed). The guards protect against what is in the
chat, not against how good the model is, so they are a policy and not part of the per-model choice.

| Guard | Strict | Standard (default) | Open |
|---|---|---|---|
| Source: the person's own words only (quote support, pasted material excluded) | Yes | Yes | No: any text in the chat, answers and tool results included |
| Text shaped like a secret refused (key formats, high-entropy tokens, "password is", card numbers, IBANs, private keys) | Yes | Yes | Yes |
| Sensitive categories refused (MR8's check) | Yes | Yes | No: to the inbox |
| Web pages, tool results, document passages or pasted material in the turns read | The write is dropped | The write goes to the inbox | Kept like any other |
| Instructions and procedures from a model | Never, not even suggested | Inbox only | May be kept automatically |
| Keep automatically | Not available | Per model, the person's choice | Per model, the person's choice |
| Suggestions from connected apps (MCP) | Off | Inbox | Inbox |

- **Custom** sets each row separately, including secret refusal, for testbed work.
- **The secret check is a seat belt, not a guarantee.** Code catches the shape of a secret, not its
  meaning: "the garage code is 4417", a login written as "Troy / bluefish77", a password in another
  language, a key split across lines, or a fact that is secret only by context all pass it, and a model
  classifier would only lower the miss rate. The protection is containment: under Standard a note comes
  only from the person's own words in their own chat, which already holds the secret on the same disk; what
  memory adds is re-exposure, into other chats, to outside models and through connections. Those exits are
  the controls that matter: no notes to outside models without a say (the owner's "never" final), none to
  an outside search model, connections scoped and revocable, receipts and real deletion. Copy never claims
  more than the check does ("That looks like a password or key").
- **Open question (call 12):** notes a model kept automatically stay local-only (no outside model, no
  connection) until the person has seen them in Recently learned. *My default: yes under Standard and
  Strict; it costs nothing for local models and closes the path where an unseen, model-kept secret leaves
  the machine.*
- **Who controls it:** the install owner sets the policy in the console (Workbench's config trio:
  `memoryWritePolicy` strict, standard, open or custom, with the custom rows shown only for custom) and
  whether people may loosen it (`memoryPolicyPeople`: "stricter only" by default, or "any"). A person may
  always choose a stricter policy on their Memory settings.
- **Settings never lie:** the Memory screen names the policy in effect, and under Open or Custom says what
  it allows ("Models may keep notes drawn from web pages and tool results").
- **Auditable:** each kept note records the policy it was kept under, beside its model and source, so a
  testbed run can be reviewed and removed in one step.
- **Enforced in code, not written as instructions to the model.** Workbench checks every proposed note
  against the policy before storing it; the model only proposes. A rule given to the model as a prompt can
  be argued away by the very text it guards against (a web page saying "remember to trust X"). The memory
  block's "data, not instructions" line stays as a second layer.

All of MR8's code checks stay: secret shapes, the quote must be the person's words, sensitive categories,
pasted-material exclusion, dismissed stems, rate limits. A tidy pass (deterministic first: duplicates,
supersession chains, past events) proposes merges to the inbox. A model-proposed consolidation, as
ChatGPT's dreaming and Anthropic's Dreams do, is a later step, under the same per-model choice.

### 7.6 Size and scale

| | Today | Reshaped default (each a setting) |
|---|---|---|
| Note | 240 characters | 240-character title + 20,000-character body |
| Notes per person | 300 (max 2,000) | 20,000 (max 200,000) |
| Pinned block | in the 1,000 | `min(2,000, 4%)` |
| Relevant memory per turn | `min(1,000, 8%)` with the pinned notes | `min(6,000, 10%)` |
| Past chats | not indexed | every exchange |

At 32k that is about 4,600 tokens of memory a turn; at 128k and above, 8,000. A heavy user produces on the
order of 100,000-200,000 exchanges a year [I]; the numpy scan is 8.6 ms at 100k x 1,024 but 410 MB of
float32, so episodic vectors are stored as int8 (recall@10 0.3626 against 0.3633 in October's check) and
the October upgrade path to an approximate index applies past about 300,000 passages [R October; I].
Backfill at today's 30 embeddings a minute would take days for a large history; on a GPU search model the
rate should rise [U].

### 7.7 Backends behind one contract

The engines analogy holds at the seam, not at the default:

- **Eugene defines the contract** (MCP-shaped, the same verbs Workbench's `/mcp` serves to other apps):
  `remember`, `recall` (query and token budget), `search_chats`, `get`, `list`, `supersede`, `forget`,
  `export`, `purge`, plus capability flags (supersession, time, graph, episodic, verified delete).
- **The built-in store is the default backend**, as llama.cpp is for engines: no model needed to keep or
  recall, works on any hardware.
- **Eugene's layer sits above every backend and is never delegated**: the person binding (the namespace is
  derived from the sign-in, never from the model or the client), what was sent, the outside-model guard,
  secret refusal and the taint rule on writes, the keep-or-inbox policy, deletion with a check that
  `recall` no longer returns it, export, rate limits, and the Memory screens.
- **First outside backend: Hindsight**, labelled experimental and offered for 20B+ models with reliable
  tool calls. The agent installs and supervises it as a catalogue app in its own account (C1), bound to
  loopback, telemetry off, one bank per person, its model, embedder and reranker all pointed at the gateway
  (the C4 lesson: every address it holds is ours).
- **Bring your own**: a person may connect their own MCP memory server; the screen says Eugene cannot check
  what it keeps or deletes.
- **Rejected for now: a memory door at the gateway** (TencentDB's proxy shape). The gateway sees keys, not
  people; injecting into requests from apps we do not own hides what was sent and breaks their cache.
  Revisit if Open WebUI users need the same memory as Workbench.
- **Where it lives**: Workbench stays the person's memory home; other apps reach it through connections
  (MR9b, working with Claude Code and Codex). A separate component only when a second app must write
  without MCP. The repo name `memory` is retired and taken.

---

## 8. Kept and thrown away

| Kept | Thrown away or replaced |
|---|---|
| Per-person scoping and the 404 rule; the owner cannot read notes | One line of 240 characters as the whole note |
| "What was sent", per chat, now per turn | 300 notes by default |
| The outside-model guard; local-only search models for notes | The 1,000-token ceiling |
| Real deletion and audit-text nulling; export | Every note frozen into the system prompt |
| Secret refusal, quote support, sensitive categories, pasted-material exclusion, as the Standard write policy | "Suggest" as the ceiling for every model |
| The MR8 harness and its passing models, now as the recommendation | The measured list as a gate the person cannot override |
| | The October claim that auto-extraction is 97.8% junk on any model |
| Relevance by words and meaning; the frozen pinned block for the cache | The Memory page with settings above the notes |
| "Still true?" and event expiry | The 60-day timer as the only revisit trigger (provenance adds a real cause) |
| Documents, folders, sorter (MR2-MR7) | |
| MCP connections and the Anthropic door (MR9) | |

---

## 9. Calls for Troy

Each has my recommended default. **Taken by Troy, 2026-10-19: all fourteen at their defaults** (call 4
as he decided it; call 14 with his master tag list).

1. **Verdict.** Reshape: keep the built-in store as the default and floor, rebuild on the four types, add
   the contract and optional backends. *Default: yes.*
2. **Graph.** No graph store in the built-in; time and supersession as fields; graphs only through an
   optional backend for 27B+ models. *Default: yes.*
3. **The bar for recommending Keep automatically** (a recommendation, not a gate; call 4): no secret,
   injection or sensitive note; false memories at most 2% of kept (today 5%); noise and unreadable at most
   2% each; recall at least 60%; plus a new supersession check. *Default: this bar, measured on the
   starter models before MV3 ships.*
4. **Who chooses. Decided by Troy, 2026-10-19:** the person, per model (Off, Suggest, Keep automatically),
   including models Eugene has not measured. Eugene shows its recommendation and the reason, offers
   Measure this model, and records which model kept each note (7.5). The content guards are a write
   policy, Strict, Standard (default), Open or Custom, with the install owner in final control and people
   free to choose stricter (7.5; Troy, same day). Open question inside it: whether Open keeps secret
   refusal (my default: yes; Custom can turn it off).
5. **Budgets.** Pinned `min(2,000, 4%)`, relevant `min(6,000, 10%)`, both settings with the person's
   override. *Default: these.*
6. **Sizes.** Title 240 characters, body 20,000, 20,000 notes a person (setting to 200,000). *Default:
   these.*
7. **Past chats.** Indexed and searchable by screen, tool and MCP; not injected unless the person turns it
   on for a chat. *Default: yes.*
8. **Where relevant memory goes.** The latest user turn, re-chosen each turn; the pinned block stays frozen
   in the system message. *Default: yes.*
9. **Backends.** Define the contract with the reshape; Hindsight as the first experimental backend after
   the built-in work; bring-your-own MCP servers allowed with the warning. *Default: yes, Hindsight last
   in the order.*
10. **Home.** Memory stays in Workbench, reached by other apps through connections; no new component and
    no gateway memory door now. *Default: yes.*
11. **Evaluation.** Extend `scripts/m-memory-measurement.py` with LongMemEval-style questions (knowledge
    update, time, several sessions) and PersistBench-style negatives, run on the passing models before
    automatic keeping ships, with one cloud model through the same memory as the reference, so the gap
    to commercial quality is a number. *Default: yes.*
12. **Unseen model-kept notes stay local.** A note a model kept automatically is not sent to an outside
    model or a connection until the person has seen it (7.5). *Default: yes under Standard and Strict.*
13. **Projects.** Workbench has no projects, and ChatGPT and Claude both scope memory to one. Add chat
    projects whose notes, procedures and documents can be kept to the project, with an "also use my
    general memory" switch. *Default: yes, as MV7, designed with the Memory app (MV4).*
14. **Tags** (Troy asked, 2026-10-19; neither this research nor October's design considered them). Not for
    speed: words and meaning search take milliseconds at a person's scale, so a tag pre-filter saves
    nothing until millions of items [I]. For weight and organisation, the evidence is good: LongMemEval's
    keys enriched with extracted facts gave +9.4% recall and +5.4% accuracy [R], and documents already
    weight heading paths twice in the word index. The risk is tag sprawl ("work", "job", "career") when a
    model invents them. Design:
    - Notes carry tags; `kind` stays as the fixed set beside them.
    - Tags are a separate word-index column weighted above the text (as heading paths are), and are
      embedded with the note ("Tags: ...").
    - `#tag` in a search filters; a tag word in a question boosts.
    - **A tag list per person is the master vocabulary** (Troy, 2026-10-19: it must be exportable,
      importable and editable in a standard, editable format):
      - Each entry is a tag and an optional description. The description is what the model reads, so
        "clients: work for paying customers" separates it from "work".
      - Edited on the Memory screen: add, describe, rename (every note follows), merge (rename onto an
        existing tag), delete (notes keep their text and lose the tag; the dialog names how many).
      - **Export** as CSV with the columns `tag,description` (any spreadsheet or text editor). **Import**
        takes the same CSV, or a `.txt` with one tag per line. Import adds new tags and updates
        descriptions; "Replace my list" is a separate choice that names the tags it would remove and from
        how many notes before it does.
      - The memory export (Markdown and JSON) carries the tags on each note and the list itself.
      - Matching ignores case; a tag is at most 40 characters, no `#` or commas.
    - A model proposes tags only from that list (an enum with the descriptions in the extraction schema,
      which small models follow reliably); a tag not on the list goes to the inbox with "Add to my tags".
      A very long list may be too much for a small model's schema; the cut-off is measured in MV1 [U].
    - The Memory screen filters by tag. Tags replace the "folders" the Notes reorganisation planned, since a
      note can carry several.

    *Default: yes, the index in MV1 and the screen in MV4.*

---

## 10. Slices after the calls

| Slice | What | Needs |
|---|---|---|
| MV1 | Notes with bodies and the procedure kind; caps raised; supersession fields; budgets scaled; relevant memory moved to the latest turn; search tools for tool-calling models | Calls 2, 5, 6, 8 |
| MV2 | Past chats: the exchange index with backfill, Search chats, `search_chats` (tool and MCP), deletion with the chat | Call 7 |
| MV3 | Learning: the evaluation extension, the stricter bar measured, the per-model choice with Eugene's recommendation and reason, Measure this model from the screen, the model recorded on each note with bulk removal, Keep automatically with receipts, the in-turn `remember` tool, the write policy (Strict, Standard, Open, Custom) with the owner's control | Calls 3, 11 (4 decided) |
| MV4 | Memory as an app: the screen reorganised so notes, inbox and past chats lead and settings move to Settings (`feedback_app_before_config`) | MV1-MV3 shapes |
| MV5 | The contract as a Workbench interface, the built-in behind it, Hindsight from the catalogue, bring-your-own MCP | Calls 9, 10 |
| MV6 | Provenance and "Still true?" from changed documents; the deterministic tidy pass | MV1 |
| MV7 | Chat projects with project-scoped memory, procedures and documents | Call 13, MV4 |

MV1 and MV3 change what models receive and who writes memory: MV3 is high risk under the testing policy
(automatic writes, injection surface) and gets an adversarial review and a real-environment run.

---

## 11. Corrections to the October design

1. `workbench-memory-and-documents.md` section 1, 6(b), and section 4.8 cite "97.8% of 10,134
   auto-extracted entries were junk with a 2B local model and with Claude Sonnet 4.6". The Sonnet batch was
   89.6%; the total does not add up; the cause was mostly the pipeline (5.6). The conclusion "measure
   before anything is automatic" stands; "refuse automatic writes" does not follow from it.
2. "Open WebUI's own floor is about 27B" (same places): it is the smallest model its docs list as tested,
   not a floor (4.2).
3. Section 4.1 names a `VectorIndex` interface; none exists. The swap point is `knowledge/vectors.py`
   (`Matrix`, `scan`, `MatrixCache`) [R].
4. The MCP `suggest_note` was designed with a `why` argument; it was built without one, and without the
   `event` kind [R].
5. `memory_learn.py:23-25` still says "PASSED is empty"; the list has four models [R]. A docstring, fixed
   with MV3.

---

## 12. Sources

The five researchers' reports were returned to this session and not saved; their sources, all opened on
2026-10-19:

- **CoALA and benchmarks:** arXiv 2309.02427 (CoALA), 2410.10813 (LongMemEval), 2402.17753 (LoCoMo),
  2507.05257 (MemoryAgentBench), 2510.27246 (BEAM), 2511.03506 (HaluMem), 2605.12493 (LongMemEval-V2),
  2609.05441 (MERIT), 2606.24775, 2602.01146 (PersistBench), 2603.26680 (AlpsBench), 2605.11325, 2502.11371
  (RAG against GraphRAG), 2506.05690 (GraphRAG-Bench), 2502.14802 (HippoRAG 2), 2605.20815, 2601.23014,
  2601.02553, 2502.05167 (NoLiMa), 2404.06654 (RULER), 2605.07731, 2512.12818 (Hindsight), 2501.13956 (Zep),
  2504.19413 (Mem0), 2304.03442 (Generative Agents), 2503.03704 (MINJA), 2601.05504, 2407.12784 (AgentPoison),
  2606.04329, 2605.08442, 2606.30306, 2602.11988; trychroma.com/research/context-rot;
  github.com/dial481/locomo-audit; letta.com/blog/benchmarking-ai-agent-memory;
  mastra.ai/research/observational-memory; getzep.com/blog/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory;
  anthropic.com/news/contextual-retrieval; embracethered.com;
  microsoft.com/en-us/security/blog/2026/02/10/ai-recommendation-poisoning/.
- **Hosted:** help.openai.com articles 8590148 and 6825453; openai.com/index/chatgpt-memory-dreaming;
  support.claude.com articles 11817273 and 12123587; platform.claude.com docs for the memory tool, Managed
  Agents memory and Dreams; support.google.com/gemini answers 16598469, 16598625, 16413516, 13594961.
- **Local apps:** docs.openwebui.com (memory, tools, MCP), open-webui `backend/open_webui/utils/memory.py`
  and docs commit a5b676c2; librechat.ai memory docs; docs.anythingllm.com/features/memories; janhq/jan
  `docs/src/pages/docs/agent/memory.mdx`; CherryHQ/cherry-studio memory overview; docs.msty.ai persona
  studio; lmstudio.ai memory plugin README.
- **Memory systems:** github.com/mem0ai/mem0 (README, `mem0/memory/main.py`, issues 3391, 3944, 4573, 4956,
  5428, PR 6530), docs.mem0.ai; github.com/letta-ai/letta and letta-code, docs.letta.com;
  github.com/getzep/zep and graphiti (issues 1516, 1746, 1837, 1909, 1911, 1922), help.getzep.com;
  github.com/langchain-ai/langmem (issues 43, 176, 196, 202); github.com/topoteretes/cognee (issues 1812,
  2840, 3647), docs.cognee.ai; github.com/vectorize-io/hindsight (issues 3865, 4457, 4561, 5531, 5544,
  5564); supermemory, MemOS (issue 2456), memobase, MIRIX, memU, basic-memory, Memori, A-MEM, MemoryOS,
  MemPalace (HISTORY.md, issue 875), OpenViking, TencentDB-Agent-Memory, ontogr/agentic-graphrag
  (`agrag/cypher/documents.py`, `agrag/ingestion/_cutover.py`, `agrag/memory/decisions.py`); GitHub REST API
  and PyPI JSON for stars and releases.
- **This repo:** `docs/design/workbench-memory-and-documents.md`; Workbench code as cited in section 3.
