# A warm standby that follows (control#5)

**2026-10-08. Designed; calls SB1–SB4 taken by Troy the same day.** Built
the same day; §7 says what building changed. Record:
[`warm-standby-run.md`](../acceptance/warm-standby-run.md).

Issue: [control#5](https://github.com/eugene-plexus/control/issues/5).
Background:

- [`m5-multi-host-and-trust.md`](m5-multi-host-and-trust.md) §5 and §9:
  the log, the snapshot and promotion.
- [`per-node-token-keys.md`](per-node-token-keys.md) §5, which left the
  standby session-only "until a standby identity is designed".
- [`remote-nodes.md`](remote-nodes.md) row N16.

## 1. What is wrong today

A warm standby cannot follow the active root. Measured in the code on
2026-10-08:

- **The follower sends no credential.** It is built with
  `token_provider=None` (`control/app.py:148-159`).
- **The replication routes take an operator session only.** That is
  `require_replica = require_operator` (`dependencies.py:190-206`), so
  every 2 s pull gets a 401, forever.
- **R2.4 once let any `service:control` token in.** That was removed on
  2026-09-25, because any enrolled node could mint one: `aud: control`
  names no instance.
- **The agent has no standby concept.** A control is started as a standby
  only by hand, through `spawn.env` (`EUGENE_PLEXUS_CONTROL_ROLE`,
  `_ACTIVE_URL`).
- **A control process gets no credential from its agent.** Control is a
  trust-root kind (`supervisor.py:193`, asserted at
  `test_supervisor.py:470-482`).
- **Standby lag is never reported.** `standby_reports` is never written,
  so every standby shows as unreachable.
- **The status route reads `standbyUrls`,** a list typed by hand into
  Settings.

## 2. The calls (all taken, 2026-10-08)

| # | Call | Taken |
|---|---|---|
| SB1 | **Who makes a machine the standby** | A `standby` grant on one named machine, given only by an owner action on Machines. Removing the grant revokes the standby. Never from a join token, and never claimed by the node. |
| SB2 | **The credential** | A service token with `sub: standby`, `aud: [control]`, signed by the standby's own node key. It lasts 15 minutes, as every token to another machine does. It is valid only with the grant. The replication routes accept a session or this token; **no other route accepts it.** |
| SB3 | **Who sets it up** | The standby's agent. When the agent sees the grant on its own machine, it starts its control as a standby, pointed at the root it joined, and gives it the means to get the token. No `spawn.env`, no typed URL. |
| SB4 | **How lag is known** | The root records each standby's position when that standby pulls: `after` on a log read is the follower's applied index. No new route, and no probing of the standby. |

**The security trade, accepted with SB1.** A warm standby holds the
replication set: the sealed keys, the salt and the passphrase verifier
(m5 §5's table). So two things give the material away and allow offline
guessing of the passphrase (at least 12 characters):

- the standby's node key, until revoked;
- the standby's disk.

Before 2026-09-25 any node could read this material. With SB1 only the
one named machine can. Promotion still needs the passphrase. Rejected
alternative: a standby that replicates the log without the sealed values.
That is safer at rest, but it cannot take over on its own.

**Chosen by the design, not called** (Troy may overrule any of these):

- one standby at a time;
- `standbyUrls` retires in favour of the grant;
- the replica is deleted when the grant is removed;
- promotion from the console waits for its own slice.

## 3. The design

### 3.1 The grant (SB1)

- **`TrustGrant` gains `standby`.** It sits beside `node`, never instead
  of it. Its meaning: service tokens with `sub: standby` to `control`, and
  nothing else.
- **New log op `setStandby {node, on}`.** It is applied state, replay is
  byte-stable, and the node's grants stay sorted.
  - It refuses a node that does not exist, a retired Job Site and the
    active root's own node.
  - It refuses when another node already holds `standby` (409, which names
    the holder). One standby at a time is the easy default; more would be
    a later call.
- **Two control routes, operator session only:**
  - `PUT /v1/nodes/{name}/standby`
  - `DELETE /v1/nodes/{name}/standby`
  - Each republishes the trust bundle and pushes it to the nodes, as
    enrollment does.
- **`promote` drops the promoted node's own `standby` grant.** A root
  doesn't follow itself.
- **`standbyUrls` retires.** The grant is the one source of truth, which
  is Troy's rule that settings never lie.
  - A config that still holds `standbyUrls` loads without complaint, but
    nothing reads it.
  - Settings stops showing the field.
  - The status route lists every node holding `standby`.

### 3.2 The token (SB2)

- **The shared token module** (`tokens.py`, byte-identical in five repos)
  gains `GRANT_STANDBY`, `SUB_STANDBY` and one rule in `_check_grants`: a
  `sub: standby` token may leave its machine only if its key holds
  `standby`, and only to `control`.
  - Minting (the agent's `mint_service`) and verifying (every component)
    run the same check, as for `gateway`.
  - `r7-signing-checks.py` keeps the five copies identical.
- **On the root, `require_replica`** accepts an operator session, or a
  service token with `sub: standby` whose issuer is a node that holds
  `standby` in the root's **applied state** at that moment.
  - The second check repeats the bundle's on purpose, as
    `_session_or_services` does. A revoked grant then shuts the next pull
    out (within 2 s) even while a 15-minute token is still alive.
- **What stays exactly as it is:**
  - `require_operator`, and every other route.
  - `_actor`, which takes `sub: agent` only.
  - The status, people, sign-in and node routes. None of them may accept
    `sub: standby`.

### 3.3 The standby's agent (SB3)

- **Trigger.** `trust.accept` (the 60 s pull, or the root's push) gains
  one reaction. When this node's own key gains or loses `standby`, the
  agent reconciles its components.
- **When the grant is gained:**
  - The agent declares a `control` entry with role `standby`, its active
    URL the `controlUrl` from `node.yaml`, and its own data directory. It
    takes the next free port, walking past taken ones as every component
    does.
  - It starts that entry.
- **When the grant is lost:**
  - The agent stops the standby and deletes its data directory: the
    replica holds the sealed values (§2).
  - It logs one line naming why.
- **The credential.** The standby gets a spawn token with `sub: standby`,
  for its own machine, under `EUGENE_PLEXUS_CONTROL_SERVICE_TOKEN`.
  - Its follower exchanges that token at the agent's existing loopback
    `POST /v1/auth/service-token` for a 15-minute token addressed to
    `control`. It exchanges again before that token expires.
  - That loopback route is how the gateway gets its remote tokens today.
    Nothing new is listening.
- **Nothing else.** The standby gets no signing key, no master key, no
  trust bundle file and no recipient. The supervisor test that pins this
  for control (`test_supervisor.py:470-482`) gains a standby case that
  allows exactly the one service token.
- **The agent's `GET /v1/node`** reports the standby: running or not, its
  applied index and its last pull. The console can then show it from
  either side.

### 3.4 Lag (SB4)

- **On the root,** each authorized standby read records
  `standby_reports[node] = {appliedIndex, at}`:
  - for `GET /v1/control/log`, from `after`;
  - for a snapshot, from the snapshot's index.
- **`StandbyStatus` gains `node`.** `url` becomes the node's URL.
  `reachable` means the root heard from that standby within three follow
  intervals, and `lastContactAt` says when.
  - A root restart empties the reports. Until the next pull, the status
    says *not heard from yet*, never *unreachable*.

### 3.5 The console

- **Machines gains per-node actions:**
  - *Make this the standby* (owner only), which asks first and says the
    §2 trade in one sentence.
  - *Stop being the standby*, which says the copy will be deleted.
- **A standby's row** shows *Standby · up to date* or *Standby · N
  entries behind, last heard 4 s ago*.
- **Settings → replication** links to Machines, and Machines links back:
  related settings cross-link both ways.
- **Promotion from the console is banked.** It is called on the standby
  with the passphrase, and is a separate slice. It is not part of
  control#5.

## 4. Build order

Each step lands with a test that fails without it. The sabotage runs on
the changed code only.

1. **Contract** (specs):
   - `TrustGrant.standby`;
   - the two node routes;
   - `StandbyStatus.node`;
   - `standbyUrls` deprecated in the config schema;
   - the agent's node report of its standby.

   Measure the radius by regenerating every consumer.
2. **The token module,** in all five repos (the editor copies it).
   - Unit tests:
     - a `sub: standby` token without the grant is refused, to `control`
       and to any machine;
     - with the grant, it is refused to anything but `control`;
     - a `sub: agent` token with the grant opens nothing new.
3. **Control:**
   - `setStandby` and its refusals, plus a replay test;
   - the two routes;
   - `require_replica`;
   - the follower's token provider;
   - `standby_reports`;
   - status from the grant;
   - `promote` dropping its own grant.
4. **Agent:**
   - the bundle reaction;
   - the standby entry, its port and its data directory;
   - the spawn token;
   - the delete on revoke;
   - the supervisor test's standby case;
   - the `GET /v1/node` report.
5. **UI:** the two actions, the row's status and the cross-links. Rebuild
   `dist`.
6. **Acceptance:** `specs/scripts/standby-acceptance.py`, in CI. Two
   agents, real processes and non-default ports, with Eugene's own keys
   and no cloud.
   - Before the grant, nothing follows.
   - The grant is given → within 60 s a standby runs on the second
     machine, follows, and the status shows lag 0 with a recent contact.
   - These tokens are refused at `/v1/control/log` and
     `/v1/control/snapshot`:
     - a `sub: agent` token from the standby's machine;
     - a `gateway` token;
     - a `sub: standby` token from an ungranted node;
     - a session that isn't an operator's.
   - The grant is removed → the next pull is refused, and the standby is
     stopped with its directory gone.
   - **Failover, end to end:** give the grant again and let it catch up.
     Stop the root. Promote the standby with the passphrase. It serves
     sign-in and the node list. The old root, started again, is fenced by
     the epoch.

## 5. What must not change

- **Only the granted node, or an operator session, reads the replication
  surface.** It carries `sealedSigningKey`, `sealedControlKey`,
  `sealedRecoveryKey`, `salt` and `passphraseVerifier`. No other node and
  no other token kind may read it: R2.4's narrowness stays.
- **Promotion still needs the passphrase.** It checks it against the
  replicated verifier, and refuses a standby that is behind unless `force`
  is set.
- **One writer.** The standby pulls; the root never pushes the log.

## 6. Left for building to confirm

- A promoted standby's `securityMode`. The passphrase opens the sealed
  keys in every mode, but `os_keyring` cannot carry over to a new host
  (m5 §1). Say what the promoted root asks for at its next start, and
  test it.
- That a Windows worker can hold the standby's data directory privately,
  as it does every component's.

## 7. What building found

- **The root could not tell its own machine.** Every node record says
  `role: agent`, so "never the active root's own node" had nothing to check.
  `NodeIdentity.hostsControl` (specs `c65170f`) is the agent's answer, read
  by the root's probe. The agent doesn't count its own standby entry. The
  route refuses the root's node by its own `node_name` setting or by the
  probe's `hostsControl`, and says why (409).
- **A promotion must name its node.** The standby learns its machine's name
  from its agent (`EUGENE_PLEXUS_CONTROL_NODE_NAME`), so `promote` can drop
  that node's own `standby` grant and record it as the root.
- **A promotion takes the grant too, so losing it is ambiguous.** An owner
  removed it, or this copy is now the root. The agent asks the local
  control's `/healthz` for `details.role` before it stops or deletes
  anything: `standby` → stop it and delete `standby-state/`; `control` →
  keep it, and say so once; no answer → keep it and ask again at the next
  bundle.
- **The planner sets `ROLE` and `ACTIVE_URL` only while the grant holds.**
  A promoted copy that restarts therefore starts as the root, not as a
  standby of the root it replaced.
- **`StandbyStatus.url` is optional** (specs `62ef542`): a node may have
  no recorded address, and the status still names it by `node`.
- **The agent's report is `{component, url, status, following}`,** not the
  applied index and last pull §3.3 planned. The root already holds the
  position (SB4), and the standby's own status has the rest.
- **A locked root still serves its standby.** `require_replica` checks the
  grant in applied state, which needs no unsealed key.
- **"Settings → replication links to Machines" (§3.5) is dropped.** With
  `standbyUrls` retired, no replication setting is left to link from.
- **The token module is six copies vendored from `platform/1.0.0/`,** not
  five kept level by hand (§3.2). The source changes first; each consumer's
  `VENDORED.json` carries its hash, and its CI refuses an edited copy.
- **The copy lives in `standby-state/` beside `agent.yaml`,** on a port
  walked up from 8083, bound to loopback (it pulls; nothing dials it).
- **§6, the promoted root's `securityMode`.** The mode is replicated config,
  so the promoted root has the old root's. Nothing new asks:
  - `prompt_on_startup` (the acceptance): locked at each start until a
    sign-in.
  - `passphrase_file`: unlocks by itself if the same file is mounted on the
    standby's machine.
  - `os_keyring`: the first start finds no key on the new host, logs that
    it is locked until a sign-in, and the sign-in stores the key.

  Only the first is run end to end; the other two are the existing startup
  paths, not run on a promoted copy.
- **§6, a private directory on Windows.** The copy inherits the agent's
  config directory, which `install.ps1` protects. Checked on Amish_Station,
  the live standby: the installing person's unelevated session cannot even
  read the folder's ACL.
- **A pushed bundle that could not be written was lost.** Windows refuses
  to replace a file any process has open, and every component reads
  `trust_bundle.json`. The agent kept the new bundle in memory, logged one
  warning, and never wrote it again. After a promotion that matters: the
  new root pushes once, and the agent's pulls still go to the root that
  stopped. Now a write refused this way is retried briefly, and then before
  every trust pull until it lands (agent `trust.save_pending`). Found by the
  acceptance on Windows, after promotion. The other reader was not
  identified: either its own polling of the file every 0.25 s, or
  antivirus.
- **After a revoke and a new grant, the standby may come back on a
  different port.** Linux still holds the old one for a moment, and the
  agent walks past it. The acceptance reads the port from B's report.
- **Found, not fixed (banked):** after a promotion, only the promoted
  machine reaches the new root. The copy stays bound to loopback, and no
  agent learns a new root address: m5 §9 step 4 says agents learn "the new
  epoch and endpoint", but nothing carries an endpoint. The banked step
  that turns a promoted copy into the install's `control` entry has to
  answer both.
