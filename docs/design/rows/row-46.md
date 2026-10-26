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

## What building found (2026-10-26)

- **A pushed copy of the held bundle reset the age.** The push door
  (`POST /v1/node/trust-bundle`) takes no bearer: the signature is the
  credential. So anybody who can reach a machine, a removed machine
  included, could post the last bundle every hour and the limit would
  never come. Built: a bundle the machine pulled from the root at its own
  address is word now; a pushed bundle counts only when it is newer than
  the one held, and only from the time the root signed it. A bundle that
  does not verify changes nothing.
- **The clock.** The age is the longer of the wall clock's count and the
  process's own (`perf_counter`), so a clock set back does not shorten
  it while the agent runs, and a suspended Linux machine still counts
  the time it slept. A pull after a clock set back still counts as word.
  Left: across a restart the age comes from the kept file's time on the
  wall clock, so a clock set back before a restart shortens it. Moving
  this machine's clock needs this machine.
- **Which tokens are another machine's.** Any token whose `iss` is not
  `control` and not this machine. `verify` binds `iss` to the key that
  signed it, so a third key cannot claim to be the root or this machine.
  Today only two kinds of another machine's token reach a change route:
  a gateway with the `gateway` grant (runtime start and stop), and the
  Library machine's agent on `POST /v1/ollama/send` (Keep). The other
  routes in §2 (declare, PATCH, components, config, engines) take only
  the root's tokens or an operator session, which the root signs. They
  are listed as changes too, so a route that starts to take another
  machine's token is covered from its first day.
- **Classification.** `dependencies.FROZEN_TRUST_CHANGES` and
  `FROZEN_TRUST_QUESTIONS` name every agent route on a method other than
  GET, HEAD and OPTIONS (75 changes, 11 questions). A route in neither is
  refused as a change, and `test_trust.py` fails until it is named. The
  questions are the admission dry run and client-key admission (on an
  answer's path), and the preflights, previews and checks.
- **A stopped model is not woken from another machine** while the limit
  is passed (start is a change). A running model keeps answering.
- **The root's sessions pass by design**, so a session signed out at the
  root after the machine lost it still works there until it expires.
- **A client key needs the root anyway.** Client-key admission is relayed
  to the root and never allowed locally during an outage (A5), so with
  the root dead an app's key is refused at the gateway whatever this
  limit says. Operator sessions and the machine's own tokens answer. The
  acceptance's prompt uses a session.
- **The acceptance** sets the limit to 1 hour and the kept bundle's time
  back 2 hours, then restarts the agent with the root stopped. The
  setting is in whole hours, so a 60 s limit is not possible.
- **Mixed versions.** `NodeIdentity` gains two optional fields
  (`trustBundleMaxAgeSeconds`, `trustBundleFrozen`). The root reads
  `GET /v1/node` as a plain mapping and the push answer is not parsed,
  so no root needs deploying first. No request any machine sends
  changes. An older agent has no limit; an older UI shows no second line.

## Calls answered by Troy (2026-10-22)

- **R46-FREEZE: Choice 1.** After 24 hours without the root, a machine
  refuses changes from other machines' keys; answers keep working.
- **R46-SCOPE: neither choice.** "A system MUST be able to be restored to
  a fresh machine. We can not make backups useless." Keys are not bound
  to one machine's OS or TPM; 46a is removed and the row is the freeze
  limit only.
