# The Inference screen — one place for everything that serves

**2026-09-12. Built on four calls Troy took, verified against the live
two-machine install.** Agent `f872e31` (the `node:<name>` proxy
target) and `7090cbf` (the llama.cpp acquisition fix below); `ui` `f2b65c6` +
`90922e8` (dist `c49cd5f`). No contract changed.

The report, from the operator, in full because every sentence of it
turned out to be a distinct defect:

> When I log into the control root, I see the Amish node is connected.
> There is no way for me to tell what it serves from here. So I log into
> the node directly. If I click onto Runtimes, it shows none are
> installed, with no option to install them. It also doesn't mention the
> Ollama. I have to go to Config, then click on ollama-qwen to see the
> "inference-driver" I set up on install. I understand that Ollama
> support is 2nd class compared to runtimes we manage, but it feels
> buried compared to llama_cpp and vllm. I would expect to be able to
> find all inference engines in one place, regardless of who manages it
> or how we connect.

## The framing was right about the UI and wrong about the system

The gateway never distinguished. It routes to **drivers**, and a driver
fronting Ollama is as routable as a companion driver fronting a
llama.cpp process — the same `/v1/admin/drivers` row, the same routing
table entry, the same `x_eugene_plexus.driver` on every completion.
"Runtime" is this project's word for an engine process *it supervises*,
and Ollama is not one; only the UI had a category for the one and not
the other, so Ollama fell through to a Config tab.

Every install-wide view the operator wanted **already existed as an
API and nothing rendered it**:

| what | where | rendered before |
| --- | --- | --- |
| every backend the gateway routes to — name, reachable, model, backend kind, which runtime it follows | gateway `/v1/admin/drivers` | nowhere |
| per model: tiers, each backend's eligibility, in-flight, runtime state | gateway `/v1/admin/routing` | nowhere |
| which node each component and runtime runs on | control `/v1/components`, `/v1/runtimes` | nowhere |

The Runtimes page read the local agent alone — engines on *this* host,
runtimes on *this* host. On the worker that was "nothing installed, no
runtimes", while the only model in the install was served from that
very machine through a driver the page had no row for. Nodes showed
name, address and "2 device(s)", nothing served. Launch lived on Library
and posted to the local agent.

## The four calls

Brought as a proposal with a recommendation on each; Troy took all four.

1. **Replace Runtimes rather than add beside it.** "Runtime" is our
   word; the operator's question is "what is serving". `/inference` is
   the page; `/runtimes` redirects, so the wizard's closing text, old
   links and the e2e walk still land.
2. **Launch stays on Library and gains a node picker.** One choice for
   two things that must agree: whose memory a fit verdict is scored
   against, and where Launch goes. A verdict about node A followed by a
   launch on node B recommends a quant for a card the launch never
   reaches. This closed the gap the guidance record had left open the
   same day — the root's own console can now score against, and launch
   on, the worker.
3. **External backends are listed now; the guided "Add" form is a
   follow-up.** Listing fixes "buried"; each backend kind has its own
   config, so the form is its own piece. The button exists and says
   where the declaration lives today.
4. **Cross-node actions through a node-addressed proxy target**, not
   through the control root. Start, stop and restart are per-agent by
   nature and control forwards only *declarations*, by design; teaching
   it to forward actions would widen the trust root's contract for no
   security gain, since the operator's token is already accepted at
   every agent.

## What was built

**`node:<name>`** (agent `f872e31`). The same registry and reachability
rules as the component hop, one difference: no `/api/proxy` prefix on
the far side — this is the agent's own API, so there is no second
resolution and no way to loop. Our own name is the local agent without a
lookup, because the screen names every node the same way and the local
one must not cost a round trip to the root and back. Live from the
worker:

```
GET /api/proxy/node:468e3ed662bf/v1/engines   -> the NAS agent's engines
GET /api/proxy/node:Amish_Station/v1/engines  -> local, no lookup
GET /api/proxy/node:ghost/v1/engines          -> 503 "No node named 'ghost'
                                                  is enrolled in this install"
```

**The Inference screen.** Rows are the gateway's drivers, joined to the
install's runtimes where a driver follows one, grouped by the node the
control root places each on. A declared driver the gateway never
mentioned is a row too — "declared and not routable" is the row an
operator is looking for when a model is missing. Per node: hardware
line, engines with install offered (never applied), the rows. Four
sources, **each soft**: a sealed root or a gateway in safe mode removes
a column's worth and is named at the top, because the page an operator
opens when something is wrong must not be the page that fails because
something is wrong. The join is a module (`lib/inferenceRows.ts`)
tested against **the bodies the worker's proxy actually returned**,
not fixtures shaped to the code; two sabotage-checked.

**The node picker** on Library and Discover (`NodePicker`,
`useTargetNode`): the local agent's `/v1/node` plus the control root's
`/v1/nodes`, local by default, remembered per browser only while that
node is still enrolled. Engines are read from the *picked* node, so
"can this format be launched" is answered about the machine it would be
launched on. Launch on another node goes `POST control /v1/runtimes
{node, spec}`, which forwards first and records second.

**Nodes** gains a Serves column (drivers per node from control, live
state from the gateway). **Config**'s driver tabs list every driver in
the install, labelled `name @ node`.

## Found on the way: llama.cpp was "not installable" on every host

The new screen puts each node's engines in front of the operator, and
the worker — Windows x64, RTX 5090 — read:

```
"reason": "release b10931 has no asset for 'win-cuda-13.3-x64'.
           Published variants: (none)."
```

Not a Windows problem. Upstream's newest release object, `b10931`,
published 2026-09-12 14:48Z, had **zero assets** — its CI had not
uploaded, or never did — and `b10930` an hour earlier carried the usual
27. `latest_release()` took the highest build number and so every host
in the install was told nothing was installable, for as long as that
object stayed newest. It now takes the highest build **that has
assets** (agent `7090cbf`). Checked before fixing: every `b` build upstream is marked
prerelease, so that flag could not be the filter; the presence of
assets can.

## What this run does not cover

- **No browser drove it.** Every call each screen makes was exercised
  over HTTP through the worker's proxy, and the join was tested against
  the captured bodies; nobody clicked start on a runtime, because this
  install supervises none — its one model is Ollama's.
- **Launch on another node was not exercised end to end.** The path is
  wired and control's forwarding is tested in its own repo, but this
  install's library lives on the NAS and its model paths do not exist
  on the worker — the honest failure (*"that path does not exist
  here"*) would be relayed from the agent, and M11's compute/storage
  separation is what makes it succeed instead.
- **The "Add an external backend" form** is a link to Config with an
  explanation, by call #3.
- **Two workers with a driver of the same name** would be labelled
  apart on Config but resolve to the first found by the proxy's
  name-keyed hop. Not this install's shape; noted.
