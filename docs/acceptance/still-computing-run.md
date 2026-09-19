# R2.5 — a backend that is still computing has not failed: the run

**2026-09-18. `scripts/still-computing-acceptance.sh`, 29 PASS live, zero
failures, fifth execution. `scripts/r25-sabotage.py`, 29 sabotages over four
gates, 28 caught and 1 escaped by measurement — after a FIRST pass that escaped
eight and found that three of the run's checks could not fail. Read §5 before
believing the run.** Roadmap:
[`../design/release-roadmap.md`](../design/release-roadmap.md) §3.5. Findings
closed: review §6.2 #13, §6.2 #16.

Repos: `inference-driver`, `gateway`, `agent`, and `specs` — **there was a
contract change after all, and finding it was part of the work.**
`gateway.yaml` stated in two places that *timeouts cascade*, which is precisely
what this slice stops, and neither document carried a 504 or a 499 on any path.
That is the "stale claim inside a contract" pattern this repo already names as
its worst kind. Prose plus five response entries; **no schema moved**.

**Radius measured by regenerating, not by reading the diff.** `gateway` and
`inference-driver` came back byte-identical apart from the SHA in a generated
header and **re-pinned anyway, because they implement the rule the prose now
states** (the `a83df4b` precedent). `agent`, `control` and `library` codegen
neither changed document and stay where they are. `ui` does see a diff —
`openapi-typescript` emits operation descriptions and the new response entries —
and is **deliberately not re-pinned**: it is JSDoc no screen consumes, and
re-pinning would force a `dist` rebuild for a comment.

---

## 0. The shape of it

One sentence: **we were treating "has not finished" as "has failed", and the
difference is what the layer above does next.**

A backend that refused the connection, or answered 500, or is a cloud provider
handing back a 429 did no work and will do none: the next backend in the slot is
a real rescue, and cascading to it is why failover exists. A backend that has
not answered inside the deadline is the opposite — it is almost certainly *still
computing*, holding a GPU or a processor's worth of exactly this prompt, and the
next replica will take the same time to do the same work.

Both arrived as `httpx.HTTPError`. So the cascade recomputed, and the review's
measured case is a 30B on the processor told **"Every backend serving this model
failed"** after 240 s, with two engines having computed the answer.

Four things were wrong, and the roadmap's verification found the fourth:

| | what | why it matters on its own |
| --- | --- | --- |
| **order** | the driver's 120 s fired before the gateway's 180 s | the knob the UI and the docs point an operator at governed nothing |
| **anonymity** | `str(httpx.ReadTimeout(""))` is the empty string | the error read literally `openai_compat_http request failed: ` and stopped |
| **recomputation** | every timeout cascaded | one slow model became N slow models and then a total failure |
| **durability** | the agent's boot reconcile rewrote every companion driver's config | the setting that fixes all of the above did not survive a restart |

And beside them, §6.2 #16: **nothing cancelled the backend when the client gave
up.** The OpenAI SDK retries twice by default, so on a box slow enough for that
to happen the caller does not merely leave — it leaves and asks again, twice,
and three identical generations queue for nobody.

---

## 1. The order, and why it is a number rather than a mechanism

Two deadlines sit on the request path and nothing had ever compared them. The
fix is that the front door owns the answer:

* gateway `requestTimeoutSeconds` → **600 s**, and 600 is not arbitrary: it is
  the OpenAI Python SDK's own default timeout, so the commonest caller stops
  waiting at the same moment we stop serving instead of racing us.
* driver `requestTimeoutSeconds` → **660 s**, one minute above, a backstop
  rather than a decision.
* both maxima raised from 900 s to 3600 s, because a large model on a processor
  is not a 15-minute problem in every install.

