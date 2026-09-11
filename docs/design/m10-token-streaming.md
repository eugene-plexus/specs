# M10 — token streaming, end to end

**Status: design, 2026-09-11.** Renumbers the compute/storage-separation
milestone to M11; that one is decided and undesigned, this one is the
last functional hole a user meets in the first five minutes.

## 0. The gap is bigger than the roadmap said

CLAUDE.md has carried this as *"driver token streaming returns 501"* for
several milestones, which undersells it in a way worth correcting before
designing anything:

- All three driver engines raise `NotImplementedError` from `.stream()`
  — `openai_compat_http`, `claude_code_cli`, `codex_cli`.
- `POST /v1/generate/stream` is a 501 stub.
- The **gateway compensates by sending the entire completion as a single
  SSE content chunk** (`routes/inference.py`, `_stream_completion`,
  documented there honestly as a deliberate M0 limitation).

So the framing is right and every OpenAI client works unmodified — and
**nothing anywhere delivers a token before the generation is finished**,
including this project's own playground. A chat UI shows a long silence
and then the whole answer at once.

The good news is that everything except the implementation is already
in place, which is why this is a contained piece of work:

- `inference-driver.yaml` **already specifies the stream**: `event:
  token` / `event: done` / `event: error`, with an explicit allowance
  that backends without native streaming MAY emit one `token` then
  `done`.
- `InferenceDriverInfo.capabilities.streaming` already exists and is
  documented as *"whether `/v1/generate/stream` emits true incremental
  tokens"*.
- The driver's `BackendEngine` protocol already declares `stream() ->
  AsyncIterator[StreamChunk]`, and `StreamChunk` (`text`, `done`,
  `result`) already exists.
- All three engine stubs carry a note saying the backend supports
  streaming and only a consumer was missing.

## 1. The commit point — the one rule that matters

`TieredClient.generate()` can retry freely because **nothing has reached
the client** until it returns. Streaming breaks that assumption, and it
is the whole design:

> **Failover is possible until the first token is emitted. After that, a
> backend failure truncates the stream — it must never be retried on
> another backend.**

Retrying after the first token would splice two models' output into one
answer, with no marker at the seam. That is worse than a truncated
response: it is a wrong answer that looks like a right one, which is the
failure mode this project keeps designing against.

So `TieredClient.stream()` has two phases:

1. **Before the first chunk** — identical to `generate()`. A
   cascade-eligible failure (transport / 5xx / timeout) moves to the
   next candidate; a 4xx raises immediately.
2. **After the first chunk** — the slot is *committed*. Any failure
   propagates to the route, which emits an OpenAI `error` frame and ends
   the stream. No further candidates are tried.

The route already handles the second half correctly for a different
reason, and says so: *"An error after the stream has been opened cannot
become an HTTP status — the 200 is already sent."* The new rule is the
same observation one step earlier — an error after the first *token*
cannot become a failover either.

**This is observable behaviour of the public endpoint**, so it earns the
design's only contract change: a sentence in `gateway.yaml` saying that
a streamed request can be truncated where a non-streamed one would have
cascaded. A caller that needs failover guarantees should not stream.

## 2. The driver

Three engines, all of which upstream already supports:

| Engine | How it streams | `capabilities.streaming` |
|---|---|---|
| `openai_compat_http` | SSE with `stream: true`, deltas off `choices[0].delta.content` | `true` |
| `claude_code_cli` | `--output-format stream-json --include-partial-messages` | `true` if verified live, else `false` |
| `codex_cli` | `--json` is already a JSONL feed | `true` if verified live, else `false` |

**`capabilities.streaming` must be honest, and it is allowed to be
false.** The contract explicitly permits one `token` event followed by
`done`, so a backend that cannot stream still works — it just doesn't
deliver early. Reporting `true` for a backend that batches would make
the flag useless for the only thing it is for: telling a UI whether to
expect progressive output.

The route stops being a 501 and becomes an SSE response over
`engine.stream()`, emitting the three contracted event types. Errors
**before** the first token can still be a real HTTP status; after it,
they become an `event: error` frame, mirroring the gateway's rule one
layer down.

## 3. The gateway

- `DriverClient` (the gateway's internal protocol, not a spec type)
  grows `stream()`. `HttpDriverClient` implements it by consuming the
  driver's SSE; `TieredClient` implements the commit-point rule above;
  the test fakes implement it too.
- `_stream_completion` stops calling `generate()` and iterates
  `client.stream()`, emitting one content delta per token through the
  `frame()`/`envelope()` helpers that already exist. The role frame,
  the usage frame, the `x_eugene_plexus` final frame and `data: [DONE]`
  all stay exactly as they are — that framing is already correct and
  is not what this milestone changes.

**No SSE library.** Both ends of this stream are our own contract —
three event types, single-line JSON payloads — and the gateway already
hand-*frames* SSE on its output side. A ~25-line parser scoped to that
contract is symmetric, dependency-free, and one less Dependabot stream.
If we ever consume a third party's SSE, use a real library; this parser
should not be reached for then.

## 4. Metrics keep working, and an attempt that dies mid-stream is not "served"

M8's `RoutingHooks` fire around every attempt on both paths, and that is
already the recording seam precisely because the streaming path returns
a `StreamingResponse` and never builds a response object. Two rules:

- An attempt is `served=True` only when it reaches `done`. One that
  emitted tokens and then broke is `served=False` with the error class —
  it did not serve the request, and calling it served would hide
  truncation from the one surface that could show it.
- `latency_ms` per attempt stays what it already is. **Time to first
  token is a new and more useful number for a streaming request, and
  this milestone does not add it** — that is a schema change to the
  metrics rows and belongs with a decision about whether the balancer
  should consume any of it (still open by choice since M8).

## 5. Cancellation

A client that disconnects mid-stream must not leave the driver
generating. The async generator is closed when the response is
abandoned, so the upstream response has to be released in a `finally` —
in both the gateway's SSE consumer and the driver's engine
implementations. Untested before; an acceptance check should kill a
client mid-stream and assert the engine's request ends.

## 6. Contract changes

Expected: **one, and it is documentation.** A sentence in `gateway.yaml`
stating the commit-point rule, because it is observable behaviour of the
public endpoint. Radius: `gateway`, `ui`.

Everything else was contracted at M0 and never implemented, which is the
pleasant half of this milestone — same shape as M4, where the second
engine needed no contract change at all.

## 7. Acceptance

`scripts/m10-acceptance.sh`, live, against a real engine:

1. A streamed completion delivers **more than one** content frame, and
   the first arrives materially before the last. (The current
   implementation would pass a naive "did it stream" check — it emits
   correct SSE — so the check must count frames and measure the gap.)
2. Time to first token is well under total time.
3. A non-streamed completion is unchanged.
4. A backend killed **before** the first token cascades to the next
   tier, exactly as today.
5. A backend killed **after** the first token produces an `error` frame
   and no second backend's output. This is the commit point, and it is
   the check the milestone exists for.
6. `capabilities.streaming` is reported per backend and is true for at
   least one.
7. The UI playground shows tokens arriving progressively — browser, via
   the Playwright suite M9 added.

## 8. What this cannot prove

Streaming from the two CLI subscription backends needs those
subscriptions live; `claude_code_cli` costs ~31k prompt tokens a
request, so it is exercised once rather than in a loop. Everything else
runs against a local llama.cpp.
