# What an answer being written is doing, and which cap stopped it

Troy, 2026-10-10, on his first Strata chat in Workbench:

- **The working line said "Waiting for the model…" through minutes of
  reasoning.** That reads as a connection not yet made. The line knew only
  the prompt stage (llama.cpp's reading) and tools. Strata sends neither, and
  each piece of reasoning cleared what little there was.
- **Then "The answer reached its length limit… raise Longest answer
  (tokens) in this chat's settings."** Strata's own record showed the
  request had asked for `max_tokens: 4096`. It generated exactly 4,096
  tokens, still thinking, in a 131,072-token context. The cap was his
  install's `defaultMaxTokens`, saved long before; the chat had none. The
  default has been blank (no cap) since 2026-09-28. Troy cleared it.

Troy's calls (2026-10-10):

- Exact tokens where the engine counts them, and elapsed time where it does
  not; never an estimate.
- Build the fix that names where a cap came from.

## What changed

- **Contract** (specs `53edce0`, `a502f60`):
  - `StreamProgress` gains `generating`, with the backend's own running
    count (`generated_tokens`) and speed.
  - `CompletionRoutingInfo.output_cap` (`OutputCap`, `OutputCapSource`) is
    the `max_tokens` sent and its source: `request`, `profile` or
    `install`.
  - The first version inlined the source enum, which renamed the
    gateway's existing `Source` to `Source1`. It is a named schema now.
- **inference-driver.**
  - llama.cpp is asked for `timings_per_token`, alongside `return_progress`
    and only once it has answered as llama-server.
  - Each frame's `timings.predicted_n` becomes `generating` progress, at
    most every half second.
  - Measured on b10948: the count rises token by token, and the last
    frame's count equals the usage's `completion_tokens`.
  - Strata 0.1.39 counts only at the end, so it sends none.
- **gateway.**
  - The count is relayed in its own words.
  - Each candidate's cap and its source are recorded as the candidate is
    prepared, and the final frame (or the whole answer) reports the one
    that answered. A fallback's cap is its own model's profile.
- **Workbench.**
  - The line says Waiting for the model, then the model is working, then
    *Thinking* or *Writing the answer*, with the backend's count and speed
    (*Thinking · 1,234 tokens · 83.1 tok/s*), or else how long the answer
    has run (*Thinking · 1 min 12 s*).
  - A count is no longer cleared by the text it counts.
  - The answer keeps the cap it was sent (schema 9, `output_cap`).
  - A length stop names the setting: this chat's Longest answer, the
    model's Library profile, or the install's Default max output tokens.
    When the gateway said nothing, it blames no setting.
- **ui (Playground).**
  - The working line shows the count.
  - The length badge names the cap: *hit the install's cap (4,096)*, with a
    title saying where to change it.

## Acceptance of record

`scripts/progress-acceptance.py` uses real processes: llama.cpp b10948 on
the processor with Qwen3 0.6B, a real driver over it, a real driver over a
stub hosted API, and a real gateway. Step 4b is new. It ran on
Amish_Station, 2026-10-10, and **ALL PASS**:

```
== 4b. while it writes: the backend's own count, and the cap it was sent
  PASS  5 counts while it wrote, rising: 1 ... 177
  PASS  the counts came between the words, as it wrote
  PASS  the last count, 177, is within the usage's 200
  PASS  and the backend's own speed: 87.0 tok/s
  PASS  the final frame says the cap was the request's own 200
  PASS  a reply stopped by the install's cap says it was the install's 24 (Troy's case)
== 5. a hosted API: never sent llama.cpp's flag, and still heard from
  PASS  the hosted API was not sent return_progress or timings_per_token, which it would refuse
```

Run it with `EP_LLAMA_SERVER` pointing at a llama-server that loads. The
script's default, b11215, is now missing its DLLs on this machine.

The first run of 4b failed three of its own checks, and each was the check's
fault, not the product's:

- The first count (1 token) comes a moment before the first word, on the
  frame where llama.cpp opens its thinking with no text.
- The request asked for progress without `include_usage`, so there was no
  usage to compare with. The gateway omits it then, as documented.
- 4b's requests ran before step 4, which reads the two newest metrics rows.
  4b now runs after step 4.

## Unit tests

- inference-driver: `tests/test_stream_progress.py` (4 new, over a capture
  of the real b10948 stream with its model path replaced:
  `fixtures/llamacpp_b10948_timings_per_token.sse`). Two existing tests
  now also check that `timings_per_token` is never sent unasked or to a
  hosted API.
- gateway: `tests/test_output_cap.py` (10: profile, request, install, none,
  and a fallback's own profile, each streamed and whole), and one in
  `tests/test_stream_progress.py`.
- Workbench:
  - `tests/test_output_cap.py` (4: kept across a restart, none, a
    malformed cap, a schema 8 store);
  - `web/src/lib/lib.test.ts` (the working line, the count across
    pieces, a note per source).
- ui: `lib/outputCap.test.ts`, `lib/workingState.test.ts` and
  `app/playground/page.test.tsx`.

## Sabotage

`scripts/writing-progress-sabotage.py`: **22 caught, 0 escaped**, across
the driver (4), the gateway (5), Workbench's server (3), its page (4), the
Playground (3) and the acceptance on real processes (2). Each gate passed
at baseline and again after the restore.

Full suites before landing:

| Repo | Result |
| --- | --- |
| inference-driver | 1069 passed |
| gateway | 1287 passed |
| Workbench | 251 passed; web 261 (25 files) |
| ui | 1878 passed (152 files) |

lint, format and types were clean in each.

## Pinned

- inference-driver `608cd77`
- gateway `b8e7db0`
- agent `0eb1d8f` (the catalogue's Workbench: dist `349ef13`, built from
  `530740f`)
- ui `dist` `4ba4ef2` (built from `6340cf78`)

## The live run (owed)

Once Edge has this and Workbench's catalogue pin:
- A Strata chat in Workbench should read *Thinking · 1 min 12 s* while it
  reasons.
- A llama.cpp model should read *Thinking · N tokens · R tok/s*.
- A length stop should name the setting that made it.
