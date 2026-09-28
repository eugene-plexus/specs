# B2 — a real Kev answers typed decisions through the whole install

**Run:** 2026-09-22, `scripts/b2-decision-acceptance.py` on WSL2 Ubuntu,
CPU only, **ALL 13 CHECKS PASSED on the twelfth execution** — the earlier executions each failed on something real, and the findings section below is what they found. Measured on a Ryzen 9950X (WSL2, Python 3.12, torch 2.8.0 CPU): process-cold start to `ready` 5.6 s, offline restart 4.5 s, single-question p50 228 ms / p95 239 ms over 8 sequential requests, kev peak RSS 5.6 GB (VmHWM), proxy overhead 47 ms median over direct.

**What is real:** everything on the control path. A real control root, a
real enrolled agent that **spawned `python -m kev.serve`** on the pinned
checkpoint (`jaredpalmer/kev-0.8b` @ `54f4f877`, base
`Qwen/Qwen3.5-0.8B-Base`, Apache-2.0, upstream commit `1c35199`) and
declared its companion `systemone_custom` driver with
`decisionMaxConcurrent: 1`; a real gateway routing `POST /v1/systemone`;
real `curl` as the first client. `CUDA_VISIBLE_DEVICES=""` rode the
runtime's own env — the owner's GPU was never touched, so every number
here is a CPU number. **What is simulated:** two additional System One
backends are counting fixtures, for the checks a real model cannot
produce on demand (a second distinguishable alias, controlled
misbehavior, held requests for the timeout and concurrency gates).

Environment: one uv venv (Python 3.12) holding all four components
installed editable from the working trees at the B2 commits; the Kev
environment is its own checkout venv (`uv sync --extra serve` at the
pinned commit; `transformers` 5.x, torch 2.8.0). The checkpoint and its
base were downloaded once by the planning-day measurement run, so
"cold" below means a cold process over a warm HuggingFace cache — the
true first-ever launch, which downloads the base model, was the manual
run that measured the server's behavior in the first place.

## The checks

 1. the agent spawned the pinned kev-0.8b and proved it ready in 5.6s (cold, CPU)
 2. the supervised kev model is discoverable and marked decisions-only
 3. real curl -> real gateway -> real driver -> real kev: the refund is a 0.98 yes routed to billing
 4. string, object and array states all serve; a reused question id is independent
 5. a second public alias reaches its own backend, distinguishably
 6. a chat request naming the decision model is refused with the door's name
 7. a scoped key is refused the other model; a local-only key serves the supervised kev and is denied the external backend with zero requests to it
 8. protocol violations are 422 before work; a backend that leaves a question unanswered or answers out of range is a 502, never an invented decision
 9. a fired deadline is a 504 with an uncertain outcome, asked of exactly one backend, whose work runs to completion and only then frees capacity
10. a single-slot backend is 503-not-queued while its one request is in flight
11. routing fidelity: 5/5 identical answers direct vs proxied; model accuracy on the frozen set 5/5 (recorded, not gated); proxy overhead 47ms median
12. single-question p50 228ms / p95 239ms over 8 sequential requests on CPU; kev peak RSS 5626640 kB
13. stop, then a second launch with outbound access disabled (HF_HUB_OFFLINE=1): ready from pinned local artifacts in 4.5s

## What the run found, in order

**A launch guard did its job twice, and the second refusal is a
finding.** The first execution was refused: a runtime binary outside the
managed store needs whitelisting. Adding the kev venv's `bin` to
`engineBinaryRoots` did NOT fix it, and correctly: **a uv venv's python
is a symlink to the shared uv-managed CPython**, so the resolved binary
never lives under the venv directory and a directory whitelist can never
cover it — S5's `sys.prefix` lesson, one guard over. The by-design path
is the engine's own config key: `kevPython` set to the venv interpreter
is trusted by resolved-path equality, and it is also what exercises the
adapter's configured discovery. The recipe already said to set
`kevPython`; now the harness proves it is the only shape that works.

**The third execution found a real product defect no unit test had:**
a client key scoped to `allowedModels: [tickets]` was served `invoices`
on `/v1/systemone`. `ClientAdmissionMiddleware` wrapped an explicit
four-path set that did not include the new door, so the client context
was never created and every downstream check — scopes, local-only,
concurrency, rate limits, usage attribution — read "no client, nothing
to limit." Fixed in gateway `5b0db63`: the set is a named constant
(`CLIENT_ADMISSION_PATHS`) whose docstring states the rule — **a door
added without a row there is a door with no client admission at all** —
and a test pins all five doors into it.

**The fourth and fifth executions tripped over the gateway doing its
job.** An induced indeterminate 502 opens the backend's circuit breaker,
so the *next* induced failure — and then the timeout probe — answered
503 "cooling down" without reaching the backend. The harness is
circuit-aware now: each sabotage waits out the cooling window
(bounded), asserts the 502 names the defect, restores health and waits
for a clean 200 before the next one. A cooling 503 never reaches the
backend, which is also what keeps "the timeout was asked of exactly one
backend" honest. The concurrency check's baseline read its counter at
the last moment, because the waits in between answer requests too — a
stale baseline is a check that can pass while broken.

