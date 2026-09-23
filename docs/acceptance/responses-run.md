# The Responses door, and a configurable image limit: slice 4

**Built and run 2026-09-23.** Troy's calls the same day
(`docs/design/responses-and-completions.md` §3): build `/v1/responses` now;
leave `/v1/completions` and fill-in-the-middle for later; make the image
limit configurable with a default of 12.

- Contract: `openapi/gateway.yaml` (the path, `/v1/responses/{responseId}`,
  seven loose schemas) and the image-limit prose in
  `openapi/components/common.yaml` and on `/v1/messages`.
- Gateway: `responses.py` (the translation), a route and its stream in
  `routes/inference.py`, the path added to client admission, the body limit
  and CORS, a `response.failed` for the admission middleware's mid-stream
  refusal, and the `maxImagesPerRequest` setting.
- Inference-driver: its image cap is now a ceiling of 64 rather than a
  second copy of the policy.
- Instruments: `scripts/responses-capture.py` (the listener, sixteen
  modes), `scripts/responses-acceptance.py` (the live run),
  `scripts/responses-sabotage.py` (the sabotage pass). The capture record
  is `docs/acceptance/responses-measurement.md`.

## What the capture changed

The design (written the same morning) had the shape right. The capture
found five things it did not know, and each is now a line of the
translation and a test.

| Found | Consequence |
| --- | --- |
| Codex sends **no `max_output_tokens`**, and regenerates an answer that ends `response.incomplete` **five times** before failing. | The install's `defaultMaxTokens` (2048) is not applied on this door; the model profile's cap still is. Without this, any long answer costs six generations and an error. |
| Codex's **idle timeout (five minutes) runs before the first event**, and an SSE comment does not reset it; `response.in_progress` does. | The stream opens as soon as a backend is chosen and repeats `response.in_progress` every ten seconds until output arrives. |
| A bare `error` event loses our message; `response.failed` keeps it, and **its code decides** whether Codex retries: `context_length_exceeded` and `invalid_prompt` stop, `server_error` retries. | Failures after the stream opens are `response.failed`, coded by whether another attempt could help. A fired deadline is `invalid_prompt`, since the next attempt would compute the same prompt for as long. |
| Codex sends `detail: "high"` on **every** image, on a `-i` attachment and in `view_image`'s result, and `view_image` answers with a **list** holding an `input_image`. | `detail` is accepted and named on the ignored-settings header (the chat door's refusal of anything but `auto` would 400 every picture), and a tool's picture moves to the next user message, as on `/v1/messages`. |
| A 404 is retried five times before Codex shows it; a 400 once. | A model nothing serves is a 400 here, as on `/v1/messages`. |

## The live run

`scripts/responses-acceptance.py`, with `EP_CODEX=1`. Engines on the
processor (the GPU was occupied): llama.cpp b10948 serving Qwen3-0.6B
(text, tools, reasoning) and Gemma 4 E4B with its projector (images, the
tool loop, the timing checks). Codex CLI 0.130.0 with an isolated
`CODEX_HOME`, `wire_api = "responses"`.

**First execution: 16 of 17.** The failure was the model, not the door:
asked to run `cat secret.txt`, Gemma sent `["cat secret.txt"]`, one string,
which Codex's policy blocks (as it blocks `cmd /c`). The loop itself
worked: the call went out, Codex returned its refusal, and the model said
so. With the argv spelled out in the prompt, the shell check passed.

| # | Check | Result |
| --- | --- | --- |
| 1 | the gateway routes both engines | PASS |
| 2 | a Codex-shaped request is answered; `web_search` and the cache key named, not refused | PASS: `ignored='prompt_cache_key, tools.web_search'` |
| 3 | streamed: `response.created`, `response.in_progress` first, `response.completed` last, numbered, no `[DONE]` | PASS |
| 4 | the install cap (set to 16) stops the chat door and not this one, on the same prompt | PASS: chat `length` at 16 tokens; responses `completed` at 34 |
| 5 | `max_output_tokens` is carried and a cut answer is `incomplete` | PASS |
| 6 | a required tool call is a `function_call` item with JSON arguments | PASS: `{'command': ['ls', '-R']}` |
| 7 | streamed: the argument deltas add up to the arguments | PASS |
| 8 | reasoning is a `reasoning_text` item, and `encrypted_content` decodes to it | PASS: 467 characters |
| 9 | a reasoning item sent back reaches the prompt | PASS: 221 input tokens without a canary sentence, 237 with it |
| 10 | an over-long prompt is `context_length_exceeded`, as a 400 and as `response.failed` | PASS |
| 11 | a model nothing serves is 400 `model_not_found` here, 404 on the chat door | PASS |
| 12 | a long prefill is covered by `response.in_progress` at most ten seconds apart | PASS: first output at 22.7 s, three keep-alives before it |
| 13 | Codex completes a turn | PASS: `ready.` |
| 14 | Codex runs a shell tool loop and replies with a nonce only the tool could have given it | PASS on the second execution: `NONCE-A18E43FB`, two requests |
| 15 | Codex's `-i` picture reaches the model: `sample.png` red, then green | PASS |
| 16 | Codex's `view_image` picture reaches the model: red, then green | PASS: two requests each |
| 17 | **Codex with a 15 s idle timeout sits through a 20.9 s prefill in one request** | PASS: one request, 33 s |

Check 17 is the keep-alive proven in the client it exists for. The engine's
prompt cache was cleared first and the prefill read from the engine's own
log, because a cache hit from an earlier run makes the prefill instant and
the check meaningless (last session's trap). Codex's own prompt prefills in
about ten seconds on this processor, so the task directory's `AGENTS.md`
carried enough text to make it longer than the timeout.

## The sabotage pass

`scripts/responses-sabotage.py`: **40 sabotages, 40 caught**, baseline and
restore green on both repos, every restore from a copy. Each one is a way
the door could be wrong about Codex, and four are the over-correction of a
fix in this slice: the cap dropped on every door; every in-stream failure
fatal, a dead backend included; a later developer message hoisted into the
leading system prompt; and someone else's `encrypted_content` read as
reasoning. Three are the measured traps themselves: the
keep-alive sent as an SSE comment, the stream silent until the first
token, and a failure sent as a bare `error` event.

Two catch only by a structural test, and say so: the door left out of
client admission (as `/v1/systemone`'s was, a test reads the set), and out
of the body limit (a request claiming a huge body is no longer a 413).

## Pins

Contract specs `a62ddc9`. Gateway `6e90a6b` and inference-driver `dfaac8e`,
each re-pinned to it, **pinned in both installers**; the UI was not
re-pinned, since no screen reads the new types, and `maxImagesPerRequest`
reaches Config through the schema-driven editor without one.

## Found on the way, not fixed

**llama.cpp b10948 ignores a named `tool_choice`.** Asked with
`{"type": "function", "function": {"name": "shell"}}`, it answered in text
with `finish_reason: stop`; with `"required"` it called the tool. That is a
setting silently dropped one layer down, on every door, not only this one.
The driver could send `required` with only the named function offered,
which means the same thing; that is its own change, recorded here for Troy.

## Not done

- No client other than Codex CLI 0.130 was measured. The OpenAI Agents SDK
  defaults to Responses and was not installed.
- Codex's auto-compaction against this door was not exercised.
- A wake (a model loading on demand) happens before the stream opens, so a
  load longer than Codex's idle timeout is still retried by Codex; the
  retry finds the load already under way.
- vLLM and Ollama behind this door were not run.
