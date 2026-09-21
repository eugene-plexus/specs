# API compatibility

This describes development builds after A2/A3, not the frozen `v0.1.0-alpha.1`.
Compatibility means the features below, not every feature of a provider API.

| Surface or feature | Status | Boundary |
| --- | --- | --- |
| `GET /v1/models` | Supported | Eugene's discovered models and routing aliases. |
| `POST /v1/chat/completions` | Supported | Text messages, tools, structured-output forwarding, batch responses and SSE. |
| `POST /v1/messages` | Supported subset | Anthropic text/tool translation; measured Claude Code 2.1.207 shapes remain covered. |
| `POST /v1/embeddings` | Supported | Text inputs; requires an embedding-capable backend. |
| `/v1/responses`, audio, files, batches, provider storage | Not implemented | No Responses API or general provider endpoint parity. |
| Images/content-part arrays | Rejected | Image support and acceptance are A4. Do not send an image expecting a text-only approximation. |
| Tools and `response_format` | Forwarded | Definitions, JSON Schema and `strict` survive the wire. Backend support and schema enforcement vary; Eugene does not execute tools or post-validate output. |
| Reasoning effort, penalties, logit bias, parallel-tool control, log probabilities | Rejected on chat | Unsupported consequential settings return 400, including unknown nested message/tool/format fields. |
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
`tool_choice` and `response_format` are carried to the driver. Explicit controls
are identified separately from inherited defaults, allowing an adapter to reject
a control it knows it cannot honor before starting work. Streaming failures after
HTTP headers have been sent use an error frame; clients must inspect it.

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
| `openai_compat_http`, local llama.cpp/vLLM or other compatible servers | Sends normalized `maxTokens` as upstream `max_tokens`. | Forwards sampling, stop, tools and response format. The server validates and enforces what it supports. |
| `openai_compat_http`, configured OpenAI endpoint | Sends upstream `max_completion_tokens`. | The configured fixed-temperature model rule rejects explicit temperature/top-p; inherited defaults are omitted. Other supported fields are forwarded. |
| `claude_code_cli`, `codex_cli` | An explicit limit is refused; these harnesses do not expose this knob through Eugene's adapter. | Explicit sampling/stop/response-format controls are also refused. Calls without explicit controls retain harness/profile-default behavior; no deterministic sampling or token cap is promised. |

The two public limit spellings express one Eugene generation limit, not two
different budgets. OpenAI documents its completion limit as including reasoning
tokens as well as visible output. That does not establish identical accounting
in local engines or CLI harnesses. No universal visible-output or reasoning-token
cap has been measured here. [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)

## Anthropic compatibility concessions

`/v1/messages` requires a positive integer `max_tokens`. It carries text, tool
definitions/results, temperature, top-p and stop sequences into the same routing
path. Images, documents, hosted tools, `mcp_servers`, `top_k` and unknown top-level
settings receive explicit refusals. The measured Claude Code request includes
`thinking`, `context_management` and cache hints even when pointed at local models.
These remain accepted, but **are not enforced**. Both streaming and ordinary
responses list non-null ignored controls in `x-eugene-plexus-ignored-settings`.
Metadata remains an ignored annotation. This is not native Anthropic reasoning,
caching or context editing; consumers requiring those guarantees should not use
this compatibility subset. Historical measurements remain in
[the Claude Code capture](acceptance/anthropic-messages-measurement.md).

Update gateway and inference-driver together when adopting A2. Older drivers do
not understand caller-setting provenance. Contract/unit checks and isolated HTTP
acceptance establish forwarding and refusals; live provider enforcement and newer
client versions remain unverified.
