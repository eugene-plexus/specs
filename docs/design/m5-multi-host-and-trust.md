# M5 — Multi-host, trust, and the control root (design)

**Status:** designed 2026-09-09. Milestone **M5** of
[`local-inference-control-plane.md`](local-inference-control-plane.md).
Follows [M4](m4-second-engine-vllm.md), whose contracts landed and whose
implementation is **paused** for this.

**Why this jumps the queue.** Decided 2026-09-09: a project that will
support distributed deployment has to answer identity, trust direction
and failover *before* it accumulates code that assumes one host,
because retrofitting a trust model is expensive. Most installs being
single-host does not change that — it only changes how long you can get
away with postponing it. The trigger was a specific question: what stops
two hosts both claiming to be the trust root?

**Nothing here is implemented.** This is a contract-and-design milestone
like M4's first half.

Decisions taken to open it, all Troy's, 2026-09-09:

- **The watchdog splits into two components** — a **control root** and a
  **node agent** — rather than one binary with a role flag. The
  generative rule applies: supervision is per-host and there are N of
  them, while the trust root, install topology and UI are inherently one.
  Two responsibilities, two components.
- **Per-node sealing.** Secrets are sealed to the node that needs them.
  A single install-wide master key on every host is the wrong blast
  radius when the hosts are in different buildings.
- **Warm standby, log-shaped, with a replay-equivalence test.** Not Raft.
  Not state-copying either — see §5, which is the decision that keeps the
  Raft door open at low cost.

---

## 1. What is actually broken today

Multi-host is *designed* and partially built: `Component.url` is
documented as what the watchdog probes for a remote component,
`Component.spawn` being absent already means "remote, monitor only," and
the gateway resolves driver URLs from topology. The inference path is
genuinely cross-host.

It is not *authenticable* cross-host, and that is the whole problem.

From `watchdog.yaml`, job #5 is to hold **"the install's trust root"** —
singular — and:

> Component-internal calls (gateway → driver, and so on) use
> per-component service tokens: same `Authorization: Bearer …` shape,
> different audience claim, **rotated on each watchdog restart**.

So a driver spawned by watchdog B verifies tokens against **B's** signing
key, while the gateway, spawned by watchdog A, presents a token signed by
**A**. Driver B rejects it. Four consequences:

| Today | Consequence at N hosts |
|---|---|
| One signing key per watchdog, rotated on restart | Cross-host calls fail; rotation is already an undesigned distributed event |
| One master key per watchdog | Secrets sealed on host B are under B's key, unreadable elsewhere |
| `/v1/components` and `/v1/runtimes` are per-watchdog | No union view; the dashboard can only ever show one host |
| `securityMode: os_keyring` puts the master key in *that host's* keyring | Auto-unlock is inherently host-bound and cannot serve a standby |

The install is therefore not so much *capped* at one host as
**uncoordinated** beyond it: N hosts means N passphrases, N UIs, N key
domains, and manual key surgery to make the data path work.

**One property is worth stating early because the rest of this document
leans on it.** Once things are running, the data path needs no control
root: the gateway routes from topology it already holds plus driver
health, each driver holds its own config on disk, and engines are
supervised by their local agent. So a control root that dies should stop
*management*, not inference. That is a much cheaper guarantee than
consensus and a much more valuable one. **It is currently an accident, not
a designed property** — §5's test is what turns it into one.

---

## 2. The split

| | **control root** (`control`) | **node agent** (`agent`) |
|---|---|---|
| How many | exactly one active | one per host |
| Holds | trust root, install topology, node registry, the replicated log, the UI | this host's process handles, engine adapters, node private key |
| Spawns | **nothing** | every local component *and* every local engine runtime |
| Knows | the whole install | this host, plus who its control root is |

The agent is today's watchdog minus the trust root and minus
install-wide topology. It keeps the supervision machinery entirely: argv
construction, engine adapters, readiness probes, respawn, crash backoff,
log capture, safe mode. That is the code that already exists and it does
not move.

**The agent supervises the control root.** On whichever host holds it,
`control` is just another local component in that agent's topology. This
is what avoids the trap of the split: if the control root supervised
things, it would need a second copy of the supervision machinery — and
"components share schemas, not code" means a genuine second copy, not an
import. So there is exactly one supervisor implementation, running on
every host, and the control root is a supervised process like the gateway
and the library.

