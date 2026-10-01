# A5: tool calls that work with local models

**Status: measured 2026-09-30; §2 items 1 and 2 built the same day on
Troy's call** (inference-driver `b35bc54`, `53412d5`; through the driver a
forced call went from 0 of 6 to 28 of 28 across ten models, see the
record). Upstream reporting is Troy's to write: llama.cpp forbids
AI-written bug reports.
The audience roadmap's A5 is *"measure first: how often a local model's
tool call fails, and whose failure it is"*. This document holds the
method, then the table, then what the table says to build, if anything.

**The short answer: there is almost nothing to repair.** Across ten
models and 314 answers there was:
- no broken JSON;
- no call written as text that a second parser could recover;
- no cut-off call that looked whole.

The starter set made no mistake of its own. The failure every client meets
is the engine ignoring a named `tool_choice`. Eugene can fix it in the
driver, and a measurement says the fix works.

## Why measure per model

The complaint is real but thin. In T1, *"my harness is looping and can't
use the tools"* (5 points) was blamed on Ollama, and Eugene's tool-call
carriage and context honesty already answer that. What is left is repair.
A failed tool call has three different causes, and each has a different
answer:

| Kind | What happened | Whose | What would answer it |
|---|---|---|---|
| **Engine** | The model wrote a good call in its own format; the engine did not turn it into `tool_calls`. It arrives as text, or as an engine error | llama.cpp's parser (upstream) | A second, lenient parser in our driver, or an upstream fix |
| **Model's JSON** | The arguments do not parse, or the token budget cut them off | The model, or the budget | Report it, never repair it. A truncated call can still be valid JSON with a 200 (the failover thread's warning) |
| **Wrong** | Valid JSON that names a tool nobody offered, breaks the schema, or does something other than what was asked | The model | Nothing a parser can do. Better settings or a better model |

So a table of models against those kinds decides what gets built. Mostly
engine: a repair is ours to build. Mostly model: it is a model
recommendation, and the Discover copy should say which models call tools
well. Mostly budget: the answer is to say so.

## §0 The instrument

`scripts/a5-tool-call-measurement.py` (and `--stream`, which assembles the
streamed answer as a client does) drives `llama-server` directly
(b11303, Windows CPU build, `--jinja` as default), one model at a time.
Each model runs with its own card's recommended sampling, three samples
per scenario (two for the dense 24-27B models on CPU), seeds 1-3.
Nothing goes through Eugene: what is measured is the engine and the model.

Twelve scenarios, each chosen for a way calls break:

| Id | What it asks | What it stresses |
|---|---|---|
| single | one tool, one call | the floor |
| choose | nine tools, pick `read_file` | selection |
| escaping | write a program with quotes and backslashes | JSON string escaping |
| nested | an event with an object and an array of objects | nested schemas |
| parallel | two cities | more than one call |
| chain | the next call after a tool result | using a result |
| types | a 15-minute timer | integer, not `"15"` |
| no_params | the time | an empty arguments object |
| no_call_needed | 17 x 3 | calling when nothing needs a tool |
| many_tools | commit, among twenty tools | a coding agent's tool list |
| forced | `tool_choice` names the function | the engine's grammar |
| truncated | an essay into a file, with 120 tokens of budget | what a cut-off call looks like |

Every answer is classified as one of:
- `ok`
- **engine:** `unparsed_call` (with whether a lenient parse recovers a
  valid call), `engine_error`
- **model's JSON:** `broken_json`, `cut_off`, `truncated_valid` (a call
  that parses although the budget ran out: the hazard)
- **wrong:** `wrong_tool`, `bad_args` (breaks the schema), `wrong_args`
  (valid, but not what was asked), `partial` (one of two calls),
  `unneeded_call`
- `no_call`: answered in prose when a call was needed

## §1 The table

[`../acceptance/a5-tool-calls-measurement.md`](../acceptance/a5-tool-calls-measurement.md)
has it, with every answer that was not ok. By kind:

