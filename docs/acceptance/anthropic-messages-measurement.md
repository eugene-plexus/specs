# R4 step one — what a real Claude Code actually sends

**Measured 2026-09-19 against Claude Code `2.1.207` (agent-sdk `0.3.274`,
`@anthropic-ai/sdk` `0.94.0`, node `v26.3.0`, Windows x64), on this box.**
Instrument: [`scripts/r4-capture.py`](../../scripts/r4-capture.py), a throwaway
loopback listener that records every request byte for byte and speaks just
enough of the Anthropic Messages wire for a real turn to complete. Nine runs:
three credential paths, one tool loop, seven HTTP statuses.

This is the step the roadmap put in front of the code, because **the premise
the whole auth half of R4 rests on was upstream client behaviour that had been
reasoned about and never captured**. It was right, and four things beside it
were not — two of which would have made the shim fail on the first request from
the only client it exists for.

---

## 0. Why this was measured rather than reasoned

This project has a standing record of reasoning about somebody else's wire and
being wrong: the hub answers **401** for a repo that does not exist, not 404
(S6); llama.cpp's two cudart archives are named differently (S10); Ollama's
resolved context window appears only on `/api/ps` (step 7); `full=true` and
`expand[]` are mutually destructive (S6 §6.5). Each was a claim held with
confidence until something dialled the real thing.

**The isolation matters and is the first finding.** A capture taken without an
isolated `CLAUDE_CONFIG_DIR` records the operator's own live Anthropic
credential, not the key under test — see §1.3. The instrument redacts what it
recognises on the way to disk; the isolation is what makes the reading true.

---

## 1. The auth answer

### 1.1 `ANTHROPIC_API_KEY` → `x-api-key`, and no `Authorization` at all

```
POST /v1/messages?beta=true HTTP/1.1
Accept: application/json
Content-Type: application/json
User-Agent: claude-cli/2.1.207 (external, claude-vscode, agent-sdk/0.3.274)
X-Claude-Code-Session-Id: 55207bfa-f77e-4240-8526-074e05bbe229
anthropic-beta: claude-code-20250219,interleaved-thinking-2025-05-14,thinking-token-count-2026-05-13,context-management-2025-06-27,prompt-caching-scope-2026-01-05
anthropic-dangerous-direct-browser-access: true
anthropic-version: 2023-06-01
x-api-key: ep-capture-apikey-000000000003
x-app: cli
```

**The roadmap's premise is confirmed, and it is stronger than it was written.**
It is not that Claude Code sends `x-api-key` *as well*; there is **no
`Authorization` header on the request at all**. The gateway's
`HTTPBearer(auto_error=False)` in `gateway/dependencies.py:32` reads only
`Authorization`, so a shim wired to the existing dependency does not merely
prefer the wrong header — it sees no credential whatsoever and refuses with the
401 that §4 shows is the single worst status we could return.

### 1.2 `ANTHROPIC_AUTH_TOKEN` → `Authorization: Bearer`, and no `x-api-key`

The same run with `ANTHROPIC_AUTH_TOKEN=ep-capture-token-0002` and no API key:

```
Authorization: Bearer ep-capture-token-0002
```

So the two variables are **disjoint, not layered**. Supporting both headers is
required, and the recipe can use either — but see §5 for which one it should
name.

### 1.3 An ambient OAuth login beats `ANTHROPIC_API_KEY`, and sends a real Anthropic token to whatever `ANTHROPIC_BASE_URL` names

The first run of this measurement was taken with the operator's ordinary
config dir and `ANTHROPIC_API_KEY` set. What arrived was:

```
Authorization: Bearer sk-ant-oat01-<REDACTED-LIVE-CREDENTIAL>
anthropic-beta: claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14,thinking-token-count-2026-05-13,context-management-2025-06-27,prompt-caching-scope-2026-01-05,extended-cache-ttl-2025-04-11
```

**`ANTHROPIC_API_KEY` was ignored.** A subscription OAuth token was sent
instead, to a listener on `127.0.0.1`, because that is where `ANTHROPIC_BASE_URL`
pointed. Note the beta list also changes: `oauth-2025-04-20` and
`extended-cache-ttl-2025-04-11` appear only on this path, and the extended TTL
changes the `cache_control` shape on the wire (§2.2).

This is a fact about the recipe we are about to publish, not about our code. A
user who is signed in to a Claude subscription, follows our instructions, sets
`ANTHROPIC_BASE_URL` at our gateway and `ANTHROPIC_API_KEY` to an Eugene Plexus
client key **will send their Anthropic OAuth token to our gateway, and to
whatever their gateway's tailnet neighbours can see**, while the client key
they minted is never used. The token is theirs and the gateway is theirs, so
nothing is stolen — but the recipe must not quietly arrange it, and the
troubleshooting line "it still says my key is wrong" has this as its commonest
cause.

