# Row 4: agents learn a promoted root's address

Read at agent `74d8427` and control `f083a3c`. This row uses row 3's door file.

**What happens today**
- `node.yaml` `controlUrl` is set at enrolment and never changes.
- Promotion pushes a bundle carrying the new epoch (`C/routes/control.py:271`), but the bundle carries no address. Agents keep pulling from the dead root.
- The promoted copy stays the `standby` component. `is_standby()` keeps it out of `active_control_entry` (`A/standby.py:46`), so no machine can reach it.
- **LT-OLDSB.** A standby that ran pre-LT1 code holds no `tlsPins`. Nothing notices that its state differs from the root's.

## 1. What it delivers

- After a promotion, every machine that can reach the new root follows it within a minute. That covers sign-in, announcements, trust pulls and topology reads.
- A machine that was off during the promotion finds the new root when it returns.
- The promoted copy is reached through its machine's port, without a restart, so it does not come back sealed.
- A standby whose copy differs from the root's takes a fresh snapshot by itself. Machines shows the standby's version and which machines still follow the old root.

## 2. The design

**Contract**
- `control.yaml` `MachineList.control` `{epoch, node, url}`. `url` is the plain form `http://<host>:<machine port>`, which machine tables carry to TLS, or the root's nodes name. It is taken from the door file or from `nodes_origin`.
- `control.yaml` `LogPage.appliedDigest`: the SHA-256 of the canonical applied state at `appliedIndex`, cached per index.
- `control.yaml` `StandbyStatus.version`, taken from an `Eugene-Plexus-Version` header on each pull. Also `StandbyStatus.matches`.
- `agent.yaml` `POST /v1/node/machine-list`, the mirror of the trust-bundle push. It has no bearer: the signature is the credential. It answers 409 when the version is older or the epoch is lower.
- `agent.yaml` `NodeIdentity.controlUrlEpoch`.

**Agent**
- **`controlUrlEpoch`.** When it is missing at load, it is set to the epoch held, so an upgrade never moves a node.
- **When a node moves.** `machine_trust.accept` moves the node only when all of these hold:
  - the list verifies;
  - it is newer than the one held;
  - its `control.epoch` is above `controlUrlEpoch`;
  - its `control.epoch` is at least the epoch held.
- **What a move does.** The agent writes `controlUrl` and `controlUrlEpoch`, rebuilds the table, announces again (so the new root records its pins), pulls the bundle, and logs *the install's root moved to B (epoch 3)*.

  **The same epoch never moves a node.** A node may reach its root at an address the root does not know, such as a tailnet address.
- **Fallback.** After 2 minutes of failed pulls, the agent asks the machine that held the `standby` grant in its last bundle. It sends `GET https://<that door>/control/v1/trust/machines`, pinned to that machine's key, and judges the answer by the same rules. A copy that is still a standby has no route, so the request goes nowhere.
- **`standby.py`.** When the copy answers `role: control` and the grant is gone, the agent persists `standbyPromoted: true`. `is_standby()` then returns false, so `active_control_entry`, `/control` and the door file all point at the copy. Nothing restarts. Deletion still waits for `role: standby`.

**Control**
- After `promote`, `trust.publish` is followed by a new `push_machine_list`, over pinned TLS. The promoted copy holds every node's pins.
- The probe loop pushes the bundle and the list to any reachable node that reports a lower epoch, at most once a minute.
- **`replication.py`.** The follower sends its version. Once caught up, it compares digests. If they differ, it logs *"this copy differs from the root at index N; taking a fresh snapshot"* and takes one, at most once in 10 minutes. If the copy still differs after that, it reports `matches: false`.

**Order on a promotion**
1. The owner promotes B with the passphrase.
2. B's control moves to epoch E+1, signs a bundle and a list, and pushes both.
3. B's agent marks its copy promoted. A node that dials B in the few seconds before then gets a 404 and moves at its next pull.
4. Each agent takes the epoch, then the list. It moves, announces and pulls.
5. A node that was off moves within 2 minutes of its return, by push or by fallback.
6. The old root, started again, signs at epoch E. Every node answers 409, its own agent included. Stopping or demoting the old root is left to automatic takeover.

**Failures**
- *"Refused machine list: epoch 2 is below the 3 this node holds."*
- *"Cannot reach the root at http://B:8083: connection refused."* This shows on the node's own console, and the node keeps trying.
- A failed snapshot leaves `last_error` set, in the root's words.

