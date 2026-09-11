# The CLI subscription backends, through the gateway

**Status:** run 2026-09-10 (latest). **Claude Code: works.** **Codex:
blocked on the operator's CLI auth, not on anything here.** Script:
[`scripts/cli-backend-check.sh`](../../scripts/cli-backend-check.sh).

Differentiator #7 is not only "many local backends at once". It is
**"one endpoint over local models AND the subscriptions the user already
pays for"** — and that half had never been exercised under the control
plane. `claude_code_cli` and `codex_cli` date from the v0.2
consciousness era; no acceptance script mentioned either.

```
agent :8079 --spawns--> gateway :8080
            --spawns--> claude-cli :8094 -> `claude` (subscription)
            --spawns--> codex-cli  :8095 -> `codex`  (subscription)
```

---

## Claude Code: end to end

```
/v1/info : ('claude_code_cli', 'claude-sonnet-4-5', 'claude_subscription')
gateway lists: ['claude-sonnet-4-5', 'gpt-5']

completion: "ready"
routing   : driver=claude-cli backend=claude_code_cli latency_ms=4086 tier=1
usage     : prompt_tokens=31121  completion_tokens=45
metrics   : reqs=1  p50=4086ms  tps=11.0  overhead=6ms
```

A subprocess backend with no HTTP endpoint of its own, routed to by the
same gateway that serves llama.cpp and Ollama, recorded by the same
metrics, attributed to `claude_code_cli` rather than to an HTTP kind.

### 31,000 prompt tokens for a one-line prompt

The prompt was `Reply with exactly one word: ready`. It cost **31,121
prompt tokens**.

That is Claude Code's own system prompt and harness, and it is the
single most important operational fact about this backend. It is not a
thin proxy to the model; it is a coding agent that happens to answer.
Consequences an operator should know before routing traffic here:

- **Cost and quota per request are roughly fixed and large**, almost
  independent of the prompt. A short question is not a cheap one.
- **Throughput figures for this backend are not comparable** to a local
  engine's. 11 tok/s here is 45 completion tokens over 4.1 s that
  included processing 31k of prompt.
- It is a reasonable **fallback tier** and a poor default tier, which is
  exactly what `modelSlots` is for.

### The docs were wrong, and this settles it

Earlier the same day, the M8 contract prose claimed "the CLI
subscription backends report no token counts, ever" — inherited from
`CompletionUsage`, which had said "the CLI subprocess backends generally
do not" since an earlier milestone. That was corrected by **reading**
the mappers. This run confirms it by **running** them: usage came back
populated.

The nullable design stands and its stated reason is now right: absence
of usage is a per-request fact, not a property of a backend kind.

---

## Codex: the operator's CLI is not signed in

```
codex exited 1: Failed to refresh token: 401 Unauthorized
  "Your refresh token has already been used to generate a new access
   token. Please try signing in again."
```

**Not a defect here.** The driver spawned the CLI, the CLI refused to
authenticate, and the failure travelled back correctly: a 502 through
the gateway, an `error` row, `backend: codex_cli`, the error class and
not the message. Re-running `codex login` is the fix, and the check is
worth re-running afterwards because `codex_cli` remains genuinely
unproven.

---

## What the failure found in our own code

**A request no backend served was attributed to nobody.** The summary
joined on the serving attempt, so an all-failed request landed in a
group with a null driver and a null backend:

```
claude-cli   backend=claude_code_cli    reqs=1 p50=4086ms tps=11.0 overhead=6ms
None         backend=None               reqs=1 p50=4347ms tps=unreported overhead=unreported
```

"Is anything failing" is one of the five questions the endpoint exists
for, and it could be answered with a count but not with a name. Fixed in
gateway `29dd606`: a request is attributed to the attempt that served
it, or to the last one tried when none did.

Worth noting how it hid. Every fixture in the suite that produces an
error produces it from a driver that is also the *only* driver, so the
group had a name by coincidence. **It took a real backend failing for a
real reason.**

## And a lead on the 116 ms

The same table narrows the open overhead question sharply:

| backend | control-plane overhead |
|---|---|
| Ollama, over `openai_compat_http` | **116 ms** |
| Claude Code, over `claude_code_cli` | **6 ms** |

The control plane is not uniformly slow. A subprocess backend measured
through the same subtraction shows 6 ms, so the ~110 ms difference is
**specific to the HTTP driver path** — either `httpx`'s
`response.elapsed` not covering the body read, or work the HTTP engine
does after it. That is a much smaller haystack than "somewhere in the
control plane", and it came free with a test aimed at something else.
