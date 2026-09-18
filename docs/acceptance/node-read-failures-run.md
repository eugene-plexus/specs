# R2.1 — a node that did not answer: the run

**2026-09-18. `scripts/r21-acceptance.sh`, 14 PASS, zero failures, second
execution. `scripts/r21-sabotage.py`, 15 sabotages, 15 caught, 0 escaped**, and
the three findings were **each put back against the live gateway** and each
failed the checks written for it. Roadmap:
[`../design/release-roadmap.md`](../design/release-roadmap.md) §3.1. Findings
closed: review §6.1 #9, §6.2 #18 and §6.2 #17.

Repo: `gateway` only. **No contract change and no UI change**; nothing
re-pinned.

---

## 0. Two reads, and failure spelled as an answer

Every refresh reads two things from every agent. Both treated a failed read as
a fact, in opposite and equally wrong directions.

| read | failed | meant | consequence |
| --- | --- | --- | --- |
| `/v1/components` | `[]` | "this node declares no drivers" | every driver on it *left the topology*: cached HTTP clients closed **under the requests using them**, models un-routed |
| `/v1/runtimes` | `{}` | "this node has no runtimes" | every driver on it gets `runtime is None`, which the eligibility rule reads as *follows nothing of ours, route to it whenever reachable* |

One 401 from clock skew — which this install has produced, for half a second of
drift — one 5 s timeout, or the agent restart the S5 Reach switch performs on
purpose is enough for either. **The control root's read, eighty lines above
these two, has kept the previous map on a failure since the day it was
written.**

Both now return `(value, answered)` and the caller keeps that node's last
successful answer. Stale facts are bounded by the thing that actually checks
liveness: every entry is still probed at its own `/v1/info`, so a driver on a
dead node lands in `unreachable` and is not routed to. What survives a missed
read is the *shape* of the node — which engines exist and what state they were
last in — which is exactly what a missed read should not erase.

**The caches are per node, and that is the whole reason they exist.** Node A's
agent going quiet must not touch node B, and a node the control root no longer
lists really is gone and takes its cache with it.

**`fetch_driver_entries` deliberately does not fall back.** It is what
`POST /v1/config/test` calls, and a Test button answering from a cache is
answering the wrong question.

## 1. The idle-unload race

`idle_pass` and `_evict_for` are check-await-act: they establish that nothing is
in flight, then **await** an HTTP round trip to stop the engine. A request
arriving inside that await was routed to a runtime being shut down — a 502 on
the non-streamed path and, because M10's commit point forbids failover once a
token is out, a **visibly truncated answer** on the streamed one. `_evict_for`
reopens the same window up to eight times, on a path a user is actively waiting
on.

`RoutingTable.stopping(name)` is a context manager holding the runtime out of
routing for exactly that span. **A context manager rather than a pair of calls
because the one property that matters is that it is always released** — a
reservation left behind removes a healthy runtime from the install for the life
of the process. **Counted rather than flagged** because an idle pass and an
eviction can be stopping the same runtime and the inner span must not
un-reserve it for the outer one. The reservation map is shared **by reference**
with every `_Backend`, so a stop taken after a refresh is visible to backends
built before it.

The span is the stop call and nothing longer; afterwards the runtime's own
`status` carries the ineligibility, which is the honest source for it.

## 2. What the live run proves that the unit checks cannot

A real gateway process, a real agent whose reads fail the way a real one fails,
and completions crossing the wire during the failure.

| # | what it does |
| --- | --- |
| 3 | the engine is stopped **and** `/v1/runtimes` refuses — the model must stay un-routable, and a request gets 503 |
| 3b | the same with a **401**, the trigger this install has actually produced |
| 4 | `/v1/components` refuses — the node's models stay routable and a completion still succeeds |
| 5 | **the sharp end**: ten completions spanning several failing refreshes; none may die because its driver client was closed |
| 6 | both reads recover and the fresh answer replaces the kept one |
| 7 | the stub samples the gateway's own admin view **from inside the stop handler** — the only vantage point the race is visible from |

**All three findings were put back against the live gateway and each failed its
own checks**, with the consequence the review described:

```
#18  FAIL  one missed read made a stopped engine routable
     FAIL  a request for a stopped engine returned 200      <- routed to it
     FAIL  a 401 read as 'this node has no runtimes'
#9   FAIL  one missed read un-routed every model on the node
     FAIL  a completion failed while the agent was merely quiet
     FAIL  10 completions died because a refresh closed their driver client
#17  FAIL  a backend was still eligible while its engine was being stopped
```

Ten of ten, for #9. That is not a narrow window.

## 3. The sabotage pass

`scripts/r21-sabotage.py`, **15 sabotages, 15 caught, 0 escaped** — after one
escape that was a missing check.

The three findings are the first entries. The ones after them take the fix
apart a property at a time, and two are worth naming: **the flag without the
fallback** (the fetchers report the failure honestly and the caller ignores it —
the half a reviewer would assume is the whole fix) and **the probe not sharing
the table's reservation map**, which leaves the reservation real, correct, and
invisible to routing because every backend got its own empty dict.

**The escape, and it named a missing check rather than a redundant guard.**
Removing the `try/finally` from `stopping()` passed. The reason is that the
test drove it with an `httpx.ConnectError`, and `AgentLifecycleClient.stop`
catches **every** `httpx.HTTPError` and returns `False` — so the exception never
reached the `with` block and the happy path was the only one ever exercised.
The `finally` earns its place against something `stop()` does not catch: the
idle loop's task being **cancelled mid-stop at shutdown**. Both cases are
checks now, and they leave by different paths.

## 4. The harness defect

**Check 3 asserted 404 and the product answered 503** — and 503 is the better
sentence: the model *is* served by something this gateway knows about and none
of it can take a request, which is not the same as "no such model". The first
execution reported the product broken for being more accurate than the check.

## 5. What the unit checks pin

`gateway/tests/test_node_read_failures.py`, 19 cases. A failed components read
keeping the node routable and **not closing a client a request is holding** —
asserted by using that client afterwards, because "the dict still has an entry"
is not the property; a successful read that drops a driver still closing it; a
failed runtimes read keeping `stopped` and `loading` rather than inheriting
faith; a 401 as a failed read; recovery; **one node's failed read not reaching
the other**, and a node that left keeping nothing; the boundary where a driver
naming a runtime no agent reports *while answering* stays routable on faith,
which is pre-existing and deliberately unchanged; and six on the reservation.

## 6. Not covered

The live run is one node. The per-node isolation is unit-tested against two and
has not been driven across two processes — `m7-acceptance.sh` builds that
topology and is where it belongs. Nothing here exercises a control root whose
own read fails *while* an agent's does. The stale-facts window is unbounded in
time by design (the probe is the liveness check), so a node down for an hour
keeps its shape for an hour; no check asserts what that looks like after a long
outage. And `_evict_for`'s reservation is proved by unit test only — the live
check drives `idle_pass`, because provoking a real eviction needs an admission
refusal the stub would have to invent.

**Window B is not closed by this slice, deliberately.** The reservation covers
the stop *call*; between the agent's 202 and the next refresh the snapshot
still says `ready`. `idle_pass` refreshes immediately after its loop, and the
pre-existing mechanism for a stale snapshot is M6's refresh-on-demand when
nothing is eligible. Widening the reservation past the call would need a rule
for releasing it that cannot get stuck, and the stuck case — a healthy runtime
permanently unroutable — is worse than the window.
