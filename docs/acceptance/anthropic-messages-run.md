# R4 — a real Claude Code, pointed at a real gateway

**Run 2026-09-19 on this box.** Claude Code `2.1.207` → the real
`eugene-plexus-gateway` on 8180 → a stub agent on 8179 and a stub driver on
8181 ([`scripts/r4-stubs.py`](../../scripts/r4-stubs.py)). Auth **on**: a real
HS256 signing key, a real `aud: client` token with a `jti`.

**The result: the loop completes.** `claude -p "list the python files here"
--model local-qwen --allowedTools Glob` printed its answer and exited 0, having
called a tool through our gateway and read the result back. The assertions
below are taken from **the driver's own record on disk**, not from Claude
Code's account of itself.

---

## 0. Why the stubs are on the outside

Everything around the gateway is a stub and the gateway is real, which is the
opposite of this project's usual acceptance arrangement. The question this run
asks is whether a real Anthropic client can drive a real gateway; a real engine
would add minutes of model loading to every iteration while answering no part
of it. What the stubs implement is only what `RoutingTable` and `DriverClient`
actually read.

**The driver fragments its tool-call arguments across two frames**, because a
stub that emitted a whole call in one frame would pass every assertion a broken
accumulator also passes — which is the defect step 6's first acceptance run
shipped with, one protocol down.

---

## 1. What the run proved

**The premise, on a real socket rather than in a document.** With the same
client-key token:

```
GET  /v1/models    -H "x-api-key: <token>"        → 401 "Missing token"
GET  /v1/models    -H "Authorization: Bearer …"   → 200
POST /v1/messages  -H "x-api-key: <token>"        → 200
POST /v1/messages  (no credential)                → 403
```

The 401 on the first line is the existing door reading only `Authorization`, so
"a shim wired to the existing dependency would see no credential" is now a
demonstration rather than a claim.

**The tool loop, from `driver-requests.jsonl`:**

```
=== driver call 1: /v1/generate/stream
    top-level keys: ['maxTokens', 'messages', 'temperature', 'tools']
      system | 'x-anthropic-billing-header: cc_version=2.1.207.881...'
      user   | '<system-reminder>…'
      system | 'Available agent types for the Agent tool:…'
    tools: Agent, Bash, CronCreate, CronDelete, CronList, Edit, … (23)

=== driver call 2: /v1/generate/stream
      system | 'x-anthropic-billing-header: …'
      user   | '<system-reminder>…'
      system | 'Available agent types …'
      assistant | None | toolCalls=True
      tool      | 'alpha.py\nbeta.py' | toolCallId=call_stub_1
```

Six things are asserted there at once, and the first is the one a status code
could never show:

1. **The request the backend received has exactly four top-level keys** —
   `maxTokens`, `messages`, `temperature`, `tools`. So `thinking`,
   `cache_control`, `metadata` and `context_management` demonstrably never
   reached a backend, rather than being refused or forwarded.
2. The three system blocks were concatenated, billing header included.
3. The in-message `system` block kept its position after the user turn (§3).
4. 23 tool definitions were translated into the OpenAI function shape.
5. The assistant turn came back as `content=None` with `toolCalls` set — the
   single most common assistant turn in an agent loop, and the one whose schema
   step 6 had to loosen.
6. **The `tool_result` arrived as a `tool` role message** carrying
   `toolCallId=call_stub_1` and the real `Glob` output. Anthropic has no `tool`
   role; getting this wrong turns the tool's output into the human speaking.

**And `GET /v1/metrics` sees this door**, which is the shared-path claim proved
rather than asserted:

```
rows: 3
   local-qwen local-qwen streamed=True  outcome=served attempts=1
   local-qwen local-qwen streamed=True  outcome=served attempts=1
   local-qwen local-qwen streamed=False outcome=served attempts=1
```

A door that had re-implemented routing would be invisible there. That is M8's
finding — *the response envelope is the wrong recording point, and the
streaming path was not it* — arriving in a new place, and `_prepare` existing
is what stopped it.

---

## 2. The run's finding, and it is about how it was found

**The first execution failed, on the client's very first request:**

```
API Error: 400 messages.1.role: Input should be 'user' or 'assistant'
```

Claude Code sends a **`system`-role message inside `messages`** — 8,356
characters, positioned after the first user turn — *in addition to* the
documented top-level `system`. Anthropic documents two message roles; the
contract said two; a real client sends three.

**43 green unit tests did not see it**, and the reason is exact rather than
sloppy: every fixture in `test_anthropic_messages.py` was built from the
step-one capture of a *simple* request, and this shape appears only once tools
are in play. The measurement was right about everything it covered and this was
outside it.

Fixed in the contract (`specs` `eb05ec7`) rather than with a hand-written
guard, after which **the translation needed no change at all** — which is the
argument for putting a measured shape in the schema. Recorded as §7 of
[`anthropic-messages-measurement.md`](anthropic-messages-measurement.md), and
as a unit test that now carries the real shape.

---

## 3. Not done, named

- **No real engine.** Every answer came from the stub, so nothing here measures
  the translation of a real local model's output — a model that emits a
  `<think>` block, or malformed tool arguments, has not met this door.
- **No second client.** The Anthropic SDKs, `claude-code-router` and Cline's
  Anthropic mode all speak this wire and none of them was pointed at it.
- **The refusals were not exercised live.** Images, documents, `mcp_servers`
  and a fifth `stop_sequence` are unit-tested only; no real client was made to
  send one.
- **The 403 was exercised with no credential, not with a revoked one.** The
  revocation guard's live path needs a real agent serving
  `/v1/auth/client-keys/revoked`.
- **No browser.** `/v1/messages` joined the CORS front door and no page has
  made a preflight to it.
- **The UI recipe is not built.** Home's *Use it from your apps* still has
  seven recipes and the test asserting Claude Code's absence still passes. That
  is R4's second half, and until it lands the door exists and nothing tells
  anybody how to use it.