`ComponentKind` therefore gains `control`. The **agent does not become a
`ComponentKind`**, for the same reason the watchdog never was: it
supervises, it is not supervised. Its own lifecycle belongs to the
platform (systemd unit, container entrypoint).

**Bootstrap order,** which is not circular though it reads that way. The
agent on the control host starts first, reads local config saying it
hosts the control root, spawns it, and receives the signing key from it
locally — exactly the env-var threading that exists today. Remote agents
receive the key at enrollment instead. An agent supervises local
processes perfectly well with no signing key at all; the key gates its
*API*, not its supervision, which is what makes this order work and is
consistent with the standing degraded-mode rule.

**Repo mapping:** `watchdog` → `agent` (a rename, since that is where the
supervision code lives and history should follow it), plus a new
`control` repo. Seven live repos, six codegen consumers. Names in this
document are provisional.

---

## 3. `down` versus `out`

Borrowed from Ceph deliberately, because the distinction is exactly the
one that matters and the vocabulary is already in operators' heads.

- **down** — unreachable, expected back. Nothing is reassigned. Wait.
- **out** — not coming back. Its responsibilities must be relocated.

| Subject | `down` | `out` |
|---|---|---|
| **node agent** | its runtimes are unknown, not dead; the gateway stops routing to drivers it can't reach; the dashboard marks the node stale | operator removes the node: its runtimes are un-declared, its enrollment revoked, the signing key rotated (§8) |
| **control root** | management pauses — no config edits, no new runtimes, no enrollment, no UI login. **Inference continues.** Agents keep supervising from cached state | operator **promotes a standby** (§9) |

**A control root is never marked `out` automatically.** Ceph has
`mon_osd_down_out_interval` and turns an OSD out on a timer; we
deliberately do not, because automatic promotion without quorum is the
definition of split-brain. `down → out` for the control root is an
operator decision, always. That is the single property that makes
"two hosts both claiming root" structurally impossible rather than
merely unlikely.

---

## 4. What must survive: the replication set

A standby is undefinable until this list is exact.

| State | Lives | Survive `out`? | Why |
|---|---|---|---|
| Operator passphrase | the operator's head | n/a | the root secret; never stored |
| Argon2id **salt** | control root | **yes** | without it the same passphrase derives a different key |
| Passphrase verifier | control root | **yes** | so a standby can authenticate the operator at promotion |
| Install topology — components, nodes, declared runtimes | control root | **yes** | "what should be running where" |
| Node registry — ids, public keys, enrollment epoch | control root | **yes** | the trust graph itself |
| Service-token signing key | control root | **yes** | otherwise every node must re-enroll after promotion |
| Recovery key (sealed) | control root | **yes** | §7; the only path back to secrets on a dead node |
| Replicated log + snapshot | control root | **yes** | §5 |
| Master key / derived keys | memory only | **no** | re-derivable from passphrase + salt |
| Sealed component secrets | **with each component, on its host** | **no** | already distributed; the standby never holds them |
| UI session tokens | memory | **no** | ephemeral by design |
| Process handles, pids, engine state | each agent | **no** | inherently local |

Two useful facts fall out. **Sealed secrets are already distributed**, so
replication is a small-state problem — kilobytes of topology and
registry, not a database. And **the master key never has to exist on the
standby at rest or cross the wire to it**: promotion is manual, so the
operator is present to supply the passphrase exactly when it is needed.
That resolves the "does the master key cross a host boundary" question in
the good direction, and it is §7 that makes it stick.

---

## 5. One writer, one ordered log

**This is the decision that determines what a later move to Raft costs,
and it is nearly free to get right now.**

Two ways to replicate control state:

- **Copy the state** — ship the current topology to the standby. Simple
  today. Going Raft later is close to a rewrite: every mutation path has
  to be converted into a log entry, and ordering and idempotency get
  retrofitted onto code that assumed neither.
- **Append to a log** — every control-state change is an entry the
  standby applies in order. Raft then becomes a **swap of the transport
  and the election**, not a redesign, because the log, the apply
  function, the snapshot and the epoch already exist.

