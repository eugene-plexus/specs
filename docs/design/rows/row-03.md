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

## Calls answered by Troy (2026-10-21)

- **R3-SCHEDULE: asked again (R3-SCHEDULE-2).** Troy chose a yearly change if the keys expire by themselves. They do not: a machine key is self-signed and pinned by its SPKI hash, and the browser certificate renews every 60 days on the same key. Default until he answers: Eugene changes each machine key once a year by itself, as a small follow-up after this row merges, because this row makes a change safe for offline machines.
