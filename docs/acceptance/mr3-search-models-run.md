# MR3: embedding and reranking models the agent starts by itself

**2026-10-11. 62 checks, 0 failures. 43 of 43 breaks caught (the one that escaped the first pass was a missing test, now written).**
`scripts/mr3-search-models-acceptance.py`; sabotage `scripts/mr3-sabotage.py`.
MR3 of the memory-and-documents plan (MR0 is
[`mr0-embeddings-honest-run.md`](mr0-embeddings-honest-run.md)): a search model
(an embedder) or a result sorter (a reranker) is started the way llama-server
has to be told to start it, from the file's own header, with no flag typed
anywhere, and everything the agent then says about it is true of what it
started. Contracts
`79188dfc917ec6fd0a5c50865ad6040e29ab2f4d` and
`668cad9c512b021e758c6e46292827d61ac2cd06`; agent, library, ui and
inference-driver commits are in the table at the end. Nothing is pushed.

## What changed

An embedding GGUF started by the agent answered neither `/v1/embeddings`
(501) nor chat (500) and was listed as a chat model, because the llama.cpp
adapter never passed `--embeddings`, `--pooling` or `--reranking`. It does now,
and a profile or a runtime can say otherwise.

- **Contract** (specs `79188df`, `668cad9`): `RuntimeMode` (`auto`, `chat`,
  `embedding`, `reranking`), `RuntimeSpec.mode` and `Runtime.mode`;
  `RuntimeCapabilities.embeddings` says how the runtime was started and a new
  `reranking` does the same; a running search model's `idleUnloadSeconds` and
  `startOnDemand` are reported absent. `ModelCapabilities.rerank`, `ProfileMode`
  and `ModelProfileSpec.mode` / `ModelProfile.mode` in the library's contract.
  The gateway's text no longer says nothing in Eugene starts an embedder. The
  enums carry no schema `default:` (see the calls below).
- **Agent** (`engines/run_mode.py`, `gguf_context.py`, `engines/llama_cpp.py`,
  `runtimes.py`, `routes/runtimes.py`, `run_worker.py`, `companions.py`):
  `auto` reads three keys of the GGUF header (`<arch>.pooling_type`,
  `<arch>.attention.causal`, `<arch>.classifier.output_labels`): pooling type 4
  or classifier labels is a reranker, any other pooling type or non-causal
  attention an embedder, anything else chat, a header that will not read chat.
  An embedder gets `--embeddings` (and `--pooling mean|last` only when the header
  names none), a reranker `--reranking`, and both `--ctx-size 4096 --parallel 4
  --batch-size 2048 --ubatch-size 2048` unless the profile, the engine's own
  environment variable or `extraArgs` says otherwise; `extraArgs` stay last.
  **A chat model's command line is what it was**: `test_chat_argv_is_unchanged`
  pins nine representative chat profiles, captured from the code before this
  change (`0eb1d8f`), each as no mode, `auto` and `chat`, over a missing file
  and a real chat header (54 command lines). What a running runtime says it is comes off the
  command line it was launched with, because `/props` carries no such field; a
  running search model is never unloaded for being idle, started on demand or
  offered for eviction; admission and the reservation measure it at its 4,096
  window and not the model's own 32,768; Run does not size it to the card; a
  search mode is refused for an engine that cannot start one; a run that meets
  a runtime declared under another mode is refused as a changed flag is.
  **Tests**: 196 new test cases in four files (`test_run_mode` 56, `test_search_models` 56, `test_gguf_run_facts` 28, `test_chat_argv_is_unchanged` 56) and 4 more in `test_run_worker`; the full suite is 2399 passed, 19 skipped (host-specific); ruff, `ruff format --check`, mypy, `mypy --platform linux` and `check-vendored` clean.
- **Library** (`formats/gguf.py`, `scanner.py`, `preflight.py`, `store.py`):
  `is_rerank` from the same keys, `capabilities.rerank`; a reranker is not also
  an embedding model; the profile keeps its `mode`, replaced whole. 26 new tests in `test_search_models.py`; the full suite is 801 passed, 25 skipped; static checks clean.
- **Console** (`ui`): "Runs as: search model (found in the file)" under Run and
  in the profile editor, with Auto, Chat, Search and Sort results; a Search
  models shelf on Library's empty pane and Discover's, three models, each opening
  its Hugging Face repo with `?repo=`. Plain words, enforced by the copy gate.
  83 new tests; vitest 157 files and 1961 tests passed; typecheck, lint and prettier clean; the `dist` branch is not rebuilt.