**Each number now exists once.** It had been written in seven places — the
gateway's schema default, `app.py`'s `or 180` and `RoutingTable`'s signature
default; the driver's schema default and each of the three engines' `or 120` —
which is how a number drifts and, here, how the order got inverted without
anyone deciding it. `gateway/config.py::DEFAULT_REQUEST_TIMEOUT_SECONDS` and
`inference-driver/engines/base.py::DEFAULT_REQUEST_TIMEOUT_SECONDS` are the two
places left, and each carries the other's value in a comment with the reason.
The driver's lives in `engines/base.py` and not in `config.py` because
`config.py` imports the engines and not the other way round.

**Neither repo can test the comparison**, so it is asserted three ways: a unit
check in each repo pinning its own constant against the other's literal, and
check 3 of the run reading both numbers out of the two *running processes*'
`GET /v1/config` and `GET /v1/config/schema`.

---

## 2. A deadline that fired is 504

`BackendTimeout(CliError)` carries `limit_seconds`. It is a subclass, so every
`except CliError` in the driver's routes keeps working unchanged; what it adds
is identity.

* `openai_compat_http` catches `httpx.TimeoutException` on the completion, the
  stream and the embeddings path and raises it, with a message that names the
  seconds and the setting. The CLI engines' own timeouts raise it too.
* `routes/generate.py::_backend_error` maps it to **504**, and `_error_frame`
  carries the same split once the 200 is already on the wire — a caller reading
  the frame is reading the only description of the failure it will get, and
  "still computing" and "broken" are different instructions.
* the gateway's `_is_cascade_eligible` refuses to cascade a `TimeoutException`
  of its own and a 504 from the driver, and both routes answer 504 with a
  message naming `requestTimeoutSeconds` rather than
  `Every backend serving 'x' failed`.

**The split inside `TimeoutException` is load-bearing and is the whole reason
this is not a one-line change.** `httpx.ConnectTimeout` *is* a
`TimeoutException`, and it is a dead host: nothing was ever handed to an engine,
so the next backend is a real rescue and it must keep cascading. `ReadTimeout`,
`WriteTimeout` and `PoolTimeout` mean the work started, and they must not. The
driver splits it the same way, one `except` clause earlier.

**`test_timeout_cascades_to_backup` asserted the defect.** It sat in
`gateway/tests/test_failover.py` since v0.2.1, green, next to a docstring that
locked "5xx / transport / timeout cascade" in as intent. That is R2.5's instance
of the pattern behind six of the review's findings, and it is why the roadmap's
rule is to write the reproduction first: a check written after the fix tends to
assert the fixture. It is now `test_a_connect_timeout_cascades_to_backup`, which
is the half that was always right.

---

## 3. A client that leaves takes the backend with it

`disconnect.py` in both repos (duplicated, not shared — components share
schemas, not code). `serve_while_connected(request, work)` races the backend
call against the receive channel and, when the client goes,
**cancels the task and awaits it** before returning. Awaiting is the line that
does the work: it is what lets the `CancelledError` reach httpx, close the
socket, and — one layer down — reach the engine.

Five sites: the gateway's completion and embeddings, the driver's generate,
embed, and the first `anext` of its stream.

**That last one is the site reasoning gets wrong.** `StreamingResponse` already
races the body iterator against `http.disconnect`, so a stream in flight is
covered by Starlette. But `/v1/generate/stream` awaits the first chunk *before*
handing the generator over — deliberately, so a failure that early can still be
a status code — and on a cold `llama-server` that await is the whole model load
plus the prefill. Minutes, on exactly the box where a caller gives up.

**499, not 500.** Nothing will read it; the socket is closed. It is what the
access log records, and "the caller left" and "we failed" must not look the same
there. The gateway still records the attempt in `/v1/metrics`: a generation
nobody read is a real cost, and hiding it would hide the one signal that says
your clients are giving up on you.

### The trap, which cost the whole driver suite

