# Running Eugene Plexus over a tailnet

**For:** an operator putting an install on more than one machine, or on a
machine that is not the one in front of them. Everything here has been
run on real hardware — Windows and WSL2 Ubuntu, across NAT and a host
firewall, 2026-09-11
([record](../acceptance/m7-two-host-run.md)).

**What a tailnet buys you.** Every machine gets a stable private address
that works from anywhere, with no port forwarding, no dynamic DNS, and no
listening socket on the public internet. That matters here because
Eugene Plexus is a *networked* control plane — a gateway on your desktop
routing to a GPU box in another building is the shape it was built for —
and because **nothing in it is written to survive the open internet.**
See [What not to expose](#what-not-to-expose); that sentence is load
bearing.

This document covers Tailscale by name because it is what the project is
tested on. Plain WireGuard works the same way; substitute your own
addresses.

---

## The shape

```
┌─ machine A ────────────────────────┐      ┌─ machine B ───────────────┐
│  agent            :8079  0.0.0.0   │      │  agent          :8084 wide│
│   ├─ control      :8083  0.0.0.0   │◄────►│   ├─ companion driver wide│
│   ├─ gateway      :8080  0.0.0.0   │      │   └─ engine     127.0.0.1 │
│   └─ library      :8082  0.0.0.0   │      └───────────────────────────┘
└────────────────────────────────────┘          tailnet 100.64.0.0/10
```

One **agent per machine**. One **control root** in the whole install, plus
any number of warm standbys. One **gateway**, which is the address you
point clients at. **Engines never leave loopback** — see
[Engines are never widened](#engines-are-never-widened).

---

## 1. Machine A — the first one

Install Tailscale and bring it up, then note the address:

```bash
tailscale up
tailscale ip -4          # e.g. 100.64.0.1
```

**Set the advertise address before the first start.** This is the single
most important instruction in this document, and it cost an hour to
discover:

```bash
export EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0
```

and put the address in the agent's config so it survives restarts —
`agent.yaml`, beside wherever you point `EUGENE_PLEXUS_AGENT_CONFIG_FILE`:

```yaml
advertiseUrl: http://100.64.0.1:8079
```

Then start it:

```bash
eugene-plexus-agent
```

On a genuinely fresh machine with a terminal attached it asks one
question — *new install, or join an existing one?* Answer **new**. It
then declares the control root, the gateway and the library itself, and
starts them. Open `http://100.64.0.1:8079` in a browser and finish the
first-run wizard: set a passphrase, point at your model directories.

### Why the advertise address must be set *first*

A component binds `0.0.0.0` **only when its node advertises a
non-loopback address.** That rule is what keeps a single-machine install
from putting four services on every interface it has, and it is
evaluated when a component is spawned.

Enrollment deliberately **does not restart the control root** — it is the
trust root, and bouncing it during a trust operation is exactly the wrong
moment. So if you discover the advertise address late and set it
afterwards, every other component picks it up on the next restart and
**the control root stays on loopback**, unreachable from any other
machine, in an install that otherwise looks healthy.

If you have already made that mistake: set `advertiseUrl`, then restart
the agent. The control root comes back wide with everything else.

---

## 2. Machine B — every machine after the first

Same package, same command, same entry point. **There is no separate
"worker" build.**

On A, open the UI and go to **Nodes → Add a node**. Mint a token; the
screen renders the exact command. On B:

```bash
tailscale up
export EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0
eugene-plexus-agent join \
  --control http://100.64.0.1:8083 \
  --token <the token> \
  --name gpu-box
eugene-plexus-agent
```

`join` enrolls, writes `node.yaml`, and exits. The start after it finds
an enrolled node and **does not declare a control plane of its own** —
which is the whole point, because a second control root in one install is
the failure the design refuses.

Three ways to answer the same question, pick whichever fits:

| Path | When |
|---|---|
| the first-boot prompt | you are at a terminal on the machine |
| `eugene-plexus-agent join` | provisioning, Ansible, a setup script |
| `EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY=0` | a systemd unit or a container |

**A start with no terminal seeds a new install.** A container must never
block on a question, so with no TTY the agent does what it has always
done. That is right for the overwhelmingly common single-machine case,
and a spurious control plane is recoverable — an agent hung at boot
waiting for a terminal nobody is watching is not. If B is provisioned by
a service unit, use `join` or the environment variable.

**You do not need to set `advertiseUrl` on B.** With none configured, the
agent derives it from the local end of the TCP connection it used to
reach the control root — on a mesh VPN that is precisely the interface
the root can reach back on. Set it by hand when that is wrong, which
means: when B is behind NAT that the root cannot traverse, or when it has
several interfaces and the route to the root is not the one other
machines use. `GET /v1/node` reports what it derived, so a wrong guess is
visible rather than silent.

### If a machine's address changes

It tells the root, on every start and whenever `advertiseUrl` changes.
Nothing to do. Before this existed (M9, 2026-09-11) an address was
announced exactly once, at enrollment, and a host that rebooted onto a
new address left the root holding one nobody was listening on — with no
way back, because the only address the root had was the stale one.

A tailnet address is stable **until the user reinstalls Tailscale**,
which is exactly the case this protects.

---

## 3. Engines are never widened

`llama-server` and `vllm serve` bind loopback even on a machine where
every component is wide open. This looks like an oversight and is not.

An engine is reached by **its own companion driver, on its own host** —
since M6 the agent declares one driver per runtime, beside it. Nothing
on another machine ever talks to an engine directly; it talks to the
gateway, which talks to a driver, which talks to the engine over
loopback. So widening an engine would add an unauthenticated inference
endpoint to your tailnet and buy nothing: **engines have no auth at
all.** They are upstream projects we supervise, not components we wrote.

The two-host run confirmed this holds in practice: `vllm serve` on B was
spawned `--host 127.0.0.1` while B's companion driver bound `0.0.0.0`.

---

## 4. The three auth surfaces are not interchangeable

An operator who assumes one token opens everything will be confused in a
way the API cannot fix. There are three, and they exist for different
reasons.

**The operator passphrase.** One per install, set at first run, typed by
a human. It derives the master key that unwraps at-rest secrets and it is
what `POST /v1/auth/login` takes. Both the agent and the control root
have to be given it — the control root mints its own auth, deliberately,
and nothing else can set its passphrase for it. Until it has one it
answers **503 across its entire surface**: an uninitialized trust root
does not fall open.

**Service tokens.** Minted from the install's signing key and handed to
each component in its environment at spawn. This is what lets a gateway
on A authenticate to a driver on B — one signing key for the whole
install, which is precisely what a single-supervisor install could not
do. A service token names a **kind**, not a host.

**The control identity's signature.** Used for exactly two operations,
and never a bearer for either:

- `POST /v1/node/rekey` — the root proves itself to a node. A rotation
  invalidates every service token in the install, *including any the root
  could present*, so a bearer cannot survive the operation that needs it.
- `PATCH /v1/nodes/{name}` — a node proves itself to the root, signed
  with the node's own identity key. Same argument in the other direction,
  plus: a service token names a kind, so any agent could otherwise
  re-address any node.

**Consequences worth knowing before they surprise you:**

- **Enrolling a node logs out the operator session that asked for it**,
  on that node. The key it was signed with has been replaced by the
  install's. Log in again — at that node or at the control root; both now
  mint tokens it accepts.
- **Rotating the signing key logs everyone out**, for the same reason.
- **Revoking a node is a rotation, not a deletion.** A revoked node still
  *holds* the signing key, so removing its registry entry would not stop
  it authenticating. `DELETE /v1/nodes/{name}` re-mints the key and
  redistributes it, which means nodes that are down during the rotation
  hold a superseded key until they reconnect.

### Detaching a machine

Two operations, each local to the thing whose keys are changing:

```bash
# On the machine leaving. Discards the install's key and returns the
# node to its own; tells the root on the way out, and proceeds anyway
# if the root is gone.
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://100.64.0.7:8079/v1/node/unenroll
```

Un-enrolling is safe to run from the node because it **discards** the
signing key — the opposite direction from revocation. A node cannot
escape revocation this way; it can only disarm itself. Read
`controlNotified` in the response: `false` means the install still lists
this node and still trusts the key it just threw away, and you owe the
root a `DELETE /v1/nodes/<name>`.

---

## 5. What not to expose

**The tailnet is the perimeter.** The auth layer sits on top of it and
does not replace it. Concretely, do not put any of these on a public
interface:

| Port | What | Why not |
|---|---|---|
| 8079 | agent | supervises processes and spawns binaries |
| 8080 | gateway | your inference endpoint, and your bill if a provider key is behind it |
| 8082 | library | reads and writes paths on your disk |
| 8083 | control | the trust root |
| engine ports | `llama-server`, `vllm serve` | **no authentication whatsoever** |

If you want the playground reachable from a phone, put the phone on the
tailnet. That is a one-line install on iOS and Android and it is the
answer this project is designed around.

**Tailscale ACLs are worth setting** even inside the tailnet, if the
tailnet has machines that are not part of this install. The components
authenticate each other; they do not authorize by source address.

**`tailscale serve` / Funnel:** do not use Funnel to put any of the above
on the public internet. `serve` inside the tailnet is fine and buys you
HTTPS with a real certificate, which is worth having if browsers on your
network complain about mixed content.

---

## 6. Checking it worked

From another machine on the tailnet:

```bash
# The node registry: every machine, its address, and whether the root
# can reach it.
curl -s -H "Authorization: Bearer $TOKEN" http://100.64.0.1:8083/v1/nodes | jq

# The install-wide component view, assembled by asking every node.
# A machine that does not answer lands in `unreachableNodes` rather than
# silently contributing nothing.
curl -s -H "Authorization: Bearer $TOKEN" http://100.64.0.1:8083/v1/components | jq

# What is actually bound wide, on the machine itself.
netstat -an | grep -E '8079|8080|8082|8083'
```

The UI's **Nodes** page shows the same registry, including which node the
root cannot currently reach and whether any node is behind on the epoch —
the visible symptom of a machine that was partitioned during a promotion.
That window is real, bounded to the partitioned machines, and
self-healing; it is surfaced rather than hidden, because the price of
having no quorum is a window you can see.

### Common symptoms

| Symptom | Cause |
|---|---|
| A node shows `none recorded` as its address | It enrolled before it had an address to give. Set `advertiseUrl` and restart, or re-enroll. |
| The control root is unreachable from B, everything else is fine | `advertiseUrl` was set after the first start. Enrollment does not restart the root. Restart the agent on A. |
| A node is `down` but the machine is up | Its address changed and it has not announced, or it enrolled before nodes carried a signing identity — re-enroll it. |
| Every call to the control root is 503 | It has no passphrase yet. Finish the first-run wizard, or `POST /v1/auth/initialize`. |
| A node's re-advertisement is refused 401 | It enrolled before M9. Its model files and runtimes are untouched by re-enrolling. |

---

## 7. What is still unproven

Stated because an operator deserves to know where the tested ground
stops.

- **Two hosts is proven; three is not.** Nothing in the design is
  two-specific, but nobody has run it.
- **An offline-node rotation** — revoking while a node is genuinely
  powered off — needs independent power and has not been run.
- **Clock skew between buildings.** Log ordering is by index and never by
  timestamp, deliberately, so this should not matter. Untested.
- **A partitioned-but-alive old control root**, as opposed to a shut-down
  one. Epoch fencing exists for exactly this and has only been exercised
  against a root that was stopped.
- **Two GPUs in one machine**, and AMD, Intel or Apple unified memory
  detection on real hardware.

---

## See also

- [`m5-multi-host-and-trust.md`](../design/m5-multi-host-and-trust.md) —
  why the control root and the node agent are separate components, and
  why a root is never marked `out` automatically.
- [`m7-second-host-readiness.md`](../design/m7-second-host-readiness.md) —
  enrollment, the signed re-key, and advertise addresses.
- [`m9-networked-polish.md`](../design/m9-networked-polish.md) —
  un-enrolling, re-advertising, and the onboarding question.
- [`m7-two-host-run.md`](../acceptance/m7-two-host-run.md) — the run this
  document is written from.
