# Row 46: a limit on frozen trust

Lane TRUST, after row 3. **High risk** (token checks).
Sources: TOK-RES in `per-node-token-keys.md` §"Residual risks" ("Freeze. A
node cut off from the root keeps its last bundle. The age is reported, not
enforced (D3)"), agent `trust.py`, control `tokens.py`.

The row first also wrapped each machine's keys with a key its OS or TPM
holds (46a). Troy's answer to R46-SCOPE (2026-10-22) removed that part: a
system must always restore to a fresh machine, and keys bound to one
machine make a backup useless there. Machine keys stay restorable from a
backup, protected by file permissions as today, and the recovery
checkpoints (`scripts/recovery.py`) stay encrypted with the unlock
passphrase, which restores on any machine. TPM-resident keys are not on
the roadmap for the same reason.

## 1. What it delivers

- **A machine cut off from the root stops taking changes from other
  machines after a day.** Today it trusts its last trust list forever, so
  someone who blocks it from the root keeps a revoked machine's key
  working there. Inference keeps working (the root being down must never
  stop answers); starting, stopping and configuring from other machines
  is refused there until it hears from the root again, and it says so.

## 2. Design

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

The agent setting `maxTrustBundleAgeHours` and the 403 problem text. No
control change.

## 3. Repositories and files

specs (`agent.yaml`), agent (`trust.py`, `dependencies.py`), ui (Home's
warning, the setting). Regenerate agent and ui and diff.

## 4. Tests that fail before

- agent `test_trust.py::test_a_stale_bundle_refuses_another_machines_mutation`
  and `test_inference_and_the_roots_tokens_still_pass`.

## 5. Acceptance (CI, Linux and Windows, about 3 minutes)

`specs/scripts/row46-frozen-trust-acceptance.py` on row 2's harness:
1. The root is stopped and the limit set to 60 s: after it, another
   machine's stop request is refused with the age; an inference request
   through the gateway still answers; the root returns, a bundle arrives,
   and the stop succeeds.
2. **Sabotage:** skip the age check; step 1 must fail.

**The reviewer should attack:** which tokens the frozen limit lets through
(a forged "own" token, a root-signed token replayed), the clock the age
uses (a clock moved back), and a bundle that arrives but fails to verify.

## 6. Do not change

- `machine_key_change.py` and row 3's door file.
- control's `keyring_store.py` and the master key (row 5 changes sealing).
- Token algorithms (Ed25519 stays).

## 7. Size and risks

S-M, about 1 day. One adversarial review.
Risk: **the freeze limit can refuse a real change** from the console on a
machine whose network to the root is broken; the 403 and Home both name
the cause, and the limit is a setting.

## Calls answered by Troy (2026-10-22)

- **R46-FREEZE: Choice 1.** After 24 hours without the root, a machine
  refuses changes from other machines' keys; answers keep working.
- **R46-SCOPE: neither choice.** "A system MUST be able to be restored to
  a fresh machine. We can not make backups useless." Keys are not bound
  to one machine's OS or TPM; 46a is removed and the row is the freeze
  limit only.
