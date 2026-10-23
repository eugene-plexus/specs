# Row 57: Responses: non-function tools and `compact`

Lane GW. Cross risk. Sources: RSP-T, gateway `responses.py` (today every
tool type but `function`, `namespace`, `web_search` and `image_generation`
is "a tool this gateway cannot run"), `openai-inference-compatibility.md`
("`/v1/responses/compact` is deferred: OpenAI's compaction returns an item
no other backend can read back").

## 1. What it delivers

- **Client-run tools of the Responses API work with local models.**
  Coding agents built on Responses send tools that the client runs:
  `custom` (free-text input), `local_shell`, `shell` and `apply_patch`.
  The gateway gives each to the model as a function it can call, and turns
  the call back into the item type the client expects (`custom_tool_call`,
  `local_shell_call`, `shell_call`, `apply_patch_call`), and their
  `*_output` items back into tool results.
- **`/v1/responses/compact` works.** A client that asks Eugene to compact a
  long conversation gets a compaction item it can send back later; the
  gateway expands it to the summary for whatever model serves the next
  request.
- **What stays refused says why and what would work:**
  `computer_use_preview` (no local model is trained for it),
  `code_interpreter` (Eugene has no sandbox to run code; "use a function
  tool and run it yourself"), `mcp` (row 59), `file_search` (row 56).

## 2. Design

### Client-run tools (`responses.py`)

| Tool | The model sees | Back to the client |
|---|---|---|
| `custom` {name, description, format} | function `name` with one string parameter `input` | `custom_tool_call` {call_id, name, input} |
| `local_shell` | function `local_shell` with `command` (array), `workdir`, `timeout_ms`, `env` | `local_shell_call` {call_id, action: {type: exec, …}} |
| `shell` | function `shell` with OpenAI's documented parameters | `shell_call` |
| `apply_patch` | function `apply_patch` with one string parameter `input` (the patch) | `apply_patch_call` |

- Input items `custom_tool_call_output`, `local_shell_call_output`,
  `shell_call_output`, `apply_patch_call_output` become tool results with
  their `call_id`.
- **Grammars are not enforced.** A `custom` tool's `format` (Lark or
  regex) is passed in the function's description and named in
  `x-eugene-plexus-ignored-settings` (`tools[i].format`), so the client
  knows the output was not constrained (settings never lie). A later row
  may pass a regex grammar to llama.cpp where it applies.
- Streaming emits OpenAI's event types for each item
  (`response.custom_tool_call_input.delta` and the rest).

### `compact`

- `POST /v1/responses/compact` takes the conversation (`input`, or
  `previous_response_id` once row 54 is built) and the model.
- The gateway asks that model for a summary with a fixed compaction prompt
  (what was asked, decided and done, open threads, files touched), within
  a budget of 4,000 tokens.
- It returns OpenAI's shape: output items ending with a `compaction` item
  whose `encrypted_content` is the summary, encrypted and authenticated
  with the gateway's own key (the same kind of key file as
  `video-handles.key`), so it is opaque to the client and cannot be
  forged.
- When a later request's input carries that item, the gateway decrypts it
  and puts the summary in place as a developer message. An item from
  another gateway or from OpenAI is refused with "This compaction was made
  elsewhere; send the conversation instead."
- No store is needed: the item carries its own summary.

### Contract (`gateway.yaml`)

The tool types above as accepted, their call and output items, the
compact path and the compaction item; the refusal texts for the tools
that stay refused.

## 3. Repositories

gateway (`responses.py`, a new `compaction.py`), specs (contract,
acceptance).

## 4. Tests that fail before

- `test_responses_tools.py::test_a_custom_tool_round_trips_as_custom_tool_call`
  (today: refused).
- `test_responses_tools.py::test_local_shell_call_and_its_output`.
- `test_responses_tools.py::test_apply_patch_call_and_its_output`.
- `test_responses_tools.py::test_a_grammar_is_named_as_ignored`.
- `test_compaction.py::test_compact_returns_an_item_that_expands_next_time`
  and `test_a_tampered_item_is_refused`.

## 5. Acceptance (CI, Linux, about 3 minutes)

`specs/scripts/row57-responses-tools-acceptance.py` on row 2's harness with
the fixture backend scripted to call each tool: a Responses client using
the OpenAI Python SDK sends each tool type, gets the right call item,
returns its output, and receives the final answer; a compaction made, then
sent back, reaches the fixture backend as a developer message with the
summary.

## 6. Do not change

Row 54's chain loading (call it when present), row 59's MCP tool, row 56's
`file_search`.

## 7. Size and risks

M, about 2 days. Risks:
- **Unconstrained free-text tools:** a patch the model writes may not
  apply; the client's own apply step reports it, as it does today with
  function tools; the ignored-settings header says the grammar was not
  enforced.
- **Summaries lose detail:** the compaction prompt and budget are fixed and
  written down; the client chose to compact.

**Calls:** none.
