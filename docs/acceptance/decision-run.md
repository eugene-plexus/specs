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

## Pending, named

- **Hosted Jev is unverified.** No TypeSafe credentials exist here, so
  the hosted provider (`typesafe`, key-required, always
  cloud-classified) is covered by driver fixture tests only. One real
  synthetic-data request with authorized credentials, a pinned model id
  and a recorded result is Troy's to run before "hosted Jev access" is
  claimed as verified. The local release does not wait on it.
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
