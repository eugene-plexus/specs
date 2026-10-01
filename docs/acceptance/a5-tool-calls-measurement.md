# A5 measurement: how local models' tool calls fail, per model

**2026-09-30.** `scripts/a5-tool-call-measurement.py` (the instrument) and
`scripts/a5-summarize.py` (the table), data in
[`a5-data/`](a5-data/). Design and the decision it feeds:
[`../design/tool-call-repair.md`](../design/tool-call-repair.md).

**What was measured.** `llama-server` b11303 (the Windows CPU build; the
5090 holds the live install's model), `--jinja`, 16k context, one slot.
Ten models, each with its model card's recommended sampling. Twelve
scenarios, three samples each, two for the dense 24-27B models. Nothing
went through Eugene: this is the engine and the model, which decide what,
if anything, Eugene builds.

## The table

The budget scenario (`truncated`) is counted apart, in the last column.
"One call at a time" is a model making one of two calls and leaving the
other for the next turn, which OpenAI's semantics allow and an agent loop
handles. It is not a failure.

| Model | Answers | OK | One call at a time | Engine | Model's JSON | Wrong | of which type coercion fixes | No call | Text calls a lenient parse recovers | Cut off but valid |
|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-4b *(starter 4B)* | 33 | 30 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 of 3 |
| gemma-4-e4b *(starter 8B)* | 33 | 30 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 of 3 |
| gemma-4-12b *(starter 14B)* | 33 | 29 | 1 | 3 | 0 | 0 | 0 | 0 | 0 | 0 of 3 |
| qwen3.8-27b *(starter 30B)* | 22 | 20 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 of 2 |
| qwen3.6-35b-a3b *(starter MoE)* | 33 | 30 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 of 3 |
| qwen3-coder-30b-a3b | 33 | 33 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 of 3 |
| qwen3-30b-a3b-instruct-2507 | 33 | 30 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 of 3 |
| gpt-oss-20b | 33 | 26 | 3 | 3 | 0 | 1 | 0 | 0 | 0 | 0 of 3 |
| mistral-small-3.2-24b | 22 | 18 | 0 | 2 | 0 | 2 | 0 | 0 | 0 | 0 of 2 |
| llama-3.1-8b | 33 | 12 | 0 | 4 | 0 | 14 | 6 | 3 | 0 | 0 of 3 |

**Across 314 answers:**
- **No model wrote broken JSON.** Not once.
- **No call arrived as text that a second parser could have recovered.**
  Whenever llama-server failed to parse a call, it said so with an error
  and no text (below).
- **Every cut-off call said it was cut off.** All 28 `truncated` answers
  came back with `finish_reason: length` and arguments that do not parse.
  The failover thread's hazard (a truncated call that is valid JSON with a
  200) did not occur.
- **The starter set's five models made no mistake at all** except the
  engine's below.

## The engine's failures

**1. A named `tool_choice` is ignored: 22 of 30 forced answers.**
`tool_choice: {"type": "function", "function": {"name": "get_weather"}}`
asks for that call. llama-server b11303 reads `tool_choice` as a string
(`json_value` in `tools/server/server-common.h`), so an object falls back
to `auto`. All it does is log *"Wrong type supplied for parameter
'tool_choice', using default value"*, once per forced request in every
server log. Eight of ten models then answered in prose. The two that did
not (Qwen3-Coder, Llama 3.1) call the tool anyway. Through Eugene it is the
same: the driver passes `tool_choice` through untouched. Forcing one tool is
how structured-output libraries work (LangChain's `with_structured_output`,
Instructor), so this is the one failure here that a real client meets on
every model.

**2. Llama 3.1's parallel calls are rejected whole.** On `parallel`, all
three samples answered *500: "The model produced output that does not match
the expected peg-native format"*, and so did one `escaping` sample.
Generating the same tokens through `/apply-template` and `/completion` shows
what it wrote:
`{"name": "get_weather", "parameters": {"city": "Oslo", ...}}; {"name":
"get_weather", "parameters": {"city": "Paris", ...}}`. That is two
well-formed calls in the model's own format, separated by `; `, and a
lenient parse recovers both, valid, every time. But the 500 carries no
text, so no layer above the engine (Eugene included) can repair it. Meta's
format documents single calls only.

