# Reasoning and the local samplers — a real engine, a real Claude Code

**Run 2026-09-23 on this box.** llama.cpp b10948 serving Qwen3-0.6B-Q4_K_M on
the CPU (`-c 40960`, the agent's own argv otherwise) → the real
`eugene-plexus-inference-driver` (`6391945`) → the real `eugene-plexus-gateway`
(`558c91c`) → `r4-stubs.py agent`, plus a real Claude Code 2.1.207.
[`scripts/reasoning-samplers-acceptance.py`](../../scripts/reasoning-samplers-acceptance.py):
**20 PASS, 0 FAIL, third execution.** Contracts `99c64c9`, `cb526bf`, `e7eaae7`.
Both installers re-pinned.

## 0. What was missing, measured before anything was written

| Gap | How it was measured |
| --- | --- |
| **A reasoning model's thinking was discarded.** llama.cpp puts it in `reasoning_content` by default and vLLM 0.29 in `reasoning`; the driver read only `content`. | Capture against llama-server; then the **old driver run live**: "What is 2+2?" at `maxTokens: 24` answered `content: ""`, `finishReason: length`, 24 tokens spent, nothing else in the body. |
| **A vLLM reasoning-only turn was a 502.** `content: null` with no calls raised "missing string content". | vLLM 0.29 `ChatMessage` source; unit fixture. |
| **A history turn's reasoning never reached the engine.** llama.cpp renders `reasoning_content` on history for templates that keep it (`--reasoning-preserve` defaults on); it ignores `reasoning`. | Same tool-loop request: 172 prompt tokens without it, 184 with a twelve-token canary, 172 with the `reasoning` key. |
| **`top_k`, `min_p`, both penalties, `parallel_tool_calls` and `developer` were a 400** on the OpenAI door (`top_k` on the Anthropic door too); llama.cpp accepted all of them. | Gateway tests pinned the refusals; llama-server answered all five 200. |
| **`disable_parallel_tool_use` was silently dropped.** | Read `_tool_choice`. |
| **`stop_sequence` was always null.** llama.cpp cannot say which stop matched (its choice carries `finish_reason`, `index`, `message`); vLLM can (`stop_reason`). | Capture; vLLM source. |
| **Cached and reasoning token counts were dropped.** llama.cpp reports `prompt_tokens_details.cached_tokens`; vLLM also `completion_tokens_details.reasoning_tokens` when its parser is on. | Capture; vLLM source. |

## 1. What the run proved

| # | Check | Evidence |
| --- | --- | --- |
| 3 | A model that thought until `max_tokens` returns its reasoning | `content: ''`, 75 chars of `reasoning_content` |
| 4 | Streamed reasoning arrives first, on its own field | 222 `reasoning_content` frames, all before the 1 content frame |
| 5 | Cached prompt tokens from llama.cpp; no invented reasoning count | `prompt_tokens_details: {cached_tokens: 14}`, no `completion_tokens_details` |
| 6 | All five samplers reach **the engine** | read from the driver's DEBUG log of the upstream payload, not its request object |
| 7 | …and take effect | `top_k: 1` at temperature 2: 1 distinct output in 3; without it, 3 in 3 |
| 9 | An assistant turn sent back verbatim puts its reasoning into the engine's prompt | prompt grew by 80 tokens |
| 11–13 | Anthropic: thinking block with text, `display: "omitted"` → empty text + our signature, streamed `thinking_delta` in block 0 closed before the text block | 1,033 chars decoded from the signature; 224 thinking deltas |
| 14 | A client that did not enable thinking gets `content[0].text` | `['text']` |
| 15 | An omitted block echoed back reaches the engine's prompt | grew by 72 tokens |
| 16 | Cached input split Anthropic's way | `input_tokens: 1, cache_read_input_tokens: 14` |
| 18 | Claude Code, `--output-format stream-json --verbose`: gets the reasoning as text | `['thinking', 'text']`, result `ok` |
| 19 | Claude Code, text mode (`display: "omitted"`): parses the empty block + `signature_delta` | printed `ok` |
| 20 | Claude Code `--continue`, pointed at `r4-capture.py`: sends our block back **with the signature intact** | 1 signature, 572 chars decoded |

## 2. The run's findings

**Claude Code could not use the Anthropic door at all, and not because of this
change.** The first execution failed check 18 on the first request:
`API Error: 400 output_config: unsupported setting`. Re-captured with
`r4-capture.py`: Claude Code 2.1.207, now bundling agent-sdk **0.3.280** (the
R4 capture had 0.3.274), sends `output_config: {"effort": "high"}` on every
request, with beta `effort-2025-11-24`. A2's unknown-field refusal, correct in
principle, turned that into a 400 on turn one of every session, and **every
unit test stayed green because the Claude Code fixture predated the field.**
Making the fixture match today's request reproduced it as 61 failures. Fixed in
contract `e7eaae7`: `effort` is accepted and named on the ignored-settings
header, like `thinking.budget_tokens`; any other key, structured output's
`format` included, is refused by name.

**Claude Code chooses `display` by output mode.** The second execution failed
check 19. My check assumed `omitted` everywhere, but under
`--output-format stream-json --verbose` Claude Code sends
`{"type": "adaptive"}` with **no** display, so the block came back with text,
which is correct. Text mode sends `"omitted"`. The checks now cover both, plus
the round trip.

**Anthropic's `display: "omitted"` drove the signature design.** Taken
literally, an omitted block with an empty signature would show Claude Code
nothing (its choice) *and* drop a tool loop's reasoning between steps (a loss).
Anthropic's own answer is that the opaque signature carries continuity, so ours
does: `eugene-plexus-reasoning-v1:<base64>`, which is readable, prefixed, and
never presented as Anthropic's. Check 20 is the proof that Claude Code keeps it.

**TTFT and decode rate were wrong for reasoning models and are now right.** The
first driver event used to be the first *answer* token, after the whole thinking
phase, while `completion_tokens` counted the thinking. So `GET /v1/metrics`
over-reported time-to-first-token and over-reported decode tok/s. Reasoning is
now the first event, and the commit point too.

## 3. Sabotage

[`scripts/reasoning-samplers-sabotage.py`](../../scripts/reasoning-samplers-sabotage.py):
**64 of 64 caught** across both repos. It restores from a copy and opens with a
baseline on both gates. Each fix has three kinds of sabotage: the finding put
back, the over-correction put in, and the discriminator taken apart. The
over-corrections checked include reading one engine's field name but not the
other's, accepting any null `content`, sending reasoning to OpenAI's endpoint,
inventing a `parallel_tool_calls` default, a truthiness guard on `top_k: 0`,
showing thinking to a client that never enabled it, trusting a foreign
signature, and counting cached input twice.

**What the first pass taught:** one anchor had been reflowed by `ruff format`
after the list was written, so it matched zero times and reported SKIP (a
sabotage that never ran, counted as an escape rather than a pass). **Two
mechanisms were found before the pass and one was deleted:** the gateway's
assistant-only guard on `reasoning` duplicated the chat contract's refusal and
the Anthropic translator's scope, so it could never be observed. **Two fixtures
were strengthened so their discriminator could fail:** a foreign signature
exactly as long as our prefix and followed by valid base64, and a corrupt one
that a lenient decoder would read as `CORRUPT`. **One test was added because the
sabotage list named a path no test read:** every gateway test used the fake
driver, so the real `HttpDriverClient` parser was covered by nothing.

## 4. Not done, named

- **vLLM was not run.** Its field names, `stop_reason` and usage details come
  from the 0.29 source in the WSL venv, not a live server. `stopSequence` is
  unit-tested only.
- **Ollama was not run.** The driver reads both reasoning field names, so either
  one Ollama uses will be read; its handling of `top_k`/`min_p` is unverified.
- **Only a 0.6B model**, on the CPU. The mechanics do not depend on size; answer
  quality was not assessed.
- **`thinkingMode: off` was not driven live.** It is unit-tested on both paths.
- **No Claude Code tool loop against a real engine.** Check 20 proves the
  signature round-trips through Claude Code, and check 15 proves the same shape
  reaches the engine's prompt; the two were not joined in one run.
- **The UI is not re-pinned.** No screen reads `reasoning_content` yet; the
  playground shows nothing for a model's thinking phase, as before.