### 1.4 `ANTHROPIC_API_KEY` alone does not work at all in a fresh profile

```
$ CLAUDE_CONFIG_DIR=<fresh> ANTHROPIC_API_KEY=<key> claude -p "..."
Not logged in · Please run /login
```

The key must be **approved** first. Approval is recorded in
`$CLAUDE_CONFIG_DIR/.claude.json` as
`customApiKeyResponses.approved`, holding the key's **last 20 characters** —
which is also why a key shorter than 20 characters cannot be approved this way.
Interactively, Claude Code asks once and remembers.

`ANTHROPIC_AUTH_TOKEN` needs no approval step (§1.2). **That asymmetry decides
the recipe** — see §5.

---

## 2. The request shape

### 2.1 Every request, every run

| Field | Observed |
| --- | --- |
| path | `POST /v1/messages?beta=true` — **a query parameter**, on every single request |
| `anthropic-version` | `2023-06-01` |
| `stream` | **`true`, always** — nine of nine requests |
| `max_tokens` | `32000`, always present |
| `model` | passed through verbatim, **including an arbitrary local id** (§2.3) |
| `metadata.user_id` | a JSON *string* containing `device_id`, `account_uuid`, `session_id` |
| `context_management` | `{"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]}` |
| `tools` | 23 on a default run, each `{name, description, input_schema}` |
| `tool_choice` | absent |
| `top_p`, `top_k`, `stop_sequences`, `mcp_servers`, `service_tier` | **never sent** |
| body size | 126–128 KB on a one-line prompt |

A preceding **`HEAD /`** probe arrives from `Bun/1.4.0` (not the SDK) before the
first POST. **It is not load-bearing**: a run in which the probe was answered
`404` completed normally. We do not need to serve it.

### 2.2 `cache_control` is on three blocks, and its shape varies

Three occurrences per request: system block 1, system block 2, and **the last
user content block**. In the OAuth run it carries
`{"type": "ephemeral", "ttl": "1h"}`; on the api-key path, plain
`{"type": "ephemeral"}` — because `extended-cache-ttl-2025-04-11` is only
negotiated on the OAuth path.

The roadmap already had this one right and called it load-bearing: a blanket
unknown-field refusal passes every refusal test and then fails on the first
real request. **The correction is that it is not only on system blocks** —
dropping it must be done per block wherever a block can carry it, including
`tool_result` (§3).

System block 0 is a **billing header smuggled as prose**:
`x-anthropic-billing-header: cc_version=2.1.207.d35; cc_entrypoint=claude-vscode;`
— 80 characters with no `cache_control`. It is inert to us, and it is the
reason a naive "the system prompt is `system[0]`" read is wrong.

### 2.3 **`thinking` is sent on every request, and R4 planned to refuse it**

This is the finding that changes the slice. Four runs, four shapes:

| run | `thinking` |
| --- | --- |
| `--model claude-sonnet-4-5-20250929` | `{"budget_tokens": 31999, "type": "enabled", "display": "omitted"}` |
| `--model qwen3-8b` (an arbitrary local id) | `{"type": "adaptive", "display": "omitted"}` |
| `--model qwen3-8b`, `MAX_THINKING_TOKENS=0` | `null` — **the key is still present** |
| never | absent |

R4 as written refuses `thinking` with a 400 naming the field. **The default
request from a user pointing Claude Code at a local model id carries
`thinking: {"type": "adaptive"}`**, so that refusal fires on request one, for
everybody, and the shim 400s the only client it was built for. It is exactly
the `cache_control` trap the roadmap identified, one field over, and the
roadmap put `thinking` on the other side of the line.

And a presence check is not enough either: with `MAX_THINKING_TOKENS=0` the key
is present with the value `null`, so `if "thinking" in body: refuse` refuses the
one configuration that is genuinely asking for no thinking.

**`thinking` is dropped, not refused** — and dropping it is honest, because
`ThinkingFilter` already exists on the driver side and `thinkingMode` is a
profile setting; a local model's thinking behaviour is ours to control, not the
caller's. Worth one line in the docs as a real loss, beside `top_k`.

---

## 3. The tool loop, and our own stream framing

A run in which the listener answered turn one with a **streamed, fragmented**
`tool_use` for `Glob`: Claude Code parsed it, ran the tool, and sent turn two.
The whole loop completed and printed the final answer.

**That is a result about our translator, not only about the client.** The SSE
framing in the instrument — `message_start`, `content_block_start`,
`input_json_delta` in two fragments, `content_block_stop`, `message_delta` with
`stop_reason: "tool_use"`, `message_stop`, with text at index 0 and the tool at
index 1 — was accepted by a strict SDK. R4's hardest piece is stateful block
indexing, and this is a worked reference for it that came from a real client
rather than from the docs.

The `tool_result` that came back:

```json
{
  "role": "user",
  "content": [
    {
      "tool_use_id": "toolu_r4_capture_0001",
      "type": "tool_result",
      "content": "alpha.py\nbeta.py",
      "cache_control": {"type": "ephemeral"}
    }
  ]
}
```