We take the log. Warm-done-log-shaped is *Raft minus voting* — the same
shape as Postgres streaming replication.

### The rule that actually has to hold

**One writer, one ordered mutation path, monotonic index.** Every
control-state change — enroll a node, revoke one, declare or delete a
runtime, patch a component's config, rotate the signing key, change
topology — goes through a single choke point that stamps an index. If
mutations write files from ten places, the door is shut.

```
LogEntry
  index    monotonic, gapless, assigned by the active control root only
  epoch    the control-root generation that appended it (§6)
  op       enrollNode | revokeNode | putComponent | deleteComponent
           | putRuntime | deleteRuntime | patchConfig | rotateSigningKey
           | promote
  payload  op-specific
  at       timestamp, informational only — never used for ordering
```

Applied state is a deterministic function of the log. The existing
topology file becomes the **snapshot**, so a new standby does not replay
history from the beginning and the log can be compacted. Timestamps are
never load-bearing; index is the only ordering, which keeps clock skew
between buildings out of the correctness argument.

### The commit rule, and where Raft would change it

Warm commits when **the active root has applied it**, then ships to
standbys asynchronously. Raft commits when **a majority has
acknowledged**. That is a change to *when a caller is told their write
succeeded* — a change in one function, not in the data model.

What Raft would add, for the record: quorum commit, timeout-driven leader
election in place of manual promotion, joint-consensus membership
changes, and a 3-node minimum. What it would **not** add: identity,
enrollment, sealing, epochs, snapshots, or the log — all of which are
here already.

A practical note that belongs in the decision rather than a footnote:
mature Raft implementations are Go and Rust (etcd, hashicorp/raft, tikv).
For Python components, "go hot" realistically means an external sidecar
dependency or writing consensus by hand, and consensus bugs are the worst
class of bug to own. This is a cost that shrinks to zero if it is never
needed, which for a self-hosted inference control plane is the likely
case — and if it *is* needed, a single process with a small log-shaped
state directory is also easy for an operator's existing HA to manage
(VM live migration, shared storage, a one-replica Deployment). Ceph
implements quorum because Ceph *is* the storage layer and has nothing to
stand on. We have something to stand on.

### The test that makes promotion trustworthy

**Replay equivalence: a standby's applied state must be byte-identical to
the active root's after applying the same log.** This is the property
that makes a promotion safe rather than hopeful, it is what would later
let Raft be dropped in underneath, and it is exactly the kind of
invariant that rots silently if nothing asserts it. It is a required
deliverable of this milestone, not a nice-to-have.

Second required test, because §1 called the surviving-data-path an
accident: **kill the control root and assert that a chat completion still
succeeds** through the gateway to a running engine. That turns the
property into a guarantee.

---

## 6. Epoch fencing

Manual promotion leaves one hole: the old root comes back, and now two
processes believe they are root. The fix needs no consensus.

**Every control root carries a monotonic `epoch`. Agents record the
highest epoch they have seen and refuse to go backwards.**

- Promotion increments the epoch.
- An agent presented with a *lower* epoch than its recorded one rejects
  the caller outright.
- The returning old root, at epoch 5 against agents at 6, is fenced
  permanently. No election, no quorum, and **no agent has to agree with
  any other agent** — each independently declines a downgrade.

This is Raft's term and Ceph's MON epoch doing the one job we need. Since
the log's entries already carry `epoch`, a standby can also reject log
entries from a superseded root.

**The honest caveat, stated in the doc rather than discovered later:** an
agent partitioned *during* a promotion still trusts the old root until it
reconnects, and until then the old root can command it. Blast radius is
the partitioned nodes only; it is operator-visible, because
`GET /v1/nodes` reports each node's last-seen epoch and a disagreement is
right there on the dashboard; and it resolves on reconnect. That is the
price of no quorum, and it is a fraction of quorum's cost. **Do not
"fix" this with automatic promotion** — that trades a visible, bounded,
self-healing window for genuine split-brain.

---

## 7. Per-node sealing