- **Inference driver** (outside the brief's repos, for the two defects below):
  a loading model's 503 is "not now" and not "this backend does not embed", and a
  backend is asked whether it reranks before it is ever asked to embed. `test_embeddings.py` goes from 11 tests to 25; the full suite is 1083 passed, 5 skipped; static checks clean.

## What building found

The research (`rag/options.md` 4.2, `rag/internals.md`) was right about the
fault and wrong about some of what surrounds it. Each of these changed what was
built.

1. **The agent did not already read the header.** The design had the adapter
   resolve `auto` "from the GGUF header it already reads (`_read_capabilities`)".
   `_read_capabilities` asks the running engine's `/props`; the only header
   reader in the agent returned the trained context. `gguf_context.run_facts` is
   new, and duplicates the library's rule by the polyrepo rule (`is_embedding`,
   `is_rerank`): the console predicts with one and the agent decides with the
   other, and tests on both sides pin the same cases.
2. **The design's own flags cannot take its own acceptance input.**
   `--ctx-size 4096 --parallel 4` gives each request a quarter of the window
   (4 slots do not share a pool when `--parallel` is named), so "a 1,651-token
   input working" is a 400. Measured, llama-server b11552, Qwen3-Embedding-0.6B
   with the agent's command line, CPU:

   | input | as the agent starts it | with `--kv-unified` added |
   |---|---|---|
   | 1,601 tokens | 400 `exceed_context_size`, "exceeds the available context size (1024 tokens)" | 200 |
   | 3,901 tokens | 400, the same limit | 200 |
   | four of 901 at once | 200, 200, 200, 200 | 200, 200, 200, 200 |

   The flags are the design's and stay; the refusal is clean (the gateway passes
   the limit through as a 400, check W1) and a profile's own `contextSize` fixes it
   (checks W2 to W4: 8,192 gives 2,048 a request, and 1,601 tokens embed). Adding
   `--kv-unified` to the four defaults would make 1,600 tokens work as the design
   expected, at no cost the measurement shows. **Troy's call**; it is one flag, the
   words in the contract and the console that say "1,024 tokens a request", and
   this script's W1.
3. **A reranking llama-server dies when it is asked to embed, and the driver
   asked it every poll.** The gateway listed the reranker as chat (its driver finds
   zeros or nulls in `/v1/embeddings`), which the contract text says is so until
   the rerank door of MR6. What the research did not know is that the driver's
   embeddings probe reaches the engine: `POST /v1/embeddings` to
   `llama-server --reranking` answers with numbers it never computed and
   sometimes kills it (`0xC0000005`, on the first request it is sent). Measured
   with the agent's reranker command line, one request after ready:

   | build | died |
   |---|---|
   | b10948 (the installed engine) | 0 of 30 |
   | b11429 (v0.6.0) | 3 of 30 |
   | b11552 (nightly) | 1 of 30 |

   On b11552 the same request killed it in 2 to 12 of 40 starts for each of six
   flag sets (`--reranking` alone, and with `--ctx-size 4096`, with `--parallel 4`,
   with the two batch sizes, with `--parallel 1`, with `--kv-unified`), so the flags
   are not the cause. The
   probe is repeated at every poll until it has an answer and a reranker's never
   was one, so a reranker the driver followed died within minutes: it was found
   by this acceptance, whose reranker runtime crashed in 2 of 8 runs. The driver
   now asks `POST /v1/rerank` first (llama-server refuses it at once, 501, when
   not started with `--reranking`; 150 reranks in a row on a reranker, none
   failed) and a reranker is never asked to embed. Check S5 reads the driver's own
   request log: one rerank, no embeddings.
4. **The driver also recorded a loading model's 503 as "does not embed", for its
   life.** The agent starts a runtime's driver beside the engine, so the driver's
   first look often lands while the model loads (llama-server answers 503
   "Loading model"), and `probe_embeddings` treated any HTTP error as a definite
   no and kept it. In the acceptance's first full run the runtime declared with
   a larger `contextSize` lost that race (the others won it): it was listed as chat
   and refused embeddings ("serves chat and not embeddings") for as long as its
   driver lived. The log line: `[driver: embedder-wide-driver] backend at ...
   does not serve embeddings (HTTP 503)`. A 503 (and 408, 425, 429, 502, 504) is
   now "not now" and is asked again.
5. **A driver's answer outlives the mode that gave it.** The driver keeps what it
   learned, and a profile's `mode` can now change what the same file is. The agent
   restarts a runtime's companion driver when an edit changes what the runtime
   starts as (and not otherwise), so it asks again. Checks F1 to F4 edit one runtime
   from embedder to chat and back: each time the gateway lists it as what it now is
   within four seconds, and chat is routed to it.