**UI** (Machines and `StandbyPanel.tsx`)
- *Root: B, since 21 Oct, 14:02, took over from NAS.*
- *Still follows the old root; it moves when it next answers.* Shown when `lastSeenEpoch` is lower than the root's.
- *Standby · runs v0.3.0, older than the root; update it*, with the existing Update button.
- *Standby · its copy differed from the root; took a fresh copy at 14:05.*

**Defaults and calls**
- Nothing new is configured.
- **Flag:** a digest mismatch replaces the standby's copy. The standby never writes, so it loses nothing.
- **Recommended:** keep a same-epoch move, such as the root's own DHCP change, out of scope, for the tailnet reason above.

## 3. Repositories and files

- **control:** `machine_list.py`, `trust.py`, `replication.py`, `routes/control.py`, `nodes_client.py`, `app.py`.
- **agent:** `node_identity.py`, `machine_trust.py`, `standby.py`, `machine_port.py`, `routes/node.py`, `app.py`.
- **ui:** `app/nodes/page.tsx`, `components/StandbyPanel.tsx`, `lib/standby.ts`.
- **specs:** both yaml files, `warm-standby.md` §7, and a new harness.

**Codegen:** `control.yaml` is consumed by control and ui. `agent.yaml` is consumed by agent, control and ui.

## 4. The tests that fail first

**`agent/tests/test_root_moved.py::test_higher_epoch_list_moves_control_url_and_reannounces`**
- A list at epoch 3 naming B moves the node, and the node announces to B.
- A list at epoch 2 is refused.
- A list at the same epoch with another URL does not move the node.

**`agent/tests/test_standby.py::test_promoted_copy_is_the_active_control_entry`**
- `/control` reaches the copy.
- Nothing was started.

**`control/tests/test_replication.py::test_replica_that_differs_takes_a_snapshot`**
- A replica whose nodes lack `tlsPins` re-snapshots and then holds the pins.

## 5. Acceptance (CI, high risk)

`specs/scripts/root-moved-acceptance.py`, built on the LT1 Docker harness, runs on Linux runners with all ports inside containers. Four machines:
- A, the root;
- B, the standby, seeded with a snapshot that has no pins;
- C, a worker with the gateway grant and a stub engine;
- D, a worker.

The checks:
1. B takes a fresh copy.
2. With D and A stopped, promote B through its console.
3. Within 60 s, C names B as its root. Sign-in and prompts through C work. B's list carries C's pins.
4. D, once started, moves within 2 minutes.
5. A, once restarted, is refused by C and D.

About 10 minutes.

**The reviewer should attack:** any path that signs a higher epoch without a `promote` entry (the epoch is only as strong as the identity key, which the old and new roots share); the fallback as a way to redirect a node; an old promotion's list, replayed; canonicalisation that differs between versions and loops re-snapshots; a standby that sets the promoted flag.

## 6. Do not change (hot for other lanes)

- **`agent/tokens.py`** (row 35). The address must not ride the bundle, which is the vendored token module.
- `agent/__main__.py` (row 2).
- `agent/reach.py` (row 8).
- `control/client_admission.py` (rows 11, 24, 40).
- `settingsTopics.ts`, `ResourceTree.tsx` and `resourceTree.ts` (row 33).
- `ConfigField.tsx` (row 62).
- `*/scripts/codegen.py` (row 1).

## 7. Size, risks, split

**Size:** M-L.

**Split:**
- **4a, the root moves (M):** the `control` block, the push, the move, the fallback and the promoted copy.
- **4b, the copy matches (S):** the digest, the version and the status. Row 5 needs 4b.

**Risks:**
- A Windows standby gets one run by hand.
- Digest cost is held down by caching per index.

## Calls answered by Troy (2026-10-21)

- **R4-MOVE: Choice 1.** Machines follow a new root address only with a promotion.

## What building found (2026-10-22)

Built on branch `r4-promoted-root` in specs, control and agent. UI not built
(see the last item).

