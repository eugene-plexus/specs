# P2c: the missing chat fields — record

**2026-09-28.** Design:
[`openai-inference-compatibility.md`](../design/openai-inference-compatibility.md)
§8, "Taken without a separate call". Measured first:
[`provider-accounts-measurement.md`](provider-accounts-measurement.md) §7.
**Built, run and pinned in both installers, and P2 is complete:** its
done-when (an audio question and a PDF question answered through chat, Lyria's
music through chat, a text-only backend routed around) is met. The installers
pin all five Python components at P2's end:

| Component | Pin | What moved |
|---|---|---|
| inference-driver | `8390004` | P2c |
| gateway | `fa81fca` | P2c and its fix |
| agent | `47d4e2a` | regen-only, specs `eca5391` |
| control | `0608bac` | regen-only, specs `eca5391` |
| library | `7052065` | regen-only, specs `eca5391` |

Every archive was fetched (HTTP 200). The specs CI acceptance set (12 steps)
passes locally against exactly these heads. `ui` stays at dist `323e3b5`: no
screen consumes P2 yet.

| Repo | Commit |
|---|---|
| specs (contract) | `8ee10cf`, then `eca5391` (a sentence the acceptance run proved wrong) |
| inference-driver | `8390004` |
| gateway | `2977f8b`, then `fa81fca` (the defect below) |

- **`scripts/p2-media-acceptance.py`: 18 checks with fixtures, 28 with
  `--openrouter-live`, all PASS.** P2a and P2b's checks plus four new fixture
  checks and two new live ones.
- **`scripts/p2-sabotage.py`: 62 of 62 caught** (22 new), plus two declared
  escapes.
- **Unit suites:** inference-driver 730 (15 new), gateway 851 (23 new). ruff,
  format and mypy are clean on both. Against the pre-P2c source, **12 of the
  driver's 15 and 20 of the gateway's 22 new tests fail**; the rest are checks
  of an absence that held before too (a local engine claims none of the
  settings, `logprobs: false` asks for nothing, hints are dropped). The
  twenty-third gateway test is the reproduction for the defect below and
  fails with it put back.

## What it does

**Settings, routed by A2's `callerSettings`:** `logprobs` (with
`top_logprobs`), `logit_bias`, `reasoning_effort`, `verbosity`, `prediction`
and `web_search_options`.

- **Claimed only where known.** An OpenRouter model claims the ones its listing
  names; OpenAI's own endpoint claims all six. A local engine and a provider
  whose list says nothing per model claim none. So a request that sets one is
  routed to a model that honours it, and refused if there is none.
- **The refusal names the setting now**, in the caller's spelling, with
  `param`. It used to say *"the required tools or explicit settings"*, which
  left the caller to guess which. That improves every A2 refusal, not only
  P2c's.
- `logprobs: false` asks for nothing and does not restrict routing.
  `top_logprobs` without `logprobs: true` is refused.
- The agentic CLIs refuse all six, as they refuse the other settings they
  cannot carry.

**What comes back, batch and streamed, in OpenAI's shapes:**

- `choice.logprobs`. Streamed, it rides on each frame's choice beside `delta`,
  which is where OpenRouter puts it (measured).
- `message.annotations`, and `delta.annotations` when streamed: the
  `url_citation`s a provider's web search produced. OpenRouter's own `file`
  annotations are its cache of a parsed PDF, not citations, and are not carried.

**Hints:** `prompt_cache_key`, `prompt_cache_retention`, `service_tier` and
`safety_identifier` are carried to OpenAI's own API and dropped elsewhere with
one warning. They never restrict routing: a hint changes where or how cheaply
an answer is made, not what it says. No OpenRouter model lists any of them
(measured). `safety_identifier` used to be discarded at the door; it is not now.

**The deprecated `functions`:** `functions`, `function_call` and the `function`
role are translated to tools in the raw body, before the schema reads it. The
answer goes back in the old shape: `message.function_call`,
`delta.function_call` fragments and `finish_reason: function_call`. A history in
the old shape is carried as a tool call and its result, paired in order. It is
refused together with `tools` or `tool_choice`, and a `function` result with no
`function_call` before it is refused too.

**`POST /v1/responses/input_tokens`:** the body is translated as `/v1/responses`
translates it. It is counted by a ready backend's own template and tokenizer,
through the same path as `/v1/messages/count_tokens`, now one helper. A count
the backend cannot give without generating is a 400 saying so: every hosted
provider, since OpenRouter has no such endpoint (measured).

## Found on the way

- **The first build sent `parallel_tool_calls: false` for the old shape, and
  that routed it almost nowhere.** It made the setting explicit, so A2 kept
  only models listing `parallel_tool_calls`: 12 of 455 on OpenRouter. The unit
  fake listed every setting, so no unit test could see it. The acceptance run's
  fixture lists only four, and the request was refused, naming
  `parallel_tool_calls`. It is not sent now, and if a model makes more than one
  call the first is given. The contract said *"`parallel_tool_calls` is sent as
  false"* and was corrected (`eca5391`). A new gateway test fails with the
  injection put back.
