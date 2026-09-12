# A worker's browser is a console for the install — live run

**2026-09-12. Verified against the live two-machine install**, not
against a harness. Agent `93f8bb9`, `ui` `661fe14` (dist `39139ce`); no
contract change, so no other consumer moved.

Reported by the operator, from the machine it happened on:

> On Amish_Station, when I click on Gateway, I get this message:
> `503 Service Unavailable — {"detail":{"type":"…#target-not-in-topology",`
> `"title":"Target not in topology","status":503,"detail":"No component`
> `of kind 'gateway' is declared on this node. …"}}`

Two defects in one screenshot: the worker could not reach the install's
gateway at all, and the sentence explaining why was buried in an
envelope.

## It was never only the gateway

An enrolled node declares **no** gateway, library or control root —
`should_seed` refuses to seed a control plane onto a node, which is
correct and was M9's fix. So of the UI's four proxy targets, a worker
could reach exactly one:

| Target | Calls in the UI | On a worker, before |
| ------ | --------------- | ------------------- |
| `agent` | 19 | works |
| `library` | 13 | 503 |
| `control` | 6 | 503 |
| `gateway` | 4 | 503 |

Config, Library, Discover, Metrics, Nodes and the playground's model
list were all unreachable from a worker node's console. The Gateway tab
is simply where the operator clicked first.

## THE MEASUREMENT THAT DECIDED THE DESIGN

The obvious implementation is: ask the control root where the gateway
is, and proxy there. **The live install falsifies it.**

```
GET http://192.168.16.252:8283/v1/components
{"components":[
  {"node":"468e3ed662bf","name":"gateway","kind":"gateway",
   "url":"http://127.0.0.1:8080/","status":"running"}, …
```

That URL is correct **on that host** and useless anywhere else, and no
rewriting fixes it: the container binds 8080 and UnRAID publishes it as
**8280**, a mapping nothing inside the container can see. The same is
true of `advertiseUrl`, which is derived as *advertise host + the port
the component binds* — under a port remap that derivation is wrong by
construction, for every component in the container.

So the hop goes to the **owning node's agent**, and that agent resolves
the component against its own topology, where loopback is true again:

```
worker browser
  -> worker agent   /api/proxy/gateway/v1/models
  -> root agent     /api/proxy/gateway/v1/models     (Node.url, 8279)
  -> root gateway   /v1/models                       (127.0.0.1:8080)
```

**One address per node instead of one per component**, and it is the one
address the install already maintains, announces on every start, and
re-announces whenever it changes. The port remap is invisible to the
design because the operator states the node's address in full.

## The blocker this exposed, and it is a real defect

`Node.url` for the control host was **`http://127.0.0.1:8079/`**. The
container's agent derives its advertise address from the interface it
used to reach the control root — and its control root is in the same
container, so the route is loopback. Correct derivation, useless answer,
and nothing had noticed because until now nothing outside that host ever
needed the control host's address.

Fixed on the live install by setting the agent config field, which
announces immediately — no restart, no re-enrollment:

```
PATCH http://192.168.16.252:8279/v1/config
{"advertiseUrl":"http://192.168.16.252:8279"}
-> {"applied":["advertiseUrl"],"rejected":[],"requiresRestart":false}

GET  .../v1/nodes
468e3ed662bf  http://192.168.16.252:8279/   (advertiseSequence 7)
Amish_Station http://192.168.16.75:8079/    (advertiseSequence 5)
```

**A node whose registry entry is loopback is now explained rather than
dialled.** Without that branch the proxy would connect to port 8079 on
the *asking* machine and report "the gateway did not answer" — naming
the wrong host entirely. The refusal names the field to set instead.

The config field's own description was stale about this and is
corrected: it claimed "the control root keeps the URL it was told at
enrollment until this node re-enrolls", which M9 stopped being true
when it added announce-on-change.

## What ran

Live, across the LAN, from the worker's own proxy:

