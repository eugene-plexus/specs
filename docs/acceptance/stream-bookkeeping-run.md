# R1.4 — a stream that ends leaves nothing behind: the run

**2026-09-18. `scripts/r14-acceptance.sh`, 18 PASS, zero failures, third
execution. `scripts/r14-sabotage.py`, 13 sabotages, 13 caught, 0 escaped.**
Roadmap: [`../design/release-roadmap.md`](../design/release-roadmap.md) §2.4.
Findings closed: review §6.1 #3 (a disconnect mid-stream leaks the in-flight
counters) and §6.3 #38 (a stream with no `done` frame is recorded served), plus
the second, independent leak of the same counter that the roadmap's own
verification added.

Repo: `gateway` only. **No contract change and no UI change**; neither
installer is re-pinned. The six pins stay as R1.1 left them, to be bumped once
at the end of R1.

---

## 0. One seam, three ways an attempt ends

`TieredClient.stream` classified every attempt with an `except Exception` /
`else` pair, and that pair cannot see two of the three ways a stream ends.

| how it ends | what is raised | which arm ran | what was recorded |
| --- | --- | --- | --- |
| driver failed | `Exception` | `except` | `served=False` ✓ |
| driver finished | — | `else` | `served=True` ✓ |
| **client closed the tab** | `GeneratorExit` | **neither** | **nothing** |
| **request task cancelled** | `CancelledError` | **neither** | **nothing** |
| **driver stopped, no `done`** | — | `else` | **`served=True`** ✗ |

Both `BaseException`, so the attempt was opened and never closed. The counter
it left behind is not cosmetic: `lifecycle.py:220` skips any runtime with
`runtime_inflight(name) > 0` on **every** idle sweep, and `:362` will not evict
one to make room for a wake. One closed tab took that engine's memory out of
circulation for the life of the gateway process.

The fix is one `saw_done` local and one `finally` arm, plus `reported` so the
paths that already closed the attempt do not close it twice. The same three
lines went into `generate` and `embed`, which have the identical shape.

## 1. The second leak, and why it is here rather than in R2.1

`on_attempt_start` resolved the runtime by scanning the live snapshot, and
`on_attempt_end` scanned it **again** against whatever snapshot had since been
installed. Two answers to one question, and a refresh lands between them
routinely — a 401 from clock skew, a 5 s timeout, or the agent restart the S5
Reach switch performs on purpose.

**Forward:** the second lookup answers `None`, the increment is never undone,
and that runtime never idle-unloads again. **Mirror, and worse:** a request
that starts while the facts are missing and ends after they return decrements a
counter it never raised, `max(0, …)` absorbs it, and a live in-flight request
reads as zero — after which the idle pass unloads an engine mid-answer.

`on_attempt_start` now **returns** the runtime it counted against and the slot
hands it straight back. An attempt is one thing and is counted once, against
one runtime. R2.1 still owns the reads that make the snapshot wrong in the
first place; this owns the pairing, which is wrong whatever the reads do.

## 2. What the live run proves that the unit checks cannot

The unit module drives `TieredClient.stream` in-process and closes the
generator by hand. That is the right shape for the mechanism and it is not the
last word on the finding, because **§6.1 #3 is a claim about two other
libraries' behaviour** — starlette takes its disconnect-listening task group
for any ASGI spec below `(2, 4)`, uvicorn advertises `2.3`. So the run puts a
real gateway process over a stub agent and a stub driver, and kills `curl`
mid-answer on a real socket.

| # | what it does |
| --- | --- |
| 2 | 20 content frames — the baseline, or every check below passes for the wrong reason |
| 3 | `curl` killed mid-stream; `in_flight` is 1 during, **0 after** |
| 4 | three killed streams in a row still leave 0 — the fix is per attempt, not a latch |
| 5 | the agent is really asked to **unload** the runtime afterwards |
| 6 | a driver that stops with no `done`: a terminal frame carries `stop`, the row reads `served=False` / `error=IncompleteStream` / `outcome=error` |
| 7 | a complete stream still reads `served` — the guard on 6 |