- **A listed parameter is not a promise, twice.** OpenAI refuses
  `web_search_options` for `gpt-4o-mini`, which OpenRouter lists as taking it.
  And mistral-nemo's providers refuse a *named* `tool_choice` (*"No endpoints
  found that support the provided 'tool_choice' value"*) though it lists
  `tool_choice`. Both come back as the caller's 400 with the provider's words.
  The live check forces a function on `gpt-4o-mini` instead.
- **Two tests locked in old refusals:** `test_consequential_unsupported_settings`
  expected `reasoning_effort`, `logit_bias` and `logprobs: true` to be refused as
  unsupported fields. They are still refused, by routing now, and the named
  refusal is what keeps those three cases passing. The comment was amended.

## The acceptance run

One more fixture model, `acme/thinks`, lists all six settings, answers with
logprobs and citations (plus a `file` note), and calls a tool when one is
forced. Like OpenRouter with `require_parameters`, the fixture refuses a
setting a model does not list with a 404. A second fixture driver, `llama`, is
a single-model `llama-server` that counts through `/apply-template` and
`/tokenize`.

**Fixture checks (4 new; 18 in all, second execution):**

15. Every setting sent to `careful → [text-only, thinks]` is answered by tier
    2 in one attempt, with every field on the wire in OpenAI's names and
    `require_parameters` set. Logprobs and the citation come back streamed and
    not, without OpenRouter's `file` note. The text model is never asked. The
    `llama` driver and the text-only model claim none of the six.
16. A setting no backend lists is refused naming it, with nothing sent.
    `top_logprobs` needs `logprobs`. Hints go to a model that lists none of
    them, and are dropped on the way.
17. The deprecated `functions` reach the backend as tools with the call forced
    and `parallel_tool_calls` unsent. They come back as `message.function_call`
    and `function_call` fragments. A function history is carried as a tool call
    and its result.
18. `/v1/responses/input_tokens` on `local-llama` is the backend's count (4 for
    four words). On the OpenRouter-shaped model it is a 400 saying it cannot
    count without generating.

**Live checks (2 new; 28 in all, second execution):**

- A slot `live-careful → [gemini-2.5-flash-lite, mistral-nemo]` answered
  `logprobs` with two alternatives per token, from tier 2 in one attempt.
  gemini lists no logprobs.
- `openai/gpt-oss-20b` spent more reasoning tokens at `high` than at `low`: 142
  against 14 on one run, 54 against 3 on the next. `perplexity/sonar` returned
  20 `url_citation`s. `openai/gpt-4o-mini`, forced by the deprecated
  `function_call`, answered `{"name": "get_weather", "arguments":
  "{\"city\":\"Oslo\"}"}` with `finish_reason: function_call`.

The first live execution failed on mistral-nemo's named `tool_choice`, above.
About $0.07 per live run, most of it Lyria and Sonar; P2c's measurements cost
about $0.012.

## The sabotage pass

`scripts/p2-sabotage.py` gained 23 sabotages for P2c, run with P2a's and P2b's
41 in one pass: a baseline first, every anchor checked before any edit, and
restores from byte copies. **All 22 that should be caught were caught on the
first pass.**

- **Driver (8):** the listing's `reasoning_effort` not read; a local engine
  claimed for the hosted settings; `logit_bias` not put on the wire; hints sent
  to every backend; a batch answer's logprobs not read; a streamed token's
  logprobs dropped; a streamed citation not forwarded; any annotation taken for
  a citation (declared escape, below).
- **Gateway (15):** `logit_bias` not named as explicit; `web_search_options`
  not carried; a batch answer's citations dropped; its logprobs dropped; a
  streamed citation not forwarded; the driver's stream logprobs not read;
  `top_logprobs` taken without `logprobs`; a refused setting not named;
  `functions` not carried as tools; a legacy caller answered with `tool_calls`;
  its finish reason left `tool_calls`; its stream sent `tool_calls` fragments; a
  function result not paired with its call; `parallel_tool_calls: false` sent
  again (the defect above, put back); `input_tokens` answering a count nobody
  made.

**The declared escape:** removing the driver's `url_citation` filter lets
OpenRouter's `file` note through to validation. `ChatAnnotation`'s `type` is the
constant `url_citation`, so validation drops it anyway. Two mechanisms do one
job; the filter is kept because it says why before the schema does. P2a's
declared escape (the gateway's chat-door PDF rewrite) escaped again as
declared.

## Still owed

- **At P2's end, which this is:** agent, control and library re-pin
  regen-only, since `common.yaml` gained P2b's and P2c's schemas. `ui`
  re-pins when a screen consumes any of it.

## Not covered

- **No local engine is claimed for `logprobs` or `logit_bias`**, though
  llama.cpp and vLLM document both. Neither was measured here, so they are
  routed around, which is where a request asking for logprobs was before P2c
  (refused).
- `reasoning_effort` is claimed only where the listing names it (186 models).
  323 list OpenRouter's own `reasoning` object; mapping one to the other was
  not measured.
- OpenAI's own endpoint is claimed for all six settings and for the hints by
  reasoning, not measurement: no OpenAI key was used.
- The Responses door carries none of P2c's settings (its `reasoning`, `text`
  and logprob fields); only `input_tokens` is new there.
