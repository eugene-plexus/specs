# Embeddings — acceptance run

**2026-09-12. 14 checks, zero failures, second attempt.**
`scripts/embeddings-acceptance.sh`. Design
[`agent-clients-and-tool-calling.md`](../design/agent-clients-and-tool-calling.md),
call #2.

Contracts `91c9360`; inference-driver `8981fa9`, gateway `c0f1ede`, `ui`
for the playground picker. `agent`, `control` and `library` not
re-pinned — `common.yaml` was untouched.

## What the call was

**Serve what we already launch** (Troy, 2026-09-12), chosen from four
options over "defer it" and over a wider scope including reranking.

The argument that decided it was coherence rather than demand. The
library already detects dedicated embedding models — `is_embedding()` in
both the GGUF reader (a pooling type) and the safetensors reader (an
encoder architecture), populating `chat`/`embedding` on every scanned
model. So this install would discover, download and launch one, after
which it appeared on `GET /v1/models` looking like any other model and
failed every request sent to it. We were letting people acquire a thing
we could not serve.

## What ran

Five processes on this Windows box — agent on **8179**, its declared
control root, gateway and library — plus up to four inference-drivers
against a live Ollama serving **`nomic-embed-text`** (768 dimensions)
and a **chat** model.

## The three findings, all measured before anything was built

### 1. The capability belongs to the running backend, not the model

```
POST /v1/embeddings  {model: <a chat model>}
-> "This server does not support embeddings. Start it with `--embeddings`"
```

That is Ollama refusing to embed **the very model it is serving**,
because the runner was started for chat. And there is no read-only
signal anywhere:

- `llama-server` b9846's `/props` exposes **no** pooling or embedding
  field. Checked the whole payload: `bos_token`, `build_info`,
  `chat_template`, `default_generation_settings`, `modalities`,
  `total_slots`, … and nothing about embeddings.
- Ollama's OpenAI-compatible surface says nothing; `/api/ps` reports a
  context length but not a task.

So detection is a **functional probe**, cached for the engine's
lifetime. That lifetime is right: the capability cannot change without
the backend restarting, and the engine is rebuilt on every config
change. A **transport** failure is deliberately not cached — a backend
that happened to be restarting would otherwise be recorded as
permanently incapable.

**The probe is nearly free in the negative case**, which is what makes
it viable: llama.cpp rejects a non-pooling model in **45 ms**, before
any compute (`Pooling type 'none' is not OAI compatible`), and Ollama
answers immediately.

Checks 1 and 2 assert both directions live: the embedding driver reports
`embeddings=true`, the chat driver reports `false`.

### 2. The surfaces are not always disjoint, so `surfaces` is a list

Ollama's are: a chat runner will not embed, and `nomic-embed-text`
answers `"nomic-embed-text" does not support chat`. But **`llama-server`
given `--embedding` still serves chat perfectly well** — measured, a
completion came back normally from a server in embedding mode.

An enum would have been wrong. A list was not a guess.

### 3. `encoding_format: base64` is what the OpenAI SDKs ask for

Ignoring it would break the most common client while every hand-rolled
`curl` kept working. It is handled at the gateway rather than passed
down, because backends differ on implementing it — so a caller sees the
same behaviour whichever backend answered.

The encoding was verified **byte-for-byte against a real backend's own
base64 output** rather than inferred from OpenAI's documentation:
little-endian `float32`, then base64, re-encoded locally and compared as
strings. Check 6 re-verifies it end to end through our own stack — the
base64 answer decodes to exactly the floats the float request returned.

## THE RULE THIS ENDPOINT TURNS ON

> **Failover does not cross models here.**

Everywhere else in the gateway a slot is an ordered list of targets and
a failure cascades to the next. For chat that degrades gracefully — a
different model answers and the caller can tell. For embeddings it is
silent corruption: vectors from two models occupy different spaces, so a
fallback writes noise into the caller's vector store with a 200 and
nothing to mark the seam. Different dimensions would at least raise; the
**same** dimension poisons quietly, and unlike a bad chat answer the
damage outlives the request in a database.

Same family as M10's "failover is possible until the first token and
impossible after it": both give up a retry to avoid returning a wrong
answer that looks like a right one.

**Check 10 proves it live.** A dead driver in tier 1 with a healthy
embedder for a *different* model in tier 2:

```
POST /v1/embeddings {model: "ghost-embed"}
-> HTTP 503, no vectors
```

A 200 there would not have been a near-miss — it would have been
vectors from the wrong space, indistinguishable from correct ones.

**Check 11 is the half that makes it a rule rather than a refusal to
route**: two replicas of the *same* model balance and serve normally.

It is enforced **structurally, not by a check at the end**:
`pick_embedding` builds a client over a single tier containing only
backends serving the requested model id, so there is no second tier for
a cascade to walk into and the rule cannot be lost by someone later
editing the cascade logic.

## What the second attempt fixed, and it was the harness

The first run was **11 of 12**, and the failure was mine rather than the
code's: check 11 slept 18 seconds against a `routingRefreshSeconds` of
**15** and lost the race. The driver was up and had probed successfully
— the log shows `backend at http://127.0.0.1:11434 serves embeddings` —
and the `/v1/models` read landed just before the refresh that would have
included it.

Diagnosed from the log rather than patched by lengthening the sleep,
because "a wait satisfied by something other than its subject" is this
project's most-recorded harness failure. Replaced with a bounded wait on
the actual condition, which fails just as loudly if the thing never
arrives and does not fail when it is merely slow. The same fix was
applied to check 10's slot visibility, where a premature read would have
produced a **404** that passed "it did not serve vectors" for entirely
the wrong reason.

## Found while building, and removed rather than shipped

A hand-written check for "a non-empty list of strings" was added to the
gateway handler, then measured to be **unreachable**: the contract types
`input` as string-or-array-of-string with `minItems: 1`, so both a token
array and an empty batch are rejected as **422** by schema validation
before the handler runs. It was deleted rather than kept with a test
asserting it fires — which would have been this project's most familiar
mistake one layer in. The tests assert the 422 and say why.

Two codegen wrinkles are recorded in comments because neither is
guessable: `oneOf: [string, array]` generates a `RootModel` that needs
`.root` rather than iteration, and `encoding_format`'s generated default
is the literal string `"float"` rather than the enum member, so an unset
field has no `.value`.

## What this run does not cover

- **llama.cpp and vLLM as embedding backends.** Both were used to
  establish the *detection* facts, but every vector in this run came
  from Ollama. A pooling-enabled llama.cpp serving real embeddings has
  not been driven end to end.
- **`dimensions`.** Contracted as pass-through with no emulation;
  Ollama ignores it and nothing asserted what happens when a backend
  honours it.
- **A vector store consuming the output.** The corruption this design
  prevents is described, and the refusal is proved; nobody has actually
  indexed a corpus through this endpoint and searched it.