The current model threads one install-wide master key to every spawned
child. Extended across hosts, that means one compromised GPU box in
another building yields **every secret in the install**. With "GPUs in
different physical buildings, internet-connected only" as a stated
deployment target, that is the wrong blast radius.

Instead:

- **Each node has an identity keypair**, generated at enrollment. The
  private key never leaves the node.
- A secret entered in the UI is **sealed to the node whose component will
  read it**. Topology already says which node a component runs on, so the
  control root knows the recipient without asking.
- The agent unseals with its node private key and threads plaintext to
  its children — the same env-var mechanism as today, sourced from a
  different key.
- **The control root never holds the plaintext, and never holds a key that
  can read every node's secrets in normal operation.**

### The recovery recipient

Sealing only to the node makes a dead node's secrets unrecoverable. So
every secret is sealed to **two recipients**: the target node, and a
**recovery key** held by the control root — itself sealed under the
passphrase-derived key and unsealed *only* during an explicit recovery or
re-seal. Normal operation never decrypts a secret at the control root.

Blast radius, stated plainly:

| Compromise | Yields |
|---|---|
| One node | that node's secrets only |
| Control root process | nothing directly — the recovery key is sealed under the passphrase |
| Control root **and** the passphrase | everything. This is unavoidable and is what the passphrase *is* |

`securityMode` keeps its two options per node, and the tension named in
§1 becomes explicit: `os_keyring` is host-bound, so a standby control
root cannot inherit auto-unlock and will require the passphrase at
promotion. That is consistent with promotion being a human act anyway.

---

## 8. Enrollment, revocation, and rotation

**Enrollment.** The operator mints a join token at the control root:
short-lived, single-use, and scoped to one node. The new agent generates
its keypair, presents the token and its public key, and receives back its
node id, the service-token signing key, the current epoch, and the subset
of topology it needs. The exchange is one `enrollNode` log entry. A mesh
VPN remains the network boundary — this sits on top of it rather than
replacing it, unchanged from the standing commitment.

**Revocation is a rotation, not a deletion.** This is the part that is
easy to get wrong: a revoked node still *holds* the signing key, so
removing its registry entry does not stop it authenticating to other
components. Revoking a node therefore means **rotating the signing key
and redistributing it to every remaining node**, then bumping the epoch.
Which is why rotation has to be a first-class distributed operation with
its own log entry rather than the incidental restart-time behaviour it is
today.

**Rotation** consequently needs to tolerate nodes that are `down` during
it: they are re-keyed on reconnect, and until then they hold a
superseded key and are refused. The current contract's "rotated on each
watchdog restart" becomes "rotated on an explicit operation, and on
revocation" — a restart must stop being a re-key, because with N nodes a
restart re-keying everything is an outage.

---

## 9. Promotion

An operator action, never a timer.

1. Operator picks a standby and calls promote, supplying the passphrase.
2. The standby verifies the passphrase against the replicated verifier,
   derives the master key from the replicated salt, and confirms its
   applied index is at least the last index it received.
3. It increments the epoch, appends a `promote` entry, and begins
   accepting writes.
4. Agents learn the new epoch and endpoint on their next contact and
   record it, fencing the old root by §6.

A standby that is behind reports how far behind before promoting, and the
operator decides. **Refusing to promote is a valid outcome** — a standby
that cannot prove its state is better than no standby, and silently
promoting a stale one is how a control plane loses a node registry.

---

## 10. Contract sketch

```
common.yaml
  ComponentKind      + control
  ConfigValueType    + node_name      (dropdown from GET /v1/nodes)

agent.yaml   (was watchdog.yaml — supervision surface, minus the trust root)
  /v1/runtimes …            unchanged, but scoped to THIS host
  /v1/engines …             unchanged, scoped to this host
  /v1/components …          local components only
  /v1/node                  this node's id, epoch, control-root endpoint,
                            accelerators, agent version
  /v1/node/enroll           accept a join token, generate keypair (bootstrap)

control.yaml (new)
  /v1/nodes                 the install's nodes, each with role, reachability,
                            last-seen epoch, accelerators
  /v1/nodes/{id}            one node
  /v1/nodes/join-token      mint a scoped single-use token
  DELETE /v1/nodes/{id}     revoke -> rotates the signing key (§8)
  /v1/runtimes              UNION across nodes, each tagged with node
  /v1/components            install-wide topology
  /v1/control/status        epoch, role, applied index, standbys and their lag
  /v1/control/promote       operator action, passphrase required (§9)
  /v1/control/rotate-key    explicit signing-key rotation
  /v1/auth/*                moves here from the watchdog
  /v1/config{,/schema}      the standard trio

Runtime       + node        which host it runs on
RuntimeSpec   + node        where to place it; defaults to the local node
Node          id, name, url, role: control|standby|agent, reachable,
              agentVersion, os, arch, accelerators[], publicKey,
              lastSeenEpoch, enrolledAt
```

