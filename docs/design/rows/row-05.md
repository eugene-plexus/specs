# Row 5: rotate the sign-in key, and change Eugene's passphrase

Read at control `f083a3c` and agent `74d8427`. This row needs `StandbyStatus.version` from row 4b.

## Today

**The sign-in key.** It is made the first time it is needed (`C/oidc.py:315`). `putOidcKey` keeps the two newest keys (`applied.py:1326`), but nothing ever makes a second one.

**Control's passphrase.** The master key is Argon2id(passphrase, salt). These are sealed under it:
- the four identity values;
- `oidc_keys[].sealedKey`;
- `browser_sign_in.providers[].sealedSecret`.

No route changes the passphrase.

**The root machine's agent.**
- It keeps its own passphrase hash, and checks a sign-in against it before forwarding (`A/routes/auth.py:368`).
- Its master key seals the share passwords and every child's secrets: provider keys, catalogue tokens and the tool-driver `apiKey`.

So changing the passphrase at control alone would lock sign-in through that agent.

**Split (recommended):** 5a is the sign-in key (S). 5b is the passphrase (M).

## 1. What it delivers

- **5a:** the sign-in key changes every 90 days by itself, or on demand. Apps stay signed in: the old key verifies until the last refresh token it signed has expired. After a suspected leak, *End every app sign-in now* stops the old key at once.
- **5b:** the owner changes Eugene's passphrase from People. The root's sealed values and the standby's copy are re-sealed, and the old ciphertext is compacted away.
- **5b:** every reachable machine that keeps its own passphrase takes the new one. A machine that was off takes it at its next sign-in.
- **5b:** auto-unlock keeps working. Where it cannot, a notice names why.

## 2. Design, 5a

**Contract (`control.yaml`).**
- `GET /v1/oidc/keys` returns `{keys: [{kid, createdAt, signs, verifiesUntil}], nextChangeAt}`.
- `POST /v1/oidc/keys/change {endSignIns}`. Operator only.
- New config field `signInKeyDays`: default 90, minimum 31, and 0 means never. The UI renders it from the schema.

**Routine change.**
- It appends the existing `putOidcKey`, so a standby on any version applies it.
- It answers 409 while the newest key is younger than 30 days and 10 minutes, because the key it would drop may have signed refresh tokens that are still live: *"The sign-in key changed on 12 Oct. Changing it again before 11 Nov ends some app sign-ins. Choose End every app sign-in now to do it anyway."*

**Leak.**
- `putOidcKey`, then a new op, `retireOidcKeys {keep}`.
- It answers 409 while the standby's version predates that op: *"Update B first; its copy would stop at this change."*

**Timer.** The active, unlocked root checks once an hour. A locked root logs that it is locked and waits.

**Apps.**
- Workbench reads the keys again when it sees an unknown `kid` (`workbench/signin.py:331`). Authlib does the same.
- **Limit:** Workbench caches keys for 5 minutes, so a forged token signed with a retired key can still pass there during that window.

**UI.** On People, under *Apps that sign in with Eugene*:
- *Sign-in key: made 21 Oct; changes on 19 Jan.*
- **Change sign-in key**, with a checkbox: *End every app sign-in now (the key may have leaked)*.

## 3. Design, 5b

**Contract.**
- `control.yaml` `POST /v1/auth/passphrase {current, new}`.
  - It needs an operator session and the current passphrase, under the login rate limit. The new passphrase must be at least 12 characters.
  - It returns `{changedAt, machines[{node, state, detail}], passphraseFile: matches|old|none}`.
- New op: `changePassphrase {salt, passphraseVerifier, sealed{…}}`.
- Agent `POST /v1/auth/passphrase`: the console's door, which forwards to control.
- Agent `POST /v1/node/passphrase`: accepts a `svc:control` token only, over pinned TLS only.
- `NodeIdentity.ownPassphrase`.