**The contract as built**
- `control.yaml`: `MachineList.control` (`MachineListControl`: `epoch`,
  `node`, `url`, the last two nullable); `LogPage.appliedDigest`;
  `StandbyStatus.version` and `StandbyStatus.matches`; the
  `Eugene-Plexus-Version` header (the standby's on its pulls, the root's on a
  log page) and `Eugene-Plexus-Copy-Digest` (the standby's digest at `after`).
- `agent.yaml`: `POST /v1/node/machine-list` (204; 401 for a list not signed
  by the pinned root; 409 for an older list or a lower epoch) and
  `NodeIdentity.controlUrlEpoch`. The body schema is `SignedMachineList`, a
  copy of control's, because agent.yaml does not reference control.yaml.
- The specs branch merges `ac04e63` (row 17's contract): agent main pins it
  and specs main does not have it yet, so a pin of this branch from main
  alone would have taken row 17's fields out of the agent.

**Decisions made while building**
- **Two lists that name roots at different epochs are ordered by epoch, not
  by version.** Each root numbers its own lists, and an old root that kept
  writing could out-number the new one. A list with no `control` block (a
  root older than row 4) is ordered by version as before.
- **A list at an epoch above the one a node holds raises it**, even when the
  node cannot move (the list names no address, or a loopback or link-local
  one). The list is signed by the same identity as the bundle, so it fences
  the old root the same way.
- **A move drops the join token's root pin** (`controlPins` in `node.yaml`):
  it was the old root's key; the new root's list names its own.
- **The promoted mark is `standbyPromoted` in `agent.yaml`**, beside the
  entry it is about, and it goes with the entry. It is set only when the copy
  answers `role: control` at epoch N and the machine list held (signed)
  names this machine the root at N. A copy that answers `control` without a
  promotion (one started without its role) is not taken for the root.
  `is_standby()` still names the copy, so the planner keeps its wiring (its
  state directory and node name) and a restart starts it as the root on the
  same copy; `standby.promoted()` and `is_root()` decide the routes.
- **The promoted copy starts its node poller** (and the TLS-key watch when it
  has a nodes name) at the promotion: nothing restarts it, and before this
  row a promoted copy never polled.
- **A root pushes to a node behind only on `controlUrlEpoch` when its list
  names an address**; otherwise that node cannot move and the push would
  repeat every minute for nothing. A node behind on `epoch` is always sent
  the bundle again.
- **The fallback remembers the last standby holder.** A promotion takes the
  grant, so the new root's bundle names none. A node that restarts after
  taking the new root's bundle but not its list has no holder to ask; the
  new root's poll still reaches it.
- **4b compares only on one version.** The root's version rides the log page
  as a header; a standby on another version does not compare, and the root
  does not judge its copy (`matches` absent). Otherwise a rolling update
  replaces the copy every 10 minutes and reports it different. The root
  computes `matches` itself, from the copy's digest at its own index; a pull
  behind the root keeps the last answer.
- **"Cannot reach the root at ..."** is in the node's log, said once per
  silence. No field carries it to the console yet.

**Acceptance.** `specs/scripts/root-moved-acceptance.py` runs in Pinned
integration on Linux and Windows (L1 and W3, every profile), not on the LT1
Docker harness: Windows runners cannot run Linux containers, and the shared
harness's real start path gives each agent its machine port on a free port.
The four agents advertise the runner's routable address, each on its own
ports, so every call between them crosses a machine table to a machine port.
The promotion is called at the copy's loopback port, not through the
console. `standby-acceptance.py` step 7 now expects B's agent to report
`hostsControl` and no standby after the promotion. Sabotage: ten new checks
(the epoch rule, the fence, the loopback refusal, both conditions of the
promoted mark, the 2-minute wait, both version gates, the 10-minute limit,
the once-a-minute push), each caught by its unit test.

**Not changed**
- The bundle's own rule (`tokens.accepts_replacement`, row 35's file)
  refuses a bundle at a higher epoch with a lower version. Bundle versions
  are the log index, so a promoted copy's bundle is refused only where an
  old root wrote past the index the copy was promoted at (a forced
  promotion of a copy that was behind). Its list still moves the node, but
  the node takes the new root's bundles only once its index passes.
- **UI (Machines, `StandbyPanel.tsx`) is not built.** The contract carries
  what it needs: `Node.lastSeenEpoch` for "still follows the old root",
  `StandbyStatus.version` and `matches` for the standby's line. A follow-up
  row in `ui`.

## The adversarial review (2026-10-22), and what changed

Codex reviewed the branch with in-memory probes: four blockers and four
should-fix items. Each fix has a test that failed before it; 19 new checks
were broken once each and caught.

- **A superseded root could still command machines** (a promotion keeps the
  root's token key). Every token the root signs but a client key carries
  `ep`, the epoch it was signed at. Every verifier (the vendored token
  module, in agent, control, gateway, inference-driver, library and
  tool-driver) refuses a root token whose `ep` is below its bundle's epoch,
  and the agent also refuses one below the epoch it holds from a list:
  *"This command came from a root this machine no longer follows (epoch 2;
  it follows epoch 3)."* A root token with no `ep` (a root older than row
  4) is refused once the bundle's `tokenEpochs` (written once, as a hidden
  `patchConfig`, by the first bundle an unlocked active root signs) says
  roots mark theirs, if it is newer than that or a promotion followed. Chosen
  over rotating the token key at promotion: a rotation needs the old key
  revoked everywhere it is cached, and leaves client keys broken. Client keys
  are not fenced by epoch: they outlive any root and are revoked one by one.
  A session signed before a promotion is refused after it: sign in again.