The first version used `Request.is_disconnected()`. That is the documented way
to ask, and it **wedges**: it peeks at the receive channel inside an
already-cancelled `anyio.CancelScope`, which only behaves inside anyio's own
task tree, and the watcher is a raw `asyncio.Task`. Under `TestClient`, whose
receive blocks until the response is complete, the peek never came back — the
driver's suite hung at `test_embeddings.py`, and the symptom looked like an
infrastructure problem rather than like this change.

What is there instead is what Starlette's own
`StreamingResponse.listen_for_disconnect` does: one blocking `receive()`, no
polling, and cancelling it is an ordinary task cancellation. It also made the
unit gate 250× faster (5.03 s → 0.02 s), because nothing polls.

`test_the_watcher_does_not_hang_a_plain_request` is in both repos now. Nothing
had asserted "an ordinary request still returns", which is why a hang read as
noise.

---

## 4. The knob has to survive the next boot

`companions.py::_write_config` rendered the three fields the agent manages and
wrote the result over the file. The driver's own `PATCH /v1/config` writes into
that same file — it is how a Config tab in the tree saves anything — so the boot
reconcile, which runs for every runtime and M6 declares one companion per
runtime, silently discarded every setting the operator had saved.

It merges now: `MANAGED_KEYS` are set, everything else is left alone.

**`changed` still means *a managed key moved*, and that is not a detail.** If it
meant "the bytes changed", an operator's edit would restart their driver a
second time and the reconcile's own reformatting would restart every companion
in the install at every boot. A sabotage puts that version back.

An unreadable companion config returns `{}` rather than raising, per
`degraded-mode-required`: one bad file must not take the runtime down, and the
operator fixes it through the driver's own degraded config surface.

---

## 5. The run, and what only it could prove

`scripts/still-computing-acceptance.sh` — a real gateway over a **real**
inference-driver over a stub engine, plus stub drivers as the second replica,
the stalled backend and the dead one; then a real agent, restarted. 29 checks.
Ports +100, every ambient `EUGENE_PLEXUS_*` dropped, teardown by pid.

Four claims exist only between processes:

1. **the order** — read from two running processes, not from either source tree
2. **that nothing recomputes** — a second replica on a real socket, counted
   before and after
3. **that a cancellation crosses every hop** — curl → gateway → driver → engine,
   four processes and three sockets
4. **that the knob survives a restart** — which is what durable means

The measured numbers: the driver's own deadline fires at **12 s** and answers
**504** naming both the seconds and the setting; the gateway's fires at **9 s**
and the request ends there rather than waiting out a second deadline on the
replica (**9 s against the 18 s a cascade would have cost**); the second replica
is asked **zero** times across both, while the *same* replica is asked and
answers when a dead host cascades to it; the engine's socket is cut **2.3 s**
after the client is killed, through all three hops; and an over-long prompt
still hard-fails 400.

### Four instrument defects, and two of them made checks that could not fail

The first two cost an execution each. **The other two were found by the
sabotage pass, and they are the ones worth reading**, because they are this
project's signature failure: a green check that is not about its subject.

**The first execution** ran a driver that ignored every environment variable it
was given: the prefix is `EUGENE_PLEXUS_DRIVER_`, not
`EUGENE_PLEXUS_INFERENCE_DRIVER_`, so it bound its own default port and loaded a
`claude_code_cli` config it wrote itself. Four checks failed against a working
fix. An environment variable that is ignored is silent by construction — worth
one assertion that the process came up where it was told to.

**The second** got the disconnect probe wrong. The stub engine tested whether
its socket had closed with a zero-length `send()`, which on Windows **returns 0
without raising**, so every cancelled call was recorded as `finished` and both
disconnect checks failed while the product was right. A readable socket that
peeks empty is the portable answer — nothing is ever sent to the stub on that
connection, so readable can only mean FIN. Same family as this project's
recurring instrument findings, and the third one in a row to report a passing
product as failing rather than the reverse.