6. **A causal embedder still chats.** Qwen3-Embedding-0.6B with `--embeddings`
   answers chat with text that means nothing, where an encoder (nomic) refuses with
   a 500. The disjoint answers MR0 recorded are an encoder's, so there is no
   refusal to lean on for the model the design makes the default: the header (or a
   person) decides, and checks O2 and F3 start that file as chat on purpose.
7. **The header cannot name every reranker.** The gpustack
   `bge-reranker-v2-m3` conversion is a non-causal `bert` with a classifier head
   and neither key, so it reads as an embedder here and in the Library. The
   override is how a person says otherwise (Sort results); the tensor list would
   name it, and is not read.
8. **The radius was five consumers and not three** (below).

## The run

Real processes throughout, with one choice: the engine is a CPU build of
llama.cpp, because the live install holds the GPU.

- the real agent (its own `main()`, `--unattended`) on ports the OS chose,
  supervising the real Library over a folder of hard-linked GGUF files, the real
  gateway, and the real companion inference-driver the agent keeps for each runtime;
- real `llama-server` b11552 (`version: 0.6.0-dev (build 11552, commit
  23b0202a1)`, from `llama-b11552-bin-win-cpu-x64.zip`, whose SHA-256
  `c0074117...` is the digest GitHub lists for it), started by the agent with
  `POST /v1/runtimes`, its command line read back from `GET /v1/runtimes`;
- a client key minted by the agent, and the gateway called with it as an app is.

The models, each with the SHA-256 Hugging Face lists for that file:
`Qwen/Qwen3-Embedding-0.6B-GGUF` Q8_0 (`06507c7b...`, the default embedder),
`nomic-ai/nomic-embed-text-v1.5-GGUF` Q8_0 (`3e243421...`, the light one),
`ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF` (`22c9979c...`, the only reranker whose
scores are right) and `unsloth/Qwen3-0.6B-GGUF` Q4_K_M (`ac2d9771...`, a chat model on
the same stack as the control). Their full hashes are printed at the top of the run.

Isolation: every ambient `EUGENE_PLEXUS_*` variable is dropped (check 1), every port
is the OS's (check 62: none is in 8079-8190, where the live install is), the agent's
own `agent.yaml`, state, engines directory and logs are in a temporary directory, and
the live install's agent, engines directory and ports were not touched. The one thing
moved is where the agent starts handing out runtime and driver ports, which it starts
at 8090 and has no setting for: a two-line launcher sets it, then runs the agent's own
`main()`.

```
agent/.venv/Scripts/python.exe specs/scripts/mr3-search-models-acceptance.py \
    --llama-server <b11552>/llama-server.exe \
    --embedding-model nomic-embed-text-v1.5.Q8_0.gguf \
    --qwen3-embedding Qwen3-Embedding-0.6B-Q8_0.gguf \
    --chat-model Qwen3-0.6B-Q4_K_M.gguf \
    --reranker qwen3-reranker-0.6b-q8_0.gguf
```

**62 PASS, 0 FAIL, about three minutes.** The groups: L the Library's reading of each
file's header (4 to 7); A the agent's command lines (11 to 14); C what it reports
(15 to 18); I the idle control, where the same 20-second timeout is declared on a
chat model and on an embedder, the gateway unloads the chat model and the embedder,
sent nothing, is still on its own process three timeouts on (19 to 21); G through the
gateway (22 to 30); W a request's window (31 to 34); O the override (35 to 40); F a
runtime edited from embedder to chat and back (41 to 48); R the reranker (49 to 55);
S the agent's log, and the teardown (56 to 62). The output below is the run's, with
paths named by what they are and two response bodies cut.

