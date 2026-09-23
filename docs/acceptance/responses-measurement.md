# What Codex CLI sends and does on the Responses wire

**Measured 2026-09-23** with Codex CLI **0.130.0** on Windows, against
`scripts/responses-capture.py` (a listener that records every request and
answers just enough of the Responses stream). Each run used an isolated
`CODEX_HOME` with one custom provider, `wire_api = "responses"`, and
`codex exec --skip-git-repo-check --ephemeral`. `wire_api = "chat"` is
refused at startup by this version, so this is the only wire Codex has.

This record is behind `POST /v1/responses` on the gateway. Each fact here
decided a line of the translation, and the tests quote them.

## 1. The request

Every request is `POST /v1/responses` with `Authorization: Bearer <key>`,
`stream: true`, **`store: false`** and **no `previous_response_id`**: the
whole conversation is resent on every turn. Top-level keys, all turns:

`model`, `instructions` (21 KB of prose), `input`, `tools`, `tool_choice:
"auto"`, `parallel_tool_calls: false`, `reasoning: null`, `store: false`,
`stream: true`, `include: []`, `prompt_cache_key` (the session id),
`client_metadata` (`x-codex-installation-id`).

**Not sent:** `max_output_tokens`, `temperature`, `top_p`, `text`,
`service_tier`, `truncation`.

`input` on turn one is a `developer` message (two `input_text` parts: the
sandbox rules and the skills list), then **two consecutive `user`
messages** (an `<environment_context>` block, then the prompt).

`tools` holds nine `function` tools with `strict: false` (`shell`,
`update_plan`, `request_user_input`, `view_image`, `spawn_agent`,
`send_input`, `resume_agent`, `wait_agent`, `close_agent`) and **one
server-side tool on every request: `{"type": "web_search",
"external_web_access": false}`**.

With `model_supports_reasoning_summaries = true` and
`model_reasoning_effort = "high"`, `reasoning` becomes `{"effort": "high",
"summary": "auto"}` and `include` becomes
`["reasoning.encrypted_content"]`. Without the first setting Codex sends
`reasoning: null` for a model id it does not know, whatever the effort.

## 2. What comes back on the next turn

Answered with a `function_call`, the follow-up resends the whole history
with our items appended. **Item `id` and `status` are dropped**; the rest
comes back as sent:

```json
{"type": "function_call", "name": "shell", "arguments": "{...}", "call_id": "call_1"}
{"type": "function_call_output", "call_id": "call_1", "output": "<text>"}
```

A `reasoning` item comes back **with its `content` and
`encrypted_content` intact, even when `include` was empty**:

```json
{"type": "reasoning", "summary": [],
 "content": [{"type": "reasoning_text", "text": "RAW: I should run echo."}],
 "encrypted_content": "CAPTURE-OPAQUE-REASONING-1"}
```

A `summary_text` summary is shown to the user. Raw `reasoning_text`
content is not shown (Codex's `show_raw_agent_reasoning` governs that).

**Images.** `-i picture.png` sends one user message whose parts are
`input_text "<image name=[Image #1]>"`, then `input_image` with a
`data:image/png;base64,…` URL **and `detail: "high"`**, then `input_text
"</image>"`, then the prompt. The `view_image` tool's result is a
`function_call_output` whose `output` is a **list**, holding one
`input_image` with a data URL and `detail: "high"`.

## 3. HTTP statuses: how many attempts, and what the user sees

The listener answered every request with the status and an OpenAI error
envelope whose message began `CAPTURE-<status>`.

| Status | Attempts | Time | What Codex showed |
| --- | --- | --- | --- |
| 400 | **1** | 0 s | our message |
| 401, 403, 404, 413 | 6 | 6-7 s | our message |
| 429 | 1 | 1 s | *"exceeded retry limit, last status: 429"*, **our message dropped** |
| 500 | 30 | 24 s | *"We're currently experiencing high demand"*, **our message dropped** |
| 502, 503, 504 | 30 | 25 s | our message |

So a 404 costs five pointless retries before the message appears, and a
5xx costs twenty-nine. **A model nothing serves is a 400 on this door**
(the Anthropic door's rule, for the same kind of reason).

## 4. Once the stream is open

| What the listener sent | Attempts | What Codex showed |
| --- | --- | --- |
| `response.failed`, `code: server_error` | 6 | our message |
| `response.failed`, `invalid_request_error` or `rate_limit_exceeded` | 6 | our message |
| **`response.failed`, `invalid_prompt`** | **1** | **our message** |
| `response.failed`, `cyber_policy` | 1 | our message |
| **`response.failed`, `context_length_exceeded`** | **1** | *"Codex ran out of room in the model's context window. Start a new thread or clear earlier history before retrying."* |
| `response.failed`, `server_is_overloaded` | 1 | *"Selected model is at capacity"*, our message dropped |
| `response.failed`, `insufficient_quota` | 1 | *"Quota exceeded"*, our message dropped |
| a bare `error` event | 6 | *"stream closed before response.completed"*, **our message dropped** |
| **`response.incomplete`, `max_output_tokens`** | **6** | each partial answer, then *"Incomplete response returned, reason: max_output_tokens"* |

Three consequences:

- A failure after the stream opens is `response.failed`, never a bare
  `error` event, which loses the message.
- The error code picks what Codex does. `context_length_exceeded` for an
  over-long prompt; `invalid_prompt` for anything that another attempt
  cannot fix (a backend that refused the request, a deadline that fired
  while the engine was still computing); `server_error` for the failures a
  retry can fix (a backend that died, nothing ready yet).
- **An answer cut off at `max_output_tokens` is generated six times and
  then fails.** Codex sends no `max_output_tokens`, so on this door the
  gateway's install-wide `defaultMaxTokens` (2048) would make every long
  answer do exactly that. The model's settings profile still caps it; the
  install default does not.

## 5. The idle timeout, and what keeps the stream alive

Codex drops a stream that sends nothing for `stream_idle_timeout_ms`
(default 300,000 ms) and retries it, five times. Measured with the timeout
set to 6 s and a 12 s silence:

| Before the answer | Result |
| --- | --- |
| nothing at all | idle timeout, 6 attempts, *"idle timeout waiting for SSE"* |
| an SSE comment (`: keepalive`) every 2 s | **the same: comments do not count** |
| `response.created`, then silence | the same |
| `response.created`, then **`response.in_progress` every 2 s** | **answered, 1 attempt** |

**The idle timeout runs before the first event.** A local engine
prefilling Codex's ~10k-token first prompt on a processor can take longer
than five minutes, and each retry starts the prefill again. So this door
opens the stream as soon as routing has chosen a backend and sends
`response.in_progress` every ten seconds until output arrives.

## Not measured

The OpenAI Agents SDK, and any Responses client other than Codex CLI.
Codex's own auto-compaction against a custom provider. A real reasoning
model's summary display. How Codex behaves across a network rather than
loopback.
