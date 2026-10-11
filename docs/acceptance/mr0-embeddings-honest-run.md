# MR0: the embeddings door says what it ignores

**2026-10-11. 13 checks, 0 failures. 17 of 17 sabotage runs caught.**
`scripts/mr0-embeddings-honest-acceptance.py`; sabotage
`scripts/mr0-sabotage.py`. First slice of the memory-and-documents plan (MR0,
decision MRC23: say it is ignored now, pass it where a driver can later).
Gateway `201da3e6524295cc3bafd45c7e43f17094eb48e1`; the driver is unchanged
(`608cd77`). Follows [`embeddings-run.md`](embeddings-run.md).

## What changed

`POST /v1/embeddings` accepted `dimensions` and `user`, sent neither to any
backend (the driver's `EmbedRequest` has no field for either) and said
nothing, while `gateway.yaml` called `dimensions` "passed through" and `user`
"recorded", and the compatibility design said "Built, all 5 fields". A caller
who asked for 256 dimensions got the model's full width with a 200.

- **Gateway** (`routes/inference.py`): a served answer carries
  `x-eugene-plexus-ignored-settings` naming each of the two the request
  carried, as `dimensions, user` in that order whatever the request's order.
  Neither sent, or a JSON `null`, gets no header; a refusal or a failure names
  nothing. Nothing acts on them: no truncation (a truncated vector is a wrong
  answer that looks like a right one) and nothing forwarded. 8 new tests in
  `test_embeddings.py` (21 there now); `test_client_disconnect.py` calls the
  route by hand and now passes the `Response` FastAPI would inject. ruff,
  `ruff format --check` and `mypy src/` clean; **1295 passed, 1 skipped** (a
  POSIX file-mode test).
- **Contract, text only** (`gateway.yaml`): the operation and its 200,
  `EmbeddingRequest.dimensions` and `user`, and the `surfaces` text that said
  `llama-server --embedding` "still serves chat perfectly well".
- **Docs**: the compatibility row (`openai-inference-compatibility.md`, and
  `api-compatibility.md`, which said "Supported" with no caveat),
  `agent-clients-and-tool-calling.md` §5.1 and `embeddings-run.md`, each with a
  dated correction beside the claim it replaces.

### The stale claim, measured again

On this box, CPU only, `nomic-embed-text-v1.5` for the embedder and Qwen3-0.6B
for chat:

| llama-server | b10948 (installed) | b11552 (newest nightly) |
|---|---|---|
| started with `--embedding`: `/v1/chat/completions`, `/v1/completions` | 500 "...does not [support] logits computation" | the same |
| started without it: `/v1/embeddings` | 501 "Start it with `--embeddings`" | the same |
| the embedding GGUF started as the agent starts it (no flag): `/v1/embeddings`, chat | 501, 500 | the same |
| `--embedding`, `dimensions: 64` and `user` sent | 768 wide | 768 wide |

So the surfaces are disjoint both ways, as `embeddings-acceptance.sh`'s header
said on 2026-09-16. And the agent never starts an embedder: `build_argv` in
`engines/llama_cpp.py` passes the model, host, port, alias, the curated flags
and the profile's `extraArgs`, never `--embeddings`, `--pooling` or
`--reranking`, and `_read_capabilities` reports `embeddings` as unknown. An
embedding GGUF launched from the Library answers neither surface and is listed
as `chat` until `--embeddings` is typed into its profile's extra arguments.

## The run

Real processes: the gateway, the inference-driver (`openai_compat_custom`) and
`r4-stubs.py agent` in front of the component list. Two engines: a fixture
playing `llama-server --embedding` that **records every body it is sent**, and
a real `llama-server` b10948 on `nomic-embed-text-v1.5.Q8_0` (CPU only; the
live install holds the GPU). Ports chosen by the OS, every ambient
`EUGENE_PLEXUS_*` variable dropped (check 1), processes stopped by handle.

```
PASS   1. no ambient EUGENE_PLEXUS_* variable reaches a component
PASS   2. the gateway routes the fixture engine's model as an embedder
PASS   3. neither setting sent: a plain 200 with the model's own width and no header   -- width 8
PASS   4. dimensions: named as ignored, and the vector is not truncated to it   -- header ['dimensions'], asked for 4, got width 8
PASS   5. user: named as ignored   -- header ['user']
PASS   6. both: one header naming each, in the door's order whatever the request's   -- ['dimensions, user']
PASS   7. base64 with dimensions: named, and still the model's whole vector   -- 8 floats
PASS   8. null settings are not settings: no header
PASS   9. the engine was sent neither setting, on any request   -- 6 of 6 requests reached it, body keys ['input', 'model']
PASS  10. the gateway routes a real llama-server --embedding as an embedder
PASS  11. a real embedder, nothing asked: its own width, and no header   -- width 768
PASS  12. a real embedder asked for 256 dimensions answers its own width, and the header says so   -- ['dimensions, user'], got width 768
PASS  13. ignored means ignored: the vector is the one it gives when nothing is asked   -- L2 norm 1.000000
13 PASS, 0 FAIL
```

`embeddings-acceptance.sh` is not extended. It binds the default gateway,
library and control ports (8080, 8082, 8083), 8083 is the live install's control
here, and its teardown kills whatever listens on them, so it cannot run beside
the live install. The embedding model was on the box; the ports were the blocker.
A check added to a script that cannot run here could not be shown to fail.

## Sabotage

Eight breaks (each restored from a copy; every gate green again afterwards),
17 runs over three gates (`unit`, `acceptance`, `acceptance-real`): **17
caught, 0 escaped.** The header never sent; `user` or `dimensions` left out; the
two in the other order; a setting that was not sent named; an explicit null
named; the opposite fix, `dimensions` honoured by truncating; the header on a
refusal.

The two that matter, with the checks that went red (the rest stayed green):

| Break | Red |
|---|---|
| the header line deleted | 4, 5, 6, 7, 12 |
| `dimensions` honoured by truncating the vector | 4, 7, 12, 13 (the real 256-wide vector has L2 norm 0.5878: a wrong answer that looks like a right one) |

## Radius, and the pins

- **Radius of the contract change**, by regenerating every consumer whose
  codegen names `gateway.yaml` from specs HEAD with and without it: the
  gateway's `models.py` changes in 3 description lines (`user`, `dimensions`,
  `surfaces`); the ui's `gateway.ts` in comments only (11 out, 64 in). No other
  repo names `gateway.yaml`. Redocly 2.30.4 lint: valid, the same 3
  `operation-2xx-response` warnings as before (the videos doors);
  `openapi_spec_validator`: OK.
- **Pinned**: gateway `201da3e` in `release/manifest.json` and both installers
  (`scripts/release-inputs.py`, then `--check`; `release-artifacts-checks.py`
  agrees). Not pushed: the gateway goes first, then this repo's pin commit.
- **Not moved**: the gateway's own `SPECS_REF` stays `a502f60`, so its served
  OpenAPI document keeps the old `dimensions` text until it re-pins to the
  pushed specs commit and regenerates (3 lines). The ui follows at its next
  re-pin.

## Left alone, for Troy

- **Unknown fields on `/v1/embeddings` are accepted with a 200 and no header**
  (`input_type` and `bogus` both were), because the request model does not
  forbid extras. `api-compatibility.md` says unknown fields are rejected with a
  400. It matters for a hint such as `input_type`.
- **`user` is named here and not on the Responses door**, whose contract
  discards it as an opaque annotation, as the Anthropic door does `metadata`.
  The plan asked for it to be named here; the two doors now differ.