**Control, in order.**
1. Verify the session and `current`. If the standby predates the op, answer 409.
2. Make a new salt and a new master key. Open every sealed value with the old key and seal it with the new one. If any value fails to open, refuse, name the value, and change nothing.
3. Append the entry, take a snapshot, and compact through it.
4. **Keyring.** Write the new key under the new install id, then delete the old entry.
5. **Passphrase file.** If Eugene cannot write the passphrase file, report `old`. Issues then says: *"The passphrase file on NAS holds the old passphrase; after a restart Eugene stays locked until someone signs in. Put the new one in /run/secrets/control_passphrase."* This is rechecked at each start and every hour.
6. Send `{current, new}` to each agent where `ownPassphrase` is true. If an agent can only be reached in plain HTTP, send nothing and say so.

**Standby.** It applies the entry, then takes a snapshot and compacts. It deletes its keyring entry for the old install id.

**An agent with its own passphrase.**
1. It verifies `current`.
2. It keeps its master key, so the children's secrets still open.
3. It wraps that key under the new passphrase: `agent.yaml` gains `kekSalt` and `wrappedMasterKey`.
4. It rewrites the passphrase file it manages.

**A machine that was off.**
- If the root accepts a passphrase that this agent refuses, and the agent is unlocked, it wraps its key under the new passphrase.
- If the agent is locked, it asks once: *"This machine was off when the passphrase changed. Enter the old passphrase once to finish."*

**A crash after the entry is written.**
- The keyring still holds the old key. At the next start the root deletes it and says: *"The stored key no longer opens this install (the passphrase changed); sign in."*
- Agents that were not reached show as pending.

**UI.** On People, the owner's row gets **Change passphrase**. The form says that the keys it protects stay the same, that a copy made earlier still opens with the old passphrase, and that after a leak the sign-in key and the token key should change too. The result lists each machine as *changed*, *changes at its next sign-in*, or *not sent: reached in plain HTTP*.

**Call for Troy.** Should each machine's own secrets be re-sealed under a new key? That needs changes to inference-driver, library and tool-driver. **Recommended:** a later row.

## 4. Repositories and files

- **control:** `oidc.py`, `applied.py`, `security.py`, `routes/auth.py`, `routes/oidc*.py`, `keyring_store.py`, `passphrase_file.py`, `config.py`, `app.py`, `replication.py`.
- **agent:** `routes/auth.py`, `state.py`, `security.py`, `keyring_store.py`, `passphrase_file.py`.
- **ui:** `app/people/page.tsx`, `components/PassphraseChange.tsx`, `components/SignInKey.tsx`.
- **specs:** `control.yaml`, `agent.yaml`, `sign-in-with-eugene.md` §10.

**Codegen:** changes to `control.yaml` regenerate control and ui. Changes to `agent.yaml` regenerate agent, control and ui.

## 5. The tests that fail first

- **5a:** `control/tests/test_oidc_key_change.py`:
  - `::test_change_signs_with_new_key_and_old_refresh_still_works`
  - `::test_end_sign_ins_refuses_old_refresh`
- **5b:** `control/tests/test_passphrase_change.py::test_change_reseals_every_sealed_value`:
  - The new passphrase unlocks, and the old one gets 401.
  - No string in the snapshot or the log opens with the old key. The test walks every string, so a sealed field added later is caught.
  - A replica ends with identical canonical bytes.
- **5b:** `agent/tests/test_passphrase_change.py::test_wrapped_key_keeps_share_password_open`.

## 6. Acceptance (CI, high risk)

**`c2-sign-in-acceptance.py`** (real Authlib, real processes, OS-picked ports):
- After a change, refresh still works and a new sign-in verifies.
- `endSignIns` refuses the old refresh token.

**`standby-acceptance.py`** (root, standby, and agent A in `passphrase_file` mode):
- After a change, sign-in through A works with the new passphrase and fails with the old.
- A restart unlocks from the rewritten file.
- Promotion takes the new passphrase only.
- Nothing in the standby's state opens with the old key.

Together these add about 5 minutes.

**The reviewer should attack:** the change route's rate limit; the passphrase in logs or problem details; the control-to-agent call sent in plain HTTP or replayed; a crash between the entry and the keyring write; a sealed field the re-seal misses; old ciphertext that survives compaction; a retired `kid` still cached; the standby's old keyring entry.