```
INFO engine llama-server.exe: version: 0.6.0-dev (build 11552, commit 23b0202a1)
INFO model nomic-embed-text-v1.5.Q8_0.gguf (nomic): 146146432 bytes, sha256 3e24342164b3d94991ba9692fdc0dd08e3fd7362e0aacc396a9a5c54a544c3b7
INFO model Qwen3-Embedding-0.6B-Q8_0.gguf (qwen3-embedding): 639150592 bytes, sha256 06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439
INFO model Qwen3-0.6B-Q4_K_M.gguf (chat): 396705472 bytes, sha256 ac2d97712095a558e31573f62f466a3f9d93990898b0ec79d7c974c1780d524a
INFO model qwen3-reranker-0.6b-q8_0.gguf (reranker): 639153184 bytes, sha256 22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48
PASS 1. the agent is given only its own EUGENE_PLEXUS_* variables, none from the live install -- [EUGENE_PLEXUS_AGENT_BIND_HOST EUGENE_PLEXUS_AGENT_BIND_PORT EUGENE_PLEXUS_AGENT_CONFIG_FILE EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY EUGENE_PLEXUS_AGENT_ENGINE_ROOT]
PASS 2. the library and the gateway are up under the agent
PASS 3. the agent mints a client key, as an app is given one -- 201
PASS 4. the library says what nomic-embed-text-v1.5.Q8_0.gguf is, from its header: (chat, embedding, rerank) = (False, True, False) -- (False, True, False)
PASS 5. the library says what Qwen3-Embedding-0.6B-Q8_0.gguf is, from its header: (chat, embedding, rerank) = (False, True, False) -- (False, True, False)
PASS 6. the library says what Qwen3-0.6B-Q4_K_M.gguf is, from its header: (chat, embedding, rerank) = (True, False, False) -- (True, False, False)
PASS 7. the library says what qwen3-reranker-0.6b-q8_0.gguf is, from its header: (chat, embedding, rerank) = (False, False, True) -- (False, False, True)
PASS 8. the agent declares the embedder (no mode, an idle timeout of 20 s, as an old declaration might) -- HTTP 201
PASS 9. the agent declares a chat model on the same stack, with the same timeout and a curated flag -- HTTP 201
PASS 10. the embedder reaches ready, started by the agent
PASS 11. A1 the embedder's command line: the model, host, port and alias, its four defaults and --embeddings, and no --pooling (its header names one) -- llama-server.exe --model Qwen3-Embedding-0.6B-Q8_0.gguf --host 127.0.0.1 --port 63238 --alias embedder --ctx-size 4096 --parallel 4 --batch-size 2048 --ubatch-size 2048 --embeddings
PASS 12. A2 the lighter embedder (nomic, an encoder that names mean pooling) gets the same, and no --pooling either -- llama-server.exe --model nomic-embed-text-v1.5.Q8_0.gguf --host 127.0.0.1 --port 63242 --alias embedder-light --ctx-size 4096 --parallel 4 --batch-size 2048 --ubatch-size 2048 --embeddings
PASS 13. A3 the chat model started on the same stack gets exactly the command line a chat model always had: its own curated flag, and nothing about search -- llama-server.exe --model Qwen3-0.6B-Q4_K_M.gguf --host 127.0.0.1 --port 63240 --alias chat-control --ctx-size 2048
PASS 14. A4 and no flag of the search kind appears on it
PASS 15. C1 the embedder says it embeds and does not rerank (read off the command line it was started with: llama-server's /props says nothing of it) -- {'contextLength': 1024, 'parallelSlots': 4, 'contextPoolTokens': None, 'embeddings': True, 'reranking': False, 'vision': False, 'multimodal': False}
PASS 16. C2 its window is the one its argv gave it: 1,024 tokens a request, 4 requests -- {'contextLength': 1024, 'parallelSlots': 4, 'contextPoolTokens': None, 'embeddings': True, 'reranking': False, 'vision': False, 'multimodal': False}
PASS 17. C3 it reports no idle timeout and no start-on-demand, whatever was declared: that is what the gateway reads -- {'idleUnloadSeconds': None, 'startOnDemand': None}
PASS 18. C4 the chat model reports it does not embed, and keeps the idle timeout it declared -- {'capabilities': {'contextLength': 2048, 'parallelSlots': 4, 'contextPoolTokens': 2048, 'embeddings': False, 'reranking': False, 'vision': False, 'multimodal': False}, 'idle': 20}
INFO waiting for the gateway to unload the chat model (idle 20 s, swept every 2 s); nothing is sent to either runtime meanwhile
PASS 19. I1 the control: the gateway unloads the idle chat model (21 s after ready), so the machinery is live in this run -- {'status': 'stopped stopReason': 'idle'}
PASS 20. I2 the embedder, declared with the same timeout, is still ready 60 s on, three times the 20 s it would have gone at, having been sent nothing -- ready
PASS 21. I3 and nothing stopped it: no stop reason, its process is the one it started with -- {'pid': 53380, 'stopReason': None}
PASS 22. G1 GET /v1/models lists the embedder as embeddings and not chat -- [embeddings]
PASS 23. G2 and says what one request may hold: 1,024 tokens -- 1024
PASS 24. G3 the lighter embedder is listed as embeddings too -- [embeddings]
PASS 25. G4 a 16-input batch returns 16 vectors of the model's width (1024) in 0.4 s -- HTTP 200, 16 vectors, widths [1024]
PASS 26. G5 every vector is a unit vector (the engine normalises) -- norms 1.00000..1.00000
PASS 27. G6 they are in the order sent, and they mean something: the cat sentence is nearer its paraphrase than the tax one -- 0.939 against 0.253
PASS 28. G7 the same sentence alone gives the vector it gave in the batch
PASS 29. G8 the lighter embedder's batch: 16 unit vectors of 768 -- HTTP 200
PASS 30. G9 chat to an embedder is refused naming the door to use, not answered with nonsense -- 400 {"error":{"message":"The model 'embedder' serves embeddings and not chat. Send this request to /v1/embeddings instead. G
PASS 31. W1 an input longer than a request's 1,024-token window is refused, with the limit named and not as a server fault -- HTTP 400 {"error":{"message":"The backend rejected the request: openai_compat_http returned 400 for embeddings: {\"error\":{\"code\":400,\"message\":\"request (1601 tokens) exceeds the available context size (1024 tokens), try increasing it\",\"type\":\"exceed_context_size_error\",\"n_prompt_tokens\":1601,\"n_ctx\":1024}}","type":"invalid_request_error","param":null,"code":null}}
PASS 32. W2 the same file declared with the person's own contextSize (8192) -- HTTP 201
PASS 33. W3 curated flags win: --ctx-size 8192 once, the other three defaults kept -- llama-server.exe --model Qwen3-Embedding-0.6B-Q8_0.gguf --host 127.0.0.1 --port 63244 --alias embedder-wide --ctx-size 8192 --parallel 4 --batch-size 2048 --ubatch-size 2048 --embeddings
PASS 34. W4 and then a ~1,600-token input works (1601 tokens counted): one unit vector of 1024 -- HTTP 200
PASS 35. O1 the embedding file declared with mode chat -- HTTP 201
PASS 36. O2 mode chat beats the header: the command line is exactly a chat model's, nothing of the search kind -- llama-server.exe --model Qwen3-Embedding-0.6B-Q8_0.gguf --host 127.0.0.1 --port 63244 --alias as-chat
PASS 37. O3 and it reports what it runs as: mode chat, not an embedder -- {'mode': 'chat caps': {'contextLength': 32768, 'parallelSlots': 4, 'contextPoolTokens': 32768, 'embeddings': False, 'reranking': False, 'vision': False, 'multimodal': False}}
PASS 38. O4 the chat file declared with mode embedding -- HTTP 201
PASS 39. O5 its header names no pooling, so --pooling last is added after --embeddings: the one case it is -- llama-server.exe --model Qwen3-0.6B-Q4_K_M.gguf --host 127.0.0.1 --port 63244 --alias chat-as-embedder --ctx-size 4096 --parallel 4 --batch-size 2048 --ubatch-size 2048 --embeddings --pooling last
PASS 40. O6 and it embeds: 3 unit vectors, all of one width -- HTTP 200, widths [1024]
PASS 41. F1 the embedding file declared as an embedder -- HTTP 201
PASS 42. F2 the gateway lists it as embeddings -- [embeddings]
PASS 43. F3a it is edited to mode chat: accepted, and the engine restarts -- HTTP 200
PASS 44. F3b the gateway lists it as chat within 4 s of the edit, not as what it was -- [chat completion]
PASS 45. F3c and chat to it is routed to it, not refused as an embedder -- HTTP 200
PASS 46. F4a it is edited to mode embedding: accepted, and the engine restarts -- HTTP 200
PASS 47. F4b the gateway lists it as embeddings within 4 s of the edit, not as what it was -- [embeddings]
PASS 48. F4c and it embeds again: 2 unit vectors of 1024 -- HTTP 200
PASS 49. R1 the reranker declared with no mode -- HTTP 201
PASS 50. R2 its header names rank pooling and labels, so the agent adds --reranking and the defaults, and neither --embeddings nor --pooling -- llama-server.exe --model qwen3-reranker-0.6b-q8_0.gguf --host 127.0.0.1 --port 63244 --alias reranker --ctx-size 4096 --parallel 4 --batch-size 2048 --ubatch-size 2048 --reranking
PASS 51. R3 it reports that it reranks and not that it embeds, and has no idle timeout -- {'contextLength': 1024, 'parallelSlots': 4, 'contextPoolTokens': None, 'embeddings': False, 'reranking': True, 'vision': False, 'multimodal': False}
PASS 52. R4 the engine reranks: the relevant passage scores above the others -- {0: 0.9983708262443542, 2: 0.00018201240163762122, 1: 2.4978924557217397e-05}
PASS 53. R5 the reranker is never listed as an embedder, so no client indexes with it (it is listed as chat until the rerank door of MR6: recorded, not gated) -- [chat completion]
PASS 54. R6 and an embeddings request for it is refused, not answered with zeros -- 400 {"error":{"message":"The model 'reranker' serves chat, completion and not embeddings. Send this request to /v1/chat/comp
PASS 55. R7 and it is still up, on the process it started with, after 20 s of its driver polling it -- {'status': 'ready pid': 12432, 'lastError': None}
PASS 56. S1 the agent logged what each search model starts as, and why (settings never lie) -- [2026-10-11 06:57:56,674 INFO eugene_plexus_agent.engines.llama_cpp: runtime embedder starts as an embedding model: its header names pooling type 3 2026-10-11 06:57:57,080 INFO eugene_plexus_agent.engines.llama_cpp: runtime embedder-light starts as an embedding model: its header names pooling type 1 2026-10-11 06:59:00,933 INFO eugene_plexus_agent.engines.llama_cpp: runtime embedder-wide starts as an embedding model: its header names pooling type 3]
PASS 57. S2 and warned that the idle timeout declared on the embedder is not acted on
PASS 58. S3 and said nothing of the kind about the chat model
PASS 59. S4 and said, once for each edit that changed what the runtime starts as, that it restarted the driver -- 2 lines
PASS 60. S5 the reranker's driver asked it to rerank and never to embed (its own request log: llama-server --reranking answers an embeddings request with numbers it never computed, and has died answering it) -- 1 rerank requests, 0 embeddings requests
PASS 61. teardown by the agent leaves no owned port listening
PASS 62. none of the ports this run was given is one the live install uses (8079-8190) -- 11 ports, 63235-63245
62 PASS, 0 FAIL, 0 SKIP (work <work>)
INFO kept <work>
```

