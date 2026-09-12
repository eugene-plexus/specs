# Tool calling, end to end — acceptance run

**2026-09-11 (late). 16 checks, zero failures, second attempt.**
`scripts/tool-calling-acceptance.sh`. Install-paths §9 step 6; design
[`agent-clients-and-tool-calling.md`](../design/agent-clients-and-tool-calling.md)
§5 items 1–2.

Contracts `95dfa8f`; inference-driver `b2aab87`, gateway `bf2c930`,
`ui` `be94751`, the rest re-pinned (`common.yaml` changed, so the radius
is all six).

## What ran

Six processes on this Windows box — agent on **8179**, its declared
control root, gateway and library, plus two inference-drivers — against
a local Ollama serving **qwen3-coder:30b**, a model trained for tool
calling. A model that was not would make a failure ambiguous between
"our stack lost the tools" and "this model does not do tools", which is
the exact confusion the milestone exists to remove.

The script binds 8179 rather than 8079 and **tears down by port**,
because this machine is also a live worker node in the UnRAID install.
Every earlier script in `scripts/` ends with `pkill -f eugene_plexus_`,
which here would kill the operator's own agent and everything under it.

## The headline

A real 30B model, given real tool definitions through the full
gateway → driver → backend path, **emitted a real tool call**, and the
loop closed:

```
finish_reason: tool_calls
tool_calls:    [{"id": "call_8lz8q0xu", "type": "function",
                "function": {"name": "get_weather",
                             "arguments": "{\"city\":\"Oslo\"}"}}]
```

then, handed `{"tempC": -3, "sky": "snow"}` back as a `tool` message:

> The current weather in Oslo is snowing with a temperature of -3°C.

That second request is the one that matters. It replays the assistant
turn that asked plus the result, and if either is lost or reshaped on
the way down the model cannot see that its call was answered — the
symptom being that it calls the same tool again, which reads as a stupid
model rather than as a lost message.

## THE FINDING: local engines do not fragment tool calls

**The first run failed two checks, and both checks were wrong.** They
asserted that a streamed call arrives in many fragments and that time to
first fragment is a small fraction of the request. Measured directly
against Ollama afterwards:

```
frame 1: delta_keys=['role', 'content', 'tool_calls']
         tool_calls=[{"id": "call_9z5zayhy", "index": 0, "type": "function",
                      "function": {"name": "get_weather",
                                   "arguments": "{\"city\":\"Bergen\"}"}}]
frame 2: delta_keys=[]
```

**Ollama emits the entire call — id, name and complete `arguments` — in
one delta.** It never fragments. So the check could only have passed
against a backend that fragments, and it was failing a correct
pass-through. This is the project's recurring failure — *a check whose
subject is not where it's looking* — and it appeared in the script
written to avoid it.

OpenAI proper does fragment, so the accumulation path is real and is
unit-tested on both sides with a fake that splits `arguments` mid-token.
What a live run against a local engine can prove is the part we own, so
the checks became:

- **equality with the backend**, measured in the same run rather than
  assumed — turning one delta into several would invent fragmentation,
  folding several into one would defeat streaming, and only the
  comparison distinguishes either from correct
- **structural, not timed** — the fragment gets its own frame *before*
  the terminal one (frame 2 of 3 here). A time-to-first-fragment
  threshold is a claim about when the model decided to call, which
  against a backend that emits the whole call at the end of generation
  is necessarily late and says nothing about us. It measured 97%, and
  97% is correct.

## The checks

| # | Check | Result |
|---|---|---|
| — | preflight: agent python, live Ollama with the model, every port free | PASS |
| — | agent up on 8179; it declares control, gateway and library itself | PASS |
| 1 | driver `/v1/info` reports `capabilities.toolCalling` | PASS |
| 2 | `GET /v1/models` reports `tool_calling` per model | PASS |
| 3 | a real model emits exactly one tool call | PASS |
| 4 | `finish_reason` is `tool_calls` | PASS |
| 5 | `arguments` is a string that parses to the declared parameter | PASS |
| 6 | **the loop closes** — the answer uses the tool result | PASS |
| 7 | streaming forwards exactly the fragments the backend emitted | PASS |
| 8 | every fragment carries an `index` | PASS |
| 9 | fragments reassemble to valid JSON | PASS |
| 10 | fragments reach the client before the terminal frame | PASS |
| 11 | the terminal frame says `tool_calls` | PASS |
| 12 | a request with no tools is untouched (`stop`, real content) | PASS |
| 13 | the CLI driver honestly reports `toolCalling: false` | PASS |
| 14 | that driver **refuses** a tools request with 400 | PASS |

Sixteen `ok` call sites; counted from the script rather than from the
output, after M9's record claimed 40 checks for a script with 39.

## Worth not rediscovering

**`content` going nullable is the change with the widest blast radius.**
An assistant turn that only calls a tool has no text, and an empty
string would assert the model said nothing. Both type checkers caught
the fallout rather than production: mypy found the thinking-mode
directive, the driver's config self-test sample output and two Claude
Code CLI system-prompt joins; `tsc` found three sites in the UI's
`ChatLog`. None of them would have failed until a tool call actually
came back.

**The driver's non-streaming parser used to raise on exactly the
well-formed case.** It required `content` to be a string, so a
tool-call-only response — the normal shape — produced a 502.

**The commit point needed no code.** `TieredClient.stream` sets
`committed` on the first event of *any* kind, so a tool-call fragment
was already past the point of no return. The contract now says so
explicitly, because the failure it prevents is worse than M10's:
splicing `arguments` half-written by one model and completed by another
can parse as valid JSON naming real parameters — a wrong action taken
confidently, handed to a harness that will execute it.

**A pre-existing library test reads live hardware.**
`test_detail_groups_candidates_and_attaches_the_fit` failed during this
session's re-pin sweep and had nothing to do with the contract change:
`recommend()` returns `None` when nothing fits in free VRAM, and the
acceptance run had left qwen3-coder resident. 509 MiB free → fail;
30,650 MiB free → 11 passed. CI is green at the same SHA because CI has
no GPU. Not fixed; recorded.