## 7. Do not change (hot for other lanes)

- control: `permissions.py`, `administration.py` (rows 37, 39); `routes/client_keys.py`, `client_admission.py` (rows 11, 24, 40).
- agent: `tokens.py`, `tray.py` (row 35).
- ui: `settingsTopics.ts` (row 33); `ConfigField.tsx`, `configValue.ts` (row 62).
- `*/scripts/codegen.py` (row 1).
- inference-driver, library and tool-driver: no edits.

## 8. Size and risks

- **Size:** 5a is S. 5b is M: about 300 lines in control, 200 in the agent and 150 in the UI.
- **Risks:**
  - The re-seal must reach every sealed value.
  - The agent's new wrap changes how its master key is derived. Every existing install starts with no wrap.

## Calls answered by Troy (2026-10-21)

- **R5-RESEAL: Choice 1.** This row re-wraps each machine's key under the new passphrase and does not re-lock each machine's secrets. Re-locking with new keys is a later row.

## What building found (2026-10-24)

Built on branch `r5-sign-in-key` in specs, control, agent and ui.

**The contract as built**
- `control.yaml`: `GET /v1/oidc/keys` (`OidcKeyList`: `keys[{kid, createdAt, signs, verifiesUntil}]`, `nextChangeAt`) and `POST /v1/oidc/keys/change {endSignIns}`; `POST /v1/auth/passphrase {current, new}` (`PassphraseChangeResult`: `changedAt`, `machines[{node, state, detail}]` with `changed`, `pending` or `plain`, and `passphraseFile`); the ops `retireOidcKeys {keep}` and `changePassphrase {salt, passphraseVerifier, sealed}`; `AuthStatus.passphraseFile`; the `Eugene-Plexus-Log-Version` header and `StandbyStatus.logVersion`.
- `agent.yaml`: `POST /v1/auth/passphrase` (the console's door), `POST /v1/node/passphrase` (the root's), `NodeIdentity.ownPassphrase`, and `AgentLoginRequest.previousPassphrase`.
- Control config: `signInKeyDays`, default 90, 0 for never, otherwise at least 31.

