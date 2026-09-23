# API compatibility

This describes development builds after A4 implementation, not the frozen `v0.1.0-alpha.1`.
Compatibility means the features below, not every feature of a provider API.

| Surface or feature | Status | Boundary |
| --- | --- | --- |
| `GET /v1/models` | Supported | Eugene's discovered models and routing aliases. |
| `POST /v1/chat/completions` | Supported | Text messages, tools, structured-output forwarding, batch responses and SSE. |
| `POST /v1/messages` | Supported subset | Anthropic text/tool translation; measured Claude Code 2.1.207 shapes remain covered. |
| `POST /v1/embeddings` | Supported | Text inputs; requires an embedding-capable backend. |
| `POST /v1/systemone` | Experimental (B2, not in alpha.2) | TypeSafe System One typed decisions against decision-only backends. See [typed decisions](#typed-decisions-b2). |
| `/v1/responses`, audio, files, batches, provider storage | Not implemented | No Responses API or general provider endpoint parity. |
| OpenAI image/content-part input | Supported subset | Ordered text plus inline PNG/JPEG on user messages, confirmed vision backends only. See limits below. Anthropic images remain refused. |
| Tools and `response_format` | Forwarded | Definitions, JSON Schema and `strict` survive the wire. Backend support and schema enforcement vary; Eugene does not execute tools or post-validate output. |
| Reasoning output | Supported | A model's separately reported reasoning (llama.cpp `reasoning_content`, vLLM `reasoning`) is returned as `reasoning_content` on the OpenAI door and as `thinking` blocks on the Anthropic door when the request enabled thinking. See [reasoning](#reasoning). |
| `frequency_penalty`, `presence_penalty`, `top_k`, `min_p`, `parallel_tool_calls`, the `developer` role | Carried | Refused with 400 before 2026-09-23. Backends that cannot take one are routed around; see [chat settings](#chat-settings). |
| Reasoning effort, logit bias, log probabilities | Rejected on chat | Unsupported consequential settings return 400, including unknown nested message/tool/format fields. |
| All clients, providers and reasoning-token accounting | Unverified | Captured requests test transport semantics; they do not demonstrate every model's behavior. |

## Client authentication

Use a client key from Home's **Use it from your apps** card. Enrolled agents
manage one install-wide registry; all accepting gateways enforce its revocations.
Policy refresh is 15 seconds by default, with a 60-second maximum cache age
(plus up to five seconds clock tolerance). Stale or unavailable policy returns
client-only 503; operator repair access remains available. See
[client keys](client-keys.md) for migration and outage behavior.

## Chat settings

Use either `max_tokens` or `max_completion_tokens` with a positive JSON integer.
Both may be supplied only when their non-null values are equal. A conflict returns
400 naming `max_completion_tokens`; neither spelling overrides the other. Strings,
booleans, fractional numbers, integral floats, zero and negatives are rejected.
Null means unspecified. Normalization happens before routing/profile defaults.
Each fallback attempt retains the explicit limit; omitted limits use that
candidate's model profile, then the gateway's `defaultMaxTokens` (initially 2,048).

`temperature`, `top_p`, `seed`, up to four `stop` strings (or one string), `tools`,
`tool_choice`, `response_format`, `frequency_penalty`, `presence_penalty`,
`parallel_tool_calls` and the local-engine extensions `top_k` and `min_p` are
carried to the driver. Explicit controls are identified separately from inherited
defaults, allowing an adapter to reject a control it knows it cannot honor before
starting work — and a backend that does not advertise one is skipped when choosing
where to send the request. None of the five newer fields has a profile or install
default; an absent one stays absent, and `parallel_tool_calls` most of all, since
llama.cpp assumes false and OpenAI true. Streaming failures after HTTP headers
have been sent use an error frame; clients must inspect it.

A `developer` message is delivered to the backend as `system`, in place.
`reasoning_content` is accepted on an `assistant` message and handed back to the
backend (see [reasoning](#reasoning)); on any other role it is a 400.

`n: 1`, `logprobs: false` and `store: false` are accepted neutral defaults; other
non-null values are refused. `user`, string-valued `metadata` and
`safety_identifier` are ignored annotations, neither stored nor forwarded nor
used as authenticated identity. Unknown fields are refused even when null.
The gateway does not include prompt content or invalid values in validation errors.

With `stream: true`, `stream_options.include_usage: true` produces a final
usage-only chunk when the driver reports usage. False omits usage. Omitting
`stream_options` preserves Eugene's older final choice chunk containing usage.
This option does not change retained metrics. Token counts are not invented when
a backend supplies none.

## Engines and token accounting

| Adapter/backend | Limit behavior | Other controls |
| --- | --- | --- |
| `openai_compat_http`, local llama.cpp/vLLM or other compatible servers | Sends normalized `maxTokens` as upstream `max_tokens`. | Forwards sampling (including `top_k`, `min_p`, both penalties), stop, tools, `parallel_tool_calls` and response format, and an assistant turn's reasoning as `reasoning_content`. The server validates and enforces what it supports. Measured on llama.cpp b10948; vLLM from its 0.29 source; Ollama's handling of `top_k`/`min_p` unverified. |
| `openai_compat_http`, configured OpenAI endpoint | Sends upstream `max_completion_tokens`. | Explicit `top_k`/`min_p` are refused (OpenAI rejects them); the fixed-temperature model rule also refuses explicit temperature/top-p and both penalties; inherited defaults are omitted. History reasoning is not sent. Other supported fields are forwarded. |
| `claude_code_cli`, `codex_cli` | An explicit limit is refused; these harnesses do not expose this knob through Eugene's adapter. | Explicit sampling (all of it), stop, `parallel_tool_calls` and response-format controls are also refused. Calls without explicit controls retain harness/profile-default behavior; no deterministic sampling or token cap is promised. No reasoning is returned. |

The two public limit spellings express one Eugene generation limit, not two
different budgets. OpenAI documents its completion limit as including reasoning
tokens as well as visible output. That does not establish identical accounting
in local engines or CLI harnesses. No universal visible-output or reasoning-token
cap has been measured here. [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)

## Anthropic compatibility concessions

`/v1/messages` requires a positive integer `max_tokens`. It carries text, tool
definitions/results, temperature, top-p, `top_k`, stop sequences and
`tool_choice.disable_parallel_tool_use` into the same routing path. Images,
documents, hosted tools, `mcp_servers`, any `output_config` key other than
`effort` (structured output's `format` included) and unknown top-level settings
receive explicit refusals. The measured Claude Code request includes `thinking`,
`context_management`, `output_config.effort` and cache hints even when pointed at
local models. `context_management`, `output_config.effort` and cache hints remain
accepted, but **are not enforced**;
`thinking` decides whether reasoning is returned (below), but a `budget_tokens` is
not enforced and `disabled` hides reasoning without stopping the model thinking.
Both streaming and ordinary responses list controls that were not honoured in
`x-eugene-plexus-ignored-settings`. Metadata remains an ignored annotation.
`stop_sequence` names the matched sequence when the backend reports it (vLLM
does; llama.cpp does not, so behind llama.cpp `stop_reason` reads `end_turn`).
When the backend reports cached prompt tokens, they are `cache_read_input_tokens`
and `input_tokens` is the remainder, so the three input fields sum to the prompt.
This is not native Anthropic reasoning, caching or context editing; consumers
requiring those guarantees should not use this compatibility subset. Historical
measurements remain in [the Claude Code capture](acceptance/anthropic-messages-measurement.md).

## Reasoning

A reasoning model's thinking, when its backend reports it apart from the answer
(llama.cpp's default `reasoning_content`, vLLM's `reasoning` with a reasoning
parser), is returned to the caller. Before 2026-09-23 it was discarded, so a model
that thought until `max_tokens` answered with an empty `content`.

- **OpenAI door:** `message.reasoning_content` on a batch response,
  `delta.reasoning_content` frames ahead of the answer on a stream. Absent when
  there was none. Send the assistant message back unchanged and the reasoning goes
  back to the backend, which llama.cpp renders into the prompt for templates that
  keep it (Qwen3, gpt-oss).
- **Anthropic door:** a `thinking` block ahead of the answer, streamed as
  `thinking_delta`, **only** when the request's `thinking` is non-null and not
  `disabled`. `display: "omitted"` — which Claude Code sends on every request —
  returns the block with empty text and the reasoning carried in `signature` as
  `eugene-plexus-reasoning-v1:<base64>`; echoing the block back returns it to the
  model. That signature is Eugene's, not Anthropic's. `redacted_thinking` and
  foreign signatures are ignored.
- **Either door:** reasoning is output, so its first fragment is the streaming
  commit point — no failover after the caller has seen the model think. A driver
  whose `thinkingMode` is `off` returns none. Usage carries
  `completion_tokens_details.reasoning_tokens` only where the backend counts it
  (vLLM); llama.cpp does not, and Eugene does not estimate it.

Update gateway and inference-driver together when adopting A2. Older drivers do
not understand caller-setting provenance. Contract/unit checks and isolated HTTP
acceptance establish forwarding and refusals; live provider enforcement and newer
client versions remain unverified.


## Image input (A4)

Use OpenAI chat user content parts of type `text` and `image_url`, with an
inline `data:image/png;base64,...` or `data:image/jpeg;base64,...` URL. The gateway
never fetches remote URLs, local paths or file IDs. Images on system, assistant
or tool messages, animation, other formats, and explicit `detail: high/low` are
refused. Omitted detail and `auto` are accepted. Text-only arrays are joined in
order; arrays containing images remain structured through every routing attempt.

Limits cover the entire conversation, including images in earlier turns:

- Four images per request, each at most 5 MiB decoded; 10 MiB decoded total.
- At most 16 million pixels per image and 8192 pixels along either dimension.
- At most 16 MiB for the JSON body, including text and base64 overhead.

The gateway and direct driver validate the file type and image bounds. Invalid
images return a field-specific refusal; oversized HTTP bodies return 413 before
JSON parsing. Image payloads are excluded from driver debug logs and upstream
error excerpts.

`x_eugene_plexus.image_input` on `GET /v1/models` means at least one candidate
confirms vision support. Image requests use only those candidates; text-only
fallbacks are skipped. The driver rechecks the loaded model before forwarding.
Initially verified capability discovery is the single-model llama.cpp server's
`/props` vision modality plus matching `/v1/models` identity. Other engines and
multi-model endpoints do not yet advertise image input, even if they could
support it outside Eugene. Unknown capability is not a promise.

See [application setup](application-workflows.md) for the named client paths.

## Typed decisions (B2)

`POST /v1/systemone` accepts the TypeSafe System One request as pinned on
2026-09-22: `model` (an Eugene alias), `state` (string, object or array) and
`questions`, a map of names to `noul`, `choice` or `score` questions. Answers use
TypeSafe's field names, keyed by your question names; `usage` reports
`input_tokens`/`output_tokens` only when the backend reports them. A TypeSafe
client changes its base URL and nothing else. Client keys, revocation, model
scopes, local-only policy and per-key limits apply as on the other doors.
[Design and pins](design/decision-models.md)

Refused before any backend work: more than `decisionMaxQuestions` questions
(gateway config, default 32), a `choice` with other than 1-255 options, a
`score` with other than 2-10 levels, a question field the protocol does not
define, and the shared body-size limit. Malformed questions return 422, as
TypeSafe does.

A backend answer is checked before it is returned: every question answered once
with its own type, choices drawn from the request's options, distributions of
finite numbers in [0, 1] summing to 1, scores inside the scale. Anything else is a
502 naming the defect. Eugene never repairs a decision or substitutes a chat
model prompted for JSON. Probabilities and `confidence` are the provider's own
calibration, not comparable across models.

Non-streaming only. Decision models refuse chat and embeddings with a 400 naming
`/v1/systemone`; chat models refuse decisions with a 400 naming
`/v1/chat/completions`. A deadline that fires is a 504 with an uncertain outcome:
the same decision is **not** re-sent to another backend. A backend that holds one
request at a time answers 503 while busy rather than queueing, and a client that
disconnects does not free it until its work finishes. Disable automatic retries
in any SDK you use; a retried decision is a second decision.

| Backend | Status |
| --- | --- |
| Kev (`jaredpalmer/kev-0.8b`), supervised by the agent | **Measured** on WSL2 CPU ([run](acceptance/decision-run.md)); CUDA, ROCm, Metal unverified |
| Another System One server (`systemone_custom`) | Supported when it passes the answer checks above; see [the recipe](application-workflows.md#register-another-system-one-server) |
| Hosted Jev (`typesafe`) | **Unverified** — fixture tests only; always external, refused to local-only keys, never a fallback for a local model |
| Vercel `/v1/evaluate`, AI SDK evaluation | Not implemented — a different dialect |

Decision requests are not yet rows in `GET /v1/metrics`.
