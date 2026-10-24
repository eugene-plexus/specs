# Row 36: Machines says why a machine's announcement was refused

Lane TRUST, position 7. Sources: R2.4 ("Left undone and named" in
`docs/history/release-roadmap.md` §3.4), `docs/acceptance/proportionate-credentials-run.md`
§6, control `routes/nodes.py` (`announce_node_address`), agent `enrollment.py`
(`keep_address_announced`), ui `lib/issues.ts`.

## 1. What it delivers

- When the root refuses a machine's new address, Machines and Home say why,
  in the root's words, with the next step. Today the machine reads
  "unreachable" with a probe error from its old address, which sends the
  owner to firewalls and keys.
- **A move onto the open internet can be confirmed from the console.** The
  owner sees "nas announced https://203.0.113.9:8079, an address on the open
  internet" and presses **Accept this address**. Today the only way is to
  re-enroll the machine.
- The root also counts announcements for a machine that were not signed by
  it, and shows the count and the last time, never the text they carried.

## 2. Design

### What the root keeps

An observation, as `lastError` and `machineKeyChange` are: kept in memory on
the active root (`app.state.announcement_refusals`, beside `node_probes`),
never in the replicated log, never replicated to a standby. A refusal must
not grow the log, and a standby learns it at the machine's next attempt (see
the agent change below).

Per machine, the last refusal of an announcement **that verified against
the machine's signing key**:

| `reason` | Refused by today | Next step shown |
|---|---|---|
| `open_internet` | 409 "Address puts this node on the open internet" | **Accept this address** (below), or nothing if the move is not expected |
| `anothers_address` | 409 "Another machine's address" | "If that machine moved, this clears when it says where. If it is gone, remove it." Link to that machine |
| `not_a_node` | 400 "Address cannot be a node" | "Set this machine's address in Reach on that machine." The cause names the class (metadata, link-local, multicast) |
| `machine_port` | 400 "Machine port cannot be a node's" | the root's own sentence; it names the cause |
| `stale_sequence` | 409 "Stale announcement" | "Its identity was restored from a backup. Re-enroll it." |

The 401 "Node has no signing key" is a fact of the record, so the route
records it as `no_signing_key` whatever the request carried. Malformed
bodies and signatures that do not verify are counted, not kept: an
announcement anyone can send must not put words on the owner's screen.

An accepted announcement (changed or not), a removal and a re-enrollment
clear the machine's entry. A root restart clears all of them.

### Contract (`control.yaml`)

```yaml
Node:
  announcementRefused: NodeAnnouncementRefusal | null
  unverifiedAnnouncements: {count: integer, lastAt: date-time} | null
NodeAnnouncementRefusal:
  required: [at, reason, title, detail]
  at: date-time
  reason: NodeAnnouncementRefusalReason   # named enum, the five above + no_signing_key
  title: string        # the problem title the machine was sent
  detail: string       # the problem detail, which names both addresses
  announcedUrl: string | null
  acceptable: boolean  # true only for open_internet while the held announcement still applies
/v1/nodes/{name}/announcement/accept:
  post acceptNodeAnnouncement   # operator; 200 NodeAddressAck, 404, 409
```

Both fields are optional and nullable, so an older console ignores them.

### Accept this address (`open_internet` only)

- The root holds the refused, signed body (url, sequence, machine fields,
  signature) for that machine, in memory with the refusal.