**What building found**
- **Every build says `Eugene-Plexus-Version: 0.1.0`.** `__version__` is never raised, so "the standby's version predates the op" cannot be read from `StandbyStatus.version`. Built: a log version (`applied.LOG_VERSION`, 1 for this row's two ops). The standby sends it on each pull, and the root reports it as `StandbyStatus.logVersion`. A standby that sends none applies version 0.
- **Row 4's review made `install_snapshot` refuse a snapshot with another salt.** A passphrase change makes a new salt, so every standby behind the change would refuse the root's snapshot forever. Changed in row 4's code (`state_machine.py`): the install is named by its identity key (`controlPublicKey`), which a change keeps. The salt is the test only for a replica that holds no identity key. So the 409 for an older standby is not only caution: a row 4 standby would refuse the new snapshot and stop.
- **The compaction keeps the change itself.** The root writes a snapshot and drops every entry before `changePassphrase`; the entry stays, because it holds only values sealed under the new key. A standby one entry behind reads it from the log and does the same; one further behind takes the snapshot. Nothing on either root opens with the old key afterwards (checked by walking every string, in the unit test and in `standby-acceptance.py`).
- **Two nets under the re-seal.** `applied.sealed_inventory` is the one list of sealed values, and `changePassphrase` applies only when `sealed` names exactly that list. Under it, the root walks every string of the state it would write and refuses the change if one still opens with the old key, naming where (a sealed field added later and never listed).
- **Where the new passphrase goes.** Only to agents that report `ownPassphrase: true`. The root reaches its own machine's agent at `agent_url` on loopback, never at its LAN address, and any other agent through the machine table's pinned TLS route, or at a loopback address (a second agent on this machine). Anything else is `plain` and gets nothing. The agent takes it only with the root's own token, over TLS or from this machine. A replay's `current` no longer verifies.
- **A machine that was off.** A sign-in its own hash refuses still goes to the root. The agent believes the root's 200 only for a session its trust bundle verifies and that names this machine, so a forged answer cannot make it take a passphrase. Unlocked, it wraps its key at once; locked, it answers 409 `old-passphrase-needed`, and the sign-in page asks once for the old passphrase.
- **The root's push does not unlock a locked agent.** The agent opens its key with `current` to wrap it, and stays locked: a change is not a sign-in.
- **The agent keeps `masterSalt`**, so its keyring entry's install id stays. `agent.yaml` is `stateVersion: 3`: the `auth` block may hold `kekSalt` and `wrappedMasterKey`. An agent older than this row would derive the wrong key from a changed passphrase; downgrading an agent after a change is not supported.
- **The root's passphrase file.** After a change the root writes it, or reports `old` when it cannot (a container secret). `AuthStatus.passphraseFile` is checked at start, every hour, and again when the mode, the path or the passphrase changes; the console's Issues list warns about `old`.
- **A crash between the entry and the keyring** leaves a marker in the root's state directory. The next start deletes the old keyring entry and logs *"The stored key no longer opens this install (the passphrase changed); sign in."*
- **The console has no control for the root token key** (`POST /v1/control/rotate-key`, ui#26). The passphrase form says that the change does not change that key, and that the console cannot change it yet.
- **The key timer** runs on every root and acts only while it is the active one. Its first check is an hour after start, so a restart loop cannot change the key twice.

**The review (Codex, 2026-10-24), and what changed for it**
- **A sealed write names its key generation.** Every entry that carries a value sealed under the master key (`putOidcKey`, `rotateSigningKey`, `setInstallCa`, `putExternalProvider`, `changePassphrase`) names the salt it was sealed under. The writer appends it only while that is the install's salt, checked under its lock. A value sealed just before a change (the reproduction: a connected account's secret, sealed before its metadata request, saved after the change) is refused with 409, *"The passphrase changed while this was saved; save it again."*, and never stored. `AuthState` keeps the key with its salt and hands them out together (`sealing_key`). The provider write, the token key rotation, the install CA, the first sign-in key and the key change use it; the first sign-in key and the install CA are made again under the key in effect, because no person saved them.
- **The new key is in effect as soon as the change entry is durable.** The snapshot and the compaction come after it (`StateMachine.compact_pending`). When they fail (the reproduction: a full disk), the answer is still 200, `PassphraseChangeResult.cleanup` names the cause, and the root tries again every hour, a standby at every pull, and every root at its next start.
- **Restart-safe cleanup.** At start, a root whose log still holds entries before its last `changePassphrase` (or whose snapshot predates it) compacts first. A standby notes the keyring entry a change makes stale before it takes the change (an entry or a snapshot); `finish_interrupted` deletes it at the next start after a kill.
- **Two key changes at once are one.** The age check and the change hold one lock, so the second waits, sees the key the first made, and a routine one is refused as too soon.
- **A machine that could not save its passphrase file says so.** `POST /v1/node/passphrase` answers 200 with `NodePassphraseResult` (the file's state, and why it is `old`). The root reports the machine as `changed` with *this machine could not save its passphrase file: <cause>*, and People shows it.
- **The leak text promises less.** Workbench asks people to sign in again within five minutes (its JWKS cache); Open WebUI keeps its sessions until they expire or people sign out.
- Not this row: the standby's snapshot is not authenticated over plain HTTP (control#11, inherited).

**Acceptance.** `c2-sign-in-acceptance.py` checks 80 to 88: the harness starts its own control process, so it moves only the key schedule's clock (`oidc_keys.now`, by the days in `key-clock-days`), and every token keeps the real clock. `standby-acceptance.py` step 5b: A (on the root's machine) keeps its passphrase in a file that the root also unlocks from; the change goes through A's console door; A and B take it; the old passphrase is refused at both; nothing in the root's or the standby's state opens with the old master key; A and the root, restarted, unlock from the rewritten file; step 7 then refuses to promote with the old passphrase. Sabotage: `scripts/row5-sabotage.py`, cases across control, agent and ui, each caught by its named test (run on Windows, 2026-10-24).
