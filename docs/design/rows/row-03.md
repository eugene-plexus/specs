# Row 3: rotate a machine's TLS key

Read at agent `74d8427` and control `f083a3c`.

**Today**
- An announcement carries one `tlsPin` (`C/routes/nodes.py:248`).
- The machine port loads its key once, at start (`A/machine_port.py:744`).
- Control gets the root's pin at spawn (`MACHINE_PINS`, `A/app.py:974`). Changing that pin therefore means restarting control, and control comes back sealed.
- An unplanned change of the root's key does recover, through the plain list fetch (`A/machine_trust.py:312`), but only once control is restarted and unlocked.

## 1. What it delivers

- An owner can press **Change machine key** on any machine, the root included. Traffic keeps flowing while the key changes.
- Machines shows progress: *Changing machine key: 2 of 3 machines have the new key*, then *Machine key changed 21 Oct, 14:03*.
- A machine that is offline during the change takes the new key when it returns.
- If the root dies mid-change, the old key keeps serving, and the change finishes once a root answers.

## 2. The design

**Contract**
- **`control.yaml`:**
  - `NodeAddressAnnouncement.tlsNextPin` is optional and signed under its own name. A node record holds at most 2 pins.
  - `MachineList.keyChange: true` marks a root that takes `tlsNextPin`. When the field is absent, the agent offers no change.
  - `Node.machineKeyChange` is an observation: `{nextPin, listVersion, waitingOn[], unreachable[]}`.
- **`agent.yaml`:**
  - `MachinePort.listVersion`.
  - `MachinePort.keyChange`: `{state, nextPin, startedAt, error}`.
  - `POST /v1/node/machine-key` starts a change (operator, 202).
  - `DELETE /v1/node/machine-key` stops it before the switch, and answers 409 after.
- **Process configuration:** `EUGENE_PLEXUS_CONTROL_MACHINE_DOOR_FILE` names a JSON file, `{pins, url}`.
  - The root's agent writes it, and control re-reads it at most once a second.
  - `MACHINE_PINS` stays, for an older control.
  - Row 4 uses `url`.

**Order of operations** (new `agent/machine_key_change.py`: a 15 s loop, with its state in `node.yaml`)
1. **Start.** The node must be enrolled, its port listening, and its list must carry `keyChange`. It makes a P-256 key and writes it as `tlsNext*` in one write.
2. **On the root only:** the door file becomes `[current, next]`. Join tokens keep the current pin.
3. **Announce both pins.** `_recorded_differs` compares the pin sets.
4. **Wait** until both conditions hold:
   - the held list names both pins (a locked root signs no list, so the node waits for it);
   - the root's `GET /v1/nodes/{own}` shows `waitingOn` empty, or 3 minutes have passed since the list first named the new pin.

   An agent that reports no `listVersion` counts as caught up after 3 minutes. Unreachable machines pull the list when they return.
5. **Switch.**
   - Swap the keys in `node.yaml` in one write.
   - `MachinePort.reload` calls `load_cert_chain` on the live context. New handshakes get the new key; open sessions finish on the old one.
   - The client doors ask for a new leaf at once (`client_tls.wanted()` already notices the change).
   - On the root, the door file becomes `[new, old]`.
6. **Drop.** Announce `tlsPin` alone. On the root, the door file becomes `[new]`.

**If the root dies**
- Before step 5, the node does not switch. It shows *waiting for the root*. Both pins are replicated, so a promoted standby carries on.
- After step 5, the list keeps both pins until a root records the drop.

**Failures**
- If the root refuses the announcement, the change is undone, the next key is deleted, and the root's detail is shown.
- A join code made before the switch says: *"The root's key changed after this join code was made. Make a new one."*

**Control**
- `routes/nodes.py`: signs over the raw `tlsNextPin`, and applies `_checked_machine` to both pins.
- `machine_list.py`: `keyChange`, reading the door file, and the version in which each node's pin set was first signed.
- `nodes_client.py`: reads `machine.listVersion`.

**UI** (Machines row, owner only)
- **Change machine key** asks: *"This machine gets a new key. The others take it within a few minutes; nothing stops."*
- **Stop** stays available until the switch.
- Progress lines: *…NAS is offline; it takes the new key when it returns*, *…waiting for the root (connection refused)*, *Machine key not changed: the root refused it (…)*.

**Defaults**
- Manual only. **Recommended:** no schedule, because a pinned key does not wear out.
- **Flag:** the switch deletes the old private key. That is intended.

## 3. Repositories and files

- **agent:** `node_identity.py`, `machine_port.py`, `machine_key_change.py` (new), `enrollment.py`, `machine_trust.py`, `app.py`, `routes/node.py`, `client_tls.py` (a one-line trigger).
- **control:** `routes/nodes.py`, `machine_list.py`, `settings.py`, `nodes_client.py`.
- **ui:** `app/nodes/page.tsx`, `lib/machineLink.ts`, `components/MachineKeyChange.tsx`.
- **specs:** both yaml files, and `tls-between-machines.md` §7.3.

**Codegen:** `control.yaml` regenerates control and ui. `agent.yaml` regenerates agent, control and ui.

## 4. The tests that fail first

- `control/tests/test_machine_key_change.py::test_next_pin_is_signed_recorded_and_listed`
  - Both pins are recorded and listed.
  - A signature that does not cover `tlsNextPin` gets 401.
  - A third pin gets 400.
- `agent/tests/test_machine_key_change.py::test_switch_waits_for_coverage_then_presents_new_key`
  - There is no switch while `waitingOn` is not empty.
  - After the switch, a handshake returns the new pin with no restart.
  - The next announcement carries one pin.

## 5. Acceptance (CI, high risk)