Three things the translator has to handle that a request-only capture would not
have shown:

1. **A tool result is a block inside a `user` message**, not a role of its own —
   so the inbound mapping to our `tool` role has to look inside user content,
   and one user message can hold several results.
2. **The assistant turn is echoed back to us** as `text` + `tool_use` blocks, so
   the translator needs an inbound assistant→`tool_calls` mapping as well as the
   outbound one. R4's scope named the outbound half only.
3. **`cache_control` rides on `tool_result` too** (§2.2).

`content` here is a plain string. The Anthropic schema also allows a list of
blocks, and a client that sends images in a tool result is the case we refuse.

---

## 4. The error table, which decides our status codes

Each status answered with an Anthropic-shaped error body; the column that
matters is what the *client* then did.

| we answer | attempts | what the user sees |
| --- | --- | --- |
| **400** | 1 | `API Error: 400 <our message>` — **verbatim** |
| **401** | **unbounded** — 9 in 79 s, still climbing at 100 s | **nothing.** Silent hang |
| **403** | 1 | `Failed to authenticate. API Error: 403 <our message>` — **verbatim** |
| **404** | 2 | `There's an issue with the selected model (qwen3-8b). It may not exist or you may not have access to it.` — **our message is discarded** |
| **429** | 7 in 45 s | nothing |
| **500** | 7 in 45 s | nothing |
| **503** | 7 in 45 s | nothing |

**`X-Stainless-Retry-Count` stayed `0` on every single retry**, including the
ninth. A server cannot use it to detect a retry storm; it is not a counter of
what we are being subjected to.

Three consequences, and the first one inverts an ordinary design choice:

**A bad or revoked client key must be answered 403, not 401.** 401 is what
every other route in this project returns for a bad bearer
(`gateway/dependencies.py:61,76,107`) and it is, on this door, an invisible
infinite retry loop against our gateway — the looping symptom step 7 was built
to remove, one layer up, in the client we are courting. 403 names the reason on
the first attempt in the user's terminal. This is a deliberate divergence
between the two front doors and it needs saying in the contract, or the next
reader will "fix" it back.

**A 404 for "no backend serves this model" loses its text.** The gateway's
no-models 404 says useful things — including `503 Locked` when the control root
is sealed, which was built precisely so that surface would stop naming two
healthy places and never mention the root. Claude Code throws it away and
blames the model. On this door that refusal should be a **400** so the
explanation survives.

**429/500/503 are retried and silent**, which is tolerable — a cascade failure
should be retried — but it means a user whose every backend is down sees a hang,
not a message. Worth a line in the recipe's troubleshooting.

---

## 5. What this changes in R4

1. **Accept `x-api-key` and `Authorization: Bearer`, and treat them as
   alternatives.** Not a fallback ordering: neither run sent both.
2. **`thinking` moves from the refusal list to the drop list** (§2.3), and the
   drop must survive `thinking: null`.
3. **`cache_control` is dropped per block, including `tool_result`** — not just
   on system blocks.
4. **A bad key is 403.** A model nothing serves is 400, not 404.
5. **`?beta=true` must not break routing**, and the route must tolerate an
   unknown `anthropic-beta` list rather than validating it.
6. **The recipe should name `ANTHROPIC_AUTH_TOKEN`, not `ANTHROPIC_API_KEY`** —
   it needs no approval step (§1.4) and it is not silently overridden by an
   ambient subscription login (§1.3). Name `ANTHROPIC_API_KEY` second, with
   both caveats, because it is the variable everyone will reach for first.
7. **Inbound assistant `tool_use` blocks need a mapping**, which the scope had
   not named (§3).
8. **The non-streaming path is never exercised by Claude Code** — every request
   is `stream: true`. It still has to work for other clients, and the acceptance
   run should not assume Claude Code covers it.
9. **`HEAD /` need not be served.**

None of this changes the slice's shape: translate at the edge into
`ChatCompletionRequest`, share `_serve()`, keep the envelope in headers. It
changes the refusal list, the status table, and the recipe.

---

## 6. What was not measured

- **No `/v1/messages/count_tokens` request was ever seen.** It may appear on
  longer sessions; nothing here says it does not exist.
- **Only Claude Code.** The Anthropic SDKs, `claude-code-router`, Cline's
  Anthropic mode and OpenCode all speak this wire and none of them was pointed
  at the listener.
- **No image, document, or `thinking` *response* content** — the instrument
  never emitted a `thinking` block, so a client's handling of one is untested.
- **No real backend.** Every answer came from the instrument, so nothing here
  measures translation of a real local model's output.
- **The 401 loop was never allowed to terminate.** It was still retrying when
  the run's 100 s timeout fired, so "unbounded" is a lower bound of nine
  attempts, not a proof that it never gives up.