- `POST /v1/nodes/{name}/announcement/accept` with `require_operator` (an
  operator session or the owner's token; never a node or service token).
  It verifies the held body's signature again, runs every other rule again
  (`rejection`, `_not_anothers_address`, `_checked_machine`, the sequence
  must still advance), and appends the same `OP_UPDATE_NODE` the announce
  route appends. The log line names who accepted it.
- 409 when the held announcement no longer applies (a newer one arrived, or
  the sequence moved), with the reason. 404 when nothing is held.
- **Why this is safe:** the 409 exists because a stolen signing key could
  move a machine onto the internet with nobody watching. The owner pressing
  Accept on a sentence that shows both addresses is the confirmation
  re-enrollment gave, without walking to the machine. Call R36-ACCEPT.

### Agent

`keep_address_announced` stops repeating a definite refusal for an address
today. It now tries the same address again every 15 minutes (logging the
refusal once per address and reason, as now), so a restarted root or a
promoted standby learns the reason within 15 minutes. An accept on the root
answers the next attempt with "unchanged".

### UI (`lib/issues.ts`, `app/nodes/page.tsx`)

- **Machines:** when `announcementRefused` is set, the machine's row shows
  its `title` and `detail` and the next step from the table, above the
  probe error. `acceptable` shows **Accept this address** with a confirm:
  "nas will be reached at https://203.0.113.9:8079, on the open internet.
  Accept only if you moved it there."
- **Home:** an unreachable machine with a refusal gets the refusal as its
  `node-down` detail, not a second issue. A reachable machine with a refusal
  (its old address still works) gets a new warning, `announcement-refused`.
- `unverifiedAnnouncements` is one line under the machine:
  "3 announcements not signed by this machine were refused, the last at
  14:05." No issue: it is not something the owner can fix.

## 3. Repositories and codegen

specs, control, agent and ui. Regenerate control, agent (it reads
`control.yaml`) and ui, and diff each.

## 4. Tests that fail before

In a new control file, `tests/test_announcement_refusals.py`:
- `test_a_signed_refusal_is_shown_on_the_node`, one case per reason; today
  `GET /v1/nodes/{name}` has no field.
- `test_an_unsigned_announcement_is_counted_not_shown`.
- `test_accept_applies_the_held_open_internet_announcement` and
  `test_accept_rechecks_every_other_rule` (another machine took the address
  meanwhile: 409).
- `test_a_node_token_cannot_accept` (403).

And:
- agent `tests/test_node.py::test_a_refused_address_is_announced_again_after_15_minutes`.
- ui `issues.test.ts`: a refusal replaces the probe error in `node-down`;
  `announcement-refused` for a reachable machine.

## 5. Acceptance (CI, Linux, about 2 minutes)

`specs/scripts/row36-announcement-acceptance.py` on row 2's harness: a real
root and one enrolled agent on loopback ports, every `EUGENE_PLEXUS_*`
variable cleared.
1. The agent's configured address becomes a TEST-NET-3 address the harness
   maps to its loopback listener; the root refuses it, and `GET
   /v1/nodes` shows `open_internet` with both addresses.
2. A second machine record holds an address; the agent announces it:
   `anothers_address`, naming that machine.
3. A body with a bad signature: the count rises, nothing else changes.
4. Accept as the operator: the record moves; the agent's next attempt is
   "unchanged"; the refusal is gone.
5. A root restart: the refusal is back within one agent retry (the test
   shortens the 15 minutes).

## 6. Do not change

- control `oidc.py`, `sealing.py`, `passphrase_file.py`, `keyring_store.py`
  (row 5), and the promoted-root address files row 4 changes
  (`machine_list.py` is shared: add, do not restructure).
- agent `machine_key_change.py` (row 3, merged; call into it only).

## 7. Size and risks

M, about 1.5 days, cross. Risks:
- **Accept widens what an operator session can do** to a machine's address.
  It needs the operator, the held body's signature and every rule again;
  the reviewer should attack replays of an old held body and a race with a
  newer announcement.
- An attacker without the key can raise the unverified count. It is a
  number and a time, nothing else.

## Calls answered by Troy (2026-10-22)

- **R36-ACCEPT: Choice 2.** Re-enrollment stays the only way to confirm a
  machine's move onto the open internet. Machines says why the address was
  refused and tells the owner to re-enroll the machine. Not built: the
  **Accept this address** button, `POST /v1/nodes/{name}/announcement/accept`,
  the held announcement body, `NodeAnnouncementRefusal.acceptable`, the
  accept tests in section 4 and acceptance step 4 (the agent's next attempt
  after re-enrollment is "unchanged" instead).