Two notes on shape. **A host is not a component** — the same reasoning
that made engine processes `runtimes` in their own collection rather than
components applies again, so nodes get `/v1/nodes` and not a
`ComponentKind`. And **`Node.accelerators` is the cross-host hardware
inventory M3 deferred**, landing precisely where M3 predicted it would:
*"building a real inventory is topology work and belongs to the watchdog
if it belongs anywhere."* The library's fit surface already takes a
hardware override and reports which host it measured, so multi-host fit
scoring works the moment nodes exist — that is pre-wiring, not
retrofitting.

M4's `runtimeName` resolution becomes node-local: a driver follows a
runtime through *its own* agent, which is correct because a driver lives
next to its engine. One clarifying sentence, no redesign.

---

## 11. Scope

**In:** the component split, node identity and enrollment, per-node
sealing with a recovery recipient, the single-writer ordered log plus
snapshot, epoch fencing, warm standby replication, operator-driven
promotion, explicit signing-key rotation, revocation-as-rotation,
`Node.accelerators`, the union runtime view, and the two required tests
of §5.

**Out:**

- **Raft, quorum, and automatic promotion.** Deliberate and documented,
  not deferred by neglect. §5 records the upgrade path; §3 and §6 record
  why automation without quorum is worse than manual.
- **More than one standby being *required*.** N standbys is a
  configuration, not a mechanism.
- **Cross-building network design.** The mesh VPN commitment already owns
  it.
- **Multi-writer control state.** One writer is load-bearing, not a
  simplification to be relaxed later.
- **Migrating an existing single-host install.** A fresh-install story
  first; migration once the shape is proven.
- **Secret sharing between nodes.** A secret belongs to the node that
  reads it; two components on two hosts needing the same credential means
  two sealed copies.
- **Hardware-aware *placement*.** `Node.accelerators` reports; deciding
  which node should host a model is lifecycle policy, now M6.

---

## 12. Risks

- **This is a security design and it has had no adversarial review.**
  The largest risk on the page. Enrollment, rotation and the sealing
  recipients each have failure modes that are invisible until someone
  attacks them, and none of it has been implemented, let alone attacked.
- **Revocation-as-rotation is the sharp edge.** If rotation is
  incomplete — a node `down` during it, a partial redistribution — the
  install is left in a mixed-key state where some legitimate calls fail
  and a revoked node may still be trusted somewhere. This needs to be
  idempotent and resumable, and it needs a test that revokes a node while
  another is offline.
- **The partition window in §6 is real,** and the temptation to close it
  with automatic promotion will recur. It is written down precisely so
  that the argument does not have to be rediscovered.
- **The single-box install pays for all of this.** A one-host user now
  runs an agent *and* a control root where one watchdog sufficed — six
  processes instead of five, for machinery whose value they will never
  see. That is the real cost of the split and it should be measured, not
  assumed away: if the first-run experience gets worse, the product gets
  worse, and differentiator #5 was "networked-first" rather than
  "networked-only".
- **Two renames and a new repo, on a codebase that just landed M4's
  contracts.** `watchdog` → `agent` moves the Python package, the
  `EUGENE_PLEXUS_WATCHDOG` env prefix, the kind→module map and the
  codegen wiring. The last two renames sat undone for four milestones and
  were cited as fact while stale; this one should be executed or
  explicitly deferred, not left ambiguous.
- **`os_keyring` and HA are in tension** (§7) and the wizard will have to
  say so in words an operator understands, rather than offering both and
  letting them discover it at promotion time.
