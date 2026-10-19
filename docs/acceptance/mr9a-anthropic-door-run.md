# MR9a: search results and the memory tool on the Anthropic door (run of record, 2026-10-18)

Design: `docs/design/workbench-memory-and-documents.md` section 10.2. Script:
`scripts/mr9a-anthropic-door-acceptance.py`.

**Stack.** A real `llama-server` (b11719, on the processor) with Qwen3.5-4B Q4_K_M, behind a recording
proxy, behind the real inference-driver and the real gateway (the MR9a working tree, pinned to specs
`241059c`), with `r4-stubs.py agent` listing the components. Every ambient `EUGENE_PLEXUS_*` variable
dropped; ports 9480-9484.

**Result: 11 PASS, 0 FAIL.**

| # | Check | Observed |
|---|---|---|
| 1 | The gateway routes the model | Qwen3.5-4B-Q4_K_M |
| 2 | A top-level search result reaches the engine numbered 1 | `[Search result 1: Project Heron note 1 (kb://heron/1)]` in the user message |
| 3 | A tool's search result is numbered after it | `[Search result 2: ...]` in the `tool` message |
| 4 | The model answers with a code word only the search results hold | `TANGERINE-4417` |
| 5 | Citations enabled: answered, `citations` named ignored | 200; `x-eugene-plexus-ignored-settings: citations, thinking` |
| 6 | Mixed citation settings: a 400, nothing reaches the engine | 400 naming `citations` |
| 7 | The memory tool reaches the engine as a function `memory` | the six commands in the enum |
| 8 | The protocol text follows the request's own system text | `You are a careful assistant.` then the protocol |
| 9 | The model's call comes back as `tool_use` `memory` | `stop_reason: tool_use`, input `{"command": "view"}` |
| 10 | The caller's result is taken and the loop continues | the `tool` message carries the listing; 200 |
| 11 | `count_tokens` counts both | 11 bare, 53 with a result, 799 with the memory tool |

`engine-requests.jsonl` (kept with the logs) shows the forced call's body carried `tool_choice:
"required"`.

**Observed limits.**

- With Qwen3-0.6B (the script's default model) check 9 failed in an earlier run: `tool_choice:
  required` reached the engine, and the model spent the whole 200-token cap without a call. The cap is
  now 600 for that request; the run of record used the 4B model.
- The model's `view` call left out `path`. The schema requires only `command` (one flat schema for
  six commands), so a client's handler sees what Anthropic's own model can send.

Gateway tests: `tests/test_anthropic_reach.py` (16), with the Anthropic and server-tool files, 189
passed; ruff, ruff format, mypy (win32 and linux) clean.
