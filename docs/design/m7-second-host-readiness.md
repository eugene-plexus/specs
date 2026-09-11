# M7 — Second-host readiness (design)

**Status:** designed and built 2026-09-10; live-verified on **two agents
on one box** the same day (§11), and on **two real machines 2026-09-11**
— Windows A and WSL2 Ubuntu B across NAT and a host firewall, 41 checks,
first attempt, **with nothing in any component changed**
([record](../acceptance/m7-two-host-run.md)). Milestone **M7** of
[`local-inference-control-plane.md`](local-inference-control-plane.md).
Follows [M6](m6-lifecycle-policy.md). Contracts first, then implementation,
then an acceptance run against the closest thing this machine allows.

**What it is.** The slice between "M6 is done" and "multi-host has run on
two machines": make a second host *possible* before a second host exists.
Four things, each of which the two-machine run would have hit in its first
minute: the agent's half of M5's enrollment, which was contracted in
2026-09-09 and never built; an address at which other hosts can reach an
agent and the components it spawns, because every URL the agent writes
today is `http://127.0.0.1:<port>`; proof that the gateway fans out over
several agents and sends a lifecycle action to the agent that owns the
runtime; and an acceptance script written for two hosts and run against
two agents on one.

**Why a milestone and not a §13 on M5's doc — Troy's call, built on the
recommendation.** One third of this is M5 debt (enrollment). The other two
thirds are the first half of what the roadmap called M7, *networked
polish*: an advertise address and cross-host auth verified end to end are
the networked part. Folding it into M5 would put a genuinely new design
decision (§4) and a two-agent acceptance record inside a document whose
status line says 2026-09-09, and would make that document the longest in
the repo. The cost of a number is that M7 now names work that is partly
debt; the roadmap says so, and the wizard and tailnet documentation that
were also "networked polish" move to M9. *(They were assigned M8 when
this was written; the retained-metrics work took that number first —
see the roadmap's §5 note.)*

---

## 0. What was verified before designing (2026-09-10, evening)

Verified with `gh`, `wsl` and `nvidia-smi`, not with CLAUDE.md.

| Repo | HEAD | Pin |
|---|---|---|
| `specs` | `3544676` | — |
| `agent` | `7565031` | `8727736` |
| `gateway` | `c43baf8` | `8727736` |
| `inference-driver` | `7fe3e1e` | `8727736` |
| `library` | `57024d6` | `8727736` |
| `control` | `ca17ba4` | `8727736` |
| `ui` | `f679fab` | `8727736` |

Every working tree clean, every CI status pending-then-green. `wsl
--status`: **not installed**, so the second host is still this box and
`scripts/m4-acceptance.sh` still has never run. `nvidia-smi -L`: **one
GPU**, the RTX 5090. `grep` over `agent/src` for `enroll`, `Runtime.node`
and any advertise address: nothing outside `_generated/` except the
docstring in `routes/node.py` saying enrollment is M5 debt.

**Four more facts, found while reading, that shape the design.** Each is
something the control repo's fake agents agreed to and a real agent would
not have.

1. **Control's rotation calls an endpoint the contract does not declare.**
   `routes/control.py::_distribute` POSTs `{signingKey, signingKeyId,
   epoch}` to each node's `POST /v1/node/rekey`. `agent.yaml` declares
   `/v1/node` and `/v1/node/enroll` and nothing else under `node`. The
   fake agents in `test_rotation_and_sealing.py` register the path by
   hand.
2. **Enrollment never tells the control root where the agent is.**
   `EnrollmentRequest` is `{token, name, publicKey, agentVersion, os,
   arch, devices}` — no URL. So `NodeRecord.url` is `None` for every
   really-enrolled node: the node poller reports *"no url recorded for
   this node"*, `POST /v1/runtimes` on the control root answers 502
   *"Node has no address"*, and the gateway's `discover_agents` drops the
   node and falls back to loopback. The control tests work around it by
   appending a **second** `enrollNode` entry carrying the URL directly to
   the log (`_enroll` in `test_topology.py` and `test_rotation_and_sealing.py`).
3. **The rekey is authenticated with a token no agent can verify.**
   `perform_rotation` swaps `auth.signing_key` to the new key *before*
   `_distribute` runs, and `_distribute` presents `node_service_token`
   — signed with the **new** key. An agent holding the old key rejects
   it; an agent holding the new key did not need it. The fakes check no
   auth. The contract already names the mechanism that should be used:
   `Enrollment.controlPublicKey` exists *"so the node can verify that
   later epoch changes come from a root it recognises rather than from
   anything that can reach its port."* Nothing signs anything with it.
4. **A second agent on this box cannot host a routable companion.** The
   agent's port is a literal `8079` in `__main__.py`; the driver's
   `EUGENE_PLEXUS_DRIVER_AGENT_URL` defaults to `loopback:8079` and the
   agent never threads its own address to children. A companion spawned
   by an agent on 8084 would resolve its `runtimeName` against the wrong
   agent and come up degraded. And the control root's forwarded `POST
   /v1/runtimes` presents `service:control`, which the agent's create
   route refuses — it is operator-only.

None of these is a fault in M5's design. All four are the gap between a
contract exercised by fakes and one exercised by the thing it describes,
which is the gap this milestone exists to close before hardware does it
the expensive way.

---

## 1. Decisions

Four scope calls, each stated with the recommendation and the main
tradeoff; the build proceeds on the recommendation because the surrounding
work is the same either way.

**1. Milestone number.** Covered above: M7, "second-host readiness";
"networked polish" becomes M9 for what remains of it — M8 when this was
written, renumbered once retained metrics shipped under that number.

**2. Where the advertise address lives** (§4). An agent config field,
`advertiseUrl`, with a derived default: when unset, the agent learns its
own reachable address at enrollment from the local end of the socket it
opens to the control root, plus its own bind port. The effective value is
persisted with the node identity and sent to the control root as the
node's URL; the control root records what it was told and derives
nothing. `Component.url` keeps its one meaning — the operator's
declaration, which the agent binds and probes — and a new read-only
`Component.advertiseUrl` carries where *peers* reach a spawned component.
Tradeoff: two URL fields on `Component` where one used to do both jobs,
against rewriting the operator's persisted declaration or making the
control root guess from a source IP that a proxy or NAT can lie about.

**3. Whether a same-box pair is worth running as an acceptance.** Yes, and
the honest boundary is drawn in §10. It **can** prove: enrollment over
real HTTP with a real join token; epoch fencing against a signed message;
fan-out from a real `/v1/nodes` with attribution by node; a stop/start for
a runtime on node B reaching node B's agent port rather than 8079; the
install signing key reaching a companion spawned after enrollment, and the
gateway's token verifying on it; a real signing-key rotation re-keying
both agents with the gateway serving afterwards. It **cannot** prove: a
genuinely offline node during a rotation (both agents share one kernel,
so "down" is a closed port, which the control suite already covers); real
clock skew; a partitioned old root (simulated by a forged lower-epoch
message, which tests the *refusal* and not the partition); any bind to a
non-loopback interface; latency. Tradeoff: a run that proves eight things
and says what it does not, against fixtures alone, which prove nothing
about the seam between components — where every prior milestone's worst
defects lived.

**4. Not reopened:** the companion driver per runtime, the gateway
deciding and the agent executing, `LogOp` closed at nine, a control root
never marked `out` automatically, admission refusing and never queueing.
Nothing below touches any of them; the one new thing the control root
sends to nodes (§5) is a signed observation, not a log entry.

---

## 2. Enrollment on the agent

`POST /v1/node/enroll` is operator-only and does what `agent.yaml` has
said since M5, in this order:

1. **409** if this agent is already enrolled. Re-enrolling elsewhere is a
   deliberate act that starts with revocation at the old root.
2. Generate the node's X25519 keypair if none exists. The private half is
   written to `node.yaml` beside `agent.yaml` and never leaves the host.
3. Resolve the advertise URL (§4).
4. Detect devices, OS and architecture — the same detector `GET /v1/node`
   uses.
5. `POST {controlUrl}/v1/nodes/enroll` with the join token, the requested
   name (default: the hostname), the public key, the advertise URL and
   the inventory.
6. On `201`, persist everything the `Enrollment` carries — name, epoch,
   the signing key and its id, `controlPublicKey`, `recoveryPublicKey` —
   with the control URL and the advertise URL.
7. **Adopt the install's signing key** into the agent's own auth state
   and **restart every supervised component**, because children read the
   key from their environment at spawn and are holding this agent's old
   random one. Engines are untouched: they have no auth.

Step 7 is what makes the install *authenticable* across hosts, which M5
§1 named as the whole problem: after it, a token minted by the control
root verifies on this agent and on every component it spawns, and a token
this agent mints verifies at the control root and on every other enrolled
host. The acceptance run checks it from both directions.

**The key is persisted in plaintext, file mode 0600, and that is a
decision.** The agent hands the signing key to every child in its
environment, so a process compromise on the host already yields it;
sealing it on disk would protect it from exactly nothing that matters
while making a headless GPU box unable to spawn a verifiable companion
until someone typed a passphrase *at that host*. The node's private key
lives in the same file for the same reason: what it protects is secrets
sealed *to this node*, whose plaintext also rides in children's
environments. `node.yaml` is therefore exactly as sensitive as the agent's
process environment, no more and no less, and the mesh VPN remains the
network boundary. The file is separate from `agent.yaml` because that
file is topology an operator edits and has already leaked once via
`git add -A`; identity is never edited by hand.

**At boot**, an enrolled agent builds its auth state from the persisted
install key rather than minting a random one, *before* it spawns anything.
That is the property M5 §8 asked for — *"a restart must stop being a
re-key"* — arriving on the agent side.

**`GET /v1/node`** now reports the enrolled shape: `name`, `publicKey`,
`controlUrl`, `epoch`, and three fields added here — `advertiseUrl`,
`signingKeyId` (so a rotation's *"which host is stale"* is answerable from
the node itself) and `controlPublicKey` (so a dashboard can show a node
trusts the root it should).

**`Runtime.node`** is filled from the identity's name on every runtime
the agent reports, and absent until enrolled, exactly as the contract
says. The gateway already joins it to `/v1/nodes` for the owning agent's
URL.

**Every node enrolls the same way, including the control host's.** M5 §2
sketched the agent on the control host *"receiving the signing key from
it locally — exactly the env-var threading that exists today."* Nothing
like that was built, and building it would be a second mechanism for the
same fact. The control host's agent mints a join token at the root it
spawned and enrolls through it; that is also what puts the control host
in `/v1/nodes` at all, which the gateway's fan-out needs.

---

## 3. What `POST /v1/runtimes` accepts, now that something forwards to it

The control root forwards a declaration to the owning node with
`service:control`. The agent's create route was operator-only, on M6's
reasoning that a leaked service token must not start a process that holds
a GPU. That reasoning still stands for *drivers* and the *library*; it
does not stand for the trust root, whose token is what the whole install's
trust reduces to. `POST /v1/runtimes` accepts the operator **or
`service:control`**, checked exactly, in the same shape as M6's
`service:gateway` on stop and start. Nothing else on the runtimes surface
changes.

---

## 4. The advertise address

Three URLs meet here and had one name.

| What | Who uses it | Today | Correct value |
|---|---|---|---|
| The agent's own address | control root (probes, forwards); gateway (lifecycle) | not recorded anywhere | reachable from other hosts |
| A spawned component's address | the agent (bind port, health probe); the gateway (`/v1/info`, `/v1/generate`) | `http://127.0.0.1:<port>`, one field for both jobs | bind locally; reachable from other hosts |
| An engine runtime's address | its companion driver, on the same host | `http://127.0.0.1:<port>` | **loopback, by design** — an engine has no auth |

### The agent's address

**`advertiseUrl`**, a config-trio field (`url`, category *Node*), editable
from the generic editor like every other knob. When set, it is the answer.
When unset, the agent **derives** it at enrollment: it opens a TCP
connection to the control root's host and port and reads the local end of
the socket, which on a mesh VPN is precisely the interface the control
root can reach back on — then appends its own bind port. The effective
value is persisted with the identity and reported on `GET /v1/node`, so an
operator can see what was derived and override it if the guess was wrong.

Considered and rejected: **the control root deriving it from the
enrollment request's source address.** Right on a flat mesh network,
wrong behind any proxy or NAT, and it would need the agent to send its
port anyway. The agent is the one that knows how it reached the root, so
the agent derives, and the control root records the URL it is told,
normalized once on the way into the log as every URL is. Also rejected:
**the hostname.** It does not resolve across a tailnet unless MagicDNS
happens to be on, and a value that works on some networks is a bug report
waiting on the others.

Changing `advertiseUrl` after enrollment changes what the agent stamps on
its components immediately; the *node's* URL at the control root is what
was recorded at enrollment and moves only on re-enrollment. §8 names the
gap.

### A spawned component's address

`Component.url` stays what the contract has said since M0: the address
the agent parses the bind port from and probes for health — the
operator's declaration, never rewritten. **`Component.advertiseUrl`** is
new, read-only, derived at read time, and present only on an agent that
has an advertise address and only for components the agent spawns: the
advertise host with that component's port. The gateway prefers it and
falls back to `url`, which is the one-line change that makes a companion
on another host reachable.

**Binding follows advertising.** A component that must be reached from
another host cannot bind loopback, so when the agent's effective advertise
host is not a loopback address it spawns components with
`EUGENE_PLEXUS_<KIND>_BIND_HOST=0.0.0.0`. All interfaces rather than the
advertise IP alone, because the agent's own health probe and the driver's
lookup of its agent stay on loopback and must keep working. Engines are
never widened: they have no auth, the companion beside them reaches them
on loopback, and reaching a model from another machine is the gateway's
job. When the advertise host *is* loopback — the same-box pair, or a
single-host install that set nothing — components bind exactly as before.

### The agent's own address, for its children

The agent now threads `EUGENE_PLEXUS_<KIND>_AGENT_URL` to every component
it spawns, as `http://127.0.0.1:<its own bind port>`. Local, deliberately:
a companion's agent is always on the same host, and the loopback default
that has been correct since M0 was only ever wrong about the *port*. This
is the fix for §0's fourth finding, and the agent's port is a bootstrap
setting now (`EUGENE_PLEXUS_AGENT_BIND_PORT`, default 8079) rather than a
literal, which is what lets two agents share a box at all.

---

## 5. Re-key, epoch fencing, and an epoch announcement

**`POST /v1/node/rekey`** is declared, and it is the one endpoint on the
agent that takes **no bearer token**. Its credential is a signature.

The body carries the new `signingKey`, its `signingKeyId`, the control
root's current `epoch`, and a **detached Ed25519 signature** over the
canonical form of those three fields, made with the control root's
identity key — the private half sealed in the snapshot, the public half
every node recorded at enrollment as `controlPublicKey`. The agent:

1. **401** unless it is enrolled and the signature verifies against the
   `controlPublicKey` it recorded. Anything that can reach the port but
   does not hold the control identity is refused here.
2. **409** if `epoch` is **lower** than the highest this agent has
   recorded. That is the fencing rule from M5 §6, now code on the side
   that does the fencing: a superseded root returning at a lower epoch is
   refused with no election and no agreement between agents.
3. **409** if the epoch is equal and the `signingKeyId` is *lower* than
   the one held — a replayed rotation from the same generation.
4. Otherwise: record the epoch and the key, adopt the key into auth
   state, and restart every supervised component so they pick it up.
   A message carrying the key the agent already holds records the epoch
   and restarts nothing.

The canonical message is the UTF-8 bytes of the JSON object
`{"epoch": <int>, "signingKey": "<base64>", "signingKeyId": "<id>"}` with
keys sorted and no whitespace — three lines on either side, and stated in
the contract so both sides implement it from the same sentence.

**Why a signature rather than fixing the bearer.** The control root could
sign the rekey request with the *old* key, and a first-time rotation would
then work. A *re-run* would not: the design requires rotation to be
resumable, and on a re-run the root does not know which nodes hold which
key. A signature by an identity that does not rotate is the credential
that stays valid across exactly the operation that invalidates every
other one, and it is what `controlPublicKey` was put in the contract for.

**Promotion announces itself.** Rule 4's *"a message carrying the key the
agent already holds records the epoch"* is what gives a promotion a
delivery path: after `POST /v1/control/promote` succeeds, the new root
sends every enrolled node a signed message carrying the **unchanged**
signing key and the **new** epoch. M5 §9 said agents *"learn the new epoch
and endpoint on their next contact"*; there was no contact that carried an
epoch. Now there is one, it is the same message as a rotation, and a node
that is `down` during it learns the epoch when the next rotation or
announcement reaches it — the bounded, visible, self-healing window §6 of
M5 accepted. Announcing is best-effort and unlogged: it delivers an
observation about the log's own epoch, and `LogOp` stays at nine.

**What a rotation does to a host, honestly.** Every component the agent
spawns restarts to pick up the new key — a companion driver is
unreachable for the second or two it takes to come back, and the gateway's
next refresh finds it. Engines keep running. The gateway itself, on the
host that spawned it, restarts too; a request in flight through it during
that second fails. That is the cost of *"rotated on an explicit operation"*
and it is paid on the operation rather than on every restart.

---

## 6. The gateway across hosts

M6 §11's first departure already put the mechanism in place: with a
`controlUrl`, the gateway reads `/v1/nodes` and then each node's agent
directly. What was missing was any test in which `/v1/nodes` returned two
nodes, and a fix for the URL a remote component is reached at.

Proven against two fake agents in-process (§10): runtimes from both agents
appear in one table, each tagged with the node that reported it; a driver
entry with an `advertiseUrl` is probed there rather than at `url`; and
the lifecycle client sends a stop for a runtime on node B to node B's URL
and never to the default agent. The live run repeats the last of those
with two real agents on two ports.

**Does the gateway's `/v1/info` probe need the service token to verify on
the remote host?** Yes, and it does, by construction rather than by
distribution: a companion spawned *after* its agent enrolled reads
`AUTH_SIGNING_KEY` from an environment the agent built from the adopted
install key. A companion spawned *before* enrollment was restarted by
enrollment. There is no separate key-distribution step for components; the
agent's own adoption plus the restart it triggers is the distribution. The
run checks the gateway lists node B's companion as reachable and serves a
completion through it, which is the only assertion that proves the token
was accepted.

---

## 7. Contract

Every change, by document. `common.yaml` is untouched, so the re-pin
radius is the consumers of `agent.yaml` and `control.yaml` — `agent`,
`control` and `ui` — with the other three bumped for levelness after a
generate-both-sides diff comes back empty.

```
agent.yaml
  POST /v1/node/rekey              new; security: [] — the credential is the
                                   signature; 401 / 409 as in §5
  RekeyRequest                     new: signingKey, signingKeyId, epoch, signature
  NodeIdentity                     + advertiseUrl, signingKeyId, controlPublicKey
  Component                        + advertiseUrl (read-only, derived)
  POST /v1/runtimes                auth: operator OR service:control
  GET /v1/config description       + advertiseUrl
  info.description                 enrollment is served; trust-root text updated

control.yaml
  EnrollmentRequest                + url — where this node's agent is reachable;
                                   what lands on Node.url
  Enrollment                       + signingKeyId
  POST /v1/nodes/enroll            description: url recorded verbatim
  POST /v1/control/rotate-key      description: the rekey is signed by the
                                   control identity
  POST /v1/control/promote         description: announces the epoch to nodes
```

**What this deliberately does not add.** No `LogOp`. No `url` on
`RuntimeSpec` (placement stays on the control root). No change to
`Runtime.url`, which is node-local by design. No `Node.role` claimed by
the enrolling agent — which node hosts the control root is not
self-detected, so `node` must still be named on the control root's `POST
/v1/runtimes`; §8. No un-enroll endpoint; §8.

---

## 8. Scope

**In:** the agent's enrollment, persisted identity, key adoption and
restart; `Runtime.node`; `advertiseUrl` on the agent with the derived
default, `Component.advertiseUrl`, bind-host and agent-URL threading to
children; the agent's bind port as a setting; the signed rekey with epoch
fencing and replay refusal; the control root recording the node URL and
signing its rekeys; promotion announcing its epoch; `service:control` on
the agent's create route; the gateway preferring `advertiseUrl` and its
two-agent tests; `scripts/m7-acceptance.sh`, parameterised for two hosts
and run against two agents on one; the re-pin.

**Out:**

- **Un-enrolling a node from the agent's side.** No endpoint. The manual
  path is revoke at the control root, delete `node.yaml`, restart the
  agent. Named rather than hidden; a readiness slice does not need it.
- **Re-advertising after enrollment.** The node's URL at the control root
  is what enrollment recorded. Changing `advertiseUrl` later moves the
  components' addresses immediately and the node's only on re-enrollment.
- **Node role self-detection.** The agent could report that it supervises
  a `control` component; it does not, so `_local_node_name` on the control
  root stays `None` until something enrolls with a control role, and
  `POST /v1/runtimes` there needs an explicit `node`. The acceptance run
  names it.
- **Sealing per-node secrets.** The mechanism exists in `control`; nothing
  on the agent unseals anything yet, because nothing on the agent holds a
  sealed secret yet.
- **A UI for any of this.** The types regenerate; no screen is built.
- **WSL2, and therefore M4's run.** Not installed; unchanged since M6.
- **Two real hosts.** §10 says what one box proves.

---

## 9. Risks

- **`node.yaml` holds the install's signing key in the clear.** Stated in
  §2 with the reasoning; a host compromise already yields it from any
  child's environment. The file is 0600 on POSIX and inherits the profile
  ACL on Windows. Anyone tempted to seal it should read §2 first and
  answer how a headless node spawns a verifiable companion at boot.
- **A rotation restarts every component on every node.** A second of
  unreachability per host per rotation, including the gateway. Acceptable
  for an operation that means "a host should no longer be trusted"; not
  acceptable as anything routine, which is why a restart stopped being
  one.
- **The derived advertise host is a guess about routing symmetry.** The
  interface used to reach the control root is the one it can reach back
  on — true on a mesh VPN, false with asymmetric routing. The value is
  reported and overridable, which is the most a guess can offer.
- **`0.0.0.0` widens every spawned component on a node that advertises a
  non-loopback address.** Components authenticate every call, so this is
  exposure of an authenticated surface, and the mesh VPN is still the
  boundary. It is nevertheless a change in posture the operator opted
  into by setting or accepting an advertise address, and the field's
  description says so.
- **Fencing is only as good as delivery.** An agent learns an epoch from
  an enrollment, a rotation or an announcement. A node that misses all
  three keeps trusting the old root until one reaches it. Bounded,
  visible on `/v1/nodes`, self-healing — and still a window.
- **This is still a security design with no adversarial review**, and it
  now has a signature scheme in it. The canonical form is three fields;
  the surface is small; it has been read by one person.

---

## 10. Verification

`scripts/m7-acceptance.sh`, written for two hosts — one running the
control root and the gateway, one running only an agent with a runtime —
and parameterised by two agent URLs. In `same-box` mode it starts both
agents itself: A on 8079 with control, gateway and library; B on 8084 with
its own config directory and nothing declared. In `two-host` mode it
expects B to be running already at the URL it is given.

1. **Enroll B over real HTTP.** A join token minted at the control root,
   bound to B's name; `POST B/v1/node/enroll`; B reports `enrolled: true`,
   the name, `epoch: 1`, the control URL, a derived `advertiseUrl` equal
   to its own URL, `signingKeyId: "1"`. The control root's `/v1/nodes`
   lists B **with a URL**, and after a poll `reachable: true` and
   `lastSeenEpoch: 1`. The token replayed is 409; enrolling B again is 409.
2. **Enroll A** the same way. Two nodes.
3. **Authenticable across hosts.** An operator token from the control
   root reads B's `/v1/runtimes`; a token B mints after enrollment reads
   the control root's `/v1/nodes`; B's *pre*-enrollment token is refused
   by B.
4. **Declare a runtime on B through the control root** with `node: B`.
   Forwarded with `service:control`, accepted by B, companion spawned by
   B after enrollment. The gateway lists the alias with `ready_backends:
   1`; the routing view attributes the backend to node B and probes it at
   its `advertiseUrl`.
5. **A completion**, attributed to B's runtime and B's companion.
6. **Idle unload crosses hosts.** The runtime declared `idleUnloadSeconds`
   and `startOnDemand`; B's agent reports it `stopped / idle`; A's agent
   has no such runtime, so the stop went to 8084 and not 8079.
7. **Wake on demand crosses hosts.** A completion for the sleeping alias
   is served with `swapped_in: true`; B's runtime is `ready` again.
8. **Rotate the signing key.** `POST /v1/control/rotate-key` at the
   control root; after re-login the rotation reads `done` with two nodes
   re-keyed; both agents report `signingKeyId: "2"`; the gateway (a child
   of A, restarted by A's re-key) comes back and serves a completion
   through B's companion (restarted by B's re-key) under the new key.
9. **Fencing.** The control identity's private key is opened from the
   snapshot with the passphrase, and a rekey carrying epoch **0** is
   signed with it and sent to B: **409**. The same body with a garbage
   signature: **401**.
10. Teardown; no `llama-server` survives.

**What this proves and does not**, printed by the script at the end so
the record cannot omit it: everything above is about HTTP between
processes on different ports with different keys, and one box is enough
for all of it. It proves nothing about a host that is genuinely
unreachable during a rotation, about clock skew, about a root that is
partitioned rather than dead, or about a component bound to a real
interface. Those were the two-machine run's — **which happened on
2026-09-11 and passed, 41 checks, discharging the non-loopback-bind item
outright; see `docs/acceptance/m7-two-host-run.md`.** This script is the one it
starts from.

Unit tests use fake control roots and fake agents as M5 and M6 did. The
live run is not skipped because the fixtures pass; §0 is four reasons
why.

---

## 11. Implementation notes (2026-09-10)

Built the same day as the design, in three repos plus a six-way re-pin,
and verified by [`scripts/m7-acceptance.sh`](../../scripts/m7-acceptance.sh)
— record in [`docs/acceptance/m7-two-agent-run.md`](../acceptance/m7-two-agent-run.md).

| Repo | Landed | What |
|---|---|---|
| `specs` | `a0d793e` | the contracts of §7, verbatim |
| `agent` | `9b0901a`, `6589820` | `node_identity.py`; enroll, re-key and the enrolled `GET /v1/node`; `advertiseUrl`; `bind_port`; `Runtime.node`; `Component.advertiseUrl`; `<KIND>_AGENT_URL` and `BIND_HOST` to children; `service:control` on create; `restart_all` skips the trust root; 304 tests |
| `control` | `48cfeb2` | `Node.url` from enrollment, `signingKeyId`, the signed re-key, the epoch announcement after promotion, the identity check before minting; 88 tests |
| `gateway` | `1484589`, `2e5544d` | prefers `advertiseUrl`; `tests/test_multi_agent.py`; refreshes serialized; 130 tests |
| `inference-driver` `library` `ui` | `907cd00` `d6ea284` `3cf98cc` | re-pin only; the `ui` gains the types and no screen |

### What the live run found

**Passed on the third run, 41 checks.** The first two runs each failed one
stage the same way and one of them left orphans; the record has the
numbers. Everything the design's §10 listed happened: both agents enrolled
over HTTP with real tokens (`/v1/nodes` carried both URLs, the field the
exchange never used to send); a control-minted token read B and a
B-minted token read the control root while each agent's pre-enrollment
session was refused; the control root forwarded a declaration to node-b
with `service:control`; the companion B spawned after enrolling was listed
and served by the gateway on the other agent; the idle unload and the wake
reached :8084; a rotation re-keyed both agents (`2/2`, generation 2) and a
completion succeeded under the new key; a genuinely signed epoch-0 re-key
was fenced with 409 and the same body with a changed epoch was 401.

**One window is open and recorded, not closed.** Twice, a request sent
about 2.5 s after the cross-host idle unload was routed to B's companion
as eligible — a 502 from the driver instead of a wake — although the
gateway had refreshed twice and read B's `/v1/runtimes` (200) after the
stop, and B itself reported `stopped/idle`. With a 4 s pause the wake
succeeded every time, and the routing view dumped at that moment showed
the driver ineligible and the runtime `stopped`. Refresh serialization
(below) was landed as a plausible cause and **did not close it**: run two
had the lock and failed the same way. `EP_WAKE_DELAY=0` reproduces it.
Candidates for the next session, in order: the snapshot the request saw
was not the one the last refresh assigned; B's runtime list parsed to
nothing for one read (`_get_json` logs that at DEBUG only, so raise it);
the driver's `/v1/info` reported no `runtime` for one probe. The M6
single-agent run never met this because its wake test paused for the
idle check first.


**Refreshes were not serialized.** Three things call the gateway's
`refresh()` — the periodic loop, the lifecycle manager after a stop, a
request that found nothing eligible — and two in flight at once is a
lost update. A periodic refresh that began before the cross-host idle
unload finished *after* the one issued once the stop returned, put the
runtime back to `ready` over `stopped`, and the next request went to a
driver whose engine was gone: a 502 where a wake should have been. Steady
state was already right, which is why no fixture caught it and why the
same completion succeeded against the still-running processes a minute
later. `refresh()` takes a lock now; snapshots land in the order the
refreshes began.

**`restart_all` restarted the control root.** Found while writing the
script rather than by running it: enrolling the control host's agent
would have restarted the root it had just enrolled with, and a restarted
root holds its keys sealed and is locked until someone logs in. The root
receives nothing from the agent's auth state — no master key, no signing
key — so the restart handed it nothing. It is skipped, on login too.

**The pid the script held was a subshell's.** `( cd a && … ) &` and the
teardown killed two subshells, orphaning both agents and an engine.
`exec` in the subshell; recorded because the same shape will recur in
the two-host script.

### Where the implementation departs from, or refines, this document

1. **The operator session that requests an enrollment dies with it.**
   §2 said the key is adopted; it did not say what that does to the
   token that asked. The same price a rotation charges at the control
   root, documented on the route: log in again, here or at the root.
2. **Two agents on one box see loopback everywhere.** The derived
   advertise host is `127.0.0.1`, so `Component.advertiseUrl` equals
   `url` and no component widens its bind. The mechanism is exercised;
   the interesting values are not, and §10 says so.
3. **Fencing was tested by forging, not by partitioning.** The control
   identity's private key was opened from the snapshot with the
   passphrase and an epoch-0 re-key signed with it; the agent answered
   409, and the same body with the epoch changed answered 401. That is
   the refusal, exactly as contracted, and not the partition.
4. **The trust root is excluded from `restart_all`** (above), which M5
   never said and which the M5 and M6 runs did not need because they
   never re-keyed anything.

### Process notes

- **A description-only contract change still changes generated code**
  (docstrings, TS comments). Consumers stay pinned at `a0d793e` through
  the docs commits, as at M6.
- **The gateway's `route_http` fixture lives in a test module**, not
  `conftest.py`; a new module needs its own copy.
- **`initialize` already restarts children once**; restart counts in
  agent tests are relative to that.
- **Routes without `response_model_exclude_none` emit `field: null`.**
  Assert `is None`, not `not in`.
- The Write tool's CRLF, the byte normalizer, patch scripts asserting
  `count == 1`: all as before, zero casualties.
