# Tools are assumed, and turned off only on evidence

Troy, 2026-10-12, when Workbench's "Search the web" was off for Qwen3.8-Flash-Next on Strata: "I don't
like the idea that Eugene blocks tool use simply because the developer hasn't tested a particular
configuration. What if a user is using Eugene to test their custom engine endpoint? We should always
assume in 2026 that a model & engine can use tools."

## The rule

- A chat model on any engine is taken to use tools (`toolCalling: true`) unless Eugene has evidence
  otherwise.
- Evidence is one of:
  1. The backend refused a request because of its tools, in its own words. Only measured wording is
     matched: llama-server's "tools param requires --jinja flag" (a 500 from a `--no-jinja` engine).
     The driver reports `toolCalling: false` and asks again every 10 minutes with the smallest request
     carrying a tool. An answer clears it, so a backend fixed in place gets its tools back. The person
     sees the backend's words.
  2. A provider's own listing says so (OpenRouter's `supported_parameters`, OpenAI's Responses-only
     tool models).
  3. Eugene has no way to carry tools to that engine (the Claude Code and Codex CLI subscriptions).
     This is said as Eugene's limit, never as the model's.
- A setting the engine is measured not to honour is sent anyway and named in
  `x-eugene-plexus-ignored-settings`, not refused. A refusal is for what cannot be sent at all.
- An unknown answer (an older driver that reports nothing) counts as yes at the gateway.

What was already so: the OpenAI-compatible engine (llama.cpp, vLLM, custom endpoints) defaulted to
tools on. **Strata was the exception**: it shipped text-only until a live check (`strata-engine.md`,
capability checks), so the driver refused tools and structured output for it, and the gateway
listed every Strata model without tools.

## Strata, measured (2026-10-12, Troy's running engine)

Strata v0.1.39, `qwen3.8-flash-next-iq2_xs` on the RTX 5090, its own OpenAI chat endpoint, directly.

| Check | Result |
|---|---|
| `tools`, `tool_choice` absent (auto) | a correct call, valid JSON arguments, `finish_reason: tool_calls`, reasoning apart from the content; 1.6 s |
| the same, streamed | the call in deltas, valid JSON; 0.7 s |
| the round trip (call, tool result, answer) | "It's currently 17°C in Paris with light rain." |
| Eugene's `web_search` tool | two calls with sensible queries in one turn |
| two calls at once | Paris and Tokyo |
| tool calls emitted as thinking (Strata#754, seen on its Anthropic interface on 0.1.38) | not on the OpenAI path |
| `tool_choice: none` | **ignored**: it called the tool |
| `tool_choice: required` (a question needing no tool) | **ignored**: "Hello!" |
| `tool_choice` naming `get_time` (a weather question) | **ignored**: it called `get_weather` |
| `response_format` `json_schema` | valid JSON to the schema; 1.5 s |
| `response_format` `json_object` | valid JSON; 3.6 s |
| `json_schema` together with tools | Strata's own 400: "structured response_format with tools/MCP is not supported" |

The script and its output: `scratchpad/strata-tools/` in the session that ran it; the numbers are
copied here.

## What the first build round found (driver `f6b3ddf`, gateway `4588eea`, both reviewed)

- **llama-server's refusal of tools is a 500, not a 4xx.** b10948 with `--no-jinja` (`--jinja` is its
  default) answers every tools request `500 {"error":{"code":500,"message":"tools param requires --jinja
  flag"}}`. The evidence is the whole message matched, at any status, and it is the caller's 400.
- **`parallel_tool_calls` was still refused for Strata, so Codex could not use it at all** (Codex sends
  `false` on every request). Measured by the reviewer: `true` is honoured, `false` is ignored. Both are
  now sent, and `false` is named.
- **A per-request header from the driver made the gateway hold every stream's head** until the
  backend's first frame (or a 10 s keepalive). That broke the Responses door's contract and Codex's
  retry mapping. So what is not honoured is now static, `capabilities.settingsNotHonoured`, read
  from the chosen backend before anything is sent. Streams open as they always have.
- **A learned "no tools" outlived its cause**, until the driver restarted. While turned off, the driver
  asks again every 10 minutes and an answer clears it.
- **Ollama's equal gap was refused** (`tool_choice` other than `auto`, `parallel_tool_calls: false`);
  it is now sent and named, as Strata's is.
- **"A listing that says nothing" is not a no**: an OpenRouter entry without `supported_parameters` and
  Gemini's Gemma models (a name prefix, never measured) are now taken to call tools.
- Only what the caller sent is named, not the gateway's own search loop's forcing. An embedding model
  sent tools is refused for being the wrong door. The no-tools refusal is worded as the driver's
  report, not the model's failing.

## What shipped (driver `4511bfb`, gateway `47521ef`, both reviewed twice)

- **Driver, Strata:**
  - tools, tool results, `response_format` and `parallel_tool_calls` pass through;
  - `tool_choice: none` is honoured by sending no tools (and no `parallel_tool_calls`);
  - `capabilities.settingsNotHonoured` lists `toolChoice` [`required`, `function`] and
    `parallelToolCalls` [`false`] (measured: Strata ignores them);
  - `response_format` with tools is Strata's own 400, relayed in its words;
  - the driver's forced-tool route (a named `tool_choice` turned into a JSON schema, for llama-server)
    is unreachable for Strata.
- **Driver, Ollama:** its equal gaps are sent and named the same way, no longer refused.
- **Driver, every engine:**
  - llama-server's measured refusal, "tools param requires --jinja flag" (a 500 at any status), turns
    `toolCalling` off for that model and makes the request the caller's 400 in the backend's words;
  - it is asked again every 10 minutes with one tool and one token, and an answer clears it.
  - A request without tools is not refused for `tool_choice` or `parallel_tool_calls` meanwhile.
- **Listings that say nothing are not a no:**
  - an OpenRouter entry without `supported_parameters`, and Gemini's Gemma models, call tools;
  - an entry whose listing has the key and lacks tools stays no.
- **Driver contract:** `/v1/generate` and its stream also answer a per-request
  `x-eugene-plexus-ignored-settings` (driver spelling), for direct callers. The gateway does not read
  it.
- **Gateway:**
  - The chat, Messages and Responses doors name what the chosen backend's `settingsNotHonoured`
    lists, for what the caller sent, before anything is sent, so streams open as before.
  - Only a chat model that says nothing counts as calling tools.
  - Tool-adjacent settings are admitted where a driver reports nothing.
  - A non-chat model sent tools is refused for the wrong door.
- **Workbench** (`2f40f0a`): the reason names Eugene's limit ("Eugene cannot give X tools as it runs
  here"). The reason was already on the screen under the composer, not only in the tooltip.

Left for round three (reviewed, not blocking):
- Gemini and OpenRouter still refuse an explicit `parallel_tool_calls: false` (Codex cannot use them).
- LM Studio reads a capability list without `tool_use` as no.
- The gateway's header can name the balancer's first pick rather than the backend asked first.
- `tool_choice: none` with `parallel_tool_calls: false` names the latter though it is not sent.
- An unreadable `/v1/info` turns a tools request into a 400 rather than a retryable 5xx.
- Some new paths have no test that can fail.
