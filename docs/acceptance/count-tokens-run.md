# Anthropic `count_tokens` — counted, never generated

**Run 2026-09-23 on this box.** llama.cpp b10948 → the real
`eugene-plexus-inference-driver` (`0a1fc8c`) → the real `eugene-plexus-gateway`
(`004704d`) → `r4-stubs.py agent`, on two engines: Gemma 4 E4B (CPU, the
[images run](anthropic-images-run.md)'s) and Qwen3-0.6B (CPU). Plus a real
Claude Code 2.1.207 (agent-sdk 0.3.280).
[`scripts/count-tokens-acceptance.py`](../../scripts/count-tokens-acceptance.py):
**6 PASS on Gemma with Claude Code, 5 PASS on Qwen3, third execution.**
Contract `07e3c5a`. Both installers re-pinned (gateway `004704d`, driver
`0a1fc8c`); `ui` not re-pinned (no screen counts tokens).

## 0. Why it was built: measured

`/context` in Claude Code (run through `--input-format stream-json`; print mode
sends `/context` to the model as text) calls `POST /v1/messages/count_tokens?beta=true`
**13–14 times**, one body per category, beta `token-counting-2024-11-01`,
bodies `{model, messages, system?, tools?}` and no `max_tokens`. With the route
absent, **every 404 was followed at once by a real `POST /v1/messages` with
`max_tokens: 1`** on the same connection (read off the gateway's access log);
the engine evaluated prompts of up to 9,050 tokens for one output token each,
17.8 s apiece on this CPU. `/context` still printed the right table — the counts
were the engine's own — but one diagnostic command cost fourteen prefills,
would wake an idle-unloaded model, and left fourteen one-token rows in
`GET /v1/metrics`.

`r4-capture.py --count-status N` then measured what the refusal status does:

| `count_tokens` answered | `/context` did |
| --- | --- |
| 400, 403, 404 | tried each count **once**, then fell back to a generation |
| 501, 503 | **retried** each count, then fell back |

So every "cannot count" is a **400** — including a backend that is down.

## 1. The mechanism, measured before it was written

llama.cpp's `/apply-template` renders a chat-completions body into the prompt
the model would see, and `/tokenize` with `add_special: true` counts it.
Against the `prompt_tokens` of a one-token generation of the same request,
straight at the engine:

| Engine | plain | tools | tool loop / reasoning history turn |
| --- | --- | --- | --- |
| Gemma 4 E4B | 27 / 27 | 59 / 59 | 95 / 95 |
| Qwen3-0.6B | 24 / 24 | 147 / 147 | 21 / 21 |

`add_special: false` is one short on Gemma (the BOS the completion path adds).
An image renders as a `<__media_…__>` marker in the template, so a request with
one cannot be counted this way.

## 2. What was built

- **Driver `POST /v1/generate/count`**: the payload `/v1/generate` would send
  (`_payload_for` — thinking directive and every shaped setting included), to
  `/apply-template`, then `/tokenize`. 501 where the count could not be exact:
  an image, OpenAI's own API, any backend without the template endpoint (vLLM's
  own `/tokenize` has not been run here, so it is not trusted). A backend that
  is down or rejects the request is its usual 502 / 400.
- **Gateway `POST /v1/messages/count_tokens`**: translated exactly as
  `/v1/messages` translates it (same refusals), counted by a **ready** backend
  of the tier that would serve. **Never a wake**, never past the first tier
  that holds anything — another tier is another model, whose tokenizer answers
  a different question — and **never recorded**. Replicas are tried in order;
  a backend 400 is not re-asked. A client key is **checked, not admitted**: no
  reservation and no rate charge, since `/context` sends fourteen at once; its
  model scope and `localOnly` still apply, and the path joins client admission
  so a policy refusal comes back in Anthropic's envelope.

## 3. What the run proved

| # | Check | Gemma 4 E4B | Qwen3-0.6B |
| --- | --- | --- | --- |
| 2 | Each count equals the input tokens a one-token `/v1/messages` of the same body reports, through the same stack | 23/23, 70/70, 125/125, 5,455/5,455 | 15/15, 156/156, 199/199, 5,449/5,449 |
| 2 | …and no count left a metrics row | yes | yes |
| 3 | A count of a ~5,450-token prompt vs the prefill it replaces | **43 ms vs 10,690 ms** | 43 ms vs 1,046 ms |
| 4 | An image is a 400 naming why | yes | yes |
| 5 | A model nothing serves is a 400 naming it | yes | yes |
| 6 | **A real Claude Code `/context`** | 14 counts answered 200, **0 refused, 0 `/v1/messages`**, 0.8 s | — |

The cases: plain; a `/context` category (system + a tool); a tool loop with a
`thinking` block handed back; a long system prompt.

Sabotage: [`scripts/count-tokens-sabotage.py`](../../scripts/count-tokens-sabotage.py),
**19 of 19 caught** across both repos, restoring from a copy after a baseline —
BOS dropped, a bare prompt counted instead of the generation's payload, an image
counted from its marker, OpenAI's endpoint asked, a missing template endpoint
called broken (and every 4xx called cannot-count), an unreachable backend called
cannot-count, cannot-count answered 502 or 503, local-only skipped, a sleeping
model woken, a key admitted instead of checked, its scope ignored, the path left
out of admission, the count crossing to a fallback tier, one replica's 501
ending the search, and a backend 400 asked of every replica.

## 4. The run's findings

**The second execution's speed check passed for the wrong reason.** It compared
a 37 ms count with a 237 ms "generation" of the same 5,418-token prompt — which
llama.cpp answered from its prompt cache, because the aborted first execution
had prefilled that exact text (10.7 s then; 5 tokens evaluated now). The long
prompt carries a per-run nonce at its head now, and the third execution measured
the real prefill: 10,690 ms. (The first execution died on a stray line in the
script, after five passes.)

**Two unit tests would have passed for the wrong reason before they were
written.** The image count test first used an eight-byte "PNG", which the
translation refuses as no picture at all before the count is ever considered;
it uses a real picture now and asserts the count's own reason. And the
cannot-count test first looked for wording the fake invented; the fake now
raises the real driver's 501 words.

## 5. Not done

- vLLM's `/tokenize` accepts chat messages in its source and was not run; a vLLM
  backend answers 501 today and Claude Code falls back.
- Ollama and hosted backends cannot count; same fallback.
- A count of a request with an image is refused rather than estimated.
- The stopped-model and key-scope cases are unit-tested only (the run's agent is
  a stub with no runtimes and no keys).