Two things in it are worth reading rather than counting:

- **A1 to A3, O2, O5, R2** are the command lines, byte for byte what each mode
  makes: the embedder gets the four defaults and `--embeddings` and no `--pooling`
  (its header names one); the chat model gets its own flag and nothing else; the chat
  file started as an embedder is the one that gets `--pooling last`.
- **I1 to I3** are a live control: the machinery that would have unloaded the
  embedder is shown to be running (it unloads the chat model 21 s after ready), and the
  embedder, which was declared with the same timeout, is untouched at 60 s.

## Sabotage

`scripts/mr3-sabotage.py`: 43 breaks, each restored from a copy (never a checkout:
this work was uncommitted) and the ten files compared with the copy byte for byte
afterwards; every gate green before and after. Ten gates: the agent's, the library's
and the driver's unit tests, `test_chat_argv_is_unchanged` on its own, and six slices
of the acceptance (`--skip` leaves out the phases a break cannot reach).

**First pass: 62 gate runs, 61 caught, 1 escaped. The escape was a missing test.**
A scanner that lists a reranker as chat when its header names it by classifier labels
alone (no pooling type, so it is not an embedding model either) passed every library
test, because each reranker fixture also carried the pooling type. The test is
written (`test_a_reranker_the_header_names_only_by_its_labels_is_not_listed_as_chat`,
and a labels-only case in the preflight test), the break re-run, and caught: **43 of 43
breaks caught.**