- **Lists.** Once a node holds a list that names its root, a list that
  names none is refused (409), as is a malformed `control`. Another list
  under the same version is refused. Nothing is written unless it is taken.
  A kept list below the epoch held is not loaded.
- **Bundles are ordered by epoch first**, in the vendored token module
  (`accepts_replacement`, and so every component's `BundleFile`): a root
  promoted from a copy that was behind is taken. **A crash before the
  promotion's bundle arrives** no longer restarts the copy as a standby:
  the agent passes the epoch it holds (`FOLLOW_EPOCH`), and a copy whose
  own log names its node the root at a higher epoch starts as the root; a
  copy a held list names the root is not started to follow.
- **Snapshots are checked before they replace a copy**: complete (every
  `Snapshot` field), the same install (`controlPublicKey`, `salt`) and no
  lower epoch. A snapshot that failed, gave no identity, or recovered from
  an entry that would not apply holds the next one off for 30 s. A standby
  newer than its root may now refuse the root's snapshot as incomplete
  until the root is updated.
- **Should-fix, done:** a list moves a node only to a root it lists, at that
  machine's registered port and keys; `standbyPromoted` is dropped when no
  signed list names this machine the root; a root that answers only for an
  older epoch counts as silent for the fallback, and the standby's machine
  with a changed key is asked through its root's signed list, fetched
  without the key and verified; a promotion and the poll send each machine
  its bundle and list on their own (16 at once, 30 s each).
- **Acceptance**: a machine's state is read with a token it mints for
  itself; D comes back on new ports so only the fallback can move it; A,
  unlocked, signs a list numbered above C's at its lower epoch (refused for
  the epoch) and relays a command C refuses.

## The second review (2026-10-23), and what changed

Codex re-reviewed the fixes: the four should-fix items closed, a gap left in
each blocker, and two new should-fix items. Each fix has a test that failed
before it.

- **Tokens without `ep`.** A promotion ends them, wherever it is learned:
  a node refuses a root token without `ep` once it holds an epoch above its
  bundle's (a promoted root's list came first) or above `legacyTokenEpoch`
  (`node.yaml`: the epoch it held when it first ran row 4 code, or joined).
  A root promoted from a copy that is the first to write `tokenEpochs` names
  the epoch it replaced, so every verifier refuses that root's tokens
  without `ep` at once.
- **Out of scope:** a former root re-signing tokens with a forged `ep` holds
  the install's own token key; a compromised root machine is outside what
  Eugene's code defends (Troy's standing rule, 2026-10-07).
- **The list fence survives a restart.** `node.yaml` keeps `listEpoch`, the
  highest root epoch a taken list named. A list that names no root is
  refused against it, and a kept list without one is not loaded.
- **A promoted copy that restarts locked, before anything was pushed.** The
  agent asks its copy: one that says it is the root at an epoch above any
  this node holds gives the bundle it signed at its promotion (a locked
  root still serves it), verified against the install's identity. Taken, it
  ends the standby grant here; the copy is marked promoted, this node
  follows its own copy, and `/control` opens, so the owner can sign in on
  this machine's console. `NodeIdentity.rootLocked` (from control's
  `/healthz` `details.locked`) puts "The control root on <machine> is
  locked" in Home's Needs attention, with the unlock action (ui). The
  minute's pull checks this while the root it names does not answer.
- **Snapshots are typed.** Collections must be lists, `config` and the
  other objects objects, the key fields text or null, `index` and `epoch`
  whole numbers, and every node named. Only the fields every supported root
  writes are required; later ones are optional and read as empty.
- **A failed fresh snapshot** is retried after 30 s: the 10 minutes start
  once one was taken.
