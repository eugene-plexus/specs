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

## 4. The sabotage pass — 30 of 30

`scripts/r4-sabotage.py`, second execution. Two groups. **The first puts back
R4 as designed before the measurement corrected it** — refuse `thinking`,
refuse it by presence, 401 for a bad key, 404 for an unknown model, read only
one auth header — so the measurement lives somewhere a regression trips over it
rather than only in prose. The second takes the translation apart one property
at a time.

**Three escaped on the first pass and each named something different.**

**(a) A missing check, not a weak fix.** A text block left open when a tool
block opens escaped *both* streaming tests: one streams only text and the other
only tool calls, so the nesting assertion never met a second block and the index
assertion never met an open text one. Each was correct about its own case and
neither covered the seam. A third test drives the translator across it directly,
because the fake answers with tool calls *or* text and cannot produce the shape.

**(b) A sabotage that sabotaged nothing.** `headers={} or envelope_headers(…)`
returns the right-hand side, because `{}` is falsy. It escaped because the code
was unchanged.

**(c) A claim in this slice's own contract, disproved.** The contract and the
code comment beside it said a default allow-list without `x-api-key` would
"answer the preflight and then fail the request". It would not: the middleware
**echoes** `access-control-request-headers` whenever a preflight sends one, and
a real browser always does. Removing `x-api-key` from the default changed no
browser outcome at all — which is exactly why nothing caught it. Both now say
the list is a fallback that agrees with the surface rather than the mechanism,
and a test covers the preflight that names no headers.

**The harness needed fixing twice before it could be believed, and the baseline
assertion caught both.** Vitest started from `cmd` — as `shell=True`, as
`cmd /c npx …`, as `cmd /c npm run test` — fails inside its own setup file with
*"Vitest failed to find the current suite"*, while the identical command from
bash passes 22 tests; three invocations reported a healthy gate as broken. And
printing a failing gate's output crashed on this box's cp1252 stdout, on the one
path that matters. Without the baseline, every sabotage would have read *caught*
for the wrong reason.

---

## 5. What R4 still owes

There is **no numbered acceptance script** for this slice. §1's results came
from a hand-driven live run against `scripts/r4-stubs.py`, which is reproducible
but is not `scripts/r4-acceptance.sh` with counted checks in the shape every
other slice here has. That is the honest gap, and it is the reason this document
says "the loop completes" rather than "20 PASS".

---

## 6. Not done, named

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