| Group (breaks) | What was broken | Red |
|---|---|---|
| argv per mode (13) | no `--embeddings` (the bug); a reranker started as an embedder, or with no `--reranking`; `--pooling` added when the header names one, or never added; the four defaults missing; a default beating the person's flag, the engine's variable or a typed argument; `extraArgs` no longer last; pooling 4, any other pooling type, or non-causal attention no longer read | unit tests for every one; acceptance for 7 (A1 and A2; R2 and R3; O5 and O6; W3 and W4) |
| auto against an explicit choice (6) | the header beating `chat`, `embedding` or `reranking`; the profile's mode dropped on its way to the runtime; a run adopting a runtime declared under another mode; a runtime with no mode told from one that says `auto` | unit tests; acceptance O2, O3 and O5, O6 for the first two |
| no idle unload for a search model (6) | an embedder keeping its declared idle timeout, start-on-demand or eviction; what a runtime was started as never read off its command line; capabilities never saying it embeds; a reranker reported as an embedder too | unit tests; acceptance C3 and I2 (the embedder, `idleUnloadSeconds: 20`, unloaded) and C1 and C4 |
| the Library's rerank from header bytes (7) | `is_rerank` never true; rank pooling read as 3; labels ignored; a reranker also listed as embedding; the scanner or preflight not saying `rerank`; a labels-only reranker listed as chat | library tests; acceptance check 7 (`(False, True, False)`, `(False, True, True)`, `(False, False, False)` for the three that reach it) |
| the chat-argv regression test (4) | a chat header with nothing to say resolving to an embedder; an unreadable header resolving to one; a chat model given the four defaults; every chat model given one flag more | `test_chat_argv_is_unchanged` alone, on a different case each time; acceptance A3 and A4 (and S3) for two |
| the driver and the companion (7) | a reranker asked to embed; a backend that cannot say yet whether it reranks asked to embed; a loading model's 503 recorded as "does not rerank" or "does not embed"; the refusal not kept; a runtime edited to start as something else keeping its driver, or every edit restarting it | driver and agent unit tests; acceptance S5 (zero rerank requests) and F3b, F3c (the gateway still listing it as embeddings 93 s after it became chat) |