| Kind | Answers | Where |
|---|---|---|
| Engine | 26 of 314 | 22 are a named `tool_choice` ignored (eight models). 3 are Llama 3.1's two `;`-separated calls rejected with a 500 and no text. 1 is the same 500 on a single call |
| Model's JSON | 0 | none. All 28 cut-off calls said `length` and did not parse |
| Wrong | 17 | Llama 3.1 14 (6 fixed by type coercion), Mistral 2, gpt-oss 1. Five are a program copied inexactly |
| No call | 3 | Llama 3.1, after a tool result |

## §2 What the table says to build

1. **Honour a named `tool_choice` on llama.cpp. Recommended, ours.**
   llama-server b11303 reads `tool_choice` as a string and drops an object
   to `auto` with only a log line. The obvious translation, `"required"`
   with only the named tool, is **not** enough (§3): Qwen3.6-35B-A3B, the
   starter set's MoE, wrote prose and degenerated to the token limit 3
   times of 3. Asking for the tool's arguments as structured output
   (`response_format: json_schema`, no `tools`) gave a valid call there 3
   of 3. So the recommended repair is structured output, returned as the
   call. The driver already knows a backend is llama-server (it answers
   `/props`, read for progress, context and fill-in-the-middle). So the
   translation needs no contract change and touches no other backend. The
   build should start by measuring it across all ten models: that is its
   failing check. **And report it upstream**: a fix there makes ours
   unnecessary. Upstream already knows `"required"` is not enforced
   (#29295, #27217, #27767). The named choice falling back to `auto` for
   every model does not appear to be filed (the record's "Known upstream"
   table). Filing it is Troy's call.
2. **Mint long tool-call ids. Recommended, trivial.** The driver's
   streaming fallback names a call `call_{index}` when a backend sends
   none. Under 9 characters, Mistral's template refuses it on the next
   turn.
3. **Do not build a lenient parser for calls in text.** It would have
   recovered nothing: 0 such answers. The only parse failures were
   llama-server's 500s, which carry no text to parse.
4. **Do not repair JSON, or a cut-off call.** 0 broken JSON, and every
   cut-off call said so. Keep passing `finish_reason: length` through,
   which the gateway does.
5. **Not now: schema-guided type coercion** (`"15"` to `15`). It fixes 6
   answers, all from Llama 3.1 8B, a 2024 model the starter set does not
   ship. Revisit if a current model needs it.
6. **Report upstream: Llama 3.x's `;`-separated parallel calls** become a
   500. Meta documents single calls for that format, so upstream may call
   it the model's fault. Either way the text is lost before Eugene sees
   it.

What the table does not say: nothing here went through Eugene's gateway
and driver, and only llama.cpp was measured. Streaming changes nothing:
six models re-ran streamed and every answer matched.

## §3 Forcing one tool, two ways

**`"required"`, with only the named tool** (`forced_as_required`, three
samples, 4,096 tokens; data in `a5-data/required/`):

| Model | Honoured |
|---|---|
| llama-3.1-8b, gemma-4-e4b, gemma-4-12b, gpt-oss-20b, qwen3-coder-30b-a3b | 3 of 3 each |
| qwen3.5-4b, qwen3-30b-a3b-instruct-2507 | 2 of 3 each |
| qwen3.6-35b-a3b | 0 of 3 |
| mistral-small-3.2-24b | 0 of 1 (stopped: 25 minutes a sample on CPU) |
| qwen3.8-27b | not run |

**22 of 28.** Every miss is the same shape: no call, prose, then
generation until the token limit. Qwen3.6 degenerated into repeated emoji.
So the grammar `required` asks for is not applied to these models'
answers.

**Structured output** (`response_format: json_schema` with the tool's
parameters, no `tools`, and a system line naming the function):

- **qwen3.6-35b-a3b: 3 of 3**, a valid `{"city": "Oslo"}` each time.
- **qwen3.5-4b: 2 of 3**. The miss spent the whole 4,096-token budget
  thinking and returned nothing, which `finish_reason: length` reports.

Thinking is not constrained by either method, so a model that thinks
past its budget still answers with no call. Saying so (`length`) is the
honest end of that case.