| # | What | Result |
| - | ---- | ------ |
| 1 | `GET /api/proxy/gateway/v1/models` | 200, `qwen3-coder:30b`, identical to the gateway direct |
| 2 | `GET /api/proxy/gateway/v1/config` | 200 — the tab the operator clicked |
| 3 | `GET /api/proxy/library/v1/models` | 200 |
| 4 | `GET /api/proxy/control/v1/nodes` | 200 |
| 5 | `GET /api/proxy/gateway/v1/metrics` | 200 |
| 6 | `POST /api/proxy/gateway/v1/chat/completions` | 200, `"cross-node console works"`, 2542 ms, tier 1 |
| 7 | the same request with `stream: true` | **71 frames, TTFT 0.179 s = 6.8 %** |
| 8 | a request carrying the hop marker | 503, naming the node that forwarded it |
| 9 | a target nothing in the install runs | 503, "not a question of which node you are browsing from" |

Check 6 is worth reading twice: the request crosses the LAN to the
control host, is routed by the gateway back to the worker's own driver,
and returns. Three crossings for one completion, and the operator's
browser never left same-origin.

**Check 7 is the one that could have passed while broken.** There are
now *two* agent proxies in the path, and a buffering proxy still
delivers every frame — M10's recorded harness lie. Measured against the
same request made directly to the gateway in the same run: 71 frames
both ways, TTFT **6.8 %** through two hops against **12.9 %** direct.
Nothing buffers.

## The credential, which is what makes this legitimate

The lookup carries **the caller's own `Authorization`** to the control
root rather than minting anything. An enrolled node holds the install's
signing key, so a token the worker's agent issued is one the root
accepts — that is precisely what makes a worker's console a console for
the install, and it is why this is not a privilege escalation: the set
of reachable addresses is the operator's own node registry, and every
component still enforces its own auth.

**A refused credential is deliberately not cached.** The proxy is
unauthenticated by design — it is the path the login request itself
travels — so an anonymous request reaches this lookup and is refused. A
5-second negative cache would then answer the signed-in operator with
someone else's 401. Found by reading, tested, and sabotage-checked.

Confirmed live, incidentally: an unauthenticated proxy call resolves
from a warm cache, is forwarded, and comes back **401 from the gateway**
— `"component":"gateway"` in the body. The trust boundary is where the
docstring says it is.

## The second defect: the envelope

`ConfigEditor`'s error formatter was `status + JSON.stringify(body)`.
Every component writes an RFC 7807 `Problem` whose `detail` is the
operator's next action; this screen printed the document around it.

One unwrapper in `lib/api.ts` now. And it found a third thing:
`errorMessage` in `completions.ts` handled `{detail: <string>}` and
**not** `{detail: {detail}}` — the shape FastAPI actually produces, and
therefore the shape of every `Problem` the proxy has ever returned. Its
own docstring named the proxy as a case it covered. So a proxy failure
reached the playground as `HTTP 503 Service Unavailable` with the reason
discarded.

## What is covered by tests rather than by this run

23 unit tests in `agent/tests/test_install_wide_proxy.py`, of which
**eight were sabotage-checked** — the hop guard, the loopback
explanation, the caller's credential, the cache, hopping to the node
rather than the component, kind-over-name precedence, invalidating a
dead address, and not caching a refused credential. Each sabotage made
its own test red; a green one would have meant the test asserted
nothing.

The loopback fixture is the value read off the live registry before it
was fixed, not an invented one.

## What this run does not cover

- **There is no acceptance script.** The hop needs two enrolled agents
  and a real control root; `m7-acceptance.sh` already builds exactly
  that topology on one box and is the place to add it. Until then this
  path has unit coverage and one live run, and a regression would be
  found by an operator rather than by CI.
- **No browser drove it.** Every call each screen makes was exercised
  over HTTP; Playwright was not pointed at the worker.
- **Worker-to-worker.** A driver on another node resolves by the same
  mechanism and is unit-tested, but this install has one worker, so two
  workers have never talked through each other.
- **A node that moves mid-session.** The 30-second cache is invalidated
  when a hop fails, which is tested; a node genuinely changing address
  under load is not.
