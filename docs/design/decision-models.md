# Typed decisions: `/v1/systemone`, a supervised Kev, an optional hosted Jev

**Status: built and live-verified on WSL2 CPU, 2026-09-22 (roadmap B2);** evidence in [`../acceptance/decision-run.md`](../acceptance/decision-run.md), user recipe in [`../application-workflows.md`](../application-workflows.md#typed-decisions-with-kev-experimental-b2). The experimental-model
roadmap's second slice: one Eugene endpoint that takes a state and named
typed questions and returns structured decisions from a locally hosted
model, with hosted Jev as an optional, explicitly cloud-classified
provider. The calling application owns any subsequent action.

## Upstream facts, re-verified 2026-09-22

Everything below was read on 2026-09-22 from the named source, not
carried from the planning row. The pins:

**TypeSafe protocol** (docs.typesafe.ai/api): `POST /v1/systemone` takes
`state` (string | object | array), `model`, and `questions` — a map of
caller-chosen names to question objects. Three kinds:

| kind | request | answer |
|---|---|---|
| `noul` | `instructions`, optional `criteria` `{true, false}` | `noul`: probability of yes, 0–1 |
| `choice` | `instructions`, `criteria` map of ≤ 255 options → rubric/null | `choice`, `probabilities` summing to 1, `confidence` 0–1 |
| `score` | `instructions`, `criteria` array of 2–10 ordered levels | `score` (probability-weighted), `legend`, `probabilities`, `confidence` |

Response: `model`, `answers` keyed by the request's question names,
`usage` with `input_tokens` / `output_tokens`. Errors: 401, 422, 429,
529. **TypeSafe's SDKs retry automatically by default** — Eugene
disables that wherever an SDK is used, because a hidden retry is a
second bill and a second decision nobody asked for.

**Jev** (docs.typesafe.ai/models): hosted SaaS only — current version
`jev-1.13.0`, aliases `jev-latest` / `jev-preview`, 64k context, no
downloadable weights in the official material. So the promise is
**access to hosted Jev**, never local hosting of Jev, and the hosted
path is cloud-classified: never a local fallback, refused outright by
local-only keys.

**Kev** (github.com/jaredpalmer/kev, pinned commit `1c35199`, read from
`kev/serve.py` and the README at that commit):

- Install: `uv sync --extra serve` in the checkout (Python 3.12+,
  `transformers >= 5.17`). Launch:
  `python -m kev.serve --run <checkpoint> --port <p>`.
- Flags are exactly `--run` (Hub id, local directory, or `id@revision`;
  default `runs/kev`), `--fallback`, `--port` (default 8008). **No
  `--host`: the bind is hardcoded `127.0.0.1`** in the uvicorn call,
  which is precisely the posture we want — Eugene is the authenticated
  front door.
- **The model loads BEFORE the server binds** (`ck.load(...)` precedes
  uvicorn startup in `main`), and there is **no health endpoint**. That
  is vLLM's readiness shape: alive-and-refusing is `loading`, and only
  the supervisor can say so. The readiness probe is `GET /v1/models`,
  which answers only once serving and reports
  `{models: [{id, aliases, run, base, lora, device, dtype, temperature,
  prefix_cache: {...}}]}`.
- The request's `model` field is **echoed unchanged, never validated**
  (`"model": req.model`). So the public alias travels as-is and the
  driver's identity normalization (`upstreamModelId`, B1) is available
  but not required for Kev.
- Malformed requests are 422. Extra endpoints beyond the protocol:
  `/v1/systemone/permute` and `/v1/systemone/separate` (evaluation
  tooling, not part of Eugene's surface).
- **The server handles one request at a time** (a lock in the server;
  no cross-caller batching). The driver therefore advertises
  `maxConcurrent: 1` on its decision capability and the layers above
  must not over-admit — a non-cancellable engine that is over-admitted
  holds capacity nobody can free.
- Checkpoints: Kev-0.8B (base Qwen3.5-0.8B-Base), Kev-4B, Kev-9B —
  rank-16 LoRA adapters plus a small pointer head, tokenizer and
  calibration artifacts in the checkpoint, base model downloaded
  separately on first run. Apache-2.0 (weights and bases); training
  datasets carry their own licenses. **The starter is Kev-0.8B**, the
  smallest published checkpoint. The exact on-disk layout of a
  checkpoint is NOT documented at the pin; the live run records it
  before the library learns to recognize one.

**Vercel `/v1/evaluate`** (vercel.com/docs/ai-gateway): a different
dialect — the boolean kind is `type: "boolean"` answering
`probability`, and usage is `inputTokens`/`outputTokens` — so TypeSafe
compatibility must not be advertised as AI SDK evaluation
compatibility. A follow-up unless it ships with a real pinned-client
test.

## The shape

**The public door is TypeSafe's, verbatim.** `POST /v1/systemone` on
the gateway takes `model` (a public Eugene alias), `state`, `questions`
and answers in TypeSafe's response vocabulary, because the point is
that a TypeSafe client changes its base URL and nothing else.
Non-streaming, initial scope. Client keys are accepted (the fifth
client-admission path, beside `/v1/models`), and every existing control applies unchanged: scopes and
discovery filter on the public model id, local-only refuses anything
not local-and-enforced, concurrency and rate limits count decisions
like completions, and bounds (question count, option count, level
count, body size) are enforced **before** any backend work.

**Protocols stay in drivers.** A reusable `systemone_http` engine
speaks the pinned protocol to a configured endpoint — a supervised Kev
runtime by `runtimeName`, some other System One server by `baseUrl`, or
TypeSafe's hosted endpoint with a protected `apiKey`. Public and
upstream model names reuse B1's split. Client-supplied destinations and
provider secrets never ride the public request.

**The agent hosts Kev.** `EngineKind.kev`: argv from the pinned flags,
`answers_while_loading = False` with a startup budget (first launch
downloads a base model), readiness by `GET /v1/models`, an isolated
environment recipe pinned to the commit, and the same
never-in-Eugene's-venv rule as vLLM and MLX.

**Decision-only is a capability, not a hidden failure.**
`DriverInfo.capabilities.decision` names the supported kinds and limits;
`capabilities.chatCapable: false` on a decision driver makes a chat
call to that model a clear 400 naming `/v1/systemone`, instead of a
protocol error from a backend that never spoke chat. The reverse holds
too: `/v1/systemone` to a chat-only model is a 400 naming
`/v1/chat/completions`.

**Decision meaning is validated, never invented.** The driver checks
answer keys and types, legal choices, distributions, finite numbers and
score ranges before returning success; malformed backend output is a
backend error. Provider probabilities and calibration provenance are
preserved (`reportedModel` carries what the backend said it was) without
claiming cross-model comparability. No JSON-prompted chat model is ever
silently substituted. Raw state is not logged by default.

**A timeout is not permission to re-decide.** The R2.5 rule applies
unchanged: a fired deadline after possible execution does not cascade —
the same decision quietly sent to a different model is a different
decision. Refusals before work keep cascading, per A6b.

## Out of scope (from the roadmap, restated)

Training a competing model, automatic tool execution or approval,
turning Eugene into an agent harness, semantic equivalence between
providers, every Jev-inspired project, Vercel `/v1/evaluate`
compatibility without a real pinned-client test, and a new general
benchmarking dashboard.