**Sabotaged live, not just in unit tests.** With the `finally` arm removed and
the gateway restarted, checks 3, 4 and 5 fail and check 4 reads `in_flight is
4` — one per closed tab, accumulating. With `served=saw_done` put back to
`served=True`, check 6 fails on both the attempt row and the request outcome.

## 3. The check that passed against its own sabotage, and had to be rewritten

**Check 5 was `idle_seconds` off the admin view, and it PASSED against a
deliberately sabotaged gateway.** `idle_seconds` is computed from the
last-served mark; it has nothing to do with the in-flight counter, so it reads
the same whether or not the counter leaked. That is this project's recurring
failure — M10's check 7, step 6's fragmentation checks, S7's component-not-
wiring tests — caught this time only because the live sabotage run was done
rather than assumed.

What cannot be faked is **the agent being asked to stop**. The stub now
declares an `idleUnloadSeconds` on request (off for the rest of the run, or the
idle pass fires after some other check's completed stream and check 5 reads
someone else's unload) and records every stop it receives. Fixed: the runtime
whose client went away is unloaded, the memory comes back. Sabotaged: `stops
the agent was asked for: []`.

## 4. The sabotage pass

`scripts/r14-sabotage.py`, **13 sabotages, 13 caught, 0 escaped.** Restores
from a copy taken up front, opens with a baseline that the gate passes
unsabotaged.

The two findings are the first two entries. The third is the one worth keeping:
**the `finally` arm made to fire only for `GeneratorExit`** — which still
passes the closed-tab check and fails the cancellation check. Without it, a fix
covering only the symptom someone happened to press would have looked complete.
The rest: reporting twice on the paths that already reported; a cascaded
failure reported twice; `saw_done` never set (so nothing ever serves); the
truncation recorded with no reason; and four on the pairing — the end
resolving the runtime itself again, the start refusing to say what it counted,
and the name dropped on the way back through `generate` and through `embed`.

**`embed`'s entry was added after the first pass.** Nothing covered it, so
changing its `runtime=runtime` to `runtime=None` would have escaped — the
missing check, found by writing the sabotage before believing the coverage.

## 5. Two harness defects, both in this run's own instrument

**`tail -1` is the blank line, not the frame.** An SSE frame ends with an empty
line, so two `[DONE]` assertions failed against a perfectly well-formed stream.
The first execution reported the product broken on two checks while it was
right. `last_frame()` takes the last non-empty line.

**`attempts` on a metrics row is a count, not a list.** The per-attempt facts
are under `tries[]`, and `outcome` is derived from whether any of them served —
which is the whole subject of #38, one layer up and the layer that would have
hidden it. Both are asserted now.

## 6. What the unit checks pin

`gateway/tests/test_stream_bookkeeping.py`, 14 cases. A complete stream
balancing to zero (the baseline, so a fix that never increments cannot pass the
leak cases); the closed generator and the cancelled task, each asserting the
counter is **1 during** before asserting 0 after; an abandoned attempt recorded
`served=False` and not refreshing the backend's last-served mark; a cascade
recording exactly one row per attempt; the done-less stream; the pairing in
both directions; and `generate` and `embed` separately.

## 7. Not covered

The live disconnect is `curl` killed with SIGKILL, which is the closed tab and
not every disconnect — a proxy timing out, or a browser's own abort, arrive at
the same place but have not been driven here. The stub driver is not an
inference-driver: a real driver's own cancellation behaviour on the wire behind
the gateway is untested, deliberately, because the subject is what the gateway
does when its client goes away. `embed` has no live check at all; its pairing
is unit-tested and sabotage-checked only. And nothing here touches the reads
that make a snapshot wrong in the first place — that is R2.1, which sits right
behind this one and is now reachable: until today a leaked counter was what
accidentally kept a runtime out of the idle pass.