**3. A tool-call id under 9 characters makes Mistral's template refuse.**
The first run's `chain` scenario used the id `call_1`. Mistral Small 3.2's
chat template raises (*"Tool call IDs should be alphanumeric s…"*) and
llama-server answers 400 before generating anything. The scenario now uses
a realistic id. A side test of four shapes passed all four: 9
alphanumerics, llama-server's own 32-character ids, OpenAI's `call_…` and
Claude Code's `toolu_…`. The rerun replaces those two records, and both
are ok. The table counts the rerun. **One place Eugene mints a short id:**
the driver's streaming fallback, `call_{index}` (`call_0`), when a backend
streams a call without an id. It is rare (llama-server always sends one).

## Known upstream (llama.cpp's tracker, searched 2026-09-30)

| Finding | Upstream |
|---|---|
| `tool_choice: "required"` does not force a call | **Known**: #29295 (advisory, not grammar-enforced, Qwen3), #27217, #27767 (Qwen3.6; *"likewise a named function `tool_choice`"*). #27767 also finds `response_format: json_schema` enforced, as §3 of the design does |
| A named `tool_choice` falls back to `auto` for every model, because `tool_choice` is read as a string | **Not filed as such.** #27767 reports the symptom on Qwen3.6 only, without this cause |
| A parse failure answers 500 and discards the whole generation | **Known class**: #27733 (Qwen3.8), #25321 (gpt-oss, closed), #26381. Llama 3.1's `;`-separated calls: not found |
| Mistral's template refuses a tool-call id | **Related**: #26359 (Ministral-8B refuses llama-server's own id), closed as stale, not fixed |

Filing the named-choice issue is Troy's call: it is public.

## The models' failures

- **Llama 3.1 8B types values as strings**: `"minutes": "15"`,
  `"amend": "false"`, and the attendee list as one string. A
  schema-guided coercion fixes 6 of its 14 wrong answers. It also calls
  a tool for "17 times 3" every time, and after a tool result it
  describes the next step instead of making it (3 no-call). No other
  model needs coercion.
- **Copying a program exactly** (`escaping`): five answers changed it, a
  dropped quote or a dropped `!`. That is Llama 3.1 twice, Mistral twice and
  gpt-oss once. The JSON was valid each time; the content was wrong.
- **gpt-oss-20b makes one call at a time** (3 of 3 on `parallel`), and so
  did Gemma 4 12B once.

## Streamed, as harnesses send it

Harnesses stream, and llama-server parses a streamed call on its own,
partial-parsing path. Six models re-ran all twelve scenarios streamed
(`--stream`, which assembles tool-call deltas by index as a client does;
data in `a5-data/streamed/`). These were qwen3.5-4b, llama-3.1-8b,
gemma-4-e4b, gpt-oss-20b, qwen3-coder-30b-a3b and qwen3.6-35b-a3b. **Every
model's answers were identical, scenario by scenario, to its non-streamed
run**, the 500s and the ignored named choice included.

## Forcing one tool

`"required"` with only the named tool, and structured output, are in §3
of the design. In short: `"required"` was honoured 22 of 28 times and
never on Qwen3.6-35B-A3B. Structured output gave a valid call 5 of 6
times on the two Qwen models tried; the miss ran out of budget thinking.

## Not measured

- **Through Eugene.** The gateway and driver carry tool calls (P-series
  acceptance, live against Ollama). A second engine (Ollama, vLLM) was not
  measured.
- **A GPU.** Sampling is the same and timings are not the subject, but a
  GPU build is a different binary.
- **Long agent loops.** These are one or two turns; a ten-turn loop with
  growing context is not here.