**The later executions found four more, smaller and all one family —
an assertion about the wrong subject.** A PATCH of
`requestTimeoutSeconds` to 2 was rejected PER FIELD inside a 200 the
harness never read (the field's minimum is 5), so the file never carried
the key and a 5 s hold sailed through a "2 s" budget; a config PATCH's
status is not its verdict. With the value real, the deadline STILL did
not move: **the gateway's request timeout binds when the routing table
constructs its driver clients**, so a live PATCH reaches only clients
built afterwards — the harness restarts the gateway, which is also the
honest operator flow for this knob. The 504 that then arrived carried
the shared total-request-deadline machinery's A6b wording ("No automatic
replay … a remote provider may still have acted") rather than the
decision route's own sentence — two honest bodies for one refusal, and
the check accepts either. And the lifecycle verbs answer **202**, not
200, with `PATCH /v1/runtimes/{name}` taking the FULL spec rather than a
delta — both the agent's contract working as written, asserted wrongly
by the harness first.

## Hosted Jev through OpenRouter, 2026-09-28

The pending item below said hosted Jev needed TypeSafe credentials. It no
longer does: OpenRouter serves Jev at `https://openrouter.ai/api/v1/systemone`
with the same pinned protocol, so the `typesafe` provider was pointed there
(`baseUrl: https://openrouter.ai/api`, `upstreamModelId: typesafe/jev-1.13`,
an OpenRouter key in the driver's `apiKey`). `scripts/b2-hosted-jev-check.py`
builds a real control root, an enrolled agent, a real gateway, two
`typesafe` drivers (one with a deliberately invalid key) and, since the fix
below, an `openrouter` chat driver with an invalid key, run from the B2 venv
in WSL2:

```
cd /mnt/d/py/eugene-plexus/specs/scripts && ~/b2/ep-venv/bin/python b2-hosted-jev-check.py
```

**ALL 9 CHECKS PASSED**, on the second attempt: the first was cut off by the
upstream, not by Eugene (see below).

1. The provider starts against OpenRouter: `locality: external`, `jev` →
   `typesafe/jev-1.13`, decisions only (noul, choice, score).
2. The gateway lists `jev` as decisions-only.
3. A real hosted decision through gateway and driver on the refund ticket:
   `refunded` 0.98, routed `billing`, urgency 0.17, 441 input tokens.
4. String, object and array states all decided; end-to-end p50 **278 ms**,
   max 399 ms over 6 calls.
5. A chat request naming `jev` is refused with the decision door's name.
6. A client key decides; a local-only key is refused with 403, because the
   provider is external.
7. An unknown question field is a 422 at the gateway.
8. A key OpenRouter refuses comes back as a refusal, not a hang (see finding 2).
9. The key appears in no process log and no response (32 responses scanned).

**Findings.** 2 and the doubled sentence in 3 were fixed the same day; 1 is
recorded and not fixed.

1. **The upstream revision is not surfaced.** `gateway.yaml`
   (`SystemOneResponse.model`) says the backend's own model revision is
   "surfaced in `x_eugene_plexus`". The driver records it
   (`reportedModel: typesafe/jev-1.13-20260917`, `systemone_http.py`), but
   `CompletionRoutingInfo` has no field for it and the gateway drops it.
   Either the contract gains the field or the sentence changes.
2. **A provider-refused key blames the caller.** OpenRouter's 401 for a bad
   key reached the client as HTTP 400 `invalid_request_error` ("The backend
   rejected the request: systemone_http returned 401: User not found."). The
   driver's `_backend_error` (`routes/generate.py`) turns every upstream 4xx
   except 408/409/425/429 into its own 400, so this is not decision-specific:
   a chat driver whose OpenAI, OpenRouter or xAI key is revoked says the same.
   R3.4 fixed the neighbouring case, where the driver refuses the gateway
   (502 `upstream_auth_error`); this is the provider refusing the driver.
   **Fixed 2026-09-28** — contracts `b417855` (prose), inference-driver
   `934d824`, gateway `ba25538`. A 401, a 402 (no credit), or a 403 whose
   words are not about the content is the driver's 502
   `#backend-credential-refused` and the gateway's 502 `upstream_auth_error`,
   naming the driver, its URL, the provider's words and where the key is set.
   It stays `terminal`: no cascade (the 4xx rule is unchanged) and no breaker
   trip, which would have turned the cause into "backends cooling down". A
   403 about flagged content stays the caller's 400.
   `scripts/credential-refused-sabotage.py`: **15 of 15 caught** across both
   repos. Live re-run: **ALL 10 CHECKS PASSED**, first attempt, with the
   decision door and a new chat-door driver both reading *"The driver
   'driver-badkey' at … could not use its provider: The backend refused this
   driver's credential (its API key; HTTP 401): … User not found."* **Pinned in
   both installers 2026-09-28, with P2a**, after P2a's own acceptance run and
   sabotage pass ([record](media-inputs-run.md)).
3. **The hosted service stalls in bursts.** The first attempt's opening
   decision took 22 s and the next was an OpenRouter 503 ("upstream connect
   error … connection timeout"). A direct probe minutes later saw 4 of 6
   calls fail after 20-30 s (read timeouts, 503, 520). Eugene reported it
   correctly as `upstream_error` with "outcome unknown, no automatic replay",
   but that sentence appeared twice in one message, once from the driver and
   once from the gateway. **The doubled sentence is fixed** (gateway
   `ba25538`); the stalls are upstream's.

## Pending, named
- **The documented SDK half is blocked on distribution, measured:**
  PyPI's `typesafe` package is an unrelated library capped at 0.9.1, so
  `pip install typesafe==1.13.*` cannot install TypeSafe's SDK. The
  panel's snippet warns about the collision and points at TypeSafe's own
  docs; the curl half is the verified first client.
- Kev on CUDA, ROCm and Metal each need their own evidence; the engine
  stays `experimental` and only WSL CPU is claimed.
- Decision requests record per-attempt metrics through the routing
  hooks, but no request-level row lands in `GET /v1/metrics` — the
  dashboard stays chat-shaped for decisions. Recorded, not fixed.
- The frozen labeled set is five examples — a routing-fidelity and
  honesty check, not a model evaluation; accuracy is recorded, never
  gated, and says nothing about Jev-equivalence (out of scope by the
  roadmap's own list).