Labels `key-change` and `root-key-change` in `lt1-machine-tls-acceptance.py`: a Docker pair on Linux runners, with every port inside the containers.
- **Under load:** one prompt a second goes through the root's gateway to the worker for the whole change. None may fail.
- **After the drop:**
  - the worker presents the new key;
  - the lists hold one pin;
  - the capture holds no plaintext;
  - an impostor using the old key is refused.
- **Root key:** the worker's `/control` calls keep working, and its `controlPins` end as the new pin.
- **Offline:** the worker's agent is stopped before the switch and started after the drop. It recovers within 2 minutes.
- **Root death:** control is stopped between steps 3 and 5. The node stays on the old key, and the change finishes after a restart.

The labels add about 8 minutes.

**The reviewer should attack:**
- a stolen node signing key registering a next pin for another machine's door;
- a replayed announcement that brings back a dropped pin;
- a switch before every machine has the new pin;
- who can write the door file;
- reloading the context during a handshake;
- a leaf issued for a key that was never announced.

**Orchestrator's note (2026-10-21), a required check.** A machine that is
offline for the whole change holds a list with only the old pin. After step 5
the root's machine port presents the new key, so that machine's TLS check
fails before it can fetch the new list. The build must show how it recovers
with no person: for example, it fetches the root-signed machine list over a
path that does not depend on the old pin and verifies the list's signature
with the control identity key, which does not rotate. The acceptance script
must include this case (a machine stopped before step 1 and started after
step 6), and the reviewer must attack it.

## 6. Do not change (hot for other lanes)

- `agent/__main__.py` (row 2)
- `agent/reach.py` (row 8)
- `agent/client_doors.py` (row 25; `set_context` already reloads)
- `agent/tokens.py` (row 35)
- `*/scripts/codegen.py` (row 1)
- `settingsTopics.ts`, `ResourceTree.tsx` and `resourceTree.ts` (row 33)
- `ConfigField.tsx` and `configValue.ts` (row 62)

Rows 36 (`machine_list.py`) and 45 (`client_tls.py`) are in this lane and come later. Keep the edits to those files small.

## 7. Size and risks

- **Size:** M. About 350 lines in the agent, 120 in control and 120 in the UI. No split is needed.
- **Risk:** a locked root does not probe the other machines. The 3-minute bound covers that.
- **Risk:** the old key's client leaf is not revoked, because LT2 has no revocation. A stolen old key can impersonate the node to browsers for up to 90 days. Record this as a limit.

## 8. What building found (2026-10-21)

Branch `r3-machine-key` in specs, agent and control.

**The offline machine (the orchestrator's check).**
- It was stranded, and not only at the TLS check. The minute's pull asks
  for the trust bundle first, over the pinned call the root's new key
  refuses, and gave up there: the machine list, whose plain fallback already
  existed, was never fetched. Now a pin refusal on the bundle fetches the
  list first and asks again (`leaving.bundle_response`).
- The list comes over TLS to the root's machine port with no key checked,
  and in plain HTTP only when that port does not answer TLS. It is taken
  only if it verifies against the root's identity key, which never changes.
  So the capture holds no plain connection between machines.
- Acceptance: `root-key-change` stops the worker (agent and driver) before a
  second change of the root's key and starts it after the drop.

**Order on the root.**
- A list that names a key for the root's own node that its `controlPins` do
  not is ignored by every other machine (`build_table`), and under required
  that refuses their calls to the root's agent. So the door file names the
  next key 1.5 s before the announcement (control reads it at most once a
  second), and keeps the old key until the root has recorded the drop.
- Control reads the door file whole each second: a modification time can
  miss a rewrite of the same size.

**Contract and record.**
- `Node.tlsNextPin` is in applied state and in snapshots: `tlsPins` is
  sorted, so the record could not say which key is next otherwise.
- A third pin is refused by the schema (`tlsNextPin` is one string): 422,
  not 400. The same key twice, or a next key with no current key, is 400.
- A root that does not answer is waited for: the 3-minute bound applies only
  to machines a root that answers still lists in `waitingOn`.
- A node's announcements now go one at a time (a lock on its identity
  store): the change announces beside the address loop.

**Not built in this row.**
- The console's **Change machine key** button and its progress lines: the
  row's repositories were agent and control. Until a UI row lands, the
  change starts from `POST /v1/node/machine-key` only, which the GUI
  equality rule does not allow for long.

**Limits.**
- An open session made with the old key keeps running until it closes (the
  gateway's pooled sessions); new handshakes get the new key.
- The client doors' leaf for the old key is not revoked (LT2 has no
  revocation), and its key stays in the client-TLS files until the new leaf
  arrives, which is asked for at the switch.
- An agent older than row 3 reports no list version, so a change waits the
  full 3 minutes for it.

**The adversarial review (2026-10-21), and what changed.** Four blockers,
each now a fault-injection test that failed first:
1. **node.yaml written after memory took the switch.** A failed write left
   memory switched, so a retry reported done and announced the old key; a
   restart then presented a key the root refused. Now node.yaml is written
   before the record is held, a switch it cannot keep puts the old key back
   on the port, and the status keeps the observed cause.
2. **An agent older than row 3, off for the whole change of the root's
   key**, came back with only the old root key and never recovered (its pull
   stops at the refused bundle). The root now remembers which machines have
   reported a list version (`notReady` names the rest), and the root's own
   change does not switch while any is named, with no time bound. Another
   machine's change is not held up.
3. **The list version was reported before the children could read the
   table** (or when the file write failed, and taking the same list again
   did not retry). Now only the version in the file, written, and past the
   children's one-second cache is reported.
4. **Done on the root's acknowledgement.** A root restarted sealed takes the
   drop but signs nothing and keeps serving both keys. Now done needs a
   verified signed list that names the new key alone; until then the status
   says what it waits for, naming a sealed root.
