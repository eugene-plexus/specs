# M10 acceptance — tokens actually arrive early

**Status:** passed 2026-09-11, **13 checks, zero failures**, on the
seventh attempt. Script:
[`scripts/m10-acceptance.sh`](../../scripts/m10-acceptance.sh). Design:
[`m10-token-streaming.md`](../design/m10-token-streaming.md).

```
agent :8079 -> control :8083, gateway :8080, library :8082
driver ollama-stream :8091 -> ollama :11434 (dolphin3 8B Q4)
driver flaky-upfront :8092 -> stub :8195, 503s before producing anything
driver flaky-mid     :8093 -> stub :8196, emits 3 SSE deltas then vanishes
```

## Why the check is a frame count and a clock

From M0 to M9 `/v1/chat/completions` with `stream: true` returned
perfectly well-formed SSE — correct `ChatCompletionChunk` objects, the
correct `data: [DONE]` sentinel — and delivered the whole answer in a
single content frame once generation had finished. **Every "is it
streaming" assertion that checks framing passed throughout that time.**
So this script is not allowed to check framing: it counts content frames
and measures the gap between the first and the last.

## The numbers

| | |
|---|---|
| content frames | **79** (M0–M9 produced exactly 1) |
| time to first token | **0.11 s** |
| total | 0.43 s |
| first token at | **26 % of the request** |
| usage on the final frame | 24 prompt / 80 completion / 104 total |
| `x_eugene_plexus` on the final frame | `driver=ollama-stream` |

## What it found that the fixtures could not

**A stream that stops is not a stream that finished.** The check that
exists for the commit point failed, correctly, and the reason was a real
defect: a backend that dies mid-answer simply closes the connection,
httpx's `aiter_lines()` ends without raising, and the driver fell
through to emitting its `done` chunk with whatever had arrived. The
driver logged `POST /v1/generate/stream 200 OK`; the gateway saw a
completed stream; the client got half an answer presented as a whole
one. Upstream always marks the end — `data: [DONE]` or a
`finish_reason`, and llama.cpp, vLLM and Ollama all send at least one —
so the absence of both now raises, and the gateway emits an error frame.
Fixed in `inference-driver` `6317e11`.

## Three ways the harness lied before it told the truth

All three are the same family, and the family is already in this
project's notes: *a check whose subject is not where it is looking
reports confidently on the wrong thing.*

**1. The instrument buffered.** The first run reported time-to-first-token
at **94 % of the request** while also counting 79 content frames — two
things that cannot both be true. `urllib` handed the frames over in a
lump. `curl -N` plus an unbuffered reader put TTFT at 0.11 s. The same
shape as M4's socket instrument, which counted the HTTP 200 meaning
"ready" as a probe refuting the claim it was written to test.

**2. The assertion matched the failure it should have caught.** Check 7
asserted on the token `"The "`, and passed — against
`{"error":{"message":"The model 'flaky' does not exist..."}}`. The
gateway's own 404 text contains `"The "`, and the error envelope
contains `"error"`, so both assertions were satisfied by a request that
never streamed at all. **The most important check in the script was
green for a run in which the thing under test had not happened.** Only
fixing an unrelated cosmetic line — a diagnostic that printed nothing —
revealed it. The stub now emits `ZEBRA`/`QUARTZ`/`VELLUM`: an assertion
whose subject also appears in the failure it is meant to catch is not an
assertion.

**3. The wait was satisfied by something other than its subject.**
`wait_for_model` grepped the raw `/v1/models` JSON, so the model name
`flaky` matched a *driver* name elsewhere in the document and the wait
returned before anything was routable. It now parses the model ids and
matches exactly.

And one environmental trap worth keeping: **Windows let three stale
stubs stack on one loopback port**, with the oldest still serving. A run
was reading a two-runs-old reply from a process it thought it had
started. `free_port` now kills by port rather than by pid or command
pattern — the same lesson as M9's teardown, which killed the pid it held
rather than whatever owned the port.

## What this proves, and what it cannot

**Proves:** tokens reach the client as they are generated, measured by
frame count and by a clock rather than by framing; the final frame still
carries `usage` and `x_eugene_plexus`; non-streaming is unchanged; a
backend that dies *before* the first token still cascades; and one that
dies *after* it truncates with an error frame and **is not completed by
the other backend sitting right there in the install** — the commit
point, live.

**Cannot:** the CLI subscription backends. `claude_code_cli` streams for
real (its `text_delta` events were captured from the CLI at v2.1.207
while building the adapter) and `codex_cli` does not and reports
`capabilities.streaming: false`; both need live subscriptions, Claude
costs ~31k prompt tokens a request, and this box's Codex auth is
currently stale. The browser half is `ui`'s own vitest suite — including
the frame-split-across-reads case — plus the playground by hand.