An earlier attempt at this pass stopped at its baseline: the `acc-rerank` gate was red
because the reranker had died (killed by the driver's probe, finding 3). The script's
rule of opening with a baseline on every gate it will use is what kept an engine crash
from being counted as a catch, and the crash is how the defect was found.

## Radius, and the pins

- **Radius of the contract change**, by regenerating every consumer at the contract
  commit and at its parent and diffing (each consumer's own `scripts/codegen.py` and
  `.venv`, run on a local `git archive` of each commit, since the commits are not on
  GitHub; the route reproduces every committed `_generated` byte for byte at its own
  pin): agent `models.py` 73 lines; control `agent_models.py` 73 (generated and unused
  there); library `models.py` 35; gateway `library_models.py` 35 (unused there) and
  `models.py` 2 description lines; ui `agent.ts`, `library.ts` and `gateway.ts` 193
  lines in all (the gateway's is comment text); inference-driver, tool-driver,
  site-host and workbench 0. The design expected agent, library and ui: control's
  codegen names `agent.yaml` and the gateway's names `library.yaml`. Neither re-pins:
  pins are not level on purpose, and neither uses a new field.
  `run-operations.json`, vendored into agent, library and ui by
  `scripts/vendor-platform.py`, gained `rerank`, `ProfileMode` and the profile's `mode`
  (its own contract commit, `668cad9`: the library's
  `test_run_protocol_matches_the_vendored_contract` was the one failing test in its
  suite until it was regenerated).
- Redocly 2.30.4 lint of the seven documents: valid. 35 warnings (30
  `no-unused-components`, 3 `operation-2xx-response`, which MR0's record names too,
  and 2 `no-ambiguous-paths`), none in a component or an operation of this change.
- **The control root needs nothing, and nothing is deployed first.** It relays a
  node's runtime views and declarations as raw JSON (`nodes_client.py`,
  `applied.py`: `RuntimePlacementSpec.spec` is `additionalProperties: true`), so a
  `mode` or a `reranking` flag crosses it untouched. Checked in the code; no root was
  run against an agent with the new fields.
- **Pins and order.** Each consumer's `SPECS_REF` is the contract commit
  `79188df`, which is not on GitHub: regenerating from the archive of a just-pushed
  commit can 404 for a minute after the push. Push in this order: inference-driver,
  agent, library, ui (and rebuild its `dist` branch: not built here), then this repo,
  whose `release/manifest.json` pins agent, library and inference-driver (the ui pin
  is a `dist` commit and stays). This repo's CI runs its acceptance scripts against the
  pinned components, so the script goes out in the same push as the pins. The
  acceptance script is not wired into CI: it needs 1.9 GB of models and an engine.

## Calls the design did not cover

Listed for Troy to overrule. Only the first would touch a contract.

1. **The enums have no schema `default:`.** The design says "default `auto`".
   `datamodel-code-generator` gives the Python field the bare string `'auto'` as its
   default and pydantic warns on every serialisation of a model that carries it (a
   runtime is serialised on every poll). "Absent means `auto`" is in the text and the
   code, and a Library run writes `auto` into the runtimes it declares.
2. **What a runtime reports is what is in effect.** A running search model's
   `idleUnloadSeconds` and `startOnDemand` are absent in the agent's view whatever the
   declaration says (it keeps what was said, and the log says it is not acted on). The
   gateway reads those from the view, so it needed no change, and admission's
   `evictable` follows.
3. **What a runtime is comes off the command line it was launched with**, and the
   engine's environment (`LLAMA_ARG_EMBEDDINGS`, `LLAMA_ARG_RERANKING`), however the
   flag got there: `mode`, a profile, or `extraArgs`.
4. **`--pooling` rule.** Added only when the header names none, or names `none` (0,
   which `/v1/embeddings` refuses): `mean` for a model that is not causal, `last` for
   one that is, nothing for a header that will not read. A reranker gets
   `--reranking` and nothing about pooling (llama-server sets it).
5. **The four defaults go to a reranker too**, and yield to the profile's curated flag,
   to the engine's variable in the runtime's `env`, and to the same flag typed into
   `extraArgs` (argv beats the environment in llama.cpp, so a default on the command
   line would have beaten the person's variable).
6. **A reranker is not also an embedding model in the Library** (`embedding` and `chat`
   are false, `rerank` true), and the console calls it a result sorter, not a search
   model.
7. **A header that will not read is chat**, as it was. A search mode for an engine that
   cannot start one (vLLM, MLX, Strata) is a 400 and says so.
8. **A run that meets a runtime declared under another mode is refused** ("different
   mode; rename or edit it on Inference"), as a changed flag already was, and a mode
   nobody wrote is `auto`, so every runtime that exists replays unchanged.
9. **Admission, the reservation and Run's context suggestion treat a search model as
   what it will be**: measured at its 4,096-token window, and not sized to the card.
10. **The companion driver is restarted when an edit changes what a runtime starts
    as** (agent), and **the inference driver asks whether a backend reranks before it
    asks it to embed, and treats a loading model's 503 as "not now"** (driver). Both
    are outside the repos the brief named; each is its own commit and can be dropped
    or redone. Without them the reranker dies on its own and an embedder that loads
    slowly is listed as chat.
11. **The acceptance moves one thing in the agent**: `_RUNTIME_PORT_BASE`, set by a
    two-line launcher before the agent's own `main()` runs, because the agent starts
    handing out runtime and driver ports at 8090 and has no setting for it. Every
    port the run was given is checked against 8079-8190 (check 62).
12. **The shelf's three models and their sizes** are the design's; the repos, files and
    sizes were checked against Hugging Face's own SHA-256 (see The run).
13. **The UI says "Search" and "Sort results"**, not "embedding" and "reranking";
    the override's values are the contract's.

## Left alone, for Troy

- **`--kv-unified` or not** (finding 2). One flag, and the words that say 1,024.
- **A reranker is listed as chat and completion** until the rerank door (MR6): the
  gateway lists what its driver says, and the driver has no `rerank` surface yet. It
  is not asked to embed any more, and an embeddings request for it is a 400 (checks
  R5, R6). It could be hidden from `/v1/models` entirely with a driver change.
- **The design's stretch**: the driver mapping llama-server's HTTP 500 for an
  encoder's input longer than its physical batch to a 400 naming the limit. Not built,
  and not in the brief. With the defaults the per-request window (1,024) is reached
  first and that is a 400 already; the 500 needs a profile that raises `contextSize`
  past four batches.
- **Placement** (design 4.2, item 4; MRC28, his): GPU only when admission has room,
  else CPU, said on the runtime card. Not built, and not in the brief; every run here
  was CPU.
- **`probe_completion` has the same shape as the embeddings probe** (it caches a "no"
  from a `/props` that answered 503 while the model loaded). Not touched; not
  measured.
- **The library's `test_a_mixed_tree_end_to_end` is flaky and was before this change**
  (a scan from the fixture's start still running when the test posts its own: 409;
  `test_full_scan_is_accepted` carries the comment, "seen on CI, library eb6b553").
  It failed in one full run, passed alone one run in two, and passed in the last full
  run.
- **The crash is upstream's**: llama.cpp b11429 and b11552 (Windows, CPU build) die
  answering `/v1/embeddings` on a reranking server. Troy writes upstream reports
  himself; the numbers above are the evidence.

## Commits (local, not pushed)

| Repo | Commit | What |
|---|---|---|
| specs | `79188dfc917ec6fd0a5c50865ad6040e29ab2f4d` | the contract: `agent.yaml`, `library.yaml`, `gateway.yaml` (text only), two dated corrections in the design docs |
| specs | `668cad9c512b021e758c6e46292827d61ac2cd06` | `openapi/run-operations.json`, regenerated from the library's router |
| inference-driver | `18ff1f565418f2a58fe8e9415aa3f5c2635fa187` | the rerank probe and "not now" (2 files) |
| agent | `a13749de9702b613d2d986784b74959e4a5ad012` | 19 files, 6 of them new |
| library | `581d87db7cbf70291d397b727a3c9856f06ae7c3` | 11 files |
| ui | `fdd8ab8b67607de1b707a1fb13c12f0199529ed5` | 29 files; the `dist` branch is not rebuilt |
| specs | the commit that adds this record | `scripts/mr3-search-models-acceptance.py`, `scripts/mr3-sabotage.py`, this file |
| specs | the pin commit after it | `release/manifest.json` (agent, library, inference-driver) and what `scripts/release-inputs.py` regenerates from it |