**The third: `r25-stalled` had one backend, so "the second replica was never
asked to recompute" was an assertion about a model with nothing to cascade to.**
It passed with the cascade fix removed. The backup stub answered for
`r25-model`, not for the stalled one — so the check was true and empty. It is
two `modelSlots` now (`r25-stalled → r25-backup` and `r25-cascade →
r25-backup`), which also turned check 6 from *a dead backend returns some error
code* into *a dead backend cascades and the backup serves the request* — and
**the pair is what tells the fix from the over-correction**, since refusing to
cascade a connect timeout would silence the backup in both.

**The fourth: a socket also closes when a deadline fires.** Checks 8 and 9
asked the stub engine *did your socket close*, and it did — at 12 s, because
the driver's own deadline dropped the connection. Both passed with the
disconnect fix removed, measuring the timeout and calling it a cancellation.
The stub records `cut@<elapsed>` now and the checks require it **inside 5 s**,
where no deadline could have produced it: measured at **2.3 s** through all
three hops.

**And the same shape in a unit test.** `_drive`'s own `wait_for(..., 5)` was
hiding the sabotage that abandons the backend task instead of cancelling it:
the deadline's cancellation reached the route, was swallowed by the `suppress`,
cancelled the backend on its way past, and the route returned a perfectly good
499 — five seconds late, with every assertion green. The deadline is 2 s now and
the elapsed time is itself asserted.

### Sabotage

`scripts/r25-sabotage.py`, 29 sabotages over four gates — the three repos' unit
gates plus the live run. The first five are the findings themselves, put back
the way the repo had them and driven against the live processes.

**The first pass escaped eight**, and that was the most useful hour in the
slice: three escapes were the check defects above, two named a missing check
(no test fed the agent an unreadable companion config; the driver gate did not
include the file the `is_disconnected()` wedge actually hangs on), one was a
stale anchor, and one escapes on measurement. **The final pass, run against the
committed state, is 28 caught and 1 escaped**, with all four gates green before
and after.

**The one escape is deliberate and is a measurement, not a gap.** *Never
awaiting* the cancelled task is belt-and-braces: `task.cancel()` alone closes
the socket to the backend fast enough that the live check's 5 s window still
sees the cut. The `await` stays, because "fast enough on this box today" is not
a guarantee and the cost is one line — but nothing here can prove it is load
bearing, and saying so is better than inventing a check that would pass either
way.

**A gate that HANGS counts as caught**, and one sabotage exists for exactly
that: putting `Request.is_disconnected()` back has no symptom except that the
gate never returns, which is how the trap in §3 announced itself. **The wedge is
order-dependent** — it is anyio cancel-scope bookkeeping, not a deterministic
deadlock — so the gate answers with more route tests rather than a cleverer one.

**One premise was measured rather than assumed, and it decided whether any of
§6.2 #16 was real:** a FastAPI endpoint on **uvicorn 0.52.4** is *not* cancelled
when the client disconnects. A 30 s sleep against a killed `curl` reported
`cancelled: false, finished: false` — still running. Without that measurement,
the live escapes could as easily have meant the server already did this for us.

---

## 6. Not done, named

* **No real engine.** Every deadline in the run fires against a stub that sleeps
  on purpose. A real `llama-server` on a real CPU taking six minutes is the case
  the numbers were chosen for and it has not been run.
* **No browser.** The 504 and the 499 are statuses; what the playground and
  Home render for them is unlooked-at, and "Backend did not finish in time" is
  the kind of sentence S8's vocabulary gate exists for.
* **The CLI engines' timeouts** now raise `BackendTimeout` and are unit-tested
  only — no `claude_code_cli` or `codex_cli` invocation was actually timed out.
* **`PoolTimeout` is classed as *still computing*** by the same rule as a read
  timeout, on the argument that a saturated pool is saturated by work that
  started. That is reasoning, not measurement.
* **The streamed path's commit point is untouched**, and a timeout after the
  first token still truncates rather than cascading — which is M10's rule and
  correct, but nothing in this run exercised it.
