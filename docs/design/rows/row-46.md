# Row 46: node keys a copied file cannot give away, and a limit on frozen trust

Lane TRUST, after row 3. **High risk** (key custody, token checks).
Sources: TOK-RES in `per-node-token-keys.md` §"Residual risks" ("Node keys
can be exported. A TPM or DPAPI-backed non-exportable key would stop the
file leak outright. Recorded, not built." and "Freeze. A node cut off from
the root keeps its last bundle. The age is reported, not enforced (D3)"),
agent `node_identity.py`, `_private_files.py`, `trust.py`, `machine_port.py`,
`client_tls.py`, control `tokens.py`.

## 1. What it delivers

- **A copy of a machine's key file is useless elsewhere.** Today
  `node.yaml` holds the machine's four private keys in the clear (mode
  0600, or the install's ACL on Windows), and its TLS key is copied to
  three more files. A backup, a disk image or another account that can
  read the file gets the machine. After this row the keys on disk are
  wrapped by a key this machine's OS or TPM holds, and the TLS key is on
  disk only for the moment it is loaded.
- **A machine cut off from the root stops taking changes from other
  machines after a day.** Today it trusts its last trust list forever, so
  someone who blocks it from the root keeps a revoked machine's key
  working there. Inference keeps working (the root being down must never
  stop answers); starting, stopping and configuring from other machines
  is refused there until it hears from the root again, and it says so.

## 2. Design

### Wrapping the keys at rest (agent)

- **One wrapping key per machine** (32 random bytes), held by the OS:

  | Platform | Holder | Who can unwrap |
  |---|---|---|
  | Windows | DPAPI, user scope of the account the agent runs as (`CryptProtectData`, no UI) | that account on this machine |
  | Linux system install | a systemd credential the installer makes (`systemd-creds encrypt --with-key=auto`: the TPM 2.0 when present, else the host key), loaded by the unit's `LoadCredentialEncrypted=` into the service's private tmpfs | the service, on this machine (and, with a TPM, this board) |
  | Linux `--user`, macOS, containers | none yet | (the file stays as today) |

- **What is wrapped:** the private keys in `node.yaml` (`privateKey`,
  `signingPrivateKey`, `tokenPrivateKey`, `tlsPrivateKey`,
  `tlsNextPrivateKey`) become one field, `wrappedKeys`, AES-256-GCM under
  the wrapping key with the node name as associated data. Public keys
  stay readable.
- **Migration:** at the first start with a holder, the agent wraps the
  clear keys, writes the new file atomically, and keeps nothing in the
  clear; a failure leaves the old file untouched and says why. With no
  holder, nothing changes.
- **The TLS key's copies** (`machine_tls.pem`, `client_tls.key`): Python's
  TLS loads a key only from a file, so the agent writes it into a
  private temporary file (the service's runtime tmpfs on Linux, a 0600 /
  owner-only file in its data folder on Windows), loads it, and deletes it
  at once. Nothing else keeps a copy.
- **Reported:** `Node.keyProtection` {method: `dpapi` | `tpm` |
  `host-key` | `none`, detail}. Machines shows "Keys: held by this
  machine's TPM" / "… by Windows for the Eugene account" / "stored in the
  clear on this machine (no OS key store here yet)".
- **Backups and restores:** a restored `node.yaml` on another machine
  cannot be unwrapped; the agent says "This machine's keys were wrapped on
  another machine. Re-enroll it." (the same path as a lost identity).
  Recovery scripts (`scripts/recovery.py`) treat `wrappedKeys` as opaque.

**Not in this row:** keys that never leave a TPM (they would need P-256
for tokens and sealing in place of Ed25519 and X25519, a contract change
on every machine) and macOS Keychain wrapping for the daemon from row 8.
Both are named in the doc as the next step. Call R46-SCOPE.

### A limit on frozen trust (agent, `trust.py`)

- **The age** is `trustBundleAgeSeconds`, already reported (time since
  this machine last took a bundle).
- **The limit:** `maxTrustBundleAgeHours`, default 24, 0 for none (expert,
  in the agent's settings). Past it, the agent refuses tokens minted by
  **another machine's** key for mutating routes (runtime start, stop,
  declare and PATCH; component writes; config PATCH; engine installs) with
  403: "This machine has not heard from the root for 31 hours, so it takes
  no changes from other machines. Check its network to the root."
- **Still accepted past the limit:** tokens of the root's key (they are
  checked against the same old bundle, and the root is the authority),
  this machine's own tokens for its children, and every inference and
  read route, so a dead root never stops answers (M5).
