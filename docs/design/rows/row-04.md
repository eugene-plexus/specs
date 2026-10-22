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
