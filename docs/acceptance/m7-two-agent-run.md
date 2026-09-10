# M7 acceptance — two agents, one box, one key domain

**Status:** passed 2026-09-10, on the third run. Script:
[`scripts/m7-acceptance.sh`](../../scripts/m7-acceptance.sh). Follows
[M6's six-process run](m6-six-process-run.md); design in
[`m7-second-host-readiness.md`](../design/m7-second-host-readiness.md).

```
"host A"  agent A :8079 ──spawns──> control :8083, gateway :8080 (controlUrl set), library :8082
"host B"  agent B :8084 ──spawns──> nothing, until the control root forwards it a runtime;
                                     then qwen-b (llama-server :8090) + qwen-b-driver :8091
both agents ──enroll──> control root, with join tokens minted there and bound to their names
gateway   ──/v1/nodes──> control ──> reads BOTH agents; routes to B's companion; stops and wakes B's runtime
```

Both "hosts" are this box. Everything below is HTTP between processes on
different ports holding different keys until they enroll, and one box is
enough for all of it. What one box cannot prove is at the end.

---

## What it proved

Forty-one checks, all green on the third run.

- **Enrollment over real HTTP with real tokens.** A join token minted at
  the control root and bound to `node-b`; `POST B/v1/node/enroll`; B came
  back `enrolled: true, name=node-b, epoch=1, signingKeyId=1`, with a
  public key and an `advertiseUrl` of `http://127.0.0.1:8084` **derived**
  from the route to the root plus its own port. Enrolling B again: 409.
  Replaying its spent token at the root under another name: 409. A did the
  same first, as `node-a`.
- **`/v1/nodes` carried both agents' URLs** — the field the exchange never
  used to send — and after a poll both were `reachable: true,
  lastSeenEpoch: 1`.
- **The control root stayed up through A's enrollment.** A adopted the
  install key and restarted its children; the trust root is skipped now,
  because a restarted root is locked until someone logs in.
- **One key domain.** A's and B's pre-enrollment sessions were refused
  (401) the moment each adopted the install key. A control-minted operator
  token read A's `/v1/node` and B's `/v1/runtimes`; a token B minted after
  enrolling read the control root's `/v1/nodes`.
- **Declared on B through the control root.** `POST control/v1/runtimes`
  with `node: node-b` was forwarded with `service:control` and accepted
  (201). A had no runtime; B's reached `ready` with `Runtime.node=node-b`
  and `driver=qwen-b-driver`. The companion carried
  `Component.advertiseUrl` — B's advertise host with its own port; on one
  box, the same as `url`.
- **The gateway on "host A" listed the alias with `ready_backends: 1`**
  behind a driver spawned by another agent after that agent enrolled,
  which is the only assertion that proves the gateway's token verified
  there. The routing view attributed the backend to `node-b`.
- **A completion** served on B, attributed `driver=qwen-b-driver,
  runtime=qwen-b`.
- **Idle unload crossed hosts.** B reported `stopped / idle`; A was never
  asked. **Wake crossed hosts:** `swapped_in: true`, 5,679 ms wall clock,
  4,958 ms waiting; B's runtime `ready` again.
- **Rotation re-keyed both agents.** `POST /v1/control/rotate-key`
  answered 202 and logged the session out by design; after re-login the
  rotation read `done`, `2/2` re-keyed, nothing pending; both agents
  reported `signingKeyId: "2"`; the gateway (restarted by A) served a
  completion through B's companion (restarted by B) under the new key.
- **Fencing.** The control identity's private key was opened from the
  snapshot with the passphrase and an epoch-0 re-key was signed with it:
  B answered **409** *"refusing epoch 0: this node has already acknowledged
  epoch 1"*. The same body with the epoch changed, signature now stale:
  **401**. B stayed at epoch 1.
- **Clean teardown.** No `llama-server` survived, once the script held the
  agents' pids rather than their subshells'.

## What the first two runs found

**Run 1 — three failures.** The wake (below), and a teardown that killed
two subshells and orphaned both agents and an engine: `( cd a && … ) &`
gives you the subshell's pid. `exec` fixed it. Also found while writing
the script: `restart_all` restarted the control root on enrollment and
login, locking it. Fixed in the agent before run 1.

**Runs 1 and 2 — the wake, the same way both times, and still open.**
The completion sent about 2.5 s after the cross-host idle unload was
routed to B's companion as *eligible*: the driver tried its engine, got
*"All connection attempts failed"*, and the gateway answered 502 with no
wake attempted. The gateway had refreshed twice after the stop — both
reads of B's `/v1/runtimes` were 200 — and B itself reported
`stopped/idle` to the script. Between the runs, `refresh()` was serialized
on the hypothesis that a periodic refresh begun before the stop had
overwritten the post-stop one; run 2 had the lock and failed identically,
so that was not it. Run 3 added a 4 s pause and a dump of the routing view
before the request: `qwen-b-driver eligible=False, runtime=qwen-b,
runtime_status=stopped, node=node-b`, and the wake succeeded. **The window
exists, is about two seconds wide after a cross-host stop, and is not
diagnosed.** `EP_WAKE_DELAY=0` reproduces it. Candidates, in order: the
snapshot the request resolved against was not the one the last refresh
assigned; B's runtime list parsed to nothing on one read (`_get_json`
logs that at DEBUG only, which should be raised); the driver's `/v1/info`
reported no `runtime` for one probe. M6's single-agent run never met it
because its wake test waited through an idle check first.

## What one box could not prove

- A node **genuinely offline** during a rotation. Both agents share a
  kernel; "down" here is a closed port, which the control suite covers.
- **Clock skew.** One clock.
- A **partitioned** old root. The forge tests the refusal exactly as
  contracted, not the partition.
- Any **non-loopback bind.** The derived advertise host was `127.0.0.1`,
  so `Component.advertiseUrl` equalled `url` and no component widened its
  bind to `0.0.0.0`. The mechanism ran; the interesting values did not.
- **WSL2 is still not installed**, so `scripts/m4-acceptance.sh` has still
  never run.

## Timings worth keeping

| What | Measured |
|---|---|
| Enrollment, `POST /v1/node/enroll` round trip including device detection | under a second |
| Companion spawned after enrollment to `ready` alias in the gateway | about 15 s from the forward, including the engine load |
| Idle unload seen on B after the 20 s timeout | within one 5 s idle check |
| Wake on demand across agents | 5,679 ms wall clock, 4,958 ms waiting |
| Rotation across two nodes to `done` | under 3 s, plus the children's restarts |
| Whole run | about four minutes |