- Home's existing stale-bundle warning (600 s) gains the second line once
  the limit is passed: "Changes from other machines are refused here."

### Contract (`agent.yaml`)

`Node.keyProtection`, the agent setting `maxTrustBundleAgeHours`, and the
403 problem text. No control change.

## 3. Repositories and files

specs (`agent.yaml`, `scripts/install.sh` for the systemd credential and
unit line, `scripts/recovery.py`), agent (`node_identity.py`,
`_private_files.py`, a new `key_wrap.py`, `machine_port.py`,
`client_tls.py`, `trust.py`, `dependencies.py`), ui (Machines, Home's
warning). Regenerate agent and ui and diff.

## 4. Tests that fail before

- agent `test_key_wrap.py::test_node_yaml_holds_no_clear_private_key_after_migration`
  (with a fake holder), `test_a_file_from_another_machine_says_re_enroll`,
  `test_no_holder_leaves_the_file_as_it_was`.
- agent `test_key_wrap.py::test_dpapi_round_trip` (Windows only, real DPAPI).
- agent `test_client_tls.py::test_the_tls_key_file_is_gone_after_loading`.
- agent `test_trust.py::test_a_stale_bundle_refuses_another_machines_mutation`
  and `test_inference_and_the_roots_tokens_still_pass`.

## 5. Acceptance (CI, Linux and Windows, about 4 minutes)

`specs/scripts/row46-key-custody-acceptance.py` on row 2's harness:
1. **Windows:** an enrolled agent's `node.yaml` holds `wrappedKeys` and no
   private key; the machine port and client doors serve TLS; no `.pem` key
   file remains in the data folder. The file copied into a second data
   folder under another account fails with the re-enroll message.
2. **Linux:** the same with a systemd credential made by the test as the
   installer would (`systemd-creds` on the runner, host key: no TPM).
3. **Frozen trust:** the root is stopped and the limit set to 60 s: after
   it, another machine's stop request is refused with the age; an
   inference request through the gateway still answers; the root returns,
   a bundle arrives, and the stop succeeds.
4. **Sabotage:** skip the wrap on migration; step 1 must fail.

**The reviewer should attack:** a clear key left anywhere (old file,
temporary file, logs, crash dumps, the migration's failure path), the
associated data and nonce handling, the Linux credential's permissions,
which tokens the frozen limit lets through (a forged "own" token, a
root-signed token replayed), and recovery after a board swap.

## 6. Do not change

- `machine_key_change.py` and row 3's door file (call into them).
- control's `keyring_store.py` and the master key (row 5 changes sealing).
- Token algorithms (Ed25519 stays).

## 7. Size and risks

L (the roadmap said M), about 3 days. One adversarial review.
Risks:
- **A machine that cannot unwrap its keys is a machine to re-enroll.**
  DPAPI user scope survives Windows password changes for service accounts
  but not a rebuilt account; a TPM-bound credential does not survive a
  board swap. The message says what to do, and enrollment keeps model
  files and runtimes.
- **The freeze limit can refuse a real change** from the console on a
  machine whose network to the root is broken; the 403 and Home both name
  the cause, and the limit is a setting.

**Calls:** R46-SCOPE (wrap at rest now; TPM-resident keys later) and
R46-FREEZE (24 hours, mutations from other machines only).

## Calls answered by Troy (2026-10-22)

- **R46-FREEZE: Choice 1.** After 24 hours without the root, a machine
  refuses changes from other machines' keys; answers keep working.
- **R46-SCOPE: open.** Troy asked which modern machines lack a TPM and
  leans to Choice 2 (TPM-resident keys); the answer is in calls.md. Until
  it is decided, build 46b (the freeze limit) first; 46a waits.
